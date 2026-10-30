"""Offscreen kit archive checks using only temporary synthetic files."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
QT_AVAILABLE = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(QT_AVAILABLE, 'Optional Desktop App dependencies are not installed')
class KitArchiveDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from volcastudio.config import Config
        from volcastudio.outie_kit_archive import KitArchiveDialog
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.config = Config(*(root / p for p in ('config', 'data', 'state', 'cache', 'packs', 'syro')))
        self.config.initialize()
        self.kit = self.config.kits / 'test-kit'
        self.kit.mkdir()
        (self.kit / 'notes.txt').write_bytes(b'synthetic kit fixture\n')
        self.changes = []
        self.busy = False
        self.dialog = KitArchiveDialog(self.config, is_busy=lambda: self.busy,
                                      on_changed=lambda *args: self.changes.append(args))
        self.addCleanup(self.dialog.close)
        self.errors = []
        self.error_patch = patch('PySide6.QtWidgets.QMessageBox.warning', side_effect=lambda *args: self.errors.append(args[2]))
        self.error_patch.start()
        self.addCleanup(self.error_patch.stop)

    def confirm(self):
        from PySide6.QtWidgets import QMessageBox
        return patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes)

    def test_confirmed_archive_restore_preserves_bytes_and_notifies(self):
        original = (self.kit / 'notes.txt').read_bytes()
        self.dialog.saved.setCurrentRow(0)
        with self.confirm():
            self.dialog.archive_selected()
        self.assertFalse(self.kit.exists())
        self.assertEqual(self.dialog.archived.count(), 1)
        self.assertEqual(self.changes, [('archived', self.kit)])
        archived = next((self.config.data / 'trash').glob('*/kit'))
        self.assertEqual((archived / 'notes.txt').read_bytes(), original)
        self.dialog.archived.setCurrentRow(0)
        with self.confirm():
            self.dialog.restore_selected()
        self.assertEqual((self.kit / 'notes.txt').read_bytes(), original)
        self.assertEqual(self.dialog.saved.count(), 1)
        self.assertEqual(self.dialog.archived.count(), 0)
        self.assertEqual(self.changes[-1], ('restored', self.kit))
        self.assertFalse(self.errors)

    def test_cancel_keeps_saved_kit_and_defaults_to_cancel(self):
        from PySide6.QtWidgets import QMessageBox
        self.dialog.saved.setCurrentRow(0)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel) as question:
            self.dialog.archive_selected()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.Cancel)
        self.assertTrue(self.kit.exists())
        self.assertFalse(self.changes)
        self.assertFalse((self.config.data / 'trash').exists())

    def test_restore_collision_keeps_both_versions(self):
        from volcastudio.kits import delete_kit
        entry = delete_kit(self.config, self.kit)
        self.kit.mkdir()
        (self.kit / 'notes.txt').write_text('new version')
        self.dialog.refresh()
        self.dialog.archived.setCurrentRow(0)
        with self.confirm():
            self.dialog.restore_selected()
        self.assertEqual((self.kit / 'notes.txt').read_text(), 'new version')
        self.assertEqual((entry / 'kit' / 'notes.txt').read_bytes(), b'synthetic kit fixture\n')
        self.assertIn('already exists', self.errors[0])
        self.assertFalse(self.changes)

    def test_busy_owner_and_shared_transfer_lock_refuse_mutations(self):
        from volcastudio.transfer import device_lock
        self.dialog.saved.setCurrentRow(0)
        self.busy = True
        self.dialog.update_controls()
        self.assertFalse(self.dialog.archive_button.isEnabled())
        with patch('PySide6.QtWidgets.QMessageBox.question') as question:
            self.dialog.archive_selected()
        question.assert_not_called()
        self.assertIn('operation is in progress', self.errors[-1])
        self.busy = False
        self.dialog.saved.setCurrentRow(0)
        with device_lock(self.config.state), self.confirm():
            self.dialog.archive_selected()
        self.assertIn('transfer is active', self.errors[-1])
        self.assertTrue(self.kit.exists())
        self.assertFalse(self.changes)

    def test_operation_started_during_confirmation_is_refused(self):
        from PySide6.QtWidgets import QMessageBox
        self.dialog.saved.setCurrentRow(0)
        def start_job(*args):
            self.busy = True
            return QMessageBox.StandardButton.Yes
        with patch('PySide6.QtWidgets.QMessageBox.question', side_effect=start_job):
            self.dialog.archive_selected()
        self.assertTrue(self.kit.exists())
        self.assertFalse(self.changes)
        self.assertIn('operation is in progress', self.errors[-1])

    def test_open_callback_and_unreadable_archive_listing(self):
        entry = self.config.data / 'trash' / 'broken'
        entry.mkdir(parents=True)
        (entry / 'kit').mkdir()
        (entry / 'record.json').write_text('{invalid json')
        self.dialog.refresh()
        self.assertEqual(self.dialog.archived.count(), 0)
        self.assertIn('1 unreadable', self.dialog.status.text())
        opened = []
        self.dialog.on_open = opened.append
        self.dialog.saved.setCurrentRow(0)
        self.dialog.open_selected()
        self.assertEqual(opened, [self.kit])
        self.assertTrue(self.kit.exists())
        self.assertFalse(self.changes)


if __name__ == '__main__':
    unittest.main()
