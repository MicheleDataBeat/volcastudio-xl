"""Shared-backend operations exercised through a source or frozen Browser App helper.

All fixtures and outputs are temporary. The caller supplies simulated devices;
these checks assert that offline operations add no audio or MIDI activity.
"""
import io
import json
import wave
import zipfile
from pathlib import Path
from urllib.parse import quote


def run(client, helper, bench, work, checks):
    from .verify import expect_failure, tone
    from .bench import bench_bank
    from ..grooves import apply_pattern, load_catalog
    from ..patterns import PATTERN_PROFILE, Pattern, load_bank, save_bank
    from ..pattern_transfer import prepare_patterns

    # macOS /var and Windows short temporary paths may be aliases. The helper
    # returns resolved paths; fixture identity must use the same representation.
    work = Path(work).resolve() / 'parity'
    work.mkdir()
    count, midi = len(bench.streams), len(bench.midi)
    library = work / 'source-library'
    library.mkdir()
    source = tone(library / 'source_A3.wav', 220, seconds=.2)
    raw = source.read_bytes()
    entry = client.post('/api/library/register', {'directory': str(library), 'name': 'parity'})
    assert entry['id'] == 'reg:parity' and entry['available']
    found = client.get('/api/library?id=*&q=source_A3')['samples']
    assert [row['path'] for row in found] == [str(source)]
    status, audio, _ = client.request('GET', '/api/sample/preview?mode=source&path=' + quote(str(source)), raw=True)
    assert status == 200 and audio == raw
    client.post('/api/preferences', {'autoplay': True, 'preview_mode': 'source'})
    assert client.get('/api/preferences')['autoplay'] is True
    client.post('/api/preferences', {'autoplay': False})
    client.put('/api/draft', {'paths': [str(source)]})
    job = client.wait(client.post('/api/samples/variants', {'paths': [str(source)], 'semitones': 12}))
    assert job['outcome'] == 'done', job
    rows = job['result']['draft']['rows']
    assert len(rows) == 2 and rows[0]['path'] == str(source) and rows[1]['semitones'] == 12
    assert abs(rows[1]['seconds'] - .1) < .001 and source.read_bytes() == raw
    repeated = client.wait(client.post('/api/samples/variants', {'paths': [str(source)], 'semitones': 12}))
    assert repeated['result']['draft']['count'] == 2
    expect_failure(lambda: client.post('/api/samples/variants', {'paths': [str(work / 'outside.wav')], 'semitones': 12}), 400)
    client.post('/api/library/unregister', {'name': 'parity'})
    assert source.read_bytes() == raw
    expect_failure(lambda: client.get('/api/sample/info?path=' + quote(str(source))), 400)
    checks['library_variants_and_listening'] = {'register_in_place': True, 'all_library_search': True,
        'source_bytes_exact': True, 'additive_x2': True, 'duplicate_variant_not_added': True,
        'unregister_only_reference': True, 'preferences_persisted': True}

    # The existing scenario prepared the same kit independently for its PCM
    # oracle. Compare every generated audio file in the browser download.
    kit = helper.config.kits / 'wmc-verify'
    result = client.wait(client.post('/api/kit/export-signals', {'path': str(kit)}))
    assert result['outcome'] == 'done', result
    status, archive, _ = client.request('GET', result['result']['download'], raw=True)
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        expected = {path.relative_to(work.parent / 'reference').as_posix(): path.read_bytes()
                    for path in (work.parent / 'reference').rglob('*.wav')}
        actual = {name: bundle.read(name) for name in bundle.namelist() if name.endswith('.wav')}
        assert actual == expected and len(actual) == 104
        assert json.loads(bundle.read('manifest.json'))['count'] == 2
    expect_failure(lambda: client.get('/api/prepared/download?id=../../outside'), 400)

    bank = tuple(bench_bank())
    path = helper.config.patterns / 'parity-source.vspatterns'
    save_bank(path, bank)
    client.post('/api/patterns/open', {'path': str(path)})
    result = client.wait(client.post('/api/patterns/export-signals', {'current_destination': 7}))
    assert result['outcome'] == 'done', result
    status, archive, _ = client.request('GET', result['result']['download'], raw=True)
    assert status == 200
    current = next(pattern for pattern in bank if pattern.slot is None)
    reference = work / 'pattern-reference'
    prepare_patterns([current], reference, helper.config.syro_dir, PATTERN_PROFILE, destination=6)
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        assert bundle.read('pattern-06.bin') == current.data
        assert bundle.read('pattern-06.wav') == (reference / 'pattern-06.wav').read_bytes()
        assert json.loads(bundle.read('manifest.json'))['slots'] == [6]
    checks['downloadable_syro'] = {'kit_audio_files': len(actual), 'kit_byte_exact': True,
        'current_pattern_destination': 7, 'pattern_byte_exact': True, 'invalid_download_refused': True}

    catalog = load_catalog(firmware=PATTERN_PROFILE)
    template = catalog.resolve('MPC3000_73_B02')
    described = client.get('/api/grooves/template?id=' + quote(template.id))
    assert [step['microtiming'] for step in described['steps']] == list(template.microtiming)
    assert len(described['steps']) == 16
    assert [step['measured'] for step in described['steps']] == [bool(template.measured_mask & 1 << i) for i in range(16)]
    request = {'reset': False, 'slots': '7', 'current': True, 'destination': 7,
               'assignments': {'1': template.id}, 'name': 'parity-current'}
    plan = client.post('/api/grooves/plan', request)
    assert plan['slots'] == [7] and not (helper.config.patterns / 'parity-current.vspatterns').exists()
    saved = client.post('/api/grooves/save', request)
    expected = apply_pattern(Pattern(6, current.data), {1: template.id}, catalog, firmware=PATTERN_PROFILE)
    assert load_bank(saved['path'])[0].data == expected.data
    assert [p.sha256 for p in load_bank(saved['rollback'])] == [p.sha256 for p in bank]
    checks['current_snapshot_groove'] = {'destination': 7, 'output_byte_exact': True,
        'complete_original_bank_rollback': True, 'plan_writes_nothing': True,
        'catalogue_step_masks_preserved': True}
    diagnostic = client.get('/api/system/status')
    assert diagnostic['passed'] and diagnostic['hardware_access'] is False, diagnostic
    assert len(bench.streams) == count and len(bench.midi) == midi
    checks['installation_diagnostics'] = {'tools_present': True, 'hardware_access': False}
