"""Browser App local helper: offline acceptance, launcher, storage sharing and safety.

Only temporary storage, generated audio and the simulated bench devices are
used. No audio/MIDI device is enumerated and no browser window is opened
(a fake Chrome executable records the arguments it would receive).
"""
import http.client
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def isolated_env(root):
    env = dict(os.environ)
    for key in [k for k in env if k.startswith('VOLCASTUDIO_')]:
        env.pop(key)
    env.update(XDG_CONFIG_HOME=str(root / 'config'), XDG_DATA_HOME=str(root / 'data'),
               XDG_STATE_HOME=str(root / 'state'), XDG_CACHE_HOME=str(root / 'cache'),
               HOME=str(root / 'home'), PYTHONPATH=str(ROOT), VOLCASTUDIO_SYRO_DIR=str(ROOT / 'build/syro'),
               VOLCASTUDIO_WMC_DEBUG='1')
    return env


def read_link(proc, timeout=60):
    deadline = time.monotonic() + timeout
    lines = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line)
        if line.startswith('http://127.0.0.1:'):
            return line.strip()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    raise AssertionError(f'No link printed (exit {proc.poll()}): ' + ''.join(lines) + proc.stderr.read())


def call(link, method, path, body=None):
    url, token = link.split('#k=')
    port = int(url.rsplit(':', 1)[1].strip('/'))
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    data = json.dumps(body or {}).encode() if method != 'GET' else None
    headers = {'X-WMC-Token': token, 'Host': f'127.0.0.1:{port}'}
    if data is not None:
        headers['Content-Length'] = str(len(data))
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    return response.status, json.loads(response.read() or b'null')


class OfflineAcceptanceTests(unittest.TestCase):
    def test_offline_verification_handles_an_aliased_temporary_root(self):
        from volcastudio.wmc.verify import verify_offline
        original = tempfile.TemporaryDirectory
        with original() as tmp:
            root = Path(tmp).resolve()
            real = root / 'real'
            real.mkdir()
            alias = root / 'alias'
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('Creating directory symlinks is unavailable on this host')

            def through_alias(*args, **kwargs):
                if kwargs.get('prefix') == 'wmc-verify-':
                    kwargs['dir'] = alias
                return original(*args, **kwargs)

            output = root / 'report'
            with patch('volcastudio.wmc.verify.tempfile.TemporaryDirectory', through_alias):
                self.assertEqual(verify_offline(output), 0, (output / 'report.json').read_text())
            report = json.loads((output / 'report.json').read_text())
            self.assertTrue(report['checks']['library_variants_and_listening']['source_bytes_exact'])

    def test_full_offline_scenario_passes(self):
        from volcastudio.wmc.verify import verify_offline
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report'
            self.assertEqual(verify_offline(output), 0, (output / 'report.json').read_text())
            report = json.loads((output / 'report.json').read_text())
            self.assertTrue(report['passed'])
            self.assertFalse(report['hardware_access'])
            for key in ('security_boundary', 'kit_transfer', 'tonal_alignment', 'audio_backup', 'firmware',
                        'kit_save_reopen_exchange', 'patterns_grooves', 'explicit_devices'):
                self.assertIn(key, report['checks'])
            self.assertTrue(report['checks']['kit_transfer']['pcm_byte_exact'])
            self.assertEqual(verify_offline(output), 2)  # never reuses an existing directory


class HelperTests(unittest.TestCase):
    def setUp(self):
        from volcastudio.wmc.verify import start
        self.tmp = tempfile.TemporaryDirectory()
        self.helper, self.server, self.bench, self.client = start(self.tmp.name)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.bench.uninstall()
        self.tmp.cleanup()

    def test_unread_body_never_corrupts_the_next_keep_alive_request(self):
        port = self.server.server_address[1]
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        headers = {'X-WMC-Token': self.helper.token, 'Host': f'127.0.0.1:{port}', 'Content-Type': 'application/json'}
        for _ in range(3):
            connection.request('POST', '/api/heartbeat', body=b'{"ignored": "body"}', headers=headers)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
        connection.close()

    def test_storage_is_shared_with_the_other_editions(self):
        from volcastudio.libraries import kit_directories
        from volcastudio.outie_model import library_roots
        from volcastudio.wmc.verify import tone
        config = self.helper.config
        shared = Path(self.tmp.name) / 'shared-library'
        shared.mkdir()
        tone(shared / 'hat.wav', 4000, seconds=.1)
        config.libraries.parent.mkdir(parents=True, exist_ok=True)
        config.libraries.write_text(f'shared_lib={shared}\n')
        before = config.libraries.read_bytes()
        libraries = self.client.get('/api/libraries')['libraries']
        self.assertIn('reg:shared_lib', [l['id'] for l in libraries])
        sample = self.client.get('/api/library?id=reg%3Ashared_lib')['samples'][0]['path']
        self.client.put('/api/draft', {'paths': [sample]})
        saved = self.client.post('/api/kit/save', {'name': 'shared-kit'})
        self.assertIn(Path(saved['path']), kit_directories(config))
        self.assertIn(config.kits.resolve(), library_roots(config))
        self.assertEqual(config.libraries.read_bytes(), before)  # registrations untouched

    def test_draft_survives_a_restart(self):
        from volcastudio.wmc.verify import tone
        from volcastudio.wmc.workspace import Workspace
        path = tone(Path(self.tmp.name) / 'keep.wav', 440)
        uploaded = self.client.upload('keep', 'keep.wav', path.read_bytes())['path']
        self.client.put('/api/draft', {'paths': [uploaded, uploaded], 'name': 'later'})
        again = Workspace(self.helper.config).draft()
        self.assertEqual([r['path'] for r in again['rows']], [uploaded, uploaded])
        self.assertEqual(again['name'], 'later')

    def test_kit_zip_with_unsafe_paths_is_refused(self):
        archive = Path(self.tmp.name) / 'evil.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('kit/../../escape.wav', b'RIFF')
        status, data, _ = self.client.request('PUT', '/api/kit/import', archive.read_bytes(),
                                              headers={'X-WMC-Name': 'evil'}, raw=True)
        self.assertEqual(status, 400)
        self.assertIn(b'unsafe', data)
        self.assertFalse((self.helper.config.kits / 'evil').exists())
        self.assertFalse((Path(self.tmp.name) / 'escape.wav').exists())

    def test_korg_updater_upload_builds_lumon_os_xl(self):
        import io
        import zipfile
        from volcastudio import lumon_build
        korg_wav, patch_document = lumon_build.synthetic_case()
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('synthetic.wav', korg_wav)
        with lumon_build.override(patch_document):
            self.assertEqual(self.client.get('/api/firmware')['entries'], [])
            status, body, _ = self.client.request('PUT', '/api/firmware/korg', b'RIFF' + bytes(60),
                                                  headers={'X-WMC-Name': 'x.wav'}, raw=True)
            self.assertEqual(status, 400)
            for route in ('/api/firmware/import', '/api/firmware/lumon/begin'):
                self.assertEqual(self.client.request('PUT' if route.endswith('import') else 'POST', route, b'', raw=True)[0], 404)
            entries = self.client.put('/api/firmware/korg', archive.getvalue(), headers={'X-WMC-Name': 'synthetic.zip'})['entries']
            listed = self.client.get('/api/firmware')['entries']
        self.assertEqual([e['id'] for e in listed], [e['id'] for e in entries])
        self.assertEqual([e['variant'] for e in listed], ['lumon-xl', 'korg'])
        self.assertEqual(listed[1]['provenance']['file'], 'synthetic.zip')
        self.assertTrue(all(e['installable'] for e in listed))
        # Outside the synthetic release, the shipped patch offers nothing until the Korg updater is added.
        self.assertEqual(self.client.get('/api/firmware')['entries'], [])

    def test_decode_recorded_backup_into_a_new_bank(self):
        import wave
        from volcastudio.patterns import load_bank
        from volcastudio.wmc.bench import backup_signal, bench_bank
        recording = Path(self.tmp.name) / 'recording.wav'
        with wave.open(str(recording), 'wb') as stream:
            stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            stream.writeframes(backup_signal(Path(self.tmp.name) / 'signal'))
        result = self.client.put('/api/patterns/decode', recording.read_bytes(), headers={'X-WMC-Name': 'decoded'})
        self.assertEqual([p.sha256 for p in load_bank(result['path'])], [p.sha256 for p in bench_bank()])
        status, data, _ = self.client.request('PUT', '/api/patterns/decode', recording.read_bytes()[:200000],
                                              headers={'X-WMC-Name': 'partial'}, raw=True)
        self.assertEqual(status, 400)
        self.assertFalse((self.helper.config.patterns / 'partial.vspatterns').exists())

    def test_cancelled_offline_work_leaves_the_draft_unchanged(self):
        from volcastudio import desktop_audio
        from volcastudio.wmc.verify import tone
        path = tone(Path(self.tmp.name) / 'slow.wav', 330)
        uploaded = self.client.upload('slow', 'slow.wav', path.read_bytes())['path']
        before = self.client.put('/api/draft', {'paths': [uploaded]})
        def slow(*args, **kwargs):
            while True:
                desktop_audio.check_cancelled()
                time.sleep(.01)
        with patch('volcastudio.tuning.varispeed', side_effect=slow):
            job = self.client.post('/api/draft/varispeed', {'indices': [0], 'semitones': 5})
            self.client.post('/api/job/cancel', {'id': job['id']})
            done = self.client.wait(job)
        self.assertEqual(done['outcome'], 'cancelled')
        after = self.client.get('/api/draft')
        self.assertEqual([r['path'] for r in after['rows']], [r['path'] for r in before['rows']])

    def test_static_files_are_an_allow_list(self):
        for path in ('/C:\\Windows\\win.ini', '/..\\workspace.py', '/\\\\host\\share\\a.js', '/workspace.py', '/%2e%2e/server.py'):
            status, _, _ = self.client.request('GET', path, token=False, raw=True)
            self.assertEqual(status, 404, path)
        status, data, headers = self.client.request('HEAD', '/api/patterns/download?path=x', raw=True)
        self.assertEqual(status, 400)

    def test_late_answer_cannot_turn_a_decline_into_signals_sent(self):
        from volcastudio.wmc.jobs import Jobs
        jobs = Jobs()
        def operation(job, target):
            approved = job.confirm({'count': 1})
            time.sleep(.2)  # cleanup window after the decision
            return 0
        job = jobs.start('kit', 'race', operation, device_target='sd:0')
        while job.state != 'confirm':
            time.sleep(.01)
        jobs.cancel(job.id)
        time.sleep(.05)
        with self.assertRaises(ValueError):
            jobs.answer(job.id, True)
        while job.state != 'finished':
            time.sleep(.01)
        self.assertEqual(job.outcome, 'cancelled_before_sending')

    def test_kit_send_survives_a_disconnected_console(self):
        from volcastudio.wmc.verify import tone
        path = tone(Path(self.tmp.name) / 'pipe.wav', 440, seconds=.03)
        uploaded = self.client.upload('pipe', 'pipe.wav', path.read_bytes())['path']
        self.client.put('/api/draft', {'paths': [uploaded]})
        kit = self.client.post('/api/kit/save', {'name': 'pipe-kit'})['path']
        self.client.post('/api/devices/select', {'output': 'Studio bench::Bench recorder → SYNC IN (silent)'})
        reader, writer = os.pipe()
        os.close(reader)  # the desktop launcher/terminal has exited
        stream = os.fdopen(writer, 'w', buffering=1)
        try:
            with patch.object(sys, 'stdout', stream), patch.object(sys, 'stderr', stream):
                done = self.client.wait(self.client.post('/api/kit/send', {'path': kit}), answer=True)
            self.assertEqual(done['outcome'], 'signals_sent',
                             (done, getattr(self.helper.jobs.current, 'trace', None)))
            self.assertIsNone(done['error'])
            self.assertEqual(len(self.bench.streams), 101)
            self.assertTrue(all(s['complete'] for s in self.bench.streams))
        finally:
            try:
                stream.close()
            except BrokenPipeError:
                pass

    def test_unanswered_confirmation_is_declined_after_goodbye(self):
        from volcastudio.wmc.verify import tone
        path = tone(Path(self.tmp.name) / 'g.wav', 440)
        uploaded = self.client.upload('g', 'g.wav', path.read_bytes())['path']
        self.client.put('/api/draft', {'paths': [uploaded]})
        kit = self.client.post('/api/kit/save', {'name': 'goodbye-kit'})['path']
        self.client.post('/api/devices/select', {'output': 'Studio bench::Bench recorder → SYNC IN (silent)'})
        job = self.client.post('/api/kit/send', {'path': kit})
        while self.client.get('/api/job')['job']['state'] != 'confirm':
            time.sleep(.05)
        self.client.request('POST', '/api/bye', self.helper.token.encode(), token=False, raw=True)
        self.helper.goodbye -= 60
        self.helper.idle()
        done = self.client.wait(job)
        self.assertEqual(done['outcome'], 'cancelled_before_sending')
        self.assertEqual(self.bench.streams, [])

    def test_symlinked_library_is_never_listed_written_or_removed(self):
        outside = Path(self.tmp.name) / 'my-real-samples'
        outside.mkdir()
        (outside / 'keep.txt').write_text('mine')
        link = self.helper.config.data / 'wmc/libraries/linked'
        link.symlink_to(outside)
        ids = [l['id'] for l in self.client.get('/api/libraries')['libraries']]
        self.assertNotIn('wmc:linked', ids)
        from volcastudio.wmc.verify import ApiFailure, tone
        sample = tone(Path(self.tmp.name) / 's.wav', 440)
        with self.assertRaises(ApiFailure):
            self.client.upload('linked', 's.wav', sample.read_bytes())
        with self.assertRaises(ApiFailure):
            self.client.post('/api/library/remove', {'id': 'wmc:linked'})
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['keep.txt'])

    def test_corrupt_inputs_get_an_answer(self):
        archive = Path(self.tmp.name) / 'corrupt.zip'
        import zipfile as z
        with z.ZipFile(archive, 'w', compression=z.ZIP_DEFLATED) as stream:
            stream.writestr('kit/a.wav', b'RIFF' + bytes(5000))
        data = bytearray(archive.read_bytes())
        data[60:90] = bytes(30)
        status, body, _ = self.client.request('PUT', '/api/kit/import', bytes(data), headers={'X-WMC-Name': 'corrupt'}, raw=True)
        self.assertIn(status, (400, 500))
        self.assertIn(b'error', body)
        status, body, _ = self.client.request('PUT', '/api/patterns/decode', b'not a wav at all', headers={'X-WMC-Name': 'nope'}, raw=True)
        self.assertIn(status, (400, 500))
        self.assertIn(b'error', body)
        self.assertEqual(self.client.request('GET', '/api/state', headers={'Content-Length': '\u00b2'}, raw=True)[0], 200)

    def test_current_buffer_midi_reset_only_with_neutral_patterns(self):
        from volcastudio.wmc.verify import ApiFailure
        from volcastudio.wmc.bench import bench_bank
        from volcastudio.patterns import save_bank
        self.client.post('/api/devices/select', {'output': 'Studio bench::Bench recorder → SYNC IN (silent)', 'midi': 'Bench MIDI → Volca MIDI IN'})
        path = save_bank(self.helper.config.patterns / 'captured.vspatterns', bench_bank())
        self.client.post('/api/patterns/open', {'path': str(path)})
        with self.assertRaisesRegex(ApiFailure, 'neutral'):
            self.client.post('/api/patterns/send', {'slots': '1', 'reset_current_via_midi': True})
        self.client.post('/api/patterns/reset', {'slots': '1'})
        job = self.client.post('/api/patterns/send', {'slots': '1', 'reset_current_via_midi': True})
        self.assertEqual(self.client.wait(job, answer=False)['outcome'], 'cancelled_before_sending')

    def test_idle_and_goodbye(self):
        self.helper.idle_seconds = 0
        self.helper.last_seen -= 1  # coarse monotonic clocks (Windows) may not have advanced
        self.assertTrue(self.helper.idle())
        self.helper.idle_seconds = 600
        self.helper.touch()
        self.assertFalse(self.helper.idle())
        status, _, _ = self.client.request('POST', '/api/bye', b'wrong-token', token=False, raw=True)
        self.assertEqual(status, 204)
        self.assertIsNone(self.helper.goodbye)
        self.client.request('POST', '/api/bye', self.helper.token.encode(), token=False, raw=True)
        self.assertIsNotNone(self.helper.goodbye)
        self.helper.goodbye -= 60
        self.assertTrue(self.helper.idle())


class LauncherTests(unittest.TestCase):
    def test_single_instance_reopens_and_close_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = isolated_env(Path(tmp))
            first = subprocess.Popen([sys.executable, '-m', 'volcastudio.wmc', '--no-browser', '--port', '0'],
                                     cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                link = read_link(first)
                info = Path(tmp) / 'state/volcastudio/wmc/instance.json'
                self.assertTrue(info.is_file())
                if os.name != 'nt':
                    self.assertEqual(info.stat().st_mode & 0o777, 0o600)
                second = subprocess.run([sys.executable, '-m', 'volcastudio.wmc', '--no-browser'], cwd=ROOT, env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertIn(link, second.stdout)  # same helper, same private link
                status, state = call(link, 'GET', '/api/state')
                self.assertEqual(status, 200)
                status, _ = call(link, 'POST', '/api/shutdown')
                self.assertEqual(status, 200)
                self.assertEqual(first.wait(timeout=15), 0)
                self.assertFalse(info.exists())
            finally:
                if first.poll() is None:
                    first.kill()
                first.wait()
                first.stdout.close()
                first.stderr.close()

    @unittest.skipIf(os.name == 'nt', 'The fake browser is a script with a shebang')
    def test_opens_chrome_as_an_app_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = root / 'chrome-args.json'
            fake = root / 'fake-chrome'
            fake.write_text(f'#!{sys.executable}\nimport json, sys\nopen({str(record)!r}, "w").write(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            env = isolated_env(root)
            env['VOLCASTUDIO_WMC_CHROME'] = str(fake)
            proc = subprocess.Popen([sys.executable, '-m', 'volcastudio.wmc', '--port', '0'], cwd=ROOT, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 60
                while not record.exists() and time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(.1)
                if not record.exists():
                    if proc.poll() is None:
                        proc.kill()
                    self.fail(f'Chrome was not opened (exit {proc.wait()}): {proc.stderr.read()}')
                args = json.loads(record.read_text())
                self.assertEqual(args[0], '--new-window')
                self.assertRegex(args[1], r'^--app=http://127\.0\.0\.1:\d+/#c=[A-Za-z0-9_-]{30,}$')
                info = json.loads((root / 'state/volcastudio/wmc/instance.json').read_text())
                self.assertNotIn(info['token'], ' '.join(args))  # the token never reaches a command line
                url, code = args[1][len('--app='):].split('#c=')
                port = int(url.rsplit(':', 1)[1].strip('/'))
                def claim():
                    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
                    body = json.dumps({'code': code}).encode()
                    connection.request('POST', '/api/session/claim', body=body, headers={
                        'Host': f'127.0.0.1:{port}', 'Origin': f'http://127.0.0.1:{port}', 'Content-Length': str(len(body))})
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                status, data = claim()
                self.assertEqual((status, data['token']), (200, info['token']))
                self.assertEqual(claim()[0], 401)  # single use
                link = f'{url}#k={data["token"]}'
                self.assertEqual(call(link, 'GET', '/api/state')[1]['browser_note'], None)
                call(link, 'POST', '/api/shutdown')
                self.assertEqual(proc.wait(timeout=15), 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
                proc.stderr.close()

    def test_missing_chrome_opens_default_browser_with_notice(self):
        from volcastudio.wmc import launcher
        with patch.object(launcher, 'find_chrome', return_value=None), \
                patch.object(launcher.webbrowser, 'open', return_value=True) as browser:
            self.assertEqual(launcher.open_window('http://127.0.0.1:1/#k=abc'), 'other')
        self.assertEqual(browser.call_args.args[0], 'http://127.0.0.1:1/#k=abc&browser=other')
        with patch.dict(os.environ, {'VOLCASTUDIO_WMC_CHROME': '/nonexistent/chrome'}):
            self.assertIsNone(launcher.find_chrome())

    def test_linux_menu_entry_is_explicit_and_never_replaces_unrelated_files(self):
        from volcastudio.wmc import launcher
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_DATA_HOME': tmp}):
            with self.assertRaises(ValueError):
                launcher.install_linux_menu()  # source checkouts are not registered
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'platform', 'linux'), \
                    patch.object(sys, 'executable', str(Path(tmp) / 'VolcaStudio XL Browser App/VolcaStudio XL Browser App')):
                path = launcher.install_linux_menu()
                text = path.read_text()
                self.assertIn('Exec="', text)
                self.assertIn('X-VolcaStudio-WMC=true', text)
                path.write_text('[Desktop Entry]\nName=Other\n')
                with self.assertRaises(ValueError):
                    launcher.install_linux_menu()
                self.assertEqual(path.read_text(), '[Desktop Entry]\nName=Other\n')

    def test_console_symbols_cannot_abort_a_transfer(self):
        import io
        from volcastudio import status
        from volcastudio.wmc.launcher import robust_console
        class LegacyTerminal(io.TextIOWrapper):
            def isatty(self):
                return True  # like Windows NUL
        stream = LegacyTerminal(io.BytesIO(), encoding='cp1252')
        with patch.object(sys, 'stdout', stream):
            with self.assertRaises(UnicodeEncodeError):
                status.progress('Retiring slots', 1, 100)
            robust_console()
            status.progress('Retiring slots', 2, 100)  # no exception now

    def test_smoke_test_uses_no_devices_or_user_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = isolated_env(Path(tmp))
            result = subprocess.run([sys.executable, '-m', 'volcastudio.wmc', '--smoke-test'], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((Path(tmp) / 'data').exists())


class PackagingTests(unittest.TestCase):
    def test_mac_metadata_includes_privacy_and_agent_mode(self):
        import ast
        from tools.build_wmc import add_macos_metadata
        from volcastudio.wmc import WMC_VERSION
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / 'app.spec'
            spec.write_text("app = BUNDLE(coll, name='VolcaStudio XL Browser App.app', info_plist={'Existing': 'kept'})\n")
            add_macos_metadata(spec)
            call_node = ast.parse(spec.read_text()).body[0].value
            metadata = ast.literal_eval(next(k.value for k in call_node.keywords if k.arg == 'info_plist'))
            self.assertEqual(metadata['Existing'], 'kept')
            self.assertTrue(metadata['LSUIElement'])
            self.assertIn('Volca', metadata['NSMicrophoneUsageDescription'])
            self.assertEqual(metadata['CFBundleShortVersionString'], WMC_VERSION)

    def test_icon_is_a_valid_png(self):
        from tools.build_wmc import write_png
        with tempfile.TemporaryDirectory() as tmp:
            data = write_png(Path(tmp) / 'icon.png', 64).read_bytes()
            self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(int.from_bytes(data[16:20], 'big'), 64)

    def test_interface_assets_have_no_external_or_inline_code(self):
        web = ROOT / 'volcastudio/wmc/web'
        html = (web / 'index.html').read_text()
        self.assertNotIn('<script>', html)
        self.assertNotIn('style="', html)
        for asset in web.iterdir():
            text = asset.read_text()
            # Only links the user opens: Chrome, and Korg's official updater download.
            self.assertNotRegex(text, r'https?://(?!www\.w3\.org|www\.google\.com/chrome|www\.korg\.com/us/support/download/)')
        self.assertNotIn('MWC', html + (web / 'wmc.js').read_text())


if __name__ == '__main__':
    unittest.main()
