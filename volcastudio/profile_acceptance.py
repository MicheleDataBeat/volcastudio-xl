"""Native Desktop App acceptance of the single pattern format and firmware choice.

Isolated files and no devices. Real controls and saved files execute; the
firmware builder and the device workers are observed at their boundary.
firmware_check separately rebuilds the exact release from the optional
owner-supplied Korg input.
"""
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch


def verify_outie(window, app, output):
    from PySide6 import QtCore, QtWidgets as W
    from .patterns import FIRMWARE_LABELS, PATTERN_PROFILE, Pattern, blank_pattern, save_bank
    from .pattern_format import set_predictability
    from . import pattern_transfer

    output = Path(output)
    original_bank = (window.bank, window.bank_path, window.pattern_slots.text())
    errors, requests, build_calls = [], [], []

    def click(text, parent=window):
        choices = [b for b in parent.findChildren(W.QPushButton) if b.text() == text]
        if len(choices) != 1 or not choices[0].isEnabled():
            raise RuntimeError(f'Expected an enabled Desktop App control: {text}')
        choices[0].click()

    def wait_worker():
        until = time.monotonic() + 30
        while window.job is not None and time.monotonic() < until:
            app.processEvents()
            time.sleep(.005)
        if window.job is not None or errors:
            raise RuntimeError('Desktop App worker failed: ' + '; '.join(errors))

    profiles = [window.firmware_target.itemData(i) for i in range(window.firmware_target.count())]
    grooves = [window.groove_firmware.itemData(i) for i in range(window.groove_firmware.count())]
    labels = [window.firmware_target.itemText(i) for i in range(window.firmware_target.count())]
    if profiles != [PATTERN_PROFILE] or grooves != [PATTERN_PROFILE] or labels != [FIRMWARE_LABELS[PATTERN_PROFILE]]:
        raise RuntimeError(f'Unexpected pattern profiles: {labels} {profiles} {grooves}')
    texts = {b.text() for b in window.findChildren(W.QPushButton)}
    if 'Convert bank offline…' in texts or hasattr(window, 'firmware_build_target'):
        raise RuntimeError('A conversion or internal-build control is still offered')

    other = set_predictability(blank_pattern('lumon-xl', slot=0), 1, tuple(range(16)))
    public = blank_pattern(PATTERN_PROFILE, slot=1)
    current = Pattern(None, other.data)
    source = [other, public, current]
    source_path = save_bank(output / 'profile-ui-source.vspatterns', source)
    original_bytes = source_path.read_bytes()
    try:
        with patch.object(window, 'error', side_effect=lambda text: errors.append(str(text))):
            window.set_bank(source, source_path)
            click('Select compatible memories')
            assert window.pattern_slots.text() == '2'
            click('Create reset bank')
            assert len(window.bank) == 1 and window.bank[0].slot == 1 and window.bank[0].firmware == PATTERN_PROFILE
            window.set_bank(source, source_path)

            def observe_device(operation):
                operation(SimpleNamespace(confirm=lambda record: False), 'offline:no-device')
            with patch.object(window, 'device_job', side_effect=observe_device), \
                    patch.object(pattern_transfer, 'transfer_patterns', side_effect=lambda *a, **kw: requests.append((a, kw))):
                click('Restore selected memories…')
                assert requests[-1][0][2] == PATTERN_PROFILE
                assert [p.slot for p in requests[-1][0][0]] == [1]
                window.pattern_slots.setText('1')
                click('Restore selected memories…')
                assert len(requests) == 1 and errors
                errors.clear()
                # A current snapshot in another format is refused before any worker.
                with patch.object(W.QInputDialog, 'getItem', return_value=('5', True)):
                    click('Restore current snapshot…')
                assert len(requests) == 1 and errors
                errors.clear()
            assert source_path.read_bytes() == original_bytes

            # The single firmware choice: actual widgets and worker routing only.
            # No updater is played; real Korg reconstruction is a separate check.
            def built(path, config):
                build_calls.append('production')
                return [{'name': 'Production fixture'}]
            with patch.object(W.QFileDialog, 'getOpenFileName', return_value=('offline-fixture.zip', '')), \
                    patch('volcastudio.firmware.add_korg_updater', side_effect=built):
                click('Add Korg 1.42 updater…')
                wait_worker()
            assert build_calls == ['production']
            item = W.QListWidgetItem('Experimental fixture')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, {'id': 'fixture', 'installable': True, 'experimental': True})
            window.firmware_list.addItem(item)
            window.firmware_list.setCurrentItem(item)
            routed = []
            with patch.object(W.QMessageBox, 'question', side_effect=AssertionError('No experimental dialog')), \
                    patch.object(window, 'device_job', side_effect=lambda operation: routed.append(operation)):
                window.send_firmware()
            assert len(routed) == 1
            window.refresh_firmware()
            window.tabs.setCurrentIndex(1)
            window.grab().save(str(output / 'profile-patterns-controls.png'))
            return dict(
                passed=True, profiles=[FIRMWARE_LABELS[PATTERN_PROFILE]],
                actual_controls=['Installed destination firmware', 'Groove destination firmware',
                    'Select compatible memories', 'Create reset bank', 'Restore selected memories',
                    'Restore current snapshot', 'Add Korg 1.42 updater'],
                other_format_refused_before_worker=True, original_file_unchanged=True,
                no_conversion_control=True, no_internal_build_control=True,
                no_experimental_dialog=True, build_routes=build_calls,
                limits=['Firmware builder and transfer worker boundary observed with fixtures.',
                        'Native Qt controls and exclusive file save executed.',
                        'No device discovery, audio/MIDI playback, hardware receipt or firmware installation.'])
    finally:
        window.bank, window.bank_path = original_bank[:2]
        window.pattern_slots.setText(original_bank[2])
