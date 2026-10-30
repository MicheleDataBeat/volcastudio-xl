"""Static timing grids and lossless offline pattern timing modifications.

Parts are numbered 1–10 in this API. Stored slots remain zero-based like
``patterns.Pattern``. No function here opens a device or generates audio.
"""
import hashlib
import json
import os
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from .patterns import Pattern, PATTERN_PROFILE, SLOT_COUNT, bank_to_json, blank_pattern, save_bank
from .pattern_format import convert_native, validate_lmx2, validate_lmx3, set_microtiming, microtiming as read_microtiming
from .pattern_conversion import convert_pattern

MICRO_OFFSETS = (0x26, 0x27, 0x38, 0x3a, 0x3c, 0x3d, 0x3e, 0x3f)
LUMON_MAGIC_OFFSET = 0xa20
MICRO_VALID_OFFSET = 0xa30
CATALOG_FORMAT = 'volcastudio-groove-catalog'
CATALOG_PATH = Path(__file__).with_name('data') / 'grooves-xl.json'
# Groove templates write only the timing fields, identical in both formats:
# LMX2 (internal tools) and LMX3, the DataBeat OS 1.0 pattern format.
GROOVE_FORMATS = ('lumon-xl', PATTERN_PROFILE)
MAX_CATALOG_BYTES = 2 * 1024 * 1024
_ID = re.compile(r'[A-Z][A-Z0-9_]{0,95}\Z')


def _round_micro(value):
    """Quantize exactly once; Python round's ties-to-even is not used."""
    magnitude = abs(value)
    rounded = (2 * magnitude.numerator + magnitude.denominator) // (2 * magnitude.denominator)
    return -rounded if value < 0 else rounded


def _vector(value, limit=7):
    if not isinstance(value, (list, tuple)) or len(value) != 16:
        raise ValueError('A groove must contain sixteen microtiming values')
    if any(type(v) is not int or not -limit <= v <= limit for v in value):
        raise ValueError(f'Microtiming must be integer values from −{limit} to +{limit}')
    return tuple(value)


def _profile_id(vector):
    digest = hashlib.sha256(bytes(v & 255 for v in vector)).hexdigest()[:16].upper()
    return 'GROOVE_' + digest


@dataclass(frozen=True)
class GrooveTemplate:
    """A named source/bar/voice alias; several aliases may share one profile."""
    id: str
    display_name: str
    category: str
    profile_id: str
    microtiming: tuple
    exact_microtiming: tuple
    measured_mask: int
    family: int | str | None
    role: str | None
    bar: int | None
    provenance: dict

    @property
    def measured_count(self):
        return self.measured_mask.bit_count()

    @property
    def inferred_count(self):
        return 0 if self.category == 'analytic' else 16 - self.measured_count

    def as_dict(self):
        return {'id': self.id, 'display_name': self.display_name, 'category': self.category,
                'profile_id': self.profile_id, 'microtiming': list(self.microtiming),
                'exact_microtiming': [[v.numerator, v.denominator] for v in self.exact_microtiming],
                'measured_mask': self.measured_mask, 'measured_count': self.measured_count,
                'inferred_count': self.inferred_count, 'family': self.family, 'role': self.role,
                'bar': self.bar, 'provenance': self.provenance}


@dataclass(frozen=True)
class GrooveProfile:
    """One distinct device timing vector, with all its musical labels."""
    id: str
    microtiming: tuple
    aliases: tuple
    display_name: str
    category: str
    categories: tuple


@dataclass(frozen=True)
class Catalog:
    profiles: tuple
    templates: tuple
    sources: dict
    firmware: str = 'lumon-xl'

    def resolve(self, template_id):
        if not isinstance(template_id, str):
            raise ValueError('Choose a groove template or profile ID')
        for template in self.templates:
            if template.id == template_id:
                return template
        for profile in self.profiles:
            if profile.id == template_id:
                return self.resolve(profile.aliases[0])
        raise ValueError(f'Unknown groove template: {template_id}')

    def aliases_for(self, profile_id):
        for profile in self.profiles:
            if profile.id == profile_id:
                return tuple(self.resolve(alias) for alias in profile.aliases)
        raise ValueError(f'Unknown groove profile: {profile_id}')


def _require_format(firmware):
    if firmware not in GROOVE_FORMATS:
        raise ValueError('Groove templates need the DataBeat OS 1.0 pattern format')


def load_catalog(path=None, firmware='lumon-xl'):
    """Read and validate the portable timing-only catalog, including aliases."""
    _require_format(firmware)
    limit = 15
    path = Path(path) if path is not None else CATALOG_PATH.with_name('grooves-xl.json')
    if path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError('Groove catalog is too large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('format') != CATALOG_FORMAT
            or type(value.get('version')) is not int or value['version'] != 1
            or not isinstance(value.get('firmware'), list) or firmware not in value['firmware']
            or value.get('range') != [-limit, limit]
            or value.get('quarter_note_unit') != [1, 128]
            or value.get('rounding') != 'nearest_half_away_from_zero'
            or type(value.get('reference_swing')) is not int or value['reference_swing'] != 0):
        raise ValueError('Unsupported groove catalog format/version/timing')
    sources = value.get('sources')
    if not isinstance(sources, dict):
        raise ValueError('Invalid groove source attribution')
    for source in sources.values():
        if (not isinstance(source, dict) or not isinstance(source.get('title'), str)
                or not isinstance(source.get('url'), str)
                or not source['url'].startswith('https://')):
            raise ValueError('Invalid groove source attribution')
        for key in ('archive_sha256', 'analysis_sha256'):
            if not re.fullmatch('[0-9a-f]{64}', str(source.get(key, ''))):
                raise ValueError('Invalid groove source checksum')
    raw_profiles, raw_templates = value.get('profiles'), value.get('templates')
    if (not isinstance(raw_profiles, list) or not 1 <= len(raw_profiles) <= 1024
            or not isinstance(raw_templates, list) or not 1 <= len(raw_templates) <= 4096):
        raise ValueError('Invalid groove catalog records')
    profile_records = {}
    seen_vectors = set()
    for item in raw_profiles:
        if not isinstance(item, dict):
            raise ValueError('Invalid groove profile')
        vector = _vector(item.get('microtiming'), limit)
        ident, aliases = item.get('id'), item.get('aliases')
        if (ident != _profile_id(vector) or ident in profile_records or vector in seen_vectors
                or not isinstance(aliases, list) or not aliases
                or any(not isinstance(a, str) or not _ID.fullmatch(a) for a in aliases)
                or len(set(aliases)) != len(aliases)):
            raise ValueError('Duplicate or invalid groove profile/aliases')
        profile_records[ident] = (vector, tuple(aliases))
        seen_vectors.add(vector)
    templates = []
    seen_ids = set()
    for item in raw_templates:
        if not isinstance(item, dict):
            raise ValueError('Invalid groove template')
        ident, profile_id = item.get('id'), item.get('profile_id')
        if (not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in seen_ids
                or not isinstance(profile_id, str) or profile_id not in profile_records):
            raise ValueError('Duplicate or invalid groove template ID/profile')
        vector, aliases = profile_records[profile_id]
        exact = item.get('exact_microtiming')
        if not isinstance(exact, list) or len(exact) != 16:
            raise ValueError('Missing exact groove timing provenance')
        fractions = []
        for index, fraction in enumerate(exact):
            if (not isinstance(fraction, list) or len(fraction) != 2
                    or any(type(v) is not int for v in fraction) or fraction[1] <= 0):
                raise ValueError('Invalid exact groove timing fraction')
            timing = Fraction(*fraction)
            if _round_micro(timing) != vector[index]:
                raise ValueError('Groove vector does not match exact source/model timing')
            fractions.append(timing)
        mask, category = item.get('measured_mask'), item.get('category')
        family, role, bar = item.get('family'), item.get('role'), item.get('bar')
        provenance = item.get('provenance')
        if (ident not in aliases or type(mask) is not int or not 0 <= mask <= 0xffff
                or category not in ('analytic', 'mpc3000', 'dilla', 'dangelo')
                or not isinstance(item.get('display_name'), str) or not item['display_name']
                or not isinstance(provenance, dict)
                or (family is not None and type(family) not in (str, int))
                or (role is not None and not isinstance(role, str))
                or (bar is not None and (type(bar) is not int or not 1 <= bar <= 1024))):
            raise ValueError('Invalid groove template metadata')
        if category != 'analytic':
            if (provenance.get('source') not in sources
                    or not re.fullmatch('[0-9a-f]{64}', str(provenance.get('source_sha256', '')))):
                raise ValueError('Missing groove source provenance')
        templates.append(GrooveTemplate(ident, item['display_name'], category, profile_id,
                                        vector, tuple(fractions), mask, family, role, bar, provenance))
        seen_ids.add(ident)
    if seen_ids != {a for _, aliases in profile_records.values() for a in aliases}:
        raise ValueError('Groove alias index does not match templates')
    profiles = []
    by_id = {t.id: t for t in templates}
    for ident, (vector, aliases) in profile_records.items():
        if any(by_id[a].profile_id != ident for a in aliases):
            raise ValueError('Groove alias belongs to a different profile')
        primary = by_id[aliases[0]]
        categories = tuple(dict.fromkeys(by_id[a].category for a in aliases))
        profiles.append(GrooveProfile(ident, vector, aliases, primary.display_name, primary.category, categories))
    return Catalog(tuple(profiles), tuple(templates), sources, firmware)


def _assignments(assignments, catalog):
    if not isinstance(assignments, Mapping):
        raise ValueError('Choose groove templates by part number 1–10')
    result = []
    for part, template_id in assignments.items():
        if type(part) is not int or not 1 <= part <= SLOT_COUNT:
            raise ValueError('Groove part must be 1–10')
        result.append((part, catalog.resolve(template_id)))
    return tuple(sorted(result))


def _validate_pattern(pattern, firmware=None):
    """Validate before any mutation; ``firmware`` is the destination profile."""
    if not isinstance(pattern, Pattern) or not pattern.initialized:
        raise ValueError('Cannot apply a groove to an opaque/uninitialized pattern')
    if pattern.firmware == 'lumon-xl':
        validate_lmx2(pattern)
    elif pattern.firmware == 'lumon-xl-internal':
        validate_lmx3(pattern)
    elif pattern.firmware == 'unsupported':
        raise ValueError('Unsupported legacy pattern format')
    else:
        convert_native(pattern)  # validates canonical motion before any mutation
    if firmware is not None and pattern.firmware in GROOVE_FORMATS and pattern.firmware != firmware:
        raise ValueError('This memory uses another pattern format; grooves never convert formats')


def microtiming(pattern, part):
    """Decode effective offsets, respecting each part's timing-valid bit."""
    _validate_pattern(pattern)
    if type(part) is not int or not 1 <= part <= SLOT_COUNT:
        raise ValueError('Groove part must be 1–10')
    if pattern.firmware not in GROOVE_FORMATS:
        return (0,) * 16
    return read_microtiming(pattern, part)


def _initialized(pattern, firmware):
    """The pattern in the destination format; native payloads are packed losslessly."""
    if pattern.firmware == firmware:
        return pattern
    output = convert_native(pattern)  # native → LMX2 packing, exact
    if firmware == 'lumon-xl':
        return output
    output, issues = convert_pattern(output, firmware)  # LMX2 → LMX3, exact or refused
    if issues:
        raise ValueError(issues[0]['message'])
    return output


def _apply_resolved(pattern, assignments, firmware='lumon-xl'):
    _require_format(firmware)
    _validate_pattern(pattern, firmware)
    if not assignments:
        return pattern
    output = _initialized(pattern, firmware)
    for part, template in assignments:
        output = set_microtiming(output, part, _vector(template.microtiming, 15))
    return output


def apply_pattern(pattern, assignments, catalog=None, firmware='lumon-xl'):
    """Replace all sixteen offsets of selected parts; retain every other byte."""
    _require_format(firmware)
    resolved = _assignments(assignments, catalog or load_catalog(firmware=firmware))
    return _apply_resolved(pattern, resolved, firmware)


@dataclass(frozen=True)
class GroovePlan:
    selected_patterns: tuple
    rollback_patterns: tuple
    full_source: tuple
    assignments: tuple
    slots: tuple
    changes: tuple
    reset: bool = False
    firmware: str = 'lumon-xl'
    unbacked_slots: tuple = ()

    @property
    def changed_bytes(self):
        return sum(len(indices) for _, indices in self.changes)

    @property
    def original_backup_available(self):
        return bool(self.full_source)

    def as_dict(self):
        return {'firmware': self.firmware, 'slots': [n + 1 for n in self.slots],
                'mode': 'reset+groove' if self.reset else 'preserve',
                'assignments': [{'part': part, 'template': template.id,
                                 'profile_id': template.profile_id,
                                 'measured_count': template.measured_count,
                                 'inferred_count': template.inferred_count}
                                for part, template in self.assignments],
                'changed_bytes': self.changed_bytes,
                'patterns': [{'slot': before.slot + 1,
                              'source_sha256': before.sha256 if self.full_source and before.slot not in self.unbacked_slots else None,
                              'output_sha256': after.sha256,
                              'changed_bytes': len(indices),
                              'initialized_lumon_metadata': before.firmware != after.firmware}
                             for before, after, (_, indices) in
                             zip(self.rollback_patterns, self.selected_patterns, self.changes)],
                'current_snapshot_retained': any(p.slot is None for p in self.full_source),
                'original_backup_available': self.original_backup_available,
                'unbacked_slots': [n + 1 for n in self.unbacked_slots],
                'source_preserved': self.original_backup_available,
                'sample_audio_preserved': True, 'device_access': False,
                'restore': 'selected stored slots only; current snapshot is never assigned implicitly',
                'rollback': ('complete local source bank' if self.full_source else
                             'unavailable; reset replaces device patterns without an original backup'),
                'reference_swing': 0}


def plan_grooves(patterns, assignments, slots='all', catalog=None, firmware='lumon-xl', source_bank=None, reset=False):
    """Validate everything before producing a pure selected-slot patch plan.

    ``source_bank`` is only needed when the caller explicitly maps a separate
    current snapshot to a destination; retain its original complete backup
    here so publishing the rollback never loses that snapshot.

    With ``reset=True``, ``patterns=None`` creates native defaults without
    requiring a backup. Missing memories in a partial reset source also use
    defaults, but full_source retains only real originals. unbacked_slots marks
    destinations whose previous device contents cannot be recovered from it.
    """
    _require_format(firmware)
    if type(reset) is not bool:
        raise ValueError('Reset mode must be explicitly true or false')
    if patterns is None:
        if not reset or source_bank is not None:
            raise ValueError('A source bank is required for preserve mode; only reset can start without one')
        source = tuple(blank_pattern(firmware, n) for n in range(SLOT_COUNT))
        full_source = ()  # synthetic defaults cannot be called an original backup
    else:
        source = tuple(patterns)
        bank_to_json(source)  # same strict cardinality/duplicate validation as bank I/O
        full_source = tuple(source_bank) if source_bank is not None else source
        bank_to_json(full_source)
    stored = {p.slot: p for p in source if p.slot is not None}
    if slots == 'all':
        selected = tuple(range(SLOT_COUNT))
    else:
        if isinstance(slots, (str, bytes)):
            raise ValueError('Select zero-based stored slots or all')
        try:
            selected = tuple(slots)
        except TypeError as exc:
            raise ValueError('Select zero-based stored slots or all') from exc
        if (not selected or any(type(n) is not int or not 0 <= n < SLOT_COUNT for n in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError('Choose distinct stored slots 0–9')
        selected = tuple(sorted(selected))
    missing = tuple(n for n in selected if n not in stored)
    if missing and not reset:
        raise ValueError('The bank does not contain every selected stored slot; all requires ten memories')
    resolved = _assignments(assignments, catalog or load_catalog(firmware=firmware))
    rollback = tuple(stored[n] if n in stored else blank_pattern(firmware, n) for n in selected)
    # Validation precedes every mutation, including later selected memories.
    if not reset:
        for pattern in rollback:
            _validate_pattern(pattern, firmware)
    bases = tuple(blank_pattern(firmware, p.slot) for p in rollback) if reset else rollback
    patched = tuple(_apply_resolved(pattern, resolved, firmware) for pattern in bases)
    changes = tuple((before.slot, tuple(i for i, (a, b) in enumerate(zip(before.data, after.data)) if a != b))
                    for before, after in zip(rollback, patched))
    return GroovePlan(patched, rollback, full_source, resolved, selected, changes, reset, firmware,
                      missing if full_source else selected)


def save_groove_plan(output, plan, rollback_path=None):
    """Atomically publish new selected-pattern and complete-original bank files.

    Each file is atomically linked without clobbering. If the second publish
    fails, remove only the first file created by this call. Existing files,
    including ones appearing during a race, are never removed or overwritten.
    Standalone reset plans publish only the patch bank and return ``None``
    for the rollback path; synthetic defaults are not a device backup.
    """
    if not isinstance(plan, GroovePlan):
        raise ValueError('Expected a validated groove plan')
    # Revalidate the objects before creating directories or files.
    bank_to_json(plan.selected_patterns)
    if plan.full_source:
        bank_to_json(plan.full_source)
    elif not plan.reset:
        raise ValueError('A preserve plan must retain its source bank')
    output = Path(output).expanduser()
    if not plan.original_backup_available:
        if rollback_path is not None:
            raise ValueError('No original source bank is available for a rollback file')
        if os.path.lexists(output):
            raise FileExistsError(f'Bank destination already exists: {output}')
        save_bank(output, plan.selected_patterns)
        return output, None
    rollback_path = (Path(rollback_path).expanduser() if rollback_path is not None
                     else output.with_name(output.stem + '.rollback.vspatterns'))
    if output.resolve() == rollback_path.resolve():
        raise ValueError('Patched and rollback banks need different new paths')
    for path in (output, rollback_path):
        if os.path.lexists(path):
            raise FileExistsError(f'Bank destination already exists: {path}')
    rollback_created = False
    try:
        save_bank(rollback_path, plan.full_source)
        rollback_created = True
        published = rollback_path.stat()
        save_bank(output, plan.selected_patterns)
    except BaseException:
        if rollback_created:
            try:
                current = rollback_path.stat()
                if (current.st_dev, current.st_ino) == (published.st_dev, published.st_ino):
                    rollback_path.unlink()
            except FileNotFoundError:
                pass
        raise
    return output, rollback_path
