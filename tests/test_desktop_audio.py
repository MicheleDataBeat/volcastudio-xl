import contextlib
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from volcastudio import desktop_audio as a
from volcastudio.config import Config, xdg
from volcastudio import transfer

class DesktopAudioTests(unittest.TestCase):
    def signal(self, root):
        path = root / 'signal.wav'
        with wave.open(str(path), 'wb') as f:
            f.setparams((2,2,44100,0,'NONE','not compressed'))
            f.writeframes(bytes(4096*4))
        return path

    def backend(self, write=None):
        backend = MagicMock(); stream=Mock()
        stream.write.side_effect=write
        stream.write.return_value=False
        backend.RawOutputStream.return_value.__enter__.return_value=stream
        return backend,stream

    def test_signal_bytes_and_lead_are_unmodified(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.signal(Path(td));before=p.read_bytes();b,s=self.backend()
            with patch.object(a,'_backend',return_value=b):
                a.play(p,'sd:3')
            self.assertEqual(sum(len(call.args[0]) for call in s.write.call_args_list),(22050+4096)*4)
            self.assertEqual(p.read_bytes(),before)
            self.assertEqual(b.RawOutputStream.call_args.kwargs['device'],3)
            self.assertEqual(b.RawOutputStream.call_args.kwargs['samplerate'],44100)
            # Two PortAudio periods underran on raw ALSA hardware even with silence.
            self.assertGreaterEqual(b.RawOutputStream.call_args.kwargs['latency'],.25)

    def test_explicit_output_and_pre_cancel_never_open(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.signal(Path(td));b,s=self.backend();stop=threading.Event();stop.set()
            with patch.object(a,'_backend',return_value=b):
                with self.assertRaises(ValueError):a.play(p,None)
                with self.assertRaises(a.TransferCancelled):
                    with a.audio_operation(stop):a.play(p,'sd:1')
            b.RawOutputStream.assert_not_called()

    def test_cancel_between_blocks_closes_stream(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.signal(Path(td));stop=threading.Event()
            def write(data):stop.set();return False
            b,s=self.backend(write)
            with patch.object(a,'_backend',return_value=b),a.audio_operation(stop):
                with self.assertRaises(a.TransferCancelled):a.play(p,'sd:1')
            self.assertEqual(s.write.call_count,1)
            b.RawOutputStream.return_value.__exit__.assert_called_once()

    def test_output_listing_keeps_only_44k_outputs_with_system_routes_first(self):
        backend = MagicMock()
        backend.query_hostapis.return_value = [{'name': 'ALSA'}, {'name': 'JACK Audio Connection Kit'}]
        backend.query_devices.return_value = [
            dict(name='HDA Intel PCH: ALC233 Analog (hw:0,0)', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='Mic', hostapi=0, max_output_channels=0, default_samplerate=44100.0),
            dict(name='dmix', hostapi=0, max_output_channels=2, default_samplerate=48000.0),
            dict(name='pipewire', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='default', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='Built-in Audio Analog Stereo', hostapi=1, max_output_channels=2, default_samplerate=48000.0)]
        import os
        with patch.object(a, '_backend', return_value=backend), patch.dict(os.environ, {a.EXCLUSIVE_OUTPUTS_ENV: '1'}):
            devices = a.output_devices()
            everything = a.output_devices(include_unusable=True)
        self.assertEqual([d['id'] for d in devices], ['sd:3', 'sd:4', 'sd:0'])
        self.assertEqual(devices[0]['label'], 'System audio via PipeWire (pipewire)')
        self.assertIn('exclusive', devices[2]['label'])
        self.assertEqual({d['name'] for d in everything} - {d['name'] for d in devices}, {'dmix', 'Built-in Audio Analog Stereo'})
        backend.check_output_settings.assert_not_called()  # listing never opens a device

    def test_direct_hardware_outputs_hide_behind_the_shared_route(self):
        import os
        backend = MagicMock()
        backend.query_hostapis.return_value = [{'name': 'ALSA'}]
        backend.query_devices.return_value = [
            dict(name='HDA Intel PCH: ALC233 Analog (hw:0,0)', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='front', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='pipewire', hostapi=0, max_output_channels=2, default_samplerate=44100.0),
            dict(name='default', hostapi=0, max_output_channels=2, default_samplerate=44100.0)]
        with patch.object(a, '_backend', return_value=backend), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(a.EXCLUSIVE_OUTPUTS_ENV, None)
            self.assertEqual([d['name'] for d in a.output_devices()], ['pipewire', 'default'])
            os.environ[a.EXCLUSIVE_OUTPUTS_ENV] = '1'
            self.assertEqual([d['name'] for d in a.output_devices()], ['pipewire', 'default', 'HDA Intel PCH: ALC233 Analog (hw:0,0)', 'front'])
        # Without a sound server (no shared route) the hardware outputs are the only choice.
        backend.query_devices.return_value = backend.query_devices.return_value[:2]
        with patch.object(a, '_backend', return_value=backend), patch.dict(os.environ, {}, clear=False):
            os.environ.pop(a.EXCLUSIVE_OUTPUTS_ENV, None)
            self.assertEqual([d['name'] for d in a.output_devices()], ['HDA Intel PCH: ALC233 Analog (hw:0,0)', 'front'])

    def test_unsupported_rate_and_busy_outputs_explain_the_choice(self):
        with tempfile.TemporaryDirectory() as td:
            p = self.signal(Path(td))
            b, s = self.backend()
            class PortAudioError(Exception):
                pass
            b.PortAudioError = PortAudioError
            b.query_devices.return_value = {'name': 'Built-in Audio Analog Stereo'}
            b.check_output_settings.side_effect = PortAudioError('Invalid sample rate [PaErrorCode -9997]')
            with patch.object(a, '_backend', return_value=b):
                with self.assertRaisesRegex(ValueError, 'Built-in Audio Analog Stereo.*44.1 kHz.*pipewire') as caught:
                    a.play(p, 'sd:17')
            self.assertIsInstance(caught.exception.__cause__, PortAudioError)
            b.check_output_settings.side_effect = None
            b.RawOutputStream.side_effect = PortAudioError('Error opening RawOutputStream: Device unavailable [PaErrorCode -9985]')
            with patch.object(a, '_backend', return_value=b):
                with self.assertRaisesRegex(ValueError, 'in use by another application'):
                    a.play(p, 'sd:17')

    def test_underrun_is_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p=self.signal(Path(td));b,s=self.backend();s.write.return_value=True
            with patch.object(a,'_backend',return_value=b):
                with self.assertRaisesRegex(RuntimeError,'underrun'):a.play(p,'sd:1')

    def test_desktop_rate_does_not_change_pipewire(self):
        with patch.object(transfer,'checked') as process,a.audio_operation():
            with transfer.syro_rate():pass
        process.assert_not_called()
        with patch.object(transfer,'checked') as process:
            with transfer.syro_rate('sd:1'):pass
        process.assert_not_called()

    def test_native_paths_and_xdg_override(self):
        home_env = {'HOME': str(Path.home()), 'USERPROFILE': str(Path.home())}
        with patch.dict('os.environ',home_env,clear=True),patch('volcastudio.config.sys.platform','darwin'):
            self.assertEqual(xdg('XDG_DATA_HOME','.local/share'),Path.home()/'Library/Application Support')
        with patch.dict('os.environ',dict(home_env, LOCALAPPDATA='/native/local'),clear=True),patch('volcastudio.config.sys.platform','win32'):
            self.assertEqual(xdg('XDG_DATA_HOME','.local/share'),Path('/native/local'))
        with patch.dict('os.environ',{'XDG_DATA_HOME':'/explicit'},clear=True),patch('volcastudio.config.sys.platform','win32'):
            self.assertEqual(xdg('XDG_DATA_HOME','.local/share'),Path('/explicit'))

    def test_real_cancelled_encoder_child_is_cleaned_up(self):
        import sys
        stop=threading.Event();timer=threading.Timer(.15,stop.set);timer.start()
        try:
            with a.audio_operation(stop),self.assertRaises(a.TransferCancelled):
                transfer.checked([sys.executable,'-c','import time; time.sleep(30)'])
        finally:timer.cancel()

    def test_device_lock_excludes_another_operation(self):
        with tempfile.TemporaryDirectory() as td:
            with transfer.device_lock(Path(td)):
                with self.assertRaisesRegex(ValueError,'active'):
                    with transfer.device_lock(Path(td)):pass
            with transfer.device_lock(Path(td)):pass

    def test_windowed_progress_has_no_terminal_dependency(self):
        from volcastudio.status import progress
        with patch('sys.stdout',None):
            progress('Sending',1,2)

    def test_native_backup_publishes_complete_bank_and_abort_sends_stop(self):
        from types import SimpleNamespace
        from volcastudio.patterns import blank_pattern, load_bank
        import json
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            config=Config(root/'config',root/'data',root/'state',root/'cache',root/'packs',root/'syro')
            midi=MagicMock();midi.get_output_names.return_value=['selected'];midi.Message.from_bytes.side_effect=lambda data:bytes(data)
            output=midi.open_output.return_value.__enter__.return_value
            backend=MagicMock();decoder=Mock();decoder.complete=False;decoder.frames=[]
            def feed(data):decoder.complete=True;return True
            decoder.feed.side_effect=feed
            decoder.finish.return_value=[SimpleNamespace(slot=slot,data=blank_pattern('lumon-xl',slot).data,session=1) for slot in [*range(10),None]]
            def start(**kwargs):
                stream=MagicMock()
                stream.__enter__.side_effect=lambda:(kwargs['callback'](b'\0'*4096,2048,None,None) or stream)
                return stream
            backend.RawInputStream.side_effect=start
            with patch.object(a,'_backend',return_value=backend),patch.object(a,'_midi',return_value=midi),patch('volcastudio.pattern_audio.AudioPatternDecoder',return_value=decoder):
                target=root/'backup.vspatterns'
                a.backup(config,'selected','sd:2',target)
                self.assertEqual(len(load_bank(target)),11)
                self.assertEqual(output.send.call_count,2)
                self.assertEqual(output.send.call_args_list[0].args[0],b'\xfc')
                decoder.complete=False;decoder.feed.side_effect=ValueError('bad capture')
                output.send.reset_mock()
                bad=root/'partial.vspatterns'
                with self.assertRaisesRegex(ValueError,'bad capture'):a.backup(config,'selected','sd:2',bad)
                self.assertFalse(bad.exists())
                self.assertEqual(output.send.call_count,3)
                self.assertEqual(output.send.call_args.args[0],b'\xfc')
