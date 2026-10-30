"""Native desktop audio with explicit outputs and cooperative cancellation.

PortAudio is loaded only when requested. Development never opens a device.
The thread context keeps GUI cancellation out of unrelated CLI operations.
"""
import contextlib
import contextvars
import wave

_OPERATION = contextvars.ContextVar('studio_audio_operation', default=None)

# PortAudio's default ("high") output latency gives blocking writes only two
# periods on raw ALSA hardware devices; a Python thread then underruns even
# while writing silence. Transfers are not latency-sensitive, so request a
# generous buffer. PortAudio treats the value as a suggestion per host API.
OUTPUT_LATENCY = 0.5

class TransferCancelled(KeyboardInterrupt):
    """Cancellation is recorded as interruption, never successful transfer."""

@contextlib.contextmanager
def audio_operation(cancel_event=None, progress_callback=None):
    token = _OPERATION.set((cancel_event, progress_callback))
    try:
        check_cancelled()
        yield
    finally:
        _OPERATION.reset(token)

def active():
    return _OPERATION.get() is not None

def check_cancelled():
    op = _OPERATION.get()
    if op and op[0] is not None and op[0].is_set():
        raise TransferCancelled('Transfer cancelled; device receipt is unknown')

def report(message, current=0, total=0):
    check_cancelled()
    op = _OPERATION.get()
    if op and op[1]:
        op[1](message, current, total)

def _backend():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as exc:
        raise ValueError('Native audio needs sounddevice and PortAudio. Install the Desktop App dependencies.') from exc

TRANSFER_RATE = 44100


def _describe(index, device, apis):
    api = apis[device['hostapi']]['name'] if apis and 'hostapi' in device else ''
    name = device['name']
    rate = device.get('default_samplerate')
    if name in ('pipewire', 'pulse'):
        label, rank = f'System audio via PipeWire ({name})', 0
    elif name == 'default':
        label, rank = 'System default output (default)', 1
    elif '(hw:' in name:
        label, rank = f'{name} — direct hardware, exclusive', 2
    elif api.startswith('JACK'):
        label, rank = f'{name} — JACK/PipeWire graph', 3
    else:
        label, rank = name, 4
    return dict(id=f'sd:{index}', name=name, label=label, channels=int(device['max_output_channels']),
                hostapi=api, default_samplerate=rate, rank=rank,
                usable=rate is None or int(rate) == TRANSFER_RATE)


EXCLUSIVE_OUTPUTS_ENV = 'VOLCASTUDIO_EXCLUSIVE_OUTPUTS'


def shared_route(name):
    """An ALSA plugin that hands audio to the desktop sound server."""
    return name in ('pipewire', 'pulse', 'default')


def exclusive_output(name):
    """A device PortAudio opens directly, taking the card away from the server."""
    return '(hw:' in name or name in ('sysdefault', 'dmix', 'front', 'hdmi', 'iec958', 'spdif',
                                       'surround40', 'surround41', 'surround50', 'surround51', 'surround71')


def hide_exclusive_outputs(names):
    """One audio path: with a sound-server route present, direct hardware outputs
    stay hidden unless VOLCASTUDIO_EXCLUSIVE_OUTPUTS=1. A direct open steals the
    card from PipeWire/PulseAudio and silences other applications until they
    reconnect; the shared route carries the 44.1 kHz signal just as well."""
    import os
    if os.environ.get(EXCLUSIVE_OUTPUTS_ENV, '') in ('1', 'yes', 'true'):
        return False
    return any(shared_route(name) for name in names)


def output_devices(include_unusable=False):
    """Stereo outputs that can carry the 44.1 kHz signal, system routes first.

    PortAudio reports each device's default rate without opening it. Outputs
    fixed at another rate (PipeWire's JACK graph at 48 kHz, dmix) would fail
    later with "Invalid sample rate", so they are left out of the list, and
    direct hardware outputs are hidden while a shared route exists.
    """
    backend = _backend()
    apis = list(backend.query_hostapis()) if hasattr(backend, 'query_hostapis') else []
    devices = [_describe(i, d, apis) for i, d in enumerate(backend.query_devices()) if d['max_output_channels'] >= 2]
    hide = hide_exclusive_outputs(d['name'] for d in devices)
    return sorted((d for d in devices if (d['usable'] or include_unusable) and not (hide and exclusive_output(d['name']))),
                  key=lambda d: d['rank'])


def _explain(target, backend, exc):
    try:
        name = backend.query_devices(int(target[3:]))['name']
    except Exception:
        name = target
    text = str(exc).lower()
    if 'sample rate' in text:
        hint = ('This output runs at another sample rate and cannot carry the 44.1 kHz signal. '
                'Choose the system audio output (pipewire or default) or the direct hw: device.')
    elif 'unavailable' in text or 'busy' in text:
        hint = ('This output is in use by another application. Stop other playback, or choose the '
                'system audio output (pipewire or default), which shares the device.')
    else:
        hint = 'Choose another output in the list and try again.'
    return f'Audio output “{name}”: {exc}. {hint}'

def play(path, target, *, protocol=True):
    """Send PCM without gain, mixing, resampling or effects in application code."""
    if not isinstance(target, str) or not target.startswith('sd:') or not target[3:].isdigit():
        raise ValueError('Select an explicit native audio output (sd:device-number)')
    device = int(target[3:]); backend = _backend()
    check_cancelled()
    with wave.open(str(path), 'rb') as source:
        rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
        if protocol and (rate, channels, width) != (44100, 2, 2):
            raise ValueError('Transfer requires unchanged 44.1 kHz stereo PCM16')
        if width not in (1, 2, 3, 4) or channels not in (1, 2):
            raise ValueError('Unsupported preview PCM format')
        dtype = {1:'uint8', 2:'int16', 3:'int24', 4:'int32'}[width]
        error_type = getattr(backend, 'PortAudioError', None)
        if not (isinstance(error_type, type) and issubclass(error_type, BaseException)):
            error_type = Exception
        try:
            backend.check_output_settings(device=device, channels=channels, dtype=dtype, samplerate=rate)
            stream = backend.RawOutputStream(device=device, samplerate=rate, channels=channels,
                                             dtype=dtype, blocksize=2048, latency=OUTPUT_LATENCY)
        except error_type as exc:
            raise ValueError(_explain(target, backend, exc)) from exc
        with stream as stream:
            def write(data):
                check_cancelled()
                if stream.write(data):
                    raise RuntimeError('Audio output underrun; transfer incomplete. Verify the instrument.')
            if protocol:
                silence = bytes(2048 * channels * width)
                remaining = rate // 2
                while remaining:
                    count = min(remaining,2048); write(silence[:count*channels*width]); remaining -= count
            frames = source.getnframes(); sent = 0
            while sent < frames:
                block = source.readframes(min(2048, frames-sent))
                if not block:
                    raise ValueError('Truncated playback signal')
                write(block); sent += len(block)//(channels*width)
                report('Sending signal' if protocol else 'Preview', sent, frames)
            check_cancelled()

def input_devices():
    backend = _backend()
    return [dict(id=f'sd:{i}', name=d['name'], channels=int(d['max_input_channels']))
            for i, d in enumerate(backend.query_devices()) if d['max_input_channels'] >= 1]

def _midi():
    try:
        import mido
        mido.set_backend('mido.backends.rtmidi')
        return mido
    except ImportError as exc:
        raise ValueError('Native MIDI needs mido and python-rtmidi') from exc

def midi_outputs():
    return _midi().get_output_names()

def send_midi(port, data):
    check_cancelled()
    if not port or port not in midi_outputs():
        raise ValueError('Select an available MIDI output')
    midi = _midi()
    with midi.open_output(port) as output:
        output.send(midi.Message.from_bytes(list(data)))

def backup(config, port, input, targetfile, timeout=180, progress_callback=None):
    """Decode callback-recorded PCM; publish only eleven validated frames."""
    import os
    import queue
    import time
    from pathlib import Path
    from .pattern_audio import AudioPatternDecoder, request_audio_backup
    from .pattern_device import _valid_frames, MIDI_STOP
    from .patterns import save_bank
    from .transfer import device_lock
    if not isinstance(input, str) or not input.startswith('sd:') or not input[3:].isdigit():
        raise ValueError('Select an explicit native audio input')
    if not isinstance(timeout, (int,float)) or not 0 < timeout <= 180:
        raise ValueError('Capture timeout must be between zero and 180 seconds')
    targetfile = Path(targetfile).expanduser()
    if os.path.lexists(targetfile):
        raise FileExistsError(f'Pattern backup destination already exists: {targetfile}')
    midi = _midi()
    if not port or port not in midi.get_output_names():
        raise ValueError('Select an available MIDI output')
    backend = _backend(); device = int(input[3:])
    backend.check_input_settings(device=device, channels=1, dtype='int16', samplerate=48000)
    chunks = queue.Queue(maxsize=128); errors = []
    def receive(data, frames, timing, status):
        if status:
            errors.append(str(status))
            return
        try:
            chunks.put_nowait(bytes(data))
        except queue.Full:
            errors.append('Capture buffer overrun')
    decoder = AudioPatternDecoder(rate=48000)
    with device_lock(config.state), midi.open_output(port) as output:
        started = complete = False
        try:
            with backend.RawInputStream(device=device, samplerate=48000, channels=1,
                                        dtype='int16', blocksize=2048, callback=receive):
                check_cancelled()
                started = True
                output.send(midi.Message.from_bytes(list(MIDI_STOP)))
                output.send(midi.Message.from_bytes(list(request_audio_backup())))
                deadline = time.monotonic() + timeout
                while not decoder.complete:
                    check_cancelled()
                    if errors:
                        raise RuntimeError('Audio capture interrupted: ' + errors[0])
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Timed out waiting for eleven CRC-valid patterns')
                    try:
                        data = chunks.get(timeout=.05)
                    except queue.Empty:
                        continue
                    if decoder.feed(data) and progress_callback:
                        progress_callback(len(decoder.frames), 11)
                patterns = _valid_frames(decoder.finish())
                check_cancelled()
                complete = True
        finally:
            if started and not complete:
                try:
                    output.send(midi.Message.from_bytes(list(MIDI_STOP)))
                except Exception:
                    pass
        check_cancelled()
        return save_bank(targetfile, patterns)
