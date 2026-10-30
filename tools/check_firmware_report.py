#!/usr/bin/env python3
"""Require the real Korg-updater build in an offline report or firmware listing.

  python tools/check_firmware_report.py build/release/offline-verification/report.json
  python tools/check_firmware_report.py --listing firmware.json   # JSON from firmware.list_firmware

Checks the single production build and the Korg choice: classification and exact
hashes.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import lumon_build  # noqa: E402


def find(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for item in value.values():
            yield from find(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from find(item, key)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path', type=Path)
    parser.add_argument('--listing', action='store_true')
    args = parser.parse_args()
    patch = lumon_build.load_patch()
    expected = [patch['result']['wav_sha256'], patch['base']['wav_sha256']]
    data = json.loads(args.path.read_text())
    if args.listing:
        problems = []
        hashes = [e['sha256'] for e in data]
        if hashes != expected:
            problems.append(f'listed {[e["name"] for e in data]}, expected exactly DataBeat OS and the Korg updater')
        for entry in data:
            if not entry['installable'] or entry['experimental'] is not False or entry['hardware_tested'] is not True:
                problems.append(f'{entry["name"]} has incorrect release classification')
            if hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest() != entry['sha256']:
                problems.append(f'{entry["name"]} file differs from its checksum')
        summary = [f'{e["name"]} {e["sha256"]}' for e in data]
    else:
        builds = list(find(data, 'korg_updater_build'))
        problems = [] if builds and all(isinstance(b, dict) and b.get('bit_identical') is True for b in builds) else \
            [f'Real Korg updater build missing or not bit-identical: {builds}']
        if builds and isinstance(builds[0], dict) and builds[0].get('firmware_sha256') != expected[0]:
            problems.append('Unexpected DataBeat OS checksum')
        if list(find(data, 'internal_updater_build')):
            problems.append('An internal build appears in a public report')
        summary = builds
    print(json.dumps({'passed': not problems, 'expected_sha256': expected, 'found': summary, 'problems': problems}, indent=2))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
