import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools import check_product_name as gate

# Retired names are built from parts so this file stays clean for the gate.
STEM = 'Lu' + 'mon'
OUT, INN, WEB = 'Out' + 'ie', 'Inn' + 'ie', 'W' + 'MC'


class ProductNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.policy = {'schema': 2, 'canonical': 'DataBeat OS', 'studio': 'VolcaStudio XL',
                       'technical_tokens': [STEM.lower() + '-xl', 'volcastudio.' + OUT.lower() + '_model'], 'line_exceptions': {}}
        self.save_policy()

    def save_policy(self):
        (self.root / 'product-name-policy.json').write_text(json.dumps(self.policy))

    def text(self, value, name='README.md'):
        (self.root / name).write_text(value)

    def status(self, **options):
        return gate.check(self.root, **options)['status']

    def test_canonical_names_and_exact_compatibility_tokens(self):
        self.text('DataBeat OS 1.0 in VolcaStudio XL Desktop App; --firmware ' + STEM.lower() + '-xl\n'
                  'from volcastudio.' + OUT.lower() + '_model import x; boot scroll dAtAbEAt OS; databeat-os-1.0.patch.json\n')
        self.assertEqual(self.status(), 'PASS')

    def test_retired_names_rejected_in_each_text_surface(self):
        variants = [STEM, STEM.upper(), STEM + ' OS', STEM + ' Os XL', STEM + 'OS XL', STEM.upper() + 'OS XL',
                    STEM.lower() + ' os xl', STEM + 'OS', r'\n' + STEM.upper() + ' OS', OUT, INN, WEB, WEB.lower(),
                    'Whole ' + 'Mind Collective', 'Volca' + ' Studio XL', 'Volca' + '-Studio-XL-' + OUT + '-1.0.zip',
                    OUT + '.app', 'Data' + 'beat OS', 'DATA' + 'BEAT OS', 'DataBeat' + 'OS']
        for name in ['README.md', 'screen.html', 'translations.js', 'metadata.json', 'screen.svg', 'error.py']:
            for old in variants:
                with self.subTest(name=name, old=old):
                    self.text('Visible ' + old + ' product\n', name)
                    self.assertEqual(self.status(), 'FAIL')

    def test_bare_name_cannot_become_a_technical_token(self):
        for bare in (STEM, STEM + 'OS', OUT, WEB, 'Volca' + ' Studio'):
            with self.subTest(bare=bare):
                self.policy['technical_tokens'] = [bare]
                self.save_policy()
                with self.assertRaises(ValueError):
                    gate.check(self.root)

    def test_history_exception_is_exact_and_counted(self):
        old = 'Historical ' + STEM.upper() + ' OS XL'
        self.policy['line_exceptions'] = {'README.md': {
            gate.digest(old): {'count': 1, 'reason': 'Immutable historical quote'}}}
        self.save_policy()
        self.text(old)
        self.assertEqual(self.status(), 'PASS')
        self.text(old + '\n' + old)
        self.assertEqual(self.status(), 'FAIL')
        self.text(old + ' new claim')
        self.assertEqual(self.status(), 'FAIL')

    def test_rename_backlog_is_counted_per_file_and_strict_requires_none(self):
        self.policy['rename_backlog'] = {'README.md': 2}
        self.save_policy()
        self.text(f'{OUT} one\nclean\n{WEB} two\n')
        result = gate.check(self.root)
        self.assertEqual((result['status'], result['rename_backlog_lines']), ('PASS', 2))
        self.assertEqual(self.status(strict=True), 'FAIL')
        self.text(f'{OUT} one\n{INN} two\n{WEB} three\n')
        self.assertEqual(self.status(), 'FAIL')
        self.text(f'{OUT} one\n')
        self.assertEqual(self.status(), 'PASS')
        self.text(f'{OUT} one\n', 'other.md')
        self.assertEqual(self.status(), 'FAIL')
        (self.root / 'other.md').unlink()
        self.text('clean\n')
        result = gate.check(self.root)
        self.assertEqual(result['stale_backlog_allowances'], {'README.md': 2})
        self.assertEqual(self.status(strict=True), 'PASS')
        self.policy['rename_backlog'] = {'README.md': 0}
        self.save_policy()
        with self.assertRaises(ValueError):
            gate.check(self.root)

    def test_not_exported_files_are_reported_but_exempt(self):
        self.policy['not_exported'] = ['AGENTS.md']
        self.save_policy()
        self.text(f'{STEM.upper()} OS XL internal note\n', 'AGENTS.md')
        result = gate.check(self.root, strict=True)
        self.assertEqual((result['status'], result['not_exported_lines']), ('PASS', 1))

    def test_staged_tree_is_checked_even_with_clean_working_copy(self):
        self.text(STEM.upper() + ' OS XL')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        self.text('DataBeat OS')
        self.assertEqual(self.status(), 'PASS')
        self.assertEqual(gate.check(self.root, 'index')['status'], 'FAIL')

    def test_missing_or_old_policy_fails_closed(self):
        self.policy.update(schema=1, canonical=STEM + 'OS XL')
        self.save_policy()
        with self.assertRaises(ValueError):
            gate.check(self.root)
        (self.root / 'product-name-policy.json').unlink()
        with self.assertRaises(ValueError):
            gate.check(self.root)

    def test_new_untracked_surface_is_checked(self):
        self.text('DataBeat OS')
        self.text(STEM.upper(), 'new-language.txt')
        self.assertEqual(self.status(), 'FAIL')

    def test_new_retired_filename_is_rejected_even_with_canonical_contents(self):
        for name in (STEM.upper() + '-screen.html', STEM.lower() + '_new.py', OUT.lower() + '-guide.md'):
            with self.subTest(name=name):
                self.text('"DataBeat OS"', name)
                self.assertEqual(self.status(), 'FAIL')
                (self.root / name).unlink()
        self.policy['legacy_paths'] = [OUT.lower() + '-guide.md']
        self.save_policy()
        self.text('"DataBeat OS"', OUT.lower() + '-guide.md')
        self.assertEqual(self.status(), 'PASS')

    def test_encoded_data_is_not_a_name(self):
        self.text('data:image/png;base64,' + 'Qx' + WEB.lower() + 'A9' * 40 + '\n')
        self.assertEqual(self.status(), 'PASS')


if __name__ == '__main__':
    unittest.main()
