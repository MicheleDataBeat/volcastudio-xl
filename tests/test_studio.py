import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from volcastudio.config import Config
from volcastudio import transfer as t


def wav(path, seconds=0.01, rate=44100):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * int(seconds * rate))


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pack = self.root / 'kit with spaces'
        wav(self.pack / '01 snare.wav')
        wav(self.pack / '00 kick.wav')
        self.cfg = Config(self.root / 'config', self.root / 'data', self.root / 'state',
                          self.root / 'cache', self.root / 'old-packs', self.root / 'syro')
        self.cfg.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_slot_order_flattens_nested_folders(self):
        wav(self.pack / 'nested/02 hi hat.wav')
        _, files, seconds = t.pack_files(self.pack)
        self.assertEqual([p.relative_to(self.pack).as_posix() for p in files],
                         ['00 kick.wav', '01 snare.wav', 'nested/02 hi hat.wav'])
        self.assertAlmostEqual(seconds, .03)

    def test_invalid_or_oversized_kit_never_reaches_converter(self):
        for i in range(99):
            wav(self.pack / f'extra-{i}.wav')
        with patch.object(t, 'converter') as converter:
            with self.assertRaises(ValueError):
                t.prepare(self.pack, self.root / 'prepared', self.cfg.syro_dir)
            converter.assert_not_called()
        self.assertFalse((self.root / 'prepared').exists())

    def test_truncated_and_over_memory_wavs_rejected(self):
        path = self.pack / '00 kick.wav'
        path.write_bytes(path.read_bytes()[:-2])
        with self.assertRaises(ValueError):
            t.pack_files(self.pack)
        wav(path, seconds=66)
        with self.assertRaises(ValueError):
            t.pack_files(self.pack)

    def run_transfer(self, confirm=True, player=None, on_sent=None):
        manifest = {'count': 2, 'seconds': .02, 'pack': str(self.pack)}
        with patch.object(t, 'device_lock', return_value=contextlib.nullcontext()), \
             patch.object(t, 'prepare', return_value=manifest), \
             patch.object(t, 'syro_rate', return_value=contextlib.nullcontext()) as rate, \
             patch.object(t, 'play_stream', side_effect=player) as play, \
             patch.object(t.time, 'sleep'), patch('builtins.print'):
            result = t.transfer(self.pack, self.cfg, lambda m: confirm, on_sent=on_sent)
            return result, play, rate

    def test_cancel_never_clears_or_changes_rate(self):
        sent = unittest.mock.Mock()
        result, play, rate = self.run_transfer(confirm=False, on_sent=sent)
        sent.assert_not_called()
        self.assertEqual(result, 0)
        play.assert_not_called()
        rate.assert_not_called()
        self.assertFalse((self.cfg.state / 'last-transfer.json').exists())

    def test_gui_cancel_at_confirmation_returns_without_playback(self):
        import threading
        from volcastudio import desktop_audio
        cancel = threading.Event()
        def decline(manifest):
            cancel.set()
            return False
        with patch.object(t, 'audio_dependencies'), \
             patch.object(t, 'prepare', return_value={'count': 2}), \
             patch.object(t, 'play_stream') as player, \
             desktop_audio.audio_operation(cancel_event=cancel):
            self.assertEqual(t.transfer(self.pack, self.cfg, decline, 'sd:0'), 0)
        player.assert_not_called()
        self.assertFalse((self.cfg.state / 'last-transfer.json').exists())

    def test_opened_kit_identity_is_checked_under_the_transfer_lock(self):
        from volcastudio.kits import fingerprint
        expected = fingerprint(self.pack)
        @contextlib.contextmanager
        def changed_before_lock(state):
            (self.pack/'concurrent-edit.txt').write_text('Another edition replaced the kit')
            yield
        with patch.object(t, 'audio_dependencies'), \
             patch.object(t, 'device_lock', side_effect=changed_before_lock), \
             patch.object(t, 'prepare') as prepare, patch.object(t, 'play_stream') as play:
            confirm = unittest.mock.Mock()
            with self.assertRaisesRegex(ValueError, 'changed outside the Desktop App'):
                t.transfer(self.pack, self.cfg, confirm, 'sd:0', expected_fingerprint=expected)
            prepare.assert_not_called()
            confirm.assert_not_called()
            play.assert_not_called()

    def test_opened_kit_changed_during_preparation_never_reaches_confirmation(self):
        from volcastudio.kits import fingerprint
        expected = fingerprint(self.pack)
        def changed(*args):
            (self.pack/'concurrent-edit.txt').write_text('External edit')
            return {'count': 2}
        with patch.object(t, 'audio_dependencies'), patch.object(t, 'prepare', side_effect=changed), \
             patch.object(t, 'play_stream') as play, patch('builtins.print'):
            confirm = unittest.mock.Mock()
            with self.assertRaisesRegex(ValueError, 'changed outside the Desktop App'):
                t.transfer(self.pack, self.cfg, confirm, 'sd:0', expected_fingerprint=expected)
            confirm.assert_not_called()
            play.assert_not_called()
            self.assertFalse((self.cfg.state/'last-transfer.json').exists())

    def test_all_clears_precede_first_upload(self):
        sent = unittest.mock.Mock()
        result, play, _ = self.run_transfer(on_sent=sent)
        sent.assert_called_once_with()
        self.assertEqual(result, 0)
        names = [c.args[0].name for c in play.call_args_list]
        self.assertEqual(names[:100], [f'clear-{i:02d}.wav' for i in range(100)])
        self.assertEqual(names[100:], ['upload-00.wav', 'upload-01.wav'])
        self.assertEqual(json.loads((self.cfg.state / 'last-transfer.json').read_text())['phase'], 'signals_sent')

    def test_clear_failure_blocks_upload_and_records_failure(self):
        names = []
        def fail(path, target):
            names.append(path.name)
            raise subprocess.CalledProcessError(1, ['pw-play'])
        sent = unittest.mock.Mock()
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_transfer(player=fail, on_sent=sent)
        sent.assert_not_called()
        self.assertEqual(names, ['clear-00.wav'])
        self.assertEqual(json.loads((self.cfg.state / 'last-transfer.json').read_text())['phase'], 'failed')

    def test_interrupt_blocks_upload_and_records_interrupted(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_transfer(player=lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.assertEqual(json.loads((self.cfg.state / 'last-transfer.json').read_text())['phase'], 'interrupted')

    def test_original_pipewire_rate_restored_on_failure(self):
        def fake(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "update: id:0 key:'clock.force-rate' value:'48000' type:''", '')
        with patch.object(t, 'checked', side_effect=fake) as checked, patch.object(t.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                with t.syro_rate():
                    raise RuntimeError('playback failed')
        self.assertEqual(checked.call_args_list[-1].args[0][-1], '48000')

    def test_failed_preparation_never_asks_or_plays(self):
        confirm = unittest.mock.Mock()
        with patch.object(t, 'device_lock', return_value=contextlib.nullcontext()), \
             patch.object(t, 'prepare', side_effect=ValueError('bad converter')), \
             patch.object(t, 'play_stream') as player, patch('builtins.print'):
            with self.assertRaises(ValueError):
                t.transfer(self.pack, self.cfg, confirm)
        confirm.assert_not_called()
        player.assert_not_called()

    def test_checked_child_failure_is_propagated(self):
        with self.assertRaises(subprocess.CalledProcessError) as exc:
            t.checked(['python3', '-c', 'import sys; sys.exit(7)'])
        self.assertEqual(exc.exception.returncode, 7)

    def test_native_encoding_offline(self):
        home = Config.read().syro_dir
        try:
            t.converter(home)
        except ValueError:
            self.skipTest('Native SYRO encoder has not been built')
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg is not installed')
        before = [p.read_bytes() for p in sorted(self.pack.iterdir())]
        output = self.root / 'prepared'
        with patch.object(t, 'play_stream') as player:
            result = t.prepare(self.pack, output, home)
        player.assert_not_called()
        self.assertEqual(result['count'], 2)
        self.assertEqual(len(list(output.glob('clear-*.wav'))), 100)
        self.assertEqual(len(list(output.glob('upload-*.wav'))), 2)
        self.assertEqual(before, [p.read_bytes() for p in sorted(self.pack.iterdir())])
        self.assertEqual(result['sample_rate'], 31250)
        pcm_bytes = 0
        for sample in (output / 'samples').glob('*.wav'):
            with wave.open(str(sample), 'rb') as snapshot:
                self.assertEqual((snapshot.getframerate(), snapshot.getnchannels(), snapshot.getsampwidth()), (31250, 1, 2))
                self.assertAlmostEqual(snapshot.getnframes() / 31250, .01, delta=1 / 31250)
                pcm_bytes += snapshot.getnframes() * 2
        self.assertEqual(result['sample_pcm_bytes'], pcm_bytes)
        for stream in output.glob('*.wav'):
            t.verify_stream(stream)

    def test_normalization_fits_full_length_24bit_stereo_without_changing_source(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg is not installed')
        source = self.root / 'stereo24.wav'
        with wave.open(str(source), 'wb') as audio:
            audio.setparams((2, 3, 44100, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x00\x00\x40' * 2 * (44100 * 65))
        before = source.read_bytes()
        target = self.root / 'normalized.wav'
        t.normalize_sample(source, target)
        self.assertEqual(source.read_bytes(), before)
        with wave.open(str(target), 'rb') as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (31250, 1, 2))
            self.assertEqual(audio.getnframes(), 31250 * 65)
            self.assertLess(audio.getnframes() * 2, 4 * 1024 * 1024)

    def test_exact_65_second_100_slot_kit_allows_resampling_rounding(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg is not installed')
        pack = self.root / 'full_memory'
        for i in range(100):
            wav(pack / f'{i:02d}.wav', seconds=.65)
        checked = t.checked
        def encode(args, **kwargs):
            if args[0] == 'ffmpeg':
                return checked(args, **kwargs)
            with wave.open(str(args[1]), 'wb') as signal:
                signal.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                signal.writeframes(b'\0' * 4)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(t, 'converter', return_value=Path('/mock-syro')), patch.object(t, 'checked', side_effect=encode):
            result = t.prepare(pack, self.root / 'full_prepared', self.cfg.syro_dir)
        self.assertEqual(result['count'], 100)
        self.assertEqual(result['seconds'], 65)
        self.assertLessEqual(result['sample_pcm_bytes'], (65 * 31250 + 100) * 2)


if __name__ == '__main__':
    unittest.main()
