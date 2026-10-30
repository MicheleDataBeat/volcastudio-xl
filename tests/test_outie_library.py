"""Native library browsing against temporary libraries; no audio or devices."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
QT_AVAILABLE = importlib.util.find_spec('PySide6') is not None


def tiny_wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(b'\x00\x00' * 441)
    return path.resolve()


@unittest.skipUnless(QT_AVAILABLE, 'Optional Desktop App dependencies are not installed')
class OutieLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from volcastudio.config import Config
        from volcastudio.libraries import library
        from volcastudio.outie import Studio
        from volcastudio.outie_library import LibraryDialog
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.config = Config(*(root/p for p in ('config', 'data', 'state', 'cache', 'packs', 'syro')))
        self.config.initialize()
        self.first = root/'First Library'
        self.second = root/'Second Library'
        self.paths = [tiny_wav(self.first/'drums'/'Kick.wav'),
                      tiny_wav(self.first/'drums'/'Snare.WAV'),
                      tiny_wav(self.first/'tones'/'Bass.wav'),
                      tiny_wav(self.second/'Hat.wav')]
        (self.first/'readme.txt').write_text('not a sample')
        for name, directory in (('first', self.first), ('second', self.second)):
            library(self.config, SimpleNamespace(action='add', directory=str(directory), name=name), quiet=True)
        self.backend_patch = patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('No device access allowed'))
        self.backend_patch.start()
        self.addCleanup(self.backend_patch.stop)
        self.studio = Studio(self.config, discover_devices=False)
        self.dialog = LibraryDialog(self.studio)
        self.addCleanup(self.cleanup_windows)

    def cleanup_windows(self):
        self.dialog.reject()
        self.studio.close()
        self.app.processEvents()

    def drain_scan(self):
        deadline = time.monotonic() + 5
        while self.dialog.scan is not None and self.dialog.scan.isRunning():
            self.app.processEvents()
            if time.monotonic() >= deadline:
                self.fail('Library scanner did not finish')
            time.sleep(.002)
        for _ in range(5):
            self.app.processEvents()

    def model_paths(self):
        from PySide6.QtCore import Qt
        return [self.dialog.model.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(self.dialog.model.rowCount())]

    def choose_root(self, root):
        index = next(i for i in range(1, self.dialog.roots.count())
                     if self.dialog.roots.itemData(i) == (root.resolve(),))
        self.dialog.roots.setCurrentIndex(index)

    def test_registered_libraries_scan_nested_wavs_search_and_multiple_selection(self):
        from PySide6.QtCore import QItemSelectionModel, Qt
        self.drain_scan()
        self.assertCountEqual(self.model_paths(), self.paths)
        self.assertIn('4 samples', self.dialog.status.text())
        self.dialog.search.setText('DRUMS')
        self.app.processEvents()
        self.assertEqual(self.dialog.proxy.rowCount(), 2)
        selection = self.dialog.listing.selectionModel()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in (1, 0):
            selection.select(self.dialog.proxy.index(row, 0), flags)
        selected = self.dialog.selected_paths()
        self.assertCountEqual(selected, self.paths[:2])
        self.assertEqual(selected, [self.dialog.proxy.index(row, 0).data(Qt.ItemDataRole.UserRole) for row in range(2)])
        self.dialog.search.setText('snare.wav')
        self.app.processEvents()
        self.assertEqual(self.dialog.proxy.rowCount(), 1)
        self.assertEqual(self.dialog.proxy.index(0, 0).data(Qt.ItemDataRole.UserRole), self.paths[1])

    def test_preview_and_autoplay_reach_studio_preview_hook_without_audio(self):
        from PySide6.QtWidgets import QPushButton
        self.drain_scan()
        with patch.object(self.studio, 'preview_source') as preview:
            index = self.dialog.proxy.index(0, 0)
            self.dialog.listing.setCurrentIndex(index)
            preview.assert_not_called()
            button = next(b for b in self.dialog.findChildren(QPushButton) if b.text() == 'Preview selected sample')
            button.click()
            preview.assert_called_once_with(self.dialog.current_path())
            preview.reset_mock()
            self.dialog.autoplay.setChecked(True)
            self.dialog.listing.setCurrentIndex(self.dialog.proxy.index(1, 0))
            preview.assert_called_once_with(self.dialog.current_path())

    def test_register_and_unregister_use_shared_registry_without_deleting_samples(self):
        from PySide6.QtWidgets import QMessageBox
        from volcastudio.libraries import library, registrations
        extra = self.first.parent/'Third Library'
        sample = tiny_wav(extra/'new.wav')
        before = sample.read_bytes()
        self.drain_scan()
        with patch('PySide6.QtWidgets.QFileDialog.getExistingDirectory', return_value=str(extra)), \
             patch('volcastudio.libraries.library', wraps=library) as shared:
            self.dialog.register_library()
        shared.assert_called_once()
        self.assertIs(shared.call_args.kwargs['quiet'], True)
        self.assertIn(str(extra.resolve()), registrations(self.config))
        self.drain_scan()
        self.assertIn(sample, self.model_paths())
        self.choose_root(extra)
        self.drain_scan()
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('volcastudio.libraries.library', wraps=library) as shared:
            self.dialog.unregister_library()
        shared.assert_called_once()
        self.assertIs(shared.call_args.kwargs['quiet'], True)
        self.assertNotIn(str(extra.resolve()), registrations(self.config))
        self.assertEqual(sample.read_bytes(), before)
        self.drain_scan()
        self.assertNotIn(sample, self.model_paths())

    def test_cancel_unregister_preserves_registration_and_files(self):
        from PySide6.QtWidgets import QMessageBox
        from volcastudio.libraries import registrations
        self.drain_scan()
        self.choose_root(self.first)
        self.drain_scan()
        before = registrations(self.config)
        with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
            self.dialog.unregister_library()
        self.assertEqual(registrations(self.config), before)
        self.assertTrue(all(p.exists() for p in self.paths))

    def test_reload_ignores_batches_queued_by_previous_scan(self):
        # Let the old real worker finish without processing its queued signals.
        self.assertTrue(self.dialog.scan.wait(5000))
        self.choose_root(self.second)
        self.drain_scan()
        self.assertEqual(self.model_paths(), [self.paths[-1]])

    def test_cancel_stops_scanner_and_cleans_worker(self):
        worker = self.dialog.scan
        self.dialog.reject()
        self.assertIsNone(self.dialog.scan)
        self.assertFalse(worker.isRunning())
        self.app.processEvents()

    def test_studio_adds_selected_library_samples_to_current_draft(self):
        from PySide6.QtCore import QItemSelectionModel
        from PySide6.QtWidgets import QDialog
        self.drain_scan()
        self.dialog.search.setText('Kick.wav')
        self.app.processEvents()
        index = self.dialog.proxy.index(0, 0)
        self.dialog.listing.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
        with patch('volcastudio.outie_library.LibraryDialog', return_value=self.dialog), \
             patch.object(self.dialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.studio.open_library()
        self.assertEqual(self.studio.samples, [self.paths[0]])
        self.assertEqual(self.studio.sample_list.count(), 1)


if __name__ == '__main__':
    unittest.main()
