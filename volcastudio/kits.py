"""Explicit kit editing and recoverable removal."""
import contextlib
from . import locking as fcntl
import hashlib
import json
import math
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .transfer import pack_files


def awards(count, seconds, maximum=65):
    if not 0 <= count <= 100 or not math.isfinite(seconds) or not math.isfinite(maximum) or maximum <= 0 or not 0 <= seconds <= maximum + 1e-9:
        raise ValueError('Invalid kit totals')
    ratio = seconds / maximum
    result = [key for limit, key in ((.95, 'refined95'), (.99, 'refined99'), (1, 'memory100'))
              if ratio + 1e-12 >= limit]
    if count == 100:
        result.append('slots100')
        if ratio + 1e-12 >= 1:
            result.append('capacity')
    return result


@contextlib.contextmanager
def mutation_lock(config):
    config.initialize()
    with (config.state / 'kit-mutation.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def owned_kit(config, path, allow_external=False):
    path = Path(path).expanduser().absolute()
    roots = {config.kits.resolve()}
    if allow_external:
        roots.add(config.sources_dir.resolve())
    if path.is_symlink() or path.parent.resolve() not in roots or path.name.startswith('.'):
        raise ValueError('Choose a kit in Studio kits or configured existing packs' if allow_external else 'Choose a Studio kit')
    if not path.is_dir():
        raise ValueError(f'Kit not found: {path.name}')
    return path


def fingerprint(path):
    digest = hashlib.sha256()
    for p in sorted(Path(path).rglob('*')):
        if p.is_symlink():
            raise ValueError('Kit contains symbolic links; make an independent copy first')
        if p.is_file():
            digest.update(str(p.relative_to(path)).encode())
            digest.update(b'\0')
            digest.update(p.read_bytes())
    return digest.hexdigest()


def archive(config, path, reason):
    trash = config.data / 'trash'
    trash.mkdir(parents=True, exist_ok=True)
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    entry = trash / ident
    entry.mkdir()
    (entry / 'record.json').write_text(json.dumps({
        'name': path.name, 'reason': reason, 'origin': str(path.parent.resolve()),
    }, indent=2) + '\n')
    try:
        path.rename(entry / 'kit')
    except BaseException:
        (entry / 'record.json').unlink()
        entry.rmdir()
        raise
    return entry


def delete_kit(config, path):
    with mutation_lock(config):
        return archive(config, owned_kit(config, path), 'deleted')


def restore_kit(config, ident):
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}-[a-f0-9]{8}', ident):
        raise ValueError('Use a trash entry ID from volcastudio trash')
    with mutation_lock(config):
        entry = config.data / 'trash' / ident
        if entry.is_symlink() or (entry / 'kit').is_symlink():
            raise ValueError('Invalid trash entry')
        record = json.loads((entry / 'record.json').read_text())
        name = record['name']
        if Path(name).name != name or name.startswith('.'):
            raise ValueError('Invalid kit name')
        origin = Path(record.get('origin', str(config.kits))).resolve()
        if origin not in {config.kits.resolve(), config.sources_dir.resolve()}:
            raise ValueError('Archive origin is not a configured kit directory')
        target = origin / name
        if target.exists() or target.is_symlink():
            raise ValueError(f'{name} already exists; keep or rename it before restoring')
        (entry / 'kit').rename(target)
        (entry / 'record.json').unlink()
        entry.rmdir()
        return target


def commit_kit(config, staged, name, edit=None, expected=None):
    """Validate the completed copies before replacing a saved kit; archive the old one."""
    staged = Path(staged).absolute()
    target = owned_kit(config, edit, allow_external=True) if edit else config.kits / name
    if staged.is_symlink() or staged.parent.resolve() != target.parent.resolve() or not staged.name.startswith('.volcastudio-'):
        raise ValueError('Invalid staged kit')
    if not edit and not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', name):
        raise ValueError('Invalid kit name')
    _, files, seconds = pack_files(staged)
    fingerprint(staged)
    (staged / '.studio-kit.json').write_text(json.dumps({
        'schema': 1, 'slots': len(files), 'seconds': seconds,
        'memory_percent': seconds / 65 * 100, 'awards': awards(len(files), seconds),
    }, indent=2) + '\n')
    with mutation_lock(config):
        previous = None
        if edit:
            target = owned_kit(config, edit, allow_external=True)
            if target.name != name or not expected or fingerprint(target) != expected:
                raise ValueError('Saved kit changed during editing; the original was kept')
            # Preserve licenses, notes and other ancillary files, but never
            # reintroduce removed audio or its sample-specific sidecars.
            sidecars = {p.with_suffix('.json') for p in target.rglob('*') if p.suffix.lower() == '.wav'}
            for source in target.rglob('*'):
                if (not source.is_file() or source.suffix.lower() == '.wav'
                        or source in sidecars or source.name in {'leave.txt', '.studio-kit.json'}):
                    continue
                dest = staged / source.relative_to(target)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
            previous = archive(config, target, 'before edit')
        elif target.exists() or target.is_symlink():
            raise ValueError(f'{name} already exists')
        try:
            staged.rename(target)
            target.chmod(0o755)
        except BaseException:
            if previous and not target.exists():
                (previous / 'kit').rename(target)
                (previous / 'record.json').unlink()
                previous.rmdir()
            raise
        return target
