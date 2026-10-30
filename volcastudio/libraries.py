"""Library registrations and kit folders shared by every Studio edition."""
import re
from pathlib import Path


def kit_directories(config, external=False):
    base = config.sources_dir if external else config.kits
    if not base.is_dir():
        return []
    return sorted((p for p in base.iterdir() if p.is_dir() and not p.name.startswith('.')), key=lambda p: p.name.lower())


def registrations(config):
    source = config.libraries
    return source.read_text() if source.is_file() else ''


def library(config, args, *, quiet=False):
    content = registrations(config)
    records = {}
    for line in content.splitlines():
        if re.match(r'^\s*[a-z0-9_-]+\s*=', line):
            name, path = line.split('=', 1)
            records[name.strip()] = path.strip()
    if args.action == 'list':
        for name, path in records.items():
            print(f'{name:20} {path}')
        if not records:
            print('No libraries registered.')
        return 0
    if args.action == 'add':
        if not args.directory:
            raise ValueError('library add needs a directory')
        path = Path(args.directory).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError(f'Not a directory: {path}')
        if '\n' in str(path) or '\t' in str(path):
            raise ValueError('Library paths cannot contain tabs or newlines')
        name = args.name or re.sub(r'[^a-z0-9_-]', '_', path.name.lower()).strip('_')
        if not re.fullmatch('[a-z0-9_-]+', name):
            raise ValueError('Library name must use lowercase letters, digits, underscores or hyphens')
        if name in records:
            raise ValueError(f'Library already registered: {name}')
        records[name] = str(path)
    else:
        if not args.directory or args.directory not in records:
            raise ValueError(f'No library named {args.directory}')
        del records[args.directory]
    # Exclusive command lock prevents overlapping registration mutations.
    from . import locking as fcntl
    config.initialize()
    with (config.config / 'libraries.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if registrations(config) != content:
            raise ValueError('Registrations changed concurrently; retry this command')
        tmp = config.libraries.with_suffix('.tmp')
        tmp.write_text(''.join(f'{name}={path}\n' for name, path in records.items()))
        tmp.replace(config.libraries)
    if not quiet:
        print('Library registrations updated. Sample files are unchanged.')
    return 0
