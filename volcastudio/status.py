"""Operation status through the active desktop operation or the console."""
import shutil
import sys

from . import desktop_audio


def message(text):
    """Report transfer status through the active GUI operation or the CLI."""
    if desktop_audio.active():
        desktop_audio.report(text)
    elif sys.stdout is not None:
        print(text, flush=True)


def progress(phase, current, total, stream=None):
    if desktop_audio.active():
        desktop_audio.report(phase, current, total)
        return
    stream = stream or sys.stdout
    if stream is None:  # Native windowed distributions have no terminal stream.
        return
    if not stream.isatty():
        print(f'{phase} · {current}/{total}', file=stream, flush=True)
        return
    width = max(4, min(24, shutil.get_terminal_size((80, 24)).columns - 44))
    filled = int(width * current / total)
    print(f'\r\033[2K\033[38;2;139;201;235m◇ {phase} '
          f'{"━" * filled}{"·" * (width - filled)} {current}/{total}\033[0m',
          end='\n' if current == total else '', file=stream, flush=True)
