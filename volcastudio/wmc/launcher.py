"""One-click start for the Browser App: local helper + Google Chrome app window.

* A second launch never starts a second helper: it reopens the window of the
  running one (single-instance lock in the Browser App's own state folder).
* Chrome is preferred and opened as an app window. If Chrome is missing, the
  default browser opens the Browser App with an explicit notice instead of failing silently.
* The helper exits on "Close Browser App", or after the window has been gone for a while
  with no operation running.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .. import locking
from ..config import Config
from . import WMC_VERSION

PREFERRED_PORT = 47815
WEB = Path(__file__).with_name('web')


def chrome_candidates():
    if sys.platform == 'win32':
        roots = [os.environ.get(k) for k in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        found = [Path(r) / 'Google/Chrome/Application/chrome.exe' for r in roots if r]
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r'Software\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe') as key:
                        found.insert(0, Path(winreg.QueryValue(key, None)))
                except OSError:
                    pass
        except ImportError:
            pass
        return found
    if sys.platform == 'darwin':
        name = 'Google Chrome.app/Contents/MacOS/Google Chrome'
        return [Path('/Applications') / name, Path.home() / 'Applications' / name]
    names = ('google-chrome', 'google-chrome-stable', 'chrome', 'chromium', 'chromium-browser')
    return [Path(p) for p in (shutil.which(n) for n in names) if p]


def find_chrome():
    override = os.environ.get('VOLCASTUDIO_WMC_CHROME')
    if override:
        return Path(override) if Path(override).is_file() else None
    for candidate in chrome_candidates():
        if candidate.is_file():
            return candidate
    return None


def open_window(url, chrome=None):
    """Open an app-style Chrome window, or the default browser with a notice."""
    chrome = chrome if chrome is not None else find_chrome()
    if chrome is not None:
        flags = {}
        if sys.platform == 'win32':
            flags['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            flags['start_new_session'] = True
        try:
            subprocess.Popen([str(chrome), '--new-window', f'--app={url}'], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **flags)
            return 'chrome'
        except OSError:
            pass
    separator = '&' if '#' in url else '#'
    if webbrowser.open(url + separator + 'browser=other'):
        return 'other'
    return None


def instance_paths(config):
    base = config.state / 'wmc'
    base.mkdir(parents=True, exist_ok=True)
    return base / 'instance.lock', base / 'instance.json'


def write_private(path, text):
    fd, pending = tempfile.mkstemp(prefix='.instance-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        if os.name != 'nt':
            os.chmod(pending, 0o600)
        os.replace(pending, path)
    finally:
        Path(pending).unlink(missing_ok=True)


def running_instance(info_path):
    """(url, token, one-time browser code) of a running helper, or None."""
    try:
        info = json.loads(info_path.read_text(encoding='utf-8'))
        url = f'http://127.0.0.1:{int(info["port"])}/'
        request = urllib.request.Request(url + 'api/session/code', data=b'{}', method='POST',
                                         headers={'X-WMC-Token': info['token'], 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=3) as response:
            if response.status == 200:
                return url, info['token'], json.loads(response.read())['code']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def install_linux_menu():
    """Add the packaged Browser App to the Linux applications menu (user-level only)."""
    if not sys.platform.startswith('linux') or not getattr(sys, 'frozen', False):
        raise ValueError('The applications-menu shortcut is available in the packaged Linux edition.')
    executable = Path(sys.executable).resolve()
    folder = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
    path = folder / 'volcastudio-wmc.desktop'
    if path.exists() and 'X-VolcaStudio-WMC=true' not in path.read_text(errors='replace'):
        raise ValueError('An unrelated launcher already uses this name; nothing was changed.')
    def quoted(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text('[Desktop Entry]\nType=Application\nName=VolcaStudio XL Browser App\n'
                    'Comment=Volca Sample workstation in Google Chrome\n'
                    f'Exec={quoted(executable)}\nIcon={WEB / "wmc-icon.svg"}\nTerminal=false\n'
                    'Categories=AudioVideo;Audio;Music;\nX-VolcaStudio-WMC=true\n', encoding='utf-8')
    return path


def run(helper, server, *, open_browser=True, chrome=None, announce=None):
    """Serve until Close Browser App, idle exit or a termination signal."""
    url = server.url
    link = f'{url}#k={helper.token}'
    trace('opening the window')
    if open_browser:
        # Chrome's command line is visible to other local users: give it a
        # single-use code, never the session token.
        mode = open_window(f'{url}#c={helper.issue_code()}', chrome)
        helper.browser_note = {'chrome': None, 'other': 'chrome-missing', None: 'no-browser'}[mode]
    if announce:
        announce(link)

    def watch():
        while not helper.stopping.wait(5):
            if helper.idle():
                helper.shutdown()
    threading.Thread(target=watch, name='wmc-idle', daemon=True).start()
    try:
        server.serve_forever(poll_interval=.5)
    finally:
        server.server_close()
    return 0


def temporary_config(root):
    root = Path(root)
    return Config(root / 'config', root / 'data', root / 'state', root / 'cache', root / 'packs',
                  Config.read().syro_dir)


def smoke_test():
    """Packaged startup check: temporary storage, no devices, no browser."""
    from .server import Helper, serve
    with tempfile.TemporaryDirectory(prefix='wmc-smoke-') as tmp:
        helper = Helper(temporary_config(tmp))
        server = serve(helper, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(path, token=True):
                request = urllib.request.Request(server.url + path, headers={'X-WMC-Token': helper.token} if token else {})
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status, response.read()
            status, body = get('api/state')
            state = json.loads(body)
            if status != 200 or state['wmc_version'] != WMC_VERSION:
                return 1
            status, page = get('', token=False)
            if status != 200 or b'VolcaStudio XL Browser App' not in page:
                return 1
            try:
                get('api/state', token=False)
                return 1
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    return 1
        finally:
            server.shutdown()
            server.server_close()
    return 0


_STARTED = time.monotonic()


def trace(stage):
    if os.environ.get('VOLCASTUDIO_WMC_DEBUG') and sys.stderr is not None:
        print(f'browser-app: {time.monotonic() - _STARTED:6.2f}s {stage}', file=sys.stderr, flush=True)


def robust_console():
    """Never let console text stop an operation.

    The shared backend prints progress symbols (◇, ·, …). On Windows a
    redirected or NUL stdout may use a legacy code page and even report itself
    as a terminal; an unencodable symbol must not abort a transfer."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(errors='replace')
            except (ValueError, OSError):
                pass


def main(argv=None):
    robust_console()
    parser = argparse.ArgumentParser(prog='volcastudio-wmc', description='VolcaStudio XL Browser App (Google Chrome)')
    parser.add_argument('--no-browser', action='store_true', help='Print the private link instead of opening Chrome')
    parser.add_argument('--port', type=int, default=PREFERRED_PORT, help=argparse.SUPPRESS)
    parser.add_argument('--smoke-test', action='store_true', help='Offline startup check; no devices, no browser')
    parser.add_argument('--verify-offline', metavar='NEW_DIRECTORY', help='Full offline acceptance with simulated devices')
    parser.add_argument('--bench', action='store_true', help='Temporary storage and simulated devices (developer check)')
    parser.add_argument('--link-file', type=Path, help=argparse.SUPPRESS)  # checks of windowed builds without a console
    parser.add_argument('--version', action='version', version=f'VolcaStudio XL Browser App {WMC_VERSION}')
    args = parser.parse_args(argv)
    if args.smoke_test:
        return smoke_test()
    if args.verify_offline:
        from .verify import verify_offline
        return verify_offline(Path(args.verify_offline))
    from .server import Helper, serve

    def announce(link):
        if args.link_file:
            write_private(args.link_file, link + '\n')
        if args.no_browser and sys.stdout is not None:
            print(f'VolcaStudio XL Browser App is running. Open this private link in Google Chrome:\n{link}', flush=True)

    if args.bench:
        from .bench import install
        tmp = tempfile.TemporaryDirectory(prefix='wmc-bench-')
        bench = install(Path(tmp.name) / 'bench')
        helper = Helper(temporary_config(tmp.name), bench=bench)
        server = serve(helper, 0)
        try:
            return run(helper, server, open_browser=not args.no_browser, announce=announce)
        finally:
            tmp.cleanup()

    trace('arguments parsed')
    config = Config.read()
    config.initialize()
    trace('configuration ready')
    lock_path, info_path = instance_paths(config)
    lock = lock_path.open('a+')
    try:
        locking.flock(lock, locking.LOCK_EX | locking.LOCK_NB)
    except (BlockingIOError, OSError):
        lock.close()
        for _ in range(20):
            existing = running_instance(info_path)
            if existing:
                url, token, code = existing
                if args.no_browser or args.link_file:
                    announce(f'{url}#k={token}')
                if not args.no_browser:
                    open_window(f'{url}#c={code}')
                return 0
            time.sleep(.25)
        if sys.stderr is not None:
            print('VolcaStudio XL Browser App is starting or closing in another window. Try again in a moment.', file=sys.stderr)
        return 3
    try:
        trace('instance lock held')
        helper = Helper(config)
        trace('helper ready')
        server = serve(helper, args.port)
        trace('listening')
        write_private(info_path, json.dumps({'pid': os.getpid(), 'port': server.server_address[1],
                                             'token': helper.token, 'version': WMC_VERSION}))
        for name in ('SIGTERM', 'SIGINT', 'SIGHUP'):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), lambda *_: helper.shutdown())
        return run(helper, server, open_browser=not args.no_browser, announce=announce)
    finally:
        try:
            info_path.unlink(missing_ok=True)
        finally:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
