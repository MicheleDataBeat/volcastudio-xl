import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_audio import audio
from volcastudio.audio import detect_pitch, varispeed_x2
from volcastudio.transfer import checked, inspect_wav
from volcastudio.tuning import (alignment_plan, apply_alignment, filename_pitch,
                               sample_shift, shift_label, varispeed)


class TuningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'cache'
        self.variants = self.root / 'variants'

    def tearDown(self):
        self.tmp.cleanup()

    def tone(self, name, hz, seconds=.5):
        path = self.root / (name + '.wav')
        audio(path, lambda t: math.sin(2 * math.pi * hz * t), seconds=seconds)
        return path

    def test_seven_down_and_twenty_four_up_audio_duration_and_saved_metadata(self):
        source = self.tone('piano_A4', 440)
        before = source.read_bytes()
        down = varispeed(source, -7, self.variants)
        up = varispeed(source, 24, self.variants)
        self.assertAlmostEqual(inspect_wav(down), .5 * 2 ** (7 / 12), delta=.002)
        self.assertAlmostEqual(inspect_wav(up), .125, delta=.002)
        self.assertEqual(detect_pitch(down, self.cache)['note'], 'D4')
        self.assertEqual(detect_pitch(up, self.cache)['note'], 'A6')
        self.assertEqual(shift_label(down), '-7')
        self.assertEqual(shift_label(up), '+24')
        self.assertEqual(json.loads(up.with_suffix('.json').read_text())['factor'], 4)
        # Independent frequency oracle: raw PCM zero crossings, not the pitch
        # estimator that the feature itself uses to construct its proposal.
        import array
        raw = checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', up, '-ac', '1',
                       '-ar', '44100', '-f', 'f32le', '-'], capture_output=True).stdout
        samples = array.array('f')
        samples.frombytes(raw)
        import sys
        if sys.byteorder != 'little':
            samples.byteswap()
        positions = [i for i in range(1, len(samples)) if samples[i - 1] <= 0 < samples[i]]
        frequency = (len(positions) - 1) * 44100 / (positions[-1] - positions[0])
        self.assertAlmostEqual(frequency, 1760, delta=2)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(varispeed(source, 24, self.variants), up)

    def test_zero_identity_and_invalid_values(self):
        source = self.tone('tone', 440)
        self.assertEqual(varispeed(source, 0, self.variants), source)
        for value in (-100, 100, True, 7.5, '07'):
            with self.assertRaises(ValueError):
                varispeed(source, value, self.variants)
        with self.assertRaisesRegex(ValueError, '65 second'):
            varispeed(source, -99, self.variants)

    def test_filename_notes_and_ambiguous_names(self):
        for name, pc in [('loop_F#3.wav', 6), ('bass_Bb.wav', 10), ('phrase_Cmin.wav', 0),
                         ('organ_D_major.wav', 2), ('stab_Eb4.wav', 3)]:
            self.assertEqual(filename_pitch(name)['pc'], pc)
        for name in ('snare.wav', 'cabasa.wav', 'piano_C_D.wav', 'loop_120.wav'):
            self.assertIsNone(filename_pitch(name))
        self.assertEqual(filename_pitch('tone_B#3.wav')['midi'], 60)
        self.assertEqual(filename_pitch('tone_Cb4.wav')['midi'], 59)

    def test_octave_disagreement_requires_explicit_choice(self):
        master = self.tone('master_A4', 440)
        slave = self.tone('slave_A3', 440)
        plan = alignment_plan([master, slave], 0, [1], cache=self.cache)
        self.assertEqual(plan['conflicts'], [1])
        resolved = alignment_plan([master, slave], 0, [1], {1: 'detected'}, cache=self.cache)
        self.assertTrue(resolved['ready'])
        self.assertEqual(resolved['rows'][1]['shift'], 0)

    def test_legacy_x2_on_free_variant_keeps_cumulative_shift(self):
        source = self.tone('tone_A4', 440)
        down = varispeed(source, -7, self.variants)
        result = varispeed_x2(down, self.root / 'x2')
        self.assertEqual(sample_shift(result), 5)
        self.assertEqual(detect_pitch(result, self.cache)['note'], 'D5')
        plan = alignment_plan([source, result], 0, [1], cache=self.cache)
        self.assertFalse(plan['rows'][1]['conflict'])

    def test_existing_varispeed_is_counted_once_and_slave_matches_master(self):
        master = self.tone('master_A4', 440)
        source = self.tone('slave_C4', 261.625565)
        shifted = varispeed(source, 7, self.variants)
        plan = alignment_plan([master, shifted], 0, [1], cache=self.cache)
        self.assertTrue(plan['ready'])
        row = plan['rows'][1]
        self.assertEqual(row['filename_note'], 'G4')
        self.assertFalse(row['conflict'])
        self.assertEqual(row['shift'], 2)
        self.assertEqual(row['final_semitones'], 9)
        outputs = apply_alignment(plan, self.variants)
        self.assertEqual(outputs[0], master)
        self.assertEqual(detect_pitch(outputs[1], self.cache)['note'], 'A4')
        self.assertEqual(sample_shift(outputs[1]), 9)

    def test_discrepancy_requires_choice_and_changes_proposal(self):
        master = self.tone('master_A4', 440)
        slave = self.tone('slave_C4', 293.664768)  # Audio D, label C.
        plan = alignment_plan([master, slave], 0, [1], cache=self.cache)
        self.assertFalse(plan['ready'])
        self.assertEqual(plan['conflicts'], [1])
        with self.assertRaisesRegex(ValueError, 'discrepancies'):
            apply_alignment(plan, self.variants)
        named = alignment_plan([master, slave], 0, [1], {1: 'filename'}, cache=self.cache)
        detected = alignment_plan([master, slave], 0, [1], {1: 'detected'}, cache=self.cache)
        self.assertEqual(named['rows'][1]['shift'], -3)
        self.assertEqual(detected['rows'][1]['shift'], -5)

    def test_uncertain_excluded_but_manual_shift_allowed_and_unselected_untouched(self):
        master = self.tone('master_A', 440)
        noise = self.root / 'drum.wav'
        audio(noise, lambda t: 0)
        keep = self.tone('keep_C', 261.625565)
        plan = alignment_plan([master, noise, keep], 0, [1], cache=self.cache)
        self.assertTrue(plan['ready'])
        self.assertEqual(plan['excluded'], [1])
        self.assertEqual(apply_alignment(plan, self.variants), [master, noise, keep])
        manual = alignment_plan([master, noise, keep], 0, [1], overrides={1: 12}, cache=self.cache)
        self.assertEqual(manual['excluded'], [])
        outputs = apply_alignment(manual, self.variants)
        self.assertEqual(outputs[2], keep)
        self.assertAlmostEqual(inspect_wav(outputs[1]), .25, delta=.002)

    def test_budget_recomputed_and_rejected_before_render_or_draft_mutation(self):
        master = self.tone('master_A', 440)
        slave = self.tone('slave_C', 261.625565)
        # Long-duration oracle independent of pitch computation/render cost.
        from volcastudio.tuning import sample_tuning
        rows = [sample_tuning(p, self.cache) for p in (master, slave)]
        rows[0]['seconds'], rows[1]['seconds'] = 1, 60
        with patch('volcastudio.tuning.sample_tuning', side_effect=rows):
            plan = alignment_plan([master, slave], 0, [1])
        self.assertEqual(plan['rows'][1]['shift'], -3)
        self.assertGreater(plan['seconds'], 72)
        with patch('volcastudio.tuning.varispeed') as render:
            with self.assertRaisesRegex(ValueError, '65 seconds'):
                apply_alignment(plan, self.variants)
            render.assert_not_called()

    def test_stale_source_and_corrupt_cache_fail_closed(self):
        master = self.tone('master_A', 440)
        slave = self.tone('slave_C', 261.625565)
        plan = alignment_plan([master, slave], 0, [1], cache=self.cache)
        slave.touch()
        with self.assertRaisesRegex(ValueError, 'source changed'):
            apply_alignment(plan, self.variants)
        variant = varispeed(master, 12, self.variants)
        variant.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            varispeed(master, 12, self.variants)

    def test_failing_later_render_never_publishes_partial_kit(self):
        master = self.tone('master_A', 440)
        slaves = [self.tone('first_C', 261.625565), self.tone('second_D', 293.664768)]
        plan = alignment_plan([master, *slaves], 0, [1, 2], cache=self.cache)
        with patch('volcastudio.tuning.varispeed', side_effect=[slaves[0], ValueError('fixture')]):
            with self.assertRaisesRegex(ValueError, 'fixture'):
                apply_alignment(plan, self.variants)
        self.assertTrue(all(p.is_file() for p in [master, *slaves]))

    def test_cache_tuning_metadata_cannot_lie_about_unchanged_audio(self):
        source = self.tone('source_A4', 440)
        variant = varispeed(source, 24, self.variants)
        metadata = variant.with_suffix('.json')
        data = json.loads(metadata.read_text())
        data.update(semitones=12, factor=2)
        metadata.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'cache entry'):
            varispeed(source, 24, self.variants)

    def test_outie_plan_analyzes_only_master_and_selected_samples(self):
        import volcastudio.tuning as tuning
        master, slave, keep = self.tone('master_A4', 440), self.tone('slave_C5', 523.25), self.tone('keep_E4', 329.63)
        with patch('volcastudio.tuning.detect_pitch', wraps=tuning.detect_pitch) as detect:
            plan = alignment_plan([master, slave, keep], 0, [1], cache=self.cache, analyze_unselected=False)
        self.assertEqual({Path(call.args[0]) for call in detect.call_args_list}, {master, slave})
        self.assertEqual([row['analyzed'] for row in plan['rows']], [True, True, False])
        self.assertEqual(plan['rows'][1]['shift'], -3)
        self.assertIsNone(plan['rows'][2]['detected_note'])
        self.assertAlmostEqual(plan['rows'][2]['final_seconds'], .5, delta=.002)
        self.assertTrue(plan['ready'])
        outputs = apply_alignment(plan, self.variants)
        self.assertEqual((outputs[0], outputs[2]), (master, keep))
        self.assertEqual(sample_shift(outputs[1]), -3)
        with patch('volcastudio.tuning.detect_pitch', wraps=tuning.detect_pitch) as detect:
            alignment_plan([master, slave, keep], 0, [1], cache=self.cache)
        self.assertEqual(len(detect.call_args_list), 3)

    def test_source_changes_mid_alignment_refuse_complete_result(self):
        sources = [self.tone('master_A', 440), self.tone('slave_C', 261.625565),
                   self.tone('slave_D', 293.664768)]
        plan = alignment_plan(sources, 0, [1, 2], cache=self.cache)
        real = varispeed
        def change_next(source, semitones, variants):
            if Path(source) == sources[1]:
                sources[2].touch()
            return real(source, semitones, variants)
        with patch('volcastudio.tuning.varispeed', side_effect=change_next):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                apply_alignment(plan, self.variants)

    def test_source_and_metadata_changes_during_render_refuse_publication(self):
        source = self.tone('source_A', 440)
        real = checked
        def change_source(args, **kwargs):
            result = real(args, **kwargs)
            if args[0] == 'ffmpeg':
                source.with_suffix('.json').write_text('{}')
            return result
        with patch('volcastudio.tuning.checked', side_effect=change_source):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                varispeed(source, 12, self.variants)
        self.assertEqual(list(self.variants.rglob('*.wav')), [])

    def test_legacy_x2_parent_chain_is_recovered_without_rewriting_it(self):
        source = self.tone('source_A3', 220)
        first = varispeed_x2(source, self.root / 'old')
        second = varispeed_x2(first, self.root / 'old')
        for child, parent in ((first, source), (second, first)):
            child.with_suffix('.json').write_text(json.dumps({'source': str(parent), 'factor': 2, 'semitones': 12}))
        before = [p.with_suffix('.json').read_bytes() for p in (first, second)]
        self.assertEqual(sample_shift(second), 24)
        next_variant = varispeed(second, -7, self.variants)
        self.assertEqual(sample_shift(next_variant), 17)
        self.assertEqual([p.with_suffix('.json').read_bytes() for p in (first, second)], before)
