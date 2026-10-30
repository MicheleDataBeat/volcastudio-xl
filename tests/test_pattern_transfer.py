import array
import binascii
import contextlib
import json
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from volcastudio.config import Config
from volcastudio.patterns import Pattern, blank_pattern
from volcastudio import pattern_transfer as t


def syro_fixture(path):
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * 4)


def native_syro_blocks(path):
    """Independently demodulate exact offline SDK output, never play it.

    The two 3-bit QAM symbols occupy each eight-frame cycle. Start/channel
    marks frame the 32-byte header and 256-byte blocks. SDK protocol reference:
    https://github.com/korginc/volcasample/blob/master/syro/korg_syro_volcasample.c
    """
    with wave.open(str(path), 'rb') as audio:
        samples = array.array('h', audio.readframes(audio.getnframes()))
    import sys
    if sys.byteorder != 'little':
        samples.byteswap()
    cycles = []
    for frame in range(0, len(samples) // 2 - 7, 8):
        symbols = []
        for channel in (0, 1):
            x = samples[(frame + 2) * 2 + channel]
            y = samples[(frame + 4) * 2 + channel]
            if abs(x) >= abs(y):
                phase, amplitude = (0 if x >= 0 else 2), abs(x)
            else:
                phase, amplitude = (1 if y < 0 else 3), abs(y)
            symbols.append((phase << 1) | (amplitude > 13000))
        cycles.append((symbols[0] << 4) | symbols[1])

    def block(start, count, size):
        assert cycles[start:start + 2] == [0x55, 0x01], 'Invalid SYRO framing marks'
        pool = bits = 0
        decoded = bytearray()
        for cycle in cycles[start + 2:start + 2 + count]:
            for symbol in ((cycle >> 4) & 7, cycle & 7):
                pool |= symbol << bits
                bits += 3
                if bits >= 8:
                    decoded.append(pool & 255)
                    pool >>= 8
                    bits -= 8
        assert decoded[0] == 0xa9, 'Invalid SYRO block prefix'
        data = bytes(decoded[1:1 + size])
        crc = struct.unpack_from('<H', decoded, len(decoded) - 2)[0]
        assert crc == binascii.crc_hqx(data, 0xffff), 'Invalid SYRO block CRC'
        return data

    start = next(index for index, cycle in enumerate(cycles[:-1])
                 if cycle == 0x55 and cycles[index + 1] == 0x01)
    header = block(start, 47, 32)
    size = struct.unpack_from('<I', header, 24)[0]
    cursor = start + 49
    payload = bytearray()
    for _ in range((size + 255) // 256):
        cursor += 35  # idle cycles between data blocks
        payload.extend(block(cursor, 350, 256))
        cursor += 352
    assert not any(payload[size:]), 'Invalid last-block zero padding'
    return header, bytes(payload[:size])


class PatternTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(self.root / 'config', self.root / 'data', self.root / 'state',
                             self.root / 'cache', self.root / 'external', self.root / 'syro')
        self.config.initialize()
        self.patterns = [blank_pattern('lumon-xl', slot) for slot in (0, 9)]

    def tearDown(self):
        self.tmp.cleanup()

    def test_preparation_preserves_all_bytes_and_uses_pattern_numbers_one_to_ten(self):
        raw = bytearray(self.patterns[1].data)
        raw[0x234] = 0xfd  # opaque bytes must survive without rebuilding fields
        self.patterns[1] = Pattern(9, bytes(raw))
        output = self.root / 'prepared'
        calls = []

        def encode(args, **kwargs):
            calls.append(args)
            syro_fixture(args[1])

        with patch.object(t, 'converter', return_value=Path('/mock-syro')), \
             patch.object(t, 'checked', side_effect=encode), \
             patch.object(t, 'play_stream') as player:
            manifest = t.prepare_patterns(self.patterns, output, self.config.syro_dir, 'lumon-xl')
        player.assert_not_called()
        self.assertEqual(manifest['slots'], [0, 9])
        self.assertEqual([call[2].split(':', 1)[0] for call in calls], ['p1', 'p10'])
        self.assertEqual(sorted(p.name for p in output.glob('*.wav')), ['pattern-00.wav', 'pattern-09.wav'])
        for pattern in self.patterns:
            self.assertEqual((output / f'pattern-{pattern.slot:02d}.bin').read_bytes(), pattern.data)
        self.assertEqual(json.loads((output / 'manifest.json').read_text()), manifest)
        self.assertIn('one-way', manifest['hardware_receipt'])

    def test_full_backup_restores_ten_stored_patterns_and_keeps_current_snapshot(self):
        patterns = [blank_pattern('lumon-xl', slot) for slot in range(10)] + [blank_pattern('lumon-xl')]
        output = self.root / 'prepared'
        with patch.object(t, 'converter', return_value=Path('/mock-syro')), \
             patch.object(t, 'checked', side_effect=lambda args, **kw: syro_fixture(args[1])):
            manifest = t.prepare_patterns(patterns, output, self.config.syro_dir, 'lumon-xl')
        self.assertEqual(manifest['count'], 10)
        self.assertEqual(manifest['slots'], list(range(10)))
        self.assertTrue(manifest['current_edit_buffer_saved_not_restored'])

    def test_current_buffer_needs_explicit_destination_and_cannot_collide(self):
        current = blank_pattern('lumon-xl')
        with self.assertRaisesRegex(ValueError, 'explicit'):
            t.pattern_targets([current], 'lumon-xl')
        self.assertEqual(t.pattern_targets([current], 'lumon-xl', 8), [(8, current)])
        with self.assertRaisesRegex(ValueError, 'duplicate stored'):
            t.pattern_targets([blank_pattern('lumon-xl', 8), current], 'lumon-xl', 8)
        with self.assertRaisesRegex(ValueError, 'duplicate pattern'):
            t.pattern_targets([current, current], 'lumon-xl', 8)

    def test_ignored_current_snapshot_does_not_change_stored_target_compatibility(self):
        stored = blank_pattern('lumon-xl', 0)
        raw = bytearray(blank_pattern('lumon-xl').data)
        raw[0xa20:0xa24] = b'LMX1'
        current = Pattern(None, bytes(raw))
        self.assertEqual(t.pattern_targets([stored, current], 'lumon-xl'), [(0, stored)])
        with self.assertRaisesRegex(ValueError, 'unsupported pattern format'):
            t.pattern_targets([current], 'lumon-xl', 1)

    def test_incompatible_bank_and_invalid_destinations_are_rejected_before_encoding(self):
        with patch.object(t, 'converter') as converter:
            with self.assertRaisesRegex(ValueError, 'unsupported pattern format'):
                t.prepare_patterns([Pattern(0, blank_pattern('lumon-xl', 0).data[:0xa20] + b'LMX1' + blank_pattern('lumon-xl', 0).data[0xa24:])], self.root / 'prepared',
                                   self.config.syro_dir, 'lumon-xl')
            for destination in (-1, 10, True):
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    t.pattern_targets([blank_pattern()], 'lumon-xl', destination)
        converter.assert_not_called()
        self.assertFalse((self.root / 'prepared').exists())

    def test_failed_preparation_removes_its_staging_and_refuses_existing_directory(self):
        output = self.root / 'prepared'
        with patch.object(t, 'converter', return_value=Path('/mock-syro')), \
             patch.object(t, 'checked', side_effect=RuntimeError('encoder failed')):
            with self.assertRaisesRegex(RuntimeError, 'encoder'):
                t.prepare_patterns(self.patterns, output, self.config.syro_dir, 'lumon-xl')
        self.assertFalse(output.exists())
        output.mkdir()
        sentinel = output / 'existing'
        sentinel.write_text('unchanged')
        with patch.object(t, 'converter', return_value=Path('/mock-syro')):
            with self.assertRaises(FileExistsError):
                t.prepare_patterns(self.patterns, output, self.config.syro_dir, 'lumon-xl')
        self.assertEqual(sentinel.read_text(), 'unchanged')

    def run_transfer(self, confirmation=True, player=None, preparation_error=None):
        events = []
        manifest = {'count': 2, 'slots': [0, 9], 'patterns': [
            {'slot': 0, 'signal': 'pattern-00.wav'}, {'slot': 9, 'signal': 'pattern-09.wav'}],
            'hardware_receipt': 'unavailable: SYRO audio is one-way'}

        @contextlib.contextmanager
        def lock(state):
            events.append('lock')
            yield
            events.append('unlock')

        def prepare(*args):
            events.append('prepare')
            if preparation_error:
                raise preparation_error
            return manifest

        def confirm(record):
            events.append('confirm')
            return confirmation

        def play(path, target):
            events.append(path.name)
            if player:
                player(path, target)

        with patch.object(t.shutil, 'which', return_value='/mock'), \
             patch.object(t, 'device_lock', side_effect=lock), \
             patch.object(t, 'prepare_patterns', side_effect=prepare), \
             patch.object(t, 'syro_rate', return_value=contextlib.nullcontext()) as rate, \
             patch.object(t, 'play_stream', side_effect=play) as playback, \
             patch.object(t.time, 'sleep') as sleep:
            result = t.transfer_patterns(self.patterns, self.config, 'lumon-xl',
                                         target='selected-output', confirm_callback=confirm)
        return result, events, rate, playback, sleep

    def test_lock_precedes_prepare_and_cancel_never_changes_audio_or_device(self):
        result, events, rate, playback, sleep = self.run_transfer(confirmation=False)
        self.assertEqual(result, 0)
        self.assertEqual(events, ['lock', 'prepare', 'confirm', 'unlock'])
        rate.assert_not_called()
        playback.assert_not_called()
        sleep.assert_not_called()
        self.assertFalse((self.config.state / 'last-pattern-transfer.json').exists())

    def test_send_uses_only_prepared_patterns_and_records_signals_sent_without_receipt(self):
        result, events, _, playback, sleep = self.run_transfer()
        self.assertEqual(result, 0)
        self.assertEqual(events, ['lock', 'prepare', 'confirm', 'pattern-00.wav', 'pattern-09.wav', 'unlock'])
        self.assertEqual([call.args[1] for call in playback.call_args_list], ['selected-output'] * 2)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (1,)])
        record = json.loads((self.config.state / 'last-pattern-transfer.json').read_text())
        self.assertEqual(record['phase'], 'signals_sent')
        self.assertEqual(record['slots_sent'], [0, 9])
        self.assertIn('unavailable', record['hardware_receipt'])
        self.assertFalse((self.config.state / 'last-transfer.json').exists())

    def test_failed_preparation_never_reaches_confirmation_or_playback(self):
        with patch.object(t.shutil, 'which', return_value='/mock'), \
             patch.object(t, 'device_lock', return_value=contextlib.nullcontext()), \
             patch.object(t, 'prepare_patterns', side_effect=ValueError('bad pattern')), \
             patch.object(t, 'play_stream') as player:
            confirm = Mock()
            with self.assertRaisesRegex(ValueError, 'bad pattern'):
                t.transfer_patterns(self.patterns, self.config, 'lumon-xl', confirm_callback=confirm)
        confirm.assert_not_called()
        player.assert_not_called()

    def test_failure_or_interrupt_stops_after_first_signal_and_records_phase(self):
        for error, phase in ((RuntimeError('failed'), 'failed'), (KeyboardInterrupt(), 'interrupted')):
            with self.subTest(phase=phase):
                calls = []

                def fail(path, target):
                    calls.append(path.name)
                    raise error

                with self.assertRaises(type(error)):
                    self.run_transfer(player=fail)
                self.assertEqual(calls, ['pattern-00.wav'])
                record = json.loads((self.config.state / 'last-pattern-transfer.json').read_text())
                self.assertEqual(record['phase'], phase)
                self.assertEqual(record['slots_sent'], [])

    def test_current_reset_follows_stored_signals_inside_same_lock_and_confirmation(self):
        manifest = {'count': 1, 'slots': [0], 'patterns': [{'slot': 0, 'signal': 'pattern-00.wav'}]}
        current = blank_pattern('lumon-xl')
        events = []
        @contextlib.contextmanager
        def lock(state):
            events.append('lock')
            yield
            events.append('unlock')
        for approved in (False, True):
            events.clear()
            def confirm(record):
                self.assertTrue(record['current_buffer_reset_requested'])
                events.append('confirm')
                return approved
            with patch.object(t.shutil, 'which', return_value='/mock'), \
                 patch.object(t, 'device_lock', side_effect=lock), \
                 patch.object(t, 'prepare_patterns', return_value=manifest), \
                 patch.object(t, 'syro_rate', return_value=contextlib.nullcontext()), \
                 patch.object(t, 'play_stream', side_effect=lambda *a: events.append('stored')), \
                 patch.object(t.time, 'sleep'), \
                 patch('volcastudio.pattern_device.send_current', side_effect=lambda *a: events.append('current')) as send:
                t.transfer_patterns(self.patterns, self.config, 'lumon-xl', confirm_callback=confirm,
                                    current_pattern=current, midi_port='selected-port')
            self.assertEqual(events, ['lock', 'confirm', 'stored', 'current', 'unlock'] if approved else ['lock', 'confirm', 'unlock'])
            if approved:
                send.assert_called_once_with('selected-port', current)
                record = json.loads((self.config.state / 'last-pattern-transfer.json').read_text())
                self.assertEqual(record['phase'], 'signals_sent')
                self.assertTrue(record['current_buffer_sent'])
            else:
                send.assert_not_called()

    def test_native_pattern_encoding_is_offline(self):
        home = Config.read().syro_dir
        try:
            t.converter(home)
        except ValueError:
            self.skipTest('Native SYRO encoder has not been built')
        output = self.root / 'native-prepared'
        with patch.object(t, 'play_stream') as player:
            manifest = t.prepare_patterns(self.patterns, output, home, 'lumon-xl')
        player.assert_not_called()
        self.assertEqual(manifest['slots'], [0, 9])
        for path in output.glob('*.wav'):
            t.verify_stream(path)

    def test_native_opaque_uninitialized_slot_restores_exact_bytes(self):
        home = Config.read().syro_dir
        try:
            t.converter(home)
        except ValueError:
            self.skipTest('Native SYRO encoder has not been built')
        pattern = Pattern(4, bytes([255]) * 2624)
        output = self.root / 'opaque-native-prepared'
        with patch.object(t, 'play_stream') as player:
            manifest = t.prepare_patterns([pattern], output, home, 'lumon-xl')
        player.assert_not_called()
        self.assertEqual(manifest['opaque_slots'], [4])
        header, payload = native_syro_blocks(output / 'pattern-04.wav')
        self.assertEqual(header[20:22], bytes([0x20, 4]))
        self.assertEqual(payload, pattern.data)

    def test_native_syro_headers_and_full_lumon_bytes_decode_to_correct_memory_slots(self):
        home = Config.read().syro_dir
        try:
            t.converter(home)
        except ValueError:
            self.skipTest('Native SYRO encoder has not been built')
        patterns = []
        for slot in (0, 9):
            from test_grooves import populated
            raw = bytearray(populated(slot).data)
            patterns.append(Pattern(slot, bytes(raw)))
        output = self.root / 'lumon-native-prepared'
        with patch.object(t, 'play_stream') as player:
            t.prepare_patterns(patterns, output, home, 'lumon-xl')
        player.assert_not_called()
        for pattern in patterns:
            header, payload = native_syro_blocks(output / f'pattern-{pattern.slot:02d}.wav')
            self.assertEqual(header[:16], b'KORG SYSTEM FILE')
            self.assertEqual(struct.unpack_from('<I', header, 16)[0], 0xff0033b8)
            self.assertEqual(header[20], 0x20)  # patterns, never sample erase/upload
            self.assertEqual(header[21], pattern.slot)  # wire destinations are 0/9
            self.assertEqual(struct.unpack_from('<I', header, 24)[0], 2624)
            self.assertEqual(payload, pattern.data)  # every opaque extension byte
            self.assertEqual(payload[0xa20:0xa24], b'LMX2')


if __name__ == '__main__':
    unittest.main()
