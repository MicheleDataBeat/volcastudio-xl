"""Desktop App action contracts without Qt windows, device discovery or playback."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from volcastudio import outie_pattern_actions as actions
from volcastudio.patterns import Pattern, blank_pattern
from volcastudio.pattern_transfer import pattern_targets


class OutiePatternActionTests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(
            job=None, config=object(), bank=None,
            firmware_target=SimpleNamespace(currentData=lambda: 'lumon-xl'),
            pattern_slots=SimpleNamespace(text=lambda: '2,5'),
            backup_midi=SimpleNamespace(currentData=lambda: 'Selected MIDI → Volca'),
            device_job=Mock())
        self.guards = [patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('No audio discovery')),
                       patch('volcastudio.desktop_audio._midi', side_effect=AssertionError('No MIDI discovery')),
                       patch('volcastudio.pattern_transfer.play_stream', side_effect=AssertionError('No playback')),
                       patch('volcastudio.pattern_device.send_current', side_effect=AssertionError('No MIDI sending'))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)

    def run_worker(self, result=0, approved=True):
        operation = self.window.device_job.call_args.args[0]
        job = SimpleNamespace(confirm=Mock(return_value=approved))
        with patch.object(actions, 'transfer_patterns', return_value=result) as backend:
            self.assertEqual(operation(job, 'sd:offline-test-only'), result)
        call = backend.call_args
        self.assertIs(call.args[1], self.window.config)
        self.assertEqual(call.args[2:4], ('lumon-xl', 'sd:offline-test-only'))
        return call, job

    def test_snapshot_destinations_preserve_bytes_and_exclude_stored_patterns(self):
        raw = bytearray(blank_pattern().data)
        raw[0x234] = 0xbd
        snapshot = Pattern(None, bytes(raw))
        original = [blank_pattern(slot=0), blank_pattern(slot=9), snapshot]
        self.window.bank = original
        for destination in (0, 9):
            with self.subTest(memory=destination + 1), patch.object(actions, '_choose_destination', return_value=destination):
                actions.restore_current_snapshot(self.window)
                call, job = self.run_worker()
                self.assertEqual(call.args[0], [snapshot])
                self.assertIs(call.args[0][0], snapshot)
                self.assertEqual(call.kwargs['destination'], destination)
                self.assertEqual(pattern_targets(call.args[0], 'lumon-xl', destination), [(destination, snapshot)])
                self.assertNotIn('current_pattern', call.kwargs)
                self.assertNotIn('midi_port', call.kwargs)
                manifest = {'slots': [destination], 'operation': 'stored_patterns'}
                self.assertTrue(call.kwargs['confirm_callback'](manifest))
                self.assertNotIn('confirmation_text', manifest)
                warning = job.confirm.call_args.args[0]['confirmation_text']
                self.assertIn(f'memory {destination + 1}', warning)
                self.assertIn('does not load the live edit buffer', warning)
        self.assertEqual(self.window.bank, original)

    def test_snapshot_cancel_does_not_start_a_worker(self):
        self.window.bank = [blank_pattern()]
        with patch.object(actions, '_choose_destination', return_value=None):
            actions.restore_current_snapshot(self.window)
        self.window.device_job.assert_not_called()

    def test_snapshot_requires_exactly_one_current_snapshot(self):
        for bank in (None, [], [blank_pattern(slot=0)], [blank_pattern(), blank_pattern()]):
            self.window.bank = bank
            with self.subTest(bank=bank), patch.object(actions, '_choose_destination') as choose:
                with self.assertRaises(ValueError):
                    actions.restore_current_snapshot(self.window)
                choose.assert_not_called()
        self.window.device_job.assert_not_called()

    def test_snapshot_refuses_incompatible_data_before_worker(self):
        raw = bytearray(blank_pattern().data)
        raw[0xa20:0xa24] = b'LMX1'
        self.window.bank = [Pattern(None, bytes(raw))]
        with patch.object(actions, '_choose_destination', return_value=4), self.assertRaises(ValueError):
            actions.restore_current_snapshot(self.window)
        self.window.device_job.assert_not_called()

    def test_selected_neutral_reset_changes_only_selected_memories(self):
        self.window.bank = [blank_pattern(slot=8), blank_pattern()]
        original = list(self.window.bank)
        actions.restore_neutral_patterns(self.window)
        call, job = self.run_worker()
        self.assertEqual([p.slot for p in call.args[0]], [1, 4])
        self.assertEqual([p.data for p in call.args[0]], [blank_pattern(slot=n).data for n in (1, 4)])
        self.assertIsNone(call.kwargs['current_pattern'])
        self.assertIsNone(call.kwargs['midi_port'])
        self.assertNotIn('destination', call.kwargs)
        self.assertEqual(self.window.bank, original)

    def test_all_memory_reset_without_live_buffer_reset(self):
        actions.reset_all_patterns(self.window)
        call, job = self.run_worker()
        self.assertEqual([p.slot for p in call.args[0]], list(range(10)))
        self.assertEqual(call.args[0], [blank_pattern(slot=n) for n in range(10)])
        self.assertIsNone(call.kwargs['current_pattern'])
        self.assertIsNone(call.kwargs['midi_port'])

    def test_optional_current_reset_is_neutral_and_does_not_map_to_a_stored_slot(self):
        actions.reset_all_patterns(self.window, reset_current=True)
        call, job = self.run_worker(approved=False)
        self.assertEqual([slot for slot, _ in pattern_targets(call.args[0], 'lumon-xl')], list(range(10)))
        self.assertEqual(call.kwargs['current_pattern'], blank_pattern())
        self.assertIsNone(call.kwargs['current_pattern'].slot)
        self.assertEqual(call.kwargs['midi_port'], 'Selected MIDI → Volca')
        self.assertNotIn('destination', call.kwargs)
        self.assertFalse(call.kwargs['confirm_callback']({'slots': list(range(10))}))
        warning = job.confirm.call_args.args[0]['confirmation_text']
        self.assertIn('current edit buffer', warning)
        self.assertIn('Unsaved edits', warning)

    def test_current_reset_requires_an_existing_selected_midi_port(self):
        for port in (None, '', '  '):
            self.window.backup_midi.currentData = lambda: port
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, 'Select a MIDI output'):
                actions.reset_all_patterns(self.window, reset_current=True)
            with self.assertRaisesRegex(ValueError, 'Select a MIDI output'):
                actions.restore_neutral_patterns(self.window, reset_current=True)
        self.window.device_job.assert_not_called()

    def test_busy_window_starts_no_dialog_or_worker(self):
        self.window.job = object()
        with patch.object(actions, '_choose_destination') as choose:
            for action in (actions.restore_current_snapshot, actions.reset_all_patterns, actions.restore_neutral_patterns):
                with self.subTest(action=action.__name__), self.assertRaisesRegex(ValueError, 'Wait for the current operation'):
                    action(self.window)
            choose.assert_not_called()
        self.window.device_job.assert_not_called()

    def test_shared_backend_confirms_then_sends_stored_memories_before_current_buffer(self):
        import contextlib
        import tempfile
        from pathlib import Path
        from volcastudio.config import Config
        from volcastudio.pattern_transfer import transfer_patterns
        for approved in (False, True):
            with self.subTest(approved=approved), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.window.config = Config(root/'config', root/'data', root/'state', root/'cache', root/'packs', root/'syro')
                self.window.config.initialize()
                manifest = {'operation': 'stored_patterns', 'count': 2, 'slots': [1, 4],
                            'patterns': [{'slot': n, 'signal': f'pattern-{n}.wav'} for n in (1, 4)]}
                events = []
                def confirm(details):
                    events.append('confirm')
                    self.assertTrue(details['current_buffer_reset_requested'])
                    self.assertIn('Unsaved edits', details['confirmation_text'])
                    return approved
                with patch.object(actions, 'transfer_patterns', wraps=transfer_patterns), \
                     patch('volcastudio.pattern_transfer.audio_dependencies'), \
                     patch('volcastudio.pattern_transfer.portable_audio', return_value=True), \
                     patch('volcastudio.pattern_transfer.device_lock', side_effect=lambda _: contextlib.nullcontext()), \
                     patch('volcastudio.pattern_transfer.syro_rate', side_effect=lambda _: contextlib.nullcontext()), \
                     patch('volcastudio.pattern_transfer.prepare_patterns', return_value=manifest), \
                     patch('volcastudio.pattern_transfer.play_stream', side_effect=lambda path, target: events.append(path.name)), \
                     patch('volcastudio.pattern_transfer.time.sleep'), \
                     patch('volcastudio.pattern_device.send_current', side_effect=lambda port, pattern: events.append(('current', port, pattern.slot))), \
                     patch('builtins.print'):
                    actions.restore_neutral_patterns(self.window, reset_current=True)
                    operation = self.window.device_job.call_args.args[0]
                    operation(SimpleNamespace(confirm=confirm), 'sd:offline-test-only')
                self.assertEqual(events, ['confirm', 'pattern-1.wav', 'pattern-4.wav',
                                          ('current', 'Selected MIDI → Volca', None)] if approved else ['confirm'])

    def test_destination_dialog_uses_physical_memory_numbers(self):
        import sys
        widgets = SimpleNamespace(QInputDialog=SimpleNamespace(getItem=Mock(return_value=('10', True))))
        with patch.dict(sys.modules, {'PySide6.QtWidgets': widgets}):
            self.assertEqual(actions._choose_destination(self.window), 9)
        args = widgets.QInputDialog.getItem.call_args.args
        self.assertEqual(args[3], [str(n) for n in range(1, 11)])
        self.assertFalse(args[5])  # typed destinations cannot bypass the list


class RecordedBackupActionTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source, self.destination = self.root/'recording.wav', self.root/'decoded.vspatterns'
        self.window = SimpleNamespace(job=None, config=SimpleNamespace(patterns=self.root),
                                      start_job=Mock(), set_bank=Mock(), message=Mock())
        for target in ('volcastudio.desktop_audio._backend', 'volcastudio.desktop_audio._midi',
                       'volcastudio.desktop_audio.send_midi', 'volcastudio.pattern_device.backup_audio',
                       'volcastudio.pattern_device.send_current', 'volcastudio.transfer.play_stream'):
            guard = patch(target, side_effect=AssertionError('No device operation is allowed'))
            guard.start()
            self.addCleanup(guard.stop)

    def choose(self):
        with patch.object(actions, '_choose_recording', return_value=str(self.source)), \
             patch.object(actions, '_choose_bank_destination', return_value=str(self.destination)):
            actions.decode_recorded_backup(self.window)
        return self.window.start_job.call_args.args

    def make_recording(self, complete=True):
        import wave
        from tests.test_pattern_audio import raw_pattern, frame_bytes, modulate
        expected = [raw_pattern(n) for n in range(11 if complete else 1)]
        pcm = modulate([frame_bytes(n, data) for n, data in enumerate(expected)])
        with wave.open(str(self.source), 'wb') as wav:
            wav.setparams((1, 2, 31250, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
        return expected

    def test_real_synthetic_recording_preserves_all_pattern_bytes_and_opens_after_completion(self):
        import hashlib
        import threading
        from volcastudio.patterns import load_bank
        expected = self.make_recording()
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        work, done = self.choose()
        self.window.set_bank.assert_not_called()
        result = work(SimpleNamespace(cancel_event=threading.Event()))
        self.window.set_bank.assert_not_called()
        self.assertEqual([p.slot for p in load_bank(self.destination)], [*range(10), None])
        self.assertEqual([p.data for p in load_bank(self.destination)], expected)
        done(result)
        patterns, destination = self.window.set_bank.call_args.args
        self.assertEqual(destination, self.destination)
        self.assertEqual([p.data for p in patterns], expected)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)

    def test_incomplete_recording_saves_nothing_and_keeps_loaded_bank(self):
        import threading
        self.make_recording(complete=False)
        work, done = self.choose()
        with self.assertRaises(ValueError):
            work(SimpleNamespace(cancel_event=threading.Event()))
        self.assertFalse(self.destination.exists())
        self.window.set_bank.assert_not_called()

    def test_existing_destination_is_refused_before_work(self):
        self.destination.write_text('Keep this bank')
        with self.assertRaises(FileExistsError):
            self.choose()
        self.window.start_job.assert_not_called()
        self.assertEqual(self.destination.read_text(), 'Keep this bank')

    def test_destination_created_during_decode_is_not_overwritten(self):
        import threading
        from volcastudio.pattern_audio import AudioPatternFrame
        frames = [AudioPatternFrame(n if n < 10 else None, blank_pattern(slot=n if n < 10 else None).data, 123)
                  for n in range(11)]
        def decoded(path):
            self.assertEqual(path, self.source)
            self.destination.write_text('Another window saved this bank')
            return frames
        with patch('volcastudio.pattern_audio.decode_wav', side_effect=decoded):
            work, done = self.choose()
            with self.assertRaises(FileExistsError):
                work(SimpleNamespace(cancel_event=threading.Event()))
        self.assertEqual(self.destination.read_text(), 'Another window saved this bank')
        self.window.set_bank.assert_not_called()

    def test_cancellation_after_decoding_does_not_publish(self):
        import threading
        event = threading.Event()
        def decoded(path):
            event.set()
            return []
        with patch('volcastudio.pattern_audio.decode_wav', side_effect=decoded):
            work, done = self.choose()
            with self.assertRaises(KeyboardInterrupt):
                work(SimpleNamespace(cancel_event=event))
        self.assertFalse(self.destination.exists())
        self.window.set_bank.assert_not_called()

    def test_picker_cancellation_does_not_start_work(self):
        with patch.object(actions, '_choose_recording', return_value=''), \
             patch.object(actions, '_choose_bank_destination') as destination:
            actions.decode_recorded_backup(self.window)
            destination.assert_not_called()
        with patch.object(actions, '_choose_recording', return_value=str(self.source)), \
             patch.object(actions, '_choose_bank_destination', return_value=''):
            actions.decode_recorded_backup(self.window)
        self.window.start_job.assert_not_called()


if __name__ == '__main__':
    unittest.main()
