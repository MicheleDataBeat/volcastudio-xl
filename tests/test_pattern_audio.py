"""Synthetic FSK only: no playback, capture, hardware or persistent audio assets."""
import array
import random
import struct
import tempfile
import unittest
from pathlib import Path
import wave
import zlib

from volcastudio.pattern_audio import AudioPatternDecoder, HEADER, decode_wav, request_audio_backup
from volcastudio.patterns import Pattern, blank_pattern

SINE = (0, 1000, 1732, 2000, 1732, 1000, 0, -1000, -1732, -2000, -1732, -1000)
MARK = array.array('h', (SINE[n * 2 % 12] for n in range(12)))
BYTE_WAVES = tuple(array.array('h', (SINE[n * (bit + 1) % 12]
    for bit in (0, *(byte >> k & 1 for k in range(8)), 1) for n in range(12))) for byte in range(256))


def raw_pattern(index):
    # Random unknown bytes and explicit metadata detect accidental field-only
    # reconstruction. Header/footer and LMX2 are the only fixed signatures.
    rng = random.Random(901 + index)
    raw = bytearray(rng.randbytes(2624))
    raw[:6] = b'PTST\xb8\x33'
    raw[0xa20:0xa24] = b'LMX2'
    raw[-4:] = b'PTED'
    return bytes(raw)


def frame_bytes(index, data, session=0x12345678):
    raw = HEADER.pack(b'LMBA', 1, index, 11, int(index == 10), 2624, 0, session) + data
    return raw + struct.pack('<I', zlib.crc32(raw))


def modulate(wires, *, rate=31250, speed=1, phase=0, noise=0):
    """Literal firmware lookup waveform, linearly resampled by the capture clock."""
    nominal = array.array('h')
    for index, wire in enumerate(wires):
        # Vary waiting time to model main-loop flash snapshot/CRC preparation.
        nominal.extend(MARK * (index % 7 + 2))
        for byte in b'\x55' * 48 + wire:
            nominal.extend(BYTE_WAVES[byte])
    nominal.extend(MARK * 24)
    if rate == 31250 and speed == 1 and phase == 0 and not noise:
        return nominal.tobytes()
    step = 31250 * speed / rate
    rng = random.Random(57)
    out = array.array('h', [0] * (rate // 100))
    position = phase
    while position < len(nominal) - 1:
        n = int(position)
        frac = position - n
        value = nominal[n] + (nominal[n + 1] - nominal[n]) * frac
        if noise:
            value += rng.randint(-noise, noise)
        out.append(round(value))
        position += step
    out.extend([0] * (rate // 100))
    return out.tobytes()


def feed_chunks(decoder, pcm):
    # Odd boundaries exercise incremental PCM byte carry, not just sample carry.
    for offset in range(0, len(pcm), 16381):
        decoder.feed(pcm[offset:offset + 16381])
    return decoder


class PatternAudioTests(unittest.TestCase):
    def test_full_bank_exact_at_capture_rates_and_clock_variation(self):
        expected = [raw_pattern(n) for n in range(11)]
        wires = [frame_bytes(n, raw) for n, raw in enumerate(expected)]
        for rate, speed, phase, noise in [(44100, 1, .37, 0), (48000, 1.055, 2.19, 140)]:
            with self.subTest(rate=rate, speed=speed):
                pcm = modulate(wires, rate=rate, speed=speed, phase=phase, noise=noise)
                decoder = feed_chunks(AudioPatternDecoder(rate), pcm)
                self.assertTrue(decoder.complete)
                frames = decoder.finish()
                self.assertEqual([f.slot for f in frames], [*range(10), None])
                self.assertEqual([f.data for f in frames], expected)
                self.assertEqual({f.session for f in frames}, {0x12345678})
                for frame in frames:
                    self.assertEqual(Pattern(frame.slot, frame.data).data, frame.data)
                self.assertLessEqual(len(decoder._frame or b''), 2644)
                if rate == 44100:
                    with tempfile.TemporaryDirectory() as td:
                        path = Path(td) / 'capture.wav'
                        with wave.open(str(path), 'wb') as wav:
                            wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                            wav.writeframes(pcm)
                        self.assertEqual(decode_wav(path), frames)

    def test_drift_in_other_direction_and_arbitrary_start_phase(self):
        raw = raw_pattern(0)
        for phase in (.05, 5.73, 17.41):
            with self.subTest(phase=phase):
                decoder = feed_chunks(AudioPatternDecoder(48000), modulate([frame_bytes(0, raw)], rate=48000, speed=.945, phase=phase, noise=100))
                self.assertEqual(decoder.frames[0].data, raw)
                self.assertFalse(decoder.complete)
                with self.assertRaisesRegex(ValueError, 'Incomplete'):
                    decoder.finish()

    def test_crc_corruption_and_truncated_signal_are_rejected(self):
        wire = bytearray(frame_bytes(0, raw_pattern(0)))
        wire[1500] ^= 0x80
        with self.assertRaisesRegex(ValueError, 'CRC'):
            feed_chunks(AudioPatternDecoder(31250), modulate([wire]))
        pcm = modulate([frame_bytes(0, raw_pattern(0))])
        decoder = feed_chunks(AudioPatternDecoder(31250), pcm[:-1200])
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            decoder.finish()

    def test_opaque_stored_slots_are_preserved_but_current_is_validated(self):
        decoder = AudioPatternDecoder()
        expected = [raw_pattern(n) for n in range(11)]
        expected[3] = bytes([255]) * 2624
        expected[4] = bytes(2624)
        for n, data in enumerate(expected):
            for byte in b'\x55' * 48 + frame_bytes(n, data):
                for bit in (0, *(byte >> k & 1 for k in range(8)), 1):
                    decoder._symbol(bit)
        self.assertEqual([f.data for f in decoder.finish()], expected)
        decoder = AudioPatternDecoder()
        with self.assertRaisesRegex(ValueError, 'Invalid Volca'):
            for n in range(11):
                data = bytes(2624) if n == 10 else raw_pattern(n)
                for byte in b'\x55' * 48 + frame_bytes(n, data):
                    for bit in (0, *(byte >> k & 1 for k in range(8)), 1):
                        decoder._symbol(bit)

    def test_header_integrity_sessions_and_duplicates(self):
        # Symbol receiver and validation are tested independently. PCM tests
        # above prove that these bytes are recovered from actual FSK waveforms.
        def receive(decoder, wire):
            for byte in b'\x55' * 48 + wire:
                for bit in (0, *(byte >> k & 1 for k in range(8)), 1):
                    decoder._symbol(bit)
        first = frame_bytes(0, raw_pattern(0))
        for bad, error in [(frame_bytes(0, raw_pattern(0)), 'Duplicate'),
                           (frame_bytes(2, raw_pattern(2)), 'out-of-order'),
                           (frame_bytes(1, raw_pattern(1), 8), 'sessions')]:
            decoder = AudioPatternDecoder()
            receive(decoder, first)
            with self.assertRaisesRegex(ValueError, error):
                receive(decoder, bad)
            with self.assertRaises(ValueError):
                decoder.finish()
        for offset, replacement in [(4, 2), (6, 10), (7, 1), (8, 0), (10, 1)]:
            bad = bytearray(first)
            bad[offset] = replacement
            with self.assertRaisesRegex(ValueError, 'header'):
                receive(AudioPatternDecoder(), bad)

    def test_complete_bank_required_and_extra_frame_rejected(self):
        decoder = AudioPatternDecoder()
        for n in range(11):
            for byte in b'\x55' * 48 + frame_bytes(n, raw_pattern(n)):
                for bit in (0, *(byte >> k & 1 for k in range(8)), 1):
                    decoder._symbol(bit)
        self.assertEqual(len(decoder.finish()), 11)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            for byte in b'\x55' * 48 + frame_bytes(0, raw_pattern(0)):
                for bit in (0, *(byte >> k & 1 for k in range(8)), 1):
                    decoder._symbol(bit)

    def test_wav_format_validation_duration_and_request(self):
        self.assertEqual(request_audio_backup(), bytes.fromhex('f0 42 30 00 01 2d 7d f7'))
        decoder = AudioPatternDecoder(48000, max_seconds=1)
        with self.assertRaisesRegex(ValueError, 'duration'):
            decoder.feed(bytes(48001 * 2))
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'wrong.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(40))
            with self.assertRaisesRegex(ValueError, 'mono'):
                decode_wav(path)
        decoder = AudioPatternDecoder()
        decoder.feed(b'\0')
        with self.assertRaisesRegex(ValueError, 'PCM16'):
            decoder.finish()


if __name__ == '__main__':
    unittest.main()
