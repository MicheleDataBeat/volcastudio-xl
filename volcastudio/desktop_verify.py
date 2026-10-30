"""Offline acceptance checks for source and frozen desktop distributions."""
import hashlib
import importlib.metadata
import json
import platform
import sys
import wave
from pathlib import Path


def verify(window, app, output):
    """Use only synthetic files and the window's isolated configuration."""
    from .config import ROOT
    from .grooves import apply_pattern, load_catalog, microtiming
    from .patterns import FIRMWARE_LABELS, PATTERN_PROFILE, blank_pattern, load_bank, save_bank
    from .pattern_transfer import prepare_patterns
    from .transfer import checked, converter, device_lock, normalize_sample, tool_path, verify_stream
    from . import __version__

    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'version': __version__, 'platform': platform.platform(),
              'machine': platform.machine(), 'python': sys.version,
              'frozen': bool(getattr(sys, 'frozen', False)),
              'hardware_access': False, 'checks': {}, 'passed': False}
    checks = report['checks']
    try:
        if not (ROOT / 'docs/tuning.md').is_file():
            raise RuntimeError('Missing bundled tuning guide')
        checks['tuning_guide_bundled'] = True
        report['dependencies'] = {name: importlib.metadata.version(name) for name in
                                  ('PySide6', 'sounddevice', 'mido', 'python-rtmidi')}
        if window.tabs.count() != 4:
            raise RuntimeError('Missing application section')
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            app.processEvents()
            if not window.grab().save(str(output / f'section-{index + 1}.png')):
                raise RuntimeError('Could not save window rendering')
        checks['four_sections_rendered'] = True
        # A native/frozen end-to-end sample path, through actual FFmpeg and the
        # alignment dialog. Synthetic material only; no device discovery.
        import array
        import math
        import time
        from .tuning import varispeed, sample_shift
        from .outie import AlignmentDialog
        from .outie_model import save_ordered_kit
        from .audio import detect_pitch
        tones = []
        for name, hz in (('master_A3', 220), ('slave_C4', 261.625565)):
            path = output / (name + '.wav')
            values = array.array('h', (round(20000 * math.sin(2 * math.pi * hz * i / 44100)) for i in range(13230)))
            if sys.byteorder != 'little':
                values.byteswap()
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(values.tobytes())
            tones.append(path)
        source_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in tones]
        # Exercise the actual save button and the draft restored by a new
        # desktop window. This is independent of the model-only encoder tests.
        from PySide6 import QtCore
        for width, height in ((800, 600), (1120, 820)):
            window.resize(width, height)
            window.tabs.setCurrentIndex(0)
            app.processEvents()
            viewport = window.tabs.widget(0).viewport()
            for button in (window.save_kit_button, window.save_changes_button):
                rect = QtCore.QRect(button.mapTo(viewport, QtCore.QPoint()), button.size())
                if not viewport.rect().contains(rect):
                    raise RuntimeError(f'Save control is hidden at {width}×{height}: {button.text()}')
            window.grab().save(str(output / f'save-controls-{width}.png'))
        window.samples = list(tones)
        window.render_samples()
        window.kit_name.setText('offline-ui-kit')
        errors = []
        original_error = window.error
        window.error = lambda text: errors.append(str(text))
        try:
            window.save_kit_button.click()
            deadline = time.monotonic() + 60
            timed_out = False
            while window.job is not None:
                app.processEvents()
                time.sleep(.01)
                if not timed_out and time.monotonic() > deadline:
                    window.cancel_job()
                    timed_out = True
            if errors or timed_out or window.saved_kit != window.config.kits/'offline-ui-kit':
                raise RuntimeError('Save kit button failed: ' + '; '.join(errors))
        finally:
            window.error = original_error
        from .outie import Studio
        reopened = Studio(window.config, discover_devices=False)
        try:
            if (reopened.saved_kit != window.saved_kit or
                    [hashlib.sha256(p.read_bytes()).hexdigest() for p in reopened.samples] != source_hashes):
                raise RuntimeError('Saved kit/draft did not survive reopening the desktop window')
        finally:
            reopened.close()
        checks['save_button_and_restart'] = {'actual_button_clicked': True,
            'controls_visible_at': ['800×600', '1120×820'], 'saved_audio_matches': True,
            'new_window_restores_saved_kit': True, 'hardware_access': False}
        from .outie_acceptance import verify_workflows
        checks['native_library_and_archive_workflows'] = verify_workflows(window, app, output)
        from .profile_acceptance import verify_outie
        checks['pattern_format_and_firmware_controls'] = verify_outie(window, app, output)
        master = varispeed(tones[0], 12, window.config.data / 'variants/varispeed')
        dialog = AlignmentDialog([master, tones[1]], window.config, window)
        dialog.show()
        app.processEvents()
        if dialog.job is not None or dialog.plan is not None or dialog.master.currentData() is not None:
            raise RuntimeError('Tonal alignment analyzed samples before Align selected was pressed')
        dialog.master.setCurrentIndex(dialog.master.findData(0))
        dialog.table.item(1, 0).setCheckState(QtCore.Qt.CheckState.Checked)
        dialog.align_button.click()
        deadline = time.monotonic() + 60
        while dialog.job or (dialog.plan is None and dialog.aligned_paths is None and 'not completed' not in dialog.summary.text()):
            app.processEvents()
            time.sleep(.01)
            if time.monotonic() > deadline:
                dialog.reject()
                raise RuntimeError('Tonal alignment did not complete')
        plan, aligned = dialog.plan, dialog.aligned_paths
        if not plan or aligned is None or not dialog.accept_button.isEnabled():
            raise RuntimeError('Tonal alignment did not render: ' + dialog.summary.text())
        if not plan['ready'] or plan['rows'][1]['shift'] != -3 or plan['rows'][0]['semitones'] != 12:
            raise RuntimeError('Prior varispeed was lost or counted twice in tonal alignment')
        dialog.grab().save(str(output / 'key-alignment.png'))
        dialog.reject()
        kit = save_ordered_kit(window.config, 'offline-aligned-kit', aligned)
        files = sorted(kit.glob('*.wav'))
        if ([sample_shift(p) for p in files] != [12, -3]
                or detect_pitch(files[1], window.config.cache / 'pitch')['note'] != 'A3'
                or [hashlib.sha256(p.read_bytes()).hexdigest() for p in tones] != source_hashes):
            raise RuntimeError('Aligned saved kit lost pitch, provenance or source integrity')
        window.samples = files
        window.render_samples()
        if '[+12]' not in window.sample_list.item(0).text() or '[-3]' not in window.sample_list.item(1).text():
            raise RuntimeError('Sample tuning did not reach the kit UI')
        checks['varispeed_alignment_saved_kit'] = {'master_semitones': 12, 'slave_semitones': -3,
            'slave_note': 'A3', 'seconds': plan['seconds'], 'source_audio_unchanged': True,
            'dialog_rendered': True, 'hardware_access': False}
        from .outie_model import open_ordered_kit
        window.set_opened_kit(*open_ordered_kit(window.config, kit))
        if not window.send_kit_button.isEnabled() or window.kit_for_transfer() != kit:
            raise RuntimeError('Reopened kit could not be sent without saving a duplicate')
        window.sample_list.setCurrentRow(0)
        window.move_sample(1)
        if window.send_kit_button.isEnabled() or not window.save_changes_button.isEnabled():
            raise RuntimeError('Edited kit was still available for sending before saving')
        save_ordered_kit(window.config, kit.name, window.samples,
                         edit=kit, expected=window.kit_fingerprint)
        window.set_opened_kit(*open_ordered_kit(window.config, kit))
        if ([sample_shift(p) for p in window.samples] != [-3, 12]
                or not list((window.config.data / 'trash').glob('*/kit'))):
            raise RuntimeError('Kit edit lost slot order, tuning or its previous version')
        errors = []
        original_error = window.error
        window.error = lambda text: errors.append(str(text))
        try:
            window.prepare_kit()
            deadline = time.monotonic() + 60
            timed_out = False
            while window.job is not None:
                app.processEvents()
                time.sleep(.01)
                if not timed_out and time.monotonic() > deadline:
                    window.cancel_job()
                    timed_out = True
            if timed_out:
                raise RuntimeError('Offline kit preparation did not complete')
            if errors or 'Checked 102 signals offline.' not in window.log.toPlainText():
                raise RuntimeError('Offline kit preparation failed: ' + '; '.join(errors))
        finally:
            window.error = original_error
        window.tabs.setCurrentIndex(0)
        app.processEvents()
        window.grab().save(str(output / 'saved-kit.png'))
        checks['saved_kit_open_edit_prepare'] = {'same_kit_updated': True,
            'previous_version_archived': True, 'slot_order_and_tuning_retained': True,
            'signals_checked_offline': 102, 'hardware_access': False}
        if ([window.firmware_target.itemData(i) for i in range(window.firmware_target.count())] != [PATTERN_PROFILE]
                or [window.groove_firmware.itemData(i) for i in range(window.groove_firmware.count())] != [PATTERN_PROFILE]):
            raise RuntimeError('Unexpected pattern firmware profile')
        checks['single_pattern_format_for_patterns_and_grooves'] = True

        for firmware in (PATTERN_PROFILE,):
            catalog = load_catalog(firmware=firmware)
            template = max(catalog.templates, key=lambda t: max(map(abs, t.microtiming)))
            if (len(catalog.templates), len(catalog.profiles)) != (270, 217):
                raise RuntimeError('Incomplete XL groove catalog')
            from .pattern_conversion import convert_pattern
            from .pattern_format import set_predictability, predictability, set_motion_value, motion_value
            source_pattern = set_predictability(blank_pattern('lumon-xl', 0), 1, tuple(range(16)))
            for param, value in ((3, 255), (0, 37), (5, 2), (1, 16)):
                source_pattern = set_motion_value(source_pattern, 1, 1, param, value)
            source_pattern, issues = convert_pattern(source_pattern, firmware)  # exact fixture in this format
            if issues:
                raise RuntimeError('Fixture conversion failed')
            pattern = apply_pattern(source_pattern, {1: template.id}, firmware=firmware)
            if predictability(pattern, 1) != predictability(source_pattern, 1) or any(motion_value(pattern, 1, 1, param) != value for param, value in ((3, 255), (0, 37), (5, 2), (1, 16))):
                raise RuntimeError('Groove application changed Predictability or recorded motion')
            bank = output / (firmware + '.vspatterns')
            save_bank(bank, [pattern])
            if load_bank(bank) != [pattern] or microtiming(pattern, 1) != template.microtiming:
                raise RuntimeError('Groove/bank round trip failed')
            try:
                save_bank(bank, [blank_pattern(firmware, 0)])
            except FileExistsError:
                pass
            else:
                raise RuntimeError('An existing bank was overwritten')
            checks['grooves'] = {'format': FIRMWARE_LABELS[firmware], 'profiles': len(catalog.profiles), 'aliases': len(catalog.templates),
                                'template': template.id, 'microtiming': template.microtiming}

        with device_lock(window.config.state):
            try:
                with device_lock(window.config.state):
                    raise RuntimeError('Concurrent device lock was accepted')
            except ValueError:
                pass
        with device_lock(window.config.state):
            checks['device_lock_exclusion_and_release'] = True

        for name in ('ffmpeg', 'ffprobe'):
            path = tool_path(name)
            if not path:
                raise RuntimeError(f'Missing {name}')
            result = checked([path, '-version'], capture_output=True)
            checks[name] = {'path': path, 'version': result.stdout.decode('utf-8', 'replace').splitlines()[0]}
        source = output / 'synthetic input.wav'
        with wave.open(str(source), 'wb') as wav:
            wav.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\0\0' * 4410)
        # Exercise the packaged firmware build and guards; dry_run only, no devices.
        from .firmware_check import self_check
        checks['firmware'] = self_check(window.config, output)
        window.refresh_firmware()
        shown = [window.firmware_list.item(i).text() for i in range(window.firmware_list.count())]
        from .firmware import list_firmware
        expected = len(list_firmware(window.config))
        if len(shown) != expected or window.firmware_hint.isHidden() != bool(expected):
            raise RuntimeError(f'The firmware page shows an unexpected firmware list: {shown}')
        checks['firmware']['firmware_page_list'] = shown
        normalized = output / 'synthetic normalized.wav'
        normalize_sample(source, normalized)
        with wave.open(str(normalized), 'rb') as wav:
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getnframes()) != (31250, 1, 2, 3125):
                raise RuntimeError('Sample normalization failed')
        syro = ROOT / 'build/syro'
        sample_signal = output / 'sample-signal.wav'
        checked([converter(syro), sample_signal, f's0:{normalized}'], capture_output=True)
        verify_stream(sample_signal)
        checks['sample_encoding'] = True
        manifest = prepare_patterns([pattern], output / 'pattern-signal', syro, PATTERN_PROFILE)
        if manifest['count'] != 1 or manifest['slots'] != [0]:
            raise RuntimeError('Pattern encoding failed')
        checks['pattern_encoding'] = True
        checks['groove_predictability_motion_preserved'] = True
        checks['converter_sha256'] = hashlib.sha256(converter(syro).read_bytes()).hexdigest()
        report['passed'] = True
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['passed'] else 1
