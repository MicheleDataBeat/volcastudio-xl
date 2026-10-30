"""Offline firmware self-check for source and packaged builds: one production release.

Uses temporary storage only and never opens audio devices. The real build is
checked when the official Korg updater is supplied (argument or the
VOLCASTUDIO_KORG_UPDATER environment variable); Studio itself never ships it.
"""
import hashlib
import os
from pathlib import Path

from . import lumon_build, updater_codec
from .firmware import ADDITIONAL_BUILDS, _store, add_korg_updater, current_identities, list_firmware, transfer_firmware


def _expect_refusal(action, words):
    try:
        action()
    except ValueError as exc:
        if words not in str(exc):
            raise RuntimeError(f'Refused for an unexpected reason: {exc}') from exc
        return True
    raise RuntimeError(f'Expected a refusal ({words})')


def self_check(config, workdir, korg_updater=None):
    workdir = Path(workdir)
    report = {}
    patch = lumon_build.load_patch()
    release = patch['release']
    shipped = sorted(p.name for p in lumon_build.PATCH_FILE.parent.iterdir())
    if shipped != [lumon_build.PATCH_FILE.name]:
        raise RuntimeError(f'Unexpected files shipped with the firmware patch: {shipped}')
    if (patch.get('kind') != lumon_build.PATCH_KIND or release['experimental'] is not False
            or release['hardware_tested'] is not True):
        raise RuntimeError('The shipped patch is not the accepted production release')
    if ADDITIONAL_BUILDS:
        raise RuntimeError('Additional firmware builds are registered in this process')
    report['shipped'] = {'files': shipped, 'patch_sha256': lumon_build.PATCH_SHA256,
                         'release': f'{release["name"]} {release["version"]}', 'base': patch['base']['name'],
                         'experimental': False, 'hardware_tested': True}

    korg_wav, synthetic = lumon_build.synthetic_case()
    fixture = workdir / 'synthetic korg updater.wav'
    fixture.write_bytes(korg_wav)
    built = add_korg_updater(fixture, config, patch=synthetic)
    listed = list_firmware(config, patch=synthetic)
    if [e['id'] for e in listed] != [e['id'] for e in built] or not all(e['installable'] for e in listed):
        raise RuntimeError('Synthetic build did not list both images as installable')
    for entry in listed:
        if transfer_firmware(config, entry['id'], dry_run=True, patch=synthetic)['phase'] != 'dry_run':
            raise RuntimeError('Dry run failed')
    other = workdir / 'other updater.wav'
    other.write_bytes(updater_codec.synthetic_updater(b'\x00' * updater_codec.IMAGE_SIZE))
    report['synthetic_build'] = {
        'listed': [e['name'] for e in listed],
        'wrong_updater_refused': _expect_refusal(lambda: add_korg_updater(other, config, patch=synthetic), 'not the official'),
    }

    retired_id = 'lumon-xl-1-0-1-0000000000000000'
    _store(korg_wav, config, retired_id, name='Retired fixture', version='1.0.1', variant='lumon-xl',
           status='RETIRED_FIXTURE', experimental=False, installable=True, hardware_tested=False,
           provenance='offline self-check')
    if any(e['id'] == retired_id for e in list_firmware(config)):
        raise RuntimeError('A retired firmware appeared in the library')
    report['retired_hidden_and_blocked'] = _expect_refusal(
        lambda: transfer_firmware(config, retired_id, dry_run=True), 'sends only')

    path = korg_updater or os.environ.get('VOLCASTUDIO_KORG_UPDATER')
    if not path:
        report['korg_updater_build'] = 'not run: no Korg updater supplied'
        return report
    entries = add_korg_updater(Path(path), config)
    listed = list_firmware(config)
    identities = list(current_identities(patch))
    built = Path(listed[0]['path']).read_bytes() if listed else b''
    if ([e['id'] for e in listed] != identities or [e['id'] for e in entries] != identities
            or hashlib.sha256(built).hexdigest() != patch['result']['wav_sha256']
            or hashlib.sha256(updater_codec.decode(built).binary()).hexdigest() != patch['result']['image_sha256']
            or not all(e['installable'] and not e['experimental'] for e in listed)
            or not listed[0]['hardware_tested']):
        raise RuntimeError('The Korg updater did not produce exactly DataBeat OS and its Korg base')
    report['korg_updater_build'] = {
        'bit_identical': True, 'listed': [f'{e["name"]} {e["version"]} ({e["variant"]}, {e["sha256"]})' for e in listed],
        'firmware_sha256': listed[0]['sha256'], 'image_sha256': patch['result']['image_sha256'],
        'korg_sha256': listed[1]['sha256'],
    }
    return report
