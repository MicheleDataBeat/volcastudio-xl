"""Local HTTP helper for the Browser App: 127.0.0.1 only, one secret per launch.

Security model
--------------
* The socket binds to 127.0.0.1 and accepts only ``Host: 127.0.0.1:PORT`` or
  ``localhost:PORT`` (DNS-rebinding protection).
* Every ``/api`` request needs the per-launch token in ``X-WMC-Token``. A custom
  header cannot be sent cross-site without a CORS preflight, and this server
  never answers CORS, so other websites cannot read or change anything.
* Requests that change state also reject foreign ``Origin`` and cross-site
  ``Sec-Fetch-Site`` values.
* There is no shell, no command endpoint and no generic file access: files are
  addressed only inside Browser App libraries, Studio kits, banks and firmware archive.
"""
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import WMC_VERSION
from ..patterns import PATTERN_PROFILE
from .jobs import Busy, Jobs, describe_error
from .workspace import Workspace, upload_file, utc

WEB = Path(__file__).with_name('web')
STATIC_FILES = frozenset({'index.html', 'wmc.js', 'wmc.css', 'wmc-icon.svg'})
MAX_JSON = 1024 * 1024
MAX_SAMPLE_UPLOAD = 1024 ** 3
MAX_FIRMWARE = 64 * 1024 * 1024
MAX_RECORDING = 128 * 1024 * 1024
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def kit_labels(index, total):
    clears = 100
    if index <= clears:
        return f'Clearing sample slot {index - 1:02d} · signal {index}/{total}'
    return f'Loading sample {index - clears}/{total - clears} · signal {index}/{total}'


def pattern_labels(index, total):
    return f'Pattern memory signal {index}/{total}'


def firmware_labels(index, total):
    return 'Sending the firmware signal (about 40 seconds) — do not interrupt'


class Helper:
    """Application state shared by request threads."""

    def __init__(self, config=None, *, idle_seconds=600, bench=None):
        self.workspace = Workspace(config)
        self.jobs = Jobs()
        self.token = secrets.token_urlsafe(32)
        self.idle_seconds = idle_seconds
        self.last_seen = time.monotonic()
        self.goodbye = None
        self.started = utc()
        self.bench = bench
        self.server = None
        self.stopping = threading.Event()
        self.browser_note = None
        self.codes = {}
        self.codes_lock = threading.Lock()

    def issue_code(self, lifetime=120):
        """A single-use, short-lived code for a browser command line.

        The session token itself never appears in a process list: Chrome gets
        this code, and the page exchanges it once for the token."""
        code = secrets.token_urlsafe(24)
        with self.codes_lock:
            now = time.monotonic()
            self.codes = {k: v for k, v in self.codes.items() if v > now}
            self.codes[code] = now + lifetime
        return code

    def claim(self, code):
        with self.codes_lock:
            expiry = self.codes.pop(code, None) if isinstance(code, str) else None
        return expiry is not None and expiry > time.monotonic()

    @property
    def config(self):
        return self.workspace.config

    def touch(self):
        self.last_seen = time.monotonic()
        self.goodbye = None

    def idle(self):
        now = time.monotonic()
        job = self.jobs.current
        if (job is not None and job.state == 'confirm' and self.goodbye is not None
                and now - self.goodbye > 45):
            # The window that would answer is gone: decline, release the lock.
            job.cancel_event.set()
            job.answer_event.set()
        if self.jobs.active:
            return False
        if self.goodbye is not None and now - self.goodbye > 45:
            return True
        return now - self.last_seen > self.idle_seconds

    def shutdown(self):
        if self.stopping.is_set():
            return
        self.stopping.set()
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


class Body:
    """The request body, bounded by Content-Length, so leftovers can be drained."""

    def __init__(self, stream, length):
        self.stream, self.remaining = stream, length

    def read(self, size=-1):
        if self.remaining <= 0:
            return b''
        size = self.remaining if size is None or size < 0 else min(size, self.remaining)
        data = self.stream.read(size)
        self.remaining -= len(data)
        return data


class Handler(BaseHTTPRequestHandler):
    server_version = 'VolcaStudioWMC/' + WMC_VERSION
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    @property
    def helper(self):
        return self.server.helper

    def log_message(self, format, *args):  # quiet: no request logging to disk or console
        if os.environ.get('VOLCASTUDIO_WMC_DEBUG'):
            sys.stderr.write('browser-app: ' + format % args + '\n')

    # ------------------------------------------------------------ plumbing
    def origin(self):
        return f'http://127.0.0.1:{self.server.server_address[1]}'

    def host_allowed(self):
        port = self.server.server_address[1]
        return self.headers.get('Host', '') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def send(self, status, body=b'', content_type='application/json', headers=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', CSP)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def json(self, value, status=200):
        self.send(status, json.dumps(value, default=str).encode())

    def send_file(self, path, content_type, download=None):
        size = path.stat().st_size
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', CSP)
        if download:
            safe = download.encode('ascii', 'replace').decode().replace('"', '')
            self.send_header('Content-Disposition', f'attachment; filename="{safe}"')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with path.open('rb') as stream:
            shutil.copyfileobj(stream, self.wfile)

    def length(self):
        value = self.headers.get('Content-Length')
        if value is None or not (value.isascii() and value.isdigit()):
            raise ApiError(411, 'A content length is required.')
        return int(value)

    def body_json(self):
        length = self.length()
        if length > MAX_JSON:
            raise ApiError(413, 'Request too large.')
        if length == 0:
            return {}
        try:
            value = json.loads(self.body.read(length).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, 'Invalid request.') from None
        if not isinstance(value, dict):
            raise ApiError(400, 'Invalid request.')
        return value

    def header_text(self, name, default=''):
        return unquote(self.headers.get(name, default))

    def authorized(self):
        supplied = self.headers.get('X-WMC-Token', '')
        return hmac.compare_digest(supplied.encode(), self.helper.token.encode())

    def same_origin(self):
        origin = self.headers.get('Origin')
        if origin is not None and origin not in (self.origin(), f'http://localhost:{self.server.server_address[1]}'):
            return False
        site = self.headers.get('Sec-Fetch-Site')
        return site in (None, 'same-origin', 'none')

    # ------------------------------------------------------------- dispatch
    def do_GET(self):
        self.dispatch('GET')

    def do_HEAD(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def do_PUT(self):
        self.dispatch('PUT')

    def do_DELETE(self):
        self.dispatch('DELETE')

    def do_OPTIONS(self):
        # No CORS: refuse preflights so other websites cannot call the API.
        self.send(403, b'{"error":"Cross-origin requests are not allowed."}')

    def dispatch(self, method):
        declared = self.headers.get('Content-Length', '0')
        self.body = Body(self.rfile, int(declared) if declared.isascii() and declared.isdigit() else 0)
        try:
            self.route(method)
        finally:
            # Never leave unread bytes on a keep-alive connection: Chrome would
            # parse them as the start of its next request.
            if self.body.remaining:
                if self.body.remaining <= MAX_JSON:
                    while self.body.read(65536):
                        pass
                else:
                    self.close_connection = True

    def route(self, method):
        try:
            if not self.host_allowed():
                raise ApiError(403, 'The Browser App answers only on this computer (127.0.0.1).')
            url = urlsplit(self.path)
            path = url.path
            query = {k: v[-1] for k, v in parse_qs(url.query).items()}
            if not path.startswith('/api/'):
                if method != 'GET':
                    raise ApiError(405, 'Not allowed.')
                return self.static(path)
            if path == '/api/bye' and method == 'POST':
                return self.bye()
            if path == '/api/session/claim' and method == 'POST':
                if not self.same_origin() or self.headers.get('Origin') is None:
                    raise ApiError(403, 'Requests from other websites are refused.')
                if not self.helper.claim(self.body_json().get('code')):
                    raise ApiError(401, 'This Browser App link was already used or has expired. Open VolcaStudio XL Browser App again.')
                self.helper.touch()
                return self.json({'token': self.helper.token})
            if not self.authorized():
                raise ApiError(401, 'This window belongs to a closed Browser App session. Open VolcaStudio XL Browser App again.')
            if method != 'GET' and not self.same_origin():
                raise ApiError(403, 'Requests from other websites are refused.')
            self.helper.touch()
            route = ROUTES.get((method, path))
            if route is None:
                raise ApiError(404, 'Unknown request.')
            return route(self, query)
        except ApiError as exc:
            self.close_connection = True
            self.json({'error': str(exc)}, exc.status)
        except Busy as exc:
            self.close_connection = True
            self.json({'error': str(exc)}, 409)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as exc:  # every failure gets an answer the page can show
            self.close_connection = True
            if os.environ.get('VOLCASTUDIO_WMC_DEBUG'):
                traceback.print_exc()
            expected = isinstance(exc, (ValueError, OSError, KeyError, TypeError, RuntimeError, EOFError))
            message = describe_error(exc) if expected else f'Unexpected problem ({type(exc).__name__}: {exc}). Nothing was changed by this request.'
            try:
                self.json({'error': message}, 400 if expected else 500)
            except OSError:
                pass

    def static(self, path):
        if path in ('', '/'):
            path = '/index.html'
        name = path.lstrip('/')
        # A fixed allow-list: no path is ever built from the request (Windows
        # would accept drive letters, backslashes and UNC paths otherwise).
        if name not in STATIC_FILES:
            raise ApiError(404, 'Not found.')
        target = WEB / name
        kind = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        if name.endswith('.js'):
            kind = 'text/javascript'
        if kind.startswith('text/') or kind in ('image/svg+xml',):
            kind += '; charset=utf-8'
        self.send(200, target.read_bytes(), kind)

    def bye(self):
        # A closing window may say goodbye with sendBeacon, which cannot set
        # headers; it still has to prove knowledge of the session token.
        length = self.length()
        if length > 512:
            raise ApiError(413, 'Request too large.')
        token = self.body.read(length).decode('utf-8', 'replace').strip()
        if hmac.compare_digest(token.encode(), self.helper.token.encode()):
            self.helper.goodbye = time.monotonic()
        self.send(204, b'')

    # ------------------------------------------------------------ handlers
    def ws(self):
        return self.helper.workspace

    def idle_guard(self):
        if self.helper.jobs.active:
            raise Busy('Wait for the current operation, or cancel it, before changing this.')

    def r_state(self, query):
        from .. import __version__
        ws = self.ws()
        return self.json({'wmc_version': WMC_VERSION, 'backend_version': __version__, 'platform': sys.platform,
                          'frozen': bool(getattr(sys, 'frozen', False)), 'bench': bool(self.helper.bench),
                          'browser_note': self.helper.browser_note, 'started': self.helper.started,
                          'storage': {'data': str(ws.config.data), 'kits': str(ws.config.kits),
                                      'patterns': str(ws.config.patterns), 'wmc': str(ws.root),
                                      'config': str(ws.config.config)},
                          'job': self.helper.jobs.snapshot(), 'linux_menu': sys.platform.startswith('linux') and bool(getattr(sys, 'frozen', False))})

    def r_heartbeat(self, query):
        return self.json({'ok': True, 'job': self.helper.jobs.snapshot()})

    def r_session_code(self, query):
        return self.json({'code': self.helper.issue_code()})

    def r_shutdown(self, query):
        if self.helper.jobs.active:
            raise Busy('An operation is still running. Cancel it first, then close the Browser App.')
        self.json({'closing': True})
        self.helper.shutdown()

    # libraries
    def r_libraries(self, query):
        from .library_actions import registrations
        return self.json({'libraries': self.ws().libraries(),
                          'registrations': registrations(self.ws().config)})

    def r_library_samples(self, query):
        return self.json(self.ws().library_samples(query.get('id', ''), query.get('q', ''),
                                                  int(query.get('offset', '0')), int(query.get('limit', '250'))))

    def r_library_register(self, query):
        self.idle_guard()
        from .library_actions import register
        body = self.body_json()
        return self.json(register(self.ws().config, body.get('directory'), body.get('name')))

    def r_library_unregister(self, query):
        self.idle_guard()
        from .library_actions import unregister
        return self.json(unregister(self.ws().config, self.body_json().get('name')))

    def r_preferences(self, query):
        return self.json(self.ws().settings())

    def r_preferences_update(self, query):
        body = self.body_json()
        if set(body) - {'autoplay', 'preview_mode'}:
            raise ValueError('Unknown listening preference.')
        if 'autoplay' in body and type(body['autoplay']) is not bool:
            raise ValueError('Autoplay must be on or off.')
        if 'preview_mode' in body and body['preview_mode'] not in ('source', 'volca'):
            raise ValueError('Choose Source or Volca preview.')
        return self.json(self.ws().update_settings(**body))

    def r_import_sample(self, query):
        self.idle_guard()
        result = self.ws().import_file(self.header_text('X-WMC-Library'), self.header_text('X-WMC-Path'),
                                       self.body, self.checked_length(MAX_SAMPLE_UPLOAD))
        return self.json(result)

    def checked_length(self, limit):
        length = self.length()
        if length > limit:
            raise ApiError(413, 'The file is too large.')
        return length

    def r_remove_library(self, query):
        self.idle_guard()
        return self.json(self.ws().remove_library(self.body_json().get('id', '')))

    def r_sample_info(self, query):
        return self.json(self.ws().sample_info(query.get('path', '')))

    def r_preview(self, query):
        try:
            pitch = int(query.get('pitch', '0'))
        except ValueError:
            raise ApiError(400, 'Invalid preview pitch.') from None
        path = self.ws().preview(query.get('path', ''), pitch, query.get('mode', 'volca'))
        return self.send_file(path, 'audio/wav')

    # draft
    def r_draft(self, query):
        return self.json(self.ws().draft())

    def r_draft_put(self, query):
        self.idle_guard()
        body = self.body_json()
        return self.json(self.ws().set_draft(body.get('paths'), body.get('name'), body.get('generation')))

    def r_draft_add(self, query):
        self.idle_guard()
        return self.json(self.ws().add_to_draft(self.body_json().get('paths') or []))

    def r_draft_clear(self, query):
        self.idle_guard()
        return self.json(self.ws().clear_draft())

    def r_varispeed(self, query):
        body = self.body_json()
        operation, apply = self.ws().varispeed_operation(body.get('indices'), body.get('semitones'))
        job = self.helper.jobs.start('varispeed', 'Varispeed', operation, on_success=apply)
        return self.json(job.snapshot())

    def r_variants(self, query):
        body = self.body_json()
        operation, apply = self.ws().variants_operation(body.get('paths'), body.get('semitones'),
                                                       body.get('replace_existing', False))
        job = self.helper.jobs.start('varispeed', 'Creating sample variants', operation, on_success=apply)
        return self.json(job.snapshot())

    def r_align_analyze(self, query):
        job = self.helper.jobs.start('analysis', 'Listening for pitch', self.ws().analysis_operation())
        return self.json(job.snapshot())

    def r_align_plan(self, query):
        self.idle_guard()
        return self.json(self.ws().align_plan(self.body_json()))

    def r_align_apply(self, query):
        operation, apply = self.ws().align_apply_operation(self.body_json())
        job = self.helper.jobs.start('alignment', 'Rendering key alignment', operation, on_success=apply)
        return self.json(job.snapshot())

    # kits
    def r_kits(self, query):
        return self.json({'kits': self.ws().kits(), 'trash': self.ws().trash()})

    def r_kit_inspect(self, query):
        return self.json(self.ws().inspect_kit(query.get('path', '')))

    def r_kit_open(self, query):
        self.idle_guard()
        body = self.body_json()
        return self.json(self.ws().open_kit(body.get('path'), bool(body.get('copy'))))

    def r_kit_save(self, query):
        self.idle_guard()
        return self.json(self.ws().save_kit(self.body_json().get('name')))

    def r_kit_replace(self, query):
        self.idle_guard()
        return self.json(self.ws().replace_kit())

    def r_kit_delete(self, query):
        self.idle_guard()
        return self.json(self.ws().delete_kit(self.body_json().get('path')))

    def r_kit_restore(self, query):
        self.idle_guard()
        return self.json(self.ws().restore(self.body_json().get('id')))

    def r_kit_export(self, query):
        with tempfile.TemporaryDirectory(prefix='wmc-export-') as tmp:
            target = Path(tmp) / 'kit.zip'
            name = self.ws().export_kit(query.get('path', ''), target)
            return self.send_file(target, 'application/zip', download=f'{name}.volcakit.zip')

    def r_kit_import(self, query):
        self.idle_guard()
        name = self.header_text('X-WMC-Name')
        with upload_file(self.body, self.checked_length(2 * 1024 ** 3), 2 * 1024 ** 3, '.zip') as path:
            return self.json(self.ws().import_kit(path, name))

    def r_kit_prepare(self, query):
        """Offline dry run: encode and verify every signal, then discard them."""
        from ..transfer import prepare
        kit = self.ws().kit_to_send(self.body_json().get('path'))
        config = self.ws().config

        def operation(job):
            with tempfile.TemporaryDirectory(prefix='wmc-prepare-') as tmp:
                job.progress('Encoding SYRO signals offline (nothing is played)', 0, 1)
                manifest = prepare(kit, Path(tmp) / 'prepared', config.syro_dir)
                streams = sorted((Path(tmp) / 'prepared').glob('*.wav'))
                return {'count': manifest['count'], 'seconds': manifest['seconds'],
                        'signals': len(streams), 'sample_pcm_bytes': manifest['sample_pcm_bytes'],
                        'kit': kit.name, 'note': 'Signals encoded and verified offline, then discarded. Nothing was sent.'}
        job = self.helper.jobs.start('prepare', 'Preparing signals offline', operation)
        return self.json(job.snapshot())

    def r_kit_export_signals(self, query):
        from ..transfer import prepare
        ws = self.ws()
        kit = ws.kit_to_send(self.body_json().get('path'))
        job = self.helper.jobs.start('export', 'Preparing downloadable kit signals',
            lambda job: ws.exports.prepare(kit.name, lambda folder: prepare(kit, folder, ws.config.syro_dir), job))
        return self.json(job.snapshot())

    def r_prepared_download(self, query):
        path, name = self.ws().exports.download(query.get('id'))
        return self.send_file(path, 'application/zip', download=name)

    def r_kit_send(self, query):
        from ..transfer import transfer
        kit = self.ws().kit_to_send(self.body_json().get('path'))
        target = self.ws().resolve_device('output')
        config = self.ws().config
        job = self.helper.jobs.start('kit', f'Send kit {kit.name}',
                                     lambda job, target: transfer(kit, config, job.confirm, target),
                                     device_target=target, streams=lambda m: 100 + m['count'], labels=kit_labels)
        return self.json(job.snapshot())

    # devices
    def r_devices(self, query):
        return self.json(self.ws().device_listing())

    def r_devices_refresh(self, query):
        self.idle_guard()
        return self.json(self.ws().refresh_devices())

    def r_devices_select(self, query):
        return self.json(self.ws().select_devices(self.body_json()))

    # patterns
    def r_banks(self, query):
        from ..patterns import FIRMWARE_LABELS
        return self.json({'banks': self.ws().bank_files(), 'bank': self.ws().describe_bank(),
                          'profiles': FIRMWARE_LABELS})

    def r_bank_open(self, query):
        self.idle_guard()
        return self.json(self.ws().open_bank(self.body_json().get('path')))

    def r_bank_upload(self, query):
        self.idle_guard()
        from ..patterns import MAX_BANK_BYTES
        length = self.checked_length(MAX_BANK_BYTES)
        return self.json(self.ws().open_bank_upload(self.body.read(length), self.header_text('X-WMC-Name')))

    def r_bank_download(self, query):
        path = self.ws().bank_file(query.get('path', ''))
        return self.send_file(path, 'application/json', download=path.name)

    def r_bank_save(self, query):
        self.idle_guard()
        return self.json(self.ws().save_bank_copy(self.body_json().get('name')))

    def r_bank_reset(self, query):
        self.idle_guard()
        body = self.body_json()
        return self.json(self.ws().reset_bank(body.get('slots', ''), body.get('firmware', PATTERN_PROFILE)))

    def r_patterns_export_signals(self, query):
        from ..pattern_transfer import prepare_patterns
        ws = self.ws()
        body = self.body_json()
        firmware = ws.pattern_profile(body.get('firmware', PATTERN_PROFILE))
        patterns, destination = ws.restore_patterns(body.get('slots', ''), body.get('current_destination'), firmware)
        job = self.helper.jobs.start('export', 'Preparing downloadable pattern signals',
            lambda job: ws.exports.prepare('patterns', lambda folder:
                prepare_patterns(patterns, folder, ws.config.syro_dir, firmware, destination), job))
        return self.json(job.snapshot())

    def r_patterns_send(self, query):
        from ..pattern_transfer import transfer_patterns
        from ..patterns import blank_pattern
        body = self.body_json()
        firmware = self.ws().pattern_profile(body.get('firmware', PATTERN_PROFILE))
        patterns, destination = self.ws().restore_patterns(body.get('slots', ''), body.get('current_destination'), firmware)
        target = self.ws().resolve_device('output')
        if body.get('reset_current_via_midi') and not self.ws().bank_neutral:
            raise ValueError('Resetting the current edit buffer is offered only with neutral patterns from “Create neutral patterns”.')
        midi = self.ws().resolve_device('midi') if body.get('reset_current_via_midi') else None
        config = self.ws().config
        current = blank_pattern(firmware) if midi else None
        job = self.helper.jobs.start('patterns', 'Restore pattern memories',
            lambda job, target: transfer_patterns(patterns, config, firmware, target=target,
                                                  confirm_callback=job.confirm, destination=destination,
                                                  current_pattern=current, midi_port=midi),
            device_target=target, streams=lambda m: m['count'], labels=pattern_labels)
        return self.json(job.snapshot())

    def r_backup(self, query):
        from ..pattern_device import backup_audio
        from ..patterns import load_bank
        ws = self.ws()
        path = ws.new_bank_path(self.body_json().get('name', ''))
        port = ws.resolve_device('midi')
        node = ws.resolve_device('input')

        def operation(job):
            job.progress('Waiting for the Volca: playback stops, keep the controls untouched', 0, 11)
            try:
                backup_audio(ws.config, port, node, path,
                             progress_callback=lambda count, total: job.progress(f'Received {count}/{total} CRC-checked frames', count, total))
            except (ValueError, OSError, RuntimeError) as exc:
                text = str(exc)
                if any(key in text for key in ('InputStream', 'PaErrorCode', 'ermission', 'Invalid device')):
                    raise ValueError(f'The audio input could not be opened ({text}). Nothing was saved. '
                                     'On macOS allow VolcaStudio XL Browser App in System Settings → Privacy & Security → Microphone; '
                                     'on Windows allow desktop apps in Settings → Privacy & security → Microphone. '
                                     'Then check that the input is connected and press Refresh in Connections.') from exc
                raise
            return str(path)

        def apply(result):
            ws.set_bank(load_bank(result), Path(result).name, Path(result))
            return {'path': result, 'name': Path(result).name, 'bank': ws.describe_bank()}
        job = self.helper.jobs.start('backup', 'Capture pattern audio backup', operation, on_success=apply)
        return self.json(job.snapshot())

    def r_decode(self, query):
        self.idle_guard()
        length = self.checked_length(MAX_RECORDING)
        return self.json(self.ws().decode_recording(self.body.read(length), self.header_text('X-WMC-Name')))

    # grooves
    def r_catalog(self, query):
        from .groove_actions import catalog_listing
        return self.json(catalog_listing(self.ws().catalog(), query.get('category', 'all'), query.get('q', '')))

    def r_template(self, query):
        from .groove_actions import describe_template
        return self.json(describe_template(self.ws().catalog(), query.get('id', '')))

    def r_grooves_plan(self, query):
        from .groove_actions import build_plan
        ws = self.ws()
        return self.json(build_plan(ws.bank, self.body_json(), ws.catalog()).as_dict())

    def r_grooves_save(self, query):
        self.idle_guard()
        return self.json(self.ws().save_grooves(self.body_json()))

    def r_grooves_send(self, query):
        from ..pattern_transfer import transfer_patterns
        patterns = self.ws().groove_to_send()
        target = self.ws().resolve_device('output')
        config = self.ws().config
        firmware = self.ws().catalog().firmware
        job = self.helper.jobs.start('grooves', 'Send saved groove bank',
            lambda job, target: transfer_patterns(patterns, config, firmware, target=target, confirm_callback=job.confirm),
            device_target=target, streams=lambda m: m['count'], labels=pattern_labels)
        return self.json(job.snapshot())

    # firmware
    def r_firmware(self, query):
        return self.json(self.ws().firmware())

    def r_firmware_korg(self, query):
        self.idle_guard()
        name = Path(self.header_text('X-WMC-Name', 'korg-updater')).name[:200] or 'korg-updater'
        with upload_file(self.body, self.checked_length(MAX_FIRMWARE), MAX_FIRMWARE) as path:
            return self.json(self.ws().add_korg_updater(path, name))

    def r_firmware_send(self, query):
        from ..firmware import available_identities, transfer_firmware, inspect_firmware
        body = self.body_json()
        ident = body.get('id')
        if not isinstance(ident, str):
            raise ApiError(400, 'Choose firmware from the archive.')
        if ident not in available_identities(self.ws().config):
            raise ValueError('VolcaStudio XL sends only DataBeat OS built from your Korg updater, and that '
                             'Korg updater.')
        record = inspect_firmware(self.ws().config, ident)
        if not record.get('installable'):
            raise ValueError('This image is archived for offline analysis only and cannot be installed.')
        if record.get('experimental', True):
            raise ValueError('VolcaStudio XL sends only the accepted DataBeat OS release and the Korg updater.')
        target = self.ws().resolve_device('output')
        config = self.ws().config
        job = self.helper.jobs.start('firmware', 'Firmware update',
            lambda job, target: transfer_firmware(config, ident, target=target, confirm_callback=job.confirm),
            device_target=target, streams=1, labels=firmware_labels)
        return self.json(job.snapshot())

    # jobs
    def r_job(self, query):
        return self.json({'job': self.helper.jobs.snapshot()})

    def r_job_answer(self, query):
        body = self.body_json()
        return self.json({'job': self.helper.jobs.answer(body.get('id'), body.get('approve') is True)})

    def r_job_cancel(self, query):
        return self.json({'job': self.helper.jobs.cancel(self.body_json().get('id'))})

    # system
    def r_linux_menu(self, query):
        from .launcher import install_linux_menu
        return self.json({'path': str(install_linux_menu())})

    def r_system_status(self, query):
        from .diagnostics import report
        return self.json(report(self.ws().config))


ROUTES = {
    ('GET', '/api/state'): Handler.r_state,
    ('POST', '/api/heartbeat'): Handler.r_heartbeat,
    ('POST', '/api/shutdown'): Handler.r_shutdown,
    ('POST', '/api/session/code'): Handler.r_session_code,
    ('GET', '/api/libraries'): Handler.r_libraries,
    ('GET', '/api/library'): Handler.r_library_samples,
    ('POST', '/api/library/register'): Handler.r_library_register,
    ('POST', '/api/library/unregister'): Handler.r_library_unregister,
    ('GET', '/api/preferences'): Handler.r_preferences,
    ('POST', '/api/preferences'): Handler.r_preferences_update,
    ('PUT', '/api/import/sample'): Handler.r_import_sample,
    ('POST', '/api/library/remove'): Handler.r_remove_library,
    ('GET', '/api/sample/info'): Handler.r_sample_info,
    ('GET', '/api/sample/preview'): Handler.r_preview,
    ('GET', '/api/draft'): Handler.r_draft,
    ('PUT', '/api/draft'): Handler.r_draft_put,
    ('POST', '/api/draft/add'): Handler.r_draft_add,
    ('POST', '/api/draft/clear'): Handler.r_draft_clear,
    ('POST', '/api/draft/varispeed'): Handler.r_varispeed,
    ('POST', '/api/samples/variants'): Handler.r_variants,
    ('POST', '/api/align/analyze'): Handler.r_align_analyze,
    ('POST', '/api/align/plan'): Handler.r_align_plan,
    ('POST', '/api/align/apply'): Handler.r_align_apply,
    ('GET', '/api/kits'): Handler.r_kits,
    ('GET', '/api/kit'): Handler.r_kit_inspect,
    ('POST', '/api/kit/open'): Handler.r_kit_open,
    ('POST', '/api/kit/save'): Handler.r_kit_save,
    ('POST', '/api/kit/replace'): Handler.r_kit_replace,
    ('POST', '/api/kit/delete'): Handler.r_kit_delete,
    ('POST', '/api/kit/restore'): Handler.r_kit_restore,
    ('GET', '/api/kit/export'): Handler.r_kit_export,
    ('PUT', '/api/kit/import'): Handler.r_kit_import,
    ('POST', '/api/kit/prepare'): Handler.r_kit_prepare,
    ('POST', '/api/kit/export-signals'): Handler.r_kit_export_signals,
    ('GET', '/api/prepared/download'): Handler.r_prepared_download,
    ('POST', '/api/kit/send'): Handler.r_kit_send,
    ('GET', '/api/devices'): Handler.r_devices,
    ('POST', '/api/devices/refresh'): Handler.r_devices_refresh,
    ('POST', '/api/devices/select'): Handler.r_devices_select,
    ('GET', '/api/patterns'): Handler.r_banks,
    ('POST', '/api/patterns/open'): Handler.r_bank_open,
    ('PUT', '/api/patterns/upload'): Handler.r_bank_upload,
    ('GET', '/api/patterns/download'): Handler.r_bank_download,
    ('POST', '/api/patterns/save'): Handler.r_bank_save,
    ('POST', '/api/patterns/reset'): Handler.r_bank_reset,
    ('POST', '/api/patterns/send'): Handler.r_patterns_send,
    ('POST', '/api/patterns/export-signals'): Handler.r_patterns_export_signals,
    ('POST', '/api/patterns/backup'): Handler.r_backup,
    ('PUT', '/api/patterns/decode'): Handler.r_decode,
    ('GET', '/api/grooves'): Handler.r_catalog,
    ('GET', '/api/grooves/template'): Handler.r_template,
    ('POST', '/api/grooves/plan'): Handler.r_grooves_plan,
    ('POST', '/api/grooves/save'): Handler.r_grooves_save,
    ('POST', '/api/grooves/send'): Handler.r_grooves_send,
    ('GET', '/api/firmware'): Handler.r_firmware,
    ('PUT', '/api/firmware/korg'): Handler.r_firmware_korg,
    ('POST', '/api/firmware/send'): Handler.r_firmware_send,
    ('GET', '/api/job'): Handler.r_job,
    ('POST', '/api/job/answer'): Handler.r_job_answer,
    ('POST', '/api/job/cancel'): Handler.r_job_cancel,
    ('POST', '/api/system/linux-menu'): Handler.r_linux_menu,
    ('GET', '/api/system/status'): Handler.r_system_status,
}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, helper, port=0):
        self.helper = helper
        super().__init__(('127.0.0.1', port), Handler)
        helper.server = self

    def server_bind(self):
        # http.server would call socket.getfqdn('127.0.0.1'): a reverse DNS
        # lookup that can stall startup for many seconds on some systems.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = '127.0.0.1', self.server_address[1]

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_address[1]}/'


def serve(helper, preferred_port=0):
    """Bind 127.0.0.1, preferring a stable port so browser preferences persist."""
    try:
        return Server(helper, preferred_port)
    except OSError:
        return Server(helper, 0)
