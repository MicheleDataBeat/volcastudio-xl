#!/usr/bin/env python3
"""Check that Studio packages or source trees distribute no Korg firmware.

Given the official Korg updater (read locally, never copied), every file is
searched, recursively inside zip and tar archives:

* for any run of 31 or more bytes of the Korg firmware image (16-byte windows
  with at least six distinct values, sampled every 16 bytes), also inside long
  hexadecimal strings; counting sequences and the public CRC16-CCITT table are
  not firmware content and are ignored;
* for any WAV that decodes as a Volca Sample system updater;
* for each DataBeat OS patch: its literal data must contain no 8-byte span of the
  Korg image, and it must target the expected Korg base.

Allowed: the Korg SYRO SDK sources and converter (BSD-3-Clause), including
image windows that also occur in that SDK, such as the "KORG SYSTEM FILE"
format marker. Exit status 1 on any finding. Example:

  python tools/check_distribution.py --korg-updater volcasample_updater_1_42.zip build/release/VolcaStudio-XL-*
"""
import argparse
import gzip
import io
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import lumon_build, updater_codec  # noqa: E402

WINDOW = 16
HEX = re.compile(rb'[0-9a-fA-F]{64,}')


def _crc16_table():
    rows = []
    for value in range(256):
        crc = value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021 if crc & 0x8000 else crc << 1) & 0xffff
        rows.append(crc)
    return b''.join(r.to_bytes(2, 'little') for r in rows), b''.join(r.to_bytes(2, 'big') for r in rows)


def _ecc_table():
    rows = []
    for value in range(256):
        parity = 0
        for bit, basis in enumerate(updater_codec.ECC_BASIS):
            if value & (1 << bit):
                parity ^= basis
        rows.append(parity)
    return bytes(rows)


# Public tables of the SYRO transport (BSD-3-Clause SDK), also used by the firmware.
# Compilers place the SDK CRC table directly before its ECC table, as Korg's image does (owner-approved, 17 Oct 2026).
PUBLIC_TABLES = (*_crc16_table(), _ecc_table(), *(crc + _ecc_table() for crc in _crc16_table()))


def generic(window):
    """Counting/fill sequences and public SYRO tables carry no firmware content."""
    for lanes in (2, 4):
        if all(len({(window[i + lanes] - window[i]) & 0xff for i in range(j, WINDOW - lanes, lanes)}) == 1
               for j in range(lanes)):
            return True
    steps = [(window[i + 1] - window[i]) & 0xff for i in range(WINDOW - 1)]
    common = sorted((steps.count(s) for s in set(steps)), reverse=True)
    if sum(common[:2]) >= WINDOW - 3:
        return True
    return any(window in table for table in PUBLIC_TABLES)


class Scanner:
    def __init__(self, korg_wav):
        self.image = updater_codec.decode(korg_wav).binary()
        self.korg_wav_sha = lumon_build._sha(korg_wav)
        self.grams = {}
        for offset in range(len(self.image) - WINDOW + 1):
            gram = self.image[offset:offset + WINDOW]
            if len(set(gram)) >= 6 and not generic(gram):
                self.grams.setdefault(gram, offset)
        # Windows Korg itself publishes in the BSD-3-Clause SYRO SDK (such as the
        # "KORG SYSTEM FILE" format marker) are licensed for redistribution.
        self.allowed = []
        for source in sorted((ROOT / 'vendor/korg-syro').rglob('*')):
            if source.is_file():
                data = source.read_bytes()
                for offset in range(len(data) - WINDOW + 1):
                    gram = data[offset:offset + WINDOW]
                    if gram in self.grams:
                        self.allowed.append(gram.decode('latin-1'))
                        del self.grams[gram]
        self.findings = []
        self.files = 0
        self.patches = []

    def scan(self, name, data):
        self.files += 1
        self.search(name, data)
        for match in HEX.finditer(data):
            text = match.group()
            self.search(f'{name} (hex at {match.start()})', bytes.fromhex(text[:len(text) // 2 * 2].decode()))
        if data[:4] == b'RIFF' and data[8:12] == b'WAVE':
            try:
                transfer = updater_codec.decode(data)
            except (ValueError, EOFError, Exception):
                transfer = None
            if transfer is not None:
                self.findings.append(f'{name}: Volca Sample system updater audio')
        if name.endswith('.patch.json'):
            self.check_patch(name, data)
        self.descend(name, data)

    def search(self, name, data):
        for offset in range(0, len(data) - WINDOW + 1, WINDOW):
            korg = self.grams.get(data[offset:offset + WINDOW])
            if korg is not None:
                self.findings.append(f'{name}: Korg image bytes at file offset {offset} (image offset 0x{korg:05x})')
                return

    def check_patch(self, name, data):
        patch = json.loads(data)
        overlaps = lumon_build.literal_overlaps(patch['operations'], self.image)
        if overlaps or patch['base']['wav_sha256'] != self.korg_wav_sha:
            self.findings.append(f'{name}: patch literal data contains Korg bytes at {overlaps[:5]}'
                                 if overlaps else f'{name}: patch targets another Korg updater')
        literal = sum(len(op[2]) // 2 for op in patch['operations'] if op[0] == 'lit')
        self.patches.append({'file': name, 'release': patch['release']['name'], 'literal_bytes': literal,
                             'korg_bytes_in_literals': len(overlaps)})

    def descend(self, name, data):
        try:
            if data[:4] == b'PK\x03\x04':
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    for info in archive.infolist():
                        if not info.is_dir():
                            self.scan(f'{name}!{info.filename}', archive.read(info))
            elif data[:2] == b'\x1f\x8b':
                inner = gzip.decompress(data)
                if len(inner) > 262 and inner[257:262] == b'ustar':
                    self.tar(name, inner)
                else:
                    self.scan(f'{name}!gunzip', inner)
            elif len(data) > 262 and data[257:262] == b'ustar':
                self.tar(name, data)
        except (zipfile.BadZipFile, OSError, EOFError, tarfile.TarError):
            pass

    def tar(self, name, data):
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                if member.isfile():
                    self.scan(f'{name}!{member.name}', archive.extractfile(member).read())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--korg-updater', type=Path, required=True)
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--require-patch', action='store_true', help='Fail unless a DataBeat OS patch was found and checked')
    args = parser.parse_args()
    patch = json.loads(lumon_build.PATCH_FILE.read_bytes())
    scanner = Scanner(lumon_build.read_updater(args.korg_updater, patch))
    for path in args.paths:
        if path.is_dir() and (path / '.git').exists():
            # A checkout: what is committed is what can be distributed.
            import subprocess
            listed = subprocess.run(['git', '-C', str(path), 'ls-files', '-z'], capture_output=True, check=True).stdout
            files = [path / name for name in listed.decode().split('\0') if name and (path / name).is_file()]
        else:
            files = sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
        for file in files:
            scanner.scan(str(file), file.read_bytes())
    if args.require_patch and not scanner.patches:
        scanner.findings.append('No DataBeat OS patch found')
    print(json.dumps({'passed': not scanner.findings, 'files_scanned': scanner.files, 'patches': scanner.patches,
                      'allowed_windows_published_in_bsd_syro_sdk': scanner.allowed,
                      'findings': scanner.findings[:50]}, indent=2))
    return 1 if scanner.findings else 0


if __name__ == '__main__':
    sys.exit(main())
