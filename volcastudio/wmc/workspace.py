"""Browser App workflows over the shared VolcaStudio XL backend, without HTTP or GUI code.

Every musical operation calls the same functions as the Desktop App:
``tuning`` (varispeed, pitch, alignment), ``outie_model`` (ordered kits),
``kits`` (archive/restore), ``transfer`` (SYRO), ``patterns``/``grooves``/
``pattern_transfer``/``pattern_device`` and ``firmware``. This module only
validates browser input, keeps a persistent draft and maps paths to the
application's own storage. It never accepts an arbitrary path from the
browser: sample paths must resolve inside a known library or Studio folder.
"""
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .. import desktop_audio
from ..config import Config
from ..outie_model import save_ordered_kit, parse_slots, predictability_summary
from ..patterns import PATTERN_PROFILE
from ..transfer import (MAX_SAMPLES, MAX_SECONDS, SAMPLE_RATE, checked, device_lock,
                        inspect_wav, normalize_sample, pack_files)

NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
LIBRARY_NAME = re.compile(r'[a-z0-9][a-z0-9_-]{0,47}\Z')
MAX_SIDECAR = 64 * 1024
MAX_KIT_ZIP = 2 * 1024 ** 3
PREVIEW_PITCHES = (0, -12, -24)


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, pending = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def safe_component(text):
    """A single file or folder name from the browser, never a path."""
    text = re.sub(r'[\x00-\x1f\x7f<>:"|?*\\/]', '_', str(text)).strip().strip('.')
    if not text or text in ('.', '..'):
        raise ValueError('Invalid file or folder name')
    return text[:120]


def library_slug(text):
    slug = re.sub(r'[^a-z0-9_-]+', '-', str(text).lower()).strip('-_')[:40]
    return slug or 'samples'


def within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class Workspace:
    def __init__(self, config=None):
        self.config = config or Config.read()
        self.config.initialize()
        self.root = self.config.data / 'wmc'
        self.state_dir = self.config.state / 'wmc'
        self.cache_dir = self.config.cache / 'wmc'
        for path in (self.root / 'libraries', self.state_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.draft_generation = 0
        self.bank = None
        self.bank_label = None
        self.bank_path = None
        self.bank_neutral = False
        self.saved_groove = None
        self.saved_kit = None
        self._catalog = None
        self._draft = self._read_draft()
        from .exports import PreparedExports
        self.exports = PreparedExports(self.cache_dir)

    # ------------------------------------------------------------------ settings
    @property
    def settings_path(self):
        return self.state_dir / 'settings.json'

    def settings(self):
        try:
            value = json.loads(self.settings_path.read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def update_settings(self, **changes):
        with self.lock:
            value = self.settings()
            for key, item in changes.items():
                if item is None:
                    value.pop(key, None)
                else:
                    value[key] = item
            atomic_json(self.settings_path, value)
            return value

    # ----------------------------------------------------------------- libraries
    def registered(self):
        """Use the same last-record-wins registrations as the other editions."""
        from .library_actions import registrations
        return [(entry['name'], Path(entry['root'])) for entry in registrations(self.config)
                if entry['available']]

    def library_table(self):
        table = []
        def add(ident, title, path, kind, removable=False):
            if path.is_dir():
                table.append({'id': ident, 'title': title, 'root': path.resolve(), 'kind': kind,
                              'removable': removable})
        wmc = self.root / 'libraries'
        # The Browser App's own copies only: a symlink here is never listed, written or removed.
        for path in sorted(p for p in wmc.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith('.')):
            add('wmc:' + path.name, path.name, path, 'wmc', True)
        for name, path in self.registered():
            add('reg:' + name, name, path, 'shared')
        add('kits', 'Saved kits', self.config.kits, 'kits')
        if self.config.sources_dir.resolve() != self.config.kits.resolve():
            add('packs', 'Existing packs', self.config.sources_dir, 'packs')
        add('variants', 'Varispeed variants', self.config.data / 'variants', 'variants')
        return table

    def allowed_roots(self):
        return [entry['root'] for entry in self.library_table()]

    def libraries(self):
        result = []
        for entry in self.library_table():
            result.append({k: (str(v) if isinstance(v, Path) else v) for k, v in entry.items()})
        return result

    def library(self, ident):
        for entry in self.library_table():
            if entry['id'] == ident:
                return entry
        raise ValueError('This library is not available. Refresh the library list.')

    def library_samples(self, ident, query='', offset=0, limit=250):
        if (not isinstance(query, str) or len(query) > 500 or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 1000):
            raise ValueError('Invalid library search or page.')
        entries = self.library_table() if ident == '*' else [self.library(ident)]
        words = query.casefold().split()
        rows = []
        seen, total = set(), 0
        for entry in entries:
            root = entry['root']
            for path in self._walk_wavs(root):
                rel = path.relative_to(root)
                group = rel.parent.as_posix()
                text = f'{entry["title"]}/{rel}'.casefold()
                if not all(word in text for word in words):
                    continue
                try:
                    resolved = path.resolve()
                    if not within(resolved, root) or resolved in seen:
                        continue
                    size = resolved.stat().st_size
                except OSError:
                    continue
                seen.add(resolved)
                if offset <= total < offset + limit:
                    rows.append({'path': str(resolved), 'name': path.name,
                                 'group': (entry['title'] + '/' if ident == '*' else '') +
                                          ('' if group == '.' else group), 'size': size})
                total += 1
        return {'samples': rows, 'total': total, 'offset': offset, 'limit': limit,
                'has_more': offset + len(rows) < total, 'truncated': False}

    @staticmethod
    def _walk_wavs(root):
        for directory, folders, files in os.walk(root, followlinks=False):
            folders[:] = sorted(f for f in folders if not f.startswith('.'))
            for name in sorted(files, key=str.lower):
                if name.lower().endswith('.wav') and not name.startswith('.'):
                    yield Path(directory) / name

    def resolve_sample(self, value):
        """Accept only existing WAVs inside known libraries or Studio storage."""
        if not isinstance(value, str) or not value or '\x00' in value:
            raise ValueError('Choose a sample from a library.')
        path = Path(value)
        if not path.is_absolute():
            raise ValueError('Choose a sample from a library.')
        resolved = path.resolve()
        if resolved.suffix.lower() != '.wav' or not resolved.is_file():
            raise ValueError(f'Sample not found: {path.name}')
        if not any(within(resolved, root) for root in self.allowed_roots()):
            raise ValueError('This file is outside Browser App libraries and saved kits.')
        return resolved

    def import_file(self, library, relpath, source, length):
        """Copy one uploaded WAV (or its JSON sidecar) into a Browser App library.

        Uploaded bytes are stored unchanged. A different existing file is never
        replaced; identical content is reused. Originals on the user's disk are
        untouched because the browser only provides a copy.
        """
        if not LIBRARY_NAME.fullmatch(library or ''):
            raise ValueError('Library names use lowercase letters, digits, - and _.')
        raw = [p for p in str(relpath).replace('\\', '/').split('/') if p not in ('', '.')]
        if not raw or len(raw) > 12 or any(p.startswith('.') for p in raw):
            raise ValueError('Hidden files and folders are not imported.')
        parts = [safe_component(p) for p in raw]
        suffix = Path(parts[-1]).suffix.lower()
        if suffix not in ('.wav', '.json'):
            raise ValueError('Only WAV samples and their JSON sidecars are imported.')
        if suffix == '.json' and length > MAX_SIDECAR:
            raise ValueError('Sidecar metadata is too large.')
        unresolved = self.root / 'libraries' / library
        if unresolved.is_symlink() or any((unresolved.joinpath(*parts[:n])).is_symlink() for n in range(1, len(parts) + 1)):
            raise ValueError('The Browser App writes only into its own library folders, never through links.')
        base = unresolved.resolve()
        destination = base.joinpath(*parts)
        if not within(destination.resolve(), base):
            raise ValueError('Invalid file location in the chosen folder.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        fd, pending = tempfile.mkstemp(prefix='.upload-', dir=destination.parent)
        pending = Path(pending)
        try:
            remaining = length
            with os.fdopen(fd, 'wb') as stream:
                while remaining > 0:
                    chunk = source.read(min(1 << 20, remaining))
                    if not chunk:
                        raise ValueError('The upload ended early; nothing was saved.')
                    stream.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if suffix == '.wav':
                try:
                    inspect_wav(pending)
                except ValueError:
                    raise ValueError(f'{parts[-1]} is not a supported PCM/float WAV file.') from None
            else:
                try:
                    value = json.loads(pending.read_text(encoding='utf-8'))
                except (ValueError, UnicodeDecodeError):
                    raise ValueError(f'{parts[-1]} is not valid JSON metadata.') from None
                if not isinstance(value, dict):
                    raise ValueError(f'{parts[-1]} is not sample metadata.')
            final = destination
            counter = 2
            while True:
                if final.exists():
                    if final.is_file() and hashlib.sha256(final.read_bytes()).hexdigest() == digest.hexdigest():
                        return {'path': str(final), 'reused': True}
                    final = destination.with_name(f'{destination.stem} ({counter}){destination.suffix}')
                    counter += 1
                    continue
                try:
                    os.link(pending, final)
                except FileExistsError:
                    continue
                except OSError:
                    shutil.copyfile(pending, final)
                return {'path': str(final), 'reused': False}
        finally:
            pending.unlink(missing_ok=True)

    def remove_library(self, ident):
        entry = self.library(ident)
        if entry['kind'] != 'wmc':
            raise ValueError('Only libraries imported into the Browser App can be removed here. Shared libraries stay registered.')
        with self.lock:
            used = [p for p in self._draft['paths'] if within(Path(p), entry['root'])]
            if used:
                raise ValueError('Remove these samples from the workbench first; the draft still uses them.')
            folder = self.root / 'libraries' / entry['title']
            if folder.is_symlink() or not folder.is_dir() or folder.resolve() != entry['root']:
                raise ValueError('Only a folder created by the Browser App can be removed here.')
            shutil.rmtree(folder)
        return {'removed': entry['title']}

    # --------------------------------------------------------------------- draft
    @property
    def draft_path(self):
        return self.state_dir / 'draft.json'

    def _read_draft(self):
        try:
            value = json.loads(self.draft_path.read_text(encoding='utf-8'))
            paths = [p for p in value.get('paths', []) if isinstance(p, str)]
            edit = value.get('edit') if isinstance(value.get('edit'), dict) else None
            return {'paths': paths[:MAX_SAMPLES * 2], 'edit': edit, 'name': str(value.get('name', ''))[:64]}
        except (OSError, ValueError, AttributeError):
            return {'paths': [], 'edit': None, 'name': ''}

    def _write_draft(self):
        self.draft_generation += 1
        self.saved_kit = None
        atomic_json(self.draft_path, dict(self._draft, schema=1, updated_at=utc()))

    def draft(self):
        from ..tuning import tuning_metadata
        from ..kits import awards
        with self.lock:
            paths = list(self._draft['paths'])
            edit = self._draft['edit']
            name = self._draft['name']
        rows, total, missing = [], 0.0, 0
        for slot, value in enumerate(paths):
            row = {'slot': slot, 'path': value, 'name': Path(value).name}
            try:
                path = self.resolve_sample(value)
                seconds = inspect_wav(path)
                meta = tuning_metadata(path)
                row.update(seconds=seconds, label=meta['label'], semitones=meta['semitones'],
                           factor=meta['factor'], uncertain=bool(meta.get('history_uncertain')),
                           original=meta.get('original_name', Path(meta['source']).name))
                total += seconds
            except (ValueError, OSError) as exc:
                row.update(error=str(exc), seconds=0)
                missing += 1
            rows.append(row)
        count = len(rows)
        within_budget = 1 <= count <= MAX_SAMPLES and total <= MAX_SECONDS and not missing
        try:
            reached = awards(count, total) if within_budget else []
        except ValueError:
            reached = []
        return {'rows': rows, 'count': count, 'seconds': total, 'max_samples': MAX_SAMPLES,
                'max_seconds': MAX_SECONDS, 'over_budget': count > MAX_SAMPLES or total > MAX_SECONDS,
                'missing': missing, 'edit': edit, 'name': name, 'generation': self.draft_generation,
                'awards': reached, 'saved_kit': str(self.saved_kit) if self.saved_kit else None}

    def set_draft(self, paths, name=None, generation=None):
        if not isinstance(paths, list) or len(paths) > MAX_SAMPLES * 2:
            raise ValueError('The workbench holds up to 200 entries while you edit; a kit holds 100.')
        resolved = [str(self.resolve_sample(p)) for p in paths]
        with self.lock:
            if generation is not None and generation != self.draft_generation:
                raise ValueError('The workbench changed in the meantime; review it and try again.')
            self._draft['paths'] = resolved
            if name is not None:
                self._draft['name'] = str(name)[:64]
            self._write_draft()
        return self.draft()

    def add_to_draft(self, paths):
        with self.lock:
            return self.set_draft(self._draft['paths'] + list(paths))

    def clear_draft(self):
        with self.lock:
            self._draft = {'paths': [], 'edit': None, 'name': ''}
            self._write_draft()
        return self.draft()

    def draft_snapshot(self):
        with self.lock:
            return tuple(self._draft['paths']), self.draft_generation

    def replace_draft_paths(self, generation, paths):
        with self.lock:
            if generation != self.draft_generation:
                raise ValueError('The workbench changed while working; your previous draft was kept.')
            self._draft['paths'] = [str(Path(p)) for p in paths]
            self._write_draft()
        return self.draft()

    def selected_indices(self, indices, paths):
        if not isinstance(indices, list) or not indices:
            raise ValueError('Select one or more samples first.')
        if any(type(i) is not int or not 0 <= i < len(paths) for i in indices) or len(set(indices)) != len(indices):
            raise ValueError('The selection no longer matches the workbench.')
        return sorted(indices)

    # ------------------------------------------------------------- sample tools
    def sample_info(self, value):
        from ..audio import detect_pitch, note
        from ..tuning import tuning_metadata, filename_pitch
        path = self.resolve_sample(value)
        seconds = inspect_wav(path)
        meta = tuning_metadata(path)
        pitch = detect_pitch(path, self.config.cache / 'pitch')
        stream = json.loads(checked(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=sample_rate,channels,bits_per_sample,codec_name', '-of', 'json', path],
            capture_output=True, text=True).stdout)['streams'][0]
        audio_format = {'sample_rate': int(stream['sample_rate']), 'channels': int(stream['channels']),
                        'bits': int(stream.get('bits_per_sample', 0)), 'codec': stream['codec_name']}
        named = None if meta.get('history_uncertain') else filename_pitch(meta.get('original_name', path.name))
        speed = {}
        if pitch.get('midi') is not None:
            speed = {'minus12': note(pitch['midi'] - 12), 'minus24': note(pitch['midi'] - 24)}
        return {'path': str(path), 'name': path.name, 'seconds': seconds, 'bytes': path.stat().st_size,
                'label': meta['label'], 'semitones': meta['semitones'], 'factor': meta['factor'],
                'original': meta.get('original_name', Path(meta['source']).name),
                'uncertain': bool(meta.get('history_uncertain')), 'pitch': pitch,
                'filename_note': named['note'] if named else None, 'at_speed': speed,
                'volca_seconds': seconds, 'memory_percent': seconds / MAX_SECONDS * 100,
                'format': audio_format}

    def preview(self, value, pitch, mode='volca'):
        """Audition copy for the browser: the Volca's 31.25 kHz mono snapshot
        at SPEED 0/−12/−24, rendered with the same chain as the Desktop App's preview."""
        from ..audio import identity
        if pitch not in PREVIEW_PITCHES:
            raise ValueError('Preview pitch must be 0, −12 or −24.')
        if mode not in ('volca', 'source'):
            raise ValueError('Choose Source or Volca preview.')
        path = self.resolve_sample(value)
        if mode == 'source' and pitch == 0:
            return path
        _, signature = identity(path)
        key = hashlib.sha256(f'{signature}:{pitch}:{mode}:wmc-preview-v2'.encode()).hexdigest()
        target = self.cache_dir / 'preview' / (key + '.wav')
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.preview-', dir=target.parent) as tmp:
            snapshot = Path(tmp) / 'snapshot.wav'
            if mode == 'volca':
                normalize_sample(path, snapshot)
                rate = SAMPLE_RATE
            else:
                checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', path,
                         '-c:a', 'pcm_s16le', snapshot])
                import wave
                with wave.open(str(snapshot), 'rb') as stream:
                    rate = stream.getframerate()
            rendered = Path(tmp) / 'preview.wav'
            checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', snapshot, '-af',
                     f'asetrate={rate * 2 ** (pitch / 12)},aresample={44100 if mode == "volca" else rate}',
                     '-c:a', 'pcm_s16le', rendered])
            os.replace(rendered, target)
        return target

    def varispeed_operation(self, indices, semitones):
        from ..tuning import semitone_value
        semitone_value(semitones)
        if semitones == 0:
            raise ValueError('Zero leaves the audio unchanged; enter 1–99 semitones.')
        paths, generation = self.draft_snapshot()
        selected = self.selected_indices(indices, paths)
        sources = [self.resolve_sample(p) for p in paths]
        variants = self.config.data / 'variants/varispeed'

        def operation(job):
            from ..tuning import varispeed
            replacements = list(sources)
            for count, index in enumerate(selected, 1):
                job.progress(f'Varispeed {count}/{len(selected)}', count - 1, len(selected))
                desktop_audio.check_cancelled()
                replacements[index] = varispeed(sources[index], semitones, variants)
            return [str(p) for p in replacements]

        def apply(result):
            draft = self.replace_draft_paths(generation, result)
            return {'draft': draft, 'selected': selected, 'semitones': semitones}
        return operation, apply

    def variants_operation(self, values, semitones, replace_existing=False):
        """Add variants without replacing their originals (library J/K and ×2)."""
        from ..tuning import semitone_value
        semitone_value(semitones)
        if type(replace_existing) is not bool:
            raise ValueError('Choose whether existing workbench entries are replaced.')
        if semitones == 0:
            raise ValueError('Enter a nonzero transposition.')
        if not isinstance(values, list) or not 1 <= len(values) <= MAX_SAMPLES:
            raise ValueError('Choose 1–100 samples for variants.')
        sources = [self.resolve_sample(p) for p in values]
        before, generation = self.draft_snapshot()

        def operation(job):
            from ..tuning import varispeed
            rendered = []
            for count, path in enumerate(sources, 1):
                desktop_audio.check_cancelled()
                job.progress(f'Creating variant {count}/{len(sources)}', count - 1, len(sources))
                rendered.append(varispeed(path, semitones, self.config.data / 'variants/varispeed'))
            return rendered

        def apply(result):
            replacements = list(before)
            indices = []
            for source, path in zip(sources, result):
                value = str(path)
                old = [i for i, item in enumerate(before) if item == str(source)] if replace_existing else []
                if old:
                    for index in old:
                        replacements[index] = value
                    indices.extend(old)
                else:
                    if value not in replacements:
                        replacements.append(value)
                    indices.append(replacements.index(value))
            if len(replacements) > MAX_SAMPLES * 2:
                raise ValueError('The workbench holds up to 200 entries while editing.')
            return {'draft': self.replace_draft_paths(generation, replacements),
                    'selected': indices, 'semitones': semitones}
        return operation, apply

    # ------------------------------------------------------------ key alignment
    def align_sources(self):
        paths, generation = self.draft_snapshot()
        if not paths:
            raise ValueError('Add samples to the workbench, then choose a master and slaves.')
        if len(paths) > MAX_SAMPLES:
            raise ValueError('Key alignment works on a kit of up to 100 samples.')
        return [self.resolve_sample(p) for p in paths], generation

    def analysis_operation(self):
        sources, generation = self.align_sources()
        cache = self.config.cache / 'pitch'

        def operation(job):
            from ..tuning import sample_tuning
            rows = []
            for count, path in enumerate(sources, 1):
                job.progress(f'Listening to sample {count}/{len(sources)}', count - 1, len(sources))
                desktop_audio.check_cancelled()
                rows.append(sample_tuning(path, cache))
            return {'rows': rows, 'generation': generation}
        return operation

    @staticmethod
    def _align_inputs(request, count):
        master = request.get('master')
        slaves = request.get('slaves', [])
        choices = request.get('choices', {}) or {}
        overrides = request.get('overrides', {}) or {}
        if not isinstance(slaves, list) or not isinstance(choices, dict) or not isinstance(overrides, dict):
            raise ValueError('Invalid alignment proposal.')
        def index(key):
            try:
                value = int(key)
            except (TypeError, ValueError):
                raise ValueError('Invalid alignment proposal.') from None
            if not 0 <= value < count:
                raise ValueError('Invalid alignment proposal.')
            return value
        choices = {index(k): v for k, v in choices.items() if v}
        overrides = {index(k): v for k, v in overrides.items()}
        if any(type(v) is not int for v in overrides.values()):
            raise ValueError('Manual shifts must be whole semitones.')
        return master, slaves, choices, overrides

    def align_plan(self, request):
        from ..tuning import alignment_plan
        sources, generation = self.align_sources()
        if request.get('generation') not in (None, generation):
            raise ValueError('The workbench changed; analyse it again.')
        master, slaves, choices, overrides = self._align_inputs(request, len(sources))
        plan = alignment_plan(sources, master, slaves, choices, overrides, self.config.cache / 'pitch')
        plan['generation'] = generation
        return plan

    def align_apply_operation(self, request):
        from ..tuning import alignment_plan, apply_alignment
        sources, generation = self.align_sources()
        if request.get('generation') != generation:
            raise ValueError('The workbench changed; analyse it again before accepting.')
        master, slaves, choices, overrides = self._align_inputs(request, len(sources))
        variants = self.config.data / 'variants/varispeed'
        cache = self.config.cache / 'pitch'

        def operation(job):
            # Recompute on the helper: the browser's copy is only a display.
            plan = alignment_plan(sources, master, slaves, choices, overrides, cache)
            if not plan['ready'] or plan['over_budget']:
                raise ValueError('The proposal is not ready: resolve conflicts and fit 65 seconds first.')
            job.progress('Rendering the accepted proposal', 0, 1)
            return [str(p) for p in apply_alignment(plan, variants)]

        def apply(result):
            return {'draft': self.replace_draft_paths(generation, result)}
        return operation, apply

    # ---------------------------------------------------------------------- kits
    def kit_dirs(self):
        result = []
        for kind, base in (('studio', self.config.kits), ('pack', self.config.sources_dir)):
            if kind == 'pack' and base.resolve() == self.config.kits.resolve():
                continue
            if not base.is_dir():
                continue
            for path in sorted((p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')),
                               key=lambda p: p.name.lower()):
                result.append((kind, path))
        return result

    def kits(self):
        from ..kits import awards
        rows = []
        for kind, path in self.kit_dirs():
            row = {'kind': kind, 'name': path.name, 'path': str(path)}
            try:
                _, files, seconds = pack_files(path)
                row.update(count=len(files), seconds=seconds, awards=awards(len(files), seconds))
            except (ValueError, OSError) as exc:
                row.update(error=str(exc))
            rows.append(row)
        return rows

    def kit_path(self, value, studio_only=False):
        if not isinstance(value, str):
            raise ValueError('Choose a kit.')
        # Compare resolved paths: temporary or user folders may be reached
        # through links (/var → /private/var) or Windows 8.3 short names.
        wanted = os.path.normcase(str(Path(value).resolve()))
        for kind, candidate in self.kit_dirs():
            if os.path.normcase(str(candidate.resolve())) == wanted and (kind == 'studio' or not studio_only):
                return kind, candidate
        raise ValueError('Choose a saved Studio kit.' if studio_only else 'Choose a saved kit or pack.')

    def inspect_kit(self, value):
        from ..tuning import tuning_metadata
        kind, path = self.kit_path(value)
        pack, files, seconds = pack_files(path)
        slots = []
        for slot, file in enumerate(files):
            meta = tuning_metadata(file)
            slots.append({'slot': slot, 'file': file.relative_to(pack).as_posix(), 'path': str(file),
                          'seconds': inspect_wav(file), 'label': meta['label'], 'semitones': meta['semitones']})
        return {'kind': kind, 'name': path.name, 'path': str(path), 'count': len(files),
                'seconds': seconds, 'slots': slots}

    def open_kit(self, value, as_copy=False):
        from ..kits import fingerprint
        kind, path = self.kit_path(value)
        _, files, _ = pack_files(path)
        with self.lock:
            self._draft = {'paths': [str(p) for p in files], 'name': path.name if not as_copy else '',
                           'edit': None if as_copy else {'path': str(path), 'kind': kind,
                                                         'fingerprint': fingerprint(path)}}
            self._write_draft()
            self.saved_kit = path  # unchanged so far: the saved kit itself can be sent
        return self.draft()

    def _stage(self, paths, parent):
        stage = Path(tempfile.mkdtemp(prefix='.volcastudio-', dir=parent))
        for slot, source in enumerate(paths):
            destination = stage / f'{slot:02d}-{source.name}'
            shutil.copy2(source, destination)
            if source.with_suffix('.json').is_file():
                shutil.copy2(source.with_suffix('.json'), destination.with_suffix('.json'))
        return stage

    def save_kit(self, name):
        if not isinstance(name, str) or not NAME.fullmatch(name.strip()):
            raise ValueError('Name the kit with lowercase letters, digits, dots, dashes or underscores (e.g. dusty-breaks).')
        name = name.strip()
        with self.lock:
            paths = [self.resolve_sample(p) for p in self._draft['paths']]
        path = save_ordered_kit(self.config, name, paths)
        with self.lock:
            self._draft['name'] = name
            self._draft['edit'] = None
            self._write_draft()
            self.saved_kit = path
        return {'path': str(path), 'name': path.name, 'draft': self.draft()}

    def replace_kit(self):
        """Save the draft over the kit it was opened from; the previous version
        is archived first by the shared ``kits.commit_kit``."""
        from ..kits import commit_kit
        with self.lock:
            edit = self._draft.get('edit')
            if not edit:
                raise ValueError('This workbench was not opened from a saved kit. Save it as a new kit instead.')
            paths = [self.resolve_sample(p) for p in self._draft['paths']]
        kind, target = self.kit_path(edit.get('path'))
        if not 1 <= len(paths) <= MAX_SAMPLES or sum(inspect_wav(p) for p in paths) > MAX_SECONDS:
            raise ValueError('A kit must contain 1–100 samples within 65 seconds.')
        with device_lock(self.config.state):
            stage = self._stage(paths, target.parent)
            try:
                result = commit_kit(self.config, stage, target.name, edit=target, expected=edit.get('fingerprint'))
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        with self.lock:
            from ..kits import fingerprint
            self._draft['paths'] = [str(p) for p in pack_files(result)[1]]
            self._draft['edit'] = {'path': str(result), 'kind': kind, 'fingerprint': fingerprint(result)}
            self._write_draft()
            self.saved_kit = result
        return {'path': str(result), 'name': result.name, 'draft': self.draft()}

    def delete_kit(self, value):
        from ..kits import delete_kit
        _, path = self.kit_path(value, studio_only=True)
        with device_lock(self.config.state):
            entry = delete_kit(self.config, path)
        with self.lock:
            edit = self._draft.get('edit') or {}
            if edit.get('path') == str(path):
                self._draft['edit'] = None
                self._write_draft()
        return {'entry': entry.name, 'name': path.name}

    def trash(self):
        rows = []
        for record in sorted((self.config.data / 'trash').glob('*/record.json'), reverse=True):
            try:
                value = json.loads(record.read_text())
                rows.append({'id': record.parent.name, 'name': value.get('name'), 'reason': value.get('reason')})
            except (OSError, ValueError):
                continue
        return rows

    def restore(self, ident):
        from ..kits import restore_kit
        if not isinstance(ident, str):
            raise ValueError('Choose an archived kit.')
        with device_lock(self.config.state):
            return {'path': str(restore_kit(self.config, ident))}

    def export_kit(self, value, destination):
        """Byte-exact ZIP of every file in a kit (WAVs, sidecars, notes)."""
        _, path = self.kit_path(value)
        pack_files(path)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
            for file in sorted(path.rglob('*')):
                if file.is_symlink():
                    raise ValueError('The kit contains a symbolic link; it cannot be exported safely.')
                if file.is_file():
                    archive.write(file, path.name + '/' + file.relative_to(path).as_posix())
        return path.name

    def import_kit(self, archive_path, name):
        """Create a new Studio kit from an exported ZIP without changing bytes."""
        from ..kits import commit_kit
        if not isinstance(name, str) or not NAME.fullmatch(name.strip()):
            raise ValueError('Name the imported kit with lowercase letters, digits, dots, dashes or underscores.')
        name = name.strip()
        if (self.config.kits / name).exists():
            raise ValueError(f'A kit named {name} already exists; choose another name.')
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile:
            raise ValueError('This is not a kit ZIP exported by VolcaStudio XL.') from None
        with archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if not members or len(members) > 1000:
                raise ValueError('The ZIP must contain one kit folder with up to 100 samples.')
            if sum(m.file_size for m in members) > MAX_KIT_ZIP:
                raise ValueError('The ZIP is too large for a Volca kit.')
            tops = set()
            for member in members:
                parts = member.filename.replace('\\', '/').split('/')
                if (member.filename.startswith('/') or any(p in ('', '.', '..') for p in parts)
                        or (member.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError('The ZIP contains an unsafe path; nothing was imported.')
                tops.add(parts[0] if len(parts) > 1 else '')
            single = len(tops) == 1 and '' not in tops
            self.config.initialize()
            stage = Path(tempfile.mkdtemp(prefix='.volcastudio-', dir=self.config.kits))
            try:
                for member in members:
                    parts = member.filename.replace('\\', '/').split('/')
                    relative = parts[1:] if single else parts
                    if not relative:
                        continue
                    target = stage.joinpath(*relative)
                    if not within(target.resolve(), stage.resolve()):
                        raise ValueError('The ZIP contains an unsafe path; nothing was imported.')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('xb') as output:
                        shutil.copyfileobj(source, output)
                (stage / '.studio-kit.json').unlink(missing_ok=True)
                result = commit_kit(self.config, stage, name)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        return {'path': str(result), 'name': result.name}

    def kit_to_send(self, value):
        _, path = self.kit_path(value)
        pack_files(path)
        return path

    # ------------------------------------------------------------------ devices
    def device_listing(self):
        """Named devices with host API; IDs are resolved again at use time."""
        out = {'outputs': [], 'inputs': [], 'midi': [], 'errors': {}}
        try:
            backend = desktop_audio._backend()
            apis = backend.query_hostapis()
            devices = list(backend.query_devices())
            # One audio path, as in the Desktop App: direct hardware outputs stay hidden
            # while a sound-server route exists (desktop_audio.hide_exclusive_outputs).
            hide = desktop_audio.hide_exclusive_outputs(d['name'] for d in devices if d['max_output_channels'] >= 2)
            for index, device in enumerate(devices):
                api = apis[device['hostapi']]['name'] if 'hostapi' in device else ''
                key = f'{api}::{device["name"]}'
                if device['max_output_channels'] >= 2 and not (hide and desktop_audio.exclusive_output(device['name'])):
                    out['outputs'].append({'key': key, 'name': device['name'], 'api': api, 'id': f'sd:{index}'})
                if device['max_input_channels'] >= 1:
                    out['inputs'].append({'key': key, 'name': device['name'], 'api': api, 'id': f'sd:{index}'})
        except Exception as exc:  # PortAudio absent or failing: offline work continues
            out['errors']['audio'] = str(exc) or type(exc).__name__
        try:
            out['midi'] = list(desktop_audio.midi_outputs())
        except Exception as exc:
            out['errors']['midi'] = 'MIDI is unavailable: ' + (str(exc) or type(exc).__name__)
        settings = self.settings()
        out['selected'] = {k: settings.get(k) for k in ('output', 'input', 'midi')}
        out['connected'] = {
            'output': any(d['key'] == settings.get('output') for d in out['outputs']),
            'input': any(d['key'] == settings.get('input') for d in out['inputs']),
            'midi': settings.get('midi') in out['midi'],
        }
        return out

    def refresh_devices(self):
        """Re-scan PortAudio so newly connected interfaces appear."""
        try:
            backend = desktop_audio._backend()
            if hasattr(backend, '_terminate') and hasattr(backend, '_initialize'):
                backend._terminate()
                backend._initialize()
        except Exception:
            pass
        return self.device_listing()

    def select_devices(self, request):
        changes = {}
        for key in ('output', 'input', 'midi'):
            if key in request:
                value = request[key]
                if value is not None and (not isinstance(value, str) or len(value) > 300):
                    raise ValueError('Invalid device selection.')
                changes[key] = value or None
        self.update_settings(**changes)
        return self.device_listing()

    def resolve_device(self, kind):
        """The explicitly chosen device, or a clear error. Never a default."""
        settings = self.settings()
        wanted = settings.get(kind)
        labels = {'output': 'audio output connected to SYNC IN', 'input': 'audio input connected to the Volca headphones',
                  'midi': 'MIDI output connected to the Volca MIDI IN'}
        if not wanted:
            raise ValueError(f'Choose the {labels[kind]} in Connections first.')
        listing = self.device_listing()
        if kind == 'midi':
            if 'midi' in listing['errors']:
                raise ValueError(listing['errors']['midi'])
            if wanted not in listing['midi']:
                raise ValueError(f'The MIDI output “{wanted}” is not connected. Reconnect it or choose another one.')
            return wanted
        if 'audio' in listing['errors']:
            raise ValueError('Audio devices are unavailable: ' + listing['errors']['audio'])
        for device in listing['outputs' if kind == 'output' else 'inputs']:
            if device['key'] == wanted:
                return device['id']
        name = wanted.split('::', 1)[-1]
        raise ValueError(f'The {kind} “{name}” is not connected. Reconnect it, press Refresh, or choose another one. The Browser App never falls back to a default device.')

    # ------------------------------------------------------------------ patterns
    def bank_files(self):
        from ..patterns import archive_kind, load_bank
        base = self.config.patterns
        if not base.is_dir():
            return []
        result = []
        for path in sorted(base.glob('*.vspatterns'), key=lambda p: p.stat().st_mtime, reverse=True):
            row = {'name': path.name, 'path': str(path), 'bytes': path.stat().st_size}
            try:
                row['format'] = archive_kind(load_bank(path))
            except (ValueError, OSError):
                row['format'] = 'unreadable'
            result.append(row)
        return result

    def bank_file(self, value):
        if not isinstance(value, str):
            raise ValueError('Choose a saved pattern bank.')
        path = Path(value)
        if path.parent.resolve() != self.config.patterns.resolve() or path.suffix != '.vspatterns' or not path.is_file():
            raise ValueError('Choose a bank from the Studio pattern library.')
        return path.resolve()

    def describe_bank(self):
        from ..pattern_format import (predictability, PREDICTABILITY_MASKS,
                                      INTERNAL_PREDICTABILITY_MASKS, motion_value, microtiming)
        from ..pattern_transfer import pattern_targets
        from ..patterns import FIRMWARE_LABELS
        if self.bank is None:
            return {'loaded': False, 'label': None, 'patterns': [], 'stored': []}
        rows = []
        for pattern in self.bank:
            row = {'slot': pattern.slot, 'display': pattern.slot + 1 if pattern.slot is not None else 'current',
                   'firmware': pattern.firmware, 'format': FIRMWARE_LABELS.get(pattern.firmware, pattern.pattern_format),
                   'sha256': pattern.sha256, 'initialized': pattern.initialized,
                   'summary': predictability_summary(pattern), 'parts': []}
            row['compatible_profiles'] = []
            for firmware in FIRMWARE_LABELS:
                try:
                    pattern_targets([pattern], firmware, 0 if pattern.slot is None else None)
                except ValueError:
                    continue
                row['compatible_profiles'].append(firmware)
            if pattern.firmware in ('lumon-xl', 'lumon-xl-internal'):
                try:
                    masks = INTERNAL_PREDICTABILITY_MASKS if pattern.firmware == 'lumon-xl-internal' else PREDICTABILITY_MASKS
                    for part in range(1, 11):
                        modes = predictability(pattern, part)
                        motion = sum(1 for step in range(1, 17) for param in range(11)
                                     if motion_value(pattern, part, step, param))
                        row['parts'].append({'part': part,
                                             'predictability': ['ALL' if m == 0 else f'P.{m:02d}' for m in modes],
                                             'predictability_masks': [''.join('X' if masks[m] & (1 << bar) else '0' for bar in range(8)) for m in modes],
                                             'microtiming': list(microtiming(pattern, part)),
                                             'motion_cells': motion})
                except ValueError as exc:
                    row['error'] = str(exc)
            rows.append(row)
        return {'loaded': True, 'label': self.bank_label, 'path': str(self.bank_path) if self.bank_path else None,
                'patterns': rows, 'stored': sorted(p.slot + 1 for p in self.bank if p.slot is not None),
                'has_current': any(p.slot is None for p in self.bank)}

    def set_bank(self, patterns, label, path=None, neutral=False):
        with self.lock:
            self.bank_neutral = neutral
            self.bank = list(patterns)
            self.bank_label = label
            self.bank_path = path
            self.saved_groove = None
        return self.describe_bank()

    def open_bank(self, value):
        from ..patterns import load_bank
        path = self.bank_file(value)
        return self.set_bank(load_bank(path), path.name, path)

    def open_bank_upload(self, data, filename):
        from ..patterns import load_bank, MAX_BANK_BYTES
        if len(data) > MAX_BANK_BYTES:
            raise ValueError('Pattern file is too large.')
        suffix = Path(safe_component(filename or 'bank.vspatterns')).suffix.lower()
        if suffix not in ('.vspatterns', '.syx', '.json', '.bin', ''):
            suffix = '.vspatterns'
        with tempfile.TemporaryDirectory(prefix='wmc-bank-') as tmp:
            path = Path(tmp) / ('upload' + suffix)
            path.write_bytes(data)
            patterns = load_bank(path)
        return self.set_bank(patterns, safe_component(filename or 'uploaded bank') + ' (not yet saved in Studio)')

    def new_bank_path(self, name):
        if not isinstance(name, str) or not NAME.fullmatch(name.strip()):
            raise ValueError('Name the bank with lowercase letters, digits, dots, dashes or underscores.')
        name = name.strip()
        if name.endswith('.vspatterns'):
            name = name[:-len('.vspatterns')]
        path = self.config.patterns / f'{name}.vspatterns'
        if os.path.lexists(path):
            raise ValueError(f'{path.name} already exists. Choose a new name; banks are never overwritten.')
        return path

    def save_bank_copy(self, name):
        from ..patterns import save_bank, load_bank
        if self.bank is None:
            raise ValueError('Open or create a bank first.')
        path = save_bank(self.new_bank_path(name), self.bank)
        self.set_bank(load_bank(path), path.name, path, neutral=self.bank_neutral)
        return {'path': str(path), 'name': path.name}

    @staticmethod
    def pattern_profile(firmware):
        from ..patterns import FIRMWARE_LABELS
        if firmware not in FIRMWARE_LABELS:
            raise ValueError('Choose the DataBeat OS 1.0 pattern format.')
        return firmware

    def reset_bank(self, slots, firmware=PATTERN_PROFILE):
        from ..patterns import blank_pattern
        firmware = self.pattern_profile(firmware)
        chosen = parse_slots(slots)
        if not chosen:
            raise ValueError('Select at least one pattern memory (1–10).')
        return self.set_bank([blank_pattern(firmware, slot) for slot in chosen], 'Neutral patterns (offline, not saved)',
                             neutral=True)

    def restore_patterns(self, slots, current_destination=None, firmware=PATTERN_PROFILE):
        from ..pattern_transfer import pattern_targets
        firmware = self.pattern_profile(firmware)
        if self.bank is None:
            raise ValueError('Open or create a bank first.')
        if current_destination is not None:
            if type(current_destination) is not int or not 1 <= current_destination <= 10:
                raise ValueError('Choose a destination memory 1–10 for the current snapshot.')
            patterns = [p for p in self.bank if p.slot is None]
            if not patterns:
                raise ValueError('This bank has no current edit-buffer snapshot.')
            pattern_targets(patterns, firmware, current_destination - 1)
            return patterns, current_destination - 1
        chosen = parse_slots(slots)
        patterns = [p for p in self.bank if p.slot in chosen]
        if not patterns:
            raise ValueError('No stored memories in this bank match the selection. A current snapshot needs an explicit destination.')
        pattern_targets(patterns, firmware)
        return patterns, None

    def decode_recording(self, data, name):
        from ..pattern_audio import decode_wav
        from ..pattern_device import _valid_frames
        from ..patterns import save_bank, load_bank
        path = self.new_bank_path(name)
        with tempfile.TemporaryDirectory(prefix='wmc-recording-') as tmp:
            recording = Path(tmp) / 'recording.wav'
            recording.write_bytes(data)
            frames = decode_wav(recording)
        saved = save_bank(path, _valid_frames(frames))
        self.set_bank(load_bank(saved), saved.name, saved)
        return {'path': str(saved), 'name': saved.name}

    # ------------------------------------------------------------------- grooves
    def catalog(self):
        from ..grooves import load_catalog
        if self._catalog is None:
            self._catalog = load_catalog(firmware=PATTERN_PROFILE)
        return self._catalog

    def catalog_listing(self):
        from .groove_actions import catalog_listing
        return catalog_listing(self.catalog())

    def save_grooves(self, request):
        from .groove_actions import build_plan
        from ..grooves import save_groove_plan
        from ..patterns import load_bank
        plan = build_plan(self.bank, request, self.catalog())
        output = self.new_bank_path(request.get('name', ''))
        written, rollback = save_groove_plan(output, plan)
        self.set_bank(load_bank(written), written.name, written)
        with self.lock:
            self.saved_groove = (tuple(plan.selected_patterns), Path(written))
        return {'path': str(written), 'name': written.name, 'rollback': str(rollback) if rollback else None,
                'plan': plan.as_dict()}

    def groove_to_send(self):
        from ..patterns import load_bank
        if self.saved_groove is None:
            raise ValueError('Apply templates & save the groove bank first. Saving again is needed after any change.')
        patterns, path = self.saved_groove
        if tuple(load_bank(path)) != patterns:
            self.saved_groove = None
            raise ValueError('The saved groove bank changed on disk. Save a new copy before sending.')
        return list(patterns)

    # ------------------------------------------------------------------ firmware
    def firmware(self):
        from ..firmware import list_firmware
        try:
            return {'entries': list_firmware(self.config), 'error': None}
        except (ValueError, OSError) as exc:
            return {'entries': [], 'error': str(exc)}

    def add_korg_updater(self, upload, filename):
        from ..firmware import add_korg_updater
        return {'entries': add_korg_updater(upload, self.config, filename=filename)}


@contextlib.contextmanager
def upload_file(source, length, limit, suffix=''):
    """Spool a request body to a private temporary file."""
    if length > limit:
        raise ValueError('The file is too large for this operation.')
    with tempfile.TemporaryDirectory(prefix='wmc-upload-') as tmp:
        path = Path(tmp) / ('upload' + suffix)
        remaining = length
        with path.open('wb') as stream:
            while remaining > 0:
                chunk = source.read(min(1 << 20, remaining))
                if not chunk:
                    raise ValueError('The upload ended early; nothing was saved.')
                stream.write(chunk)
                remaining -= len(chunk)
        yield path
