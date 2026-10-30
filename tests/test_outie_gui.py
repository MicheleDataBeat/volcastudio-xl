"""Optional offscreen Qt smoke: never queries or opens actual audio devices."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'
import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

QT_AVAILABLE = importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(QT_AVAILABLE, 'Optional Desktop App dependencies are not installed')
class OutieGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_save_controls_are_visible_without_scrolling(self):
        from PySide6 import QtCore, QtWidgets
        from volcastudio.config import Config
        from volcastudio.outie import Studio, STYLE
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp).resolve()
            self.app.setStyleSheet(STYLE)
            window = Studio(Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'), discover_devices=False)
            try:
                window.show()
                for size in ((800, 600), (1120, 820)):
                    window.resize(*size)
                    self.app.processEvents()
                    viewport = window.tabs.widget(0).viewport()
                    buttons = {b.text(): b for b in window.findChildren(QtWidgets.QPushButton)}
                    for text in ('Save independent kit', 'Save changes', 'Manage kits…', 'Recover draft…'):
                        button = buttons[text]
                        rect = QtCore.QRect(button.mapTo(viewport, QtCore.QPoint()), button.size())
                        self.assertTrue(viewport.rect().contains(rect), (size, text, rect, viewport.rect()))
            finally:
                window.close()

    def test_samples_page_fits_a_small_screen_and_keeps_the_list_usable(self):
        from PySide6 import QtGui, QtWidgets
        from volcastudio.config import Config
        from volcastudio.outie import Studio, STYLE
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp).resolve()
            self.app.setStyleSheet(STYLE)
            window = Studio(Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'), discover_devices=False)
            try:
                available = QtGui.QGuiApplication.primaryScreen().availableGeometry()
                self.assertLessEqual(window.width(), max(640, available.width() - 48))
                self.assertLessEqual(window.height(), max(480, available.height() - 64))
                self.assertEqual((window.minimumWidth(), window.minimumHeight()), (640, 480))
                window.show()
                # The second pass uses a much wider font, as Windows renders it, so the rows must wrap.
                for font_size in (13, 20):
                    self.app.setStyleSheet(STYLE + f'\nQWidget {{ font-size: {font_size}px; }}')
                    for size, min_list_height in (((800, 600), 96), ((640, 480), 96)):
                        window.resize(*size)
                        self.app.processEvents()
                        page = window.tabs.widget(0)
                        inner = page.widget()
                        layout = inner.layout()
                        widths = sorted(((layout.itemAt(i).minimumSize().width(),
                                          (layout.itemAt(i).widget().__class__.__name__ + ' ' + getattr(layout.itemAt(i).widget(), 'text', lambda: '')()[:30])
                                          if layout.itemAt(i).widget() else layout.itemAt(i).layout().__class__.__name__ + ' ' + ', '.join(
                                              (layout.itemAt(i).layout().itemAt(j).widget().__class__.__name__ + ':' + str(layout.itemAt(i).layout().itemAt(j).minimumSize().width()))
                                              for j in range(layout.itemAt(i).layout().count()) if layout.itemAt(i).layout().itemAt(j).widget()))
                                         for i in range(layout.count())), reverse=True)
                        # Rows wrap instead of needing horizontal scrolling; the list keeps room.
                        self.assertEqual(page.horizontalScrollBar().maximum(), 0,
                                         (font_size, size, page.viewport().width(), inner.minimumSizeHint().width(), widths[:4]))
                        self.assertGreaterEqual(window.sample_list.height(), min_list_height, (font_size, size))
                        buttons = {b.text(): b for b in window.findChildren(QtWidgets.QPushButton)}
                        self.assertLessEqual(buttons['Save independent kit'].height(), 34 if font_size == 13 else 48, size)
            finally:
                self.app.setStyleSheet(STYLE)
                window.close()

    def test_output_labels_keep_device_names_for_preferences(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.outie_state import save_preferences, load_preferences
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            config.initialize()
            save_preferences(config, {'output': 'pipewire'})
            listing = [dict(name='pipewire', label='System audio via PipeWire (pipewire)', id='sd:14'),
                       dict(name='HDA Intel PCH: ALC233 Analog (hw:0,0)', label='HDA Intel PCH: ALC233 Analog (hw:0,0) — direct hardware, exclusive', id='sd:0')]
            with patch('volcastudio.desktop_audio.output_devices', return_value=listing):
                window = Studio(config, discover_devices=False)
                try:
                    window.refresh_outputs()
                    self.assertEqual(window.outputs.currentData(), 'sd:14')
                    self.assertEqual(window.outputs.currentText(), 'System audio via PipeWire (pipewire)')
                    window.outputs.setCurrentIndex(window.outputs.findData('sd:0'))
                    window.remember_device('output', window.outputs)
                    self.assertEqual(load_preferences(config)['output'], 'HDA Intel PCH: ALC233 Analog (hw:0,0)')
                    window.refresh_outputs()
                    self.assertEqual(window.outputs.currentData(), 'sd:0')
                finally:
                    window.close()

    def test_sigterm_closes_the_window_after_cancelling_a_running_operation(self):
        import signal
        from PySide6 import QtCore
        from volcastudio.config import Config
        from volcastudio.outie import Studio, graceful_termination, Job
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            window = Studio(Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'), discover_devices=False)
            previous = {name: signal.getsignal(getattr(signal, name)) for name in ('SIGTERM', 'SIGINT')}
            try:
                window.show()
                request = graceful_termination(window, interval=20)
                stop = threading.Event()
                window.start_job(lambda job: stop.wait(5) or 'done')  # a running operation
                # Call the installed handler directly: on Windows os.kill(SIGTERM) would
                # terminate the test process itself instead of delivering a signal.
                request(signal.SIGTERM, None)
                deadline = QtCore.QElapsedTimer()
                deadline.start()
                while window.job is not None and deadline.elapsed() < 5000:
                    self.app.processEvents()
                    QtCore.QThread.msleep(5)
                    if window.job is not None and window.job.cancel_event.is_set():
                        stop.set()  # the operation honours the cancellation requested by the handler
                self.assertIsNone(window.job)
                while window.isVisible() and deadline.elapsed() < 5000:
                    self.app.processEvents()
                    QtCore.QThread.msleep(5)
                self.assertFalse(window.isVisible())  # closed through closeEvent, draft saved
            finally:
                for name, handler in previous.items():
                    signal.signal(getattr(signal, name), handler)
                window.close()

    def test_failed_draft_is_preserved_when_starting_new_work(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.outie_state import save_draft, draft_path
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            save_draft(cfg,sources=[p/'offline-mount/sample.wav'],name='old-work')
            original=draft_path(cfg).read_bytes()
            window=Studio(cfg,discover_devices=False)
            try:
                self.assertTrue(window.unrecovered_draft)
                self.assertEqual(draft_path(cfg).read_bytes(),original)
                window.kit_name.setText('new-work')
                recovery=list((draft_path(cfg).parent/'recovery').glob('*.json'))
                self.assertEqual(len(recovery),1)
                self.assertEqual(recovery[0].read_bytes(),original)
            finally: window.close()

    def test_dirty_draft_refuses_samples_changed_by_another_edition(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.outie_model import save_ordered_kit, open_ordered_kit
        from volcastudio.outie_state import draft_path
        from volcastudio.wmc.verify import tone
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            kit=save_ordered_kit(cfg,'shared-kit',[tone(p/'tone.wav',220,seconds=.03)])
            window=Studio(cfg,discover_devices=False)
            window.set_opened_kit(*open_ordered_kit(cfg,kit))
            window.render_samples()
            window.close()
            before=draft_path(cfg).read_bytes()
            (kit/'other-edition.txt').write_text('Changed elsewhere')
            reopened=Studio(cfg,discover_devices=False)
            try:
                self.assertTrue(reopened.unrecovered_draft)
                self.assertEqual(reopened.samples,[])
                self.assertEqual(draft_path(cfg).read_bytes(),before)
                self.assertIn('changed in another edition',reopened.log.toPlainText())
            finally: reopened.close()

    def test_device_names_persist_but_disconnected_output_never_falls_back(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            first=Studio(cfg,discover_devices=False)
            first.outputs.addItem('Chosen interface','sd:9')
            first.outputs.setCurrentIndex(1)
            first.outputs.activated.emit(1)
            first.close()
            second=Studio(cfg,discover_devices=False)
            try:
                with patch('volcastudio.desktop_audio.output_devices',return_value=[dict(name='Different interface',id='sd:9')]):
                    second.refresh_outputs()
                self.assertIsNone(second.outputs.currentData())
                self.assertIn('Unavailable',second.outputs.currentText())
                with patch('volcastudio.desktop_audio.output_devices',return_value=[dict(name='Chosen interface',id='sd:4')]):
                    second.refresh_outputs()
                self.assertEqual(second.outputs.currentData(),'sd:4')
            finally: second.close()

    def test_pattern_buttons_reach_shared_actions_without_devices(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QPushButton
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.patterns import blank_pattern
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            window=Studio(cfg,discover_devices=False)
            try:
                window.bank=[blank_pattern('lumon-xl-internal',2),blank_pattern('lumon-xl-internal')]
                buttons={b.text():b for b in window.findChildren(QPushButton)}
                def invoke(operation): return operation(SimpleNamespace(confirm=lambda _:False),'sd:99')
                with patch.object(window,'device_job',side_effect=invoke), patch('volcastudio.outie_pattern_actions.transfer_patterns') as transfer, patch('PySide6.QtWidgets.QInputDialog.getItem',return_value=('10',True)):
                    buttons['Restore current snapshot…'].click()
                    self.assertEqual(transfer.call_args.kwargs['destination'],9)
                    self.assertEqual(transfer.call_args.args[0],[window.bank[1]])
                window.pattern_slots.setText('2,5')
                window.backup_midi.addItem('Fixture MIDI','fixture:port')
                with patch.object(window,'device_job',side_effect=invoke), patch('volcastudio.outie_pattern_actions.transfer_patterns') as transfer:
                    buttons['Reset memories + current buffer…'].click()
                    self.assertEqual([x.slot for x in transfer.call_args.args[0]],[1,4])
                    self.assertEqual(transfer.call_args.kwargs['midi_port'],'fixture:port')
                    self.assertIsNone(transfer.call_args.kwargs['current_pattern'].slot)
            finally: window.close()

    def test_replacing_preview_is_nonmodal_but_real_errors_are_reported(self):
        from volcastudio.outie import Job
        from volcastudio.desktop_audio import TransferCancelled
        def cancelled(job):
            job.cancel_event.set()
            raise TransferCancelled('Transfer cancelled; device receipt is unknown')
        job=Job(cancelled)
        job.kind='preview'
        failed,notices=[],[]
        job.failed.connect(failed.append)
        job.notice.connect(notices.append)
        job.run()
        self.assertEqual(failed,[])
        self.assertEqual(notices,['Preview stopped.'])
        def broken(job): raise OSError('fixture read failure')
        job=Job(broken)
        job.kind='preview'
        job.failed.connect(failed.append)
        job.run()
        self.assertEqual(failed,['fixture read failure'])

    def test_close_does_not_silently_discard_a_draft_after_disk_failure(self):
        from PySide6.QtWidgets import QMessageBox
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.wmc.verify import tone
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            window=Studio(cfg,discover_devices=False)
            window.show()
            try:
                window.samples=[tone(p/'tone.wav',220,seconds=.03)]
                with patch('volcastudio.outie_state.save_draft',side_effect=OSError('fixture disk full')), patch.object(window,'error') as error:
                    window.render_samples()
                self.assertTrue(window.draft_write_failed)
                error.assert_called_once()
                with patch('PySide6.QtWidgets.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel) as question:
                    window.close()
                self.assertTrue(window.isVisible())
                self.assertEqual(question.call_args.args[-1],QMessageBox.StandardButton.Cancel)
            finally:
                window.draft_write_failed=False
                window.close()

    def test_real_save_button_and_draft_survive_reopening_the_window(self):
        import time
        from PySide6.QtWidgets import QPushButton, QMessageBox
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.wmc.verify import tone
        from volcastudio.transfer import pack_files
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp).resolve()
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            sources = [tone(p/'first.wav', 220, seconds=.03), tone(p/'second.wav', 440, seconds=.03)]
            original = [s.read_bytes() for s in sources]
            def window():
                return Studio(config, discover_devices=False)
            def wait(w):
                deadline = time.monotonic()+10
                while w.job is not None and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.01)
                self.assertIsNone(w.job)
            with patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('No device access')):
                first = window()
                first.samples = list(sources)
                first.render_samples()
                first.kit_name.setText('my-kit')
                first.close()
                second = window()
                try:
                    self.assertEqual(second.samples, sources)
                    self.assertEqual(second.kit_name.text(), 'my-kit')
                    button = next(b for b in second.findChildren(QPushButton) if b.text()=='Save independent kit')
                    with patch.object(second, 'error', side_effect=AssertionError):
                        button.click()
                        wait(second)
                    self.assertEqual(second.saved_kit, config.kits/'my-kit')
                finally:
                    second.close()
                third = window()
                try:
                    self.assertEqual(third.saved_kit, config.kits/'my-kit')
                    self.assertEqual([x.read_bytes() for x in third.samples], original)
                    third.sample_list.setCurrentRow(0)
                    third.move_sample(1)
                finally:
                    third.close()
                fourth = window()
                try:
                    self.assertIsNone(fourth.saved_kit)
                    self.assertEqual(fourth.opened_kit, config.kits/'my-kit')
                    self.assertEqual([x.read_bytes() for x in fourth.samples], original[::-1])
                    with patch.object(fourth, 'error', side_effect=AssertionError), patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                        fourth.save_changes_button.click()
                        wait(fourth)
                    self.assertEqual([x.read_bytes() for x in pack_files(config.kits/'my-kit')[1]], original[::-1])
                    self.assertEqual(len(list((config.data/'trash').glob('*/kit'))), 1)
                    self.assertEqual([x.read_bytes() for x in sources], original)
                finally:
                    fourth.close()

    def test_open_saved_kit_send_edit_and_save_without_a_duplicate(self):
        import time
        from types import SimpleNamespace
        from PySide6.QtWidgets import QPushButton, QMessageBox
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.outie_model import save_ordered_kit
        from volcastudio.wmc.verify import tone
        from volcastudio.transfer import pack_files
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = Config(root/'config', root/'data', root/'state', root/'cache', root/'packs', root/'syro')
            sources = [tone(root/'first.wav', 220, seconds=.03), tone(root/'second.wav', 440, seconds=.03)]
            kit = save_ordered_kit(config, 'existing-kit', sources)
            original = {p.name: p.read_bytes() for p in kit.iterdir() if p.is_file()}
            with patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('No audio access allowed')):
                window = Studio(config, discover_devices=False)
                try:
                    buttons = {b.text(): b for b in window.findChildren(QPushButton)}
                    self.assertIn('Open saved kit…', buttons)
                    with patch('PySide6.QtWidgets.QFileDialog.getExistingDirectory', return_value=str(kit)):
                        buttons['Open saved kit…'].click()
                    self.assertEqual(window.saved_kit, kit)
                    self.assertEqual(tuple(window.samples), tuple(pack_files(kit)[1]))
                    self.assertTrue(window.send_kit_button.isEnabled())
                    self.assertFalse(window.save_changes_button.isEnabled())
                    with patch('PySide6.QtWidgets.QFileDialog.getOpenFileNames', return_value=([], '')):
                        window.add_samples()
                    self.assertEqual(window.saved_kit, kit)
                    with patch.object(window, 'device_job', side_effect=lambda op: op(SimpleNamespace(confirm=lambda _: False), 'sd:0')), \
                         patch('volcastudio.transfer.transfer') as send:
                        window.send_kit()
                        self.assertEqual(send.call_args.args[:2], (kit, config))
                        self.assertEqual(send.call_args.kwargs['expected_fingerprint'], window.kit_fingerprint)
                    window.sample_list.setCurrentRow(0)
                    window.move_sample(1)
                    self.assertIsNone(window.saved_kit)
                    self.assertFalse(window.send_kit_button.isEnabled())
                    self.assertTrue(window.save_changes_button.isEnabled())
                    with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
                        window.new_kit()
                    self.assertEqual(window.samples[0].read_bytes(), sources[1].read_bytes())
                    with self.assertRaises(ValueError), patch.object(window, 'device_job') as send:
                        window.send_kit()
                    send.assert_not_called()
                    with patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
                         patch.object(window, 'error', side_effect=AssertionError):
                        buttons['Save changes'].click()
                        deadline = time.monotonic() + 10
                        while window.job is not None and time.monotonic() < deadline:
                            self.app.processEvents()
                            time.sleep(.01)
                        self.assertIsNone(window.job)
                    self.assertEqual(window.saved_kit, kit)
                    self.assertTrue(window.send_kit_button.isEnabled())
                    self.assertEqual([p.name for p in config.kits.iterdir()], ['existing-kit'])
                    saved = pack_files(kit)[1]
                    self.assertEqual(saved[0].read_bytes(), sources[1].read_bytes())
                    self.assertEqual(saved[1].read_bytes(), sources[0].read_bytes())
                    archived = next((config.data/'trash').glob('*/kit'))
                    self.assertEqual({p.name:p.read_bytes() for p in archived.iterdir() if p.is_file()}, original)
                finally:
                    window.close()

    def test_saved_kit_check_is_offline_and_rejects_external_changes(self):
        import threading
        from types import SimpleNamespace
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.outie_model import open_ordered_kit, save_ordered_kit
        from volcastudio.wmc.verify import tone
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = Config(root/'config', root/'data', root/'state', root/'cache', root/'packs', root/'syro')
            kit = save_ordered_kit(config, 'existing-kit', [tone(root/'sample.wav', 440, seconds=.03)])
            with patch('volcastudio.desktop_audio._backend', side_effect=AssertionError('No audio access allowed')):
                window = Studio(config, discover_devices=False)
                try:
                    window.set_opened_kit(*open_ordered_kit(config, kit))
                    results = []
                    def run(operation):
                        results.append(operation(SimpleNamespace(cancel_event=threading.Event())))
                    with patch.object(window, 'start_job', side_effect=run), \
                         patch('volcastudio.transfer.prepare', return_value={'count': 1}) as prepare:
                        window.prepare_kit()
                        self.assertEqual(prepare.call_args.args[0], kit)
                        self.assertIn('101 signals offline', results[0])
                    def changed(*args):
                        (kit/'changed.txt').write_text('Concurrent edit')
                        return {'count': 1}
                    with patch.object(window, 'start_job', side_effect=run), \
                         patch('volcastudio.transfer.prepare', side_effect=changed), \
                         self.assertRaisesRegex(ValueError, 'changed during preparation'):
                        window.prepare_kit()
                    with patch.object(window, 'device_job') as send, self.assertRaisesRegex(ValueError, 'changed outside the Desktop App'):
                        window.send_kit()
                    send.assert_not_called()
                    self.assertFalse(window.send_kit_button.isEnabled())
                finally:
                    window.close()

    def test_groove_one_many_all_save_and_send_exact_selection(self):
        from types import SimpleNamespace
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.patterns import blank_pattern, load_bank
        from volcastudio.grooves import microtiming
        for reset in (False, True):
            for slots in ((2,), (0, 2, 4), tuple(range(10))):
                with self.subTest(reset=reset, slots=slots), tempfile.TemporaryDirectory() as tmp:
                    p = Path(tmp)
                    config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
                    window = Studio(config, discover_devices=False)
                    window.groove_firmware.setCurrentIndex(window.groove_firmware.findData('lumon-xl-internal'))
                    self.assertEqual(window.firmware_target.currentData(), 'lumon-xl-internal')
                    if not reset:
                        window.set_bank([blank_pattern('lumon-xl-internal', i) for i in range(10)])
                    window.reset_groove.setChecked(reset)
                    window.pattern_slots.setText('')
                    for slot in slots:
                        window.groove_memories[slot].setChecked(True)
                    self.assertEqual(tuple(i for i, c in enumerate(window.groove_memories) if c.isChecked()), slots)
                    template = next(t for t in window.catalog.templates if max(map(abs, t.microtiming)) > 7)
                    combo = window.groove_combos[0]
                    combo.setCurrentIndex(combo.findData(template.id))
                    output = p/'result.vspatterns'
                    self.assertFalse(window.send_groove_button.isEnabled())
                    with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(output), '')), \
                         patch('volcastudio.desktop_audio.play') as play:
                        window.save_grooves()
                        play.assert_not_called()
                    saved = load_bank(output)
                    self.assertEqual(tuple(item.slot for item in saved), slots)
                    self.assertTrue(all(microtiming(item, 1) == template.microtiming for item in saved))
                    self.assertTrue(window.send_groove_button.isEnabled())
                    with patch.object(window, 'device_job', side_effect=lambda op: op(SimpleNamespace(confirm=lambda _: False), 'sd:2')), \
                         patch('volcastudio.pattern_transfer.transfer_patterns') as send:
                        window.send_grooves()
                        self.assertEqual(send.call_args.args[:3], (tuple(saved), config, 'lumon-xl-internal'))
                        self.assertEqual(send.call_args.kwargs['target'], 'sd:2')
                        self.assertFalse(send.call_args.kwargs['confirm_callback']({}))
                    window.groove_memories[slots[0]].setChecked(False)
                    self.assertFalse(window.send_groove_button.isEnabled())
                    with self.assertRaises(ValueError):
                        window.send_grooves()
                    window.close()

    def test_groove_send_invalidates_changed_inputs_and_saved_file(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.patterns import blank_pattern, bank_to_json
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            window = Studio(Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'), discover_devices=False)
            window.reset_groove.setChecked(True)
            window.pattern_slots.setText('3')
            window.groove_combos[0].setCurrentIndex(1)
            for index, change in enumerate((
                lambda: window.groove_combos[0].setCurrentIndex(2),
                lambda: window.reset_groove.setChecked(False),
                lambda: window.pattern_slots.setText('2,3'),
                lambda: window.set_bank([blank_pattern('lumon-xl-internal', 2)]),
            )):
                output = p/f'result-{index}.vspatterns'
                with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(output), '')):
                    window.save_grooves()
                self.assertTrue(window.send_groove_button.isEnabled())
                change()
                self.assertFalse(window.send_groove_button.isEnabled())
                window.reset_groove.setChecked(True)
            output = p/'tampered.vspatterns'
            with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(output), '')):
                window.save_grooves()
            output.write_text(bank_to_json([blank_pattern('lumon-xl-internal', 1)]))
            with patch.object(window, 'device_job') as job, self.assertRaisesRegex(ValueError, 'changed'):
                window.send_grooves()
            job.assert_not_called()
            self.assertFalse(window.send_groove_button.isEnabled())
            window.close()

    def test_offline_startup_failure_returns_without_a_modal_dialog(self):
        import json
        from volcastudio.outie import main
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'failed-verification'
            with patch('sys.argv', ['desktop-app', '--verify-offline', str(output)]), \
                 patch('volcastudio.outie.Studio', side_effect=ValueError('Missing catalog')), \
                 patch('PySide6.QtWidgets.QMessageBox.critical') as dialog:
                self.assertEqual(main(), 1)
                dialog.assert_not_called()
            report = json.loads((output/'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertFalse(report['hardware_access'])
            self.assertIn('Missing catalog', report['error'])

    def test_small_window_keeps_groove_controls_readable(self):
        from PySide6.QtWidgets import QScrollArea
        from volcastudio.config import Config
        from volcastudio.outie import Studio, STYLE
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            window = Studio(config, discover_devices=False)
            window.setStyleSheet(STYLE)
            window.resize(800, 600)
            window.tabs.setCurrentIndex(2)
            window.show()
            self.app.processEvents()
            page = window.tabs.currentWidget()
            self.assertIsInstance(page, QScrollArea)
            for combo in window.groove_combos:
                self.assertGreaterEqual(combo.height(), combo.minimumSizeHint().height())
            page.ensureWidgetVisible(window.groove_combos[-1])
            self.app.processEvents()
            self.assertGreater(page.verticalScrollBar().maximum(), 0)
            window.close()

    def test_sections_offline_reset_and_no_playback(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            with patch('volcastudio.desktop_audio.output_devices', return_value=[]), patch('volcastudio.desktop_audio.play') as play:
                window = Studio(config)
                self.assertEqual(window.tabs.count(), 4)
                self.assertEqual(len(window.groove_combos), 10)
                self.assertEqual(window.firmware_target.count(), 1)
                self.assertTrue(window.firmware_target.isEnabled())
                self.assertEqual(window.firmware_target.currentData(), 'lumon-xl-internal')
                self.assertEqual((len(window.catalog.templates), len(window.catalog.profiles)), (270, 217))
                self.assertIsNone(window.outputs.currentData())
                window.pattern_slots.setText('2,4')
                window.reset_bank()
                self.assertEqual([p.slot for p in window.bank], [1, 3])
                self.assertTrue(all(p.initialized for p in window.bank))
                play.assert_not_called()
                window.close()

    def test_xl_groove_selection_save_and_preview(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.grooves import microtiming
        from volcastudio.patterns import load_bank
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            with patch('volcastudio.desktop_audio.output_devices', return_value=[]):
                window = Studio(config)
                window.firmware_target.setCurrentIndex(window.firmware_target.findData('lumon-xl-internal'))
                template = next(t for t in window.catalog.templates if max(map(abs, t.microtiming)) > 7)
                combo = window.groove_combos[0]
                combo.setCurrentIndex(combo.findData(template.id))
                self.assertIn('measured', window.groove_preview.text())
                window.reset_groove.setChecked(True)
                window.pattern_slots.setText('3')
                output = p / 'xl.vspatterns'
                with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName', return_value=(str(output), '')):
                    window.save_grooves()
                bank = load_bank(output)
                self.assertEqual([item.slot for item in bank], [2])
                self.assertEqual(microtiming(bank[0], 1), template.microtiming)
                window.close()

    def test_preview_uses_shared_device_lock(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio, Job
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            window = Studio(config, discover_devices=False)
            window.samples = [p/'sample.wav']
            window.sample_list.addItem('sample.wav')
            window.sample_list.setCurrentRow(0)
            window.outputs.addItem('Fixture only', 'sd:99')
            window.outputs.setCurrentIndex(1)
            with patch.object(window, 'start_job') as start:
                window.preview_sample()
                operation = start.call_args.args[0]
            with patch('volcastudio.transfer.device_lock') as lock, patch('volcastudio.transfer.normalize_sample'), patch('volcastudio.transfer.checked'), patch('volcastudio.desktop_audio.play') as play:
                operation(Job(lambda worker: None))
                lock.assert_called_once_with(config.state)
                lock.return_value.__enter__.assert_called_once()
                play.assert_called_once()
            window.close()

    def test_declined_confirmation_does_not_report_signals_sent(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio, Job
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            window = Studio(config, discover_devices=False)
            window.outputs.addItem('Fixture only', 'sd:99')
            window.outputs.setCurrentIndex(1)
            for returned in (0, {'phase': 'cancelled'}):
                with patch.object(window, 'start_job') as start:
                    window.device_job(lambda job, target: returned)
                    operation = start.call_args.args[0]
                result = operation(Job(lambda worker: None))
                self.assertIn('cancelled', result)
                self.assertNotIn('Signals sent', result)
            window.close()

    def test_firmware_send_has_no_experimental_dialog_and_keeps_transfer_confirmation(self):
        from PySide6 import QtCore, QtWidgets as W
        from volcastudio.config import Config
        from volcastudio.outie import Studio, Job
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            window = Studio(config, discover_devices=False)
            self.assertFalse(hasattr(window, 'firmware_build_target'))
            item = W.QListWidgetItem('Experimental fixture')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, {'id': 'fixture', 'installable': True, 'experimental': True})
            window.firmware_list.addItem(item)
            window.firmware_list.setCurrentItem(item)
            with patch('PySide6.QtWidgets.QMessageBox.question') as question, patch.object(window, 'device_job') as device, \
                    patch('volcastudio.firmware.transfer_firmware') as transfer:
                window.send_firmware()
                question.assert_not_called()
                operation = device.call_args.args[0]
                worker = Job(lambda worker: None)
                operation(worker, 'sd:99')
                # No acceptance is offered: the backend refuses anything experimental.
                self.assertNotIn('allow_experimental', transfer.call_args.kwargs)
                self.assertEqual(transfer.call_args.kwargs['confirm_callback'], worker.confirm)
                self.assertFalse(worker.approved)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, {'id': 'offline', 'installable': False, 'experimental': False})
            with patch.object(window, 'device_job') as device, patch('PySide6.QtWidgets.QMessageBox.question') as question:
                with self.assertRaisesRegex(ValueError, 'offline'):
                    window.send_firmware()
                device.assert_not_called()
                question.assert_not_called()
            window.close()

    def test_firmware_page_builds_databeat_os_from_the_korg_updater(self):
        from PySide6 import QtWidgets
        from volcastudio import lumon_build
        from volcastudio.config import Config
        from volcastudio.outie import Studio, Job
        korg_wav, patch_document = lumon_build.synthetic_case()
        with tempfile.TemporaryDirectory() as tmp, lumon_build.override(patch_document):
            p = Path(tmp)
            source = p / 'synthetic.wav'
            source.write_bytes(korg_wav)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            window = Studio(config, discover_devices=False)
            window.refresh_firmware()
            self.assertEqual(window.firmware_list.count(), 0)
            self.assertIn('synthetic.zip', window.firmware_hint.text())
            labels = [b.text() for b in window.findChildren(QtWidgets.QPushButton)]
            self.assertIn('Add Korg 1.42 updater…', labels)
            self.assertFalse([label for label in labels if label.startswith('Import firmware') or label.startswith('Import DataBeat OS')])
            with patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=(str(source), '')) as dialog, \
                    patch.object(window, 'start_job') as start, patch.object(window, 'message') as message:
                window.add_korg_updater()
                self.assertIn('*.zip', dialog.call_args.args[3])
                work, done = start.call_args.args
                done(work(Job(lambda worker: None)))
            self.assertIn('Studio checked the result', message.call_args.args[0])
            shown = [window.firmware_list.item(i).text() for i in range(window.firmware_list.count())]
            self.assertEqual(len(shown), 2)
            self.assertTrue(shown[0].startswith('Synthetic OS') and shown[1].startswith('Korg volca sample'))
            self.assertTrue(window.firmware_hint.isHidden())
            window.close()

    def test_worker_reports_interrupted_operation(self):
        from volcastudio.outie import Job
        def interrupted(worker):
            raise KeyboardInterrupt('Transfer cancelled')
        job = Job(interrupted)
        notices = []
        job.failed.connect(notices.append)
        job.run()
        self.assertEqual(notices, ['Transfer cancelled'])

    def test_worker_cancellation_unblocks_confirmation(self):
        from volcastudio.outie import Job
        job = Job(lambda worker: None)
        job.cancel_event.set()
        self.assertFalse(job.confirm({'count': 10}))

    def test_varispeed_two_digit_prompt_sign_leading_zero_and_cancel(self):
        from PySide6 import QtCore, QtWidgets as W, QtTest
        from volcastudio.outie import semitone_prompt
        for direction, text, expected in ((-1, '07', -7), (1, '24', 24), (1, '123', 12)):
            def answer(text=text):
                dialog = W.QApplication.activeModalWidget()
                entry = dialog.findChild(W.QLineEdit)
                QtTest.QTest.keyClicks(entry, 'xyz')
                self.assertEqual(entry.text(), '')
                QtTest.QTest.keyClicks(entry, text)
                dialog.findChild(W.QDialogButtonBox).button(W.QDialogButtonBox.StandardButton.Ok).click()
            QtCore.QTimer.singleShot(0, answer)
            self.assertEqual(semitone_prompt(None, direction, 3), expected)
        QtCore.QTimer.singleShot(0, lambda: W.QApplication.activeModalWidget().reject())
        self.assertIsNone(semitone_prompt(None, -1))

    def test_varispeed_selected_samples_are_committed_only_after_complete_worker(self):
        from volcastudio.config import Config
        from volcastudio.outie import Studio, Job
        from PySide6 import QtWidgets as W
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            window = Studio(Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'), discover_devices=False)
            original = [p/'a.wav', p/'b.wav', p/'c.wav']
            window.samples = original.copy()
            for path in original:
                window.sample_list.addItem(path.name)
            window.sample_list.item(0).setSelected(True)
            window.sample_list.item(2).setSelected(True)
            with patch('volcastudio.outie.semitone_prompt', return_value=-7) as prompt, patch.object(window, 'start_job') as start:
                window.shift_samples(-1)
                prompt.assert_called_once_with(window, -1, 2)
            operation, done = start.call_args.args
            replacements = [p/'a_vs-7.wav', p/'c_vs-7.wav']
            with patch('volcastudio.tuning.varispeed', side_effect=replacements) as render:
                prepared = operation(Job(lambda worker: None))
            self.assertEqual(window.samples, original)
            self.assertEqual([call.args[0] for call in render.call_args_list], [original[0], original[2]])
            with patch('volcastudio.transfer.inspect_wav', return_value=1), patch('volcastudio.tuning.shift_label', return_value='-7'):
                done(prepared)
            self.assertEqual(window.samples, [replacements[0], original[1], replacements[1]])
            self.assertIn('[-7]', window.sample_list.item(0).text())
            self.assertEqual([item.row() for item in window.sample_list.selectedIndexes()], [0, 2])
            with patch('volcastudio.tuning.varispeed', side_effect=[replacements[0], ValueError('render failure')]):
                with self.assertRaisesRegex(ValueError, 'render failure'):
                    operation(Job(lambda worker: None))
            self.assertEqual(window.samples, [replacements[0], original[1], replacements[1]])
            window.close()

    def test_alignment_waits_for_align_and_analyzes_only_the_ticked_samples(self):
        from PySide6 import QtCore
        from volcastudio.config import Config
        from volcastudio.outie import AlignmentDialog, Job
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            dialog = AlignmentDialog([p/'master_C.wav', p/'slave_D.wav', p/'noise.wav'], config)
            # Opening analyzes nothing: no worker, no master, nothing ticked.
            self.assertIsNone(dialog.job)
            self.assertIsNone(dialog.master.currentData())
            self.assertEqual([dialog.table.item(i, 0).checkState() for i in range(3)], [QtCore.Qt.CheckState.Unchecked] * 3)
            self.assertEqual([combo.currentText() for combo in dialog.choices], ['Not analyzed'] * 3)
            self.assertFalse(dialog.accept_button.isEnabled())
            with patch.object(dialog, 'start_worker') as start:
                dialog.align()
                start.assert_not_called()
            self.assertIn('master', dialog.summary.text())
            dialog.master.setCurrentIndex(dialog.master.findData(0))
            with patch.object(dialog, 'start_worker') as start:
                dialog.align()
                start.assert_not_called()
            self.assertIn('Tick at least one sample', dialog.summary.text())
            for slot in (1, 2):
                dialog.table.item(slot, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            rows = [dict(slot=0, analyzed=True, selected=False, filename_pc=0, detected_pc=0, filename_note='C', detected_note='C4', label='+12', semitones=12, conflict=False, uncertain=False, note='C', final_note='C', final_semitones=12, shift=0, final_seconds=10),
                    dict(slot=1, analyzed=True, selected=True, filename_pc=2, detected_pc=4, filename_note='D', detected_note='E4', label='', semitones=0, conflict=True, uncertain=False, note=None, final_note=None, final_semitones=0, shift=0, final_seconds=10),
                    dict(slot=2, analyzed=True, selected=True, excluded=True, filename_pc=None, detected_pc=None, filename_note=None, detected_note=None, label='', semitones=0, conflict=False, uncertain=True, note=None, final_note=None, final_semitones=0, shift=0, final_seconds=10)]
            conflict = {'rows': rows, 'before_seconds': 30, 'seconds': 30, 'ready': False, 'over_budget': False, 'conflicts': [1], 'excluded': [2], 'choices': {}, 'overrides': {}}
            with patch.object(dialog, 'start_worker') as start, patch('volcastudio.tuning.alignment_plan', return_value=conflict) as plan, \
                    patch('volcastudio.tuning.apply_alignment') as render:
                dialog.align()
                result = start.call_args.args[0](Job(lambda worker: None))
            self.assertEqual(plan.call_args.args[1:3], (0, [1, 2]))
            self.assertFalse(plan.call_args.kwargs['analyze_unselected'])
            render.assert_not_called()
            dialog.show_result(result)
            dialog.set_controls_enabled(True)
            self.assertIsNone(dialog.aligned_paths)
            self.assertFalse(dialog.accept_button.isEnabled())
            self.assertIn('conflicting slots: 01', dialog.summary.text())
            self.assertIsNone(dialog.choices[1].currentData())
            dialog.choices[1].setCurrentIndex(dialog.choices[1].findData('filename'))
            dialog.table.selectRow(1)
            dialog.table.selectionModel().select(dialog.table.model().index(2, 0), QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
            dialog.batch_shift.setValue(-7)
            dialog.set_batch_shift(False)
            over = dict(conflict, ready=True, seconds=75, over_budget=True, conflicts=[])
            with patch.object(dialog, 'start_worker') as start, patch('volcastudio.tuning.alignment_plan', return_value=over) as plan, \
                    patch('volcastudio.tuning.apply_alignment') as render:
                dialog.align()
                result = start.call_args.args[0](Job(lambda worker: None))
            self.assertEqual(plan.call_args.args[3][1], 'filename')
            self.assertEqual(plan.call_args.args[4], {1: -7, 2: -7})
            render.assert_not_called()
            dialog.show_result(result)
            dialog.set_controls_enabled(True)
            self.assertFalse(dialog.accept_button.isEnabled())
            self.assertIn('75.00 / 65.00', dialog.summary.text())
            self.assertIn('excluded slots: 02', dialog.summary.text())
            dialog.accept()
            self.assertEqual(dialog.result(), 0)
            ready = dict(over, seconds=45, over_budget=False)
            outputs = [p/'master_C.wav', p/'slave_D_vs-7.wav', p/'noise.wav']
            with patch.object(dialog, 'start_worker') as start, patch('volcastudio.tuning.alignment_plan', return_value=ready), \
                    patch('volcastudio.tuning.apply_alignment', return_value=outputs) as render:
                dialog.align()
                result = start.call_args.args[0](Job(lambda worker: None))
            render.assert_called_once()
            dialog.show_result(result)
            dialog.set_controls_enabled(True)
            self.assertTrue(dialog.accept_button.isEnabled())
            self.assertEqual(dialog.aligned_paths, outputs)
            self.assertIn('Aligned 1 sample', dialog.summary.text())
            # Changing the selection discards the rendered result until Align runs again.
            dialog.table.item(2, 0).setCheckState(QtCore.Qt.CheckState.Unchecked)
            self.assertIsNone(dialog.aligned_paths)
            self.assertFalse(dialog.accept_button.isEnabled())
            dialog.accept()
            self.assertEqual(dialog.result(), 0)
            with patch.object(dialog, 'start_worker') as start, patch('volcastudio.tuning.alignment_plan', return_value=ready) as plan, \
                    patch('volcastudio.tuning.apply_alignment', return_value=outputs):
                dialog.align()
                result = start.call_args.args[0](Job(lambda worker: None))
            self.assertEqual(plan.call_args.args[2], [1])
            dialog.show_result(result)
            dialog.set_controls_enabled(True)
            dialog.accept()
            self.assertEqual(dialog.result(), 1)

    def test_alignment_table_keeps_long_sample_names_readable_in_small_windows(self):
        from PySide6 import QtCore
        from volcastudio.config import Config
        from volcastudio.outie import AlignmentDialog
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            names = [f'{i:02d}-{i:02d}_REX_Loops_88bpm_sixth_lo_06_Em-est_Scratch_Ah1_090_MagicM_2b_vs+5.wav' for i in range(12)]
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            dialog = AlignmentDialog([p/name for name in names], config)
            dialog.resize(800, 600)
            dialog.show()
            self.app.processEvents()
            try:
                needed = dialog.table.fontMetrics().horizontalAdvance(f'11  {names[-1]}')
                # The 0.9.3–0.9.5 stretch column shrank to 100 px here and showed only "02  …".
                self.assertGreaterEqual(dialog.table.columnWidth(0), min(needed + 40, 640))
                self.assertEqual(dialog.table.textElideMode(), QtCore.Qt.TextElideMode.ElideMiddle)
                self.assertEqual(dialog.table.item(3, 0).toolTip(), str(p/names[3]))
                self.assertGreater(dialog.table.horizontalScrollBar().maximum(), 0)  # other columns scroll instead
            finally:
                dialog.close()

    def test_alignment_runs_off_gui_thread_and_cancel_discards_result(self):
        from PySide6 import QtCore
        from volcastudio.config import Config
        from volcastudio.outie import AlignmentDialog
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            dialog = AlignmentDialog([p/'a.wav', p/'b.wav'], Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro'))
            observed = []
            started = threading.Event()
            def plan(*args, **kwargs):
                observed.append(QtCore.QThread.currentThread() is self.app.thread())
                started.set()
                QtCore.QThread.msleep(200)
                return {'rows': [], 'before_seconds': 0, 'seconds': 0, 'ready': False, 'over_budget': False, 'conflicts': [], 'excluded': []}
            dialog.master.setCurrentIndex(dialog.master.findData(0))
            dialog.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            deadline = QtCore.QElapsedTimer()
            deadline.start()
            with patch('volcastudio.tuning.alignment_plan', side_effect=plan), patch('volcastudio.tuning.apply_alignment') as render:
                dialog.align()
                self.assertIsNotNone(dialog.job)
                while not started.is_set() and deadline.elapsed() < 5000:
                    self.app.processEvents()
                    QtCore.QThread.msleep(1)
                dialog.reject()  # Cancel while the worker is still busy.
                while dialog.job is not None and deadline.elapsed() < 5000:
                    self.app.processEvents()
                    QtCore.QThread.msleep(1)
            self.assertIsNone(dialog.job)
            self.assertEqual(observed, [False])
            render.assert_not_called()
            self.assertIsNone(dialog.aligned_paths)
            self.assertIsNone(dialog.plan)
            self.assertEqual(dialog.result(), 0)

    def test_alignment_generated_audio_worker_accepts_effective_pitch_and_duration(self):
        import math
        import struct
        import wave
        import hashlib
        from PySide6 import QtCore
        from volcastudio.config import Config
        from volcastudio.outie import AlignmentDialog
        from volcastudio.tuning import varispeed, sample_shift
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            config = Config(p/'config', p/'data', p/'state', p/'cache', p/'packs', p/'syro')
            config.initialize()
            originals = [p/'master_A4.wav', p/'slave_C5.wav']
            for path, hz in zip(originals, (440, 440 * 2 ** (3/12))):
                with wave.open(str(path), 'wb') as wav:
                    wav.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
                    wav.writeframes(b''.join(struct.pack('<h', round(8000 * math.sin(2*math.pi*hz*i/32000))) for i in range(6400)))
            hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in originals]
            master = varispeed(originals[0], 12, p/'variants')
            dialog = AlignmentDialog([master, originals[1]], config)
            def wait_until(predicate):
                deadline = QtCore.QElapsedTimer()
                deadline.start()
                while not predicate() and deadline.elapsed() < 15000:
                    self.app.processEvents()
                    QtCore.QThread.msleep(1)
                self.assertTrue(predicate(), dialog.summary.text())
            dialog.master.setCurrentIndex(dialog.master.findData(0))
            dialog.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            dialog.align()
            wait_until(lambda: dialog.job is None)
            self.assertIsNotNone(dialog.aligned_paths, dialog.summary.text())
            self.assertTrue(dialog.plan['ready'], dialog.summary.text())
            self.assertEqual(dialog.plan['rows'][0]['semitones'], 12)
            self.assertEqual(dialog.plan['rows'][1]['shift'], -3)
            self.assertAlmostEqual(dialog.plan['before_seconds'], .3, delta=.001)
            self.assertGreater(dialog.plan['seconds'], dialog.plan['before_seconds'])
            self.assertTrue(dialog.accept_button.isEnabled())
            dialog.accept()
            self.assertEqual(dialog.result(), 1)
            self.assertEqual(sample_shift(dialog.aligned_paths[1]), -3)
            self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in originals], hashes)
