#!/usr/bin/env python3
"""Create Studio's DataBeat OS patch from a frozen local build and the Korg updater.

Development tool. The Korg updater and the firmware files are read locally and
never copied into the repository: only the patch (DataBeat OS's own bytes plus
copy instructions into the user's Korg image) is written. Prints the SHA-256 to
pin in volcastudio/lumon_build.py.

  python tools/make_lumon_patch.py --korg-updater volcasample_updater_1_42.zip \
      --candidate FROZEN_BUILD_DIR --public-version 1.0 [--output ...]

Without --public-version, --candidate writes an experimental internal patch.
"""
import argparse
import subprocess
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import lumon_build  # noqa: E402

KORG = {'name': 'Korg volca sample system updater 1.42', 'version': '1.42',
        'updater_zip': 'volcasample_updater_1_42.zip', 'updater_wav': 'volcasample_sys_0142.wav',
        'download_page': lumon_build.KORG_DOWNLOAD_PAGE}
KORG_IMAGE_SHA256 = '4ea3647d489210cdbbba3562b48cc2ff2a6a851a00e5564f1247afc15a5f17b4'
# Public DataBeat OS releases and the frozen internal build each one is made from.
# This is the only place in the code that maps a public version to an internal one.
PUBLIC_RELEASES = {
    '1.0': {'internal_version': '1.1.0-experimental.4', 'status': 'HARDWARE_ACCEPTED_OWNER_REPORT',
            'date': '2026-10-29', 'pattern_format': 'LMX3'},
}
PRODUCT_NAME = 'DataBeat OS'
RELEASE_KEYS = ('name', 'version', 'status', 'experimental', 'hardware_tested', 'pattern_format',
                'boot_branding', 'date', 'tag', 'source_commit')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    subprocess.run([sys.executable, str(ROOT / 'tools/check_product_name.py'), '--root', str(ROOT)], check=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--korg-updater', type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--release', type=Path, help='Folder with the release manifest.json, .bin and .wav')
    source.add_argument('--candidate', type=Path, help='Frozen offline-qualified internal candidate directory')
    parser.add_argument('--public-version', choices=tuple(PUBLIC_RELEASES),
                        help='Make the accepted production patch of this public release from --candidate')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    raw = args.korg_updater.read_bytes()
    base = dict(KORG)
    if raw[:4] == b'PK\x03\x04':
        base['zip_sha256'] = sha(raw)
        with zipfile.ZipFile(args.korg_updater) as archive:
            raw = archive.read(KORG['updater_wav'])
    from volcastudio import updater_codec
    if sha(updater_codec.decode(raw).binary()) != KORG_IMAGE_SHA256:
        parser.error('Not the Korg volca sample 1.42 updater')

    if args.candidate:
        folder = args.candidate
        qualification = json.loads((folder / 'qualification.json').read_text())
        if (qualification.get('status') != 'OFFLINE_QUALIFIED_INTERNAL_CANDIDATE' or
                qualification.get('updater_transport_verified') is not True):
            parser.error('The internal candidate must be qualified offline, including its updater')
        artifacts = {name: {'sha256': digest} for name, digest in qualification['artifacts_sha256'].items()
                     if name.endswith(('.bin', '.wav'))}
        if args.public_version:
            public = PUBLIC_RELEASES[args.public_version]
            if (qualification['firmware_version'] != public['internal_version'] or
                    qualification.get('public_name') != PRODUCT_NAME or
                    qualification.get('planned_public_version') != args.public_version):
                parser.error(f'{PRODUCT_NAME} {args.public_version} is built from '
                             f'{public["internal_version"]}; this folder holds another build')
            # Accepted on the instrument by its owner: a production release.
            manifest = dict(name=PRODUCT_NAME, version=args.public_version, status=public['status'],
                            experimental=False, hardware_tested=True,
                            pattern_format=public['pattern_format'],
                            boot_branding=qualification['boot_branding'], date=public['date'],
                            artifacts=artifacts, installable=True, updater_transport_version='1.60')
        else:
            manifest = dict(name=PRODUCT_NAME, version=qualification['firmware_version'],
                            status=qualification['status'], experimental=True, hardware_tested=False,
                            pattern_format=qualification['pattern_format'],
                            boot_branding=qualification.get('boot_branding', PRODUCT_NAME),
                            date=qualification.get('date', '2026-10-24'),
                            source_commit=qualification['source_commit'],
                            artifacts=artifacts, installable=True, updater_transport_version='1.60')
    else:
        if args.public_version:
            parser.error('--public-version requires --candidate')
        folder = args.release
        manifest = json.loads((folder / 'manifest.json').read_text())
    files = {name.rsplit('.', 1)[-1]: (folder / name, item['sha256']) for name, item in manifest['artifacts'].items()}
    image, wav = (files[kind][0].read_bytes() for kind in ('bin', 'wav'))
    if sha(image) != files['bin'][1] or sha(wav) != files['wav'][1]:
        parser.error('Release files do not match their manifest')
    if manifest.get('installable') is not True:
        parser.error('Only installable releases can become a Studio patch')
    version = tuple(int(part) for part in manifest['updater_transport_version'].split('.'))
    release = {key: manifest[key] for key in RELEASE_KEYS if key in manifest}
    patch = lumon_build.make_patch(raw, image, release=release, base=base, header_version=version)
    if patch['result']['wav_sha256'] != files['wav'][1]:
        parser.error('Rebuilt updater does not match the release WAV')
    data = lumon_build.dump_patch(patch)
    output = args.output or ROOT / 'volcastudio/data/firmware' / f'databeat-os-{manifest["version"]}.patch.json'
    output.write_bytes(data)
    literal = sum(len(op[2]) // 2 for op in patch['operations'] if op[0] == 'lit')
    copied = sum(op[3] for op in patch['operations'] if op[0] == 'copy')
    print(json.dumps({'output': str(output.relative_to(ROOT) if output.is_relative_to(ROOT) else output),
                      'patch_sha256': sha(data), 'literal_firmware_bytes': literal,
                      'copied_from_user_image_bytes': copied, 'operations': len(patch['operations']),
                      'result': patch['result']}, indent=2))


if __name__ == '__main__':
    main()
