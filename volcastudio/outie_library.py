"""Browse, audition and inspect sample libraries.

``LibraryPanel`` is embedded in the Desktop App's Samples section next to the kit;
``DetailPanel`` shows the listening notes (waveform and facts) for the sample
selected in either list. ``LibraryDialog`` keeps the earlier Browse window
around the same panel for the add-samples flow.
"""
import threading
from pathlib import Path
from types import SimpleNamespace
from PySide6 import QtCore, QtGui, QtWidgets as W
from .outie_model import library_roots
from .outie_widgets import SampleListView, flow_row


class Scan(QtCore.QThread):
    batch = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, roots, parent=None):
        super().__init__(parent)
        self.roots = roots

    def run(self):
        batch, seen = [], set()
        try:
            for root in self.roots:
                for path in root.rglob('*'):
                    if self.isInterruptionRequested():
                        return
                    if path.suffix.lower() != '.wav' or not path.is_file():
                        continue
                    path = path.resolve()
                    if path in seen:
                        continue
                    seen.add(path)
                    batch.append(path)
                    if len(batch) == 100:
                        self.batch.emit(batch)
                        batch = []
            if batch:
                self.batch.emit(batch)
        except OSError as exc:
            self.failed.emit(str(exc))


def sample_facts(path, cache):
    """Duration, format, provenance and the cached pitch estimate of one sample."""
    import json
    from .audio import detect_pitch, note
    from .transfer import checked, inspect_wav, MAX_SECONDS
    from .tuning import tuning_metadata, filename_pitch
    path = Path(path)
    seconds = inspect_wav(path)
    meta = tuning_metadata(path)
    pitch = detect_pitch(path, cache)
    stream = json.loads(checked(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                                 'stream=sample_rate,channels,bits_per_sample', '-of', 'json', path],
                                capture_output=True, text=True).stdout)['streams'][0]
    named = None if meta.get('history_uncertain') else filename_pitch(meta.get('original_name', path.name))
    midi = pitch.get('midi')
    return {'name': path.name, 'seconds': seconds, 'memory_percent': seconds / MAX_SECONDS * 100,
            'rate': int(stream['sample_rate']), 'channels': int(stream['channels']),
            'bits': int(stream.get('bits_per_sample') or 0),
            'label': meta['label'], 'semitones': meta['semitones'], 'factor': meta['factor'],
            'original': meta.get('original_name', Path(meta['source']).name),
            'uncertain': bool(meta.get('history_uncertain')), 'pitch': pitch,
            'filename_note': named['note'] if named else None,
            'at_speed': (note(midi - 12), note(midi - 24)) if midi is not None else None}


def waveform_png(path, cache):
    """A cached waveform picture rendered by FFmpeg; the audio is not modified."""
    from .audio import identity
    from .transfer import checked
    _, key = identity(path)
    png = Path(cache) / 'outie-waveforms' / f'{key}.png'
    png.parent.mkdir(parents=True, exist_ok=True)
    if not png.is_file():
        checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-filter_complex',
                 'showwavespic=s=600x100:colors=0x91d5c5', '-frames:v', '1', png], capture_output=True)
    return png


def facts_text(facts):
    pitch = facts['pitch']
    if pitch.get('note'):
        measured = f"{pitch['note']} · {pitch['hz']:g} Hz · {pitch['cents']:+g} cents · confidence {pitch['confidence']:.0%}"
    else:
        measured = f"{pitch.get('status', 'unclear')} · confidence {pitch.get('confidence', 0):.0%}"
    speed = f" · at SPEED −12 / −24: {facts['at_speed'][0]} / {facts['at_speed'][1]}" if facts['at_speed'] else ''
    channels = {1: 'mono', 2: 'stereo'}.get(facts['channels'], f"{facts['channels']} channels")
    bits = f" · {facts['bits']}-bit" if facts['bits'] else ''
    if facts['semitones']:
        provenance = (f"varispeed {facts['semitones']:+d} semitones (speed ×{facts['factor']:.4f}) of {facts['original']}"
                      + (' · history uncertain' if facts['uncertain'] else ''))
    else:
        provenance = 'original speed'
    return (f"{facts['seconds']:.3f} s · {facts['memory_percent']:.1f}% of the Volca's memory · "
            f"{facts['rate']} Hz{bits} · {channels}\n"
            f"measured {measured}{speed}\n"
            f"{provenance} · filename note: {facts['filename_note'] or '—'}")


class Analysis(QtCore.QThread):
    """Facts and waveform for one sample, outside the device operation queue."""
    result = QtCore.Signal(object)
    failed = QtCore.Signal(object)

    def __init__(self, path, cache, parent=None):
        super().__init__(parent)
        self.path, self.cache = Path(path), Path(cache)
        self.cancel_event = threading.Event()

    def run(self):
        from .desktop_audio import audio_operation
        try:
            with audio_operation(cancel_event=self.cancel_event):
                facts = sample_facts(self.path, self.cache / 'pitch')
                png = waveform_png(self.path, self.cache)
            self.result.emit((self.path, facts, png))
        except (Exception, KeyboardInterrupt) as exc:
            if not self.cancel_event.is_set():
                self.failed.emit((self.path, str(exc) or type(exc).__name__))


class DetailPanel(W.QWidget):
    """Listening notes for the sample selected in the library or the kit."""
    HINT = 'Listening notes — select a sample in the library or in the kit.'

    def __init__(self, studio, parent=None):
        super().__init__(parent)
        self.studio = studio
        self.path = None
        self.pixmap = None
        self.workers = set()
        self.setAccessibleName('Listening notes')
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        self.title = W.QLabel(self.HINT)
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        row = W.QHBoxLayout()
        row.setSpacing(12)
        self.waveform = W.QLabel()
        self.waveform.setFixedHeight(56)
        self.waveform.setScaledContents(True)  # follow the panel width without raising the window's minimum
        self.waveform.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Fixed)
        self.waveform.setAccessibleName('Waveform of the selected sample')
        row.addWidget(self.waveform, 2)
        self.facts = W.QLabel()
        self.facts.setWordWrap(True)
        self.facts.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.facts.setAccessibleName('Sample facts')
        self.facts.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
        row.addWidget(self.facts, 3)
        layout.addLayout(row)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.analyze)

    def show_path(self, path):
        path = Path(path) if path else None
        if path == self.path:
            return
        self.path, self.pixmap = path, None
        self.waveform.clear()
        self.stop()
        if path is None:
            self.title.setText(self.HINT)
            self.facts.setText('')
            return
        self.title.setText(f'Listening notes — {path.name}')
        self.facts.setText('listening…')
        self.timer.start(150)

    def stop(self):
        self.timer.stop()
        for worker in self.workers:
            worker.cancel_event.set()

    def analyze(self):
        path = self.path
        if path is None:
            return
        self.stop()
        worker = Analysis(path, self.studio.config.cache, self)
        worker.result.connect(self.show_result)
        worker.failed.connect(self.show_failure)
        worker.finished.connect(lambda: self.workers.discard(worker))
        worker.finished.connect(worker.deleteLater)
        self.workers.add(worker)
        worker.start()

    def show_result(self, result):
        path, facts, png = result
        if path != self.path:
            return
        self.facts.setText(facts_text(facts))
        self.pixmap = QtGui.QPixmap(str(png))
        self.waveform.setPixmap(self.pixmap)

    def show_failure(self, failure):
        path, text = failure
        if path == self.path:
            self.facts.setText(f'Not analyzed: {text}')

    def shutdown(self):
        self.stop()
        for worker in list(self.workers):
            worker.wait(3000)


class LibraryPanel(W.QWidget):
    """Registered libraries and kits: search, audition and add samples to the kit."""
    current_changed = QtCore.Signal(object)
    add_requested = QtCore.Signal(object)

    def __init__(self, studio, parent=None):
        super().__init__(parent)
        self.studio = studio
        self.config = studio.config
        self.scan = None
        self.closed = False
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.roots = W.QComboBox()
        self.roots.setAccessibleName('Sample library')
        self.roots.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.roots.setMinimumContentsLength(16)  # long folder paths must not widen the window
        layout.addWidget(self.roots)
        choose = W.QPushButton('Browse folder…')
        choose.clicked.connect(self.choose_folder)
        register = W.QPushButton('Register library…')
        register.clicked.connect(lambda: studio.guarded(self.register_library))
        remove = W.QPushButton('Unregister')
        remove.clicked.connect(lambda: studio.guarded(self.unregister_library))
        flow_row(layout, choose, register, remove)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText('Search samples across the selected libraries…')
        self.search.setAccessibleName('Search sample libraries')
        layout.addWidget(self.search)
        self.model = QtGui.QStandardItemModel(self)
        self.proxy = QtCore.QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setSortCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterRole(QtCore.Qt.ItemDataRole.UserRole + 1)
        self.proxy.sort(0)
        self.listing = SampleListView()
        self.listing.setModel(self.proxy)
        self.listing.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.listing.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        self.listing.setMinimumHeight(96)
        self.listing.setAccessibleName('Library samples')
        layout.addWidget(self.listing, 1)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.add_button = W.QPushButton('Add to kit')
        self.add_button.setToolTip('Add the selected library samples to the kit (Enter)')
        self.add_button.clicked.connect(lambda: studio.guarded(self.add_selected))
        preview = W.QPushButton('Preview selected sample')
        preview.clicked.connect(lambda: studio.guarded(self.preview))
        self.autoplay = W.QCheckBox('Preview on selection')
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.preview_latest)
        flow_row(layout, self.add_button, preview, self.autoplay)
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        self.listing.selectionModel().currentChanged.connect(self.selection_changed)
        self.listing.activated.connect(lambda index: studio.guarded(self.add_selected))
        self.roots.currentIndexChanged.connect(self.reload)
        self.load_roots()

    def stop_scan(self):
        if self.scan is not None:
            self.scan.requestInterruption()
            self.scan.wait()
            self.scan.deleteLater()
            self.scan = None

    def load_roots(self):
        self.roots.blockSignals(True)
        self.roots.clear()
        roots = library_roots(self.config)
        self.roots.addItem('All registered libraries and kits', roots)
        for root in roots:
            self.roots.addItem(str(root), (root,))
        self.roots.blockSignals(False)
        self.reload()

    def reload(self):
        self.stop_scan()
        self.model.clear()
        roots = self.roots.currentData() or ()
        self.status.setText('Reading sample names…')
        self.scan = Scan(roots, self)
        scan = self.scan
        self.scan.batch.connect(lambda paths: self.add_batch(paths) if self.scan is scan else None)
        self.scan.failed.connect(lambda text: self.status.setText(text) if self.scan is scan else None)
        self.scan.finished.connect(lambda: self.status.setText(f'{self.model.rowCount()} samples. Select rows, then Add to kit.') if self.scan is scan else None)
        self.scan.start()

    def add_batch(self, paths):
        for path in paths:
            roots = sorted(self.roots.currentData() or (), key=lambda p: len(p.parts), reverse=True)
            root = next((root for root in roots if path.is_relative_to(root)), None)
            label = f'{root.name}/{path.relative_to(root)}' if root else path.name
            item = QtGui.QStandardItem(label)
            item.setToolTip(str(path))
            item.setData(path, QtCore.Qt.ItemDataRole.UserRole)
            item.setData(str(path), QtCore.Qt.ItemDataRole.UserRole + 1)
            item.setEditable(False)
            self.model.appendRow(item)

    def selected_paths(self):
        return [index.data(QtCore.Qt.ItemDataRole.UserRole) for index in sorted(self.listing.selectionModel().selectedRows(), key=lambda i: i.row())]

    def current_path(self):
        path = self.listing.currentIndex().data(QtCore.Qt.ItemDataRole.UserRole)
        if path is None:
            raise ValueError('Select a library sample first.')
        return path

    def selection_changed(self, *_):
        if not self.listing.currentIndex().isValid():
            self.current_changed.emit(None)
            return
        from .transfer import inspect_wav
        path = self.current_path()
        self.current_changed.emit(path)
        try:
            self.status.setText(f'{path.name} · {inspect_wav(path):.3f} seconds')
            if self.autoplay.isChecked():
                self.preview_latest()
        except (OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def add_selected(self):
        paths = self.selected_paths()
        if not paths:
            raise ValueError('Select one or more library samples first.')
        self.add_requested.emit(paths)

    def preview(self):
        self.studio.preview_source(self.current_path())

    def preview_latest(self):
        if self.closed or not self.autoplay.isChecked() or not self.listing.currentIndex().isValid():
            return
        if self.studio.job is not None:
            if getattr(self.studio.job, 'kind', None) == 'preview':
                self.studio.cancel_job()
                self.preview_timer.start(25)
            return
        self.studio.guarded(self.preview)

    def choose_folder(self):
        folder = W.QFileDialog.getExistingDirectory(self, 'Browse a sample folder')
        if folder:
            root = Path(folder).resolve()
            self.roots.addItem(str(root), (root,))
            self.roots.setCurrentIndex(self.roots.count() - 1)

    def register_library(self):
        if self.studio.job is not None:
            raise ValueError('Wait for the current operation first.')
        folder = W.QFileDialog.getExistingDirectory(self, 'Register a sample library in place')
        if not folder:
            return
        from .libraries import library
        library(self.config, SimpleNamespace(action='add', directory=folder, name=None), quiet=True)
        self.load_roots()

    def unregister_library(self):
        if self.studio.job is not None:
            raise ValueError('Wait for the current operation first.')
        selected = self.roots.currentData()
        if not selected or len(selected) != 1:
            raise ValueError('Choose one registered library first.')
        from .libraries import library, registrations
        matches = [line.split('=', 1)[0].strip() for line in registrations(self.config).splitlines()
                   if '=' in line and Path(line.split('=', 1)[1].strip()).expanduser().resolve() == selected[0]]
        if len(matches) != 1:
            raise ValueError('This folder is not one registered library.')
        if W.QMessageBox.question(self, 'Unregister library?', 'Remove this library from Studio’s list? Its sample files remain in their current folder.',
                                 W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
                                 W.QMessageBox.StandardButton.Cancel) != W.QMessageBox.StandardButton.Yes:
            return
        library(self.config, SimpleNamespace(action='remove', directory=matches[0]), quiet=True)
        self.load_roots()

    def shutdown(self):
        self.closed = True
        self.preview_timer.stop()
        if self.studio.job is not None and getattr(self.studio.job, 'kind', None) in ('preview', 'library-analysis'):
            self.studio.cancel_job()
        self.stop_scan()


class LibraryDialog(W.QDialog):
    """The Browse window: the same panel, plus an inspect button and Add/Cancel."""
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.config = studio.config
        self.setWindowTitle('Browse sample libraries')
        self.resize(850, 650)
        layout = W.QVBoxLayout(self)
        self.panel = LibraryPanel(studio, self)
        layout.addWidget(self.panel, 1)
        self.waveform = W.QLabel()
        self.waveform.setMaximumHeight(100)
        layout.addWidget(self.waveform)
        inspect = W.QPushButton('Inspect pitch / waveform')
        inspect.clicked.connect(lambda: studio.guarded(self.inspect))
        flow_row(layout, inspect)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        buttons.button(W.QDialogButtonBox.StandardButton.Ok).setText('Add selected samples')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.panel.add_requested.connect(lambda paths: self.accept())

    def __getattr__(self, name):
        # The panel owns the controls and behaviour; callers keep the earlier names.
        panel = self.__dict__.get('panel')
        if panel is None:
            raise AttributeError(name)
        return getattr(panel, name)

    def inspect(self):
        path = self.panel.current_path()
        config = self.config
        def work(job):
            from .audio import pitch_text
            from .desktop_audio import audio_operation
            with audio_operation(cancel_event=job.cancel_event):
                return pitch_text(path, config.cache / 'pitch'), waveform_png(path, config.cache)
        def done(result):
            if not self.panel.closed and self.panel.listing.currentIndex().isValid() and self.panel.current_path() == path:
                self.panel.status.setText(result[0])
                self.waveform.setPixmap(QtGui.QPixmap(str(result[1])))
        self.studio.start_job(work, done)
        if self.studio.job is not None:
            self.studio.job.kind = 'library-analysis'

    def done(self, result):
        self.panel.shutdown()
        super().done(result)
