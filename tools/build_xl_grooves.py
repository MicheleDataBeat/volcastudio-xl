#!/usr/bin/env python3
"""Rebuild extended timing catalog from exact, separately supplied research JSON.

Source audio/MIDI/AGR are never bundled. The standard catalog is retained as-is.
Usage: python tools/build_xl_grooves.py /path/to/analysis-directory
"""
import copy
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from volcastudio.grooves import GROOVE_FORMATS, _profile_id, _round_micro


def build(research, standard):
    for filename, source in (('mpc3000-analysis.json', 'samples_from_mars'), ('dilla-grid-model.json', 'kit_maker')):
        if hashlib.sha256((research / filename).read_bytes()).hexdigest() != standard['sources'][source]['analysis_sha256']:
            raise ValueError(f'Analysis checksum differs from catalog provenance: {filename}')
    catalog = copy.deepcopy(standard)
    catalog.update(firmware=list(GROOVE_FORMATS), range=[-15, 15])
    ids = {t['id'] for t in catalog['templates']}
    profiles = {p['id']: p for p in catalog['profiles']}
    def add(record):
        vector = [_round_micro(Fraction(*v)) for v in record['exact_microtiming']]
        if any(abs(v) > 15 for v in vector) or record['id'] in ids:
            return
        ident = _profile_id(vector)
        record['profile_id'] = ident
        if ident not in profiles:
            profiles[ident] = dict(id=ident, microtiming=vector, aliases=[])
            catalog['profiles'].append(profiles[ident])
        profiles[ident]['aliases'].append(record['id'])
        catalog['templates'].append(record)
        ids.add(record['id'])
    add(dict(id='SEXTUPLE_SWING_4_2', display_name='Sextuple swing · 4:2 · 66.67%', category='analytic',
             exact_microtiming=[[0,1] if i%2==0 else [32,3] for i in range(16)],
             measured_mask=0, family=None, role=None, bar=None,
             provenance=dict(method='exact_pair_ratio', ratio=[4,2], reference_swing=0)))
    for source in json.loads((research/'mpc3000-analysis.json').read_text())['templates']:
        family=source['nominal_swing_percent']
        for bar in source['bars']:
            exact=[(Fraction(t)-((bar['bar']-1)*4+Fraction(i,4)))*128 for i,t in enumerate(bar['source_times_beats'])]
            add(dict(id=f"MPC3000_{family}_B{bar['bar']:02}", display_name=f"MPC3000 · {family}% · B{bar['bar']:02}",
                     category='mpc3000', exact_microtiming=[[v.numerator,v.denominator] for v in exact], measured_mask=65535,
                     family=family, role=None, bar=bar['bar'], provenance=dict(source='samples_from_mars',
                     source_member=source['source_member'], source_sha256=source['source_sha256'], nominal_swing_percent=family,
                     method='measured_four_bar_capture', source_times_beats=bar['source_times_beats'],reference_swing=0)))
    for family in json.loads((research/'dilla-grid-model.json').read_text())['families']:
        for bar in family['bars']:
            for role in bar['roles']:
                candidate=role['candidate']
                if not candidate:
                    continue
                add(dict(id=role['id'],display_name=role['name']+f" · B{bar['index']+1:02}",category='dilla',
                         exact_microtiming=[[v['n'],v['d']] for v in candidate['exact']], measured_mask=candidate['measured_mask'],
                         family=family['id'],role=role['role'],bar=bar['index']+1,
                         provenance=dict(source='kit_maker',source_member=family['source'],source_sha256=family['source_sha256'],
                         shared_nominal_origin_tick=bar['shared_nominal_origin_tick'],ppqn=family['ppqn'],
                         method=candidate['method'],selected_phase_period=candidate['selected_phase_period'],
                         one_anchor_only=candidate['one_anchor_only'],inference_provenance=candidate['inference_provenance'],
                         source_ticks=role['source_ticks'],issues=role['issues'],
                         has_predictive_evidence=family['model_selection_per_role'][role['role']]['has_predictive_evidence'],reference_swing=0)))
    return catalog

if __name__=='__main__':
    data=Path(__file__).resolve().parents[1]/'volcastudio/data'
    catalog=build(Path(sys.argv[1]),json.loads((data/'grooves.json').read_text()))
    (data/'grooves-xl.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    print(len(catalog['profiles']), 'profiles;',len(catalog['templates']),'aliases')
