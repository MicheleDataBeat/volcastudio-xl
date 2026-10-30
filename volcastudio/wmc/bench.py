"""Simulated audio/MIDI devices for offline verification and developer checks.

Nothing here opens a real device. The bench replaces the two backend entry
points that the Desktop App also uses (``desktop_audio._backend`` for PortAudio and
``desktop_audio._midi`` for MIDI) inside a process started with temporary
storage. Every PCM block "played" is recorded so a check can compare it with
the SYRO signal byte for byte. The simulated Volca answers the real DataBeat OS
backup request with synthetic, CRC-framed FSK audio.
"""
import array
import hashlib
import struct
import threading
import time
import zlib
from pathlib import Path

from .. import desktop_audio

OUTPUT = 'Bench recorder → SYNC IN (silent)'
INPUT = 'Bench Volca headphone output'
MIDI = 'Bench MIDI → Volca MIDI IN'
API = 'Studio bench'
SESSION = 0x5743_4d31


def bench_bank():
    """Ten stored memories and a current buffer with non-trivial data in the
    DataBeat OS 1.0 pattern format, as a Volca running it backs them up."""
    from ..patterns import PATTERN_PROFILE, blank_pattern, Pattern
    from ..pattern_conversion import convert_pattern
    from ..pattern_format import set_predictability, set_microtiming, set_motion_value
    result = []
    for slot in (*range(10), None):
        # The editing helpers write the LMX2 layout; the exact conversion then
        # gives the same cells in LMX3.
        pattern = blank_pattern('lumon-xl', slot)
        number = 10 if slot is None else slot
        pattern = set_predictability(pattern, 1, [(number + step) % 16 for step in range(16)])
        pattern = set_microtiming(pattern, 2, [((number + step) % 31) - 15 for step in range(16)])
        pattern = set_motion_value(pattern, 3, 1 + number, 3, 128 + number)
        pattern = set_motion_value(pattern, 4, 2, 0, 64 + number)
        pattern, issues = convert_pattern(pattern, PATTERN_PROFILE)
        assert not issues, issues
        result.append(Pattern(slot, pattern.data))
    return result


def _fsk(frames):
    sine = (0, 1000, 1732, 2000, 1732, 1000, 0, -1000, -1732, -2000, -1732, -1000)
    mark = array.array('h', (sine[n * 2 % 12] for n in range(12)))
    waves = tuple(array.array('h', (sine[n * (bit + 1) % 12]
                  for bit in (0, *(byte >> k & 1 for k in range(8)), 1) for n in range(12))) for byte in range(256))
    out = array.array('h', [0] * 3000)
    for index, wire in enumerate(frames):
        out.extend(mark * (index % 7 + 2))
        for byte in b'\x55' * 48 + wire:
            out.extend(waves[byte])
    out.extend(mark * 24)
    out.extend([0] * 3000)
    return out


def backup_signal(cache):
    """The bench bank as a 48 kHz capture of the DataBeat OS headphone output."""
    from ..pattern_audio import HEADER
    from ..transfer import checked
    target = Path(cache) / 'bench-backup-48k.s16'
    if target.is_file():
        return target.read_bytes()
    wires = []
    for index, pattern in enumerate(bench_bank()):
        raw = HEADER.pack(b'LMBA', 1, index, 11, int(index == 10), 2624, 0, SESSION) + pattern.data
        wires.append(raw + struct.pack('<I', zlib.crc32(raw)))
    nominal = Path(cache) / 'bench-backup-31250.s16'
    nominal.parent.mkdir(parents=True, exist_ok=True)
    nominal.write_bytes(_fsk(wires).tobytes())
    checked(['ffmpeg', '-nostdin', '-v', 'error', '-f', 's16le', '-ar', '31250', '-ac', '1', '-i', nominal,
             '-ar', '48000', '-f', 's16le', '-c:a', 'pcm_s16le', target])
    return target.read_bytes()


class Bench:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.streams = []
        self.midi = []
        self.delay = 0.0
        self.input_error = None
        self.output_present = True
        self.backup_requested = threading.Event()
        self.lock = threading.Lock()

    # The simulated PortAudio module ------------------------------------
    def query_hostapis(self):
        return [{'name': API}]

    def query_devices(self):
        devices = []
        if self.output_present:
            devices.append({'name': OUTPUT, 'hostapi': 0, 'max_output_channels': 2, 'max_input_channels': 0})
        devices.append({'name': INPUT, 'hostapi': 0, 'max_output_channels': 0, 'max_input_channels': 1})
        return devices

    def _device(self, index, kind):
        devices = self.query_devices()
        if type(index) is not int or not 0 <= index < len(devices):
            raise ValueError('Bench device disappeared')
        if devices[index][f'max_{kind}_channels'] < 1:
            raise ValueError('Bench device has no such direction')

    def check_output_settings(self, device, channels, dtype, samplerate):
        self._device(device, 'output')
        if (channels, dtype, samplerate) not in ((2, 'int16', 44100), (1, 'int16', 44100), (2, 'int16', 31250)):
            raise ValueError('Bench output accepts PCM16 at its native rate only')

    def check_input_settings(self, device, channels, dtype, samplerate):
        self._device(device, 'input')
        if self.input_error:
            raise ValueError(self.input_error)

    def _terminate(self):
        pass

    def _initialize(self):
        pass

    def RawOutputStream(self, device, samplerate, channels, dtype, blocksize, latency=None):
        # Real PortAudio accepts a suggested latency; the simulation records it.
        self.output_latency = latency
        return _Output(self, device, samplerate, channels, dtype)

    def RawInputStream(self, device, samplerate, channels, dtype, blocksize, callback):
        if self.input_error:
            raise ValueError(self.input_error)
        return _Input(self, samplerate, blocksize, callback)

    # The simulated mido module ----------------------------------------
    def set_backend(self, name):
        pass

    def get_output_names(self):
        return [MIDI]

    def open_output(self, name):
        if name != MIDI:
            raise OSError('Unknown bench MIDI port')
        return _MidiOut(self)

    class Message:
        def __init__(self, data):
            self.data = bytes(data)

        @classmethod
        def from_bytes(cls, data):
            return cls(data)

        def bytes(self):
            return list(self.data)

    def record(self):
        with self.lock:
            return [dict(s) for s in self.streams]


class _Output:
    def __init__(self, bench, device, rate, channels, dtype):
        self.bench, self.rate, self.channels, self.dtype = bench, rate, channels, dtype
        self.digest = hashlib.sha256()
        self.bytes = 0
        self.path = None

    def __enter__(self):
        with self.bench.lock:
            self.index = len(self.bench.streams) + 1
        self.path = self.bench.folder / f'stream-{self.index:04d}.raw'
        self.stream = self.path.open('wb')
        return self

    def write(self, data):
        data = bytes(data)
        self.stream.write(data)
        self.digest.update(data)
        self.bytes += len(data)
        if self.bench.delay:
            time.sleep(self.bench.delay)
        return False

    def __exit__(self, *exc):
        self.stream.close()
        with self.bench.lock:
            self.bench.streams.append({'index': self.index, 'rate': self.rate, 'channels': self.channels,
                                       'dtype': self.dtype, 'bytes': self.bytes, 'path': str(self.path),
                                       'sha256': self.digest.hexdigest(), 'complete': exc[0] is None})
        return False


class _Input:
    def __init__(self, bench, rate, blocksize, callback):
        self.bench, self.rate, self.blocksize, self.callback = bench, rate, blocksize, callback
        self.stop = threading.Event()

    def __enter__(self):
        self.bench.backup_requested.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def run(self):
        silence = bytes(self.blocksize * 2)
        while not self.stop.is_set() and not self.bench.backup_requested.is_set():
            self.callback(silence, self.blocksize, None, None)
            time.sleep(.01)
        if self.stop.is_set():
            return
        signal = backup_signal(self.bench.folder)
        step = self.blocksize * 2
        for offset in range(0, len(signal), step):
            if self.stop.is_set():
                return
            self.callback(signal[offset:offset + step], len(signal[offset:offset + step]) // 2, None, None)
            time.sleep(.002)

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=5)
        return False


class _MidiOut:
    def __init__(self, bench):
        self.bench = bench

    def __enter__(self):
        return self

    def send(self, message):
        from ..pattern_audio import request_audio_backup
        data = bytes(message.data)
        self.bench.midi.append(data.hex())
        if data == request_audio_backup():
            self.bench.backup_requested.set()

    def __exit__(self, *exc):
        return False


def install(folder):
    """Route the shared desktop audio/MIDI entry points to a new bench.

    ``bench.uninstall()`` restores the real entry points (used by tests)."""
    bench = Bench(folder)
    originals = desktop_audio._backend, desktop_audio._midi

    def uninstall():
        desktop_audio._backend, desktop_audio._midi = originals
    bench.uninstall = uninstall
    desktop_audio._backend = lambda: bench
    desktop_audio._midi = lambda: bench
    return bench
