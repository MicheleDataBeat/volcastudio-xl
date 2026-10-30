"""Single pattern format and firmware choice through real Qt/Chrome controls.

Only temporary storage, generated banks and bench devices are used. A supplied
WMC_TEST_URL can point the Chrome test at an already-running packaged --bench
helper; it must be an isolated bench, never the user's normal session.
"""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORMTHEME'] = 'none'


class WorkspaceProfileTests(unittest.TestCase):
    def test_single_public_profile_and_no_conversion_in_the_workspace(self):
        from volcastudio.wmc.launcher import temporary_config
        from volcastudio.wmc.workspace import Workspace
        from volcastudio.patterns import PATTERN_PROFILE, blank_pattern
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(temporary_config(Path(tmp)))
            self.assertEqual(ws.pattern_profile(PATTERN_PROFILE), PATTERN_PROFILE)
            with self.assertRaisesRegex(ValueError, 'DataBeat OS 1.0 pattern format'):
                ws.pattern_profile('lumon-xl')
            bank = ws.set_bank([blank_pattern('lumon-xl', slot=3), blank_pattern(PATTERN_PROFILE, slot=4),
                                blank_pattern(PATTERN_PROFILE)], 'mixed')
            self.assertEqual([p['compatible_profiles'] for p in bank['patterns']], [[], [PATTERN_PROFILE], [PATTERN_PROFILE]])
            self.assertEqual(bank['patterns'][1]['format'], 'DataBeat OS 1.0 pattern format')
            with self.assertRaises(ValueError):
                ws.restore_patterns('4')
            self.assertEqual([p.slot for p in ws.restore_patterns('5')[0]], [4])
            ws.reset_bank('1,2')
            self.assertEqual([p.firmware for p in ws.bank], [PATTERN_PROFILE] * 2)
            self.assertFalse(any(hasattr(ws, name) for name in ('conversion_plan', 'preview_conversion', 'save_conversion')))


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'Native Qt is required')
class OutieProfileTests(unittest.TestCase):
    def test_actual_controls_single_profile_and_firmware_choice(self):
        from PySide6.QtWidgets import QApplication
        from volcastudio.config import Config
        from volcastudio.outie import Studio
        from volcastudio.profile_acceptance import verify_outie
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window = Studio(Config(root/'cfg', root/'data', root/'state', root/'cache', root/'packs', root/'syro'), discover_devices=False)
            try:
                report = verify_outie(window, app, root)
                self.assertTrue(report['passed'])
                self.assertEqual(report['build_routes'], ['production'])
            finally:
                window.close()


try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None
CHROME = os.environ.get('WMC_TEST_CHROME') or shutil.which('chromium') or shutil.which('google-chrome')


@unittest.skipUnless(sync_playwright and CHROME, 'Existing Playwright and Chrome are required')
class ChromeProfileTests(unittest.TestCase):
    def test_latest_firmware_refresh_survives_an_older_empty_archive_reply(self):
        """The same asynchronous-listing contract covers the firmware archive."""
        from volcastudio.wmc.verify import start
        with tempfile.TemporaryDirectory(prefix='wmc-firmware-race-') as tmp:
            external = os.environ.get('WMC_TEST_URL')
            server = bench = None
            if external:
                url = external
            else:
                helper, server, bench, client = start(Path(tmp)/'helper')
                url = f'{server.url}#k={helper.token}'
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
                    page = browser.new_page()
                    page.goto(url)
                    expect(page.locator('#minutes-last')).to_contain_text('Welcome')
                    state = page.evaluate("""async () => (await fetch('/api/state', {headers: {'X-WMC-Token': sessionStorage.getItem('wmc-token')}})).json()""")
                    self.assertTrue(state['bench'])
                    held = []
                    entry = dict(id='fixture-internal', name='Internal archive fixture', version='1.1-fixture',
                        variant='lumon-xl', status='OFFLINE_QUALIFIED_INTERNAL_CANDIDATE',
                        installable=True, experimental=True, hardware_tested=False,
                        sha256='0'*64, seconds=1.0, provenance='Synthetic browser metadata only')
                    def delayed_archive(route):
                        if not held:
                            held.append(route)
                        else:
                            route.fulfill(json={'entries': [entry], 'error': None})
                    page.route('**/api/firmware', delayed_archive)
                    page.locator('[data-space="firmware"]').click()
                    page.locator('#firmware-refresh').click()
                    expect(page.locator('#firmware-list .item')).to_have_count(1)
                    self.assertEqual(len(held), 1)
                    held[0].fulfill(json={'entries': [], 'error': None})
                    page.wait_for_timeout(150)
                    expect(page.locator('#firmware-list .item')).to_have_count(1)
                    expect(page.locator('#firmware-list')).to_contain_text('Internal archive fixture')
                    browser.close()
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                    bench.uninstall()

    def test_late_empty_listing_cannot_replace_a_newly_uploaded_bank(self):
        """Arm the exact race: old GET completes after a successful upload."""
        from volcastudio.patterns import blank_pattern, save_bank
        from volcastudio.wmc.verify import start
        with tempfile.TemporaryDirectory(prefix='wmc-bank-race-') as tmp:
            root = Path(tmp)
            external = os.environ.get('WMC_TEST_URL')
            helper = server = bench = None
            if external:
                url = external
            else:
                helper, server, bench, client = start(root/'helper')
                url = f'{server.url}#k={helper.token}'
            source = save_bank(root/'newly-uploaded.vspatterns', [blank_pattern(slot=0),
                blank_pattern('lumon-xl-internal', slot=1), blank_pattern()])
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
                    page = browser.new_page()
                    errors, held = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url)
                    expect(page.locator('#minutes-last')).to_contain_text('Welcome')
                    state = page.evaluate("""async () => (await fetch('/api/state', {headers: {'X-WMC-Token': sessionStorage.getItem('wmc-token')}})).json()""")
                    self.assertTrue(state['bench'])
                    def delay_listing(route):
                        if route.request.method != 'GET':
                            route.continue_()
                            return
                        response = route.fetch()
                        self.assertFalse(response.json()['bank']['loaded'], 'Race probe needs a fresh empty bench')
                        held.append((route, response))
                    page.route('**/api/patterns', delay_listing)
                    page.locator('[data-space="memory"]').click()
                    page.set_input_files('#bank-upload', str(source))
                    expect(page.locator('#bank-view .memory-card')).to_have_count(3)
                    self.assertEqual(len(held), 1, 'The stale listing was not intercepted')
                    route, response = held.pop()
                    route.fulfill(response=response)
                    page.wait_for_timeout(150)
                    expect(page.locator('#bank-view .memory-card')).to_have_count(3)
                    expect(page.locator('#bank-label')).to_contain_text('newly-uploaded')
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                    bench.uninstall()

    def test_single_profile_restore_reset_and_single_firmware_build(self):
        from volcastudio.patterns import PATTERN_PROFILE, blank_pattern, save_bank
        from volcastudio.wmc.verify import start
        with tempfile.TemporaryDirectory(prefix='wmc-profile-controls-') as tmp:
            root = Path(tmp)
            external = os.environ.get('WMC_TEST_URL')
            helper = server = bench = None
            if external:
                self.assertIn('127.0.0.1:', external)
                url = external
            else:
                helper, server, bench, client = start(root/'helper')
                url = f'{server.url}#k={helper.token}'
            source = [blank_pattern('lumon-xl', slot=0), blank_pattern(PATTERN_PROFILE, slot=1), blank_pattern('lumon-xl')]
            source_path = save_bank(root/'mixed.vspatterns', source)
            original_bytes = source_path.read_bytes()
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(executable_path=CHROME, args=['--no-sandbox'])
                    context = browser.new_context(viewport={'width': 1250, 'height': 900}, accept_downloads=True)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url)
                    expect(page.locator('#minutes-last')).to_contain_text('Welcome')
                    state = page.evaluate("""async () => (await fetch('/api/state', {headers: {'X-WMC-Token': sessionStorage.getItem('wmc-token')}})).json()""")
                    self.assertTrue(state['bench'], 'Browser verification requires an isolated --bench helper')
                    if os.environ.get('WMC_REQUIRE_FROZEN') == '1':
                        self.assertTrue(state['frozen'])
                    page.locator('[data-space="memory"]').click()
                    expect(page.locator('#pattern-firmware option')).to_have_count(1)
                    expect(page.locator('#pattern-firmware')).to_have_value(PATTERN_PROFILE)
                    expect(page.locator('#pattern-firmware option')).to_have_text('DataBeat OS 1.0 pattern format')
                    for removed in ('#conversion-firmware', '#conversion-preview-button', '#conversion-save'):
                        expect(page.locator(removed)).to_have_count(0)
                    page.set_input_files('#bank-upload', str(source_path))
                    expect(page.locator('#bank-view .memory-card')).to_have_count(3)
                    expect(page.locator('#restore-memories input[value="1"]')).to_be_disabled()
                    expect(page.locator('#restore-memories input[value="2"]')).to_be_checked()
                    expect(page.locator('#current-send')).to_be_disabled()
                    evidence = Path(os.environ['WMC_TEST_REPORT_DIR']) if os.environ.get('WMC_TEST_REPORT_DIR') else None
                    page.locator('#reset-slots').fill('2')
                    page.locator('#bank-reset').click()
                    expect(page.locator('#bank-view .memory-card h4 code')).to_have_text('DataBeat OS 1.0 pattern format')
                    self.assertEqual(source_path.read_bytes(), original_bytes)
                    # Real Korg input is optional and never bundled by this test.
                    korg = os.environ.get('VOLCASTUDIO_KORG_UPDATER')
                    if korg:
                        page.locator('[data-space="firmware"]').click()
                        expect(page.locator('#firmware-build-target')).to_have_count(0)
                        page.set_input_files('#korg-file', korg)
                        expect(page.locator('#operation')).to_be_hidden(timeout=180000)
                        expect(page.locator('#minutes-last')).to_contain_text('built from your Korg updater', timeout=180000)
                        expect(page.locator('#firmware-list .item')).to_have_count(2)
                        expect(page.locator('#firmware-list')).to_contain_text('DataBeat OS 1.0')
                        expect(page.locator('#accept-experimental')).to_have_count(0)
                        # The built release is selected and sendable; nothing is played here.
                        expect(page.locator('#firmware-send')).to_be_enabled()
                        if bench is not None:
                            self.assertEqual(bench.streams, [])
                    self.assertEqual(errors, [])
                    if evidence:
                        evidence.mkdir(parents=True, exist_ok=True)
                        report = dict(passed=True, frozen=state['frozen'], backend_version=state['backend_version'],
                            bench=True, hardware_access=False, real_korg_build_controls=bool(korg),
                            source_file_unchanged=True, single_pattern_profile=True, conversion_controls_absent=True,
                            selectors_exercised=['#bank-upload', '#pattern-firmware', '#reset-slots', '#bank-reset'] +
                                (['#korg-file', '#firmware-send'] if korg else []),
                            limits=['Real Chrome DOM and helper routes. Bench devices and temporary storage only.',
                                    'No firmware signal was played or physical device opened.'])
                        (evidence/'chrome-profile-controls.json').write_text(json.dumps(report, indent=2)+'\n')
                        page.screenshot(path=str(evidence/'chrome-final-controls.png'), full_page=True)
                    context.close()
                    browser.close()
            finally:
                if server is not None:
                    server.shutdown()
                    server.server_close()
                    bench.uninstall()


if __name__ == '__main__':
    unittest.main()
