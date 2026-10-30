"""Real Desktop App library/archive/preview UI checks with an offline PCM sink."""
import hashlib
import time
import wave
from pathlib import Path
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets as W


def verify_workflows(window, app, output):
    """Use the caller's isolated saved kit; never discover or open devices."""
    from .kits import fingerprint
    from .outie_model import open_ordered_kit
    from .outie_library import LibraryDialog
    from .outie_kit_archive import KitArchiveDialog

    kit = window.config.kits / 'offline-ui-kit'
    original = fingerprint(kit)
    errors, recordings = [], []
    original_error = window.error
    old_index = window.outputs.currentIndex()
    window.outputs.blockSignals(True)
    fake_index = window.outputs.count()
    window.outputs.addItem('Offline verification PCM sink', 'sd:999999')
    window.outputs.setCurrentIndex(fake_index)
    window.outputs.blockSignals(False)
    window.error = lambda text: errors.append(str(text))

    def drain():
        if window.job is not None:
            window.cancel_job()
            if not window.job.wait(15000):
                raise RuntimeError('Offline preview worker did not stop after cancellation')
            deadline = time.monotonic() + 3
            while window.job is not None and time.monotonic() < deadline:
                app.processEvents()
            if window.job is not None:
                raise RuntimeError('Offline preview worker completion was not delivered')

    def record(path, target, *, protocol=True):
        with wave.open(str(path), 'rb') as wav:
            metadata = (wav.getframerate(), wav.getnchannels(), wav.getsampwidth())
            pcm = wav.readframes(wav.getnframes())
        if protocol or metadata != (44100, 1, 2) or not pcm or not any(pcm):
            raise RuntimeError('Preview did not produce ordinary 44.1 kHz mono PCM16 audio')
        if target != 'sd:999999':
            raise RuntimeError('Preview did not use the isolated PCM sink')
        recordings.append({'format': list(metadata), 'pcm_sha256': hashlib.sha256(pcm).hexdigest(),
                           'bytes': len(pcm), 'protocol': False})

    def drive(dialog_type, step, invoke):
        deadline = time.monotonic() + 60
        timer = QtCore.QTimer()
        timer.setInterval(10)
        failure = []
        def tick():
            dialog = app.activeModalWidget()
            try:
                if errors:
                    raise RuntimeError('; '.join(errors))
                if time.monotonic() > deadline:
                    raise RuntimeError(f'{dialog_type.__name__} did not finish')
                if isinstance(dialog, dialog_type):
                    step(dialog)
            except Exception as exc:
                failure.append(str(exc))
                if dialog is not None:
                    dialog.reject()
                timer.stop()
        timer.timeout.connect(tick)
        timer.start()
        try:
            invoke()
        finally:
            timer.stop()
            drain()
        if failure or errors:
            raise RuntimeError('; '.join(failure + errors))

    def click(dialog, text):
        buttons = [b for b in dialog.findChildren(W.QPushButton) if b.text() == text]
        if len(buttons) != 1 or not buttons[0].isEnabled():
            raise RuntimeError(f'Expected one enabled button: {text}')
        buttons[0].click()

    phase, selected = [0], []
    def library_step(dialog):
        if phase[0] == 0:
            dialog.search.setText('offline-ui-kit')
            phase[0] = 1
        if phase[0] == 1 and dialog.proxy.rowCount() and not dialog.scan.isRunning():
            index = dialog.proxy.index(0, 0)
            dialog.listing.setCurrentIndex(index)
            dialog.listing.selectionModel().select(index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect | QtCore.QItemSelectionModel.SelectionFlag.Rows)
            selected[:] = dialog.selected_paths()
            click(dialog, 'Preview selected sample')
            phase[0] = 2
        elif phase[0] == 2 and window.job is None:
            if len(recordings) != 1:
                raise RuntimeError('Library preview button produced no PCM')
            click(dialog, 'Inspect pitch / waveform')
            phase[0] = 3
        elif phase[0] == 3 and window.job is None:
            pixmap = dialog.waveform.pixmap()
            if pixmap is None or pixmap.isNull() or 'pitch' not in dialog.status.text():
                raise RuntimeError('Pitch/waveform inspection did not reach the library display')
            click(dialog, 'Add selected samples')
            phase[0] = 4

    archive_phase = [0]
    def archive_step(dialog):
        if archive_phase[0] in (0, 2):
            row = next((n for n in range(dialog.saved.count())
                        if dialog.saved.item(n).data(QtCore.Qt.ItemDataRole.UserRole) == str(kit)), None)
            if row is None:
                raise RuntimeError('Saved test kit is missing from the manager')
            dialog.saved.setCurrentRow(row)
            click(dialog, 'Move to archive…' if archive_phase[0] == 0 else 'Open selected kit')
            archive_phase[0] += 1
        elif archive_phase[0] == 1:
            row = next((n for n in range(dialog.archived.count())
                        if dialog.archived.item(n).text().startswith(kit.name + ' ·')), None)
            if row is None or kit.exists():
                raise RuntimeError('Archive button did not retire the selected kit')
            dialog.archived.setCurrentRow(row)
            ident = dialog.archived.currentItem().data(QtCore.Qt.ItemDataRole.UserRole)
            if fingerprint(window.config.data / 'trash' / ident / 'kit') != original:
                raise RuntimeError('Archived kit bytes changed')
            click(dialog, 'Restore selected version…')
            archive_phase[0] = 2

    try:
        with patch('volcastudio.desktop_audio.play', side_effect=record), \
             patch.object(W.QMessageBox, 'question', return_value=W.QMessageBox.StandardButton.Yes), \
             patch.object(W.QMessageBox, 'warning', side_effect=lambda parent, title, text, *a, **k: errors.append(str(text))):
            before = tuple(window.samples)
            drive(LibraryDialog, library_step, window.open_library)
            if phase[0] != 4 or tuple(window.samples) != before + tuple(selected) or len(selected) != 1:
                raise RuntimeError('Library scan/search/select/Add did not update the kit')
            window.set_opened_kit(*open_ordered_kit(window.config, kit))
            drive(KitArchiveDialog, archive_step, window.manage_kits)
            if archive_phase[0] != 3 or window.saved_kit != kit or fingerprint(kit) != original:
                raise RuntimeError('Archive/restore/open did not preserve the saved kit')
            window.tabs.setCurrentIndex(0)
            app.processEvents()
            if not window.grab().save(str(Path(output) / 'library-archive-workflows.png')):
                raise RuntimeError('Could not save workflow rendering')
        return {'hardware_access': False, 'library_scan_search_add': True,
                'actual_pitch_and_waveform_buttons': True,
                'actual_preview_button': recordings, 'archive_restore_open': True,
                'saved_kit_bytes_preserved': True}
    finally:
        try:
            drain()
        finally:
            window.error = original_error
            window.outputs.blockSignals(True)
            window.outputs.removeItem(fake_index)
            window.outputs.setCurrentIndex(old_index)
            window.outputs.blockSignals(False)
