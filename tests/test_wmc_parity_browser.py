"""Shared-backend operation coverage through actual Browser App controls in real Chromium.

Every test uses a separate helper, temporary files and simulated native devices.
Browser Audio is replaced with a recording stub and Chromium is muted. Set
WMC_PACKAGED_APP to run these same controls against a frozen --bench helper.
WMC_PARITY_ARTIFACTS optionally retains screenshots for a visual review.
These checks never open the installed Browser App or the user's audio/MIDI devices.
"""
import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    sync_playwright = None


def browser_binary():
    candidates = [os.environ.get('WMC_TEST_CHROME'),
                  *sorted(glob.glob('/opt/pw-browsers/chromium-*/chrome-linux/chrome')),
                  shutil.which('google-chrome'), shutil.which('chromium')]
    return next((path for path in candidates if path and Path(path).is_file()), None)


AUDIO_SPY = r"""
(() => {
  window.parityPlayback = [];
  window.AudioContext = class {
    constructor() { throw new Error('Waveform inspection must use offline decoding'); }
  };
  const blobs = new WeakMap(), urls = new Map();
  const realFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await realFetch(...args);
    const url = new URL(String(args[0]), location.href);
    if (url.pathname === '/api/sample/preview') {
      const blob = response.blob.bind(response);
      response.blob = async () => {
        const result = await blob();
        blobs.set(result, Object.fromEntries(url.searchParams));
        return result;
      };
    }
    return response;
  };
  const realURL = URL.createObjectURL.bind(URL);
  URL.createObjectURL = (blob) => {
    const url = realURL(blob);
    if (blobs.has(blob)) urls.set(url, blobs.get(blob));
    return url;
  };
  window.Audio = class {
    constructor(src) { this.src = src; }
    addEventListener() {}
    pause() {}
    play() {
      window.parityPlayback.push(urls.get(this.src) || {unidentified: true});
      return Promise.resolve();
    }
  };
})();
"""


@unittest.skipUnless(sync_playwright and browser_binary(),
                     'Playwright and a Chromium-based browser are required')
class WmcParityBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=browser_binary(), args=['--mute-audio'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        from volcastudio.wmc.verify import Client, start, tone
        self.tmp = tempfile.TemporaryDirectory(prefix='wmc-parity-browser-')
        self.root = Path(self.tmp.name).resolve()
        self.addCleanup(self.tmp.cleanup)
        self.proc = None
        self.bench = None
        packaged = os.environ.get('WMC_PACKAGED_APP')
        if packaged:
            link = self.root / 'helper-link.txt'
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(('PYTHON', 'VOLCASTUDIO_'))}
            self.proc = subprocess.Popen([packaged, '--bench', '--no-browser', '--link-file', str(link)],
                                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.addCleanup(self.stop_packaged)
            deadline = time.monotonic() + 90
            while not link.exists() and self.proc.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(link.exists(), f'Packaged helper did not start (exit {self.proc.poll()})')
            self.url = link.read_text().strip()
            url, token = self.url.split('#k=')
            self.client = Client(urlsplit(url).port, token)
        else:
            self.helper, self.server, self.bench, self.client = start(self.root / 'helper')
            self.addCleanup(self.stop_source)
            self.url = f'http://127.0.0.1:{self.client.port}/#k={self.helper.token}'
        self.paths = {name: Path(value) for name, value in self.client.get('/api/system/status')['paths'].items()}
        self.samples = self.root / 'own samples'
        self.samples.mkdir()
        tone(self.samples / 'bass_A3.wav', 220, seconds=.12)
        tone(self.samples / 'lead_E4.wav', 329.627557, seconds=.16)
        self.originals = {path.name: path.read_bytes() for path in self.samples.iterdir()}
        self.context = self.browser.new_context(viewport={'width': 1400, 'height': 1000},
                                                accept_downloads=True)
        self.context.add_init_script(AUDIO_SPY)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        expect(self.page.locator('#minutes-last')).to_contain_text('Welcome', timeout=30000)
        self.page.uncheck('#motion-toggle')

    def stop_source(self):
        self.server.shutdown()
        self.server.server_close()
        self.bench.uninstall()

    def stop_packaged(self):
        if self.proc.poll() is None:
            try:
                self.client.post('/api/shutdown')
                self.proc.wait(timeout=15)
            except Exception:
                self.proc.kill()
                self.proc.wait()

    def answer(self, name):
        dialog = self.page.locator('#dialog')
        expect(dialog).to_be_visible(timeout=60000)
        button = dialog.get_by_role('button', name=name, exact=True)
        button.click()
        expect(button).to_be_hidden()

    def register(self, folder, name):
        self.page.click('#library-manage')
        expect(self.page.locator('#registration-path')).to_be_visible()
        self.page.fill('#registration-path', str(folder))
        self.page.fill('#registration-name', name)
        self.answer('Register folder')
        expect(self.page.locator('#library-select')).to_have_value('reg:' + name)
        expect(self.page.locator('#minutes-last')).to_contain_text('Registered ' + name)

    def go(self, space):
        self.page.click(f'.spaces button[data-space={space}]')
        expect(self.page.locator('#space-' + space)).to_be_visible()

    def save_kit(self, name):
        self.page.fill('#kit-name', name)
        self.page.click('#save-kit')
        expect(self.page.locator('#kit-status')).to_contain_text(name, timeout=30000)
        return self.paths['kits'] / name

    def assert_sources_unchanged(self):
        self.assertEqual({path.name: path.read_bytes() for path in self.samples.iterdir()}, self.originals)

    def assert_no_native_output(self):
        if self.bench is not None:
            self.assertEqual(self.bench.streams, [])
            self.assertEqual(self.bench.midi, [])
        # The bench writes a raw file for every opened native output stream.
        self.assertEqual(list(self.paths['state'].parent.rglob('stream-*.raw')), [])

    def screenshot(self, name):
        destination = os.environ.get('WMC_PARITY_ARTIFACTS')
        if destination:
            folder = Path(destination)
            folder.mkdir(parents=True, exist_ok=True)
            expect(self.page.locator('#celebration')).to_be_hidden(timeout=10000)
            self.page.screenshot(path=str(folder / name), full_page=True)

    def test_library_registration_all_search_pages_and_unavailable_removal(self):
        from volcastudio.wmc.verify import tone
        library = self.root / 'paged library'
        library.mkdir()
        fixture = tone(library / 'page-000_A3.wav', 220, seconds=.01).read_bytes()
        for index in range(1, 253):
            (library / f'page-{index:03d}_A3.wav').write_bytes(fixture)
        self.register(library, 'paged')
        rows = self.page.locator('#library-list .item')
        expect(rows).to_have_count(250)
        expect(self.page.locator('#library-count')).to_have_text('253 samples · 1–250 shown')
        expect(self.page.locator('#library-previous')).to_be_disabled()
        self.page.click('#library-next')
        expect(rows).to_have_count(3)
        expect(rows.last).to_contain_text('page-252_A3.wav')
        expect(self.page.locator('#library-count')).to_have_text('253 samples · 251–253 shown')
        expect(self.page.locator('#library-next')).to_be_disabled()
        self.page.click('#library-previous')
        expect(rows).to_have_count(250)
        self.register(self.samples, 'own')
        self.page.select_option('#library-select', '*')
        expect(self.page.locator('#library-count')).to_have_text('255 samples · 1–250 shown')
        self.page.fill('#library-search', 'page-252')
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('page-252_A3.wav')
        self.page.fill('#library-search', 'own lead')
        expect(rows).to_have_count(1)
        expect(rows).to_contain_text('lead_E4.wav')
        self.page.fill('#library-search', '')
        moved = library.with_name('disconnected library')
        library.rename(moved)
        self.page.click('#library-manage')
        entry = self.page.locator('#dialog li', has_text='paged')
        expect(entry).to_contain_text('unavailable')
        entry.get_by_role('button', name='Unregister', exact=True).click()
        expect(self.page.locator('#dialog-title')).to_have_text('Unregister “paged”?')
        self.answer('Unregister')
        self.page.click('#library-manage')
        expect(self.page.locator('#dialog li', has_text='paged')).to_have_count(0)
        self.answer('Close')
        self.assertEqual((moved / 'page-252_A3.wav').read_bytes(), fixture)
        self.assertIn('own=', self.paths['libraries'].read_text())
        self.assertNotIn('paged=', self.paths['libraries'].read_text())
        self.assertEqual(list((self.paths['data'] / 'wmc' / 'libraries').glob('own/*')), [])
        self.assert_sources_unchanged()
        self.assert_no_native_output()
        self.assertEqual(self.errors, [])

    def test_source_preview_autoplay_library_transposition_additive_x2_and_pack_edit(self):
        self.register(self.samples, 'own')
        library = self.page.locator('#library-list .item')
        library.first.click()
        self.page.keyboard.press('Enter')
        rows = self.page.locator('#workbench-list .item')
        expect(rows).to_have_count(1)
        rows.first.click()  # Keep a different workbench selection active.
        library.nth(1).click()
        self.page.select_option('#preview-mode', 'source')
        self.page.evaluate('window.parityPlayback = []')
        self.page.click('#listen')
        self.page.wait_for_function('() => window.parityPlayback.length === 1')
        played = self.page.evaluate('window.parityPlayback[0]')
        self.assertEqual(Path(played['path']), self.samples / 'lead_E4.wav')
        self.assertEqual((played['mode'], played['pitch']), ('source', '0'))
        self.page.wait_for_function('''() => {
          const canvas = document.querySelector('#waveform');
          const pixels = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
          return pixels.some((value, index) => index % 4 === 3 && value > 0);
        }''')
        response = self.client.get('/api/sample/preview?mode=source&pitch=0&path=' + quote(played['path']), raw=True)
        self.assertEqual(response[0], 200)
        self.assertEqual(response[1], self.originals['lead_E4.wav'])
        self.page.click('#stop-listen')
        self.page.check('#autoplay')
        self.page.wait_for_function('() => window.parityPlayback.length >= 2')
        self.page.evaluate('window.parityPlayback = []')
        library.first.click()
        self.page.keyboard.press('ArrowDown')
        self.page.wait_for_function('() => window.parityPlayback.length >= 1')
        self.assertEqual(Path(self.page.evaluate('window.parityPlayback.at(-1).path')),
                         self.samples / 'lead_E4.wav')
        self.page.uncheck('#autoplay')
        self.page.click('#stop-listen')
        # Library J/K creates and adds a derivative, without adding its original.
        library.nth(1).click()
        self.page.keyboard.press('k')
        expect(self.page.locator('#dialog input.digits')).to_be_visible()
        self.page.fill('#dialog input.digits', '3')
        self.page.keyboard.press('Enter')
        expect(rows).to_have_count(2, timeout=60000)
        expect(rows.nth(1).locator('.badge-shift')).to_have_text('+3')
        library.nth(1).click()
        self.page.keyboard.press('j')
        expect(self.page.locator('#dialog input.digits')).to_be_visible()
        self.page.fill('#dialog input.digits', '2')
        self.page.keyboard.press('Enter')
        expect(rows).to_have_count(3, timeout=60000)
        expect(rows.nth(2).locator('.badge-shift')).to_have_text('-2')
        # J/K replaces the original slot when that library source is
        # already present. It must not silently add another draft row here.
        library.first.click()
        self.page.keyboard.press('k')
        expect(self.page.locator('#dialog input.digits')).to_be_visible()
        self.page.fill('#dialog input.digits', '2')
        self.page.keyboard.press('Enter')
        expect(rows.nth(0).locator('.badge-shift')).to_have_text('+2', timeout=60000)
        expect(rows).to_have_count(3)
        original_path = self.client.get('/api/draft')['rows'][0]['path']
        original_variant = Path(original_path).read_bytes()
        rows.first.click()
        self.page.keyboard.press('ControlOrMeta+d')
        expect(rows).to_have_count(4, timeout=60000)
        draft = self.client.get('/api/draft')
        self.assertEqual(draft['rows'][0]['path'], original_path)
        expect(rows.nth(3).locator('.badge-shift')).to_have_text('+14')
        rows.first.click()
        with self.page.expect_response(lambda response: response.request.method == 'POST' and
                                       urlsplit(response.url).path == '/api/samples/variants') as pending:
            self.page.keyboard.press('ControlOrMeta+d')
        self.client.wait(pending.value.json())
        expect(self.page.locator('#operation')).to_be_hidden(timeout=30000)
        expect(self.page.locator('#minutes-last')).to_contain_text('Added ×2 variants', timeout=60000)
        self.assertEqual(len(self.client.get('/api/draft')['rows']), 4, '×2 was inserted twice')
        kit = self.save_kit('parity-variants')
        self.screenshot('samples-normal.png')
        self.page.reload()
        expect(rows).to_have_count(4, timeout=30000)
        expect(self.page.locator('#preview-mode')).to_have_value('source')
        expect(self.page.locator('#autoplay')).not_to_be_checked()
        self.go('commons')
        self.page.locator('#kits-table tbody tr', has_text='parity-variants').get_by_role(
            'button', name='Open to edit', exact=True).click()
        # Reopening has the same row count as the restored draft. Wait for the
        # open operation itself before navigating again or changing its files.
        expect(self.page.locator('#edit-badge')).to_have_text('editing parity-variants')
        expect(self.page.locator('#space-gathering')).to_be_visible()
        expect(rows).to_have_count(4)
        saved = self.client.get('/api/kit?path=' + quote(str(kit)))
        self.assertEqual([row['semitones'] for row in saved['slots']], [2, 3, -2, 14])
        self.assertEqual(Path(saved['slots'][0]['path']).read_bytes(), original_variant)
        # Existing packs have a real replace operation, preserving prior bytes.
        pack = self.paths['sources_dir'] / 'existing-pack'
        pack.mkdir(parents=True)
        for index, (name, content) in enumerate(self.originals.items()):
            (pack / f'{index:02d}-{name}').write_bytes(content)
        self.go('commons')
        self.page.locator('#kits-table tbody tr', has_text='existing-pack').get_by_role(
            'button', name='Open to edit', exact=True).click()
        expect(self.page.locator('#edit-badge')).to_have_text('editing existing-pack')
        expect(self.page.locator('#space-gathering')).to_be_visible()
        expect(rows).to_have_count(2)
        rows.nth(1).click()
        self.page.keyboard.press('Delete')
        expect(rows).to_have_count(1)
        self.page.click('#replace-kit')
        self.answer('Replace & archive previous')
        expect(self.page.locator('#minutes-last')).to_contain_text('previous version is archived')
        self.assertEqual(len(list(pack.glob('*.wav'))), 1)
        records = list((self.paths['data'] / 'trash').glob('*/record.json'))
        record = next(path for path in records if json.loads(path.read_text())['name'] == 'existing-pack')
        archived = list(record.parent.rglob('*.wav'))
        self.assertEqual(sorted(path.read_bytes() for path in archived), sorted(self.originals.values()))
        self.assert_sources_unchanged()
        self.assert_no_native_output()
        self.assertEqual(self.errors, [])

    def export_download(self, button, name):
        self.page.click(button)
        expect(self.page.locator('#dialog-title')).to_have_text('Prepare SYRO files for download?')
        expect(self.page.locator('#dialog')).to_contain_text('speakers or headphones')
        with self.page.expect_download(timeout=120000) as download:
            self.answer('Prepare download')
        path = self.root / name
        download.value.save_as(path)
        self.assertTrue(download.value.suggested_filename.endswith('-syro.zip'))
        expect(self.page.locator('#operation')).to_be_hidden(timeout=30000)
        return path

    def assert_encoded_archive(self, archive, expected):
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            files = {path.relative_to(expected).as_posix(): path for path in expected.rglob('*') if path.is_file()}
            self.assertEqual(names, set(files))
            for name, path in files.items():
                if name == 'manifest.json':
                    actual = json.loads(bundle.read(name))
                    reference = json.loads(path.read_text())
                    actual.pop('created_at', None)
                    reference.pop('created_at', None)
                    self.assertEqual(actual, reference)
                else:
                    self.assertEqual(bundle.read(name), path.read_bytes(), name)

    def open_pattern_fixture(self):
        from volcastudio.patterns import save_bank
        from volcastudio.wmc.bench import bench_bank
        original = bench_bank()
        fixture = save_bank(self.root / 'original.vspatterns', original)
        self.go('memory')
        self.page.set_input_files('#bank-upload', str(fixture))
        expect(self.page.locator('#bank-view .memory-card')).to_have_count(11)
        return original, fixture

    def test_syro_downloads_cancel_kit_selected_memories_and_snapshot_destination(self):
        from volcastudio.config import Config
        from volcastudio.pattern_transfer import prepare_patterns
        from volcastudio.transfer import prepare
        self.register(self.samples, 'own')
        self.page.locator('#library-list').focus()
        self.page.keyboard.press('ControlOrMeta+a')
        self.page.click('#add-to-kit')
        expect(self.page.locator('#workbench-list .item')).to_have_count(2)
        kit = self.save_kit('parity-export')
        before = self.client.get('/api/job')['job']
        self.page.click('#export-kit-signals')
        self.answer('Cancel')
        self.assertEqual(self.client.get('/api/job')['job'], before)
        self.assertEqual(list(self.paths['cache'].rglob('signals.zip')), [])
        exported = self.export_download('#export-kit-signals', 'kit-syro.zip')
        expected = self.root / 'independent-kit'
        prepare(kit, expected, Config.read().syro_dir)
        self.assert_encoded_archive(exported, expected)
        original, _ = self.open_pattern_fixture()
        self.page.click('#restore-none')
        self.page.locator('#restore-memories input').nth(1).check()
        self.page.locator('#restore-memories input').nth(8).check()
        exported = self.export_download('#export-pattern-signals', 'stored-syro.zip')
        expected = self.root / 'independent-patterns'
        prepare_patterns([original[1], original[8]], expected, Config.read().syro_dir, 'lumon-xl-internal')
        self.assert_encoded_archive(exported, expected)
        self.page.click('#export-current-signals')
        expect(self.page.locator('#dialog')).to_contain_text('Choose a memory from 1 to 10')
        self.answer('OK')
        self.page.select_option('#current-destination', '7')
        exported = self.export_download('#export-current-signals', 'snapshot-syro.zip')
        expected = self.root / 'independent-snapshot'
        prepare_patterns([original[-1]], expected, Config.read().syro_dir, 'lumon-xl-internal', destination=6)
        self.assert_encoded_archive(exported, expected)
        self.assert_no_native_output()
        self.assert_sources_unchanged()
        self.assertEqual(self.errors, [])

    def test_catalogue_current_snapshot_plan_save_rollback_diagnostics_and_narrow_layout(self):
        from volcastudio.grooves import apply_pattern, load_catalog
        from volcastudio.patterns import Pattern, load_bank
        original, fixture = self.open_pattern_fixture()
        fixture_before = fixture.read_bytes()
        self.go('movement')
        expect(self.page.locator('#catalog-steps tbody tr')).to_have_count(16)
        self.screenshot('grooves-normal.png')
        catalog = load_catalog()
        ident = 'DANGELO_SPANISH_JOINT_B03'
        template = catalog.resolve(ident)
        self.page.select_option('#catalog-category', 'dangelo')
        self.page.fill('#catalog-search', ident)
        expect(self.page.locator('#catalog-alias')).to_have_value(ident)
        expect(self.page.locator('#catalog-description')).to_contain_text('dangelo')
        actual_steps = self.page.locator('#catalog-steps tbody tr').evaluate_all(
            '(rows) => rows.map(row => Array.from(row.cells, cell => cell.textContent))')
        for index, row in enumerate(actual_steps):
            self.assertEqual(row[:2], [str(index + 1), str(template.microtiming[index])])
            expected_source = 'measured' if template.measured_mask & (1 << index) else 'reconstructed'
            self.assertEqual(row[2], expected_source)
        provenance = json.loads(self.page.locator('#catalog-provenance').inner_text())
        self.assertEqual(provenance['exact_microtiming'],
                         [[str(value) for value in fraction]
                          for fraction in template.as_dict()['exact_microtiming']])
        self.assertEqual(provenance['source'], catalog.sources[template.provenance['source']])
        self.page.select_option('#catalog-part', '2')
        self.page.click('#catalog-use')
        expect(self.page.locator('#groove-parts input').nth(1)).to_have_value(
            ident + ' · ' + template.display_name)
        # A category match must not silently select another category's alias.
        self.page.fill('#catalog-search', '')
        self.page.select_option('#catalog-category', 'analytic')
        expect(self.page.locator('#catalog-description')).to_contain_text('analytic')
        self.assertEqual(set(self.page.locator('#catalog-steps tbody tr td:nth-child(3)').all_text_contents()),
                         {'analytic'})
        self.page.select_option('#groove-source', 'current')
        self.page.click('#groove-preview')
        expect(self.page.locator('#dialog')).to_contain_text('destination')
        self.answer('OK')
        self.page.select_option('#groove-destination', '7')
        expect(self.page.locator('#groove-memories input:checked')).to_have_count(1)
        expect(self.page.locator('#groove-memories input:checked')).to_have_value('7')
        self.page.click('#groove-preview')
        expect(self.page.locator('#dialog-title')).to_have_text('Groove change plan')
        expect(self.page.locator('#dialog')).to_contain_text('Memories: 7 · preserve')
        expect(self.page.locator('#dialog')).to_contain_text('complete source bank')
        expect(self.page.locator('#dialog')).to_contain_text('Part 2: ' + ident)
        self.answer('Close')
        self.assertEqual(list(self.paths['patterns'].glob('*.vspatterns')), [])
        self.page.fill('#groove-name', 'snapshot-groove')
        self.page.click('#groove-save')
        expect(self.page.locator('#groove-send')).to_be_enabled(timeout=30000)
        expect(self.page.locator('#groove-status')).to_contain_text('memories 7')
        expected = apply_pattern(Pattern(6, original[-1].data), {2: ident}, catalog)
        self.assertEqual(load_bank(self.paths['patterns'] / 'snapshot-groove.vspatterns'), [expected])
        self.assertEqual(load_bank(self.paths['patterns'] / 'snapshot-groove.rollback.vspatterns'), original)
        self.assertEqual(fixture.read_bytes(), fixture_before)
        expect(self.page.locator('#groove-source')).to_have_value('stored')
        expect(self.page.locator('#groove-destination-row')).to_be_hidden()
        expect(self.page.locator('#groove-memories input:checked')).to_have_count(1)
        expect(self.page.locator('#groove-memories input:checked')).to_have_value('7')
        self.page.locator('#groove-memories input').nth(7).check()
        expect(self.page.locator('#groove-send')).to_be_disabled()
        self.go('connections')
        self.page.click('#system-check')
        expect(self.page.locator('#system-report')).to_contain_text('SYRO encoder')
        expect(self.page.locator('#system-report')).to_contain_text(str(self.paths['libraries']))
        expect(self.page.locator('#system-report')).to_contain_text('No audio or MIDI devices were opened.')
        self.assert_no_native_output()
        for width in (420, 375):
            self.page.set_viewport_size({'width': width, 'height': 860})
            for space in ('gathering', 'commons', 'memory', 'movement', 'connections'):
                self.go(space)
                overflow = self.page.evaluate('document.documentElement.scrollWidth - innerWidth')
                outside = self.page.evaluate('''() => [...document.querySelectorAll('body *')]
                  .filter(el => el.getBoundingClientRect().right > innerWidth)
                  .map(el => ({tag: el.tagName, id: el.id, class: el.className,
                               right: el.getBoundingClientRect().right})).slice(-12)''') if overflow > 0 else []
                self.assertLessEqual(overflow, 0,
                                     f'Horizontal page overflow in {space} at {width}px: {outside}')
                if width == 375 and space in ('gathering', 'memory', 'movement'):
                    self.screenshot(f'{space}-375.png')
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
