"""Offline acceptance for source and packaged Browser App builds.

Runs the real local helper on 127.0.0.1 with temporary storage and the
simulated bench devices, then exercises the HTTP API exactly as the Chrome
interface does: uploads, varispeed, tonal alignment, kits, ZIP exchange,
SYRO preparation and transfer (byte-compared with an independent encoding),
patterns, grooves, pattern audio backup, firmware gates, cancellation,
disconnected devices, denied input permission and the security boundary.
No real audio or MIDI device is enumerated or opened.
"""
import array
import hashlib
import http.client
import json
import math
import os
import platform
import sys
import tempfile
import threading
import time
import traceback
import wave
from pathlib import Path
from urllib.parse import quote

from . import WMC_VERSION


def tone(path, hz, seconds=.3, rate=44100, amplitude=20000):
    values = array.array('h', (round(amplitude * math.sin(2 * math.pi * hz * i / rate))
                               for i in range(int(rate * seconds))))
    if sys.byteorder != 'little':
        values.byteswap()
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(values.tobytes())
    return path


class Client:
    """Minimal browser-equivalent client for the helper's private API."""

    def __init__(self, port, token, host=None, origin=None):
        self.port, self.token = port, token
        self.host = host or f'127.0.0.1:{port}'
        self.origin = origin

    def request(self, method, path, body=None, headers=None, token=True, raw=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=120)
        sent = {'Host': self.host}
        if token:
            sent['X-WMC-Token'] = self.token
        if self.origin:
            sent['Origin'] = self.origin
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            sent['Content-Type'] = 'application/json'
        if body is not None:
            sent['Content-Length'] = str(len(body))
        elif method in ('POST', 'PUT'):
            sent['Content-Length'] = '0'
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        data = response.read()
        headers = dict(response.getheaders())
        connection.close()
        if raw:
            return response.status, data, headers
        value = json.loads(data) if data and headers.get('Content-Type', '').startswith('application/json') else data
        if response.status >= 400:
            raise ApiFailure(response.status, value.get('error') if isinstance(value, dict) else value)
        return value

    def get(self, path, **kw):
        return self.request('GET', path, **kw)

    def post(self, path, body=None, **kw):
        return self.request('POST', path, body if body is not None else {}, **kw)

    def put(self, path, body=None, **kw):
        return self.request('PUT', path, body, **kw)

    def upload(self, library, relpath, data):
        return self.put('/api/import/sample', data, headers={'X-WMC-Library': quote(library), 'X-WMC-Path': quote(relpath)})

    def wait(self, job, answer=None, cancel_when=None, timeout=300):
        """Poll a job; optionally approve/decline its confirmation."""
        deadline = time.monotonic() + timeout
        ident = job['id']
        while True:
            current = self.get('/api/job')['job']
            if current['id'] != ident:
                raise AssertionError('Job replaced unexpectedly')
            if current['state'] == 'confirm' and answer is not None:
                self.post('/api/job/answer', {'id': ident, 'approve': answer})
                answer = None
            if cancel_when and cancel_when(current) and not current['cancel_requested']:
                self.post('/api/job/cancel', {'id': ident})
            if current['state'] == 'finished':
                return current
            if time.monotonic() > deadline:
                raise AssertionError('Operation timed out')
            time.sleep(.05)


class ApiFailure(AssertionError):
    def __init__(self, status, message):
        super().__init__(f'{status}: {message}')
        self.status = status
        self.message = message


def expect_failure(call, status=None, text=None):
    try:
        call()
    except ApiFailure as exc:
        if status is not None and exc.status != status:
            raise AssertionError(f'Expected HTTP {status}, got {exc.status}: {exc.message}')
        if text is not None and text.lower() not in str(exc.message).lower():
            raise AssertionError(f'Expected “{text}” in “{exc.message}”')
        return exc
    raise AssertionError('The request unexpectedly succeeded')


def wav_frames(path):
    with wave.open(str(path), 'rb') as stream:
        return stream.readframes(stream.getnframes())


def start(root):
    """A helper with temporary storage and bench devices, served on a thread."""
    from .bench import install
    from .launcher import temporary_config
    from .server import Helper, serve
    bench = install(Path(root) / 'bench')
    helper = Helper(temporary_config(Path(root) / 'store'), bench=bench)
    server = serve(helper, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return helper, server, bench, Client(server.server_address[1], helper.token)


def verify_pattern_profile(client, helper, bench, work):
    """One public pattern format; other formats stay in the bank and are never restored.

    Private HTTP routes and the real file/encoding backend, on bench devices.
    """
    from ..patterns import FIRMWARE_LABELS, PATTERN_PROFILE, blank_pattern, bank_to_json
    source = [blank_pattern('lumon-xl', slot=0), blank_pattern(PATTERN_PROFILE, slot=1),
              blank_pattern(PATTERN_PROFILE)]
    raw = bank_to_json(source).encode()
    opened = client.put('/api/patterns/upload', raw, headers={'X-WMC-Name': 'mixed-formats.vspatterns'})
    assert [p['compatible_profiles'] for p in opened['patterns']] == [[], [PATTERN_PROFILE], [PATTERN_PROFILE]]
    assert opened['patterns'][1]['format'] == FIRMWARE_LABELS[PATTERN_PROFILE] == 'DataBeat OS 1.0 pattern format'
    assert len(opened['patterns'][1]['parts']) == 10, 'Inspector did not decode parts'
    profiles = client.get('/api/patterns')['profiles']
    assert list(profiles) == [PATTERN_PROFILE]
    expect_failure(lambda: client.post('/api/patterns/send', {'slots': '1'}), 400)
    expect_failure(lambda: client.post('/api/patterns/send', {'slots': '2', 'firmware': 'lumon-xl'}), 400,
                   'DataBeat OS 1.0 pattern format')
    for route in ('/api/patterns/conversion-preview', '/api/patterns/convert'):
        expect_failure(lambda: client.post(route, {'firmware': PATTERN_PROFILE, 'slots': 'all'}), 404)
    current = client.wait(client.post('/api/patterns/send', dict(current_destination=5)), answer=False)
    assert current['outcome'] == 'cancelled_before_sending'
    reset = client.post('/api/patterns/reset', dict(slots='2'))
    assert reset['patterns'][0]['firmware'] == PATTERN_PROFILE
    count, midi = len(bench.streams), len(bench.midi)
    done = client.wait(client.post('/api/patterns/send', dict(slots='2', reset_current_via_midi=True)), answer=True)
    assert done['outcome'] == 'signals_sent' and len(bench.streams) == count + 1
    assert len(bench.midi) == midi + 1 and bench.midi[-1].startswith('f0423000012d40')
    return dict(passed=True, profiles=list(profiles), mixed_archive_preserved=True,
                other_format_never_restored=True, other_profile_refused=True,
                conversion_routes_absent=True, explicit_current_destination=True,
                reset_and_midi_current=True, hardware_access=False,
                scope='Private HTTP routes and shared backend/bench; Chrome controls are verified separately.')


def scenario(client, helper, bench, work, checks):
    from ..transfer import prepare
    from ..patterns import load_bank
    from .bench import OUTPUT, INPUT, MIDI, API, bench_bank
    config = helper.config
    port = client.port

    # 1 · Security boundary --------------------------------------------------
    status, page, headers = client.request('GET', '/', token=False, raw=True)
    assert status == 200 and b'VolcaStudio XL Browser App' in page
    assert "frame-ancestors 'none'" in headers.get('Content-Security-Policy', '')
    assert client.request('GET', '/api/state', token=False, raw=True)[0] == 401
    rebinding = Client(port, client.token, host=f'evil.example:{port}')
    assert rebinding.request('GET', '/api/state', raw=True)[0] == 403
    foreign = Client(port, client.token, origin='https://evil.example')
    assert foreign.request('POST', '/api/draft/clear', b'{}', raw=True)[0] == 403
    assert client.request('OPTIONS', '/api/state', raw=True)[0] == 403
    assert client.request('GET', '/../../etc/passwd', token=False, raw=True)[0] in (403, 404)
    assert client.get('/api/state')['wmc_version'] == WMC_VERSION
    checks['security_boundary'] = {'token_required': True, 'host_checked': True, 'foreign_origin_refused': True,
                                   'cors_preflight_refused': True}

    # 2 · Samples: browser upload → Browser App library -----------------------
    sources = [tone(work / 'master_A3.wav', 220), tone(work / 'slave_C4.wav', 261.625565),
               tone(work / 'pad.wav', 330, seconds=.2)]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    uploaded = [client.upload('verify-set', f'tones/{p.name}', p.read_bytes())['path'] for p in sources]
    again = client.upload('verify-set', 'tones/master_A3.wav', sources[0].read_bytes())
    assert again['reused'] and again['path'] == uploaded[0]
    expect_failure(lambda: client.upload('verify-set', 'tones/not-audio.wav', b'RIFFxxxxWAVEjunk'), 400, 'not a supported')
    expect_failure(lambda: client.upload('verify-set', '../escape.wav', sources[0].read_bytes()), 400)
    libraries = client.get('/api/libraries')['libraries']
    assert any(l['id'] == 'wmc:verify-set' for l in libraries)
    listing = client.get('/api/library?id=' + quote('wmc:verify-set'))['samples']
    assert sorted(s['name'] for s in listing) == ['master_A3.wav', 'pad.wav', 'slave_C4.wav']
    checks['library_upload'] = {'files': len(listing), 'duplicate_reused': True, 'invalid_refused': True,
                                'path_escape_refused': True}

    # 3 · Workbench, multi-selection varispeed and badges ----------------------
    draft = client.put('/api/draft', {'paths': uploaded[:2]})
    assert draft['count'] == 2 and not draft['over_budget']
    expect_failure(lambda: client.put('/api/draft', {'paths': ['/etc/passwd']}), 400)
    job = client.post('/api/draft/varispeed', {'indices': [0], 'semitones': 12})
    done = client.wait(job)
    assert done['outcome'] == 'done', done
    rows = done['result']['draft']['rows']
    assert rows[0]['label'] == '+12' and rows[0]['semitones'] == 12 and rows[1]['label'] == ''
    assert abs(rows[0]['seconds'] - .15) < .01, rows[0]['seconds']
    job = client.post('/api/draft/varispeed', {'indices': [0, 1], 'semitones': -7})
    rows = client.wait(job)['result']['draft']['rows']
    assert [r['semitones'] for r in rows] == [5, -7], rows
    job = client.post('/api/draft/varispeed', {'indices': [0, 1], 'semitones': 7})
    rows = client.wait(job)['result']['draft']['rows']
    assert [r['semitones'] for r in rows] == [12, 0], rows
    info = client.get('/api/sample/info?path=' + quote(rows[1]['path']))
    assert info['filename_note'] == 'C4'
    status, preview, headers = client.request('GET', '/api/sample/preview?pitch=-12&path=' + quote(rows[1]['path']), raw=True)
    assert status == 200 and preview[:4] == b'RIFF' and headers['Content-Type'] == 'audio/wav'
    checks['varispeed_multi_cumulative'] = {'labels': [r['label'] for r in rows], 'preview_wav': True}

    # 4 · Tonal alignment: analysis, plan, refused stale plan, accept ---------
    generation = client.get('/api/draft')['generation']
    analysis = client.wait(client.post('/api/align/analyze'))
    assert analysis['outcome'] == 'done'
    plan = client.post('/api/align/plan', {'master': 0, 'slaves': [1], 'generation': generation})
    assert plan['ready'] and plan['rows'][1]['shift'] == -3 and plan['rows'][0]['semitones'] == 12, plan['rows']
    manual = client.post('/api/align/plan', {'master': 0, 'slaves': [1], 'overrides': {'1': 5}, 'generation': generation})
    assert manual['rows'][1]['shift'] == 5 and manual['seconds'] < plan['before_seconds']
    expect_failure(lambda: client.post('/api/align/apply', {'master': 0, 'slaves': [1], 'generation': generation - 1}), 400, 'changed')
    done = client.wait(client.post('/api/align/apply', {'master': 0, 'slaves': [1], 'generation': generation}))
    assert done['outcome'] == 'done', done
    rows = done['result']['draft']['rows']
    assert [r['semitones'] for r in rows] == [12, -3], rows
    checks['tonal_alignment'] = {'master_semitones': 12, 'slave_shift': -3, 'manual_override': 5,
                                 'proposed_seconds': round(plan['seconds'], 4), 'stale_plan_refused': True}

    # 5 · Save, reopen, metadata, ZIP exchange --------------------------------
    expect_failure(lambda: client.post('/api/kit/save', {'name': 'Bad Name'}), 400)
    saved = client.post('/api/kit/save', {'name': 'wmc-verify'})
    kit = Path(saved['path'])
    inspect = client.get('/api/kit?path=' + quote(str(kit)))
    assert [s['semitones'] for s in inspect['slots']] == [12, -3]
    assert all((kit / s['file']).with_suffix('.json').is_file() for s in inspect['slots'])
    expect_failure(lambda: client.post('/api/kit/save', {'name': 'wmc-verify'}), 400, 'exists')
    status, archive, headers = client.request('GET', '/api/kit/export?path=' + quote(str(kit)), raw=True)
    assert status == 200 and archive[:2] == b'PK'
    imported = client.put('/api/kit/import', archive, headers={'X-WMC-Name': 'wmc-verify-copy'})
    copy = Path(imported['path'])
    original_files = {p.relative_to(kit).as_posix(): p.read_bytes() for p in kit.rglob('*') if p.is_file() and p.name != '.studio-kit.json'}
    copied_files = {p.relative_to(copy).as_posix(): p.read_bytes() for p in copy.rglob('*') if p.is_file() and p.name != '.studio-kit.json'}
    assert original_files == copied_files
    reopened = client.post('/api/kit/open', {'path': str(copy)})
    assert [r['semitones'] for r in reopened['rows']] == [12, -3] and reopened['edit']
    reordered = client.put('/api/draft', {'paths': [reopened['rows'][1]['path'], reopened['rows'][0]['path']]})
    replaced = client.post('/api/kit/replace')
    assert [s['semitones'] for s in client.get('/api/kit?path=' + quote(replaced['path']))['slots']] == [-3, 12]
    trash = client.get('/api/kits')['trash']
    assert any(t['reason'] == 'before edit' for t in trash)
    deleted = client.post('/api/kit/delete', {'path': replaced['path']})
    restored = client.post('/api/kit/restore', {'id': deleted['entry']})
    assert Path(restored['path']).is_dir()
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources} == before
    checks['kit_save_reopen_exchange'] = {'zip_byte_exact': True, 'metadata_sidecars': True, 'replace_archived': True,
                                          'delete_restore': True, 'sources_unchanged': True}

    # 6 · Offline signal preparation (no playback) ----------------------------
    streams_before = len(bench.streams)
    prepared = client.wait(client.post('/api/kit/prepare', {'path': str(kit)}))
    assert prepared['outcome'] == 'done' and prepared['result']['signals'] == 102
    assert len(bench.streams) == streams_before
    checks['offline_preparation'] = {'signals': 102, 'played': 0}

    # 7 · Devices: explicit selection, no default fallback --------------------
    devices = client.get('/api/devices')
    assert devices['outputs'][0]['name'] == OUTPUT and devices['midi'] == [MIDI]
    expect_failure(lambda: client.post('/api/kit/send', {'path': str(kit)}), 400, 'choose the audio output')
    client.post('/api/devices/select', {'output': f'{API}::{OUTPUT}', 'input': f'{API}::{INPUT}', 'midi': MIDI})
    bench.output_present = False
    expect_failure(lambda: client.post('/api/kit/send', {'path': str(kit)}), 400, 'not connected')
    bench.output_present = True
    checks['explicit_devices'] = {'unselected_refused': True, 'disconnected_refused_without_fallback': True}

    # 8 · Kit transfer: decline, approve (byte-exact), cancel while sending ----
    declined = client.wait(client.post('/api/kit/send', {'path': str(kit)}), answer=False)
    assert declined['outcome'] == 'cancelled_before_sending' and len(bench.streams) == streams_before
    job = client.post('/api/kit/send', {'path': str(kit)})
    seen = {}
    def capture(current):
        if current['state'] == 'confirm' and current['manifest']:
            seen.update(current['manifest'])
        return False
    sent = client.wait(job, answer=True, cancel_when=capture)
    assert sent['outcome'] == 'signals_sent', sent
    assert seen.get('count') == 2 and seen.get('hardware_receipt', '').startswith('unavailable')
    played = bench.streams[streams_before:]
    assert len(played) == 102 and all(s['rate'] == 44100 and s['channels'] == 2 and s['dtype'] == 'int16' for s in played)
    reference = work / 'reference'
    prepare(kit, reference, config.syro_dir)
    expected = [reference / f'clear-{i:02d}.wav' for i in range(100)] + [reference / f'upload-{i:02d}.wav' for i in range(2)]
    lead = bytes(22050 * 4)
    for stream, signal in zip(played, expected):
        data = Path(stream['path']).read_bytes()
        assert data == lead + wav_frames(signal), f'Played stream differs from SYRO: {signal.name}'
    log = json.loads((config.state / 'last-transfer.json').read_text())
    assert log['phase'] == 'signals_sent'
    bench.delay = .004
    count = len(bench.streams)
    interrupted = client.wait(client.post('/api/kit/send', {'path': str(kit)}), answer=True,
                              cancel_when=lambda c: c['sending'] and c['stream_index'] >= 3)
    bench.delay = 0
    assert interrupted['outcome'] == 'interrupted', interrupted
    assert 'cannot be undone' in interrupted['error']
    assert len(bench.streams) - count < 102
    assert json.loads((config.state / 'last-transfer.json').read_text())['phase'] == 'interrupted'
    checks['kit_transfer'] = {'declined_nothing_played': True, 'streams': 102, 'pcm_byte_exact': True,
                              'format': '44100 Hz stereo PCM16', 'outcome': 'signals_sent',
                              'cancel_while_sending': 'interrupted'}

    # 9 · Patterns and grooves -----------------------------------------------
    bank = client.post('/api/patterns/reset', {'slots': 'all'})
    assert len(bank['patterns']) == 10 and bank['patterns'][0]['firmware'] == 'lumon-xl-internal'
    saved_bank = client.post('/api/patterns/save', {'name': 'neutral'})
    expect_failure(lambda: client.post('/api/patterns/save', {'name': 'neutral'}), 400, 'exists')
    catalog = client.get('/api/grooves')
    assert (catalog['profiles'], catalog['aliases']) == (217, 270)
    template = 'MPC3000_73_B02'
    groove = client.post('/api/grooves/save', {'reset': False, 'slots': '1,3', 'assignments': {'1': template, '2': 'DILLA_KICK_5_B01'}, 'name': 'groove-13'})
    assert groove['plan']['slots'] == [1, 3] and groove['plan']['mode'] == 'preserve'
    described = client.get('/api/patterns')['bank']
    part1 = described['patterns'][0]['parts'][0]
    assert part1['microtiming'] == [0, 13, -1, 13, 0, 13, -1, 13, 0, 13, -1, 13, 0, 13, -1, 15]
    count = len(bench.streams)
    sent = client.wait(client.post('/api/grooves/send'), answer=True)
    assert sent['outcome'] == 'signals_sent' and len(bench.streams) - count == 2
    reset_groove = client.post('/api/grooves/save', {'reset': True, 'slots': 'all', 'assignments': {'1': 'DILLA_KICK_1_B01'}, 'name': 'groove-all'})
    assert reset_groove['plan']['mode'] == 'reset+groove' and len(reset_groove['plan']['slots']) == 10
    checks['patterns_grooves'] = {'reset_bank': True, 'no_overwrite': True, 'profiles': 217, 'aliases': 270,
                                  'preserve_selected_1_3': True, 'reset_all': True, 'groove_signals': 2}

    # 10 · Pattern audio backup through MIDI request + audio input --------------
    done = client.wait(client.post('/api/patterns/backup', {'name': 'machine'}), timeout=240)
    assert done['outcome'] == 'done', done
    captured = load_bank(done['result']['path'])
    assert [p.sha256 for p in captured] == [p.sha256 for p in bench_bank()]
    described = done['result']['bank']
    assert described['patterns'][0]['parts'][0]['predictability'][1] == 'P.01'
    assert any(row['motion_cells'] for row in described['patterns'][3]['parts'])
    assert bench.midi[:2] == ['fc', 'f0423000012d7df7']
    preserve = client.post('/api/grooves/save', {'reset': False, 'slots': 'all', 'assignments': {'3': template}, 'name': 'machine-groove'})
    regrooved = load_bank(preserve['path'])
    from ..pattern_format import predictability, motion_value
    assert [predictability(p, 1) for p in regrooved] == [predictability(p, 1) for p in captured if p.slot is not None]
    assert [motion_value(p, 3, 1 + p.slot, 3) for p in regrooved] == [128 + p.slot for p in regrooved]
    client.post('/api/patterns/open', {'path': done['result']['path']})
    count = len(bench.streams)
    current = client.wait(client.post('/api/patterns/send', {'current_destination': 5}), answer=True)
    assert current['outcome'] == 'signals_sent' and len(bench.streams) - count == 1
    client.post('/api/patterns/reset', {'slots': '2'})
    midi_before = len(bench.midi)
    reset = client.wait(client.post('/api/patterns/send', {'slots': '2', 'reset_current_via_midi': True}), answer=True)
    assert reset['outcome'] == 'signals_sent' and bench.midi[midi_before].startswith('f0423000012d40')
    bench.input_error = 'Error opening InputStream: Unanticipated host error [PaErrorCode -9999]'
    failed = client.wait(client.post('/api/patterns/backup', {'name': 'machine-denied'}))
    bench.input_error = None
    assert failed['outcome'] == 'failed' and 'microphone' in failed['error'].lower(), failed
    assert not (config.patterns / 'machine-denied.vspatterns').exists()
    checks['audio_backup'] = {'frames': 11, 'byte_exact': True, 'predictability_motion_preserved_by_groove': True,
                              'midi_sequence': bench.midi[:2], 'denied_input_reported': True,
                              'current_snapshot_to_memory_5': True, 'current_buffer_reset_via_midi': True}
    checks['pattern_profile'] = verify_pattern_profile(client, helper, bench, work)

    # 11 · Firmware: build from the Korg updater, gates ----------------------
    from .. import lumon_build, updater_codec
    assert client.get('/api/firmware')['entries'] == []
    korg_wav, synthetic = lumon_build.synthetic_case()
    with lumon_build.override(synthetic):
        other = updater_codec.synthetic_updater(b'\x00' * updater_codec.IMAGE_SIZE)
        expect_failure(lambda: client.put('/api/firmware/korg', other, headers={'X-WMC-Name': 'other.wav'}), 400, 'not the official')
        expect_failure(lambda: client.put('/api/firmware/korg', b'not a firmware', headers={'X-WMC-Name': 'x.txt'}), 400)
        built = client.put('/api/firmware/korg', korg_wav, headers={'X-WMC-Name': 'synthetic.wav'})['entries']
        listed = client.get('/api/firmware')['entries']
        assert [e['id'] for e in listed] == [e['id'] for e in built] and [e['variant'] for e in listed] == ['lumon-xl', 'korg'], listed
        built_path = Path(listed[0]['path'])
        count = len(bench.streams)
        declined = client.wait(client.post('/api/firmware/send', {'id': listed[0]['id']}), answer=False)
        assert declined['outcome'] == 'cancelled_before_sending' and len(bench.streams) == count
        sent = client.wait(client.post('/api/firmware/send', {'id': listed[0]['id']}), answer=True)
        assert sent['outcome'] == 'signals_sent' and Path(bench.streams[-1]['path']).read_bytes() == lead + wav_frames(built_path)
    expect_failure(lambda: client.post('/api/firmware/send', {'id': listed[0]['id']}), 400, 'sends only')
    assert client.get('/api/firmware')['entries'] == []
    checks['firmware'] = {'empty_until_korg_added': True, 'wrong_updater_refused': True, 'built_and_listed': [e['name'] for e in listed],
                          'declined_nothing_played': True, 'pcm_byte_exact': True, 'other_firmware_retired': True}
    korg = os.environ.get('VOLCASTUDIO_KORG_UPDATER')
    if korg:
        entries = client.put('/api/firmware/korg', Path(korg).read_bytes(), headers={'X-WMC-Name': Path(korg).name})['entries']
        listed = client.get('/api/firmware')['entries']
        patch = lumon_build.load_patch()
        assert [e['id'] for e in listed] == [e['id'] for e in entries], listed
        assert [e['sha256'] for e in listed] == [patch['result']['wav_sha256'], patch['base']['wav_sha256']], listed
        built = Path(listed[0]['path']).read_bytes()
        assert hashlib.sha256(built).hexdigest() == patch['result']['wav_sha256']
        assert hashlib.sha256(updater_codec.decode(built).binary()).hexdigest() == patch['result']['image_sha256']
        assert (listed[0]['name'], listed[0]['version']) == ('DataBeat OS', '1.0'), listed
        assert listed[0]['hardware_tested'] and not listed[0]['experimental'], listed
        again = client.put('/api/firmware/korg', Path(korg).read_bytes(), headers={'X-WMC-Name': Path(korg).name})['entries']
        assert [e['id'] for e in again] == [e['id'] for e in listed] == [e['id'] for e in client.get('/api/firmware')['entries']]
        declined = client.wait(client.post('/api/firmware/send', {'id': listed[0]['id']}), answer=False)
        assert declined['outcome'] == 'cancelled_before_sending'
        checks['firmware']['korg_updater_build'] = {'bit_identical': True,
            'listed': [f'{e["name"]} {e["version"]} ({e["sha256"]})' for e in listed],
            'firmware_sha256': listed[0]['sha256'], 'image_sha256': patch['result']['image_sha256'],
            'single_production_release': True, 'final_confirmation_declined': True}
    else:
        checks['firmware']['korg_updater_build'] = 'not run: no Korg updater supplied'
    from ..firmware_check import self_check
    from .launcher import temporary_config
    firmware_work = work / 'firmware-self-check'
    firmware_work.mkdir()
    checks['firmware']['packaged_self_check'] = self_check(temporary_config(firmware_work / 'store'), firmware_work)

    # 12 · Busy guard and shutdown refusal while working ----------------------
    bench.delay = .004
    job = client.post('/api/kit/send', {'path': str(kit)})
    expect_failure(lambda: client.post('/api/draft/clear'), 409)
    expect_failure(lambda: client.post('/api/shutdown'), 409)
    client.wait(job, answer=False)
    bench.delay = 0
    checks['single_operation_guard'] = True


def verify_offline(output):
    output = Path(output)
    if output.exists():
        return 2
    output.mkdir(parents=True)
    report = {'product': 'VolcaStudio XL Browser App', 'wmc_version': WMC_VERSION, 'platform': platform.platform(),
              'machine': platform.machine(), 'python': sys.version, 'frozen': bool(getattr(sys, 'frozen', False)),
              'hardware_access': False, 'checks': {}, 'passed': False}
    try:
        from .. import __version__
        from ..transfer import tool_path, checked, converter
        report['backend_version'] = __version__
        for tool in ('ffmpeg', 'ffprobe'):
            path = tool_path(tool)
            if not path:
                raise RuntimeError(f'Missing bundled {tool}')
            version = checked([path, '-version'], capture_output=True, text=True).stdout.splitlines()[0]
            report['checks'][tool] = {'version': version, 'bundled': '/tools-bin/' in Path(path).as_posix()}
        with tempfile.TemporaryDirectory(prefix='wmc-verify-') as tmp:
            helper, server, bench, client = start(tmp)
            try:
                report['checks']['converter_sha256'] = hashlib.sha256(converter(helper.config.syro_dir).read_bytes()).hexdigest()
                work = Path(tmp) / 'work'
                work.mkdir()
                scenario(client, helper, bench, work, report['checks'])
                from .parity_verify import run as verify_parity
                verify_parity(client, helper, bench, work, report['checks'])
            finally:
                server.shutdown()
                server.server_close()
                bench.uninstall()
        report['passed'] = True
    except BaseException as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['trace'] = traceback.format_exc(limit=8)
    (output / 'report.json').write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1
