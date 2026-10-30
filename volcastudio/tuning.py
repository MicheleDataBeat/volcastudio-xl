"""Kit tuning proposals and source-preserving tape varispeed (no devices)."""
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from .audio import NAMES, detect_pitch, identity, note
from .transfer import checked, inspect_wav, MAX_SECONDS, MAX_SAMPLES


def semitone_value(value):
    if isinstance(value, bool) or not isinstance(value, int) or not -99 <= value <= 99:
        raise ValueError('Use an integer from −99 to +99 semitones (at most two digits).')
    return value


def tuning_metadata(path, _visited=None):
    """Only recorded transformations, never filename guesses for varispeed."""
    path = Path(path).resolve()
    visited = set() if _visited is None else set(_visited)
    if path in visited or len(visited) >= 64:
        return {'source': str(path), 'semitones': 0, 'factor': 1, 'label': '?', 'history_uncertain': True}
    visited.add(path)
    try:
        data = json.loads(Path(path).with_suffix('.json').read_text())
        shift = data.get('semitones', 12 if data.get('factor') == 2 else 0)
        if (isinstance(shift, int) and not isinstance(shift, bool)
                and abs(shift) <= 9900 and isinstance(data.get('source'), str)
                and isinstance(data.get('factor'), (int, float)) and not isinstance(data['factor'], bool)
                and math.isfinite(data['factor']) and data['factor'] > 0
                and math.isclose(data['factor'], 2 ** (shift / 12), rel_tol=1e-6)):
            uncertain = bool(data.get('history_uncertain'))
            # Earlier ×2 sidecars describe only the immediate parent. Walk
            # existing parents without changing their metadata or audio.
            if 'input' not in data and 'original_name' not in data:
                parent = Path(data['source'])
                if parent.is_file():
                    old = tuning_metadata(parent, visited)
                    shift += old['semitones']
                    data = dict(data, source=old['source'], original_name=old.get('original_name', Path(old['source']).name),
                                factor=2 ** (shift / 12))
                    uncertain = uncertain or old.get('history_uncertain', False)
                else:
                    uncertain = True
            label = f'{shift:+d}' if shift else ''
            return dict(data, semitones=shift, history_uncertain=uncertain, label=label + ('?' if uncertain else ''))
    except (OSError, ValueError, TypeError, OverflowError, AttributeError):
        pass
    return {'source': str(path), 'semitones': 0, 'factor': 1, 'label': ''}


def sample_shift(path):
    return tuning_metadata(path)['semitones']


def shift_label(path):
    return tuning_metadata(path)['label']


def source_signature(path):
    path, signature = identity(path)
    sidecar = path.with_suffix('.json')
    metadata = sidecar.read_bytes() if sidecar.is_file() else b''
    return hashlib.sha256(signature.encode() + b'\0' + metadata).hexdigest()


def filename_pitch(path):
    """Unambiguous note tokens: A, F#3, Bb, Cmin, D_major, etc.

    Multiple different note tokens, prose letters, and bare numbers are not keys.
    An octave is optional: key alignment compares pitch classes by default.
    """
    stem = Path(path).stem
    tokens = re.findall(r'(?<![A-Za-z0-9])([A-Ga-g])([#b♯♭]?)(-?[0-9])?'
                        r'(?:maj(?:or)?|min(?:or)?|m)?(?![A-Za-z0-9])', stem)
    values = []
    for letter, accidental, octave in tokens:
        pc = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[letter.upper()]
        absolute_pc = pc + (1 if accidental in ('#', '♯') else -1 if accidental in ('b', '♭') else 0)
        pc = absolute_pc % 12
        midi = (int(octave) + 1) * 12 + absolute_pc if octave else None
        values.append((pc, midi))
    if not values or len(set(values)) != 1:
        return None
    pc, midi = values[0]
    return {'pc': pc, 'midi': midi, 'note': note(midi) if midi is not None else NAMES[pc]}


def sample_tuning(path, cache=None):
    path, signature = identity(path)
    signature = source_signature(path)
    meta = tuning_metadata(path)
    # A saved/renamed derivative keeps the original filename and total shift.
    named = None if meta.get('history_uncertain') else filename_pitch(meta.get('original_name', Path(meta['source']).name))
    if named:
        named['pc'] = (named['pc'] + meta['semitones']) % 12
        if named['midi'] is not None:
            named['midi'] += meta['semitones']
        named['note'] = note(named['midi']) if named['midi'] is not None else NAMES[named['pc']]
    measured = detect_pitch(path, cache)
    if source_signature(path) != signature:
        raise ValueError('A source changed during pitch analysis; try again.')
    midi = measured['midi']
    conflict = bool(named and midi is not None and (
        named['pc'] != midi % 12 or named['midi'] is not None and named['midi'] != midi))
    return {'path': str(path), 'signature': signature, 'seconds': inspect_wav(path),
            'semitones': meta['semitones'], 'factor': meta['factor'], 'label': meta['label'],
            'filename_note': named['note'] if named else None,
            'filename_pc': named['pc'] if named else None,
            'detected_note': measured['note'], 'detected_pc': midi % 12 if midi is not None else None,
            'confidence': measured['confidence'], 'conflict': conflict,
            'uncertain': named is None and midi is None, 'analyzed': True}


def sample_outline(path):
    """Duration, provenance and signature only; no pitch analysis."""
    path, _ = identity(path)
    meta = tuning_metadata(path)
    return {'path': str(path), 'signature': source_signature(path), 'seconds': inspect_wav(path),
            'semitones': meta['semitones'], 'factor': meta['factor'], 'label': meta['label'],
            'filename_note': None, 'filename_pc': None, 'detected_note': None, 'detected_pc': None,
            'confidence': None, 'conflict': False, 'uncertain': True, 'analyzed': False}


def varispeed(source, semitones, variants):
    """Incremental tape speed: F=2^(s/12), duration/F, unchanged source/gain.

    Publish the audio and its provenance together; incomplete cache entries fail
    closed. Zero is a byte-preserving identity, not a needless resampling pass.
    """
    semitones = semitone_value(semitones)
    source, signature = identity(source)
    signature = source_signature(source)
    seconds = inspect_wav(source)
    if not semitones:
        return source
    factor = 2 ** (semitones / 12)
    if seconds / factor > MAX_SECONDS:
        raise ValueError('This varispeed sample alone exceeds the 65 second kit budget.')
    old = tuning_metadata(source)
    total = old['semitones'] + semitones
    original_name = old.get('original_name', Path(old['source']).name)
    expected = {'source': old['source'], 'original_name': original_name,
                'factor': 2 ** (total / 12), 'semitones': total,
                'input': str(source), 'input_signature': signature, 'increment': semitones,
                'gain': 'unchanged', 'history_uncertain': bool(old.get('history_uncertain'))}
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', Path(original_name).stem)[:70]
    key = hashlib.sha256(f'{signature}:{semitones}:varispeed-v1'.encode()).hexdigest()
    destination = Path(variants) / key / f'{safe}_vs{total:+d}.wav'
    sidecar = destination.with_suffix('.json')
    if destination.exists() or sidecar.exists():
        if destination.is_file() and sidecar.is_file():
            metadata = json.loads(sidecar.read_text())
            if all(metadata.get(k) == v for k, v in expected.items()):
                inspect_wav(destination)
                if metadata.get('audio_sha256') == hashlib.sha256(destination.read_bytes()).hexdigest():
                    return destination
        raise ValueError('A varispeed cache entry is incomplete or changed; the source was kept.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    rate = int(checked(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                       '-show_entries', 'stream=sample_rate', '-of', 'csv=p=0', source],
                      capture_output=True, text=True).stdout.strip())
    with tempfile.TemporaryDirectory(prefix='.varispeed-', dir=destination.parent) as tmp:
        pending = Path(tmp) / 'sample.wav'
        checked(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', source,
                 '-af', f'asetrate={rate * factor:.12g},aresample={rate}', '-c:a', 'pcm_s24le', pending])
        actual_seconds = inspect_wav(pending)
        if source_signature(source) != signature:
            raise ValueError('A source changed during varispeed rendering; the draft was kept.')
        if actual_seconds > MAX_SECONDS:
            raise ValueError('Rendered varispeed sample exceeds the kit budget.')
        metadata = dict(expected, audio_sha256=hashlib.sha256(pending.read_bytes()).hexdigest())
        pending_meta = Path(tmp) / 'sample.json'
        pending_meta.write_text(json.dumps(metadata, indent=2) + '\n')
        created = False
        try:
            os.link(pending, destination)
            created = True
            os.link(pending_meta, sidecar)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return destination


def alignment_plan(paths, master, slaves, choices=None, overrides=None, cache=None, *, analyze_unselected=True):
    """Propose nearest-pitch-class shifts for the selected slaves.

    With ``analyze_unselected=False`` only the master and the selected slaves
    are pitch-analyzed; other rows keep their duration and provenance for the
    budget and for ``apply_alignment`` without any analysis.
    """
    paths = list(paths)
    if not 1 <= len(paths) <= MAX_SAMPLES:
        raise ValueError('Choose a kit containing 1–100 samples.')
    if isinstance(master, bool) or not isinstance(master, int) or not 0 <= master < len(paths):
        raise ValueError('Select a master sample from this kit.')
    selected = set(slaves)
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(paths) for i in selected):
        raise ValueError('Select slaves from this kit.')
    selected.discard(master)
    choices, overrides = choices or {}, overrides or {}
    if any(i not in selected for i in overrides):
        raise ValueError('Manual shifts apply only to selected slaves.')
    analyzed = selected | {master}
    samples = [sample_tuning(p, cache) if analyze_unselected or i in analyzed else sample_outline(p)
               for i, p in enumerate(paths)]
    conflicts = []
    def resolve(index):
        row = samples[index]
        choice = choices.get(index)
        if choice is not None and choice not in ('filename', 'detected'):
            raise ValueError('Choose filename or detected pitch.')
        if choice:
            if row[choice + '_pc'] is None:
                raise ValueError(f'Slot {index:02d} has no {choice} pitch.')
            return row[choice + '_pc'], row[choice + '_note']
        if row['conflict']:
            conflicts.append(index)
            return None, None
        key = 'detected' if row['detected_pc'] is not None else 'filename'
        return row[key + '_pc'], row[key + '_note']
    master_pc, master_note = resolve(master)
    rows, excluded = [], []
    for i, sample in enumerate(samples):
        if i in selected:
            pc, current_note = resolve(i)
        else:
            display_source = choices.get(i) or ('detected' if sample['detected_pc'] is not None else 'filename')
            pc, current_note = sample[display_source + '_pc'], sample[display_source + '_note']
        shift, reason, exclude = 0, '', False
        if i in selected:
            if i in overrides:
                shift = semitone_value(overrides[i])
                if i in conflicts:
                    conflicts.remove(i)  # A manual amount explicitly bypasses pitch inference.
                reason = 'Manual semitones'
            elif pc is None:
                exclude = True
                reason = 'Choose filename or detected pitch' if sample['conflict'] else 'No clear tonal pitch; change manually'
            elif master_pc is None:
                exclude, reason = True, 'Choose a clear master pitch'
            else:
                shift = (master_pc - pc + 6) % 12 - 6
                reason = 'Nearest matching pitch class'
        if exclude:
            excluded.append(i)
        rows.append(dict(sample, slot=i, selected=i in selected, excluded=exclude, reason=reason,
                         shift=shift, final_semitones=sample['semitones'] + shift,
                         final_seconds=sample['seconds'] / 2 ** (shift / 12), note=current_note,
                         final_note=NAMES[(pc + shift) % 12] if pc is not None else None))
    seconds = sum(r['final_seconds'] for r in rows)
    return {'rows': rows, 'master': master, 'master_note': master_note,
            'seconds': seconds, 'before_seconds': sum(r['seconds'] for r in rows),
            'conflicts': sorted(set(conflicts)), 'excluded': excluded,
            'ready': master_pc is not None and not conflicts,
            'over_budget': seconds > MAX_SECONDS, 'choices': dict(choices), 'overrides': dict(overrides)}


def apply_alignment(plan, variants):
    if not plan['ready']:
        raise ValueError('Resolve pitch discrepancies and choose a clear master before applying.')
    if plan['over_budget'] or plan['seconds'] > MAX_SECONDS:
        raise ValueError('The proposed kit exceeds 65 seconds; adjust the proposal first.')
    rows = plan['rows']
    for row in rows:
        if source_signature(row['path']) != row['signature']:
            raise ValueError('A source changed after analysis; make a new proposal.')
    # Returning paths is the transaction boundary. Callers replace their draft
    # only after every output is complete and the actual budget is verified.
    outputs = [varispeed(row['path'], row['shift'], variants) if row['selected'] and not row['excluded']
               else Path(row['path']) for row in rows]
    for row in rows:
        if source_signature(row['path']) != row['signature']:
            raise ValueError('A source changed during alignment; the draft was kept.')
    if sum(inspect_wav(p) for p in outputs) > MAX_SECONDS:
        raise ValueError('The rendered kit exceeds 65 seconds; the draft was kept.')
    return outputs
