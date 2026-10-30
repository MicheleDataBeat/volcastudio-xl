"""Installation and storage checks; no audio/MIDI enumeration or playback."""
import importlib.util
import platform
import sys

from .. import __version__
from ..transfer import converter, tool_path


def report(config):
    checks = []
    for name in ('ffmpeg', 'ffprobe'):
        path = tool_path(name)
        checks.append({'name': name, 'available': bool(path), 'detail': path or 'Not found'})
    try:
        path = str(converter(config.syro_dir))
        checks.append({'name': 'SYRO encoder', 'available': True, 'detail': path})
    except (ValueError, OSError) as exc:
        checks.append({'name': 'SYRO encoder', 'available': False, 'detail': str(exc)})
    for name in ('sounddevice', 'mido', 'rtmidi'):
        try:
            found = importlib.util.find_spec(name) is not None
        except (ValueError, ImportError):
            found = name in sys.modules  # simulated test modules have no spec
        checks.append({'name': name, 'available': found,
                       'detail': 'Installed' if found else 'Not found'})
    return {'version': __version__, 'platform': platform.platform(),
            'frozen': bool(getattr(sys, 'frozen', False)),
            'passed': all(c['available'] for c in checks), 'checks': checks,
            'paths': {name: str(getattr(config, name)) for name in
                      ('config', 'data', 'state', 'cache', 'sources_dir', 'kits', 'patterns', 'libraries')},
            'hardware_access': False}
