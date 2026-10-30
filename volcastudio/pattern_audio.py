"""Incremental, bounded-memory decoder for the DataBeat OS audio backup.

Only a complete, ordered bank of ten memory slots and the current edit buffer
is accepted. Neither receiving a tone nor receiving a partial frame is receipt
of a valid backup. PCM is little-endian signed 16-bit mono.
"""
import array
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
import wave
import zlib

NOMINAL_RATE = 31250
SAMPLES_PER_BIT = 12
PATTERN_BYTES = 2624
FRAME_COUNT = 11
PREAMBLE_BYTES = 48
HEADER = struct.Struct('<4sBBBBHHI')
FRAME_BYTES = HEADER.size + PATTERN_BYTES + 4
AUDIO_BACKUP_REQUEST = bytes.fromhex('f0 42 30 00 01 2d 7d f7')
# The alternating 55 preamble has no unique byte boundary. Match all four
# UART magic bytes as a sliding symbol word, then align the byte receiver.
MAGIC_SYMBOLS = 0
for _magic_byte in b'LMBA':
    for _magic_bit in (0, *(_magic_byte >> n & 1 for n in range(8)), 1):
        MAGIC_SYMBOLS = (MAGIC_SYMBOLS << 1) | _magic_bit


def request_audio_backup():
    return AUDIO_BACKUP_REQUEST


@dataclass(frozen=True)
class AudioPatternFrame:
    slot: int | None
    data: bytes
    session: int


class AudioPatternDecoder:
    """Decode chunks without buffering the recording or using FFT dependencies.

    Positive zero crossings identify one-cycle space and two-cycle mark
    symbols. Hysteresis and interpolation reject small crossing noise; an
    adaptive period estimate follows the instrument clock independently of
    capture rate and absolute phase. A low symbol synchronizes every UART
    start bit, so oscillator/capture drift cannot accumulate across a bank.
    """

    def __init__(self, rate=48000, *, max_seconds=180):
        if type(rate) is not int or not 16000 <= rate <= 96000:
            raise ValueError('Audio backup capture rate must be 16000–96000 Hz')
        if not 1 <= max_seconds <= 600:
            raise ValueError('Audio backup decoder duration must be 1–600 seconds')
        self.rate = rate
        self._limit = int(rate * max_seconds)
        self._samples = 0
        self._byte_tail = b''
        self._previous_raw = 0
        self._previous = 0.0
        self._negative = False
        self._candidate = None
        self._crossing = None
        self._period = rate * SAMPLES_PER_BIT / NOMINAL_RATE
        self._nominal = self._period
        self._half = False
        self._uart = -1
        self._value = 0
        self._preamble = 0
        self._sync = 0
        self._alternating = 0
        self._last_bit = None
        self._armed = False
        self._frame = None
        self._frames = []
        self._session = None
        self._error = None

    @property
    def complete(self):
        return self._error is None and len(self._frames) == FRAME_COUNT

    @property
    def frames(self):
        return tuple(self._frames)

    @property
    def samples_received(self):
        return self._samples

    def _fail(self, message):
        self._error = ValueError(message)
        raise self._error

    def _reset_uart(self):
        self._uart = -1
        self._half = False
        self._preamble = 0
        self._alternating = 0
        self._last_bit = None
        self._armed = False

    def _symbol(self, bit):
        if self._frame is None:
            self._sync = ((self._sync << 1) | bit) & ((1 << 40) - 1)
            self._alternating = self._alternating + 1 if bit != self._last_bit else 1
            self._last_bit = bit
            if self._alternating >= 240:
                self._armed = True
            if self._armed and self._sync == MAGIC_SYMBOLS:
                self._frame = bytearray(b'LMBA')
                self._uart = -1
                self._armed = False
            return
        if self._uart < 0:
            if not bit:
                self._uart = 0
                self._value = 0
        elif self._uart < 8:
            self._value |= bit << self._uart
            self._uart += 1
        else:
            self._uart = -1
            if bit:
                self._byte(self._value)
            elif self._frame is not None:
                self._fail('Audio backup UART framing error')
            else:
                self._preamble = 0
                self._uart = 0  # This low symbol may be the next start bit.
                self._value = 0

    def _byte(self, value):
        self._frame.append(value)
        length = len(self._frame)
        if length <= 4 and self._frame != b'LMBA'[:length]:
            self._fail('Invalid audio backup frame magic')
        if length == HEADER.size:
            magic, version, index, count, flags, size, reserved, session = HEADER.unpack(self._frame)
            if (magic != b'LMBA' or version != 1 or count != FRAME_COUNT or
                    index >= FRAME_COUNT or flags != (index == 10) or
                    size != PATTERN_BYTES or reserved):
                self._fail('Unsupported or invalid audio backup frame header')
            if index != len(self._frames):
                self._fail('Duplicate or out-of-order audio backup frame')
            if self._session is not None and session != self._session:
                self._fail('Audio backup frames belong to different sessions')
        if length == FRAME_BYTES:
            raw = bytes(self._frame)
            if zlib.crc32(raw[:-4]) != struct.unpack_from('<I', raw, len(raw) - 4)[0]:
                self._fail('Audio backup CRC mismatch')
            _, _, index, _, _, _, _, session = HEADER.unpack_from(raw)
            payload = raw[HEADER.size:-4]
            if index == 10 and (payload[:6] != b'PTST\xb8\x33' or payload[-4:] != b'PTED'):
                self._fail('Invalid Volca Sample pattern in audio backup')
            self._session = session
            self._frames.append(AudioPatternFrame(None if index == 10 else index, payload, session))
            self._frame = None
            self._uart = -1
            self._alternating = 0
            self._last_bit = None
            self._armed = False

    def _positive_crossing(self, position):
        previous = self._crossing
        self._crossing = position
        if previous is None:
            return
        duration = position - previous
        ratio = duration / self._period
        if .76 <= ratio <= 1.24:
            if self._half:
                # A mark half-cycle may precede acquisition of the first start
                # bit. Once inside a frame, losing a half-cycle is corruption.
                if self._frame is not None:
                    self._fail('Audio backup lost symbol synchronization')
                self._reset_uart()
            self._half = False
            self._period += (duration - self._period) / 64
            self._symbol(0)
        elif .35 <= ratio <= .65:
            self._period += (duration * 2 - self._period) / 128
            if self._half:
                self._half = False
                self._symbol(1)
            else:
                self._half = True
        else:
            if self._frame is not None:
                self._fail('Audio backup signal interrupted or corrupted')
            self._reset_uart()
            self._period = self._nominal
        if not .8 * self._nominal <= self._period <= 1.2 * self._nominal:
            self._fail('Audio backup clock lies outside supported capture range')

    def feed(self, pcm16):
        """Consume arbitrary byte chunks; return newly validated frames."""
        if self._error is not None:
            raise self._error
        if not isinstance(pcm16, (bytes, bytearray, memoryview)):
            raise TypeError('PCM input must be bytes')
        if self._samples + (len(pcm16) + len(self._byte_tail)) // 2 > self._limit:
            self._fail('Audio backup exceeded the capture duration limit')
        pcm16 = self._byte_tail + bytes(pcm16)
        self._byte_tail = pcm16[-1:] if len(pcm16) & 1 else b''
        if self._byte_tail:
            pcm16 = pcm16[:-1]
        samples = array.array('h')
        samples.frombytes(pcm16)
        if sys.byteorder != 'little':
            samples.byteswap()
        count = len(self._frames)
        for raw in samples:
            # Two-sample averaging suppresses small high frequency crossing
            # noise while keeping both 2.6 and 5.2 kHz tones distinct.
            value = (raw + self._previous_raw) * .5
            self._previous_raw = raw
            if value < -64:
                self._negative = True
            if self._negative and self._previous <= 0 < value:
                self._candidate = self._samples - 1 + (-self._previous) / (value - self._previous)
            if self._negative and value > 64 and self._candidate is not None:
                self._positive_crossing(self._candidate)
                self._negative = False
                self._candidate = None
            self._previous = value
            self._samples += 1
        return tuple(self._frames[count:])

    def finish(self):
        if self._error is not None:
            raise self._error
        if self._byte_tail:
            self._fail('Truncated PCM16 audio backup recording')
        if not self.complete or self._frame is not None:
            self._fail(f'Incomplete audio backup: received {len(self._frames)} of {FRAME_COUNT} frames')
        return self.frames


def decode_wav(path):
    """Validate a mono PCM16 WAV recording without playing any audio."""
    with wave.open(str(Path(path)), 'rb') as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getcomptype() != 'NONE':
            raise ValueError('Audio backup WAV must be uncompressed PCM16 mono')
        decoder = AudioPatternDecoder(source.getframerate())
        while chunk := source.readframes(8192):
            decoder.feed(chunk)
        return decoder.finish()
