import array
import math
import os
import random
import tempfile
import unittest
import wave
from pathlib import Path
from volcastudio.audio import detect_pitch, varispeed_x2
from volcastudio.transfer import inspect_wav


def audio(path, generator, seconds=.5, rate=44100):
    values = array.array('h', (max(-32767, min(32767, round(generator(i/rate) * 20000))) for i in range(int(rate*seconds))))
    with wave.open(str(path), 'wb') as out:
        out.setparams((1,2,rate,0,'NONE','not compressed'))
        out.writeframes(values.tobytes())


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'tone.wav'

    def tearDown(self):
        self.tmp.cleanup()

    def test_detects_sine_note_and_cents(self):
        audio(self.source, lambda t: math.sin(2*math.pi*440*t))
        found = detect_pitch(self.source)
        self.assertEqual(found['note'], 'A4')
        self.assertAlmostEqual(found['hz'], 440, delta=3)
        self.assertGreater(found['confidence'], .9)

    def test_detects_fundamental_with_stronger_second_harmonic(self):
        audio(self.source, lambda t: .3*math.sin(2*math.pi*110*t) + .7*math.sin(2*math.pi*220*t))
        self.assertEqual(detect_pitch(self.source)['note'], 'A2')

    def test_silence_and_noise_do_not_get_a_note(self):
        audio(self.source, lambda t: 0)
        self.assertIsNone(detect_pitch(self.source)['note'])
        rng = random.Random(3)
        audio(self.source, lambda t: rng.uniform(-1,1))
        self.assertIsNone(detect_pitch(self.source)['note'])

    def test_pitch_cache_invalidated_on_source_change(self):
        audio(self.source, lambda t: math.sin(2*math.pi*440*t))
        self.assertEqual(detect_pitch(self.source, self.root/'cache')['note'], 'A4')
        audio(self.source, lambda t: math.sin(2*math.pi*220*t))
        self.assertEqual(detect_pitch(self.source, self.root/'cache')['note'], 'A3')

    def test_x2_halves_duration_raises_octave_and_preserves_source(self):
        audio(self.source, lambda t: math.sin(2*math.pi*220*t))
        before = self.source.read_bytes()
        variant = varispeed_x2(self.source, self.root/'variants')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertAlmostEqual(inspect_wav(variant), .25, delta=.002)
        self.assertEqual(detect_pitch(variant)['note'], 'A4')
        self.assertEqual(varispeed_x2(self.source, self.root/'variants'), variant)
        self.assertNotEqual(variant.stat().st_ino, self.source.stat().st_ino)

    def test_explicit_x2_sidecar_never_overwrites(self):
        audio(self.source, lambda t: math.sin(2*math.pi*440*t))
        output = self.root/'new.wav'
        output.with_suffix('.json').write_text('preserve metadata')
        with self.assertRaises(ValueError):
            varispeed_x2(self.source, self.root/'variants', output)
        self.assertFalse(output.exists())
        self.assertEqual(output.with_suffix('.json').read_text(), 'preserve metadata')

    def test_explicit_x2_output_never_overwrites(self):
        audio(self.source, lambda t: math.sin(2*math.pi*440*t))
        output = self.root/'existing.wav'
        output.write_bytes(b'keep me')
        with self.assertRaises(ValueError):
            varispeed_x2(self.source, self.root/'variants', output)
        self.assertEqual(output.read_bytes(), b'keep me')
