"""Browser App end to end in a real Chromium/Chrome: buttons → local helper → backend.

Uses temporary storage and the simulated bench devices; no real audio or MIDI
device is enumerated or opened. Skipped when Playwright or a Chromium-based
browser is unavailable. Set WMC_TEST_CHROME to choose the browser binary.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import unittest
import wave
from pathlib import Path
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:  # optional developer dependency
    sync_playwright = None


def browser_binary():
    candidates = [os.environ.get('WMC_TEST_CHROME'), *sorted(glob.glob('/opt/pw-browsers/chromium-*/chrome-linux/chrome')),
                  shutil.which('google-chrome'), shutil.which('chromium')]
    return next((c for c in candidates if c and Path(c).is_file()), None)


@unittest.skipUnless(sync_playwright and browser_binary(), 'Playwright and a Chromium-based browser are required')
class WmcBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from volcastudio.wmc.verify import start, tone
        cls.tmp = tempfile.TemporaryDirectory(prefix='wmc-browser-')
        root = Path(cls.tmp.name)
        cls.helper, cls.server, cls.bench, cls.client = start(root)
        cls.files = root / 'my samples'
        cls.files.mkdir()
        # A3 and E4 tones; "pad_C4" is deliberately mislabelled (contains A3).
        tone(cls.files / 'bass_A3.wav', 220, seconds=.4)
        tone(cls.files / 'lead_E4.wav', 329.627557, seconds=.4)
        tone(cls.files / 'pad_C4.wav', 220, seconds=.4)
        tone(cls.files / 'noise.wav', 0, seconds=.2, amplitude=0)
        cls.originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.files.iterdir()}
        cls.downloads = root / 'downloads'
        cls.downloads.mkdir()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=browser_binary())
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.bench.uninstall()
        cls.tmp.cleanup()

    def page(self, width=1400, height=950, **context):
        context = self.browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True, **context)
        page = context.new_page()
        page.errors = []
        page.on('pageerror', lambda exc: page.errors.append(str(exc)))
        page.on('console', lambda message: page.errors.append(message.text) if message.type == 'error' and 'Failed to load resource' not in message.text else None)
        page.goto(f'http://127.0.0.1:{self.port}/#k={self.helper.token}')
        expect(page.locator('#minutes-last')).to_contain_text('Welcome')
        return page

    def answer(self, page, label):
        dialog = page.locator('#dialog')
        expect(dialog).to_be_visible()
        button = dialog.get_by_role('button', name=label, exact=True)
        button.click()
        # A fast operation can already have opened its outcome dialog. Observe
        # the question's button disappearing rather than the reused container.
        expect(button).to_be_hidden()

    def wait_idle(self, page):
        expect(page.locator('#operation')).to_be_hidden(timeout=120000)

    def test_1_complete_sample_workflow(self):
        page = self.page()
        # Choose samples: the browser uploads copies into a Browser App library.
        page.set_input_files('#add-folder', str(self.files))
        expect(page.locator('#library-list .item')).to_have_count(4, timeout=30000)
        self.assertEqual({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.files.iterdir()}, self.originals)
        items = page.locator('#library-list .item')
        names = [items.nth(i).locator('.name').inner_text().split('\n')[0] for i in range(4)]
        self.assertEqual(names, ['bass_A3.wav', 'lead_E4.wav', 'noise.wav', 'pad_C4.wav'])
        # Multi-selection: click, Ctrl-click, Shift+arrow; Enter adds in order.
        items.nth(0).click()
        items.nth(1).click(modifiers=['Shift'])
        items.nth(3).click(modifiers=['ControlOrMeta'])
        expect(page.locator('#add-to-kit')).to_contain_text('Add 3')
        page.keyboard.press('Enter')
        rows = page.locator('#workbench-list .item')
        expect(rows).to_have_count(3)
        expect(page.locator('#budget-slots')).to_have_text('03 / 100 slots')
        expect(page.locator('#budget-seconds')).to_have_text('1.20 / 65.00 s')
        # Varispeed on two rows at once, then a cumulative second step.
        rows.nth(0).click()
        rows.nth(2).click(modifiers=['ControlOrMeta'])
        page.keyboard.press('k')
        page.locator('#dialog input.digits').fill('12')
        page.keyboard.press('Enter')
        expect(rows.nth(0).locator('.badge-shift')).to_have_text('+12', timeout=60000)
        expect(rows.nth(2).locator('.badge-shift')).to_have_text('+12')
        expect(rows.nth(1).locator('.badge-shift')).to_have_count(0)
        expect(page.locator('#budget-seconds')).to_have_text('0.80 / 65.00 s')
        rows.nth(0).click()
        page.keyboard.press('j')
        page.locator('#dialog input.digits').fill('07')
        page.keyboard.press('Enter')
        expect(rows.nth(0).locator('.badge-shift')).to_have_text('+5', timeout=60000)
        # Reorder by keyboard: move slot 00 down, then back.
        page.keyboard.press('Alt+ArrowDown')
        expect(rows.nth(1).locator('.badge-shift')).to_have_text('+5')
        page.keyboard.press('Alt+ArrowUp')
        expect(rows.nth(0).locator('.badge-shift')).to_have_text('+5')
        # Undo the experiment on slot 00 with a cumulative −5 → marker disappears.
        page.keyboard.press('j')
        page.locator('#dialog input.digits').fill('5')
        page.keyboard.press('Enter')
        expect(rows.nth(0).locator('.badge-shift')).to_have_count(0, timeout=60000)

        # Tonal alignment: master bass_A3; pad_C4 (+12) has a filename/measured conflict.
        page.get_by_role('button', name='Align keys…').click()
        dialog = page.locator('#align-dialog')
        expect(dialog).to_be_visible()
        summary = page.locator('#align-summary')
        expect(summary).to_contain_text('Choose Filename or Measured for: 02', timeout=60000)
        expect(page.locator('#align-accept')).to_be_disabled()
        table = page.locator('#align-table tbody tr')
        table.nth(2).locator('select').select_option('detected')
        expect(summary).to_contain_text('Kit:', timeout=30000)
        expect(summary).not_to_contain_text('Choose Filename')
        expect(page.locator('#align-accept')).to_be_enabled()
        # E4 → A: +5 automatically; pad measured A4 → already A: 0.
        self.assertEqual(table.nth(1).locator('input[type=number]').input_value(), '5')
        self.assertEqual(table.nth(2).locator('input[type=number]').input_value(), '0')
        # Manual bulk edit on selected rows, then back to automatic.
        table.nth(1).locator('td').nth(1).click()
        page.fill('#align-batch', '-7')
        page.click('#align-batch-set')
        expect(table.nth(1).locator('input[type=number]')).to_have_value('-7', timeout=30000)
        expect(table.nth(1)).to_contain_text('manual')
        page.click('#align-batch-auto')
        expect(table.nth(1).locator('input[type=number]')).to_have_value('5', timeout=30000)
        expect(page.locator('#align-accept')).to_be_enabled()
        proposed = summary.inner_text()
        self.assertIn('/ 65.00 s', proposed)
        page.click('#align-accept')
        expect(dialog).to_be_hidden(timeout=60000)
        expect(rows.nth(1).locator('.badge-shift')).to_have_text('+5')
        expect(page.locator('#celebration-title')).to_have_text('Pitch alignment applied.')

        # Save, celebrate, metadata on disk.
        page.fill('#kit-name', 'browser-kit')
        page.keyboard.press('ControlOrMeta+s')
        expect(page.locator('#kit-status')).to_contain_text('browser-kit', timeout=30000)
        expect(page.locator('#celebration-title')).to_have_text('Kit saved.')
        kit = self.helper.config.kits / 'browser-kit'
        inspect = self.client.get('/api/kit?path=' + quote(str(kit)))
        self.assertEqual([s['semitones'] for s in inspect['slots']], [0, 5, 12])

        # Sending needs an explicit output.
        page.click('#send-kit')
        self.answer(page, 'OK')
        expect(page.locator('#minutes-last')).to_contain_text('Choose the audio output')
        page.click('.spaces button[data-space=connections]')
        page.select_option('#device-output', label='Bench recorder → SYNC IN (silent) · Studio bench')
        expect(page.locator('#connection-chip')).to_contain_text('Bench recorder')
        page.click('.spaces button[data-space=gathering]')
        # Offline check plays nothing.
        page.click('#check-kit')
        expect(page.locator('#minutes-last')).to_contain_text('Checked offline: 103 signals', timeout=60000)
        self.assertEqual(len(self.bench.streams), 0)
        # Decline the confirmation: nothing is played.
        page.click('#send-kit')
        expect(page.locator('#dialog')).to_be_visible(timeout=60000)
        expect(page.locator('#dialog-title')).to_have_text('Clear the Volca and load this kit?', timeout=60000)
        expect(page.locator('#dialog')).to_contain_text('All 100 sample slots will be cleared, then 3 samples')
        self.assertEqual(page.evaluate('document.activeElement.textContent'), 'Cancel — keep the Volca as it is')
        self.answer(page, 'Cancel — keep the Volca as it is')
        expect(page.locator('#minutes-last')).to_contain_text('cancelled before sending', timeout=30000)
        self.assertEqual(len(self.bench.streams), 0)
        # Approve: every signal played unchanged; the result says "signals sent".
        page.click('#send-kit')
        # The closed dialog retains its previous title during preparation.
        # Wait for the new confirmation, rather than matching that stale title.
        expect(page.locator('#dialog')).to_be_visible(timeout=60000)
        expect(page.locator('#dialog-title')).to_have_text('Clear the Volca and load this kit?', timeout=60000)
        self.answer(page, 'Clear & send')
        expect(page.locator('#dialog-title')).to_have_text('Signals sent', timeout=120000)
        expect(page.locator('#dialog')).to_contain_text('only the Volca can show what it received')
        self.answer(page, 'OK')
        self.assertEqual(len(self.bench.streams), 103)
        self.assertTrue(all(s['rate'] == 44100 and s['channels'] == 2 for s in self.bench.streams))
        # Disconnected output: refused, no fallback.
        self.bench.output_present = False
        page.click('#send-kit')
        expect(page.locator('#dialog')).to_contain_text('not connected', timeout=30000)
        self.answer(page, 'OK')
        self.bench.output_present = True
        self.assertEqual(len(self.bench.streams), 103)
        self.assertEqual(page.errors, [])

    def test_2_commons_export_import_archive(self):
        page = self.page()
        page.click('.spaces button[data-space=commons]')
        row = page.locator('#kits-table tbody tr', has_text='browser-kit')
        expect(row).to_have_count(1)
        with page.expect_download() as info:
            row.get_by_role('button', name='Export ZIP').click()
        archive = self.downloads / 'kit.zip'
        info.value.save_as(archive)
        self.assertTrue(info.value.suggested_filename.endswith('.volcakit.zip'))
        page.set_input_files('#kit-import', str(archive))
        page.locator('#dialog input').fill('browser-kit-imported')
        page.keyboard.press('Enter')
        imported = page.locator('#kits-table tbody tr', has_text='browser-kit-imported')
        expect(imported).to_have_count(1)
        original = self.helper.config.kits / 'browser-kit'
        copy = self.helper.config.kits / 'browser-kit-imported'
        for file in original.glob('*'):
            if file.name != '.studio-kit.json':
                self.assertEqual(file.read_bytes(), (copy / file.name).read_bytes())
        imported.get_by_role('button', name='Move to archive').click()
        self.answer(page, 'Move to archive')
        expect(page.locator('#kits-table tbody tr', has_text='browser-kit-imported')).to_have_count(0)
        page.locator('#trash-list li', has_text='browser-kit-imported').get_by_role('button', name='Restore').click()
        expect(page.locator('#kits-table tbody tr', has_text='browser-kit-imported')).to_have_count(1)
        # Open to edit → reorder → replace keeps the previous version archived.
        page.locator('#kits-table tbody tr', has_text='browser-kit-imported').get_by_role('button', name='Open to edit').click()
        expect(page.locator('#edit-badge')).to_contain_text('editing browser-kit-imported')
        rows = page.locator('#workbench-list .item')
        rows.nth(2).click()
        page.keyboard.press('Delete')
        expect(rows).to_have_count(2)
        page.click('#replace-kit')
        self.answer(page, 'Replace & archive previous')
        expect(page.locator('#minutes-last')).to_contain_text('previous version is archived')
        self.assertEqual(len(list(copy.glob('*.wav'))), 2)
        page.click('.spaces button[data-space=commons]')
        expect(page.locator('#trash-list li', has_text='before edit')).to_have_count(1)
        self.assertEqual(page.errors, [])

    def test_3_patterns_grooves_backup(self):
        page = self.page()
        self.client.post('/api/devices/select', {'output': 'Studio bench::Bench recorder → SYNC IN (silent)',
                                                 'input': 'Studio bench::Bench Volca headphone output',
                                                 'midi': 'Bench MIDI → Volca MIDI IN'})
        page.click('.spaces button[data-space=memory]')
        page.click('#bank-reset')
        expect(page.locator('#bank-view .memory-card')).to_have_count(10)
        page.fill('#bank-name', 'browser-neutral')
        page.click('#bank-save')
        expect(page.locator('#bank-select')).to_contain_text('browser-neutral.vspatterns')
        # Movement: preserve two memories, invalidate on change, save again, send.
        page.click('.spaces button[data-space=movement]')
        expect(page.locator('#groove-parts input')).to_have_count(10, timeout=30000)
        page.click('#groove-none')
        page.locator('#groove-memories label', has_text='1').first.click()
        page.locator('#groove-memories label').nth(2).click()
        expect(page.locator('#groove-scope')).to_contain_text('2 memories selected: 1, 3')
        page.locator('#groove-parts input').nth(0).fill('MPC3000_73_B02 · ' + self.template_name('MPC3000_73_B02'))
        page.fill('#groove-name', 'browser-groove')
        page.click('#groove-save')
        expect(page.locator('#groove-send')).to_be_enabled(timeout=30000)
        expect(page.locator('#groove-status')).to_contain_text('memories 1, 3')
        page.locator('#groove-parts input').nth(1).fill('nonsense')
        expect(page.locator('#groove-send')).to_be_disabled()
        page.click('#groove-save')
        self.answer(page, 'OK')  # "Choose from the list"
        page.locator('#groove-parts input').nth(1).fill('')
        page.fill('#groove-name', 'browser-groove-2')
        page.click('#groove-save')
        expect(page.locator('#groove-send')).to_be_enabled(timeout=30000)
        before = len(self.bench.streams)
        page.click('#groove-send')
        expect(page.locator('#dialog')).to_contain_text('Pattern memories 1, 3 will be replaced', timeout=60000)
        self.answer(page, 'Replace memories')
        expect(page.locator('#dialog-title')).to_have_text('Signals sent', timeout=60000)
        self.answer(page, 'OK')
        self.assertEqual(len(self.bench.streams) - before, 2)
        # Backup through MIDI request + audio input; result shown in the inspector.
        page.click('.spaces button[data-space=memory]')
        page.fill('#backup-name', 'browser-machine')
        page.click('#backup-start')
        self.answer(page, 'Start capture')
        expect(page.locator('#celebration-title')).to_have_text('Pattern backup saved.', timeout=180000)
        expect(page.locator('#bank-view .memory-card')).to_have_count(11)
        expect(page.locator('#bank-view')).to_contain_text('Current snapshot')
        first = page.locator('#bank-view .memory-card').first
        first.locator('summary').click()
        expect(first.locator('.steps16 .p').first).to_be_visible()
        # Denied input permission is explained and saves nothing.
        self.bench.input_error = 'Error opening InputStream: Unanticipated host error [PaErrorCode -9999]'
        page.fill('#backup-name', 'browser-denied')
        page.click('#backup-start')
        self.answer(page, 'Start capture')
        expect(page.locator('#dialog')).to_contain_text('Privacy & Security → Microphone', timeout=60000)
        self.answer(page, 'OK')
        self.bench.input_error = None
        self.assertFalse((self.helper.config.patterns / 'browser-denied.vspatterns').exists())
        self.assertEqual(page.errors, [])

    def template_name(self, ident):
        return next(t['name'] for t in self.client.get('/api/grooves')['templates'] if t['id'] == ident)

    def test_4_firmware_gates(self):
        from volcastudio import lumon_build, updater_codec
        korg_wav, patch_document = lumon_build.synthetic_case()
        korg = Path(self.tmp.name) / 'synthetic.wav'
        korg.write_bytes(korg_wav)
        other = Path(self.tmp.name) / 'other.wav'
        other.write_bytes(updater_codec.synthetic_updater(bytes(updater_codec.IMAGE_SIZE)))
        with lumon_build.override(patch_document):
            page = self.page()
            page.click('.spaces button[data-space=firmware]')
            # Studio ships no firmware: the archive waits for the user's Korg updater.
            expect(page.locator('#firmware-list')).to_contain_text('archive is empty', timeout=30000)
            expect(page.locator('#space-firmware')).to_contain_text('volcasample_updater_1_42.zip')
            expect(page.locator('#firmware-send')).to_be_disabled()
            page.set_input_files('#korg-file', str(other))
            expect(page.locator('#dialog')).to_contain_text('not the official', timeout=60000)
            self.answer(page, 'OK')
            expect(page.locator('#firmware-list .item')).to_have_count(0)
            page.set_input_files('#korg-file', str(korg))
            expect(page.locator('#firmware-list .item')).to_have_count(2, timeout=60000)
            expect(page.locator('#firmware-list .item').nth(0)).to_contain_text('Synthetic OS')
            expect(page.locator('#firmware-list .item').nth(1)).to_contain_text('Korg volca sample')
            expect(page.locator('#minutes-last')).to_contain_text('Studio checked the result', timeout=30000)
            page.locator('#firmware-list .item').nth(0).click()
            expect(page.locator('#firmware-detail')).to_contain_text('built_from')
            expect(page.locator('#accept-experimental')).to_have_count(0)
            before = len(self.bench.streams)
            page.click('#firmware-send')
            expect(page.locator('#dialog-title')).to_have_text('Update the Volca firmware?', timeout=60000)
            expect(page.locator('#dialog')).to_contain_text('FUNC + PLAY')
            self.answer(page, 'Cancel — keep the Volca as it is')
            expect(page.locator('#minutes-last')).to_contain_text('cancelled before sending', timeout=30000)
            self.assertEqual(len(self.bench.streams), before)
            self.assertEqual(page.errors, [])

    def test_5_session_boundaries_layout_and_motion(self):
        context = self.browser.new_context(viewport={'width': 1200, 'height': 800})
        page = context.new_page()
        page.goto(f'http://127.0.0.1:{self.port}/')
        expect(page.locator('#session-notice')).to_contain_text('Open the Browser App with the “VolcaStudio XL Browser App” application')
        stale = context.new_page()
        stale.goto(f'http://127.0.0.1:{self.port}/?again#k=stale-token')
        expect(stale.locator('#session-notice')).to_contain_text('closed Browser App session')
        # The launcher's single-use code is exchanged once for the token.
        code = self.helper.issue_code()
        coded = context.new_page()
        coded.goto(f'http://127.0.0.1:{self.port}/?code#c={code}')
        expect(coded.locator('#minutes-last')).to_contain_text('Welcome')
        reused = context.new_page()
        reused.goto(f'http://127.0.0.1:{self.port}/?reuse#c={code}')
        expect(reused.locator('#session-notice')).to_contain_text('already used or has expired')
        context.close()
        # Narrow window: no horizontal scrolling; spaces become a top bar.
        page = self.page(width=420, height=860)
        overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        self.assertLessEqual(overflow, 0)
        # Reduced-motion preference turns animations off by default.
        page = self.page(reduced_motion='reduce')
        self.assertFalse(page.is_checked('#motion-toggle'))
        self.assertFalse(page.evaluate("document.body.classList.contains('motion')"))
        page.click('#motion-toggle')
        self.assertTrue(page.evaluate("document.body.classList.contains('motion')"))

    def test_6_close_from_the_window(self):
        page = self.page()
        page.click('#close-button')
        self.answer(page, 'Close Browser App')
        expect(page.locator('#session-notice')).to_contain_text('The Browser App is closed')
        self.assertTrue(self.helper.stopping.wait(5))



@unittest.skipUnless(sync_playwright and browser_binary() and os.environ.get('WMC_PACKAGED_APP'),
                     'Set WMC_PACKAGED_APP to a built "VolcaStudio XL Browser App" executable')
class PackagedAppBrowserTests(unittest.TestCase):
    """The frozen helper (bench mode: temporary storage, simulated devices) in Chromium."""

    def test_packaged_helper_round_trip(self):
        import subprocess
        from volcastudio.wmc.verify import Client, tone
        with tempfile.TemporaryDirectory() as tmp:
            sample = tone(Path(tmp) / 'snare_D3.wav', 146.83, seconds=.5)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'VOLCASTUDIO_'))}
            env['HOME'] = str(Path(tmp) / 'home')
            link_file = Path(tmp) / 'link.txt'
            proc = subprocess.Popen([os.environ['WMC_PACKAGED_APP'], '--bench', '--no-browser', '--link-file', str(link_file)],
                                    env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 60
                while not link_file.exists() and time.monotonic() < deadline:
                    time.sleep(.1)
                link = link_file.read_text().strip()
                url, token = link.split('#k=')
                port = int(url.rsplit(':', 1)[1].strip('/'))
                Client(port, token).get('/api/state')  # initial console announcement finished
                proc.stdout.close()  # the desktop launcher has exited; no console reader remains
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=browser_binary())
                    page = browser.new_page(viewport={'width': 1300, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda exc: errors.append(str(exc)))
                    page.goto(link)
                    expect(page.locator('#session-notice')).to_contain_text('Bench mode')
                    page.set_input_files('#add-files', str(sample))
                    expect(page.locator('#library-list .item')).to_have_count(1, timeout=30000)
                    page.locator('#library-list .item').first.click()
                    page.keyboard.press('Enter')
                    page.locator('#workbench-list .item').first.click()
                    page.keyboard.press('k')
                    page.locator('#dialog input.digits').fill('3')
                    page.keyboard.press('Enter')
                    expect(page.locator('#workbench-list .badge-shift')).to_have_text('+3', timeout=60000)
                    page.fill('#kit-name', 'packaged-kit')
                    page.click('#save-kit')
                    expect(page.locator('#kit-status')).to_contain_text('packaged-kit')
                    page.click('.spaces button[data-space=connections]')
                    page.select_option('#device-output', index=1)
                    # The choice is stored asynchronously; the chip reflects the stored state.
                    expect(page.locator('#connection-chip')).to_contain_text('Output: Bench recorder', timeout=30000)
                    page.click('.spaces button[data-space=gathering]')
                    page.click('#send-kit')
                    expect(page.locator('#dialog')).to_be_visible(timeout=60000)
                    expect(page.locator('#dialog-title')).to_have_text('Clear the Volca and load this kit?', timeout=60000)
                    page.locator('#dialog').get_by_role('button', name='Clear & send').click()
                    expect(page.locator('#dialog-title')).not_to_have_text('Clear the Volca and load this kit?', timeout=120000)
                    expect(page.locator('#dialog-title')).to_have_text(re.compile('Signals sent|Stopped|Not'), timeout=120000)
                    self.assertEqual(page.inner_text('#dialog-title'), 'Signals sent',
                                     page.inner_text('#dialog') + '\n' + page.inner_text('#minutes-list'))
                    page.locator('#dialog').get_by_role('button', name='OK').click()
                    page.click('#close-button')
                    page.locator('#dialog').get_by_role('button', name='Close Browser App').click()
                    expect(page.locator('#session-notice')).to_contain_text('The Browser App is closed')
                    browser.close()
                    self.assertEqual(errors, [])
                self.assertEqual(proc.wait(timeout=20), 0)
                self.assertFalse((Path(tmp) / 'home').exists())  # bench mode never touched user storage
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()


if __name__ == '__main__':
    unittest.main()
