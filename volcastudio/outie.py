"""VolcaStudio XL Desktop App: a native, keyboard-accessible desktop interface.

No shell, terminal emulator or CLI dependency. Device operations are opt-in.
"""
import json
import sys
import threading
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets as W

from .config import Config
from .outie_model import library_roots, open_ordered_kit, parse_slots, save_ordered_kit
from .outie_widgets import FlowLayout, SampleList, flow_row
from .patterns import FIRMWARE_LABELS, load_bank, save_bank, blank_pattern
from .grooves import load_catalog, plan_grooves, save_groove_plan

STYLE = '''
QMainWindow { background: #ddd9c6; }
QWidget { font-family: "DejaVu Sans Mono", "Menlo", "Consolas", monospace;
 font-size: 13px; color: #b5ece1; background: #102d38; }
QLabel#masthead { color: #102d38; background: #ddd9c6; font-size: 16px; font-weight: bold; padding: 8px 12px; }
QLabel#subtitle { color: #ddd9c6; padding: 4px 8px; }
QPushButton { border: 1px solid #619a96; padding: 4px 8px; background: #194550; }
QPushButton:hover, QPushButton:focus { border: 2px solid #eee6be; background: #245d65; }
QPushButton:disabled { color: #718b8e; border-color: #425b60; }
QListWidget, QTreeWidget, QPlainTextEdit, QLineEdit, QComboBox { background: #09222c; border: 1px solid #47757a; padding: 3px; selection-background-color: #b5ece1; selection-color: #09222c; }
QCheckBox { padding: 2px; }
QTabWidget::pane { border: 1px solid #47757a; }
QTabBar::tab { padding: 6px 12px; background: #194550; }
QTabBar::tab:selected { color: #102d38; background: #b5ece1; }
QProgressBar { border: 1px solid #619a96; text-align: center; }
QProgressBar::chunk { background: #91d5c5; }
QToolTip { color: #102d38; background: #eee6be; }
'''


class Seal(W.QWidget):
    """Static integer-pixel ornament. No external assets or animation required."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(64, 64)
        self.setAccessibleName('VolcaStudio XL emblem')

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor('#ddd9c6'))
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor('#194550'))
        rows = ('00011111000', '00100000100', '01000100010', '10001110001',
                '10011111001', '10111111101', '10000100001', '10000100001',
                '01000100010', '00100000100', '00011111000')
        for y, row in enumerate(rows):
            for x, bit in enumerate(row):
                if bit == '1':
                    p.drawRect(5 + x * 5, 5 + y * 5, 5, 5)


class Job(QtCore.QThread):
    result = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    notice = QtCore.Signal(str)
    progress = QtCore.Signal(str, int, int)
    confirmation = QtCore.Signal(object)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.cancel_event = threading.Event()
        self.answer_event = threading.Event()
        self.approved = False

    def confirm(self, manifest):
        self.answer_event.clear()
        self.confirmation.emit(manifest)
        while not self.answer_event.wait(.1):
            if self.cancel_event.is_set():
                return False
        return self.approved and not self.cancel_event.is_set()

    def run(self):
        try:
            self.result.emit(self.operation(self))
        except (Exception, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt) and self.cancel_event.is_set() and getattr(self, 'kind', None) in ('preview', 'library-analysis'):
                self.notice.emit('Preview stopped.' if self.kind == 'preview' else 'Sample analysis cancelled.')
            else:
                self.failed.emit(str(exc) or type(exc).__name__)


def semitone_prompt(parent, direction, count=1):
    """Two decimal digits only; the button determines the sign."""
    dialog = W.QDialog(parent)
    dialog.setWindowTitle('Varispeed / lower pitch' if direction < 0 else 'Varispeed / raise pitch')
    layout = W.QVBoxLayout(dialog)
    layout.addWidget(W.QLabel(f'How many semitones for {count} selected sample(s)?\n0–99; pitch and duration change together. Originals remain intact.'))
    entry = W.QLineEdit()
    entry.setMaxLength(2)
    entry.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression('[0-9]{0,2}'), entry))
    entry.setAccessibleName('Semitones, zero to ninety-nine')
    entry.setPlaceholderText('7 or 07')
    layout.addWidget(entry)
    buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
    buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(False)
    entry.textChanged.connect(lambda text: buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text)))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    entry.setFocus()
    return direction * int(entry.text()) if dialog.exec() == W.QDialog.DialogCode.Accepted else None


class AlignmentDialog(W.QDialog):
    """Offline key alignment on explicit request: nothing is analyzed on opening.

    Choose the master, tick the samples to align and press **Align selected**.
    Only those samples are analyzed and rendered; **Accept aligned kit** then
    replaces the draft. Cancel keeps the kit unchanged.
    """
    HINT = 'Choose the master, tick the samples to align, then press Align selected. No audio is sent.'

    def __init__(self, paths, config, parent=None, preselected=()):
        super().__init__(parent)
        self.paths = tuple(paths)
        self.config = config
        self.cache = config.cache / 'pitch'
        self.job = None
        self.plan = None
        self.aligned_paths = None
        self.pending_reject = False
        self.setWindowTitle('Pitch alignment')
        self.resize(1000, 620)
        layout = W.QVBoxLayout(self)
        intro = W.QLabel('Choose the master sample and tick the samples to align, then press Align selected. Only those samples are analyzed and transposed to the master\'s pitch class by the nearest semitone shift; time is not stretched. Filename and measured notes include existing varispeed. Unclear samples stay unchanged unless shifted manually.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        selectors = W.QHBoxLayout()
        selectors.addWidget(W.QLabel('Master key'))
        self.master = W.QComboBox()
        self.master.setAccessibleName('Master key sample')
        self.master.addItem('Choose the master sample…', None)
        for slot, path in enumerate(self.paths):
            self.master.addItem(f'{slot:02d}  {path.name}', slot)
        selectors.addWidget(self.master, 1)
        self.select_all = W.QPushButton('All slaves')
        self.select_none = W.QPushButton('No slaves')
        selectors.addWidget(self.select_all)
        selectors.addWidget(self.select_none)
        layout.addLayout(selectors)
        self.table = W.QTableWidget(len(self.paths), 8)
        self.table.setHorizontalHeaderLabels(['Align / sample', 'Current', 'Filename', 'Measured', 'Pitch source', 'Additional shift', 'Result', 'Seconds'])
        self.table.setAccessibleName('Samples to align, analysis and result')
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        # Keep every sample name readable: size the name column to the longest
        # name and let the other columns scroll instead of squeezing it to "…".
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, W.QHeaderView.ResizeMode.Interactive)
        metrics = self.table.fontMetrics()
        longest = max((f'{slot:02d}  {path.name}' for slot, path in enumerate(self.paths)), key=len, default='')
        self.table.setColumnWidth(0, min(max(metrics.horizontalAdvance(longest) + 56, 260), 640))
        self.table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 120)
        self.choices = []
        self.shifts = []
        preselected = set(preselected)
        for slot, path in enumerate(self.paths):
            item = W.QTableWidgetItem(f'{slot:02d}  {path.name}')
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.CheckState.Checked if slot in preselected else QtCore.Qt.CheckState.Unchecked)
            item.setToolTip(str(path))
            self.table.setItem(slot, 0, item)
            for column in (1, 2, 3, 6, 7):
                self.table.setItem(slot, column, W.QTableWidgetItem('—'))
            choice = W.QComboBox()
            choice.addItem('Not analyzed', None)
            choice.setAccessibleName(f'Pitch source for sample {slot:02d}')
            self.table.setCellWidget(slot, 4, choice)
            self.choices.append(choice)
            shift = W.QSpinBox()
            shift.setRange(-99, 99)
            shift.setToolTip('Additional semitones. Automatic shifts appear after Align selected; changing this number creates a manual override.')
            shift.setAccessibleName(f'Additional semitones for sample {slot:02d}')
            # An explicit zero override is available through the group controls.
            shift.setProperty('manual', False)
            self.table.setCellWidget(slot, 5, shift)
            self.shifts.append(shift)
            choice.currentIndexChanged.connect(self.invalidate)
            shift.valueChanged.connect(lambda value, widget=shift: self.manual_shift(widget))
        layout.addWidget(self.table, 1)
        batch = W.QHBoxLayout()
        batch.addWidget(W.QLabel('Selected rows'))
        self.batch_shift = W.QSpinBox()
        self.batch_shift.setRange(-99, 99)
        self.batch_shift.setAccessibleName('Additional semitones for selected rows')
        batch.addWidget(self.batch_shift)
        self.batch_apply = W.QPushButton('Set shift for selected')
        self.batch_reset = W.QPushButton('Use automatic for selected')
        batch.addWidget(self.batch_apply)
        batch.addWidget(self.batch_reset)
        layout.addLayout(batch)
        self.summary = W.QLabel(self.HINT)
        self.summary.setWordWrap(True)
        self.summary.setAccessibleName('Alignment status, kit duration and exclusions')
        layout.addWidget(self.summary)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        self.align_button = self.buttons.addButton('Align selected', W.QDialogButtonBox.ButtonRole.ActionRole)
        self.align_button.setAccessibleName('Analyze and align the ticked samples to the master')
        self.accept_button = self.buttons.button(W.QDialogButtonBox.StandardButton.Ok)
        self.accept_button.setText('Accept aligned kit')
        self.accept_button.setEnabled(False)
        self.align_button.clicked.connect(self.align)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.master.currentIndexChanged.connect(self.master_changed)
        self.table.itemChanged.connect(lambda item: self.invalidate() if item.column() == 0 else None)
        self.select_all.clicked.connect(lambda: self.set_slaves(True))
        self.select_none.clicked.connect(lambda: self.set_slaves(False))
        self.batch_apply.clicked.connect(lambda: self.set_batch_shift(False))
        self.batch_reset.clicked.connect(lambda: self.set_batch_shift(True))

    def set_controls_enabled(self, enabled):
        for widget in (self.master, self.table, self.select_all, self.select_none, self.batch_shift,
                       self.batch_apply, self.batch_reset, self.align_button):
            widget.setEnabled(enabled)
        self.accept_button.setEnabled(enabled and self.aligned_paths is not None)

    def start_worker(self, operation, done):
        if self.job:
            return
        self.set_controls_enabled(False)
        job = Job(operation)
        self.job = job
        job.result.connect(done)
        job.failed.connect(self.worker_error)
        job.finished.connect(self.worker_finished)
        job.start()

    def worker_error(self, text):
        self.plan = None
        self.aligned_paths = None
        self.summary.setText(f'Alignment not completed: {text} Your kit is unchanged.')

    def worker_finished(self):
        job, self.job = self.job, None
        if job:
            job.deleteLater()
        self.set_controls_enabled(True)
        if self.pending_reject:
            super().reject()

    def selection(self):
        master = self.master.currentData()
        slaves = [slot for slot in range(len(self.paths))
                  if slot != master and self.table.item(slot, 0).checkState() == QtCore.Qt.CheckState.Checked]
        return master, slaves

    def invalidate(self, *args):
        if self.plan is None and self.aligned_paths is None:
            return
        self.plan = None
        self.aligned_paths = None
        self.accept_button.setEnabled(False)
        self.summary.setText('Selection or shifts changed — press Align selected to analyze and align again.')

    def manual_shift(self, widget):
        widget.setProperty('manual', True)
        self.invalidate()

    def master_changed(self):
        master = self.master.currentData()
        if master is not None:
            self.table.blockSignals(True)
            self.table.item(master, 0).setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.table.blockSignals(False)
        self.invalidate()

    def set_slaves(self, enabled):
        master = self.master.currentData()
        self.table.blockSignals(True)
        for slot in range(len(self.paths)):
            state = enabled and slot != master
            self.table.item(slot, 0).setCheckState(QtCore.Qt.CheckState.Checked if state else QtCore.Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.invalidate()

    def set_batch_shift(self, automatic):
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        for slot in selected:
            widget = self.shifts[slot]
            widget.blockSignals(True)
            widget.setValue(0 if automatic else self.batch_shift.value())
            widget.setProperty('manual', not automatic)
            widget.blockSignals(False)
        self.invalidate()

    def align(self):
        """Analyze the master and the ticked samples, then render the aligned variants."""
        if self.job:
            return
        master, slaves = self.selection()
        if master is None:
            self.summary.setText('Choose the master sample first. Nothing was analyzed.')
            return
        if not slaves:
            self.summary.setText('Tick at least one sample to align. Nothing was analyzed.')
            return
        choices = {slot: combo.currentData() for slot, combo in enumerate(self.choices) if combo.currentData()}
        overrides = {slot: widget.value() for slot, widget in enumerate(self.shifts) if slot in slaves and widget.property('manual')}
        self.plan = None
        self.aligned_paths = None
        self.accept_button.setEnabled(False)
        self.summary.setText(f'Analyzing {len(slaves) + 1} samples and rendering aligned variants… No audio is sent.')
        paths, cache, variants = self.paths, self.cache, self.config.data / 'variants/varispeed'
        def work(job):
            from .tuning import alignment_plan, apply_alignment
            from .desktop_audio import audio_operation
            with audio_operation(cancel_event=job.cancel_event):
                plan = alignment_plan(paths, master, slaves, choices, overrides, cache, analyze_unselected=False)
                outputs = apply_alignment(plan, variants) if plan['ready'] and not plan['over_budget'] else None
            return plan, outputs
        self.start_worker(work, self.show_result)

    def show_result(self, result):
        if self.pending_reject:
            return
        plan, outputs = result
        self.plan = plan
        self.table.blockSignals(True)
        try:
            for row in plan['rows']:
                slot = row['slot']
                analyzed = row.get('analyzed', True)
                choice = self.choices[slot]
                choice.blockSignals(True)
                choice.clear()
                if analyzed:
                    if row.get('conflict'):
                        choice.addItem('Choose a source…', None)
                    if row.get('filename_pc') is not None:
                        choice.addItem('Filename', 'filename')
                    if row.get('detected_pc') is not None and not row.get('uncertain'):
                        choice.addItem('Measured', 'detected')
                    if choice.count() == 0:
                        choice.addItem('No clear pitch', None)
                    chosen = (plan.get('choices') or {}).get(slot)
                    if chosen is not None and choice.findData(chosen) >= 0:
                        choice.setCurrentIndex(choice.findData(chosen))
                else:
                    choice.addItem('Not analyzed', None)
                choice.blockSignals(False)
                unclear = 'Unclear' if analyzed else '—'
                current = row.get('note') or row.get('detected_note') or row.get('filename_note') or unclear
                cells = {1: f"{current} [{row.get('semitones', row['final_semitones'] - row.get('shift', 0)):+d}]",
                         2: row.get('filename_note') or '—',
                         3: row.get('detected_note') or unclear,
                         6: f"{row.get('final_note') or '—'} [{row['final_semitones']:+d}]",
                         7: f"{row['final_seconds']:.2f}"}
                for column, text in cells.items():
                    self.table.item(slot, column).setText(str(text))
                self.table.item(slot, 0).setToolTip('\n'.join(filter(None, [str(self.paths[slot]), str(row.get('reason', ''))])))
                widget = self.shifts[slot]
                if not widget.property('manual'):
                    widget.blockSignals(True)
                    widget.setValue(row.get('shift', 0))
                    widget.blockSignals(False)
        finally:
            self.table.blockSignals(False)
        conflicts = ', '.join(f'{slot:02d}' for slot in plan.get('conflicts', []))
        excluded = ', '.join(f'{slot:02d}' for slot in plan.get('excluded', []))
        text = f"Kit: {plan['before_seconds']:.2f} → {plan['seconds']:.2f} / 65.00 seconds."
        if excluded:
            text += f' Unclear/excluded slots: {excluded}; unchanged unless shifted manually.'
        if outputs is not None:
            self.aligned_paths = list(outputs)
            aligned = sum(1 for row in plan['rows'] if row.get('selected') and not row.get('excluded'))
            text += f' Aligned {aligned} sample(s). Accept aligned kit replaces the draft; Cancel keeps it.'
        elif conflicts:
            text += f' Choose filename or measured pitch for conflicting slots: {conflicts}, then press Align selected again.'
        elif plan.get('over_budget'):
            text += ' OVER BUDGET — change shifts or selection, then press Align selected again.'
        elif not plan.get('ready'):
            text += ' Choose a master with a clear pitch, then press Align selected again.'
        self.summary.setText(text)

    def accept(self):
        if self.job or self.aligned_paths is None:
            return
        super().accept()

    def reject(self):
        if self.job:
            self.pending_reject = True
            self.job.cancel_event.set()
            self.summary.setText('Cancelling offline work… Your kit is unchanged.')
        else:
            super().reject()

    def closeEvent(self, event):
        if self.job:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

class Studio(W.QMainWindow):
    def __init__(self, config=None, discover_devices=True):
        super().__init__()
        self.config = config or Config.read()
        self.config.initialize()
        self.job = None
        self.samples = []
        self.bank = None
        self.bank_path = None
        self.saved_kit = None
        self.opened_kit = None
        self.kit_fingerprint = None
        self.restoring_draft = False
        self.unrecovered_draft = False
        self.draft_write_failed = False
        from .outie_state import load_preferences
        try:
            self.device_preferences = load_preferences(self.config)
        except (OSError, ValueError):
            self.device_preferences = {}
        self.setWindowTitle('VolcaStudio XL Desktop App')
        screen = QtGui.QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QtCore.QRect(0, 0, 1120, 820)
        # Fit the screen (a 1920 × 1080 display at 150 % scale offers 1280 × 720) and
        # accept half-screen tiling; every section scrolls when needed.
        self.resize(min(1120, max(640, available.width() - 48)), min(760, max(480, available.height() - 64)))
        self.setMinimumSize(640, 480)
        outer = W.QWidget()
        self.setCentralWidget(outer)
        layout = W.QVBoxLayout(outer)
        header = W.QHBoxLayout()
        self.header_seal = Seal()
        header.addWidget(self.header_seal)
        label = W.QLabel('VOLCASTUDIO XL  /  DESKTOP APP\nKits, patterns, grooves, firmware')
        self.header_label = label
        label.setObjectName('masthead')
        header.addWidget(label, 1)
        layout.addLayout(header)
        self.tabs = W.QTabWidget()
        self.tabs.setAccessibleName('Sections')
        layout.addWidget(self.tabs, 1)
        self.samples_page()
        self.patterns_page()
        self.grooves_page()
        self.firmware_target.currentIndexChanged.connect(self.reload_grooves)
        self.firmware_page()
        footer = W.QHBoxLayout()
        output_label = W.QLabel('Audio output')
        output_label.setToolTip('The output connected to the Volca SYNC IN. The system audio route (pipewire or default) shares the device with other applications; hw: outputs are exclusive. Outputs that cannot run at 44.1 kHz are not listed.')
        footer.addWidget(output_label)
        self.outputs = W.QComboBox()
        self.outputs.setAccessibleName('Explicit transfer audio output')
        self.outputs.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.outputs.setMinimumContentsLength(16)  # long device names must not widen the window
        footer.addWidget(self.outputs, 1)
        footer.addWidget(self.button('Refresh outputs', self.refresh_outputs))
        self.cancel = self.button('Cancel operation', self.cancel_job)
        self.cancel.setEnabled(False)
        footer.addWidget(self.cancel)
        layout.addLayout(footer)
        self.progress = W.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(96)
        self.log.setAccessibleName('Operation report')
        layout.addWidget(self.log)
        self.message('Desktop App is ready. Open a saved kit or add WAV files.')
        if discover_devices:
            self.refresh_outputs()
        else:
            self.outputs.addItem('Offline smoke test — no devices opened', None)
        self.refresh_firmware()
        self.restore_kit_draft()
        for key, combo in (('output', self.outputs), ('backup_input', self.backup_input), ('backup_midi', self.backup_midi)):
            combo.activated.connect(lambda _, key=key, combo=combo: self.remember_device(key, combo))
        self.kit_name.textChanged.connect(self.persist_kit_draft)
        QtGui.QShortcut(QtGui.QKeySequence('Ctrl+S'), self, activated=lambda: self.guarded(self.save_current_kit))
        QtGui.QShortcut(QtGui.QKeySequence('Ctrl+O'), self, activated=self.open_bank)
        QtGui.QShortcut(QtGui.QKeySequence('Ctrl+Shift+O'), self, activated=lambda: self.guarded(self.open_saved_kit))
        QtGui.QShortcut(QtGui.QKeySequence('Escape'), self, activated=self.cancel_job)

    def resizeEvent(self, event):
        if hasattr(self, 'log'):
            compact = self.height() < 760
            if getattr(self, 'compact_layout', None) != compact:
                self.compact_layout = compact
                self.header_seal.setVisible(not compact)
                self.header_label.setText('VOLCASTUDIO XL  /  DESKTOP APP' if compact else 'VOLCASTUDIO XL  /  DESKTOP APP\nKits, patterns, grooves, firmware')
                self.header_label.setStyleSheet('padding: 6px; font-size: 16px;' if compact else '')
                self.log.setMaximumHeight(48 if compact else 96)
        if hasattr(self, 'samples_split'):
            # Narrow windows stack the panels with the kit first, so saving and
            # sending stay reachable without scrolling past the library.
            stacked = self.width() < 1000
            wanted = QtCore.Qt.Orientation.Vertical if stacked else QtCore.Qt.Orientation.Horizontal
            if self.samples_split.orientation() != wanted:
                self.samples_split.setOrientation(wanted)
                self.samples_split.insertWidget(0, self.kit_panel if stacked else self.library)
        super().resizeEvent(event)

    def button(self, text, callback):
        button = W.QPushButton(text)
        button.clicked.connect(lambda checked=False: self.guarded(callback))
        return button

    def guarded(self, callback):
        try:
            callback()
        except Exception as exc:
            self.error(str(exc))

    def page(self, title, description):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setSizeConstraint(W.QLayout.SizeConstraint.SetMinimumSize)
        label = W.QLabel(description)
        label.setWordWrap(True)
        label.setObjectName('subtitle')
        layout.addWidget(label)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(W.QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return layout

    def message(self, text):
        self.log.appendPlainText(str(text))

    def error(self, text):
        self.message(text)
        W.QMessageBox.warning(self, 'Operation not completed', text)

    def refresh_outputs(self):
        previous = self.device_name(self.outputs) if self.outputs.currentData() is not None else self.device_preferences.get('output')
        self.outputs.clear()
        self.outputs.addItem('Select an output before sending', None)
        try:
            from .desktop_audio import output_devices
            for device in output_devices():
                self.outputs.addItem(device.get('label', device['name']), device['id'])
                self.outputs.setItemData(self.outputs.count() - 1, device['name'], QtCore.Qt.ItemDataRole.UserRole + 1)
            self.restore_device_choice(self.outputs, previous)
        except Exception as exc:
            self.message(f'Audio output unavailable: {exc}. Offline work remains available.')

    def device_name(self, combo):
        """The device's own name; the list may show a friendlier label."""
        name = combo.itemData(combo.currentIndex(), QtCore.Qt.ItemDataRole.UserRole + 1)
        return name if isinstance(name, str) and name else combo.currentText()

    def remember_device(self, key, combo):
        from .outie_state import save_preferences
        if combo.currentData() is not None:
            self.device_preferences[key] = self.device_name(combo)
            try:
                save_preferences(self.config, self.device_preferences)
            except OSError as exc:
                self.message(f'Could not remember device selection: {exc}')

    def restore_device_choice(self, combo, name):
        if not name:
            return
        matches = [i for i in range(combo.count()) if combo.itemData(i) is not None
                   and name in (combo.itemText(i), combo.itemData(i, QtCore.Qt.ItemDataRole.UserRole + 1))]
        if len(matches) == 1:
            combo.setCurrentIndex(matches[0])
        else:
            combo.addItem(f'Unavailable or ambiguous: {name} — select a device', None)
            combo.setCurrentIndex(combo.count()-1)

    def target(self):
        target = self.outputs.currentData()
        if not target:
            raise ValueError('Select the audio output connected to the Volca before sending.')
        return target

    def start_job(self, operation, done=None):
        if self.job is not None:
            raise ValueError('Wait for the current operation or cancel it first.')
        job = Job(operation)
        self.job = job
        self.tabs.setEnabled(False)
        self.outputs.setEnabled(False)
        self.cancel.setEnabled(True)
        self.progress.setRange(0, 0)
        job.notice.connect(self.message)
        job.progress.connect(self.report_progress)
        job.confirmation.connect(self.confirm_job)
        job.failed.connect(self.error)
        job.result.connect(done or (lambda result: self.message(result or 'Operation completed.')))
        job.finished.connect(self.finish_job)
        job.start()

    def report_progress(self, message, current, total):
        self.progress.setRange(0, max(0, total))
        self.progress.setValue(current)
        self.progress.setFormat(message + ' · %p%')

    def finish_job(self):
        job = self.job
        self.job = None
        self.tabs.setEnabled(True)
        self.outputs.setEnabled(True)
        self.cancel.setEnabled(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if job:
            job.deleteLater()

    def cancel_job(self):
        if self.job:
            self.job.cancel_event.set()
            self.job.answer_event.set()
            self.message('Stopping sample preview.' if getattr(self.job, 'kind', None) == 'preview' else 'Cancellation requested. A partial hardware transfer cannot be undone.')

    def confirm_job(self, manifest):
        if self.job is None:
            return
        box = W.QMessageBox(self)
        box.setWindowTitle('Authorize device transfer')
        box.setIcon(W.QMessageBox.Icon.Warning)
        box.setText('Send the prepared signal to your Volca Sample v1?')
        replacement = ('The operating firmware will be replaced.' if manifest.get('operation') == 'firmware' else
                       'Pattern memories ' + ', '.join(str(slot + 1) for slot in manifest['slots']) + ' will be replaced.' if 'slots' in manifest else
                       'All 100 sample slots will be cleared before this kit is loaded.')
        box.setInformativeText('Connect the selected output to SYNC IN, not headphones. ' + replacement +
                               ' Audio transfer has no acknowledgement; check the instrument afterwards.\n\n' +
                               '\n'.join(manifest.get('procedure', [])) + str(manifest.get('confirmation_text', '')))
        box.setDetailedText(json.dumps(manifest, indent=2, default=str))
        box.setStandardButtons(W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(W.QMessageBox.StandardButton.Cancel)
        self.job.approved = box.exec() == W.QMessageBox.StandardButton.Yes
        self.job.answer_event.set()

    def device_job(self, operation):
        target = self.target()
        def run(job):
            from .desktop_audio import audio_operation
            with audio_operation(cancel_event=job.cancel_event, progress_callback=lambda message, current, total: job.progress.emit(str(message), int(current), int(total))):
                result = operation(job, target)
            if job.cancel_event.is_set():
                return 'Transfer interrupted. Any already-sent data cannot be undone.'
            if (isinstance(result, dict) and result.get('phase') == 'cancelled') or not job.approved:
                return 'Transfer cancelled before sending.'
            return result if isinstance(result, str) else 'Signals sent. Verify the result on the Volca; audio provides no receipt.'
        self.start_job(run)

    def samples_page(self):
        from .outie_library import LibraryPanel, DetailPanel
        layout = self.page('01 / Samples', 'Libraries on the left, kit on the right; the listening notes follow the selected sample. Budget: 100 samples / 65 seconds.')
        self.samples_split = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.samples_split.setChildrenCollapsible(False)
        self.library = LibraryPanel(self)
        self.library.setAccessibleName('Sample libraries')
        self.samples_split.addWidget(self.library)
        kit = self.kit_panel = W.QWidget()
        kit.setAccessibleName('Kit')
        kit_layout = W.QVBoxLayout(kit)
        kit_layout.setContentsMargins(0, 0, 0, 0)
        flow_row(kit_layout, self.button('New kit', self.new_kit), self.button('Open saved kit…', self.open_saved_kit),
                 self.button('Manage kits…', self.manage_kits), self.button('Recover draft…', self.recover_kit_draft),
                 self.button('Add WAV files…', self.add_samples))
        row = W.QHBoxLayout()
        self.kit_name = W.QLineEdit()
        row.addWidget(W.QLabel('Kit name'))
        self.kit_name.setPlaceholderText('new-kit-name')
        self.kit_name.setAccessibleName('New kit name')
        row.addWidget(self.kit_name, 1)
        kit_layout.addLayout(row)
        self.save_kit_button = self.button('Save independent kit', self.save_kit)
        self.save_changes_button = self.button('Save changes', self.save_kit_changes)
        self.save_changes_button.setEnabled(False)
        self.prepare_kit_button = self.button('Check signals offline', self.prepare_kit)
        self.prepare_kit_button.setEnabled(False)
        self.send_kit_button = self.button('Send saved kit…', self.send_kit)
        self.send_kit_button.setEnabled(False)
        flow_row(kit_layout, self.save_kit_button, self.save_changes_button, self.prepare_kit_button, self.send_kit_button)
        self.kit_status = W.QLabel('New kit — save it before sending.')
        self.kit_status.setWordWrap(True)
        kit_layout.addWidget(self.kit_status)
        self.sample_list = SampleList()
        self.sample_list.setAccessibleName('Ordered sample slots')
        self.sample_list.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)  # keep slot, name end and badge visible
        self.sample_list.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.sample_list.setMinimumHeight(96)  # the page fits a 720 px screen; the list grows with the window
        for key, direction in [('J', -1), ('K', 1)]:
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), self.sample_list)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda direction=direction: self.guarded(lambda: self.shift_samples(direction)))
        kit_layout.addWidget(self.sample_list, 1)
        self.sample_budget = W.QLabel('00 / 100 slots · 0.00 / 65.00 seconds')
        self.sample_budget.setWordWrap(True)
        kit_layout.addWidget(self.sample_budget)
        self.preview_pitch = W.QComboBox()
        self.preview_pitch.setAccessibleName('Preview pitch')
        for label, pitch in [('Original pitch', 0), ('SPEED −12', -12), ('SPEED −24', -24)]:
            self.preview_pitch.addItem(label, pitch)
        flow_row(kit_layout, self.button('Move up', lambda: self.move_sample(-1)), self.button('Move down', lambda: self.move_sample(1)),
                 self.button('Remove', self.remove_sample), self.button('Preview sample', self.preview_sample), self.preview_pitch)
        flow_row(kit_layout, self.button('Lower pitch… (J)', lambda: self.shift_samples(-1)), self.button('Raise pitch… (K)', lambda: self.shift_samples(1)),
                 self.button('Make ×2 variant', self.make_variant), self.button('Align kit keys…', self.align_keys))
        self.samples_split.addWidget(kit)
        self.samples_split.setStretchFactor(0, 4)
        self.samples_split.setStretchFactor(1, 5)
        layout.addWidget(self.samples_split, 1)
        self.detail = DetailPanel(self)
        layout.addWidget(self.detail)
        self.library.current_changed.connect(self.detail.show_path)
        self.library.add_requested.connect(self.add_library_selection)
        self.sample_list.currentRowChanged.connect(
            lambda row: self.detail.show_path(self.samples[row] if 0 <= row < len(self.samples) else None))

    def add_library_selection(self, paths):
        paths = [Path(p) for p in paths]
        self.samples.extend(paths)
        self.render_samples()
        self.sample_list.setCurrentRow(len(self.samples) - 1)
        self.message(f'Added {len(paths)} sample(s) to the kit.')

    def discard_kit_changes(self):
        if self.job is not None:
            raise ValueError('Wait for the current operation or cancel it first.')
        if self.samples and self.saved_kit is None:
            return W.QMessageBox.question(
                self, 'Discard unsaved kit changes?',
                'The current sample selection has unsaved changes. Discard them?',
                W.QMessageBox.StandardButton.Discard | W.QMessageBox.StandardButton.Cancel,
                W.QMessageBox.StandardButton.Cancel) == W.QMessageBox.StandardButton.Discard
        return True

    def persist_kit_draft(self, *_):
        if self.restoring_draft:
            return
        from .outie_state import save_draft
        try:
            self.preserve_unrecovered_draft()
            save_draft(self.config, sources=self.samples, name=self.kit_name.text(),
                       opened=self.opened_kit, expected=self.kit_fingerprint, saved=self.saved_kit)
            self.draft_write_failed = False
        except (OSError, ValueError) as exc:
            self.draft_write_failed = True
            self.error(f'Could not preserve the Desktop App draft: {exc}. Save your kit before closing.')

    def preserve_unrecovered_draft(self):
        if not self.unrecovered_draft:
            return
        import shutil, uuid
        from .outie_state import draft_path
        original = draft_path(self.config)
        if original.exists():
            backup = original.parent / 'recovery' / f'draft-{uuid.uuid4().hex}.json'
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(original, backup)
            self.message(f'Kept the unrecovered draft at {backup}')
        self.unrecovered_draft = False

    def restore_kit_draft(self, path=None):
        from .outie_state import load_draft
        from .kits import fingerprint, owned_kit
        self.restoring_draft = True
        try:
            draft = load_draft(self.config, path)
            if draft is None:
                return
            sources = [Path(p) for p in draft['sources']]
            # Validate before changing the window; an invalid draft stays on disk.
            from .transfer import inspect_wav
            for source in sources:
                inspect_wav(source)
            opened = owned_kit(self.config, draft['opened'], allow_external=True) if draft.get('opened') else None
            if opened and fingerprint(opened) != draft.get('expected'):
                raise ValueError('The opened kit changed in another edition. The old draft has been kept; reopen the kit explicitly instead of using changed sample files.')
            self.samples = sources
            self.opened_kit, self.kit_fingerprint = opened, draft.get('expected')
            self.kit_name.setText(draft['name'])
            self.render_samples()
            if draft.get('saved') and opened and draft['saved'] == str(opened) and fingerprint(opened) == self.kit_fingerprint:
                self.saved_kit = opened
            self.update_kit_status()
            self.unrecovered_draft = False
            if sources:
                self.message('Reopened your Desktop App draft. Save the kit to keep an independent copy.')
        except (OSError, ValueError) as exc:
            self.unrecovered_draft = True
            self.message(f'Could not reopen the Desktop App draft: {exc}')
        finally:
            self.restoring_draft = False

    def recover_kit_draft(self):
        if self.job is not None:
            raise ValueError('Wait for the current operation first.')
        path, _ = W.QFileDialog.getOpenFileName(self, 'Recover a Desktop App draft', str(self.config.state/'outie'), 'Desktop App drafts (*.json)')
        if path and self.discard_kit_changes():
            self.preserve_unrecovered_draft()
            self.restore_kit_draft(Path(path))
            if not self.unrecovered_draft:
                self.persist_kit_draft()

    def manage_kits(self):
        if self.samples and self.saved_kit is None:
            raise ValueError('Save your current kit before managing the archive. Your draft has been kept.')
        from .outie_kit_archive import KitArchiveDialog
        def opened(path):
            if self.discard_kit_changes():
                self.set_opened_kit(*open_ordered_kit(self.config, path))
        def changed(action, path):
            if action == 'archived' and path == self.opened_kit:
                self.new_kit()
            self.message(f'Kit {action}: {path}')
        KitArchiveDialog(self.config, self, is_busy=lambda: self.job is not None,
                         on_open=opened, on_changed=changed).exec()

    def save_current_kit(self):
        if self.tabs.currentIndex() != 0:
            return
        if self.saved_kit is not None:
            self.message(f'Kit already saved: {self.saved_kit}')
            return
        if self.opened_kit is not None:
            self.save_kit_changes()
            return
        if not self.kit_name.text().strip():
            name, accepted = W.QInputDialog.getText(self, 'Save kit', 'Kit name (lowercase letters, numbers, dots or dashes):')
            if not accepted:
                return
            self.kit_name.setText(name)
        self.save_kit()

    def new_kit(self):
        if not self.discard_kit_changes():
            return
        self.samples = []
        self.opened_kit = self.kit_fingerprint = None
        self.kit_name.clear()
        self.render_samples()

    def open_saved_kit(self):
        if self.job is not None:
            raise ValueError('Wait for the current operation or cancel it first.')
        folder = W.QFileDialog.getExistingDirectory(self, 'Open a saved Studio kit or configured pack', str(self.config.kits))
        if not folder:
            return
        opened = open_ordered_kit(self.config, folder)
        if self.discard_kit_changes():
            self.set_opened_kit(*opened)

    def set_opened_kit(self, path, sources, expected):
        self.samples = list(sources)
        self.opened_kit = path
        self.kit_fingerprint = expected
        self.kit_name.clear()
        self.render_samples()
        self.saved_kit = path
        self.update_kit_status()
        self.persist_kit_draft()

    def update_kit_status(self):
        saved = self.saved_kit is not None
        self.send_kit_button.setEnabled(saved)
        self.prepare_kit_button.setEnabled(saved)
        self.save_changes_button.setEnabled(self.opened_kit is not None and not saved)
        if saved:
            self.kit_status.setText(f'Saved kit: {self.saved_kit.name} — ready to check or send.')
        elif self.opened_kit:
            self.kit_status.setText(f'Editing {self.opened_kit.name} — save changes, or enter a new name to save an independent kit.')
        else:
            self.kit_status.setText('New kit — enter a name and save it before sending.')
        self.kit_status.setToolTip(str(self.opened_kit or ''))

    def add_samples(self):
        paths, _ = W.QFileDialog.getOpenFileNames(self, 'Choose sample WAVs', str(self.config.data), 'Wave audio (*.wav *.WAV)')
        if not paths:
            return
        self.samples.extend(map(Path, paths))
        self.render_samples()

    def open_library(self):
        from .outie_library import LibraryDialog
        dialog = LibraryDialog(self)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            selected = dialog.selected_paths()
            if selected:
                self.samples.extend(selected)
                self.render_samples()

    def render_samples(self):
        self.saved_kit = None
        self.sample_list.clear()
        for i, path in enumerate(self.samples):
            from .tuning import shift_label
            badge = shift_label(path)
            self.sample_list.addItem(f'{i:02d}  {path.name}' + (f'  [{badge}]' if badge else ''))
            self.sample_list.item(i).setToolTip(str(path))
        from .transfer import inspect_wav
        seconds = sum(inspect_wav(path) for path in self.samples)
        self.sample_budget.setText(f'{len(self.samples):02} / 100 slots · {seconds:.2f} / 65.00 seconds' +
                                  (' · OVER BUDGET' if len(self.samples) > 100 or seconds > 65 else ''))
        self.update_kit_status()

        self.persist_kit_draft()

    def move_sample(self, offset):
        index = self.sample_list.currentRow()
        other = index + offset
        if 0 <= index < len(self.samples) and 0 <= other < len(self.samples):
            self.samples[index], self.samples[other] = self.samples[other], self.samples[index]
            self.render_samples()
            self.sample_list.setCurrentRow(other)

    def remove_sample(self):
        index = self.sample_list.currentRow()
        if index >= 0:
            self.samples.pop(index)
            self.render_samples()

    def preview_sample(self):
        index = self.sample_list.currentRow()
        if index < 0:
            raise ValueError('Select a sample first.')
        self.preview_source(self.samples[index])

    def preview_source(self, source):
        target = self.target()
        pitch = self.preview_pitch.currentData()
        def run(job):
            import tempfile
            from .transfer import normalize_sample, checked, device_lock
            from .desktop_audio import audio_operation, play
            with tempfile.TemporaryDirectory(prefix='studio-preview-') as tmp:
                path = Path(tmp) / 'preview.wav'
                with device_lock(self.config.state), audio_operation(cancel_event=job.cancel_event):
                    normalize_sample(source, path)
                    shifted = Path(tmp) / 'preview-44100.wav'
                    checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-af',
                             f'asetrate={31250 * 2 ** (pitch / 12)},aresample=44100', '-c:a', 'pcm_s16le', shifted])
                    path = shifted
                    play(path, target, protocol=False)
            return 'Sample preview finished.'
        self.start_job(run)
        if self.job is not None:
            self.job.kind = 'preview'

    def shift_samples(self, direction, amount=None):
        selected = sorted(index.row() for index in self.sample_list.selectedIndexes())
        if not selected:
            raise ValueError('Select one or more samples first.')
        shift = semitone_prompt(self, direction, len(selected)) if amount is None else amount
        if shift is None or shift == 0:
            return
        sources = tuple(self.samples)
        def run(job):
            from .tuning import varispeed
            from .desktop_audio import audio_operation
            replacements = list(sources)
            with audio_operation(cancel_event=job.cancel_event):
                for index in selected:
                    if job.cancel_event.is_set():
                        raise ValueError('Varispeed cancelled; your kit is unchanged.')
                    replacements[index] = varispeed(sources[index], shift, self.config.data / 'variants/varispeed')
            if job.cancel_event.is_set():
                raise ValueError('Varispeed cancelled; your kit is unchanged.')
            return replacements
        def done(paths):
            self.samples = list(paths)
            self.render_samples()
            for index in selected:
                self.sample_list.item(index).setSelected(True)
            self.message(f'Applied {shift:+d} semitones to {len(selected)} samples; review the new kit duration before saving.')
        self.start_job(run, done)

    def make_variant(self):
        # Retain the method for callers of earlier integrations.
        self.shift_samples(1, 12)

    def align_keys(self):
        if not self.samples:
            raise ValueError('Assemble a kit first, then choose its master and slaves.')
        preselected = {index.row() for index in self.sample_list.selectedIndexes()}
        dialog = AlignmentDialog(tuple(self.samples), self.config, self, preselected=preselected)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.samples = list(dialog.aligned_paths)
            self.render_samples()
            self.message('Aligned the selected samples. Save the kit when ready.')

    def save_kit(self):
        name, sources = self.kit_name.text().strip(), tuple(self.samples)
        def done(path):
            self.set_opened_kit(*open_ordered_kit(self.config, path))
            self.message(f'Saved independent kit: {path}')
        self.start_job(lambda job: save_ordered_kit(self.config, name, sources), done)

    def save_kit_changes(self):
        if self.job is not None:
            raise ValueError('Wait for the current operation or cancel it first.')
        if self.opened_kit is None:
            raise ValueError('Open a saved kit first, or save an independent kit.')
        kit, expected, sources = self.opened_kit, self.kit_fingerprint, tuple(self.samples)
        answer = W.QMessageBox.question(
            self, 'Replace saved kit?',
            f'Replace {kit.name} with the current sample selection? Its previous version will be kept in the Studio archive.',
            W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
            W.QMessageBox.StandardButton.Cancel)
        if answer != W.QMessageBox.StandardButton.Yes:
            return
        def done(path):
            self.set_opened_kit(*open_ordered_kit(self.config, path))
            self.message(f'Saved changes to {path.name}. Previous version kept in the Studio archive.')
        self.start_job(lambda job: save_ordered_kit(self.config, kit.name, sources, edit=kit, expected=expected), done)

    def kit_for_transfer(self):
        if self.saved_kit is None:
            raise ValueError('Open a saved kit, save changes to this kit, or save an independent kit first.')
        from .kits import fingerprint
        if fingerprint(self.saved_kit) != self.kit_fingerprint:
            self.saved_kit = None
            self.update_kit_status()
            self.kit_status.setText('Saved kit changed outside the Desktop App — open it again.')
            self.save_changes_button.setEnabled(False)
            raise ValueError('The saved kit changed outside the Desktop App. Open it again before checking or sending.')
        return self.saved_kit

    def prepare_kit(self):
        import tempfile
        from .desktop_audio import audio_operation
        from .transfer import prepare
        from .kits import fingerprint
        kit = self.kit_for_transfer()
        expected = self.kit_fingerprint
        def work(job):
            with audio_operation(cancel_event=job.cancel_event), tempfile.TemporaryDirectory(prefix='outie-prepare-') as tmp:
                if fingerprint(kit) != expected:
                    raise ValueError('The saved kit changed outside the Desktop App. Open it again before checking.')
                manifest = prepare(kit, Path(tmp) / 'prepared', self.config.syro_dir)
                if fingerprint(kit) != expected:
                    raise ValueError('The saved kit changed during preparation. Open it again before checking.')
            return f'Checked {100 + manifest["count"]} signals offline. Nothing was played or sent.'
        self.start_job(work)

    def send_kit(self):
        kit = self.kit_for_transfer()
        expected = self.kit_fingerprint
        from .transfer import transfer
        self.device_job(lambda job, target: transfer(kit, self.config, job.confirm, target, expected_fingerprint=expected))

    def patterns_page(self):
        layout = self.page('02 / Patterns', 'Open a saved bank, create neutral memories, or restore selected stored slots. Backup is optional. A saved copy cannot contain later edits made on the instrument.')
        row = W.QHBoxLayout()
        row.addWidget(self.button('Open bank…', self.open_bank))
        row.addWidget(self.button('Save bank copy…', self.save_bank_copy))
        self.firmware_target = W.QComboBox()
        for ident, title in FIRMWARE_LABELS.items():
            self.firmware_target.addItem(title, ident)
        self.firmware_target.setAccessibleName('Installed destination firmware')
        row.addWidget(self.firmware_target)
        row.addStretch(1)
        layout.addLayout(row)
        self.bank_label = W.QLabel('No bank loaded. Reset + groove does not require one.')
        layout.addWidget(self.bank_label)
        self.pattern_slots = W.QLineEdit('all')
        self.pattern_slots.setAccessibleName('Pattern memories: all or numbered 1 through 10')
        form = W.QFormLayout()
        form.addRow('Memories (all / 1,3 / 1-4)', self.pattern_slots)
        layout.addLayout(form)
        row = W.QHBoxLayout()
        row.addWidget(self.button('Create reset bank', self.reset_bank))
        row.addWidget(self.button('Select compatible memories', self.select_compatible_patterns))
        row.addWidget(self.button('Restore selected memories…', self.send_patterns))
        row.addStretch(1)
        layout.addLayout(row)
        from .outie_pattern_actions import restore_current_snapshot, restore_neutral_patterns, decode_recorded_backup
        row = W.QHBoxLayout()
        row.addWidget(self.button('Restore current snapshot…', lambda: restore_current_snapshot(self)))
        row.addWidget(self.button('Reset memories + current buffer…', lambda: restore_neutral_patterns(self, reset_current=True)))
        row.addWidget(self.button('Decode recorded backup…', lambda: decode_recorded_backup(self)))
        row.addStretch(1)
        layout.addLayout(row)
        self.bank_info = W.QPlainTextEdit()
        self.bank_info.setReadOnly(True)
        layout.addWidget(self.bank_info, 1)
        backup_row = W.QHBoxLayout()
        self.backup_midi = W.QComboBox()
        self.backup_midi.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.backup_midi.setMinimumContentsLength(12)
        self.backup_midi.setAccessibleName('Backup MIDI output to Volca MIDI IN')
        self.backup_input = W.QComboBox()
        self.backup_input.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.backup_input.setMinimumContentsLength(12)
        self.backup_input.setAccessibleName('Backup audio input from Volca headphones')
        backup_row.addWidget(self.backup_midi, 1)
        backup_row.addWidget(self.backup_input, 1)
        backup_row.addWidget(self.button('Refresh inputs', self.refresh_backup_ports))
        backup_row.addWidget(self.button('Capture pattern backup…', self.capture_backup))
        layout.addLayout(backup_row)

    def refresh_backup_ports(self):
        from .desktop_audio import input_devices, midi_outputs
        previous_midi = self.backup_midi.currentText() if self.backup_midi.currentData() else self.device_preferences.get('backup_midi')
        previous_input = self.backup_input.currentText() if self.backup_input.currentData() else self.device_preferences.get('backup_input')
        self.backup_midi.clear()
        self.backup_input.clear()
        self.backup_midi.addItem('Select MIDI output', None)
        self.backup_input.addItem('Select backup audio input', None)
        for name in midi_outputs():
            self.backup_midi.addItem(name, name)
        for device in input_devices():
            self.backup_input.addItem(device['name'], device['id'])
        self.restore_device_choice(self.backup_midi, previous_midi)
        self.restore_device_choice(self.backup_input, previous_input)

    def capture_backup(self):
        port, node = self.backup_midi.currentData(), self.backup_input.currentData()
        if not port or not node:
            raise ValueError('Refresh inputs, then select the MIDI output and audio input for backup.')
        if W.QMessageBox.question(self, 'Capture pattern backup',
                'The audio pattern backup stops playback. Connect PC MIDI OUT to MIDI IN and the Volca headphone output to the selected audio input. Start capture?',
                W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
                W.QMessageBox.StandardButton.Cancel) != W.QMessageBox.StandardButton.Yes:
            return
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save captured bank', str(self.config.patterns / 'machine.vspatterns'), 'Pattern banks (*.vspatterns)')
        if not path:
            return
        def run(job):
            from .pattern_device import backup_audio
            from .desktop_audio import audio_operation
            with audio_operation(cancel_event=job.cancel_event):
                backup_audio(self.config, port, node, path, progress_callback=lambda *args: job.notice.emit(' '.join(map(str, args))))
            return path
        self.start_job(run, lambda result: (self.set_bank(load_bank(result), Path(result)), self.message('Backup captured and verified.')))

    def set_bank(self, patterns, path=None):
        self.bank, self.bank_path = list(patterns), path
        self.bank_label.setText(str(path) if path else 'New offline bank — save a copy to keep it')
        from .outie_model import predictability_summary
        self.bank_info.setPlainText('\n'.join(f'Memory {p.slot + 1 if p.slot is not None else "current (not restored)"}: {p.firmware} · {p.sha256[:12]}\n  {predictability_summary(p)}' for p in self.bank))
        self.invalidate_groove_save()
        self.update_groove_scope()

    def open_bank(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Open pattern copy', str(self.config.patterns), 'Pattern banks (*.vspatterns *.syx *.json);;All files (*)')
        if path:
            self.set_bank(load_bank(path), Path(path))

    def save_bank_copy(self):
        if self.bank is None:
            raise ValueError('Open or create a bank first.')
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save new bank copy', str(self.config.patterns / 'pattern-copy.vspatterns'), 'Pattern banks (*.vspatterns)')
        if path:
            save_bank(path, self.bank)
            self.message(f'Saved offline: {path}')

    def reset_bank(self):
        slots = parse_slots(self.pattern_slots.text())
        target = self.firmware_target.currentData()
        self.set_bank([blank_pattern(target, slot) for slot in slots])
        bars = 8 if target == 'lumon-xl-internal' else 4
        self.message(f'Neutral patterns created offline: Predictability ALL, bar filtering {bars}/{bars}. No device was changed.')

    def send_patterns(self):
        if self.bank is None:
            raise ValueError('Open or create a bank first.')
        slots = parse_slots(self.pattern_slots.text())
        patterns = [p for p in self.bank if p.slot in slots]
        if not patterns:
            raise ValueError('No stored patterns match the selected memories. Current-buffer snapshots need a stored destination first.')
        target_firmware = self.firmware_target.currentData()
        from .pattern_transfer import pattern_targets
        pattern_targets(patterns, target_firmware)  # reject mixed incompatible selections before device work
        from .pattern_transfer import transfer_patterns
        self.device_job(lambda job, target: transfer_patterns(patterns, self.config, target_firmware, target=target, confirm_callback=job.confirm))

    def select_compatible_patterns(self):
        if self.bank is None:
            raise ValueError('Open a bank first.')
        target = self.firmware_target.currentData()
        from .pattern_transfer import pattern_targets
        slots = []
        for pattern in self.bank:
            if pattern.slot is None:
                continue
            try:
                pattern_targets([pattern], target)
            except ValueError:
                continue
            slots.append(pattern.slot)
        slots.sort()
        self.pattern_slots.setText(','.join(str(slot + 1) for slot in slots))
        self.message(f'{len(slots)} compatible stored memories selected. Current snapshots need an explicit destination.')

    def grooves_page(self):
        layout = self.page('03 / Grooves', '1. Select pattern memories.  2. Assign templates to parts.  3. Save the modified bank.  4. Send the saved bank to the Volca when ready. Reference SWING 0.')
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel('Installed firmware'))
        self.groove_firmware = W.QComboBox()
        for ident, title in FIRMWARE_LABELS.items():
            self.groove_firmware.addItem(title, ident)
        self.groove_firmware.setAccessibleName('Groove destination firmware')
        self.groove_firmware.setEnabled(False)
        row.addWidget(self.groove_firmware)
        row.addWidget(self.button('Open pattern bank…', self.open_bank))
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(W.QLabel('1 / Pattern memories — tick one, several, or all ten'))
        row = W.QHBoxLayout()
        self.groove_memories = []
        for slot in range(10):
            check = W.QCheckBox(str(slot + 1))
            check.setAccessibleName(f'Apply groove to pattern memory {slot + 1}')
            check.setChecked(True)
            check.toggled.connect(self.select_groove_memories)
            self.groove_memories.append(check)
            row.addWidget(check)
        layout.addLayout(row)
        row = W.QHBoxLayout()
        row.addWidget(self.button('All 10 patterns', lambda: self.pattern_slots.setText('all')))
        row.addWidget(self.button('Clear selection', lambda: self.pattern_slots.setText('')))
        row.addStretch(1)
        layout.addLayout(row)
        self.groove_scope = W.QLabel()
        self.groove_scope.setWordWrap(True)
        layout.addWidget(self.groove_scope)
        self.reset_groove = W.QCheckBox('Reset + groove — clear notes and motion; reset secondary parameters')
        self.reset_groove.toggled.connect(self.update_groove_scope)
        self.reset_groove.toggled.connect(self.invalidate_groove_save)
        layout.addWidget(self.reset_groove)
        layout.addWidget(W.QLabel('2 / Parts — the same assignments apply to every selected pattern'))
        form = W.QFormLayout()
        self.groove_combos = []
        catalog = load_catalog(firmware=self.groove_firmware.currentData())
        self.catalog = catalog
        for part in range(1, 11):
            combo = W.QComboBox()
            combo.setEditable(True)
            combo.setInsertPolicy(W.QComboBox.InsertPolicy.NoInsert)
            combo.addItem('Keep existing / straight after reset', None)
            for template in catalog.templates:
                combo.addItem(template.id + ' · ' + template.display_name, template.id)
            combo.setAccessibleName(f'Groove template for part {part}')
            combo.completer().setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            combo.currentIndexChanged.connect(lambda index, c=combo: self.preview_groove(c))
            combo.editTextChanged.connect(self.invalidate_groove_save)
            form.addRow(f'Part {part:02}', combo)
            self.groove_combos.append(combo)
        layout.addLayout(form)
        self.groove_preview = W.QLabel('Each microstep is 1/32 of a sequencer step.')
        self.groove_preview.setWordWrap(True)
        layout.addWidget(self.groove_preview)
        layout.addStretch()
        layout.addWidget(self.button('3 / Apply templates & save bank…', self.save_grooves))
        self.groove_saved_status = W.QLabel('Save first. Nothing has been sent to the Volca.')
        self.groove_saved_status.setWordWrap(True)
        layout.addWidget(self.groove_saved_status)
        self.send_groove_button = self.button('4 / Send saved groove bank to Volca…', self.send_grooves)
        layout.addWidget(self.send_groove_button)
        self.pattern_slots.textChanged.connect(self.sync_groove_memories)
        self.saved_groove = None
        self.invalidate_groove_save()
        self.update_groove_scope()

    def select_groove_memories(self):
        selected = [str(i + 1) for i, box in enumerate(self.groove_memories) if box.isChecked()]
        self.pattern_slots.setText('all' if len(selected) == 10 else ','.join(selected))

    def sync_groove_memories(self):
        try:
            slots = parse_slots(self.pattern_slots.text())
        except ValueError:
            slots = ()
        for slot, box in enumerate(self.groove_memories):
            box.blockSignals(True)
            box.setChecked(slot in slots)
            box.blockSignals(False)
        self.invalidate_groove_save()
        self.update_groove_scope()

    def update_groove_scope(self):
        try:
            slots = parse_slots(self.pattern_slots.text())
            scope = ', '.join(str(s + 1) for s in slots)
            selection = f'{len(slots)} pattern(s) selected: {scope}.'
        except ValueError:
            selection = 'Select at least one pattern memory (1–10).'
        stored = sorted(p.slot + 1 for p in (self.bank or []) if p.slot is not None)
        source = ('Loaded bank memories: ' + ', '.join(map(str, stored)) + '.' if stored else 'No stored pattern bank loaded.')
        mode = ('Reset + groove creates empty patterns; no backup is required.' if self.reset_groove.isChecked() else
                'Preserve needs a local copy of every selected memory. Other parameters in that copy are retained.')
        self.groove_scope.setText(selection + '\n' + source + '\n' + mode)

    def invalidate_groove_save(self):
        self.saved_groove = None
        if hasattr(self, 'send_groove_button'):
            self.send_groove_button.setEnabled(False)
            self.groove_saved_status.setText('Apply templates & save first. Nothing has been sent to the Volca.')

    def reload_grooves(self):
        self.invalidate_groove_save()
        target = self.groove_firmware.currentData()
        catalog = load_catalog(firmware=target)
        previous = [combo.currentData() for combo in self.groove_combos]
        self.catalog = catalog
        for combo, ident in zip(self.groove_combos, previous):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem('Keep existing / straight after reset', None)
            for template in catalog.templates:
                combo.addItem(template.id + ' · ' + template.display_name, template.id)
            combo.setCurrentIndex(max(0, combo.findData(ident)))
            combo.blockSignals(False)
        self.groove_preview.setText('DataBeat OS 1.0 · range ±15 microsteps · SWING 0 reference')

    def preview_groove(self, combo):
        ident = combo.currentData()
        if ident:
            template = self.catalog.resolve(ident)
            self.groove_preview.setText(' '.join(f'{v:+d}' for v in template.microtiming) + f'\n{template.measured_count} measured / {template.inferred_count} reconstructed steps')

    def save_grooves(self):
        if any(c.currentText() != c.itemText(c.currentIndex()) for c in self.groove_combos):
            raise ValueError('Choose each groove from the matching results before saving.')
        assignments = {i + 1: c.currentData() for i, c in enumerate(self.groove_combos) if c.currentData()}
        if not assignments:
            raise ValueError('Choose a groove template for at least one part.')
        if not self.pattern_slots.text().strip():
            raise ValueError('Select at least one pattern memory (1–10).')
        target = self.groove_firmware.currentData()
        plan = plan_grooves(self.bank, assignments, parse_slots(self.pattern_slots.text()), catalog=self.catalog, firmware=target, source_bank=self.bank, reset=self.reset_groove.isChecked())
        path, _ = W.QFileDialog.getSaveFileName(self, 'Save new groove bank', str(self.config.patterns / 'groove.vspatterns'), 'Pattern banks (*.vspatterns)')
        if path:
            output, rollback = save_groove_plan(path, plan)
            self.set_bank(load_bank(output), output)
            self.saved_groove = (tuple(plan.selected_patterns), target, Path(output))
            self.send_groove_button.setEnabled(True)
            slots = ', '.join(str(p.slot + 1) for p in plan.selected_patterns)
            self.groove_saved_status.setText(f'Saved offline in the {FIRMWARE_LABELS[target]} · pattern memories {slots}.\nNext: select Audio output below, then Send saved groove bank. Full selected memories will be replaced; later device edits are not included.')
            self.message(f'Saved groove bank for memories {slots}: {output}\nNothing sent. Use Send saved groove bank to apply it on the Volca.' + (f'\nOriginal copy (source bank only): {rollback}' if rollback else ''))
            if plan.unbacked_slots:
                self.message('No original copy for memories: ' + ', '.join(str(n + 1) for n in plan.unbacked_slots))

    def send_grooves(self):
        if self.saved_groove is None:
            raise ValueError('Apply templates & save the groove bank before sending. Save again after changing any selection.')
        patterns, firmware, path = self.saved_groove
        if tuple(load_bank(path)) != patterns:
            self.invalidate_groove_save()
            raise ValueError('The saved groove bank changed. Apply templates & save a new copy before sending.')
        from .pattern_transfer import transfer_patterns
        self.device_job(lambda job, target: transfer_patterns(patterns, self.config, firmware,
            target=target, confirm_callback=job.confirm))

    def firmware_page(self):
        layout = self.page('04 / Firmware', 'DataBeat OS and the Korg updater\nStudio contains no firmware. Add the Korg updater you downloaded; Studio builds DataBeat OS from it and checks the result. Select an image, review its status, then authorize the procedure.')
        self.firmware_hint = W.QLabel()
        self.firmware_hint.setWordWrap(True)
        self.firmware_hint.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.firmware_hint)
        self.firmware_list = W.QListWidget()
        self.firmware_list.setAccessibleName('Firmware archive')
        self.firmware_list.currentItemChanged.connect(self.describe_firmware)
        layout.addWidget(self.firmware_list, 1)
        self.firmware_details = W.QPlainTextEdit()
        self.firmware_details.setReadOnly(True)
        layout.addWidget(self.firmware_details, 1)
        row = W.QHBoxLayout()
        row.addWidget(self.button('Refresh archive', self.refresh_firmware))
        row.addWidget(self.button('Add Korg 1.42 updater…', self.add_korg_updater))
        row.addWidget(self.button('Begin update…', self.send_firmware))
        row.addStretch(1)
        layout.addLayout(row)

    def refresh_firmware(self):
        self.firmware_list.clear()
        try:
            from .firmware import add_hint, list_firmware
            entries = list_firmware(self.config)
            for entry in entries:
                item = W.QListWidgetItem(f'{entry["name"]} · {entry.get("version", "")} · {entry["status"]}')
                item.setData(QtCore.Qt.ItemDataRole.UserRole, entry)
                self.firmware_list.addItem(item)
            self.firmware_hint.setText('' if entries else 'No firmware on file. ' + add_hint())
            self.firmware_hint.setVisible(not entries)
        except (ImportError, ValueError, OSError) as exc:
            self.message(f'Firmware archive: {exc}')

    def describe_firmware(self, item, previous=None):
        self.firmware_details.setPlainText(json.dumps(item.data(QtCore.Qt.ItemDataRole.UserRole), indent=2, default=str) if item else '')

    def add_korg_updater(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Choose the Korg volca sample 1.42 updater', str(Path.home()),
                                                'Korg updater (*.zip *.wav)')
        if not path:
            return
        from .firmware import add_korg_updater
        self.start_job(lambda job: add_korg_updater(path, self.config), lambda result: (
            self.message('DataBeat OS built from your Korg updater. Studio checked the result. '
                         'Review the archive before transferring.'), self.refresh_firmware()))

    def send_firmware(self):
        item = self.firmware_list.currentItem()
        if not item:
            raise ValueError('Select firmware from the archive first.')
        entry = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not entry.get('installable', False):
            raise ValueError('This image is archived for offline analysis only and cannot be installed. Select an installable release.')
        from .firmware import transfer_firmware
        # Studio offers only the accepted release and the Korg updater; the
        # backend refuses anything experimental.
        self.device_job(lambda job, target: transfer_firmware(self.config, entry['id'], target=target,
            confirm_callback=job.confirm))

    def closeEvent(self, event):
        if self.job:
            self.cancel_job()
            self.message('Wait for cancellation before closing the application.')
            event.ignore()
        else:
            if self.samples and self.saved_kit is None and self.draft_write_failed:
                answer = W.QMessageBox.question(self, 'Draft could not be saved',
                    'Closing now will lose the unsaved sample selection. Close anyway?',
                    W.QMessageBox.StandardButton.Discard | W.QMessageBox.StandardButton.Cancel,
                    W.QMessageBox.StandardButton.Cancel)
                if answer != W.QMessageBox.StandardButton.Discard:
                    event.ignore()
                    return
            self.library.shutdown()
            self.detail.shutdown()
            event.accept()


def graceful_termination(window, interval=300):
    """Close the window on SIGTERM/SIGINT so the draft is saved and threads stop.

    Python signal handlers run only when the interpreter gets control, so a
    timer polls the request from inside the Qt event loop. A running device
    operation is cancelled first; the window closes once it has finished.
    """
    import signal
    state = {'requested': False, 'cancelled': False}

    def request(signum, frame):
        state['requested'] = True

    for name in ('SIGTERM', 'SIGINT'):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), request)
            except (ValueError, OSError):
                pass  # not the main thread, or unsupported platform

    def tick():
        if not state['requested']:
            return
        if window.job is not None:
            if not state['cancelled']:
                state['cancelled'] = True
                window.cancel_job()
            return
        state['requested'] = False
        state['cancelled'] = False
        window.close()

    ticker = QtCore.QTimer(window)
    ticker.setInterval(interval)
    ticker.timeout.connect(tick)
    ticker.start()
    return request


def main():
    verify_output = None
    if '--verify-offline' in sys.argv:
        index = sys.argv.index('--verify-offline')
        if index + 1 >= len(sys.argv):
            return 2
        verify_output = Path(sys.argv[index + 1])
        if verify_output.exists():
            return 2
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    app.setApplicationName('VolcaStudio XL Desktop App')
    base = Path(__file__).resolve().parents[1]
    icon = base / 'assets/outie.svg'
    if not icon.is_file():
        icon = base / 'packaging/outie.svg'
    app.setWindowIcon(QtGui.QIcon(str(icon)))
    app.setOrganizationName('VolcaStudio XL')
    app.setStyleSheet(STYLE)
    temporary = None
    if '--smoke-test' in sys.argv or verify_output is not None:
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix='studio-outie-smoke-')
        p = Path(temporary.name).resolve()
        config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', base/'build/syro')
    else:
        config = None
    try:
        window = Studio(config, discover_devices=temporary is None)
    except Exception as exc:
        if temporary is not None:
            try:
                if verify_output is not None:
                    verify_output.mkdir(parents=True, exist_ok=False)
                    (verify_output / 'report.json').write_text(json.dumps({
                        'passed': False, 'hardware_access': False, 'checks': {},
                        'error': f'Startup failed: {type(exc).__name__}: {exc}'
                    }, indent=2) + '\n', encoding='utf-8')
                if sys.stderr is not None:
                    print(f'Desktop App startup failed: {exc}', file=sys.stderr)
            finally:
                temporary.cleanup()
            return 1
        W.QMessageBox.critical(None, 'VolcaStudio XL could not start', str(exc))
        return 1
    window.show()
    if verify_output is not None:
        from .desktop_verify import verify
        try:
            return verify(window, app, verify_output)
        finally:
            window.close()
            temporary.cleanup()
    if temporary is not None:
        QtCore.QTimer.singleShot(150, app.quit)
    else:
        graceful_termination(window)
    result = app.exec()
    if temporary is not None:
        temporary.cleanup()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
