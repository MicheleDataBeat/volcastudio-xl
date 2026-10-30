import contextlib
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from volcastudio import lumon_build, updater_codec
from volcastudio.firmware import (_store, add_korg_updater, current_identities, inspect_firmware,
                                  list_firmware, transfer_firmware)

KORG_WAV, PATCH = lumon_build.synthetic_case()
EXPERIMENTAL = copy.deepcopy(PATCH)
EXPERIMENTAL['release']['experimental'] = True
REAL_KORG = os.environ.get('VOLCASTUDIO_KORG_UPDATER')


class FirmwareTests(unittest.TestCase):
    patch_document = PATCH

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = SimpleNamespace(data=root / 'data', state=root / 'state')
        self.korg = root / 'synthetic.wav'
        self.korg.write_bytes(KORG_WAV)
        self.dependencies = patch('volcastudio.transfer.audio_dependencies')
        self.dependencies.start()
        self.addCleanup(self.dependencies.stop)
        override = lumon_build.override(self.patch_document)
        override.__enter__()
        self.addCleanup(override.__exit__, None, None, None)

    def add(self, source=None):
        return add_korg_updater(source or self.korg, self.config)

    def databeat(self):
        return self.add()[0]

    def test_library_is_empty_until_the_korg_updater_is_added(self):
        self.assertEqual(list_firmware(self.config), [])
        databeat, korg = self.add()
        self.assertEqual([e['id'] for e in list_firmware(self.config)], list(current_identities()))
        self.assertEqual((databeat['variant'], korg['variant']), ('lumon-xl', 'korg'))
        self.assertTrue(all(e['installable'] and not e['experimental'] for e in (databeat, korg)))
        self.assertEqual(Path(korg['path']).read_bytes(), KORG_WAV)
        built = Path(databeat['path']).read_bytes()
        self.assertEqual(hashlib.sha256(built).hexdigest(), PATCH['result']['wav_sha256'])
        self.assertEqual(updater_codec.decode(built).version, (1, 60))
        self.assertEqual(korg['provenance']['supplied_by'], 'user')
        self.assertEqual(databeat['provenance']['built_from'], korg['id'])

    def test_the_korg_zip_is_accepted_unchanged(self):
        archive = Path(self.temp.name) / 'download.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('release_note_e.txt', 'notes')
            zipped.writestr('folder/synthetic.wav', KORG_WAV)
        databeat, korg = self.add(archive)
        self.assertEqual(Path(korg['path']).read_bytes(), KORG_WAV)
        self.assertEqual(korg['provenance']['file'], 'download.zip')
        empty = Path(self.temp.name) / 'other.zip'
        with zipfile.ZipFile(empty, 'w') as zipped:
            zipped.writestr('readme.txt', 'nothing')
        with self.assertRaisesRegex(ValueError, 'does not contain synthetic.wav'):
            self.add(empty)

    def test_other_files_are_refused_and_nothing_is_saved(self):
        other = Path(self.temp.name) / 'other.wav'
        other.write_bytes(updater_codec.synthetic_updater(b'\x00' * updater_codec.IMAGE_SIZE))
        with self.assertRaisesRegex(ValueError, 'not the official'):
            self.add(other)
        text = Path(self.temp.name) / 'notes.txt'
        text.write_text('hello')
        with self.assertRaisesRegex(ValueError, 'Choose synthetic.zip'):
            self.add(text)
        self.assertFalse((self.config.data / 'firmware').exists())

    def test_a_changed_patch_saves_nothing(self):
        broken = copy.deepcopy(PATCH)
        operation = next(op for op in broken['operations'] if op[0] == 'lit')
        operation[2] = ('00' if operation[2][:2] != '00' else '11') + operation[2][2:]
        with lumon_build.override(broken), self.assertRaisesRegex(ValueError, 'differs from DataBeat OS'):
            self.add()
        self.assertFalse((self.config.data / 'firmware').exists())

    def test_saved_name_is_presented_as_stored_without_rewriting(self):
        entry = self.add()[0]
        manifest = Path(entry['path']).with_name('manifest.json')
        record = json.loads(manifest.read_text())
        record['name'] = 'Owner label'
        manifest.write_text(json.dumps(record))
        before = manifest.read_bytes()
        displayed = list_firmware(self.config)[0]
        self.assertEqual(displayed['name'], 'Owner label')
        self.assertEqual(displayed['sha256'], entry['sha256'])
        self.assertEqual(displayed['id'], entry['id'])
        self.assertEqual(manifest.read_bytes(), before)

    def test_adding_again_is_idempotent(self):
        first = self.add()
        manifest = Path(first[0]['path']).with_name('manifest.json')
        before = manifest.read_bytes()
        second = self.add()
        self.assertEqual([e['id'] for e in second], [e['id'] for e in first])
        self.assertEqual(manifest.read_bytes(), before)

    def test_damaged_entry_is_set_aside_and_rebuilt(self):
        databeat = self.databeat()
        Path(databeat['path']).write_bytes(b'damaged')
        self.assertEqual([e['variant'] for e in list_firmware(self.config)], ['korg'])
        rebuilt = self.databeat()
        self.assertEqual(hashlib.sha256(Path(rebuilt['path']).read_bytes()).hexdigest(), PATCH['result']['wav_sha256'])
        aside = [p.name for p in (self.config.data / 'firmware').iterdir() if p.name.startswith('.damaged-')]
        self.assertEqual(len(aside), 1)

    def test_production_record_must_keep_the_pinned_release_classification(self):
        built = self.databeat()
        manifest = Path(built['path']).with_name('manifest.json')
        original = manifest.read_text()
        for key, value in (('experimental', True), ('hardware_tested', not PATCH['release']['hardware_tested']),
                           ('status', 'OFFLINE_QUALIFIED_INTERNAL_CANDIDATE'), ('variant', 'korg')):
            with self.subTest(key=key):
                manifest.write_text(json.dumps(dict(json.loads(original), **{key: value})))
                self.assertNotIn(built['id'], [e['id'] for e in list_firmware(self.config)])
                with self.assertRaisesRegex(ValueError, 'classification'):
                    transfer_firmware(self.config, built['id'], dry_run=True)
        manifest.write_text(original)
        self.assertIn(built['id'], [e['id'] for e in list_firmware(self.config)])

    def test_additional_builds_are_offered_only_through_a_registered_provider(self):
        from volcastudio import firmware
        extra = _store(KORG_WAV, self.config, 'lumon-xl-experimental-fixture-0000000000000000', name='Extra',
                       version='0.0', variant='lumon-xl', status='FIXTURE', experimental=True,
                       installable=True, hardware_tested=False, provenance='test')
        self.add()
        self.assertNotIn(extra['id'], [e['id'] for e in list_firmware(self.config)])
        with self.assertRaisesRegex(ValueError, 'sends only'):
            transfer_firmware(self.config, extra['id'], dry_run=True)
        refused = []

        class Provider:
            def identities(self, config):
                return {extra['id']: extra['sha256']}

            def check(self, identity, record):
                if refused:
                    raise ValueError('Invalid fixture classification')

        with patch.object(firmware, 'ADDITIONAL_BUILDS', [Provider()]):
            self.assertEqual([e['id'] for e in list_firmware(self.config)][-1], extra['id'])
            with self.assertRaisesRegex(ValueError, 'experimental'):
                transfer_firmware(self.config, extra['id'], target='sd:0', confirm_callback=lambda _: True)
            refused.append(True)
            self.assertNotIn(extra['id'], [e['id'] for e in list_firmware(self.config)])
        self.assertEqual(firmware.ADDITIONAL_BUILDS, [])

    def test_earlier_firmware_is_preserved_but_retired(self):
        retired = _store(KORG_WAV, self.config, 'lumon-xl-1-0-1-1a1e8894e3f0e394', name='Earlier firmware v1.0.1',
                         version='1.0.1', variant='lumon-xl', status='stable', experimental=False,
                         installable=True, hardware_tested=True, provenance='earlier Studio')
        self.add()
        self.assertNotIn(retired['id'], [e['id'] for e in list_firmware(self.config)])
        self.assertEqual(inspect_firmware(self.config, retired['id'])['sha256'], retired['sha256'])
        with self.assertRaisesRegex(ValueError, 'sends only'):
            transfer_firmware(self.config, retired['id'], dry_run=True)

    def test_dry_run_offline_only_and_gate(self):
        databeat = self.databeat()
        self.assertEqual(transfer_firmware(self.config, databeat['id'], dry_run=True)['phase'], 'dry_run')
        self.assertFalse(self.config.state.exists())
        manifest = Path(databeat['path']).with_name('manifest.json')
        data = json.loads(manifest.read_text())
        data['installable'] = False
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'blocked'):
            transfer_firmware(self.config, databeat['id'], target='test', confirm_callback=lambda _: True)

    def test_explicit_experimental_and_target(self):
        with lumon_build.override(EXPERIMENTAL):
            databeat = self.databeat()
            self.assertTrue(databeat['experimental'])
            with self.assertRaisesRegex(ValueError, 'experimental'):
                transfer_firmware(self.config, databeat['id'])
            with self.assertRaisesRegex(ValueError, 'output'):
                transfer_firmware(self.config, databeat['id'], allow_experimental=True)

    def test_confirm_cancel_sends_nothing(self):
        databeat = self.databeat()
        with patch('volcastudio.transfer.play_stream') as player:
            result = transfer_firmware(self.config, databeat['id'], target='test', confirm_callback=lambda _: False)
        self.assertEqual(result['phase'], 'cancelled')
        player.assert_not_called()

    def test_single_unmodified_transfer_with_restoration(self):
        databeat = self.databeat()
        original = Path(databeat['path']).read_bytes()
        events = []
        @contextlib.contextmanager
        def rate(target):
            events.append('rate')
            try:
                yield
            finally:
                events.append('restore')
        def player(path, target):
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(target, 'test')
            events.append('play')
        with patch('volcastudio.transfer.syro_rate', rate), patch('volcastudio.transfer.play_stream', player):
            result = transfer_firmware(self.config, databeat['id'], target='test', confirm_callback=lambda _: True)
        self.assertEqual(events, ['rate', 'play', 'restore'])
        self.assertEqual(result['phase'], 'signals_sent')
        self.assertIn('unavailable', result['hardware_receipt'])

    def test_korg_recovery_can_be_sent(self):
        korg = self.add()[1]
        with patch('volcastudio.transfer.syro_rate', contextlib.nullcontext), patch('volcastudio.transfer.play_stream') as player:
            result = transfer_firmware(self.config, korg['id'], target='test', confirm_callback=lambda _: True)
        self.assertEqual(result['phase'], 'signals_sent')
        player.assert_called_once()

    def test_korg_return_uses_native_forced_mode_without_changing_the_updater(self):
        databeat, korg = self.add()
        with patch('volcastudio.transfer.play_stream') as player:
            recovery = transfer_firmware(self.config, korg['id'], dry_run=True)
            update = transfer_firmware(self.config, databeat['id'], dry_run=True)
        recovery_text = '\n'.join(recovery['procedure'])
        self.assertIn('MEMORY + PLAY', recovery_text)
        self.assertNotIn('FUNC + PLAY', recovery_text)
        self.assertIn('backup', recovery_text)
        self.assertIn('FUNC + PLAY', '\n'.join(update['procedure']))
        self.assertNotIn('MEMORY + PLAY', '\n'.join(update['procedure']))
        self.assertEqual(Path(korg['path']).read_bytes(), KORG_WAV)
        self.assertFalse(self.config.state.exists())
        player.assert_not_called()

    def test_interruption_logged_and_rate_restored(self):
        databeat = self.databeat()
        with patch('volcastudio.transfer.syro_rate', contextlib.nullcontext), patch('volcastudio.transfer.play_stream', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                transfer_firmware(self.config, databeat['id'], target='test', confirm_callback=lambda _: True)
        record = json.loads((self.config.state / 'last-firmware-transfer.json').read_text())
        self.assertEqual(record['phase'], 'interrupted')

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            inspect_firmware(self.config, '../other')

    def test_corrupt_metadata_cannot_enable_transfer(self):
        databeat = self.databeat()
        manifest = Path(databeat['path']).with_name('manifest.json')
        data = json.loads(manifest.read_text())
        data['installable'] = 'false'
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'classification'):
            inspect_firmware(self.config, databeat['id'])
        self.assertEqual([e['variant'] for e in list_firmware(self.config)], ['korg'])

    def test_symlink_waveform_rejected(self):
        databeat = self.databeat()
        waveform = Path(databeat['path'])
        waveform.unlink()
        waveform.symlink_to(self.korg)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            inspect_firmware(self.config, databeat['id'])

    def test_library_mutation_during_confirmation_does_not_change_payload(self):
        databeat = self.databeat()
        original = Path(databeat['path']).read_bytes()
        def confirm(record):
            Path(record['path']).write_bytes(b'changed after preparation')
            return True
        def play(path, target):
            self.assertEqual(path.read_bytes(), original)
        with patch('volcastudio.transfer.syro_rate', contextlib.nullcontext), patch('volcastudio.transfer.play_stream', play):
            result = transfer_firmware(self.config, databeat['id'], target='sd:0', confirm_callback=confirm)
        self.assertEqual(result['phase'], 'signals_sent')

    def test_native_target_reaches_rate_context(self):
        databeat = self.databeat()
        with patch('volcastudio.transfer.syro_rate', return_value=contextlib.nullcontext()) as rate, patch('volcastudio.transfer.play_stream'):
            transfer_firmware(self.config, databeat['id'], target='sd:7', confirm_callback=lambda _: True)
        rate.assert_called_once_with('sd:7')


class ShippedPatchTests(unittest.TestCase):
    def test_only_the_pinned_production_patch_ships(self):
        patch_document = lumon_build.load_patch()
        self.assertEqual([p.name for p in lumon_build.PATCH_FILE.parent.iterdir()], ['databeat-os-1.0.patch.json'])
        self.assertEqual(patch_document['kind'], lumon_build.PATCH_KIND)
        self.assertEqual(patch_document['release'], {
            'name': 'DataBeat OS', 'version': '1.0', 'status': 'HARDWARE_ACCEPTED_OWNER_REPORT',
            'experimental': False, 'hardware_tested': True, 'pattern_format': 'LMX3',
            'boot_branding': 'DataBeat OS', 'date': '2026-10-29'})
        self.assertEqual(patch_document['result']['image_sha256'],
                         '13c0652b2b2b25029652282cd24d8f5915866cbc770ac268e09e2e6e603ba918')
        self.assertEqual(patch_document['result']['wav_sha256'],
                         'd5d51b357869c68c7dfd76116eb28f0ae19225ff97a9c3716b84777dabacba52')
        self.assertEqual(patch_document['base']['wav_sha256'],
                         '8fe4f43c333a753d589a4d7eff7859e8fce7155cf54b889f4848d595721a55a9')
        self.assertEqual(lumon_build.dump_patch(patch_document), lumon_build.PATCH_FILE.read_bytes())

    def test_a_changed_shipped_patch_is_refused(self):
        with patch.object(lumon_build, 'PATCH_SHA256', '0' * 64), self.assertRaisesRegex(ValueError, 'damaged'):
            lumon_build.load_patch()

    @unittest.skipUnless(REAL_KORG, 'Set VOLCASTUDIO_KORG_UPDATER to the official Korg 1.42 zip')
    def test_real_korg_updater_builds_the_published_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = SimpleNamespace(data=Path(tmp) / 'data', state=Path(tmp) / 'state')
            databeat, korg = add_korg_updater(REAL_KORG, config)
            listed = list_firmware(config)
            self.assertEqual([e['id'] for e in listed], [databeat['id'], korg['id']])
            built = Path(databeat['path']).read_bytes()
            self.assertEqual(hashlib.sha256(built).hexdigest(),
                             'd5d51b357869c68c7dfd76116eb28f0ae19225ff97a9c3716b84777dabacba52')
            self.assertEqual(hashlib.sha256(updater_codec.decode(built).binary()).hexdigest(),
                             '13c0652b2b2b25029652282cd24d8f5915866cbc770ac268e09e2e6e603ba918')
            self.assertEqual((databeat['name'], databeat['version'], korg['name'], korg['version']),
                             ('DataBeat OS', '1.0', 'Korg volca sample', '1.42'))
            base = updater_codec.decode(lumon_build.read_updater(REAL_KORG)).binary()
            self.assertEqual(lumon_build.literal_overlaps(lumon_build.load_patch()['operations'], base), [])
            self.assertTrue(databeat['installable'] and databeat['hardware_tested'] and not databeat['experimental'])


if __name__ == '__main__':
    unittest.main()
