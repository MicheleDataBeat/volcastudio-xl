import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from volcastudio.grooves import apply_pattern, load_catalog, microtiming, save_groove_plan
from volcastudio.patterns import Pattern, blank_pattern, load_bank
from volcastudio.wmc.groove_actions import build_plan, catalog_listing, describe_template


SPANISH = 'DANGELO_SPANISH_JOINT_B03'
CHARADE = 'DANGELO_THE_CHARADE_B01'


def pattern(slot, volume=80):
    data = bytearray(blank_pattern('lumon-xl', slot).data)
    # Give the current snapshot and stored destination audibly different note
    # levels and samples, so retaining the wrong source cannot pass unnoticed.
    data[0x29] = volume
    data[0x20] = volume % 100
    data[0x22] = 0b01010101
    return Pattern(slot, bytes(data))


class WmcGrooveActionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def request(self, **changes):
        value = {'reset': False, 'slots': '3', 'assignments': {'2': SPANISH}}
        value.update(changes)
        return value

    def test_stored_scope_and_all_non_timing_bytes_match_shared_backend(self):
        original = tuple(pattern(slot, 60 + slot) for slot in range(10)) + (pattern(None, 17),)
        before = tuple(item.data for item in original)
        plan = build_plan(original, self.request(slots=' 3, 5-6 ', assignments={'2': SPANISH, '10': CHARADE}), self.catalog)
        self.assertEqual(plan.slots, (2, 4, 5))
        expected = tuple(apply_pattern(original[slot], {2: SPANISH, 10: CHARADE}, self.catalog)
                         for slot in (2, 4, 5))
        self.assertEqual(plan.selected_patterns, expected)
        self.assertEqual(plan.rollback_patterns, tuple(original[slot] for slot in (2, 4, 5)))
        self.assertEqual(plan.full_source, original)
        self.assertEqual(tuple(item.data for item in original), before)
        self.assertTrue(plan.as_dict()['current_snapshot_retained'])
        for item in plan.selected_patterns:
            self.assertEqual(item.data[0x29], 60 + item.slot)
            self.assertEqual(microtiming(item, 2), self.catalog.resolve(SPANISH).microtiming)
            self.assertEqual(microtiming(item, 1), (0,) * 16)

    def test_current_output_uses_snapshot_but_provenance_is_real_stored_target(self):
        original = (pattern(6, 99), pattern(1, 82), pattern(None, 17))
        plan = build_plan(original, self.request(slots='7', current=True, destination=7), self.catalog)
        expected = apply_pattern(Pattern(6, original[-1].data), {2: SPANISH}, self.catalog)
        self.assertEqual(plan.selected_patterns, (expected,))
        self.assertEqual(plan.selected_patterns[0].data[0x29], 17)
        self.assertEqual(plan.rollback_patterns, (original[0],))
        self.assertEqual(plan.full_source, original)
        self.assertEqual(plan.unbacked_slots, ())
        expected_indices = tuple(i for i, (a, b) in enumerate(zip(original[0].data, expected.data)) if a != b)
        self.assertEqual(plan.changes, ((6, expected_indices),))
        self.assertIn(0x29, expected_indices)
        self.assertEqual(plan.as_dict()['patterns'][0]['source_sha256'], original[0].sha256)
        self.assertNotEqual(plan.as_dict()['patterns'][0]['source_sha256'], original[-1].sha256)

        with tempfile.TemporaryDirectory() as directory:
            output, rollback = save_groove_plan(Path(directory) / 'groove.vspatterns', plan)
            self.assertEqual(load_bank(output), [expected])
            self.assertEqual(load_bank(rollback), list(original))
            with self.assertRaises(FileExistsError):
                save_groove_plan(output, plan)
            self.assertEqual(load_bank(rollback), list(original))

    def test_current_destination_without_original_is_explicitly_unbacked(self):
        original = (pattern(0, 99), pattern(None, 17))
        plan = build_plan(original, self.request(slots='7', current=True, destination=7), self.catalog)
        self.assertEqual(plan.unbacked_slots, (6,))
        self.assertIsNone(plan.as_dict()['patterns'][0]['source_sha256'])
        self.assertEqual(plan.as_dict()['unbacked_slots'], [7])
        self.assertEqual(plan.full_source, original)
        self.assertEqual(plan.rollback_patterns, (blank_pattern('lumon-xl', 6),))
        self.assertEqual(plan.selected_patterns[0].data[0x29], 17)

    def test_current_mode_can_replace_an_opaque_stored_target_with_valid_snapshot(self):
        target = Pattern(6, bytes(len(blank_pattern('lumon-xl', 6).data)))
        original = (target, pattern(None, 17))
        plan = build_plan(original, self.request(slots='7', current=True, destination=7), self.catalog)
        self.assertEqual(plan.rollback_patterns, (target,))
        self.assertEqual(plan.full_source, original)
        self.assertEqual(plan.as_dict()['patterns'][0]['source_sha256'], target.sha256)
        self.assertEqual(plan.selected_patterns[0].firmware, 'lumon-xl')

    def test_reset_and_current_reset_use_shared_defaults_and_true_rollback(self):
        original = (pattern(6, 99), pattern(None, 17))
        plan = build_plan(original, self.request(reset=True, slots='7', current=True, destination=7), self.catalog)
        expected = apply_pattern(blank_pattern('lumon-xl', 6), {2: SPANISH}, self.catalog)
        self.assertEqual(plan.selected_patterns, (expected,))
        self.assertEqual(plan.rollback_patterns, (original[0],))
        self.assertEqual(plan.full_source, original)
        self.assertEqual(plan.as_dict()['mode'], 'reset+groove')

        standalone = build_plan(None, self.request(reset=True, slots='ALL'), self.catalog)
        self.assertEqual(standalone.slots, tuple(range(10)))
        self.assertFalse(standalone.original_backup_available)
        self.assertEqual(standalone.unbacked_slots, tuple(range(10)))
        self.assertEqual(standalone.selected_patterns,
                         tuple(apply_pattern(blank_pattern('lumon-xl', n), {2: SPANISH}, self.catalog)
                               for n in range(10)))

    def test_invalid_requests_never_silently_map_or_reset_a_snapshot(self):
        bank = (pattern(6, 99), pattern(None, 17))
        invalid = [None, [], {}, self.request(reset=1), self.request(current=1),
                   self.request(slots=None), self.request(slots=''), self.request(slots='11'),
                   self.request(slots='7-2'), self.request(destination=7),
                   self.request(current=True), self.request(current=True, destination='7'),
                   self.request(current=True, destination=True),
                   self.request(current=True, destination=0), self.request(current=True, destination=11),
                   self.request(current=True, destination=7, slots='all'),
                   self.request(current=True, destination=7, slots='6'),
                   self.request(assignments=[]), self.request(assignments={}),
                   self.request(assignments={'0': SPANISH}), self.request(assignments={'11': SPANISH}),
                   self.request(assignments={True: SPANISH}), self.request(assignments={1.5: SPANISH}),
                   self.request(assignments={'01': SPANISH}), self.request(assignments={'2': []}),
                   self.request(assignments={'2': 'NOT_A_TEMPLATE'}),
                   self.request(assignments={2: SPANISH, '2': CHARADE})]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                build_plan(bank, request, self.catalog)
        with self.assertRaises(ValueError):
            build_plan(None, self.request(), self.catalog)
        with self.assertRaises(ValueError):
            build_plan(None, self.request(reset=True, current=True, destination=7, slots='7'), self.catalog)
        with self.assertRaises(ValueError):
            build_plan((pattern(6),), self.request(current=True, destination=7, slots='7'), self.catalog)
        with self.assertRaises(ValueError):
            build_plan((pattern(None), pattern(None)), self.request(current=True, destination=7, slots='7'), self.catalog)
        with self.assertRaises(ValueError):
            build_plan(bank, self.request(slots='all'), self.catalog)

    def test_unassigned_parts_are_omitted_without_clearing_them(self):
        original = apply_pattern(pattern(2), {1: CHARADE}, self.catalog)
        plan = build_plan((original,), self.request(assignments={'1': '', '2': SPANISH, '3': None}), self.catalog)
        self.assertEqual(microtiming(plan.selected_patterns[0], 1), self.catalog.resolve(CHARADE).microtiming)
        self.assertEqual(plan.selected_patterns[0], apply_pattern(original, {2: SPANISH}, self.catalog))

    def test_catalogue_has_all_grouped_profiles_aliases_and_per_step_evidence(self):
        listing = catalog_listing(self.catalog)
        json.dumps(listing)  # HTTP payload must contain plain JSON values
        self.assertEqual(listing['profiles'], 217)
        self.assertEqual(listing['aliases'], 270)
        self.assertEqual(len(listing['grouped_profiles']), 217)
        self.assertEqual(len(listing['templates']), 270)
        self.assertEqual(listing['categories'], ['all', 'mpc3000', 'dilla', 'dangelo', 'analytic'])
        self.assertEqual(listing['range'], [-15, 15])
        self.assertEqual(listing['step_unit'], [1, 32])
        self.assertEqual(listing['quarter_note_unit'], [1, 128])
        self.assertEqual(listing['reference_swing'], 0)
        grouped = [alias for profile in listing['grouped_profiles'] for alias in profile['aliases']]
        self.assertCountEqual([row['id'] for row in grouped], [t.id for t in self.catalog.templates])
        for profile in listing['grouped_profiles']:
            self.assertEqual(profile['alias_count'], len(profile['aliases']))
            for alias in profile['aliases']:
                self.assertEqual(alias['profile_id'], profile['id'])
                self.assertEqual(alias['microtiming'], profile['microtiming'])
        for record in listing['templates']:
            original = self.catalog.resolve(record['id'])
            for key, value in original.as_dict().items():
                self.assertEqual(record[key], value)
            self.assertEqual([step['step'] for step in record['steps']], list(range(1, 17)))
            self.assertEqual([step['microtiming'] for step in record['steps']], record['microtiming'])
            self.assertEqual(sum(step['measured'] for step in record['steps']), original.measured_count)
            self.assertEqual(sum(step['reconstructed'] for step in record['steps']), original.inferred_count)
            self.assertEqual([step['exact_microtiming'] for step in record['steps']], record['exact_microtiming'])
            self.assertEqual(record['exact_microtiming_strings'],
                             [[str(n), str(d)] for n, d in original.as_dict()['exact_microtiming']])

    def test_catalogue_search_filters_aliases_without_duplicate_profiles(self):
        listing = catalog_listing(self.catalog, category='dangelo')
        self.assertEqual({row['id'] for row in listing['templates']}, {SPANISH, CHARADE})
        self.assertEqual(len(listing['grouped_profiles']), 2)
        exact = catalog_listing(self.catalog, query='dilla_kick_5_b01')
        self.assertEqual([row['id'] for row in exact['templates']], ['DILLA_KICK_5_B01'])
        self.assertEqual(exact['grouped_profiles'][0]['name'], self.catalog.resolve('DILLA_KICK_5_B01').display_name)
        absent = catalog_listing(self.catalog, category='analytic', query='dilla')
        self.assertEqual(absent['templates'], [])
        self.assertEqual(absent['grouped_profiles'], [])
        with self.assertRaises(ValueError):
            catalog_listing(self.catalog, category='unknown')
        with self.assertRaises(ValueError):
            catalog_listing(self.catalog, query=[])

    def test_description_exposes_exact_measurement_mask_provenance_and_aliases(self):
        record = describe_template(self.catalog, CHARADE)
        self.assertEqual(record['microtiming'], list(self.catalog.resolve(CHARADE).microtiming))
        self.assertEqual(record['measured'], 8)
        self.assertEqual(record['reconstructed'], 8)
        self.assertEqual(record['source'], self.catalog.sources[record['provenance']['source']])
        for index, step in enumerate(record['steps']):
            measured = bool(record['measured_mask'] & (1 << index))
            self.assertEqual(step['source'], 'measured' if measured else 'reconstructed')
        by_profile = describe_template(self.catalog, record['profile'])
        self.assertEqual(by_profile['microtiming'], record['microtiming'])
        self.assertIn(CHARADE, [row['id'] for row in by_profile['aliases']])
        analytic = describe_template(self.catalog, 'STRAIGHT')
        self.assertEqual({step['source'] for step in analytic['steps']}, {'analytic'})
        self.assertEqual(analytic['reconstructed'], 0)
        self.assertIsNone(analytic['source'])
        with self.assertRaises(ValueError):
            describe_template(self.catalog, 'unknown')

    def test_export_records_cannot_mutate_cached_catalogue(self):
        record = describe_template(self.catalog, CHARADE)
        record['provenance']['timing_percent'] = 'bad'
        record['source']['title'] = 'bad'
        record['microtiming'][0] = 1234
        listing = catalog_listing(self.catalog)
        listing['sources'][next(iter(listing['sources']))]['title'] = 'bad'
        self.assertEqual(self.catalog.resolve(CHARADE).provenance['timing_percent'], '100')
        self.assertNotEqual(self.catalog.resolve(CHARADE).microtiming[0], 1234)
        self.assertNotIn('bad', [source['title'] for source in self.catalog.sources.values()])

    def test_import_is_available_without_windows_curses(self):
        code = ('import sys; import volcastudio.wmc.groove_actions; '
                'assert "curses" not in sys.modules; '
                'assert "volcastudio.groove_cli" not in sys.modules')
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, text=True, check=True)


if __name__ == '__main__':
    unittest.main()
