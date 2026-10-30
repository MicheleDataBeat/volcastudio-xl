"""Persistent pattern restoration with isolated, offline SYRO preparation.

Pattern destinations are numbered 0–9 internally. The installed native SYRO
converter's ``p`` argument numbers those same destinations 1–10. These signals
replace patterns only; sample clear/upload messages are never generated here.
"""
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .patterns import Pattern, SLOT_COUNT, FIRMWARE_FORMATS
from .status import message
from .pattern_format import for_firmware
from .transfer import checked, converter, device_lock, play_stream, syro_rate, verify_stream, audio_dependencies, portable_audio


def pattern_targets(patterns, firmware, destination=None):
    """Validate a bank and resolve an explicitly selected current-buffer slot."""
    if firmware not in FIRMWARE_FORMATS:
        raise ValueError('Unknown destination pattern format')
    if destination is not None and (type(destination) is not int or not 0 <= destination < SLOT_COUNT):
        raise ValueError('Pattern destination must be 0–9')
    patterns = list(patterns)
    if not 1 <= len(patterns) <= SLOT_COUNT + 1 or any(not isinstance(p, Pattern) for p in patterns):
        raise ValueError('Choose a nonempty bank of Volca Sample v1 patterns')
    if len({p.slot for p in patterns}) != len(patterns):
        raise ValueError('The bank contains duplicate pattern slots or current edit buffers')
    stored = any(p.slot is not None for p in patterns)
    targets = []
    for pattern in patterns:
        slot = pattern.slot
        if slot is None:
            if destination is None:
                if stored:
                    continue  # keep the snapshot in its bank; restore stored slots
                raise ValueError('The current edit buffer needs an explicit stored-pattern destination')
            slot = destination
        if pattern.firmware == 'unsupported':
            raise ValueError('This memory uses an unsupported pattern format; it is kept in the bank and not restored')
        if pattern.firmware != 'opaque':
            pattern = for_firmware(pattern, firmware)
        targets.append((slot, pattern))
    if destination is not None and not any(p.slot is None for p in patterns):
        raise ValueError('An explicit destination applies only to the current edit buffer')
    if len({slot for slot, _ in targets}) != len(targets):
        raise ValueError('The bank contains duplicate stored-pattern destinations')
    return sorted(targets, key=lambda item: item[0])


def prepare_patterns(patterns, output, home, firmware, destination=None):
    """Write complete raw patterns and all validated SYRO WAVs, without playback."""
    patterns = list(patterns)
    targets = pattern_targets(patterns, firmware, destination)
    binary = converter(home)
    output = Path(output).expanduser()
    output.mkdir()  # refuse to overwrite a previous prepared transfer
    try:
        records = []
        for slot, pattern in targets:
            raw = output / f'pattern-{slot:02d}.bin'
            raw.write_bytes(pattern.data)
            signal = output / f'pattern-{slot:02d}.wav'
            checked([binary, signal, f'p{slot + 1}:{raw}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            verify_stream(signal)
            records.append({'slot': slot, 'source_slot': pattern.slot,
                            'source_firmware': pattern.firmware,
                            'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                            'raw': raw.name, 'signal': signal.name})
        manifest = {'schema': 1, 'operation': 'stored_patterns', 'firmware': firmware,
                    'count': len(records), 'slots': [record['slot'] for record in records],
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'patterns': records,
                    'opaque_slots': [r['slot'] for r in records if r['source_firmware'] == 'opaque'],
                    'current_edit_buffer_saved_not_restored': destination is None and any(p.slot is None for p in patterns),
                    'hardware_receipt': 'unavailable: SYRO audio is one-way'}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise


def transfer_patterns(patterns, config, firmware, target=None,
                      confirm_callback=None, destination=None, current_pattern=None, midi_port=None):
    """Prepare under the device lock, then ask before replacing stored patterns."""
    if confirm_callback is None:
        raise ValueError('Stored-pattern replacement needs an explicit confirmation callback')
    if (current_pattern is None) != (midi_port is None):
        raise ValueError('A current-buffer reset requires both a pattern and a MIDI output port')
    if current_pattern is not None:
        if not isinstance(current_pattern, Pattern) or current_pattern.slot is not None or not current_pattern.initialized:
            raise ValueError('Choose a valid current edit-buffer pattern')
        if current_pattern.firmware == 'unsupported':
            raise ValueError('Current pattern format differs from destination firmware')
        current_pattern = for_firmware(current_pattern, firmware)
        if not isinstance(midi_port, str) or not midi_port.strip() or (not portable_audio(target) and not shutil.which('amidi')):
            raise ValueError('Select a raw MIDI output port and install amidi for current-buffer reset')
    # Reject an incompatible bank before opening an audio backend or device lock.
    patterns = list(patterns)
    pattern_targets(patterns, firmware, destination)
    audio_dependencies(target)
    with device_lock(config.state), tempfile.TemporaryDirectory(prefix='volcastudio-pattern-transfer-') as tmp:
        directory = Path(tmp) / 'prepared'
        manifest = prepare_patterns(patterns, directory, config.syro_dir,
                                    firmware, destination)
        manifest['current_buffer_reset_requested'] = current_pattern is not None
        if not confirm_callback(manifest):
            return 0
        record = dict(manifest, audio_target=target or 'default', slots_sent=[],
                      current_buffer_sent=False, midi_port=midi_port)

        def log(phase):
            record['phase'] = phase
            record['updated_at'] = datetime.now(timezone.utc).isoformat()
            pending = config.state / 'last-pattern-transfer.json.tmp'
            pending.write_text(json.dumps(record, indent=2) + '\n')
            pending.replace(config.state / 'last-pattern-transfer.json')

        try:
            log('starting')
            with syro_rate(target):
                log('sending_patterns')
                for pattern in manifest['patterns']:
                    play_stream(directory / pattern['signal'], target)
                    record['slots_sent'].append(pattern['slot'])
                    log('sending_patterns')
                    time.sleep(1)  # firmware must finish committing each slot
                if current_pattern is not None:
                    from .pattern_device import send_current
                    log('sending_current_buffer')
                    if firmware == 'lumon-xl':
                        send_current(midi_port, current_pattern)
                    else:
                        send_current(midi_port, current_pattern, firmware=firmware)
                    record['current_buffer_sent'] = True
            log('signals_sent')
            message('Pattern signals sent. Verify the memories on the Volca.')
        except BaseException as exc:
            record['error'] = str(exc) or type(exc).__name__
            log('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
    return 0
