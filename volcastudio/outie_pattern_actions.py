"""Desktop App pattern actions using the shared, confirmed transfer backend.

Creating these actions does not discover devices. ``window.device_job`` owns
output selection, worker lifetime and cancellation; ``job.confirm`` remains
the final confirmation after offline encoding. Destinations are shown as 1–10
and passed to the backend as 0–9.
"""
from .outie_model import parse_slots
from .pattern_transfer import pattern_targets, transfer_patterns
from .patterns import blank_pattern


def _idle(window):
    if window.job is not None:
        raise ValueError('Wait for the current operation or cancel it first.')


def _choose_destination(window):
    from PySide6.QtWidgets import QInputDialog
    value, accepted = QInputDialog.getItem(
        window, 'Restore current snapshot to a memory',
        'Choose the stored memory to replace (1–10). The current snapshot in '
        'the bank will be stored there.',
        [str(n) for n in range(1, 11)], 0, False)
    if not accepted:
        return None
    if value not in {str(n) for n in range(1, 11)}:
        raise ValueError('Choose a pattern memory from 1 to 10.')
    return int(value) - 1


def _confirm(job, manifest, detail):
    # The Desktop App's confirmation dialog displays confirmation_text after
    # the memory list. Keep the backend's manifest unchanged for its record.
    return job.confirm(dict(manifest, confirmation_text='\n\n' + detail))


def restore_current_snapshot(window):
    """Store only the bank's current snapshot in an explicitly chosen memory."""
    _idle(window)
    if window.bank is None:
        raise ValueError('Open a pattern bank first.')
    snapshots = [pattern for pattern in window.bank if pattern.slot is None]
    if len(snapshots) != 1:
        raise ValueError('Choose a bank containing exactly one current edit-buffer snapshot.')
    destination = _choose_destination(window)
    if destination is None:
        return
    firmware = window.firmware_target.currentData()
    pattern_targets(snapshots, firmware, destination)  # validate before starting a worker
    snapshot = snapshots[0]
    detail = (f'Stored pattern memory {destination + 1} will be replaced by the '
              'current snapshot from this bank. This does not load the live '
              'edit buffer; select the restored memory on the Volca afterwards.')
    return window.device_job(lambda job, target: transfer_patterns(
        [snapshot], window.config, firmware, target,
        confirm_callback=lambda manifest: _confirm(job, manifest, detail),
        destination=destination))


def restore_neutral_patterns(window, *, reset_current=False):
    """Restore selected neutral memories, optionally resetting the live buffer.

    This is an explicit reset action, not restoration of arbitrary bank data.
    Only memories named in ``window.pattern_slots`` are cleared through SYNC IN.
    With reset_current=True, MIDI also replaces the unsaved current edit buffer
    with a neutral pattern, after the stored-memory signals. No MIDI request is
    used as a substitute for writing a stored pattern.
    """
    _idle(window)
    return _restore_neutral_patterns(window, parse_slots(window.pattern_slots.text()), reset_current)


def reset_all_patterns(window, *, reset_current=False):
    """Reset all ten memories, with an optional live-buffer MIDI reset."""
    _idle(window)
    return _restore_neutral_patterns(window, range(10), reset_current)


def _restore_neutral_patterns(window, slots, reset_current):
    firmware = window.firmware_target.currentData()
    patterns = [blank_pattern(firmware, slot) for slot in slots]
    pattern_targets(patterns, firmware)
    port = None
    current = None
    detail = ('The displayed stored pattern memories will be replaced by empty '
              'neutral patterns. Existing notes and motion in those memories '
              'will be lost.')
    if reset_current:
        port = window.backup_midi.currentData()
        if not isinstance(port, str) or not port.strip():
            raise ValueError('Select a MIDI output connected to the Volca MIDI IN before resetting the current edit buffer.')
        current = blank_pattern(firmware)
        detail += (' After the stored memories, MIDI will also replace the '
                   'current edit buffer with a neutral pattern. Unsaved edits '
                   'in that buffer will be lost.')
    else:
        detail += ' Afterwards, select a cleared memory on the Volca to replace the current edit buffer.'
    return window.device_job(lambda job, target: transfer_patterns(
        patterns, window.config, firmware, target,
        confirm_callback=lambda manifest: _confirm(job, manifest, detail),
        current_pattern=current, midi_port=port))


def _choose_recording(window):
    from PySide6.QtWidgets import QFileDialog
    return QFileDialog.getOpenFileName(
        window, 'Decode a recorded pattern backup', str(window.config.patterns),
        'Audio backup WAV (*.wav *.WAV)')[0]


def _choose_bank_destination(window, recording):
    from pathlib import Path
    from PySide6.QtWidgets import QFileDialog
    return QFileDialog.getSaveFileName(
        window, 'Save decoded bank as a new file',
        str(window.config.patterns / (Path(recording).stem + '.vspatterns')),
        'Pattern banks (*.vspatterns)')[0]


def decode_recorded_backup(window):
    """Decode an existing WAV offline; save and open only a complete bank.

    This does not request a new backup or stop the instrument. Decoder work
    finishes its current file before observing cancellation; a cancelled decode
    does not publish a bank. Existing destinations are never overwritten.
    """
    from pathlib import Path
    from .desktop_audio import audio_operation, check_cancelled
    from .pattern_audio import decode_wav
    from .pattern_device import _valid_frames
    from .patterns import save_bank

    _idle(window)
    recording = _choose_recording(window)
    if not recording:
        return
    destination = _choose_bank_destination(window, recording)
    if not destination:
        return
    recording, destination = Path(recording), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f'Pattern bank already exists: {destination}. Choose a new filename.')

    def work(job):
        with audio_operation(cancel_event=job.cancel_event):
            frames = decode_wav(recording)
            check_cancelled()
            patterns = _valid_frames(frames)
            check_cancelled()
            path = save_bank(destination, patterns)
        return path, patterns

    def done(result):
        path, patterns = result
        window.set_bank(patterns, path)
        window.message(f'Decoded and saved 10 pattern memories and the current snapshot: {path}. Nothing was sent.')

    return window.start_job(work, done)
