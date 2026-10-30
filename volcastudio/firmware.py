"""Managed firmware waveforms: identity checks, provenance and explicit transfer.

Studio ships no firmware. The user adds the official Korg updater they
downloaded; Studio builds DataBeat OS from it (see lumon_build) and offers
exactly those two images. Additional local builds can only be offered by a
provider registered in ADDITIONAL_BUILDS; Studio registers none.
No sample erasure or automatic device discovery happens here.
"""
import hashlib
import json
import re
import shutil
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path


# Extension point for additional local builds (internal tools only). A provider
# has identities(config) -> {identity: sha256} for the entries it offers, and
# check(identity, record), which raises ValueError for a record it must refuse.
ADDITIONAL_BUILDS = []
KORG_GUIDE = 'https://www.korg.com/us/support/download/software/0/370/1475/'
PROCEDURE = (
    'Use a first-generation Volca Sample (not Sample 2), with reliable power.',
    'Connect the selected audio output directly to SYNC IN. Disconnect speakers/headphones from that output; never audition firmware audio.',
    'Pause all other audio and notifications. Disable EQ, crossfade and audio enhancements. Set the output volume appropriately.',
    'Power on the Volca while holding FUNC + PLAY. Confirm that its display reads UPdt.',
    'Start the procedure once. Do not interrupt playback or switch off the Volca while updating.',
    'Playback completion is not installation confirmation. Wait for End on the Volca; then power off and check the version by powering on with REC held.',
)
KORG_RETURN_PROCEDURE = (
    'Keep a backup of your DataBeat OS patterns. Returning to Korg does not convert them or preserve DataBeat OS feature behavior.',
) + PROCEDURE[:3] + (
    'Power on while holding MEMORY + PLAY for forced update. The display shows UPdt with its final decimal point lit. Release the buttons before sending the original Korg updater.',
) + PROCEDURE[4:]


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _wave(path):
    with wave.open(str(path), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (2, 2, 44100, 'NONE'):
            raise ValueError('Firmware requires the original stereo PCM16 44,100 Hz WAV; do not convert it')
        frames = stream.getnframes()
        if not frames or len(stream.readframes(frames)) != frames * 4:
            raise ValueError('Empty or truncated firmware WAV')
    return frames / 44100


def _directory(config, identity):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', identity):
        raise ValueError('Invalid firmware identifier')
    base = (config.data / 'firmware').resolve()
    result = base / identity
    if result.is_symlink() or (result.exists() and result.resolve().parent != base):
        raise ValueError('Firmware directory must remain in the managed library')
    return result


def inspect_firmware(config, identity):
    directory = _directory(config, identity)
    record = json.loads((directory / 'manifest.json').read_text())
    if record.get('schema') != 1 or record.get('id') != identity or record.get('target') != 'volca-sample-v1':
        raise ValueError('Invalid firmware manifest')
    if any(type(record.get(key)) is not bool for key in ('installable', 'experimental', 'hardware_tested')):
        raise ValueError('Invalid firmware classification metadata')
    if not isinstance(record.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', record['sha256']):
        raise ValueError('Invalid firmware checksum metadata')
    if any(not isinstance(record.get(key), str) or not record[key].strip() for key in ('name', 'version', 'variant', 'status')):
        raise ValueError('Invalid firmware descriptive metadata')
    waveform = directory / 'firmware.wav'
    if waveform.is_symlink() or _sha(waveform) != record['sha256']:
        raise ValueError('Firmware WAV does not match its recorded SHA-256')
    record['seconds'] = _wave(waveform)
    record['path'] = str(waveform)
    return record


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:70] or 'firmware'


def current_identities(patch=None):
    """Pinned production identities: the built DataBeat OS release and its Korg base."""
    from .lumon_build import load_patch
    patch = patch or load_patch()
    release, base, result = patch['release'], patch['base'], patch['result']
    return {
        f'lumon-xl-{_slug(release["version"])}-{result["wav_sha256"][:16]}': result['wav_sha256'],
        f'korg-{_slug(base["version"])}-{base["wav_sha256"][:16]}': base['wav_sha256'],
    }


def _offers(config, patch=None):
    """identity -> (approved SHA-256, classification check) for each offered image."""
    from .lumon_build import load_patch
    patch = patch or load_patch()
    release = patch['release']
    (production, production_sha), (korg, korg_sha) = current_identities(patch).items()

    def check_production(identity, record):
        if (record['variant'] != 'lumon-xl' or
                record['experimental'] is not bool(release['experimental']) or
                record['hardware_tested'] is not bool(release['hardware_tested']) or
                record['status'] != release['status']):
            raise ValueError('Firmware classification differs from the pinned release')

    def check_korg(identity, record):
        if record['variant'] != 'korg':
            raise ValueError('Invalid Korg updater classification')

    result = {production: (production_sha, check_production), korg: (korg_sha, check_korg)}
    for provider in ADDITIONAL_BUILDS:
        for identity, digest in provider.identities(config).items():
            result.setdefault(identity, (digest, provider.check))
    return result


def available_identities(config, patch=None):
    return {identity: digest for identity, (digest, _) in _offers(config, patch).items()}


def _offered_record(config, identity, offer):
    digest, check = offer
    record = inspect_firmware(config, identity)
    if record['sha256'] != digest:
        raise ValueError('Firmware differs from its approved SHA-256')
    check(identity, record)
    return record


def add_hint(patch=None):
    from .lumon_build import load_patch
    patch = patch or load_patch()
    base, release = patch['base'], patch['release']
    return (f'Add the official Korg volca sample {base["version"]} updater ({base["updater_zip"]}, '
            f'downloaded from {base["download_page"]}); Studio builds {release["name"]} from it.')


def _store(data, config, identity, **metadata):
    """Save exact bytes under a canonical identity; a damaged entry is set aside, not deleted."""
    digest = hashlib.sha256(data).hexdigest()
    destination = _directory(config, identity)
    record = dict(schema=1, id=identity, target='volca-sample-v1', sha256=digest, bytes=len(data), **metadata)
    if destination.exists():
        try:
            existing = inspect_firmware(config, identity)
        except (OSError, ValueError, KeyError):
            existing = None
        if existing is not None and existing['sha256'] == digest:
            stored = json.loads((destination / 'manifest.json').read_text())
            record['imported_at'] = stored.get('imported_at', record.get('imported_at'))
            record['seconds'] = existing['seconds']
            if {key: stored.get(key) for key in record} != record:
                pending = destination / 'manifest.json.tmp'
                pending.write_text(json.dumps(record, indent=2) + '\n')
                pending.replace(destination / 'manifest.json')
            return inspect_firmware(config, identity)
        destination.rename(destination.with_name(
            f'.damaged-{identity}-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.import-', dir=destination.parent) as tmp:
        staged = Path(tmp) / 'entry'
        staged.mkdir()
        (staged / 'firmware.wav').write_bytes(data)
        if _sha(staged / 'firmware.wav') != digest:
            raise ValueError('Firmware changed while saving')
        record['seconds'] = _wave(staged / 'firmware.wav')
        (staged / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
        staged.rename(destination)
    return inspect_firmware(config, identity)


def add_korg_updater(source, config, patch=None, filename=None):
    """Build DataBeat OS from the user's own Korg updater and keep both in the library.

    Studio checks the result: nothing is saved unless every stage matches its
    pinned SHA-256."""
    from .lumon_build import PATCH_FILE, build, load_patch, read_updater
    patch = patch or load_patch()
    korg_wav = read_updater(source, patch)
    firmware_wav = build(korg_wav, patch)
    firmware_id, korg_id = current_identities(patch)
    base, release = patch['base'], patch['release']
    now = datetime.now(timezone.utc).isoformat()
    korg = _store(korg_wav, config, korg_id, name='Korg volca sample',
                  version=base['version'], variant='korg', status='OFFICIAL_KORG_UPDATER_SUPPLIED_BY_USER',
                  experimental=False, installable=True, hardware_tested=True, imported_at=now,
                  provenance={'supplied_by': 'user', 'file': filename or Path(source).name,
                              'download_page': base['download_page']})
    firmware_entry = _store(firmware_wav, config, firmware_id, name=release['name'], version=release['version'],
                   variant='lumon-xl', status=release['status'], experimental=bool(release['experimental']),
                   installable=True, hardware_tested=bool(release['hardware_tested']), imported_at=now,
                   provenance={'built_by': 'VolcaStudio XL', 'built_from': korg_id, 'patch': PATCH_FILE.name,
                               'result_checked': True})
    return [firmware_entry, korg]


def list_firmware(config, patch=None):
    """The current release and its Korg base, plus any registered additional build."""
    result = []
    for identity, offer in _offers(config, patch).items():
        if not (config.data / 'firmware' / identity / 'manifest.json').is_file():
            continue
        try:
            result.append(_offered_record(config, identity, offer))
        except (OSError, ValueError, KeyError):
            continue
    return result


def transfer_firmware(config, identity, *, target=None, confirm_callback=None,
                      allow_experimental=False, dry_run=False, patch=None):
    offers = _offers(config, patch)
    if identity not in offers:
        raise ValueError('VolcaStudio XL sends only DataBeat OS built from your Korg updater '
                         'and that Korg updater.')
    record = _offered_record(config, identity, offers[identity])
    if record['variant'] not in ('lumon-xl', 'korg'):
        raise ValueError('VolcaStudio XL sends only DataBeat OS and the Korg updater')
    procedure = KORG_RETURN_PROCEDURE if record['variant'] == 'korg' else PROCEDURE
    record.update(operation='firmware', procedure=list(procedure), hardware_receipt='unavailable: one-way audio')
    if dry_run:
        return dict(record, phase='dry_run')
    if not record['installable']:
        raise ValueError('This build is archived for offline analysis, not an installation release; playback is blocked')
    if record['experimental'] and not allow_experimental:
        raise ValueError('Experimental firmware needs explicit --allow-experimental acceptance')
    if not target or confirm_callback is None:
        raise ValueError('Select an audio output and explicitly confirm the firmware procedure')
    from .transfer import device_lock, syro_rate, play_stream, audio_dependencies
    with device_lock(config.state), tempfile.TemporaryDirectory(prefix='volcastudio-firmware-') as tmp:
        staged = Path(tmp) / 'firmware.wav'
        shutil.copyfile(record['path'], staged)
        if _sha(staged) != record['sha256']:
            raise ValueError('Firmware changed before transfer')
        if not confirm_callback(record):
            return dict(record, phase='cancelled')
        audio_dependencies(target)
        record['audio_target'] = target
        def log(phase):
            record['phase'] = phase
            record['updated_at'] = datetime.now(timezone.utc).isoformat()
            pending = config.state / 'last-firmware-transfer.json.tmp'
            pending.write_text(json.dumps(record, indent=2) + '\n')
            pending.replace(config.state / 'last-firmware-transfer.json')
        try:
            log('starting')
            with syro_rate(target):
                # Recheck our private snapshot after user confirmation; never replay
                # a path into the mutable library.
                if _sha(staged) != record['sha256']:
                    raise ValueError('Staged firmware changed before playback')
                log('sending_firmware')
                play_stream(staged, target)
            log('signals_sent')
        except BaseException as exc:
            record['error'] = str(exc) or type(exc).__name__
            log('interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed')
            raise
    return record
