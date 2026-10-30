"""Offline sample analysis and tape-style varispeed; source files stay untouched."""
import array
import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from .transfer import checked, inspect_wav

NAMES = ('C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')


def identity(path):
    path = Path(path).expanduser().resolve(strict=True)
    info = path.stat()
    fingerprint = f'{path}\0{info.st_size}\0{info.st_mtime_ns}\0{info.st_ctime_ns}'
    return path, hashlib.sha256(fingerprint.encode()).hexdigest()


def speed_factor(path):
    """Read recorded transformation metadata; never infer speed from a filename."""
    from .tuning import tuning_metadata
    return tuning_metadata(path)['factor']


def note(midi):
    return NAMES[midi % 12] + str(midi // 12 - 1)


def frame_pitch(frame, window, max_lag, rate=8000):
    if sum(x*x for x in frame[:window]) / window < 1e-7:
        return None
    diffs = [0.0]
    for lag in range(1, max_lag + 1):
        diffs.append(sum((frame[i] - frame[i + lag]) ** 2 for i in range(window)))
    total = 0.0
    cmnd = [1.0]
    for lag in range(1, max_lag + 1):
        total += diffs[lag]
        cmnd.append(diffs[lag] * lag / total if total else 1.0)
    minimum = max(4, int(rate / 2000))
    lag = minimum
    while lag < max_lag:
        if cmnd[lag] < .15:
            while lag + 1 <= max_lag and cmnd[lag + 1] < cmnd[lag]:
                lag += 1
            break
        lag += 1
    else:
        return None
    refined = float(lag)
    if 1 < lag < max_lag:
        left, middle, right = cmnd[lag - 1:lag + 2]
        denom = left - 2 * middle + right
        if denom:
            refined += .5 * (left - right) / denom
    return rate / refined, max(0, 1 - cmnd[lag])


def detect_pitch(path, cache=None):
    """YIN-style periodicity estimate, not musical-key/chord detection.

    Analyze up to 12 windows across at most 30 seconds; silence/unpitched sounds
    return no note. Consistency and voiced coverage reduce confidence for drums,
    polyphony and phrases. Cached estimates are invalidated by source metadata.
    """
    path, key = identity(path)
    # Version the estimator cache: the previous 8 kHz analysis could mistake
    # high notes for an octave below because their period spans too few frames.
    key = hashlib.sha256((key + ':yin-16k-v2').encode()).hexdigest()
    cached = Path(cache) / (key + '.json') if cache else None
    if cached and cached.exists():
        return json.loads(cached.read_text())
    inspect_wav(path)
    raw = checked(['ffmpeg', '-nostdin', '-v', 'error', '-i', path, '-t', '30',
                   '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'], capture_output=True).stdout
    samples = array.array('f')
    samples.frombytes(raw)
    if sys.byteorder != 'little':
        samples.byteswap()
    result = {'source': str(path), 'method': 'YIN periodicity; monophonic estimate',
              'note': None, 'midi': None, 'hz': None, 'cents': None,
              'confidence': 0.0, 'status': 'unpitched or insufficient audio'}
    if len(samples) >= 128:
        window = min(1024, len(samples) * 2 // 3)
        max_lag = min(533, len(samples) - window)
        span = len(samples) - window - max_lag
        offsets = sorted(set(round(i * span / 11) for i in range(12)))
        pitches = []
        for offset in offsets:
            found = frame_pitch(samples[offset:offset + window + max_lag], window, max_lag, rate=16000)
            if found:
                hz, confidence = found
                pitches.append((69 + 12 * math.log2(hz / 440), confidence))
        if pitches:
            midi_float = statistics.median(p[0] for p in pitches)
            midi = round(midi_float)
            coherence = sum(abs(p[0] - midi_float) <= .5 for p in pitches) / len(pitches)
            confidence = statistics.median(p[1] for p in pitches) * coherence * len(pitches) / len(offsets)
            result.update(confidence=round(confidence, 3), status='variable or uncertain')
            if confidence >= .6:
                result.update(note=note(midi), midi=midi, hz=round(440 * 2**((midi_float - 69) / 12), 2),
                              cents=round((midi_float - midi) * 100, 1), status='estimated')
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile('w', dir=cached.parent, delete=False) as temp:
            json.dump(result, temp)
            pending = Path(temp.name)
        pending.replace(cached)
    return result


def pitch_text(path, cache=None):
    result = detect_pitch(path, cache)
    if result['note']:
        midi = result['midi']
        return (f'pitch est. {result["note"]} · {result["hz"]:g} Hz · {result["cents"]:+g} cents '
                f'· confidence {result["confidence"]:.0%}\n'
                f'at SPEED −12: {note(midi - 12)} · −24: {note(midi - 24)}')
    return f'pitch: {result["status"]} · confidence {result["confidence"]:.0%}'


def varispeed_x2(source, variants, output=None):
    source, key = identity(source)
    inspect_wav(source)
    if output:
        destination = Path(output).expanduser().resolve()
        if destination.exists():
            raise ValueError(f'Refusing to overwrite: {destination}')
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        safe = ''.join(c if c.isascii() and (c.isalnum() or c in '._-') else '_' for c in source.stem)[:70]
        destination = Path(variants) / key / (safe + '_x2.wav')
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = destination.with_suffix('.json')
    if sidecar.exists():
        raise ValueError(f'Refusing to overwrite metadata: {sidecar}')
    metadata = checked(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                        'stream=sample_rate', '-of', 'csv=p=0', source], capture_output=True, text=True).stdout.strip()
    rate = int(metadata)
    with tempfile.TemporaryDirectory(prefix='.x2-', dir=destination.parent) as temporary:
        pending = Path(temporary) / 'sample.wav'
        checked(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', source,
                 '-af', f'asetrate={rate * 2},aresample={rate}', '-c:a', 'pcm_s24le', pending])
        inspect_wav(pending)
        # Publish without replacing either user output, including metadata.
        import os
        from .tuning import tuning_metadata
        previous = tuning_metadata(source)
        total = previous['semitones'] + 12
        info = {'source': previous['source'], 'original_name': previous.get('original_name', Path(previous['source']).name),
                'input': str(source), 'factor': 2 ** (total / 12), 'semitones': total,
                'history_uncertain': bool(previous.get('history_uncertain')),
                'playback_to_restore': 'SPEED -12', 'gain': 'unchanged'}
        created = False
        metadata_created = False
        try:
            os.link(pending, destination)
            created = True
            with sidecar.open('x') as metadata_out:
                metadata_created = True
                json.dump(info, metadata_out, indent=2)
                metadata_out.write('\n')
        except FileExistsError:
            if created:
                destination.unlink()
                raise ValueError(f'Refusing to overwrite metadata: {sidecar}') from None
            if output:
                raise ValueError(f'Refusing to overwrite: {destination}') from None
        except BaseException:
            if metadata_created:
                sidecar.unlink(missing_ok=True)
            if created:
                destination.unlink(missing_ok=True)
            raise
    return destination
