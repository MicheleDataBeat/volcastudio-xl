import io
import fcntl
import os
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_studio import wav
from volcastudio.config import Config
from volcastudio.kits import awards, commit_kit, delete_kit, restore_kit, fingerprint
from volcastudio.transfer import pack_files

ROOT = Path(__file__).resolve().parents[1]


class KitManagementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = Config(*(self.root / name for name in ('config', 'data', 'state', 'cache', 'external', 'syro')))
        self.cfg.initialize()
        self.kit = self.cfg.kits / 'test_kit'
        wav(self.kit / '00_one.wav')
        wav(self.kit / '01_two.wav')
        (self.kit / '01_two.json').write_text(json.dumps({'factor': 2, 'source': '/original.wav'}))
        self.before = fingerprint(self.kit)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_restore_and_collision_keep_samples(self):
        entry = delete_kit(self.cfg, self.kit)
        self.assertFalse(self.kit.exists())
        self.assertEqual(fingerprint(entry / 'kit'), self.before)
        wav(self.kit / 'new.wav')
        with self.assertRaises(ValueError):
            restore_kit(self.cfg, entry.name)
        self.assertTrue((entry / 'kit').exists())
        (self.kit / 'new.wav').unlink()
        self.kit.rmdir()
        self.assertEqual(restore_kit(self.cfg, entry.name), self.kit)
        self.assertEqual(fingerprint(self.kit), self.before)

    def test_external_and_symlink_deletion_refused(self):
        external = self.cfg.sources_dir / 'original'
        wav(external / 'sound.wav')
        link = self.cfg.kits / 'link'
        link.symlink_to(external, target_is_directory=True)
        for path in (external, link, self.cfg.kits):
            with self.assertRaises(ValueError):
                delete_kit(self.cfg, path)
        self.assertTrue((external / 'sound.wav').exists())

    def test_edit_commit_archives_previous_version(self):
        staged = self.cfg.kits / '.volcastudio-fixture'
        wav(staged / '00_new.wav', seconds=.02)
        commit_kit(self.cfg, staged, self.kit.name, self.kit, self.before)
        self.assertTrue((self.kit / '00_new.wav').exists())
        previous = next((self.cfg.data / 'trash').glob('*/kit'))
        self.assertEqual(fingerprint(previous), self.before)

    def test_exact_full_memory_and_slots_are_saved_with_capacity_award(self):
        staged = self.cfg.kits / '.volcastudio-full'
        for i in range(100):
            wav(staged / f'{i:02d}_sample.wav', seconds=.65)
        _, _, seconds = pack_files(staged)
        self.assertEqual(seconds, 65)
        target = commit_kit(self.cfg, staged, 'full_kit')
        record = json.loads((target / '.studio-kit.json').read_text())
        self.assertEqual(record['awards'][-1], 'capacity')
        self.assertEqual(record['slots'], 100)

    def test_stale_or_invalid_edit_never_replaces_kit(self):
        staged = self.cfg.kits / '.volcastudio-fixture'
        wav(staged / '00_new.wav')
        with self.assertRaises(ValueError):
            commit_kit(self.cfg, staged, self.kit.name, self.kit, 'stale')
        self.assertEqual(fingerprint(self.kit), self.before)

        self.assertTrue(staged.exists())
        (staged / '00_new.wav').write_bytes(b'invalid')
        with self.assertRaises(ValueError):
            commit_kit(self.cfg, staged, self.kit.name, self.kit, self.before)
        self.assertEqual(fingerprint(self.kit), self.before)

    def test_failed_publication_restores_old_kit(self):
        staged = self.cfg.kits / '.volcastudio-failure'
        wav(staged / 'new.wav')
        rename = Path.rename
        def fail_staged(path, target):
            if path == staged:
                raise OSError('simulated publication failure')
            return rename(path, target)
        with patch.object(Path, 'rename', autospec=True, side_effect=fail_staged):
            with self.assertRaises(OSError):
                commit_kit(self.cfg, staged, self.kit.name, self.kit, self.before)
        self.assertEqual(fingerprint(self.kit), self.before)
        self.assertEqual(list((self.cfg.data / 'trash').iterdir()), [])

class AwardTests(unittest.TestCase):
    def test_thresholds_and_combined_award_are_distinct(self):
        self.assertEqual(awards(90, 61.74), [])
        self.assertEqual(awards(90, 61.75)[-1], 'refined95')
        self.assertEqual(awards(90, 64.35)[-1], 'refined99')
        self.assertEqual(awards(90, 65)[-1], 'memory100')
        self.assertEqual(awards(100, 10)[-1], 'slots100')
        self.assertEqual(awards(100, 65)[-1], 'capacity')
        for value in (float('nan'), float('inf'), -1, 66):
            with self.assertRaises(ValueError):
                awards(1, value)

