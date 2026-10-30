"""Browser App task parity through the real HTTP helper, with temporary user storage.

FFmpeg and the bundled native SYRO encoder run offline. The simulated bench
records any attempted playback or MIDI send; these tests must leave both empty.
No application window or real device is opened.
"""
import array
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
import wave
import zipfile

from volcastudio import __version__
from volcastudio.wmc.verify import Client, start, tone


def query(route, **values):
    return route + '?' + urlencode(values)


def stereo_wav(path):
    """Different left/right audio makes accidental mono source preview visible."""
    rate = 48000
    samples = array.array('h')
    for index in range(rate // 10):
        samples.extend((round(14000 * math.sin(2 * math.pi * 220 * index / rate)),
                        round(5000 * math.sin(2 * math.pi * 517 * index / rate))))
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(samples.tobytes())
    return path


def pcm(value):
    with wave.open(io.BytesIO(value), 'rb') as stream:
        return (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                stream.getnframes(), stream.readframes(stream.getnframes()))


class WMCParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.helper, self.server, self.bench, self.client = start(self.root)
        self.library = self.root / 'Fixture Library'
        self.library.mkdir()
        self.sample = tone(self.library / 'source_A3.wav', 220, seconds=.16).resolve()
        self.original = self.sample.read_bytes()

    def tearDown(self):
        try:
            self.server.shutdown()
            self.server.server_close()
            self.assertEqual(self.bench.streams, [], 'Offline task played audio')
            self.assertEqual(self.bench.midi, [], 'Offline task sent MIDI')
        finally:
            self.bench.uninstall()
            self.tmp.cleanup()

    def register(self, directory=None, name='fixture'):
        return self.client.post('/api/library/register',
                                {'directory': str(directory or self.library), 'name': name})

    def assert_refused(self, method, path, body=None, *, status=400, text=None):
        actual, data, _ = self.client.request(method, path, body, raw=True)
        self.assertEqual(actual, status, data)
        if text is not None:
            self.assertIn(text.casefold(), json.loads(data)['error'].casefold())

    def finish(self, path, body):
        done = self.client.wait(self.client.post(path, body))
        self.assertEqual(done['outcome'], 'done', done)
        return done['result']

    def assert_archive_matches(self, result, direct):
        status, data, headers = self.client.request('GET', result['download'], raw=True)
        self.assertEqual(status, 200, data)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        self.assertIn(result['name'], headers['Content-Disposition'])
        self.assertEqual(result['bytes'], len(data))
        files = {p.relative_to(direct).as_posix(): p.read_bytes()
                 for p in direct.rglob('*') if p.is_file()}
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()), set(files))
            for name, original in files.items():
                actual = archive.read(name)
                if name == 'manifest.json':
                    expected_manifest = json.loads(original)
                    actual_manifest = json.loads(actual)
                    self.assertEqual(actual_manifest, result['manifest'])
                    # Independent offline preparations have their own time;
                    # every other manifest field and all signal bytes match.
                    self.assertTrue(actual_manifest.pop('created_at'))
                    self.assertTrue(expected_manifest.pop('created_at'))
                    self.assertEqual(actual_manifest, expected_manifest)
                else:
                    self.assertEqual(hashlib.sha256(actual).hexdigest(),
                                     hashlib.sha256(original).hexdigest(), name)
            return {name: archive.read(name) for name in archive.namelist()}

    def test_register_unregister_shared_and_missing_library_references_over_http(self):
        from volcastudio.outie_model import library_roots
        entry = self.register()
        self.assertEqual(entry['id'], 'reg:fixture')
        listing = self.client.get('/api/libraries')
        self.assertIn('reg:fixture', [item['id'] for item in listing['libraries']])
        self.assertIn(self.library, library_roots(self.helper.config))
        sample_list = self.client.get(query('/api/library', id='reg:fixture'))
        self.assertEqual([item['path'] for item in sample_list['samples']], [str(self.sample)])
        self.assert_refused('POST', '/api/library/register',
                            {'directory': str(self.library), 'name': 'fixture'}, text='already registered')
        self.assert_refused('POST', '/api/library/register',
                            {'directory': str(self.library) + '\n', 'name': 'invalid'})
        self.assert_refused('POST', '/api/library/register',
                            {'directory': str(self.library), 'name': 'bad\tname'})
        self.assert_refused('POST', '/api/library/register',
                            {'directory': str(self.root / 'not-here'), 'name': 'missing'})
        missing = self.root / 'Disconnected drive' / 'Samples'
        registry = self.helper.config.libraries
        registry.write_text(registry.read_text() + f'disconnected={missing}\n')
        listing = self.client.get('/api/libraries')
        offline = next(item for item in listing['registrations'] if item['name'] == 'disconnected')
        self.assertFalse(offline['available'])
        self.assertNotIn('reg:disconnected', [item['id'] for item in listing['libraries']])
        self.client.post('/api/library/unregister', {'name': 'disconnected'})
        self.client.post('/api/library/unregister', {'name': 'fixture'})
        self.assertEqual(self.client.get('/api/libraries')['registrations'], [])
        self.assert_refused('GET', query('/api/sample/preview', path=str(self.sample)), text='outside Browser App')
        self.assertEqual(self.sample.read_bytes(), self.original)

    def test_listening_preferences_survive_a_helper_restart(self):
        from volcastudio.wmc.server import Helper, serve
        self.helper.workspace.update_settings(output={'name': 'Previously selected output', 'hostapi': 'Fixture API'})
        result = self.client.post('/api/preferences', {'autoplay': True, 'preview_mode': 'source'})
        self.assertTrue(result['autoplay'])
        self.assertEqual(result['preview_mode'], 'source')
        original = self.helper.workspace.settings_path.read_bytes()
        for body in ({'autoplay': 1}, {'autoplay': 'yes'}, {'preview_mode': 'anything'},
                     {'audio_output': 'unverified'}, {'preview_mode': None}):
            with self.subTest(body=body):
                self.assert_refused('POST', '/api/preferences', body)
        self.assertEqual(self.helper.workspace.settings_path.read_bytes(), original)
        config = self.helper.config
        self.server.shutdown()
        self.server.server_close()
        self.helper = Helper(config, bench=self.bench)
        self.server = serve(self.helper, 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.client = Client(self.server.server_address[1], self.helper.token)
        settings = self.client.get('/api/preferences')
        self.assertEqual(settings, result)
        settings = self.client.post('/api/preferences', {'autoplay': False, 'preview_mode': 'volca'})
        self.assertEqual(settings['output']['name'], 'Previously selected output')
        self.assertFalse(settings['autoplay'])

    def test_duplicate_registry_names_use_only_the_last_shared_registration(self):
        replacement = self.root / 'Replacement Library'
        replacement.mkdir()
        current = tone(replacement / 'current.wav', 660, seconds=.02).resolve()
        self.helper.config.libraries.write_text(f'fixture={self.library}\nfixture={replacement}\n')
        listing = self.client.get('/api/libraries')
        shared = [entry for entry in listing['libraries'] if entry['id'] == 'reg:fixture']
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0]['root'], str(replacement))
        self.assertEqual(len(listing['registrations']), 1)
        listed = self.client.get(query('/api/library', id='reg:fixture'))['samples']
        self.assertEqual([row['path'] for row in listed], [str(current)])
        self.assert_refused('GET', query('/api/sample/preview', path=str(self.sample), mode='source'),
                            text='outside Browser App')
        status, preview, _ = self.client.request('GET', query('/api/sample/preview',
                                             path=str(current), mode='source'), raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(preview, current.read_bytes())

    def test_global_search_and_pagination_reach_beyond_old_listing_limits(self):
        count = 20010
        large = self.root / 'Large Library'
        large.mkdir()
        # Listing needs filenames/stat metadata, not twenty thousand encoded
        # WAVs. Only the targets are audio fixtures and enter a draft.
        for index in range(count):
            (large / f'{index:05d}-placeholder.wav').touch()
        late = large / 'zz-late'
        late.mkdir()
        target = tone(late / 'zz_Harmony.wav', 330, seconds=.02).resolve()
        other = self.root / 'Other Library'
        other.mkdir()
        second = tone(other / 'late_Harmony.wav', 440, seconds=.02).resolve()
        self.register(large, 'large')
        self.register(large, 'same_root_alias')
        self.register(other, 'other')
        first = self.client.get(query('/api/library', id='reg:large', limit=250))
        self.assertEqual(len(first['samples']), 250)
        self.assertEqual(first['total'], count + 1)
        self.assertTrue(first['has_more'])
        self.assertFalse(first['truncated'])
        after_old_browser_limit = self.client.get(query('/api/library', id='reg:large', offset=3000, limit=5))
        self.assertEqual(after_old_browser_limit['samples'][0]['name'], '03000-placeholder.wav')
        end = self.client.get(query('/api/library', id='reg:large', offset=20000, limit=25))
        self.assertEqual(len(end['samples']), 11)
        self.assertEqual(end['samples'][-1]['path'], str(target))
        self.assertFalse(end['has_more'])
        found = self.client.get(query('/api/library', id='*', q='LATE harmony', limit=1))
        self.assertEqual(found['total'], 2)  # Alias roots do not duplicate audio.
        self.assertTrue(found['has_more'])
        next_page = self.client.get(query('/api/library', id='*', q='LATE harmony', offset=1, limit=1))
        self.assertFalse(next_page['has_more'])
        self.assertEqual({found['samples'][0]['path'], next_page['samples'][0]['path']},
                         {str(target), str(second)})
        draft = self.client.post('/api/draft/add', {'paths': [next_page['samples'][0]['path']]})
        self.assertEqual(draft['count'], 1)
        self.assertEqual(draft['missing'], 0)
        for values in ({'id': 'reg:missing'}, {'id': '*', 'offset': -1},
                       {'id': '*', 'limit': 0}, {'id': '*', 'limit': 1001},
                       {'id': '*', 'offset': 'not-a-number'}, {'id': '*', 'q': 'a' * 501}):
            with self.subTest(values=values):
                self.assert_refused('GET', query('/api/library', **values))

    def test_source_preview_preserves_stereo_bytes_and_volca_preview_matches_offline_chain(self):
        from volcastudio.transfer import checked, normalize_sample
        stereo = stereo_wav(self.library / 'stereo.wav').resolve()
        self.register()
        status, source, headers = self.client.request('GET', query('/api/sample/preview',
                    path=str(stereo), mode='source', pitch=0), raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'audio/wav')
        self.assertEqual(source, stereo.read_bytes())
        self.assertEqual(pcm(source)[:4], (2, 2, 48000, 4800))
        info = self.client.get(query('/api/sample/info', path=str(stereo)))
        self.assertEqual(info['format'], {'sample_rate': 48000, 'channels': 2,
                                         'bits': 16, 'codec': 'pcm_s16le'})
        for pitch in (-12, -24):
            reference = self.root / f'expected-source-{pitch}.wav'
            checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', stereo, '-af',
                     f'asetrate={48000 * 2 ** (pitch / 12)},aresample=48000',
                     '-c:a', 'pcm_s16le', reference])
            status, actual, _ = self.client.request('GET', query('/api/sample/preview',
                    path=str(stereo), mode='source', pitch=pitch), raw=True)
            self.assertEqual(status, 200)
            self.assertEqual(pcm(actual), pcm(reference.read_bytes()))
        snapshot = self.root / 'expected-mono-31250.wav'
        normalize_sample(stereo, snapshot)
        for pitch in (0, -12, -24):
            with self.subTest(pitch=pitch):
                reference = self.root / f'expected-volca-{pitch}.wav'
                checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', snapshot, '-af',
                         f'asetrate={31250 * 2 ** (pitch / 12)},aresample=44100',
                         '-c:a', 'pcm_s16le', reference])
                status, actual, _ = self.client.request('GET', query('/api/sample/preview',
                        path=str(stereo), mode='volca', pitch=pitch), raw=True)
                self.assertEqual(status, 200)
                self.assertEqual(pcm(actual), pcm(reference.read_bytes()))
                self.assertEqual(pcm(actual)[:3], (1, 2, 44100))
        self.assert_refused('GET', query('/api/sample/preview', path=str(stereo), mode='unknown'))
        self.assert_refused('GET', query('/api/sample/preview', path=str(stereo), mode='source', pitch=5))
        outside = tone(self.root / 'private.wav', 880, seconds=.02)
        self.assert_refused('GET', query('/api/sample/preview', path=str(outside), mode='source'))

    def test_additive_variants_deduplicate_and_keep_incremental_pitch_metadata_when_saved(self):
        from volcastudio.tuning import tuning_metadata
        self.register()
        self.client.put('/api/draft', {'paths': [str(self.sample)]})
        first = self.finish('/api/samples/variants', {'paths': [str(self.sample)], 'semitones': 12})
        rows = first['draft']['rows']
        variant = rows[1]['path']
        self.assertEqual([item['path'] for item in rows[:1]], [str(self.sample)])
        self.assertEqual([item['semitones'] for item in rows], [0, 12])
        self.assertEqual(first['selected'], [1])
        self.assertAlmostEqual(rows[1]['seconds'], .08, places=3)
        again = self.finish('/api/samples/variants', {'paths': [str(self.sample), str(self.sample)], 'semitones': 12})
        self.assertEqual(again['draft']['count'], 2)
        self.assertEqual(again['selected'], [1, 1])
        lowered = self.finish('/api/samples/variants', {'paths': [variant], 'semitones': -7})
        self.assertEqual([item['semitones'] for item in lowered['draft']['rows']], [0, 12, 5])
        third = Path(lowered['draft']['rows'][2]['path'])
        metadata = tuning_metadata(third)
        self.assertEqual(metadata['source'], str(self.sample))
        self.assertEqual(metadata['semitones'], 5)
        self.assertEqual(metadata['increment'], -7)
        self.assertAlmostEqual(metadata['factor'], 2 ** (5 / 12))
        changed = self.finish('/api/draft/varispeed', {'indices': [2], 'semitones': -5})
        self.assertEqual([item['semitones'] for item in changed['draft']['rows']], [0, 12, 0])
        before = self.client.get('/api/draft')
        for values in ({'paths': [str(self.sample)], 'semitones': 0},
                       {'paths': [str(self.sample)], 'semitones': 100},
                       {'paths': [str(self.sample)], 'semitones': True},
                       {'paths': [str(self.root / 'outside.wav')], 'semitones': 12}):
            with self.subTest(values=values):
                self.assert_refused('POST', '/api/samples/variants', values)
        self.assertEqual(self.client.get('/api/draft'), before)
        saved = self.client.post('/api/kit/save', {'name': 'variants'})
        reopened = self.client.post('/api/kit/open', {'path': saved['path']})
        self.assertEqual([item['semitones'] for item in reopened['rows']], [0, 12, 0])
        for item in reopened['rows'][1:]:
            self.assertTrue(Path(item['path']).with_suffix('.json').is_file())
            self.assertEqual(tuning_metadata(item['path'])['semitones'], item['semitones'])
        self.assertEqual(Path(reopened['rows'][0]['path']).read_bytes(), self.original)
        self.assertEqual(self.sample.read_bytes(), self.original)

    def test_library_transposition_replaces_sources_already_in_the_workbench(self):
        self.register()
        self.client.put('/api/draft', {'paths': [str(self.sample)]})
        result = self.finish('/api/samples/variants', {'paths': [str(self.sample)],
                              'semitones': 7, 'replace_existing': True})
        self.assertEqual(result['draft']['count'], 1)
        self.assertEqual(result['draft']['rows'][0]['semitones'], 7)
        self.assertEqual(self.sample.read_bytes(), self.original)
        self.assert_refused('POST', '/api/samples/variants', {'paths': [str(self.sample)],
                            'semitones': 7, 'replace_existing': 'yes'})

    def test_diagnostics_reads_installation_without_audio_or_midi_enumeration(self):
        with patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('Audio enumeration forbidden')), \
             patch('volcastudio.desktop_audio._midi', side_effect=AssertionError('MIDI enumeration forbidden')), \
             patch.object(self.bench, 'query_devices', side_effect=AssertionError('No device enumeration')), \
             patch.object(self.bench, 'get_output_names', side_effect=AssertionError('No MIDI enumeration')):
            report = self.client.get('/api/system/status')
        self.assertEqual(report['version'], __version__)
        self.assertFalse(report['hardware_access'])
        self.assertIn('SYRO encoder', [item['name'] for item in report['checks']])
        self.assertEqual(report['paths']['libraries'], str(self.helper.config.libraries))
        self.assertEqual(self.client.request('GET', '/api/system/status', token=False, raw=True)[0], 401)

    def test_cancelled_export_removes_partial_files_and_publishes_no_download(self):
        self.register()
        self.client.put('/api/draft', {'paths': [str(self.sample)]})
        saved = self.client.post('/api/kit/save', {'name': 'cancel-export'})
        entered, resume = threading.Event(), threading.Event()

        def prepare_until_cancelled(kit, folder, syro_dir):
            folder.mkdir()
            (folder / 'partial.wav').write_bytes(b'partial data')
            entered.set()
            if not resume.wait(10):
                raise AssertionError('Cancellation was never requested')
            return {'count': 1}

        with patch('volcastudio.transfer.prepare', prepare_until_cancelled):
            job = self.client.post('/api/kit/export-signals', {'path': saved['path']})
            try:
                self.assertTrue(entered.wait(5))
                self.client.post('/api/job/cancel', {'id': job['id']})
            finally:
                resume.set()
            done = self.client.wait(job)
        self.assertEqual(done['outcome'], 'cancelled', done)
        self.assertIsNone(done['result'])
        self.assertEqual(self.helper.workspace.exports.files, {})
        self.assertEqual(list(self.helper.workspace.exports.cache.iterdir()), [])

    def test_kit_signal_download_contains_every_shared_encoder_file_without_playback(self):
        from volcastudio.transfer import prepare
        self.register()
        self.client.put('/api/draft', {'paths': [str(self.sample)]})
        saved = self.client.post('/api/kit/save', {'name': 'downloadable'})
        direct = self.root / 'direct-kit-signals'
        prepare(saved['path'], direct, self.helper.config.syro_dir)
        result = self.finish('/api/kit/export-signals', {'path': saved['path']})
        files = self.assert_archive_matches(result, direct)
        self.assertIn('clear-00.wav', files)
        self.assertIn('clear-99.wav', files)
        self.assertIn('upload-00.wav', files)
        self.assertIn('samples/00.wav', files)
        self.assertEqual(len([name for name in files if name.startswith('clear-')]), 100)
        self.assertEqual(result['manifest']['count'], 1)
        self.assertEqual(result['manifest']['sample_rate'], 31250)
        self.assertFalse((self.helper.config.state / 'last-transfer.json').exists())
        for ident in ('unknown', '../manifest.json', str(self.sample), ''):
            with self.subTest(ident=ident):
                self.assert_refused('GET', query('/api/prepared/download', id=ident))
        self.assert_refused('POST', '/api/kit/export-signals', {'path': str(self.library)})
        self.assertEqual(self.sample.read_bytes(), self.original)

    def test_pattern_signal_download_preserves_stored_selection_and_explicit_current_destination(self):
        from volcastudio.pattern_transfer import prepare_patterns
        from volcastudio.patterns import bank_to_json
        from volcastudio.wmc.bench import bench_bank
        bank = bench_bank()
        uploaded = self.client.put('/api/patterns/upload', bank_to_json(bank).encode(),
                                   headers={'X-WMC-Name': 'fixture.vspatterns'})
        original = [item['sha256'] for item in uploaded['patterns']]
        direct_stored = self.root / 'direct-stored'
        prepare_patterns([bank[1], bank[7]], direct_stored, self.helper.config.syro_dir, 'lumon-xl-internal')
        result = self.finish('/api/patterns/export-signals', {'slots': '2,8'})
        files = self.assert_archive_matches(result, direct_stored)
        self.assertEqual(result['manifest']['slots'], [1, 7])
        self.assertEqual(set(files), {'pattern-01.bin', 'pattern-01.wav', 'pattern-07.bin',
                                     'pattern-07.wav', 'manifest.json'})
        for value in (0, 11, True, '7'):
            with self.subTest(destination=value):
                self.assert_refused('POST', '/api/patterns/export-signals',
                                    {'slots': '', 'current_destination': value})
        self.assert_refused('POST', '/api/patterns/export-signals', {'slots': ''})
        direct_current = self.root / 'direct-current'
        prepare_patterns([bank[-1]], direct_current, self.helper.config.syro_dir, 'lumon-xl-internal', 6)
        current = self.finish('/api/patterns/export-signals', {'slots': '', 'current_destination': 7})
        files = self.assert_archive_matches(current, direct_current)
        self.assertEqual(set(files), {'pattern-06.bin', 'pattern-06.wav', 'manifest.json'})
        self.assertEqual(current['manifest']['slots'], [6])
        self.assertIsNone(current['manifest']['patterns'][0]['source_slot'])
        self.assertNotEqual(files['pattern-06.bin'], bank[6].data)
        self.assertEqual([item['sha256'] for item in self.client.get('/api/patterns')['bank']['patterns']], original)
        self.assertFalse((self.helper.config.state / 'last-pattern-transfer.json').exists())

    def test_new_mutations_require_session_token_and_same_origin(self):
        foreign = Client(self.client.port, self.client.token, origin='https://unrelated.example')
        operations = [('/api/library/register', {'directory': str(self.library), 'name': 'refused'}),
                      ('/api/library/unregister', {'name': 'refused'}),
                      ('/api/preferences', {'autoplay': True}),
                      ('/api/samples/variants', {'paths': [str(self.sample)], 'semitones': 12}),
                      ('/api/kit/export-signals', {'path': str(self.library)}),
                      ('/api/patterns/export-signals', {'slots': 'all'})]
        for path, body in operations:
            with self.subTest(path=path):
                self.assertEqual(self.client.request('POST', path, body, token=False, raw=True)[0], 401)
                self.assertEqual(foreign.request('POST', path, body, raw=True)[0], 403)
        self.assertFalse(self.helper.config.libraries.exists())
        self.assertEqual(self.client.get('/api/draft')['count'], 0)
        self.assertFalse(self.helper.workspace.settings_path.exists())


if __name__ == '__main__':
    unittest.main()
