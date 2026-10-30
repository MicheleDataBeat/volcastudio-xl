"""Saved-kit and archive controls for the Desktop App; mutations use the shared backend."""
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets as W

from . import kits
from .transfer import device_lock


class KitArchiveDialog(W.QDialog):
    """Manage Studio kits without touching source libraries or playing audio.

    ``is_busy()`` reports an operation in the owning window. After a successful
    mutation, ``on_changed(action, path)`` receives ``archived`` with the old
    kit path, or ``restored`` with the restored path. ``on_open(path)`` may open
    the selected saved kit in the owning window.
    """

    def __init__(self, config, parent=None, *, is_busy=None, on_changed=None,
                 on_open=None):
        super().__init__(parent)
        self.config = config
        self.is_busy = is_busy or (lambda: False)
        self.on_changed = on_changed
        self.on_open = on_open
        self.setWindowTitle('Saved kits and archive')
        self.resize(760, 520)
        layout = W.QVBoxLayout(self)
        intro = W.QLabel('Open a saved Studio kit, move it to the archive, or restore an archived version. Source libraries are unchanged. Restoring never replaces an existing kit.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.saved = W.QListWidget()
        self.saved.setAccessibleName('Saved Studio kits')
        layout.addWidget(W.QLabel('Saved Studio kits'))
        layout.addWidget(self.saved)
        row = W.QHBoxLayout()
        self.open_button = W.QPushButton('Open selected kit')
        self.archive_button = W.QPushButton('Move to archive…')
        row.addWidget(self.open_button)
        row.addWidget(self.archive_button)
        layout.addLayout(row)
        layout.addWidget(W.QLabel('Archived kits and previous versions'))
        self.archived = W.QListWidget()
        self.archived.setAccessibleName('Archived kits and previous versions')
        layout.addWidget(self.archived)
        self.restore_button = W.QPushButton('Restore selected version…')
        layout.addWidget(self.restore_button)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
        self.refresh_button = buttons.addButton('Refresh', W.QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.open_button.clicked.connect(self.open_selected)
        self.archive_button.clicked.connect(self.archive_selected)
        self.restore_button.clicked.connect(self.restore_selected)
        self.refresh_button.clicked.connect(self.refresh)
        self.saved.itemSelectionChanged.connect(self.update_controls)
        self.archived.itemSelectionChanged.connect(self.update_controls)
        self.refresh()

    def update_controls(self):
        idle = not self.is_busy()
        self.open_button.setEnabled(idle and self.on_open is not None and self.saved.currentItem() is not None)
        self.archive_button.setEnabled(idle and self.saved.currentItem() is not None)
        self.restore_button.setEnabled(idle and self.archived.currentItem() is not None)

    def refresh(self):
        self.saved.clear()
        self.archived.clear()
        skipped = 0
        if self.config.kits.is_dir():
            for path in sorted(self.config.kits.iterdir(), key=lambda p: p.name.casefold()):
                if path.name.startswith('.') or path.is_symlink() or not path.is_dir():
                    continue
                item = W.QListWidgetItem(path.name)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
                self.saved.addItem(item)
        for record_path in sorted((self.config.data / 'trash').glob('*/record.json'), reverse=True):
            entry = record_path.parent
            if entry.is_symlink() or record_path.is_symlink() or (entry / 'kit').is_symlink() or not (entry / 'kit').is_dir():
                skipped += 1
                continue
            try:
                record = json.loads(record_path.read_text())
                name = record['name']
                if not isinstance(name, str) or not name or Path(name).name != name or name.startswith('.'):
                    raise ValueError('Invalid kit name')
                reason = record.get('reason', 'archived')
                item = W.QListWidgetItem(f'{name} · {reason} · {entry.name}')
                item.setData(QtCore.Qt.ItemDataRole.UserRole, entry.name)
                item.setToolTip(str(record.get('origin', self.config.kits)))
                self.archived.addItem(item)
            except (OSError, ValueError, TypeError, KeyError):
                skipped += 1
        self.status.setText(f'{self.saved.count()} saved kit(s); {self.archived.count()} archived version(s).'
                            + (f' {skipped} unreadable archive entry/entries omitted.' if skipped else ''))
        self.update_controls()

    def _idle(self):
        if self.is_busy():
            raise ValueError('Another operation is in progress. Finish or cancel it before managing kits.')

    def _error(self, exc):
        W.QMessageBox.warning(self, 'Kit archive', str(exc))

    def open_selected(self):
        item = self.saved.currentItem()
        if item is None or self.on_open is None:
            return
        try:
            self._idle()
            path = kits.owned_kit(self.config, item.data(QtCore.Qt.ItemDataRole.UserRole))
            self.on_open(path)
            self.accept()
        except Exception as exc:
            self._error(exc)

    def _mutate(self, action):
        item = (self.saved if action == 'archived' else self.archived).currentItem()
        if item is None:
            return
        try:
            self._idle()
            value = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if action == 'archived':
                path = Path(value)
                question = f'Move “{path.name}” to the archive? It will leave the saved kit list. You can restore it later. Source samples are unchanged.'
            else:
                question = 'Restore this archived version to its original directory? If a kit with the same name exists, it will be kept and restoration will stop.'
            answer = W.QMessageBox.question(self, 'Kit archive', question,
                W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
                W.QMessageBox.StandardButton.Cancel)
            if answer != W.QMessageBox.StandardButton.Yes:
                return
            with device_lock(self.config.state):
                self._idle()
                if action == 'archived':
                    kits.delete_kit(self.config, path)
                else:
                    path = kits.restore_kit(self.config, value)
            self.refresh()
            if self.on_changed is not None:
                self.on_changed(action, path)
        except Exception as exc:
            self._error(exc)
            self.refresh()

    def archive_selected(self):
        self._mutate('archived')

    def restore_selected(self):
        self._mutate('restored')
