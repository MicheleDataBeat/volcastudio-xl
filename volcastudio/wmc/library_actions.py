"""Manage shared library registrations through the shared Studio backend.

The Browser App's authenticated local helper calls these functions after the user chooses
to register or unregister a folder. Registration references a directory in
place; it does not scan, import, validate or change its sample files. Sample
reads still go through ``Workspace.resolve_sample`` and its registered-root
allow-list. This module is not a general filesystem browsing API.
"""
from pathlib import Path
import re
from types import SimpleNamespace

from .. import libraries


_NAME = re.compile(r'[a-z0-9_-]+\Z')
_RECORD = re.compile(r'^\s*[a-z0-9_-]+\s*=')
_CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def _records(config):
    """Use the same names and last-record-wins parsing as ``libraries.library``."""
    records = {}
    for line in libraries.registrations(config).splitlines():
        if _RECORD.match(line):
            name, directory = line.split('=', 1)
            records[name.strip()] = directory.strip()
    return records


def _entry(name, directory):
    path = Path(directory).expanduser()
    try:
        root = str(path.resolve()) if directory else ''
        available = bool(directory) and path.is_dir()
    except (OSError, RuntimeError):
        # A disconnected or malformed existing registration must remain
        # visible so that the user can unregister it.
        root, available = str(path), False
    return {'id': 'reg:' + name, 'name': name, 'title': name,
            'directory': str(path) if directory else '', 'root': root,
            'kind': 'shared', 'available': available}


def registrations(config):
    """Return registered folders, including unavailable removable references."""
    return [_entry(name, directory) for name, directory in _records(config).items()]


def _name(value, *, optional=False):
    if optional and value in (None, ''):
        return None
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError('Library names use lowercase letters, digits, underscores or hyphens.')
    return value


def register(config, directory, name=None):
    """Reference a user-selected local directory; return its shared identity.

    Paths must be absolute (``~`` is expanded on this computer). The shared
    ``libraries.library`` owns duplicate-name checks, the exclusive registration
    lock and the concurrent-edit check. Distinct names may reference the same directory,
    as in the shared library registry.
    """
    name = _name(name, optional=True)
    if not isinstance(directory, str) or not directory or _CONTROL.search(directory):
        raise ValueError('Enter a local folder path without tabs, newlines or control characters.')
    path = Path(directory).expanduser()
    if not path.is_absolute():
        raise ValueError('Enter the full path of a local sample folder.')
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError:
        raise ValueError(f'Folder not found: {path}') from None
    if not path.is_dir():
        raise ValueError(f'Not a directory: {path}')
    if _CONTROL.search(str(path)):
        raise ValueError('Library paths cannot contain tabs, newlines or control characters.')
    libraries.library(config, SimpleNamespace(action='add', directory=str(path), name=name), quiet=True)
    actual_name = name or re.sub(r'[^a-z0-9_-]', '_', path.name.lower()).strip('_')
    return _entry(actual_name, str(path))


def unregister(config, name):
    """Remove only a shared reference, even when its directory is unavailable."""
    name = _name(name)
    records = _records(config)
    if name not in records:
        raise ValueError(f'No library named {name}. Refresh the library list.')
    libraries.library(config, SimpleNamespace(action='remove', directory=name), quiet=True)
    return {'removed': True, 'name': name, 'directory': records[name]}
