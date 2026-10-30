"""Lossless Volca Sample v1 archives and DataBeat OS pattern files.

The complete 2624 bytes are retained. MIDI 40 loads the current edit buffer;
4C is a dump response, not a persistent write to a memory slot. Stored slots
are restored with SYRO pattern transfers.
"""
import base64
import binascii
import hashlib
import json
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

PATTERN_SIZE = 0xa40
SLOT_COUNT = 10
SYSEX_HEADER = bytes.fromhex('f0 42 30 00 01 2d')
BANK_FORMAT = 'volcastudio-pattern-bank'
MAX_BANK_BYTES = 256 * 1024
DEFAULT_CONTROLS = bytes([127, 64, 64, 0, 127, 64, 0, 127, 0, 127, 127])
# Storage and wire tokens of the two extension formats, by marker.
FIRMWARE_FORMATS = {'lumon-xl': b'LMX2', 'lumon-xl-internal': b'LMX3'}
# The pattern format of DataBeat OS 1.0 (marker LMX3), the only profile that
# VolcaStudio XL offers. LMX2 stays readable for the internal tools.
PATTERN_PROFILE = 'lumon-xl-internal'
FIRMWARE_LABELS = {PATTERN_PROFILE: 'DataBeat OS 1.0 pattern format'}


@dataclass(frozen=True)
class Pattern:
    slot: int | None
    data: bytes

    def __post_init__(self):
        if self.slot is not None and (type(self.slot) is not int or not 0 <= self.slot < SLOT_COUNT):
            raise ValueError('Pattern slot must be 0–9, or null for the current edit buffer')
        if not isinstance(self.data, bytes):
            raise ValueError('Pattern data must be immutable bytes')
        if len(self.data) != PATTERN_SIZE:
            raise ValueError(f'Pattern must contain exactly {PATTERN_SIZE} bytes')
        if self.slot is None and not self.initialized:
            raise ValueError('Invalid Volca Sample v1 pattern signature/device/footer')

    @property
    def initialized(self):
        return self.data[:6] == b'PTST\xb8\x33' and self.data[-4:] == b'PTED'

    @property
    def firmware(self):
        # Flash can contain uninitialized slots or the two original opaque
        # Pajen-overlaid OK GO templates. Archive their exact bytes; native
        # 9068 initializes only the live buffer when such a slot is selected.
        if not self.initialized:
            return 'opaque'
        marker = self.data[0xa20:0xa24]
        if marker == b'LMX3':
            return 'lumon-xl-internal'
        if marker.startswith((b'LUM', b'LMX')) and marker != b'LMX2':
            return 'unsupported'
        return 'lumon-xl' if marker == b'LMX2' else 'pajen7'

    @property
    def pattern_format(self):
        if not self.initialized:
            return 'opaque'
        marker = self.data[0xa20:0xa24]
        if marker.startswith((b'LMX', b'LUM')):
            return marker.decode('ascii', errors='replace')
        return 'native'

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def pack7(data):
    packed = bytearray()
    for offset in range(0, len(data), 7):
        group = data[offset:offset + 7]
        packed.append(sum(((value >> 7) & 1) << i for i, value in enumerate(group)))
        packed.extend(value & 127 for value in group)
    return bytes(packed)


def unpack7(data, expected_size=None):
    if any(value > 127 for value in data):
        raise ValueError('SysEx payload contains a non-data MIDI byte')
    raw = bytearray()
    for offset in range(0, len(data), 8):
        group = data[offset:offset + 8]
        if len(group) < 2 or group[0] >> (len(group) - 1):
            raise ValueError('Incomplete or noncanonical Korg 7-bit group')
        raw.extend(value | (((group[0] >> i) & 1) << 7) for i, value in enumerate(group[1:]))
    if expected_size is not None and len(raw) != expected_size:
        raise ValueError(f'SysEx has {len(raw)} pattern bytes; expected {expected_size}')
    return bytes(raw)


def parse_sysex(data):
    # MIDI realtime may be interleaved with SysEx. It is never pattern data.
    clean = bytes(value for value in data if value < 0xf8)
    patterns = []
    offset = 0
    while offset < len(clean):
        if not clean.startswith(SYSEX_HEADER, offset):
            raise ValueError('Expected a Volca Sample v1 pattern dump')
        end = clean.find(b'\xf7', offset)
        if end < 0:
            raise ValueError('Truncated SysEx frame')
        frame = clean[offset:end]
        if len(frame) < 7:
            raise ValueError('Truncated SysEx header')
        command = frame[6]
        if command == 0x40:
            slot = None
            payload = frame[7:]
        elif command == 0x4c and len(frame) >= 8:
            slot = frame[7]
            payload = frame[8:]
        else:
            raise ValueError('This SysEx is not a current/stored pattern dump')
        patterns.append(Pattern(slot, unpack7(payload, PATTERN_SIZE)))
        offset = end + 1
    if not patterns:
        raise ValueError('No pattern dump found')
    return patterns


def encode_sysex(pattern):
    """Load the edit buffer; the slot is intentionally not encoded as a write."""
    return SYSEX_HEADER + b'\x40' + pack7(pattern.data) + b'\xf7'


def request_current_dump():
    return SYSEX_HEADER + b'\x10\xf7'


def request_stored_dump(slot):
    if type(slot) is not int or not 0 <= slot < SLOT_COUNT:
        raise ValueError('Pattern slot must be 0–9')
    return SYSEX_HEADER + bytes([0x1c, slot, 0xf7])


def blank_pattern(firmware='lumon-xl', slot=None):
    """Empty defaults for the selected format: ALL and every bar admitted.

    Motion, notes, accents, loop/reverse/reverb-send and extensions are reset.
    This resets pattern data, not the instrument's separate GLOBAL settings.
    """
    if firmware not in FIRMWARE_FORMATS:
        raise ValueError('Unknown pattern format profile')
    raw = bytearray(PATTERN_SIZE)
    raw[:8] = b'PTST\xb8\x33\xff\0'
    struct.pack_into('<H', raw, 8, 0xffff)
    # Pajen repurposes bit zero here as drone; native initialization's 127
    # enables it. A neutral reset explicitly turns it off.
    raw[10] = 0
    for part in range(SLOT_COUNT):
        base = part * 256
        struct.pack_into('<H', raw, base + 0x20, part)
        raw[base + 0x28] = 127
        raw[base + 0x29:base + 0x34] = DEFAULT_CONTROLS
    raw[0xa20:0xa24] = FIRMWARE_FORMATS[firmware]
    raw[-4:] = b'PTED'
    return Pattern(slot, bytes(raw))


def _unique(patterns):
    patterns = list(patterns)
    if not 1 <= len(patterns) <= SLOT_COUNT + 1 or any(not isinstance(p, Pattern) for p in patterns):
        raise ValueError('A bank must contain 1–10 memory patterns and optionally the current edit buffer')
    if len({p.slot for p in patterns}) != len(patterns):
        raise ValueError('Duplicate pattern slot/current edit buffer in bank')
    return patterns


def bank_to_json(patterns):
    patterns = _unique(patterns)
    return json.dumps({'format': BANK_FORMAT, 'version': 1,
                       'patterns': [{'slot': p.slot, 'firmware': p.firmware, 'sha256': p.sha256,
                                     'data_base64': base64.b64encode(p.data).decode('ascii')} for p in patterns]}, indent=2) + '\n'


def bank_from_json(text):
    if len(text.encode('utf-8')) > MAX_BANK_BYTES:
        raise ValueError('Pattern bank is too large')
    value = json.loads(text)
    if not isinstance(value, dict) or value.get('format') != BANK_FORMAT or value.get('version') != 1:
        raise ValueError('Unsupported pattern bank format/version')
    records = value.get('patterns')
    if not isinstance(records, list) or not 1 <= len(records) <= SLOT_COUNT + 1:
        raise ValueError('Invalid pattern bank records')
    patterns = []
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get('data_base64'), str) or len(item['data_base64']) > 3500:
            raise ValueError('Invalid pattern data record')
        try:
            raw = base64.b64decode(item['data_base64'], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid base64 pattern payload') from exc
        pattern = Pattern(item.get('slot'), raw)
        declared = item.get('firmware')
        # Earlier banks keep their truthful historical profile label. Accept
        # that metadata only for its exact known marker, while classifying the
        # payload as unsupported for XL edits/transfers. Never rewrite bytes.
        historical = {b'LUM1': 'lumon', b'LMX1': 'lumon-xl', b'LMX3': 'unsupported'}.get(raw[0xa20:0xa24])
        matching_profile = declared == pattern.firmware or (
            historical is not None and declared == historical)
        if item.get('sha256') != pattern.sha256 or not matching_profile:
            raise ValueError('Pattern checksum/profile does not match its complete payload')
        patterns.append(pattern)
    return _unique(patterns)


def archive_kind(patterns):
    """Payload-derived name group; opaque slots do not change a known format."""
    formats = {p.pattern_format for p in patterns} - {'opaque'}
    if not formats:
        return 'opaque'
    if len(formats) > 1:
        return 'mixed'
    value = next(iter(formats))
    return value.lower() if value in ('LMX2', 'LMX3', 'native') else 'legacy'


def load_bank(path):
    path = Path(path).expanduser()
    if path.stat().st_size > MAX_BANK_BYTES:
        raise ValueError('Pattern file is too large')
    data = path.read_bytes()
    if path.suffix.lower() == '.syx' or data.startswith(b'\xf0'):
        return _unique(parse_sysex(data))
    if len(data) == PATTERN_SIZE and data.startswith(b'PTST'):
        return [Pattern(None, data)]
    return bank_from_json(data.decode('utf-8'))


def save_bank(path, patterns):
    """Publish a complete bank atomically, refusing any existing destination."""
    path = Path(path).expanduser()
    text = bank_to_json(patterns)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging = tempfile.mkstemp(prefix='.pattern-bank-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.link(staging, path)  # exclusive publication, no partial destination
    finally:
        Path(staging).unlink(missing_ok=True)
    return path
