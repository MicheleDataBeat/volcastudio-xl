"""Desktop workflows, independent of Qt and terminal applications."""
import contextlib
import re
import shutil
import tempfile
from pathlib import Path

from .kits import commit_kit, fingerprint, owned_kit
from .transfer import device_lock, inspect_wav, pack_files, MAX_SECONDS, MAX_SAMPLES


def open_ordered_kit(config, path):
    """Read a saved kit in the same slot order used for SYRO transfers."""
    path = owned_kit(config, path, allow_external=True)
    expected = fingerprint(path)
    path, files, _ = pack_files(path)
    if fingerprint(path) != expected:
        raise ValueError('The kit changed while opening it. Open it again.')
    return path, tuple(files), expected


def save_ordered_kit(config, name, sources, *, edit=None, expected=None):
    """Copy an ordered selection; explicit edits archive the previous kit."""
    if edit is None and not re.fullmatch(r'[a-z0-9][a-z0-9._-]*', name):
        raise ValueError('Use a kit name containing lowercase letters, numbers, dots or dashes.')
    sources = [Path(p).expanduser().resolve(strict=True) for p in sources]
    if not 1 <= len(sources) <= MAX_SAMPLES:
        raise ValueError('Choose between 1 and 100 samples.')
    if sum(inspect_wav(p) for p in sources) > MAX_SECONDS:
        raise ValueError('The selection exceeds the 65 second sample budget.')
    config.initialize()
    target = owned_kit(config, edit, allow_external=True) if edit is not None else config.kits / name
    # As in the Browser App: do not replace a kit while another edition is sending.
    with device_lock(config.state) if edit is not None else contextlib.nullcontext():
        stage = Path(tempfile.mkdtemp(prefix='.volcastudio-', dir=target.parent))
        try:
            for slot, source in enumerate(sources):
                destination = stage / f'{slot:02d}-{source.name}'
                shutil.copy2(source, destination)
                if source.with_suffix('.json').is_file():
                    shutil.copy2(source.with_suffix('.json'), destination.with_suffix('.json'))
            return commit_kit(config, stage, name, edit=edit, expected=expected)
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def parse_slots(text):
    """Human one-based slots to the backend's zero-based slots."""
    if text.strip().lower() == 'all':
        return tuple(range(10))
    result = set()
    for group in text.split(','):
        bounds = group.strip().split('-')
        if len(bounds) not in (1, 2) or any(not n.isdecimal() for n in bounds):
            raise ValueError('Use all, 1,3,5 or 1-4 for pattern memories.')
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= 10:
            raise ValueError('Pattern memories are numbered 1–10.')
        result.update(range(first - 1, last))
    return tuple(sorted(result))


def library_roots(config):
    roots = [config.kits, config.sources_dir]
    if config.libraries.is_file():
        for line in config.libraries.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                roots.append(Path(line.split('=', 1)[1]).expanduser())
    return tuple(dict.fromkeys(p.resolve() for p in roots if p.is_dir()))


def predictability_summary(pattern):
    """Readable part/step settings for an XL bank; legacy bytes remain archival."""
    from .pattern_format import predictability
    if pattern.firmware not in ('lumon-xl', 'lumon-xl-internal'):
        return 'Archive only: not a recognized LMX2/LMX3 pattern'
    labels = []
    for part in range(1, 11):
        try:
            modes = predictability(pattern, part)
        except ValueError as exc:
            return f'Archive retained; invalid {pattern.pattern_format}: {exc}'
        if any(modes):
            labels.append(f'part {part}: ' + ' '.join('ALL' if mode == 0 else f'P.{mode:02d}' for mode in modes))
    return '; '.join(labels) if labels else 'Predictability ALL on every step/part'
