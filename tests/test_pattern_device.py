import contextlib
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from volcastudio.config import Config
from volcastudio.patterns import blank_pattern, load_bank
from volcastudio import pattern_device as d


class FakeCapture:
    def __init__(self, stopped=False):
        self.stopped = stopped
        self.pid = 123456789

    def poll(self):
        return 1 if self.stopped else None


class PatternDeviceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(self.root / 'config', self.root / 'data', self.root / 'state',
                             self.root / 'cache', self.root / 'external', self.root / 'syro')
        self.config.initialize()
        self.destination = self.root / 'backups' / 'bank.json'
        self.frames = [SimpleNamespace(slot=slot, data=blank_pattern('lumon-xl', slot).data, session=19)
                       for slot in [*range(10), None]]

    def tearDown(self):
        self.tmp.cleanup()

    def capture(self, frames=None, feed_error=None, finish_error=None, timed_out=False,
                capture_exited=False, abort_error=None):
        events = []
        frames = self.frames if frames is None else frames
        recorder = FakeCapture(capture_exited)

        class Decoder:
            complete = False

            def __init__(self, rate):
                self.rate = rate

            def feed(self, pcm):
                events.append('decode')
                if feed_error:
                    raise feed_error
                self.complete = True

            def finish(self):
                if finish_error:
                    raise finish_error
                return frames

        def start(args, **kwargs):
            events.append('record')
            Path(args[-1]).write_bytes(b'\0\0' * 1000)  # mocked mono PCM input
            return recorder

        def stop(proc):
            events.append('stop_capture')
            recorder.stopped = True

        def send(port, message, directory, timeout=5):
            events.append(message)
            if timeout == 2 and abort_error:
                raise abort_error

        timer = [0, 0, 0, 181] if timed_out else None
        with patch.object(d.shutil, 'which', return_value='/mock'), \
             patch.object(d, 'device_lock', return_value=contextlib.nullcontext()), \
             patch.object(d, 'AudioPatternDecoder', Decoder), \
             patch.object(d.subprocess, 'Popen', side_effect=start) as popen, \
             patch.object(d, '_stop_process', side_effect=stop), \
             patch.object(d, '_send_midi', side_effect=send) as midi, \
             patch.object(d.time, 'sleep'), \
             patch.object(d.time, 'monotonic', side_effect=timer, return_value=0):
            try:
                result = d.backup_audio(self.config, 'hw:2,0,0', 'selected-input', self.destination)
                return result, events, popen, midi
            except BaseException as error:
                error.capture_events = events
                raise

    def test_current_buffer_send_uses_native_40_and_preserves_full_payload(self):
        from volcastudio.patterns import blank_pattern, parse_sysex
        pattern = blank_pattern('lumon-xl')
        with patch.object(d.shutil, 'which', return_value='/mock'), patch.object(d, '_send_midi') as send:
            d.send_current('selected-output', pattern)
            port, message, directory = send.call_args.args
            self.assertEqual(port, 'selected-output')
            self.assertEqual(message[6], 0x40)
            self.assertEqual(parse_sysex(message), [pattern])
            self.assertFalse(directory.exists())
        with patch.object(d, '_send_midi') as send:
            with self.assertRaises(ValueError):
                d.send_current('', pattern)
            with self.assertRaises(ValueError):
                d.send_current('port', blank_pattern('lumon-xl', 0))
            send.assert_not_called()

    def test_complete_bank_uses_selected_devices_and_keeps_all_bytes(self):
        raw = bytearray(self.frames[-1].data)
        raw[0x8ff] = 0xea
        self.frames[-1].data = bytes(raw)
        result, events, popen, midi = self.capture()
        self.assertEqual(result, self.destination)
        self.assertEqual(events, ['record', d.MIDI_STOP, d.request_audio_backup(), 'decode', 'stop_capture'])
        patterns = load_bank(result)
        self.assertEqual([(p.slot, p.data) for p in patterns], [(f.slot, f.data) for f in self.frames])
        args = popen.call_args.args[0]
        self.assertEqual(args[:-1], ['pw-record', '--raw', '--format=s16', '--rate=48000',
                                    '--channels=1', '--target', 'selected-input'])
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        self.assertEqual([call.args[0] for call in midi.call_args_list], ['hw:2,0,0'] * 2)
        self.assertFalse(Path(args[-1]).exists())  # isolated capture is removed

    def test_generated_audio_bank_passes_real_decoder_without_hardware_capture(self):
        from test_pattern_audio import frame_bytes, modulate, raw_pattern
        expected = [raw_pattern(index) for index in range(11)]
        pcm = modulate([frame_bytes(index, raw) for index, raw in enumerate(expected)], rate=48000)
        recorder = FakeCapture()

        def start(args, **kwargs):
            Path(args[-1]).write_bytes(pcm)
            return recorder

        with patch.object(d.shutil, 'which', return_value='/mock'), \
             patch.object(d, 'device_lock', return_value=contextlib.nullcontext()), \
             patch.object(d.subprocess, 'Popen', side_effect=start), \
             patch.object(d, '_stop_process') as stop, \
             patch.object(d, '_send_midi') as midi, \
             patch.object(d.time, 'sleep'):
            result = d.backup_audio(self.config, 'selected-port', 'selected-input', self.destination)
        stop.assert_called_once_with(recorder)
        self.assertEqual([p.data for p in load_bank(result)], expected)
        self.assertEqual([call.args[1] for call in midi.call_args_list],
                         [d.MIDI_STOP, d.request_audio_backup()])

    def test_timeout_stops_capture_then_aborts_without_publishing(self):
        with self.assertRaises(TimeoutError) as error:
            self.capture(timed_out=True)
        self.assertEqual(error.exception.capture_events,
                         ['record', d.MIDI_STOP, d.request_audio_backup(), 'stop_capture', d.MIDI_STOP])
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.destination.parent.exists())

    def test_decoder_failures_and_cancellation_stop_capture_before_best_effort_abort(self):
        for failure in (ValueError('CRC mismatch'), KeyboardInterrupt()):
            with self.subTest(error=type(failure).__name__), self.assertRaises(type(failure)) as error:
                self.capture(feed_error=failure, abort_error=RuntimeError('port unplugged'))
            self.assertEqual(error.exception.capture_events[-2:], ['stop_capture', d.MIDI_STOP])
            self.assertFalse(self.destination.exists())

    def test_incomplete_duplicate_or_mixed_session_frames_never_publish(self):
        mixed = list(self.frames[:-1]) + [SimpleNamespace(slot=None, data=self.frames[-1].data, session=20)]
        duplicate = list(self.frames[:-1]) + [self.frames[0]]
        for frames in (self.frames[:-1], duplicate, mixed):
            with self.subTest(count=len(frames)), self.assertRaises(ValueError) as error:
                self.capture(frames=frames)
            self.assertEqual(error.exception.capture_events[-2:], ['stop_capture', d.MIDI_STOP])
            self.assertFalse(self.destination.exists())

    def test_finish_failure_does_not_publish_even_if_decoder_says_complete(self):
        with self.assertRaisesRegex(ValueError, 'truncated') as error:
            self.capture(finish_error=ValueError('truncated final stop bit'))
        self.assertEqual(error.exception.capture_events[-2:], ['stop_capture', d.MIDI_STOP])
        self.assertFalse(self.destination.exists())

    def test_early_recording_exit_does_not_trigger_device(self):
        with self.assertRaisesRegex(RuntimeError, 'capture stopped') as error:
            self.capture(capture_exited=True)
        self.assertEqual(error.exception.capture_events, ['record', 'stop_capture'])
        self.assertFalse(self.destination.exists())

    def test_explicit_port_input_and_bounded_timeout_are_required(self):
        with patch.object(d.subprocess, 'Popen') as popen:
            for port, input in (('', 'input'), ('port', ''), (None, 'input'), ('port', None)):
                with self.subTest(port=port, input=input), self.assertRaises(ValueError):
                    d.backup_audio(self.config, port, input, self.destination)
            for timeout in (0, -1, 181, float('inf'), float('nan')):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    d.backup_audio(self.config, 'port', 'input', self.destination, timeout=timeout)
        popen.assert_not_called()

    def test_existing_destination_is_preserved_without_capture(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b'original')
        with patch.object(d.subprocess, 'Popen') as popen:
            with self.assertRaises(FileExistsError):
                d.backup_audio(self.config, 'port', 'input', self.destination)
        popen.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b'original')

    def test_read_only_lists_do_not_select_devices_or_send_messages(self):
        nodes = ('\tid 40, type PipeWire:Interface:Node\n'
                 '\t\tmedia.class = "Audio/Sink"\n'
                 '\t\tnode.name = "output"\n'
                 '\tid 50, type PipeWire:Interface:Node\n'
                 '\t\tmedia.class = "Audio/Source"\n'
                 '\t\tnode.name = "input"\n')
        with patch.object(d.shutil, 'which', return_value='/mock'), \
             patch.object(d, 'checked', side_effect=[SimpleNamespace(stdout='Dir Device Name\n'),
                                                    SimpleNamespace(stdout=nodes)]) as checked, \
             patch.object(d, '_send_midi') as send:
            self.assertEqual(d.list_midi_ports(), 'Dir Device Name\n')
            self.assertIn('id 50', d.list_audio_inputs())
        self.assertEqual([call.args[0] for call in checked.call_args_list], [['amidi', '-l'], ['pw-cli', 'ls', 'Node']])
        send.assert_not_called()

    def test_system_midi_message_uses_raw_file_and_owned_bounded_process(self):
        proc = Mock(returncode=0)
        proc.communicate.return_value = (None, b'')
        with patch.object(d.subprocess, 'Popen', return_value=proc) as popen, \
             patch.object(d, '_stop_process') as stop:
            d._send_midi('hw:2,0,0', d.request_audio_backup(), self.root)
        args = popen.call_args.args[0]
        self.assertEqual(args[:4], ['amidi', '--port', 'hw:2,0,0', '--send'])
        self.assertEqual(Path(args[-1]).read_bytes(), d.request_audio_backup())
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        proc.communicate.assert_called_once_with(timeout=5)
        stop.assert_called_once_with(proc)

    def test_midi_timeout_stops_its_process_group(self):
        proc = Mock()
        proc.communicate.side_effect = subprocess.TimeoutExpired('amidi', 5)
        with patch.object(d.subprocess, 'Popen', return_value=proc), \
             patch.object(d, '_stop_process') as stop:
            with self.assertRaises(subprocess.TimeoutExpired):
                d._send_midi('port', d.MIDI_STOP, self.root)
        stop.assert_called_once_with(proc)

    def test_capture_process_group_gets_term_then_kill_if_needed(self):
        proc = Mock(pid=123456789)
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired('pw-record', 3), 0]
        with patch.object(d.os, 'killpg') as kill:
            d._stop_process(proc)
        self.assertEqual([call.args for call in kill.call_args_list],
                         [(123456789, signal.SIGTERM), (123456789, signal.SIGKILL)])


if __name__ == '__main__':
    unittest.main()
