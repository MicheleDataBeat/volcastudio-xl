"""System-MIDI triggered, CRC-checked DataBeat OS audio pattern backups.

The original Volca's MIDI IN cannot return data. DataBeat OS emits its complete
bank through the headphone output instead; recording requires an explicitly
selected PC audio input and MIDI port. Nothing is saved from a partial capture.
"""
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .pattern_audio import AudioPatternDecoder, request_audio_backup
from .patterns import Pattern, SLOT_COUNT, save_bank
from .transfer import checked, device_lock, portable_audio
from . import desktop_audio

AUDIO_RATE = 48000
MIDI_STOP = b'\xfc'
MAX_CAPTURE_SECONDS = 180


def _required(tool):
    if not shutil.which(tool):
        raise ValueError(f'Missing dependency: {tool}')


def list_midi_ports():
    """Return ALSA's raw MIDI table; do not choose or open a default port."""
    _required('amidi')
    return checked(['amidi', '-l'], capture_output=True, text=True).stdout


def list_audio_inputs():
    """Return PipeWire input nodes with their IDs and selection names."""
    _required('pw-cli')
    nodes = checked(['pw-cli', 'ls', 'Node'], capture_output=True, text=True).stdout
    selected = []
    block = []
    for line in nodes.splitlines():
        if line.lstrip().startswith('id ') and block:
            if any('media.class' in item and 'Audio/Source' in item for item in block):
                selected.extend(block)
            block = []
        block.append(line)
    if any('media.class' in item and 'Audio/Source' in item for item in block):
        selected.extend(block)
    return '\n'.join(selected) + ('\n' if selected else '')


def _stop_process(proc):
    """Terminate only this operation's process group, including child helpers."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def _send_midi(port, message, directory, timeout=5):
    """Send a small raw message with bounded waiting and owned-child cleanup."""
    message_file = directory / ('midi-' + message.hex() + '.syx')
    message_file.write_bytes(message)
    args = ['amidi', '--port', port, '--send', str(message_file)]
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, start_new_session=True)
    try:
        _, error = proc.communicate(timeout=timeout)
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args, stderr=error)
    finally:
        try:
            _stop_process(proc)
        finally:
            if proc.stderr is not None:
                proc.stderr.close()


def _valid_frames(frames):
    frames = tuple(frames)
    if len(frames) != SLOT_COUNT + 1 or {frame.slot for frame in frames} != {*range(SLOT_COUNT), None}:
        raise ValueError('Audio backup must contain all ten stored patterns and the current edit buffer')
    if len({frame.session for frame in frames}) != 1:
        raise ValueError('Audio backup mixes separate device sessions')
    return [Pattern(frame.slot, frame.data) for frame in frames]


def send_current(port, pattern, firmware='lumon-xl'):
    """Load a current edit buffer through MIDI IN; this writes no stored slot."""
    from .patterns import encode_sysex
    if not isinstance(port, str) or not port.strip():
        raise ValueError('Explicitly select a raw MIDI output port')
    if not isinstance(pattern, Pattern) or pattern.slot is not None or not pattern.initialized:
        raise ValueError('Choose a valid current edit-buffer pattern')
    from .pattern_format import for_firmware
    message = encode_sysex(for_firmware(pattern, firmware))
    if portable_audio():
        return desktop_audio.send_midi(port, message)
    _required('amidi')
    with tempfile.TemporaryDirectory(prefix='volcastudio-pattern-current-') as tmp:
        _send_midi(port, message, Path(tmp))


def backup_audio(config, port, input, targetfile, timeout=MAX_CAPTURE_SECONDS, progress_callback=None):
    """Capture a complete DataBeat OS bank, then publish its full bytes atomically.

    The trigger sends MIDI Stop before the read-only backup request. A failure
    or interruption stops capture first and sends Stop again to abort the dump.
    Only mocks/generated audio may be used to test this on development systems.
    """
    if portable_audio(input):
        return desktop_audio.backup(config, port, input, targetfile, timeout, progress_callback)
    for value, label in ((port, 'raw MIDI port'), (input, 'PipeWire audio input')):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'Explicitly select a {label}')
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_CAPTURE_SECONDS:
        raise ValueError(f'Capture timeout must be greater than zero and at most {MAX_CAPTURE_SECONDS} seconds')
    targetfile = Path(targetfile).expanduser()
    if os.path.lexists(targetfile):
        raise FileExistsError(f'Pattern backup destination already exists: {targetfile}')
    for tool in ('amidi', 'pw-record'):
        _required(tool)
    with device_lock(config.state), tempfile.TemporaryDirectory(prefix='volcastudio-pattern-backup-') as tmp:
        directory = Path(tmp)
        capture = directory / 'capture.raw'
        decoder = AudioPatternDecoder(rate=AUDIO_RATE)
        proc = None
        midi_started = False
        completed = False
        deadline = time.monotonic() + timeout

        def capture_error(message):
            detail = (directory / 'capture.log').read_text(errors='replace').strip()[-2048:]
            return RuntimeError(f'{message}: {detail}' if detail else message)

        try:
            with (directory / 'capture.log').open('wb') as errors:
                proc = subprocess.Popen(['pw-record', '--raw', '--format=s16',
                                         '--rate=48000', '--channels=1', '--target',
                                         input, str(capture)], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=errors,
                                        start_new_session=True)
                # Give the explicitly selected input time to link before asking
                # the firmware to emit the first framing tone.
                time.sleep(min(.5, timeout))
                while not capture.exists():
                    if proc.poll() is not None:
                        raise capture_error('Audio capture stopped before recording began')
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Timed out starting the audio capture')
                    time.sleep(.02)
                if proc.poll() is not None:
                    raise capture_error('Audio capture stopped before the backup request')
                midi_started = True
                for message in (MIDI_STOP, request_audio_backup()):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Timed out before the audio backup request')
                    _send_midi(port, message, directory, timeout=min(5, remaining))
                with capture.open('rb') as recorded:
                    while not decoder.complete:
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Timed out waiting for all 11 CRC-valid audio pattern frames')
                        chunk = recorded.read(65536)
                        if chunk:
                            received = decoder.feed(chunk)
                            if received and progress_callback is not None:
                                progress_callback(len(decoder.frames), SLOT_COUNT + 1)
                        elif proc.poll() is not None:
                            raise capture_error('Audio capture ended before a complete pattern bank was received')
                        else:
                            time.sleep(.02)
                patterns = _valid_frames(decoder.finish())
                completed = True
        finally:
            if proc is not None:
                _stop_process(proc)
            if midi_started and not completed:
                try:
                    _send_midi(port, MIDI_STOP, directory, timeout=2)
                except Exception:
                    pass  # preserve the original capture/decoder error
        return save_bank(targetfile, patterns)
