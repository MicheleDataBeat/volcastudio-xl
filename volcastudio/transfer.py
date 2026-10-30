"""Korg SYRO encoding and audio transfer with isolated, checked staging."""
import contextlib
from . import locking as fcntl
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from .status import message, progress
from . import desktop_audio

MAX_SAMPLES = 100
MAX_SECONDS = 65.0
SAMPLE_RATE = 31250  # Volca's sample-memory rate; SYRO transport stays 44100 Hz.


def tool_path(name):
    executable = name + ('.exe' if os.name == 'nt' else '')
    bundled = Path(__file__).resolve().parents[1] / 'tools-bin' / executable
    return str(bundled) if bundled.is_file() else shutil.which(name)


def portable_audio(target=None):
    return desktop_audio.active() or os.name == 'nt' or platform.system() == 'Darwin' or str(target).startswith('sd:')


def audio_dependencies(target=None):
    if portable_audio(target):
        desktop_audio._backend()
        if not isinstance(target, str) or not target.startswith('sd:'):
            raise ValueError('Select an explicit native audio output')
    else:
        for name in ('pw-play', 'pw-metadata'):
            if not shutil.which(name):
                raise ValueError(f'Missing dependency: {name}')


def checked(args, **kwargs):
    # Each operation owns its process group. Terminate children before releasing
    # the transfer lock or restoring PipeWire, including terminal close/SIGTERM.
    if kwargs.pop('capture_output', False):
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    desktop_audio.check_cancelled()
    args = list(args)
    if str(args[0]) in ('ffmpeg', 'ffprobe'):
        args[0] = tool_path(str(args[0])) or args[0]
    if os.name == 'nt':
        kwargs.setdefault('creationflags', subprocess.CREATE_NO_WINDOW)
    with subprocess.Popen([str(x) for x in args], start_new_session=os.name != 'nt', **kwargs) as proc:
        try:
            if desktop_audio.active():
                while True:
                    desktop_audio.check_cancelled()
                    try:
                        out, err = proc.communicate(timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            else:
                out, err = proc.communicate()
        except BaseException:
            if proc.poll() is None:
                proc.terminate() if os.name == 'nt' else os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill() if os.name == 'nt' else os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            raise
        if proc.returncode:
            raise subprocess.CalledProcessError(proc.returncode, args, output=out, stderr=err)
        return subprocess.CompletedProcess(args, proc.returncode, out, err)


def inspect_wav(path):
    """RIFF metadata; reject truncated, empty, compressed or malformed audio."""
    with path.open('rb') as f:
        header = f.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            raise ValueError(f'Not a RIFF WAV: {path}')
        size = path.stat().st_size
        fmt = data = None
        while f.tell() + 8 <= size:
            cid, length = struct.unpack('<4sI', f.read(8))
            if f.tell() + length > size:
                raise ValueError(f'Truncated WAV: {path}')
            if cid == b'fmt ':
                raw = f.read(length)
                if len(raw) < 16:
                    raise ValueError(f'Invalid WAV format: {path}')
                tag, channels, rate, _, align, bits = struct.unpack('<HHIIHH', raw[:16])
                if tag == 0xfffe and len(raw) >= 26:
                    tag = struct.unpack('<H', raw[24:26])[0]
                fmt = (tag, channels, rate, align, bits)
            elif cid == b'data':
                data = length
                f.seek(length, 1)
            else:
                f.seek(length, 1)
            f.seek(length & 1, 1)
        if not fmt or not data:
            raise ValueError(f'Missing format or audio: {path}')
        tag, channels, rate, align, bits = fmt
        if tag not in (1, 3) or channels not in (1, 2) or rate <= 0 or align <= 0 or bits not in (8, 16, 24, 32):
            raise ValueError(f'Unsupported WAV format: {path}')
        if align != channels * bits // 8 or data % align:
            raise ValueError(f'Invalid frame layout: {path}')
        return data / align / rate


def pack_files(pack):
    pack = Path(pack).expanduser().resolve(strict=True)
    if not pack.is_dir():
        raise ValueError(f'Not a kit directory: {pack}')
    # Assign slots in a stable order across the kit's complete directory tree.
    files = sorted((p for p in pack.rglob('*') if p.is_file() and p.suffix.lower() == '.wav'),
                   key=lambda p: p.relative_to(pack).as_posix())
    if not files or len(files) > MAX_SAMPLES:
        raise ValueError(f'Kit must contain 1–{MAX_SAMPLES} WAVs; found {len(files)}')
    seconds = math.fsum(inspect_wav(p) for p in files)
    if seconds > MAX_SECONDS:
        raise ValueError(f'Kit exceeds memory: {seconds:.3f} s > {MAX_SECONDS:g} s')
    return pack, files, seconds


def converter(syro_dir):
    """Locate the backend compiled from the bundled Korg SDK source."""
    binary = Path(syro_dir) / 'bin' / ('volcastudio-syro.' + platform.machine() + ('.exe' if os.name == 'nt' else ''))
    if not os.access(binary, os.X_OK):
        raise ValueError(f'SYRO backend missing: {binary}. Run python3 tools/build_syro.py.')
    return binary


def verify_stream(path):
    with wave.open(str(path), 'rb') as f:
        if (f.getframerate(), f.getnchannels(), f.getsampwidth()) != (44100, 2, 2) or f.getnframes() == 0:
            raise ValueError(f'Invalid SYRO stream: {path}')
        if len(f.readframes(f.getnframes())) != f.getnframes() * 4:
            raise ValueError(f'Truncated SYRO stream: {path}')


def normalize_sample(source, destination):
    """Resample a temporary snapshot; source-rate frames consume extra Volca memory."""
    checked(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', source,
             '-map', '0:a:0', '-ac', '1', '-ar', str(SAMPLE_RATE),
             '-c:a', 'pcm_s16le', destination], stdin=subprocess.DEVNULL)


def prepare(pack, output, syro_dir):
    """Offline only: decode + normalize headers, encode every upload and clear.

    FFmpeg emits PCM16 mono at 31250 Hz, preserving pitch and duration. This
    handles PCM24, float and metadata chunks uniformly for the SYRO converter.
    """
    pack, files, seconds = pack_files(pack)
    binary = converter(syro_dir)
    output = Path(output)
    output.mkdir()  # refuse overwrite of any existing prepared transfer
    try:
        samples = output / 'samples'
        samples.mkdir()
        hashes = []
        for i, src in enumerate(files):
            dst = samples / f'{i:02d}.wav'
            normalize_sample(src, dst)
            hashes.append({'slot': i, 'source': str(src), 'normalized_sha256': hashlib.sha256(dst.read_bytes()).hexdigest()})
        # Inspect the actual decoded snapshots, not cached library durations.
        actual_seconds = math.fsum(inspect_wav(p) for p in sorted(samples.iterdir()))
        # Each independently resampled WAV may round up by one output frame.
        # The source budget was checked already; tolerate only this rounding.
        if actual_seconds > MAX_SECONDS + len(files) / SAMPLE_RATE:
            raise ValueError('Decoded kit exceeds Volca memory')
        for i in range(len(files)):
            dst = output / f'upload-{i:02d}.wav'
            checked([binary, dst, f's{i}c:{samples / f"{i:02d}.wav"}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            verify_stream(dst)
        for i in range(MAX_SAMPLES):
            dst = output / f'clear-{i:02d}.wav'
            checked([binary, dst, f'e{i}:'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            verify_stream(dst)
        manifest = {'schema': 1, 'pack': str(pack), 'count': len(files), 'seconds': seconds,
                    'sample_rate': SAMPLE_RATE,
                    'sample_pcm_bytes': round(actual_seconds * SAMPLE_RATE) * 2,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'samples': hashes,
                    'hardware_receipt': 'unavailable: SYRO audio is one-way'}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return manifest
    except BaseException:
        shutil.rmtree(output)
        raise


@contextlib.contextmanager
def device_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'transfer.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another VolcaStudio XL transfer is active') from None
        yield


@contextlib.contextmanager
def syro_rate(target=None):
    if portable_audio(target):
        desktop_audio.check_cancelled()
        yield
        return
    out = checked(['pw-metadata', '-n', 'settings', '0', 'clock.force-rate'],
                  capture_output=True, text=True).stdout
    match = re.search(r"value:\s*['\"]?(\d+)", out)
    if not match:
        raise ValueError('Cannot read PipeWire clock.force-rate; refusing to change it')
    previous = match.group(1)
    try:
        checked(['pw-metadata', '-n', 'settings', '0', 'clock.force-rate', '44100'], stdout=subprocess.DEVNULL)
        time.sleep(0.5)
        yield
    finally:
        checked(['pw-metadata', '-n', 'settings', '0', 'clock.force-rate', previous], stdout=subprocess.DEVNULL)


def play_stream(path, target=None):
    if portable_audio(target):
        return desktop_audio.play(path, target)
    # A short silence wakes the audio sink before the first protocol frame.
    lead = path.with_name('playback.wav')
    with wave.open(str(path), 'rb') as src, wave.open(str(lead), 'wb') as dst:
        dst.setparams(src.getparams())
        dst.writeframes(b'\0' * (22050 * 4) + src.readframes(src.getnframes()))
    cmd = ['pw-play', '--rate', '44100', '--volume', '1.0']
    if target:
        cmd.extend(['--target', target])
    try:
        checked(cmd + [lead], stdin=subprocess.DEVNULL)
    finally:
        lead.unlink(missing_ok=True)


def transfer(pack, config, confirm, target=None, *, expected_fingerprint=None, on_sent=None):
    if not tool_path('ffmpeg'):
        raise ValueError('Missing dependency: ffmpeg')
    audio_dependencies(target)
    with device_lock(config.state), tempfile.TemporaryDirectory(prefix='volcastudio-transfer-') as tmp:
        def check_kit():
            if expected_fingerprint is not None:
                from .kits import fingerprint
                if fingerprint(pack) != expected_fingerprint:
                    raise ValueError('The saved kit changed outside the Desktop App. Open it again before sending.')
        check_kit()
        message('Preparing and checking all transfer signals (no audio playback)…')
        directory = Path(tmp) / 'prepared'
        manifest = prepare(pack, directory, config.syro_dir)
        check_kit()
        if not confirm(manifest):
            if not desktop_audio.active():
                message('Transfer cancelled. No samples cleared.')
            return 0
        record = dict(manifest, phase='starting', audio_target=target or 'default')
        def log(phase):
            record['phase'] = phase
            record['updated_at'] = datetime.now(timezone.utc).isoformat()
            pending = config.state / 'last-transfer.json.tmp'
            pending.write_text(json.dumps(record, indent=2) + '\n')
            pending.replace(config.state / 'last-transfer.json')
        try:
            with syro_rate(target):
                log('clearing')
                progress('Retiring slots', 0, MAX_SAMPLES)
                for i in range(MAX_SAMPLES):
                    play_stream(directory / f'clear-{i:02d}.wav', target)
                    progress('Retiring slots', i + 1, MAX_SAMPLES)
                log('uploading')
                progress('Loading samples', 0, manifest['count'])
                for i in range(manifest['count']):
                    play_stream(directory / f'upload-{i:02d}.wav', target)
                    progress('Loading samples', i + 1, manifest['count'])
                    time.sleep(1)
            log('signals_sent')
            message('All signals sent. Check the kit on the Volca (audio transfer has no acknowledgement).')
        except BaseException as exc:
            record['error'] = str(exc) or type(exc).__name__
            log('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
        if on_sent:
            on_sent()
        return 0
