"""Shared Browser App registrations in temporary storage, without devices or playback."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from volcastudio import libraries, locking
from volcastudio.config import Config
from volcastudio.wmc import library_actions
from volcastudio.wmc.workspace import Workspace


def wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        stream.writeframes(bytes(882))
    return path.resolve()


class WMCLibraryActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.config = Config(*(self.root / name for name in
                               ('config', 'data', 'state', 'cache', 'packs', 'syro')))
        self.config.initialize()
        self.folder = self.root / 'My Samples'
        self.sample = wav(self.folder / 'drums' / 'kick.wav')
        self.audio = self.sample.read_bytes()
        self.metadata = self.folder / 'README.txt'
        self.metadata.write_text('Preserve this source collection.\n')
        no_devices = patch('volcastudio.desktop_audio._backend',
                           side_effect=AssertionError('No device access allowed'))
        no_devices.start()
        self.addCleanup(no_devices.stop)

    def register(self, name='mine', folder=None):
        return library_actions.register(self.config, str(folder or self.folder), name)

    def test_empty_list_does_not_create_a_registry(self):
        self.assertEqual(library_actions.registrations(self.config), [])
        self.assertFalse(self.config.libraries.exists())

    def test_register_references_source_without_copying_scanning_or_printing(self):
        original = {p.relative_to(self.folder): p.read_bytes()
                    for p in self.folder.rglob('*') if p.is_file()}
        output = io.StringIO()
        with patch('volcastudio.libraries.library', wraps=libraries.library) as shared, \
             patch.object(Path, 'rglob', side_effect=AssertionError('No library scanning')), \
             contextlib.redirect_stdout(output):
            entry = self.register()
        self.assertEqual(output.getvalue(), '')
        shared.assert_called_once()
        self.assertTrue(shared.call_args.kwargs['quiet'])
        self.assertEqual(shared.call_args.args[1].action, 'add')
        self.assertEqual(entry['id'], 'reg:mine')
        self.assertEqual(entry['root'], str(self.folder))
        self.assertTrue(entry['available'])
        self.assertEqual(self.config.libraries.read_text(), f'mine={self.folder}\n')
        self.assertEqual({p.relative_to(self.folder): p.read_bytes()
                          for p in self.folder.rglob('*') if p.is_file()}, original)
        self.assertEqual(list(self.config.kits.iterdir()), [])

    def test_optional_name_uses_the_shared_backend_name(self):
        entry = library_actions.register(self.config, str(self.folder))
        self.assertEqual(entry['name'], 'my_samples')
        self.assertEqual(library_actions.registrations(self.config), [entry])

    def test_registered_audio_enters_and_leaves_the_existing_read_allowlist(self):
        workspace = Workspace(self.config)
        with self.assertRaisesRegex(ValueError, 'outside Browser App'):
            workspace.resolve_sample(str(self.sample))
        self.register()
        self.assertEqual(workspace.resolve_sample(str(self.sample)), self.sample)
        outside = wav(self.root / 'private' / 'outside.wav')
        with self.assertRaisesRegex(ValueError, 'outside Browser App'):
            workspace.resolve_sample(str(outside))
        library_actions.unregister(self.config, 'mine')
        with self.assertRaisesRegex(ValueError, 'outside Browser App'):
            workspace.resolve_sample(str(self.sample))
        self.assertEqual(self.sample.read_bytes(), self.audio)

    def test_symlinked_sample_cannot_escape_the_registered_root(self):
        outside = wav(self.root / 'private' / 'outside.wav')
        link = self.folder / 'outside.wav'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symlinks is unavailable on this platform')
        self.register()
        with self.assertRaisesRegex(ValueError, 'outside Browser App'):
            Workspace(self.config).resolve_sample(str(link))

    def test_list_and_unregister_include_missing_folders_without_changing_audio(self):
        self.register()
        missing = self.root / 'Disconnected drive' / 'Samples'
        self.config.libraries.write_text(self.config.libraries.read_text() + f'lost={missing}\n')
        entries = library_actions.registrations(self.config)
        self.assertEqual([entry['name'] for entry in entries], ['mine', 'lost'])
        self.assertFalse(entries[1]['available'])
        self.assertEqual(entries[1]['directory'], str(missing))
        with patch('volcastudio.libraries.library', wraps=libraries.library) as shared:
            result = library_actions.unregister(self.config, 'lost')
        shared.assert_called_once()
        self.assertTrue(shared.call_args.kwargs['quiet'])
        self.assertEqual(result, {'removed': True, 'name': 'lost', 'directory': str(missing)})
        self.assertEqual([entry['name'] for entry in library_actions.registrations(self.config)], ['mine'])
        self.assertEqual(self.sample.read_bytes(), self.audio)
        self.assertEqual(self.metadata.read_text(), 'Preserve this source collection.\n')

    def test_duplicate_name_fails_but_shared_directory_alias_is_allowed(self):
        self.register()
        original = self.config.libraries.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already registered'):
            self.register()
        self.assertEqual(self.config.libraries.read_bytes(), original)
        self.register(name='alias')
        library_actions.unregister(self.config, 'mine')
        self.assertEqual(library_actions.registrations(self.config)[0]['name'], 'alias')
        self.assertEqual(Workspace(self.config).resolve_sample(str(self.sample)), self.sample)

    def test_invalid_names_and_paths_do_not_mutate_the_registry(self):
        self.register()
        original = self.config.libraries.read_bytes()
        for name in ('Bad', 'with space', 'a=b', '../other', 'bad\nnew', 'bad\tname', 1, [], {}):
            with self.subTest(name=name), self.assertRaises(ValueError):
                library_actions.register(self.config, str(self.folder), name)
        for path in ('', '.', 'relative/folder', 'bad\npath', 'bad\rpath', 'bad\tpath',
                     'bad\x00path', str(self.root / 'missing'), str(self.sample), None, [], 1):
            with self.subTest(path=path), self.assertRaises(ValueError):
                library_actions.register(self.config, path, 'new')
        for name in ('', None, '../mine', 'MINE', 'mine\nother', [], 1):
            with self.subTest(remove=name), self.assertRaises(ValueError):
                library_actions.unregister(self.config, name)
        self.assertEqual(self.config.libraries.read_bytes(), original)

    def test_source_symlink_resolves_to_the_same_registered_root(self):
        link = self.root / 'Chosen Folder'
        try:
            link.symlink_to(self.folder, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Creating symlinks is unavailable on this platform')
        entry = library_actions.register(self.config, str(link), 'linked')
        self.assertEqual(entry['root'], str(self.folder))
        self.assertEqual(self.config.libraries.read_text(), f'linked={self.folder}\n')

    def test_listing_uses_shared_last_record_wins_rules(self):
        missing = self.root / 'missing'
        self.config.libraries.write_text(f'# comment\n mine = {self.folder}\ninvalid name={self.folder}\n'
                                         f'mine={missing}\n')
        entries = library_actions.registrations(self.config)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], 'mine')
        self.assertEqual(entries[0]['root'], str(missing))
        self.assertFalse(entries[0]['available'])

    def test_unregister_unknown_name_does_not_rewrite_the_registry(self):
        self.register()
        original = self.config.libraries.read_bytes()
        with self.assertRaisesRegex(ValueError, 'No library named other'):
            library_actions.unregister(self.config, 'other')
        self.assertEqual(self.config.libraries.read_bytes(), original)

    def test_shared_busy_lock_refuses_register_and_unregister(self):
        self.register()
        original = self.config.libraries.read_bytes()
        with (self.config.config / 'libraries.lock').open('w') as owner:
            locking.flock(owner, locking.LOCK_EX | locking.LOCK_NB)
            try:
                with self.assertRaises(BlockingIOError):
                    self.register('new')
                with self.assertRaises(BlockingIOError):
                    library_actions.unregister(self.config, 'mine')
            finally:
                locking.flock(owner, locking.LOCK_UN)
        self.assertEqual(self.config.libraries.read_bytes(), original)
        self.assertEqual(self.sample.read_bytes(), self.audio)

    def test_shared_snapshot_check_preserves_concurrent_registration_changes(self):
        self.register()
        original = self.config.libraries.read_text()
        external = original + f'concurrent={self.root / "elsewhere"}\n'
        original_read = libraries.registrations
        calls = 0

        def changed_before_commit(config):
            nonlocal calls
            calls += 1
            if calls == 2:
                config.libraries.write_text(external)
            return original_read(config)

        with patch('volcastudio.libraries.registrations', side_effect=changed_before_commit):
            with self.assertRaisesRegex(ValueError, 'changed concurrently'):
                self.register('new')
        self.assertEqual(self.config.libraries.read_text(), external)
        self.assertEqual(self.sample.read_bytes(), self.audio)

    def test_unregister_preserves_a_change_after_its_initial_lookup(self):
        self.register()
        original = self.config.libraries.read_text()
        external = original + f'concurrent={self.root / "elsewhere"}\n'
        original_read = libraries.registrations
        calls = 0

        def changed_before_commit(config):
            nonlocal calls
            calls += 1
            # One read for the response metadata, then the CLI's snapshot,
            # then its comparison while holding the exclusive lock.
            if calls == 3:
                config.libraries.write_text(external)
            return original_read(config)

        with patch('volcastudio.libraries.registrations', side_effect=changed_before_commit):
            with self.assertRaisesRegex(ValueError, 'changed concurrently'):
                library_actions.unregister(self.config, 'mine')
        self.assertEqual(self.config.libraries.read_text(), external)
        self.assertEqual(self.sample.read_bytes(), self.audio)

    def test_empty_and_missing_registrations_remain_removable(self):
        self.config.libraries.write_text('empty=\n')
        entry = library_actions.registrations(self.config)[0]
        self.assertFalse(entry['available'])
        self.assertEqual(entry['root'], '')
        library_actions.unregister(self.config, 'empty')
        self.assertEqual(self.config.libraries.read_text(), '')


if __name__ == '__main__':
    unittest.main()
