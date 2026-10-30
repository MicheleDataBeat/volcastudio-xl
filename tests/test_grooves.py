import copy
import json
import random
import struct
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from volcastudio.grooves import (CATALOG_PATH, MICRO_OFFSETS, apply_pattern,
                                 load_catalog, microtiming, plan_grooves, save_groove_plan)
from volcastudio.patterns import Pattern, PATTERN_SIZE, blank_pattern, load_bank, save_bank


def populated(slot=0, firmware='lumon-xl', valid=0x3ff):
    """Canonical packed motion plus content in every opaque/native field."""
    data = bytearray(blank_pattern('lumon-xl', slot).data)
    rng = random.Random(71 + (slot or 0))
    data[0x20:0xa3c] = rng.randbytes(0xa1c)
    for part in range(10):
        base = part * 256
        for offset in (0x35, 0x36, 0x37, 0x39):
            data[base + offset] = 0
        for step in range(16):
            values = [rng.choice((0, *range(128, 256))) for _ in range(3)]
            if firmware == 'lumon-xl':
                code = sum((value - 127 if value else 0) * 129 ** index for index, value in enumerate(values))
                data[base + 0xa0 + step] = code & 255
                data[base + 0xb0 + step] = (code >> 8) & 255
                data[base + 0x110 + step] = code >> 16
                mode = (part * 16 + step) % 16
                meta, shift = base + (0x35, 0x36, 0x37, 0x39)[step >> 2], 2 * (step & 3)
                data[meta] |= (mode & 3) << shift
                data[base + 0x110 + step] |= (mode >> 2) << 6
            else:
                for offset, value in zip((0xa0, 0xb0, 0x110), values):
                    data[base + offset + step] = value
    data[0xa20:0xa24] = b'LMX2' if firmware == 'lumon-xl' else b'OLD!'
    struct.pack_into('<H', data, 0xa30, valid)
    return Pattern(slot, bytes(data))


class GrooveCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_compatible_inventory_is_deduplicated_without_losing_musical_names(self):
        catalog = self.catalog
        self.assertEqual(len(catalog.profiles), 217)
        self.assertEqual(len(catalog.templates), 270)
        self.assertEqual(Counter(t.category for t in catalog.templates),
                         {'analytic': 4, 'mpc3000': 96, 'dilla': 168, 'dangelo': 2})
        self.assertEqual(len({p.microtiming for p in catalog.profiles}), len(catalog.profiles))
        for category, expected in [('mpc3000', 87), ('dilla', 128), ('dangelo', 2)]:
            profiles = {t.profile_id for t in catalog.templates if t.category == category}
            self.assertEqual(len(profiles), expected)
        alias_ids = {t.id for t in catalog.templates}
        self.assertEqual(alias_ids, {a for p in catalog.profiles for a in p.aliases})
        for profile in catalog.profiles:
            self.assertEqual(catalog.resolve(profile.id).microtiming, profile.microtiming)
            self.assertEqual(tuple(t.id for t in catalog.aliases_for(profile.id)), profile.aliases)
            for alias in profile.aliases:
                self.assertEqual(catalog.resolve(alias).microtiming, profile.microtiming)
        for template in catalog.templates:
            self.assertEqual(len(template.microtiming), 16)
            self.assertTrue(all(-15 <= value <= 15 for value in template.microtiming))
        with self.assertRaises(ValueError):
            catalog.resolve('SEXTUPLE_4_2')

    def test_source_phase_authored_strength_and_reconstruction_survive(self):
        catalog = self.catalog
        expected_mpc = (0, 7, 0, 7, 0, 5, 0, 7, -1, 5, -1, 5, 0, 7, 0, 5)
        self.assertEqual(catalog.resolve('MPC3000_60_B01').microtiming, expected_mpc)
        self.assertNotEqual(catalog.resolve('MPC3000_50_B01').microtiming, (0,) * 16)
        kick, hat = catalog.resolve('DILLA_KICK_5_B01'), catalog.resolve('DILLA_HAT_5_B01')
        self.assertEqual((kick.family, kick.bar, kick.role), (5, 1, 'kick'))
        self.assertEqual(kick.provenance['shared_nominal_origin_tick'],
                         hat.provenance['shared_nominal_origin_tick'])
        self.assertEqual(hat.microtiming, (0, 1, 0, 3, -4, 3, 0, 0, -3, 3, 0, 3, -4, 1, 0, 1))
        self.assertEqual(hat.measured_count, 16)
        self.assertGreater(kick.inferred_count, 0)
        self.assertEqual(kick.measured_count + kick.inferred_count, 16)
        spanish = catalog.resolve('DANGELO_SPANISH_JOINT_B03')
        charade = catalog.resolve('DANGELO_THE_CHARADE_B01')
        self.assertEqual((spanish.measured_count, spanish.inferred_count), (16, 0))
        self.assertEqual((charade.measured_count, charade.inferred_count), (8, 8))
        self.assertEqual(spanish.provenance['timing_percent'], '87')
        self.assertEqual(charade.provenance['timing_percent'], '100')
        self.assertFalse(spanish.provenance['random_and_velocity_applied'])
        self.assertEqual(spanish.microtiming, (0, 5, -1, 1, 3, 1, 1, 0, 1, -4, -3, 3, 2, 6, 2, 7))
        self.assertEqual(catalog.resolve('QUINTUPLE_3_2').microtiming,
                         tuple(6 if i % 2 else 0 for i in range(16)))
        self.assertEqual(catalog.resolve('SEPTUPLE_4_3').microtiming,
                         tuple(5 if i % 2 else 0 for i in range(16)))
        self.assertEqual(catalog.resolve('STRAIGHT').inferred_count, 0)
        portable = CATALOG_PATH.read_text()
        self.assertNotIn('/home/', portable)
        self.assertNotIn('/tmp/', portable)
        self.assertNotIn('data_base64', portable)

    def test_corrupt_vectors_fractions_aliases_and_versions_are_rejected(self):
        original = json.loads(CATALOG_PATH.read_text())
        def corrupt_version(value): value['version'] = True
        def corrupt_vector(value): value['profiles'][0]['microtiming'][0] = 16
        def corrupt_bool(value): value['profiles'][0]['microtiming'][0] = True
        def corrupt_fraction(value): value['templates'][0]['exact_microtiming'][0] = [1, 0]
        def mismatch_fraction(value): value['templates'][0]['exact_microtiming'][0] = [1, 1]
        def corrupt_alias(value): value['profiles'][0]['aliases'].append('MISSING_ALIAS')
        def duplicate_profile(value): value['profiles'].append(copy.deepcopy(value['profiles'][0]))
        def duplicate_alias(value): value['templates'].append(copy.deepcopy(value['templates'][0]))
        def missing_source(value): value['sources'] = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            for mutation in (corrupt_version, corrupt_vector, corrupt_bool, corrupt_fraction,
                             mismatch_fraction, corrupt_alias, duplicate_profile, duplicate_alias,
                             missing_source):
                with self.subTest(mutation=mutation.__name__):
                    value = copy.deepcopy(original)
                    mutation(value)
                    path.write_text(json.dumps(value))
                    with self.assertRaises(ValueError):
                        load_catalog(path)


class GroovePatternTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_only_selected_microtiming_bytes_and_valid_bits_change(self):
        original = populated(valid=0xf881)
        assignment = {2: 'DANGELO_SPANISH_JOINT_B03', 10: 'DILLA_HAT_5_B01'}
        patched = apply_pattern(original, assignment, self.catalog)
        allowed = {0xa30, 0xa31}
        for part in assignment:
            allowed.update((part - 1) * 256 + offset for offset in MICRO_OFFSETS)
            allowed.update((12 + 2 * (part - 1), 13 + 2 * (part - 1)))
        changes = {i for i, (a, b) in enumerate(zip(original.data, patched.data)) if a != b}
        self.assertTrue(changes)
        self.assertLessEqual(changes, allowed)
        original_valid = struct.unpack_from('<H', original.data, 0xa30)[0]
        new_valid = struct.unpack_from('<H', patched.data, 0xa30)[0]
        self.assertEqual(new_valid, original_valid | (1 << 1) | (1 << 9))
        for part, ident in assignment.items():
            self.assertEqual(microtiming(patched, part), self.catalog.resolve(ident).microtiming)
        for part in set(range(1, 11)) - assignment.keys():
            self.assertEqual(microtiming(original, part), microtiming(patched, part))
        self.assertEqual(patched.data[0xa24:0xa30], original.data[0xa24:0xa30], 'echo/ratchet/slices')
        self.assertEqual(patched.data[0xa32:0xa3c], original.data[0xa32:0xa3c], 'remaining extension data')
        self.assertEqual(apply_pattern(patched, assignment, self.catalog), patched)
        self.assertEqual(apply_pattern(original, {}, self.catalog), original)

    def test_native_initialization_packs_motion_losslessly(self):
        from volcastudio.pattern_format import motion_value, predictability
        original = populated(firmware='native')
        for selected in range(1, 11):
            patched = apply_pattern(original, {selected: 'QUINTUPLE_3_2'}, self.catalog)
            self.assertEqual(patched.firmware, 'lumon-xl')
            for part in range(1, 11):
                self.assertEqual(predictability(patched, part), (0,) * 16)
                for step in range(1, 17):
                    for param, offset in ((3, 0xa0), (4, 0xb0), (10, 0x110)):
                        self.assertEqual(motion_value(patched, part, step, param), original.data[(part - 1) * 256 + offset + step - 1])
                expected = self.catalog.resolve('QUINTUPLE_3_2').microtiming if part == selected else (0,) * 16
                self.assertEqual(microtiming(patched, part), expected)
        self.assertEqual(apply_pattern(original, {}, self.catalog), original)

    def test_full_bank_is_retained_but_output_contains_selected_slots_only(self):
        source = tuple(populated(n) for n in range(10)) + (populated(None),)
        plan = plan_grooves(source, {1: 'DILLA_KICK_5_B01', 3: 'SEPTUPLE_4_3'}, [8, 2], self.catalog)
        self.assertEqual(plan.slots, (2, 8))
        self.assertEqual(tuple(p.slot for p in plan.selected_patterns), (2, 8))
        self.assertEqual(plan.rollback_patterns, (source[2], source[8]))
        self.assertEqual(plan.full_source, source)
        self.assertTrue(plan.as_dict()['current_snapshot_retained'])
        self.assertEqual(plan.as_dict()['slots'], [3, 9])
        all_plan = plan_grooves(source, {n: 'STRAIGHT' for n in range(1, 11)}, 'all', self.catalog)
        self.assertEqual(len(all_plan.selected_patterns), 10)
        for pattern in all_plan.selected_patterns:
            for part in range(1, 11):
                self.assertEqual(microtiming(pattern, part), (0,) * 16)
        self.assertEqual(source[-1], plan.full_source[-1])

    def test_current_requires_explicit_destination_and_preserves_original_source(self):
        current = populated(None)
        with self.assertRaises(ValueError):
            plan_grooves([current], {1: 'STRAIGHT'}, [0], self.catalog)
        destination = Pattern(4, current.data)
        plan = plan_grooves([destination], {1: 'STRAIGHT'}, [4], self.catalog, source_bank=[current])
        self.assertEqual(plan.selected_patterns[0].slot, 4)
        self.assertEqual(plan.full_source, (current,))

    def test_invalid_selections_are_rejected_before_a_plan_is_created(self):
        source = [populated(0)]
        for assignments in ({True: 'STRAIGHT'}, {0: 'STRAIGHT'}, {11: 'STRAIGHT'},
                            {1: 'MISSING'}, {1: None}, []):
            with self.subTest(assignments=assignments), self.assertRaises(ValueError):
                plan_grooves(source, assignments, [0], self.catalog)
        for slots in ('all', [], [0, 0], [True], [10], [1], '1', None):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                plan_grooves(source, {1: 'STRAIGHT'}, slots, self.catalog)
        for patterns in ([], [source[0], source[0]]):
            with self.assertRaises(ValueError):
                plan_grooves(patterns, {1: 'STRAIGHT'}, [0], self.catalog)
        opaque = Pattern(1, bytes([255]) * PATTERN_SIZE)
        with self.assertRaises(ValueError):
            plan_grooves(source + [opaque], {1: 'STRAIGHT'}, [0, 1], self.catalog)
        unknown = bytearray(source[0].data)
        unknown[0xa20:0xa24] = b'LUM2'
        with self.assertRaises(ValueError):
            apply_pattern(Pattern(0, bytes(unknown)), {1: 'STRAIGHT'}, self.catalog)
        with self.assertRaises(ValueError):
            plan_grooves(source, {1: 'STRAIGHT'}, [0], self.catalog, firmware='pajen7')
        with self.assertRaises(ValueError):
            plan_grooves(source, {1: 'STRAIGHT'}, [0], self.catalog, reset=1)

    def test_reset_plus_groove_replaces_only_selected_slots_with_native_defaults(self):
        original = (populated(0), Pattern(1, bytes([255]) * PATTERN_SIZE), populated(None))
        plan = plan_grooves(original, {4: 'DANGELO_THE_CHARADE_B01'}, [0, 1], self.catalog, reset=True)
        self.assertEqual(plan.as_dict()['mode'], 'reset+groove')
        self.assertEqual(plan.full_source, original)
        for actual in plan.selected_patterns:
            expected = apply_pattern(blank_pattern('lumon-xl', actual.slot),
                                     {4: 'DANGELO_THE_CHARADE_B01'}, self.catalog)
            self.assertEqual(actual, expected)
            for part in range(1, 11):
                base = (part - 1) * 256
                self.assertEqual(actual.data[base + 0x35], 0, 'Predictability ALL')
                self.assertEqual(actual.data[base + 0x3b], 0, 'bar filtering 4/4')
                self.assertEqual(actual.data[base + 0x40:base + 0x100], bytes(192), 'notes/motion')
            self.assertEqual(actual.data[0xa24:0xa30], bytes(12), 'echo/ratchet/slice defaults')

    def test_partial_reset_all_preserves_only_real_source_in_rollback(self):
        original = [populated(2)]
        plan = plan_grooves(original, {1: 'STRAIGHT'}, 'all', self.catalog, reset=True)
        self.assertEqual(plan.slots, tuple(range(10)))
        self.assertEqual(plan.full_source, tuple(original))
        self.assertEqual(plan.unbacked_slots, (0, 1, 3, 4, 5, 6, 7, 8, 9))
        report = plan.as_dict()
        self.assertIsNone(report['patterns'][0]['source_sha256'])
        self.assertEqual(report['patterns'][2]['source_sha256'], original[0].sha256)
        with tempfile.TemporaryDirectory() as directory:
            output, rollback = save_groove_plan(Path(directory) / 'reset.vspatterns', plan)
            self.assertEqual(len(load_bank(output)), 10)
            self.assertEqual(load_bank(rollback), original)
        with self.assertRaisesRegex(ValueError, 'every selected stored slot'):
            plan_grooves(original, {1: 'STRAIGHT'}, 'all', self.catalog)

    def test_standalone_reset_needs_no_backup_and_does_not_invent_one(self):
        plan = plan_grooves(None, {6: 'QUINTUPLE_3_2'}, [1, 7], self.catalog, reset=True)
        self.assertEqual(tuple(p.slot for p in plan.selected_patterns), (1, 7))
        self.assertEqual(plan.full_source, ())
        self.assertFalse(plan.original_backup_available)
        self.assertFalse(plan.as_dict()['source_preserved'])
        self.assertIsNone(plan.as_dict()['patterns'][0]['source_sha256'])
        self.assertIn('unavailable', plan.as_dict()['rollback'])
        self.assertEqual(len(plan_grooves(None, {}, 'all', self.catalog, reset=True).selected_patterns), 10)
        with self.assertRaises(ValueError):
            plan_grooves(None, {}, [0], self.catalog)
        with self.assertRaises(ValueError):
            plan_grooves(None, {}, [0], self.catalog, source_bank=[populated(0)], reset=True)

    def test_native_decode_clamps_raw_eight_and_respects_inactive_parts(self):
        data = bytearray(blank_pattern('lumon-xl', 0).data)
        data[0x26] = 0
        data[12:14] = b'\xff\xff'
        struct.pack_into('<H', data, 0xa30, 1)
        self.assertEqual(microtiming(Pattern(0, bytes(data)), 1)[:2], (-15, -15))
        struct.pack_into('<H', data, 0xa30, 0)
        self.assertEqual(microtiming(Pattern(0, bytes(data)), 1), (0,) * 16)

    def test_publication_preserves_full_original_bank_and_refuses_existing_paths(self):
        source = tuple(populated(n) for n in range(10)) + (populated(None),)
        plan = plan_grooves(source, {1: 'STRAIGHT'}, [0, 9], self.catalog)
        with tempfile.TemporaryDirectory() as directory:
            original_file = Path(directory) / 'original.vspatterns'
            save_bank(original_file, source)
            original_bytes = original_file.read_bytes()
            output = Path(directory) / 'modified.vspatterns'
            actual, rollback = save_groove_plan(output, plan)
            self.assertEqual(actual, output)
            self.assertEqual(load_bank(output), list(plan.selected_patterns))
            self.assertEqual(load_bank(rollback), list(source))
            self.assertEqual(original_file.read_bytes(), original_bytes)
            with self.assertRaises(FileExistsError):
                save_groove_plan(output, plan)
            self.assertEqual(load_bank(rollback), list(source))
            with self.assertRaises(ValueError):
                save_groove_plan(Path(directory) / 'same', plan, Path(directory) / 'same')
            output2 = Path(directory) / 'modified2.vspatterns'
            existing_rollback = Path(directory) / 'existing.vspatterns'
            existing_rollback.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                save_groove_plan(output2, plan, existing_rollback)
            self.assertEqual(existing_rollback.read_bytes(), b'keep')
            self.assertFalse(output2.exists())
            self.assertEqual(list(Path(directory).glob('.pattern-bank-*')), [])

    def test_second_publication_failure_removes_only_our_new_rollback(self):
        plan = plan_grooves([populated(0)], {1: 'STRAIGHT'}, [0], self.catalog)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'modified.vspatterns'
            def racing_save(path, patterns):
                if Path(path) == output:
                    output.write_bytes(b'created by another writer')
                    raise FileExistsError('racing writer')
                return save_bank(path, patterns)
            with patch('volcastudio.grooves.save_bank', side_effect=racing_save):
                with self.assertRaises(FileExistsError):
                    save_groove_plan(output, plan)
            self.assertEqual(output.read_bytes(), b'created by another writer')
            self.assertFalse(output.with_name('modified.rollback.vspatterns').exists())

    def test_standalone_publication_produces_only_patch_bank(self):
        plan = plan_grooves(None, {2: 'SEPTUPLE_4_3'}, [3], self.catalog, reset=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new.vspatterns'
            path, rollback = save_groove_plan(output, plan)
            self.assertEqual(path, output)
            self.assertIsNone(rollback)
            self.assertEqual(load_bank(output), list(plan.selected_patterns))
            self.assertEqual(list(Path(directory).iterdir()), [output])
            with self.assertRaises(FileExistsError):
                save_groove_plan(output, plan)
            with self.assertRaises(ValueError):
                save_groove_plan(Path(directory) / 'other', plan, Path(directory) / 'fake-rollback')



def populated_lmx3(slot=0, valid=0x3ff, seed=97):
    """Random content everywhere plus valid LMX3 joint motion/Predictability codes."""
    rng = random.Random(seed + (slot or 0))
    data = bytearray(blank_pattern('lumon-xl-internal', slot).data)
    data[0x20:0xa3c] = rng.randbytes(0xa1c)
    for part in range(10):
        base = part * 256
        for step in range(16):
            number = rng.randrange(24) * 129 ** 3 + rng.randrange(129 ** 3)
            data[base + 0xa0 + step] = number & 255
            data[base + 0xb0 + step] = (number >> 8) & 255
            data[base + 0x110 + step] = (number >> 16) & 255
            meta, shift = base + (0x35, 0x36, 0x37, 0x39)[step >> 2], 2 * (step & 3)
            data[meta] = data[meta] & ~(3 << shift) | ((number >> 24) << shift)
    data[0xa20:0xa24] = b'LMX3'
    struct.pack_into('<H', data, 0xa30, valid)
    return Pattern(slot, bytes(data))


class GrooveDataBeatFormatTests(unittest.TestCase):
    """Grooves in the DataBeat OS 1.0 pattern format (LMX3): only timing bytes change."""
    PROFILE = 'lumon-xl-internal'

    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(firmware=cls.PROFILE)

    @staticmethod
    def timing_bytes(parts):
        allowed = {0xa30, 0xa31}
        for part in parts:
            allowed.update((part - 1) * 256 + offset for offset in MICRO_OFFSETS)
            allowed.update((12 + 2 * (part - 1), 13 + 2 * (part - 1)))
        return allowed

    def test_catalog_offers_the_same_profiles_for_both_formats(self):
        lmx2 = load_catalog()
        self.assertEqual(self.catalog.firmware, self.PROFILE)
        self.assertEqual((len(self.catalog.profiles), len(self.catalog.templates)), (217, 270))
        self.assertEqual(self.catalog.profiles, lmx2.profiles)
        self.assertEqual(self.catalog.templates, lmx2.templates)
        with self.assertRaises(ValueError):
            load_catalog(firmware='opaque')

    def test_every_template_and_part_changes_only_timing_bytes(self):
        from volcastudio.pattern_format import motion_value, predictability, validate_lmx3
        original = populated_lmx3(valid=0x0281)
        for template in self.catalog.templates:
            part = 1 + sum(map(ord, template.id)) % 10
            patched = apply_pattern(original, {part: template.id}, self.catalog, firmware=self.PROFILE)
            with self.subTest(template=template.id, part=part):
                validate_lmx3(patched)
                self.assertEqual(patched.data[0xa20:0xa24], b'LMX3')
                changes = {i for i, (a, b) in enumerate(zip(original.data, patched.data)) if a != b}
                self.assertLessEqual(changes, self.timing_bytes([part]))
                self.assertEqual(microtiming(patched, part), template.microtiming)
                self.assertEqual(struct.unpack_from('<H', patched.data, 0xa30)[0], 0x0281 | 1 << (part - 1))
        for part in range(1, 11):
            self.assertEqual(predictability(patched, part), predictability(original, part))
            for step in range(1, 17):
                for param in (3, 4, 10):
                    self.assertEqual(motion_value(patched, part, step, param), motion_value(original, part, step, param))

    def test_all_signed_values_round_trip_on_every_part(self):
        from dataclasses import replace
        from volcastudio.grooves import _apply_resolved
        original = populated_lmx3(valid=0)
        template = self.catalog.templates[0]
        for value in range(-15, 16):
            vector = tuple((value if step % 2 else -value) for step in range(16))
            for part in range(1, 11):
                patched = _apply_resolved(original, [(part, replace(template, microtiming=vector))], self.PROFILE)
                changes = {i for i, (a, b) in enumerate(zip(original.data, patched.data)) if a != b}
                self.assertLessEqual(changes, self.timing_bytes([part]))
                self.assertEqual(microtiming(patched, part), vector)

    def test_native_source_is_initialized_exactly_in_the_destination_format(self):
        from volcastudio.pattern_conversion import convert_pattern
        from volcastudio.pattern_format import convert_native
        original = populated(firmware='native')
        expected_base, issues = convert_pattern(convert_native(original), self.PROFILE)
        self.assertEqual(issues, [])
        patched = apply_pattern(original, {4: 'QUINTUPLE_3_2'}, self.catalog, firmware=self.PROFILE)
        self.assertEqual(patched.firmware, self.PROFILE)
        changes = {i for i, (a, b) in enumerate(zip(expected_base.data, patched.data)) if a != b}
        self.assertLessEqual(changes, self.timing_bytes([4]))
        self.assertEqual(microtiming(patched, 4), self.catalog.resolve('QUINTUPLE_3_2').microtiming)
        self.assertEqual(apply_pattern(original, {}, self.catalog, firmware=self.PROFILE), original)

    def test_formats_are_never_converted_by_a_groove(self):
        lmx2 = populated()
        lmx3 = populated_lmx3()
        with self.assertRaisesRegex(ValueError, 'another pattern format'):
            apply_pattern(lmx2, {1: 'QUINTUPLE_3_2'}, self.catalog, firmware=self.PROFILE)
        with self.assertRaisesRegex(ValueError, 'another pattern format'):
            apply_pattern(lmx3, {1: 'QUINTUPLE_3_2'}, load_catalog(), firmware='lumon-xl')
        with self.assertRaisesRegex(ValueError, 'another pattern format'):
            plan_grooves([lmx2], {1: 'QUINTUPLE_3_2'}, [0], catalog=self.catalog, firmware=self.PROFILE)
        from volcastudio.pattern_format import microtiming as read_timing
        self.assertEqual(microtiming(lmx3, 1), read_timing(lmx3, 1))

    def test_plans_reset_and_preserve_in_the_destination_format(self):
        source = [populated_lmx3(slot) for slot in range(10)]
        plan = plan_grooves(source, {2: 'DANGELO_SPANISH_JOINT_B03'}, [1, 3], catalog=self.catalog, firmware=self.PROFILE)
        self.assertEqual(plan.as_dict()['firmware'], self.PROFILE)
        for before, after in zip(plan.rollback_patterns, plan.selected_patterns):
            changes = {i for i, (a, b) in enumerate(zip(before.data, after.data)) if a != b}
            self.assertLessEqual(changes, self.timing_bytes([2]))
        reset = plan_grooves(None, {1: 'DILLA_KICK_1_B01'}, reset=True, catalog=self.catalog, firmware=self.PROFILE)
        self.assertTrue(all(p.firmware == self.PROFILE for p in reset.selected_patterns))
        for after in reset.selected_patterns:
            base = blank_pattern(self.PROFILE, after.slot)
            changes = {i for i, (a, b) in enumerate(zip(base.data, after.data)) if a != b}
            self.assertLessEqual(changes, self.timing_bytes([1]))


if __name__ == '__main__':
    unittest.main()
