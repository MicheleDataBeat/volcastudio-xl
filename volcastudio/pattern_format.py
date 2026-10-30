"""Lossless LMX2/LMX3 validation and read helpers; timing edits in both formats.

Parts and steps in the public helpers are numbered 1–10 and 1–16. Motion
parameters use the device's 0–10 control indices. Packed motion contains the
three original raw cells (absent 0, present 128–255), without quantization.
"""
import struct

from .patterns import Pattern

MAGIC = b'LMX2'
INTERNAL_MAGIC = b'LMX3'
MAGIC_OFFSET = 0xa20
PREDICTABILITY_MASKS = (0xff, 0x01, 0x80, 0x11, 0x88, 0x55, 0xaa, 0x77, 0xee,
                         0x51, 0x15, 0x45, 0x57, 0xae, 0xea, 0xa8)
PREDICTABILITY_LABELS = ('ALL', 'X0000000', '0000000X', 'X000X000', '000X000X',
                         'X0X0X0X0', '0X0X0X0X', 'XXX0XXX0', '0XXX0XXX',
                         'X000X0X0', 'X0X0X000', 'X0X000X0', 'XXX0X0X0',
                         '0XXX0X0X', '0X0X0XXX', '000X0X0X')
INTERNAL_PREDICTABILITY_MASKS = (255,1,128,17,136,21,168,69,73,81,85,254,127,238,119,234,87,186,182,174,170,15,240,36)
PREDICTABILITY_OFFSETS = (0x35, 0x36, 0x37, 0x39)
MOTION_ROWS = (0, 2, 4, 6, 7, 8, 9, 10, 11, 12, 13)
PACKED_PARAMS = (3, 4, 10)
RADIX = 129
PACKED_LIMIT = RADIX ** 3
MICRO_OFFSETS = (0x26, 0x27, 0x38, 0x3a, 0x3c, 0x3d, 0x3e, 0x3f)


def _part(part):
    if type(part) is not int or not 1 <= part <= 10:
        raise ValueError('Pattern part must be 1–10')
    return (part - 1) * 256


def _step(step):
    if type(step) is not int or not 1 <= step <= 16:
        raise ValueError('Pattern step must be 1–16')
    return step - 1


def _require_xl(pattern, marker=None):
    if not isinstance(pattern, Pattern) or not pattern.initialized:
        raise ValueError('An initialized extension-format pattern is required')
    actual = pattern.data[MAGIC_OFFSET:MAGIC_OFFSET + 4]
    if actual not in ((marker,) if marker is not None else (MAGIC, INTERNAL_MAGIC)):
        expected = marker.decode() if marker is not None else 'LMX2 or LMX3'
        raise ValueError(f'{expected} is required; pattern formats are not converted implicitly')
    return actual


def _joint(raw, base, step):
    return (raw[base+0xa0+step] | raw[base+0xb0+step]<<8 | raw[base+0x110+step]<<16 |
            ((raw[base+PREDICTABILITY_OFFSETS[step>>2]]>>(2*(step&3)))&3)<<24)


def _code(raw, base, step):
    return raw[base + 0xa0 + step] | raw[base + 0xb0 + step] << 8 | (raw[base + 0x110 + step] & 63) << 16


def _put(raw, base, step, code):
    raw[base + 0xa0 + step] = code & 255
    raw[base + 0xb0 + step] = (code >> 8) & 255
    index = base + 0x110 + step
    raw[index] = (raw[index] & 192) | (code >> 16)


def _mode(raw, base, step):
    return ((raw[base + PREDICTABILITY_OFFSETS[step >> 2]] >> (2 * (step & 3))) & 3) | ((raw[base + 0x110 + step] >> 6) << 2)


def validate_lmx2(pattern):
    """Reject impossible packed cells before any device write."""
    _require_xl(pattern, MAGIC)
    for part in range(10):
        base = part * 256
        for step in range(16):
            if _mode(pattern.data, base, step) >= len(PREDICTABILITY_MASKS):
                raise ValueError(f'Invalid Predictability mode at part {part + 1}, step {step + 1}')
            if _code(pattern.data, base, step) >= PACKED_LIMIT:
                raise ValueError(f'Invalid packed motion at part {part + 1}, step {step + 1}')
    return pattern


def validate_lmx3(pattern):
    """All 26 bits jointly store motion + mode*129^3; unused codes fail closed."""
    _require_xl(pattern, INTERNAL_MAGIC)
    for part in range(10):
        for step in range(16):
            if _joint(pattern.data, part*256, step) >= len(INTERNAL_PREDICTABILITY_MASKS)*PACKED_LIMIT:
                raise ValueError(f'Invalid LMX3 joint motion/Predictability at part {part+1}, step {step+1}')
    return pattern


def validate_xl(pattern):
    """Validate an LMX2 or LMX3 payload against its own marker."""
    marker = _require_xl(pattern)
    return validate_lmx3(pattern) if marker == INTERNAL_MAGIC else validate_lmx2(pattern)


def for_firmware(pattern, firmware):
    """Validate the selected destination without converting extension formats."""
    if firmware == 'lumon-xl':
        return convert_native(pattern)
    if firmware == 'lumon-xl-internal':
        if pattern.firmware == 'pajen7':
            convert_native(pattern)  # validate native cells; firmware initializes its own format
            return pattern           # preserve the archived native payload exactly
        return validate_lmx3(pattern)
    raise ValueError('Unknown pattern format profile')


def predictability(pattern, part):
    marker = _require_xl(pattern)
    base = _part(part)
    internal = marker == INTERNAL_MAGIC
    result = tuple((_joint(pattern.data, base, step)//PACKED_LIMIT if internal else _mode(pattern.data, base, step)) for step in range(16))
    if any(mode >= len(INTERNAL_PREDICTABILITY_MASKS if internal else PREDICTABILITY_MASKS) for mode in result):
        raise ValueError('Invalid Predictability mode')
    return result


def set_predictability(pattern, part, values):
    """Set a complete part's IDs while preserving all ordinary motion cells."""
    validate_lmx2(pattern)
    base = _part(part)
    if not isinstance(values, (tuple, list)) or len(values) != 16 or any(type(mode) is not int or not 0 <= mode < len(PREDICTABILITY_MASKS) for mode in values):
        raise ValueError('Predictability requires sixteen mode IDs from 0 (ALL) to 15')
    raw = bytearray(pattern.data)
    for step, mode in enumerate(values):
        index = base + PREDICTABILITY_OFFSETS[step >> 2]
        shift = 2 * (step & 3)
        raw[index] = (raw[index] & ~(3 << shift)) | ((mode & 3) << shift)
        index = base + 0x110 + step
        raw[index] = (raw[index] & 63) | ((mode >> 2) << 6)
    return Pattern(pattern.slot, bytes(raw))


def motion_value(pattern, part, step, param):
    """Read one original primary raw motion cell; paired secondary rows remain raw."""
    marker = _require_xl(pattern)
    base, step = _part(part), _step(step)
    if type(param) is not int or not 0 <= param <= 10:
        raise ValueError('Motion parameter must be 0–10')
    if param not in PACKED_PARAMS:
        return pattern.data[base + 0x40 + 16 * MOTION_ROWS[param] + step]
    code = _joint(pattern.data, base, step) if marker == INTERNAL_MAGIC else _code(pattern.data, base, step)
    if marker == INTERNAL_MAGIC:
        if code >= len(INTERNAL_PREDICTABILITY_MASKS)*PACKED_LIMIT:
            raise ValueError('Invalid LMX3 joint motion/Predictability')
        code %= PACKED_LIMIT
    if code >= PACKED_LIMIT:
        raise ValueError('Invalid packed motion')
    index = (code // RADIX ** PACKED_PARAMS.index(param)) % RADIX
    return index + 127 if index else 0


def microtiming(pattern, part):
    """Read effective LMX2/LMX3 timing; format and validity are never inferred."""
    _require_xl(pattern)
    base = _part(part)
    index = part - 1
    valid = struct.unpack_from('<H', pattern.data, 0xa30)[0]
    if not valid & (1 << index):
        return (0,) * 16
    plane = struct.unpack_from('<H', pattern.data, 12 + index * 2)[0]
    result = []
    for offset in MICRO_OFFSETS:
        byte = pattern.data[base + offset]
        for nibble in (byte & 15, byte >> 4):
            code = nibble | (((plane >> len(result)) & 1) << 4)
            result.append(max(-15, code - 32 if code >= 16 else code))
    return tuple(result)


def set_motion_value(pattern, part, step, param, raw_value):
    """Write a primary raw cell; paired secondary rows and format flags stay intact.

    The three packed ordinary parameters require absent 0 or present 128–255.
    Other rows retain their native byte representation, including low SPEED
    values and musical-EG/slice tags when enabled by their separate flags.
    """
    validate_lmx2(pattern)
    base, step = _part(part), _step(step)
    if type(param) is not int or not 0 <= param <= 10:
        raise ValueError('Motion parameter must be 0–10')
    if type(raw_value) is not int or not 0 <= raw_value <= 255:
        raise ValueError('Motion raw value must be an integer byte from 0 to 255')
    if param in PACKED_PARAMS and raw_value != 0 and raw_value < 128:
        raise ValueError('Motion raw value must be absent (0), or present (128–255)')
    raw = bytearray(pattern.data)
    if param not in PACKED_PARAMS:
        raw[base + 0x40 + 16 * MOTION_ROWS[param] + step] = raw_value
    else:
        divisor = RADIX ** PACKED_PARAMS.index(param)
        code = _code(raw, base, step)
        old = (code // divisor) % RADIX
        new = raw_value - 127 if raw_value else 0
        _put(raw, base, step, code + (new - old) * divisor)
    return Pattern(pattern.slot, bytes(raw))


def set_microtiming(pattern, part, values):
    """Replace a part's offsets, touching only its timing fields and valid bit.

    The timing fields are the same in LMX2 and LMX3; the marker is kept.
    """
    validate_xl(pattern)
    base = _part(part)
    if not isinstance(values, (tuple, list)) or len(values) != 16 or any(type(value) is not int or not -15 <= value <= 15 for value in values):
        raise ValueError('Microtiming requires sixteen integer offsets from −15 to +15')
    raw = bytearray(pattern.data)
    for step, value in enumerate(values):
        index, shift = base + MICRO_OFFSETS[step >> 1], 4 * (step & 1)
        raw[index] = (raw[index] & ~(15 << shift)) | ((value & 15) << shift)
    struct.pack_into('<H', raw, 12 + 2 * (part - 1), sum(((value & 31) >> 4) << step for step, value in enumerate(values)))
    valid = struct.unpack_from('<H', raw, 0xa30)[0] | 1 << (part - 1)
    struct.pack_into('<H', raw, 0xa30, valid)
    return Pattern(pattern.slot, bytes(raw))


def convert_native(pattern):
    """Initialize native Korg padding and pack canonical motion without loss.

    Legacy extension signatures are refused. Native reserved extension bytes
    are initialized exactly as firmware does; notes, controls and ordinary
    motion survive unchanged in their decoded representation.
    """
    if not isinstance(pattern, Pattern) or not pattern.initialized:
        raise ValueError('Cannot convert an opaque/uninitialized pattern')
    marker = pattern.data[MAGIC_OFFSET:MAGIC_OFFSET + 4]
    if marker == MAGIC:
        return validate_lmx2(pattern)
    if marker.startswith((b'LUM', b'LMX')):
        raise ValueError('Legacy pattern format is unsupported; no implicit conversion to LMX2')
    for part in range(10):
        for step in range(16):
            for offset in (0xa0, 0xb0, 0x110):
                value = pattern.data[part * 256 + offset + step]
                if value != 0 and value < 128:
                    raise ValueError(f'Noncanonical native motion at part {part + 1}, step {step + 1}; original retained')
    raw = bytearray(pattern.data)
    for part in range(10):
        base = part * 256
        for step in range(16):
            values = [raw[base + offset + step] for offset in (0xa0, 0xb0, 0x110)]
            code = sum((value - 127 if value else 0) * RADIX ** index for index, value in enumerate(values))
            raw[base + 0x110 + step] = 0
            _put(raw, base, step, code)
        for offset in (*PREDICTABILITY_OFFSETS, 0x3b):
            raw[base + offset] = 0
    raw[12:32] = bytes(20)
    raw[0xa20:0xa3c] = bytes(28)
    raw[0xa20:0xa24] = MAGIC
    return Pattern(pattern.slot, bytes(raw))
