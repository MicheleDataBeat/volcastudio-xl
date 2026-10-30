"""Exact single-pattern conversion between the LMX2 and LMX3 extension formats.

Technical helper of the shared backend: the groove editor uses it to give a
native pattern the DataBeat OS 1.0 pattern format (native → LMX2 packing →
LMX3). VolcaStudio XL offers no conversion command; bank-level conversion is
an internal tool. A payload that cannot be represented exactly is returned
unchanged with its issues; nothing is approximated.
"""
from .pattern_format import (PACKED_LIMIT, PREDICTABILITY_MASKS,
    INTERNAL_PREDICTABILITY_MASKS, PREDICTABILITY_OFFSETS, motion_value,
    predictability, validate_lmx2, validate_lmx3)
from .patterns import Pattern, FIRMWARE_FORMATS


def _issue(pattern, kind, message, **details):
    location = 'Current snapshot' if pattern.slot is None else f'Memory {pattern.slot + 1}'
    return dict(slot=pattern.slot, kind=kind, message=f'{location}: {message}', **details)


def _put(raw, base, step, motion, mode, internal):
    """Replace precisely the owned 26-bit field, retaining neighboring step bits."""
    offset = base + PREDICTABILITY_OFFSETS[step >> 2]
    shift = 2 * (step & 3)
    if internal:
        number = motion + mode * PACKED_LIMIT
        raw[base + 0xa0 + step] = number & 255
        raw[base + 0xb0 + step] = (number >> 8) & 255
        raw[base + 0x110 + step] = (number >> 16) & 255
        upper = number >> 24
    else:
        raw[base + 0xa0 + step] = motion & 255
        raw[base + 0xb0 + step] = (motion >> 8) & 255
        raw[base + 0x110 + step] = (motion >> 16) | ((mode >> 2) << 6)
        upper = mode & 3
    raw[offset] = (raw[offset] & ~(3 << shift)) | (upper << shift)


def convert_pattern(pattern, firmware):
    """Convert one LMX2/LMX3 payload exactly, or return it unchanged with the issues."""
    if pattern.firmware not in FIRMWARE_FORMATS:
        return pattern, [_issue(pattern, 'unsupported_source',
            f'{pattern.pattern_format} is retained unchanged; select only LMX2/LMX3 patterns for conversion')]
    validator = validate_lmx3 if pattern.pattern_format == 'LMX3' else validate_lmx2
    try:
        validator(pattern)
    except ValueError as exc:
        return pattern, [_issue(pattern, 'invalid_source', str(exc))]
    if pattern.firmware == firmware:
        return pattern, []

    internal = firmware == 'lumon-xl-internal'
    source_masks = PREDICTABILITY_MASKS if internal else INTERNAL_PREDICTABILITY_MASKS
    target_masks = INTERNAL_PREDICTABILITY_MASKS if internal else PREDICTABILITY_MASKS
    target_ids = {mask: mode for mode, mask in enumerate(target_masks)}
    issues, settings = [], []
    for part in range(10):
        excluded = pattern.data[part * 256 + 0x3b]
        if internal and excluded & 0xf0:
            issues.append(_issue(pattern, 'reserved_bar_bits',
                f'part {part + 1} has nonzero reserved LMX2 bar bits (0x{excluded:02x}); converting would discard them',
                part=part + 1, excluded=excluded))
        if not internal and (excluded & 15) != (excluded >> 4):
            issues.append(_issue(pattern, 'bar_filter',
                f'part {part + 1} has different bar filters in bars 1–4 and 5–8 (0x{excluded:02x}); LMX2 cannot represent both',
                part=part + 1, excluded=excluded))
        modes = predictability(pattern, part + 1)
        target_modes = []
        for step, mode in enumerate(modes):
            mask = source_masks[mode]
            if mask not in target_ids:
                issues.append(_issue(pattern, 'predictability_mask',
                    f'part {part + 1}, step {step + 1}: P.{mode:02d} mask 0x{mask:02x} has no exact LMX2 equivalent',
                    part=part + 1, step=step + 1, source_mode=mode, mask=mask))
            target_modes.append(target_ids.get(mask))
        settings.append((excluded, target_modes))
    if issues:
        return pattern, issues  # validation/representability precede every mutation

    raw = bytearray(pattern.data)
    for part, (excluded, modes) in enumerate(settings):
        base = part * 256
        raw[base + 0x3b] = excluded | (excluded << 4) if internal else excluded & 15
        for step, mode in enumerate(modes):
            cells = (motion_value(pattern, part + 1, step + 1, param) for param in (3, 4, 10))
            motion = sum((value - 127 if value else 0) * 129 ** index
                         for index, value in enumerate(cells))
            _put(raw, base, step, motion, mode, internal)
    raw[0xa20:0xa24] = FIRMWARE_FORMATS[firmware]
    result = Pattern(pattern.slot, bytes(raw))
    (validate_lmx3 if internal else validate_lmx2)(result)
    return result, []
