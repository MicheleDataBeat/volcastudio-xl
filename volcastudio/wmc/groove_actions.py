"""Browser input and catalogue records for the shared offline groove backend.

No terminal UI, browser, device, filesystem or timing implementation lives here.
Stored memories in requests are one-based; ``GroovePlan`` uses zero-based slots.
"""
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace

from ..grooves import plan_grooves
from ..outie_model import parse_slots
from ..patterns import Pattern, bank_to_json, blank_pattern

CATEGORIES = ('all', 'mpc3000', 'dilla', 'dangelo', 'analytic')


def _assignments(value):
    if not isinstance(value, Mapping):
        raise ValueError('Invalid groove assignments.')
    parsed = {}
    for part, template in value.items():
        # JSON object keys are strings. Also accept integers for Python callers;
        # bool, fractional values and duplicate representations are not parts.
        if type(part) is int:
            number = part
        elif isinstance(part, str) and part in {str(n) for n in range(1, 11)}:
            number = int(part)
        else:
            raise ValueError('Groove parts are numbered 1–10.')
        if not 1 <= number <= 10:
            raise ValueError('Groove parts are numbered 1–10.')
        if number in parsed:
            raise ValueError(f'Part {number} was assigned more than once.')
        if template in ('', None):
            continue  # an unassigned part keeps its existing/neutral timing
        if not isinstance(template, str):
            raise ValueError('Choose a groove template or profile ID.')
        parsed[number] = template
    if not parsed:
        raise ValueError('Choose a groove template for at least one part.')
    return parsed


def build_plan(bank, request, catalog):
    """Validate Browser App choices, then delegate all musical edits to plan_grooves.

    ``current`` maps the bank's separate current snapshot to one explicit stored
    destination. The output uses that snapshot, but rollback/provenance describe
    the real original destination, when it was included in the source bank.
    The complete original bank (including its separate snapshot) remains intact.
    """
    if not isinstance(request, Mapping):
        raise ValueError('Invalid groove request.')
    reset = request.get('reset')
    if type(reset) is not bool:
        raise ValueError('Choose Preserve or Reset + groove.')
    current = request.get('current', False)
    if type(current) is not bool:
        raise ValueError('Choose stored memories or the separate current snapshot.')
    destination = request.get('destination')
    if current and (type(destination) is not int or not 1 <= destination <= 10):
        raise ValueError('The current snapshot needs an explicit destination memory (1–10).')
    assignments = _assignments(request.get('assignments', {}))
    slots = request.get('slots')
    if not isinstance(slots, str):
        raise ValueError('Select pattern memories 1–10, a list/range, or all.')
    selected = parse_slots(slots)
    if not selected:
        raise ValueError('Select at least one pattern memory (1–10).')
    original = tuple(bank) if bank is not None else None
    if original is not None:
        bank_to_json(original)  # cardinality, type and duplicate-slot validation
    if not current:
        if destination is not None:
            raise ValueError('A destination memory requires the current snapshot.')
        if original is None and not reset:
            raise ValueError('Preserve needs an existing pattern bank.')
        return plan_grooves(original, assignments, selected, catalog=catalog,
                            source_bank=original, reset=reset, firmware=catalog.firmware)

    target = destination - 1
    if selected != (target,):
        raise ValueError('Select only the explicit destination memory for the current snapshot.')
    if original is None:
        raise ValueError('Open a bank containing a separate current snapshot first.')
    snapshots = tuple(pattern for pattern in original if pattern.slot is None)
    if len(snapshots) != 1:
        raise ValueError('The selected bank has no separate current snapshot.')
    mapped = Pattern(target, snapshots[0].data)
    plan = plan_grooves((mapped,), assignments, selected, catalog=catalog,
                        source_bank=original, reset=reset, firmware=catalog.firmware)

    # A mapped snapshot is not the old contents of its destination. Compare
    # against the actual stored target rather than labelling snapshot bytes as
    # its backup. Missing targets remain explicitly unbacked; their comparison
    # base is synthetic, just as in the shared reset plan.
    previous = next((pattern for pattern in original if pattern.slot == target), None)
    before = previous if previous is not None else blank_pattern(catalog.firmware, target)
    after = plan.selected_patterns[0]
    indices = tuple(i for i, (a, b) in enumerate(zip(before.data, after.data)) if a != b)
    return replace(plan, rollback_patterns=(before,), changes=((target, indices),),
                   unbacked_slots=() if previous is not None else (target,))


def _template_record(template):
    record = deepcopy(template.as_dict())
    # Existing Browser App fields remain available alongside the complete shared record.
    record.update(name=template.display_name, profile=template.profile_id,
                  measured=template.measured_count, reconstructed=template.inferred_count)
    # JSON integers beyond 2**53 lose precision in JavaScript. Keep the shared
    # numeric record and provide exact display strings for the browser.
    record['exact_microtiming_strings'] = [[str(n), str(d)] for n, d in record['exact_microtiming']]
    record['steps'] = [
        {'step': index + 1, 'microtiming': value,
         'exact_microtiming': record['exact_microtiming'][index],
         'exact_microtiming_strings': record['exact_microtiming_strings'][index],
         'measured': bool(template.measured_mask & (1 << index)),
         'reconstructed': template.category != 'analytic' and not bool(template.measured_mask & (1 << index)),
         'source': ('analytic' if template.category == 'analytic' else
                    'measured' if template.measured_mask & (1 << index) else 'reconstructed')}
        for index, value in enumerate(template.microtiming)
    ]
    return record


def catalog_listing(catalog, category='all', query=''):
    """Distinct profiles plus searchable source/voice/bar aliases and evidence."""
    if category not in CATEGORIES:
        raise ValueError('Choose a groove category from the catalogue.')
    if not isinstance(query, str):
        raise ValueError('Groove search must be text.')
    search = query.casefold()
    templates = [template for template in catalog.templates
                 if (category == 'all' or template.category == category)
                 and search in (template.id + ' ' + template.display_name).casefold()]
    records = {template.id: _template_record(template) for template in templates}
    profiles = []
    for profile in catalog.profiles:
        aliases = [records[alias] for alias in profile.aliases if alias in records]
        if not aliases:
            continue
        primary = next((alias for alias in aliases if alias['id'].casefold() == search), aliases[0])
        profiles.append({'id': profile.id, 'name': primary['name'],
                         'category': primary['category'],
                         'categories': list(profile.categories),
                         'microtiming': list(profile.microtiming), 'aliases': aliases,
                         'alias_count': len(profile.aliases)})
    return {'profiles': len(catalog.profiles), 'aliases': len(catalog.templates),
            'categories': list(CATEGORIES), 'range': [-15, 15],
            'firmware': catalog.firmware, 'reference_swing': 0,
            'step_unit': [1, 32], 'quarter_note_unit': [1, 128],
            'templates': list(records.values()), 'grouped_profiles': profiles,
            'sources': deepcopy(catalog.sources)}


def describe_template(catalog, template_id):
    """Full timing/evidence for either an alias ID or a distinct profile ID."""
    template = catalog.resolve(template_id)
    record = _template_record(template)
    record.update(reference_swing=0, step_unit=[1, 32], quarter_note_unit=[1, 128],
                  aliases=[_template_record(alias) for alias in catalog.aliases_for(template.profile_id)])
    source = template.provenance.get('source')
    record['source'] = deepcopy(catalog.sources.get(source))
    return record
