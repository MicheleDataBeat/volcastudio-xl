"""Download page assembly and its OS-aware button in a real Chromium."""
import functools
import hashlib
import http.server
import json
import re
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from tests.test_wmc_browser import browser_binary, sync_playwright
from tools.prepare_wmc_site import main as prepare
from tools.prepare_wmc_site import markdown
from volcastudio import __version__
from volcastudio.wmc import WMC_VERSION

BASE = 'https://github.com/MicheleDataBeat/volcastudio-xl-releases/releases/download/v' + __version__
NAMES = [f'VolcaStudio-XL-Browser-{WMC_VERSION}-windows-x64.zip', f'VolcaStudio-XL-Browser-{WMC_VERSION}-macos-arm64.zip',
         f'VolcaStudio-XL-Browser-{WMC_VERSION}-linux-x86_64.tar.gz',
         f'VolcaStudio-XL-Desktop-{__version__}-windows-x64.zip',
         f'VolcaStudio-XL-Desktop-{__version__}-linux-x86_64.tar.gz',
         'VolcaStudio-XL-Browser-0.0.1-linux-x86_64.tar.gz']
# Retired product and edition names; the generated site must not show them.
RETIRED = re.compile('|'.join(['lu' + 'mon', r'\bout' + r'ie\b', r'\binn' + r'ie\b', r'\bw' + r'mc\b',
                               'whole ' + 'mind', 'sever' + 'ance', 'reinte' + 'gration', r'Volca[ -]Studio']), re.I)


class ReleaseSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.packages = Path(self.tmp.name) / 'packages'
        self.packages.mkdir()
        for name in NAMES:
            (self.packages / name).write_bytes(name.encode())
            digest = hashlib.sha256(name.encode()).hexdigest()
            Path(str(self.packages / name) + '.sha256').write_text(f'{digest}  {name}\n')

    def build(self, *extra):
        output = Path(self.tmp.name) / 'site'
        with unittest.mock.patch('builtins.print'):
            self.assertEqual(prepare(['--packages', str(self.packages), '--output', str(output), *extra]), 0)
        return output, json.loads((output / 'downloads.json').read_text())

    def test_all_editions_link_to_release_assets(self):
        output, data = self.build('--download-base', BASE)
        self.assertEqual(data['version'], __version__)
        listed = {(p['edition'], p['system']): p['file'] for p in data['packages']}
        self.assertEqual(set(listed), {('browser', 'windows'), ('browser', 'macos'), ('browser', 'linux'),
                                       ('desktop', 'windows'), ('desktop', 'linux')})
        self.assertTrue(all(url.startswith(BASE + '/') for url in listed.values()))
        self.assertFalse((output / 'downloads').exists())
        self.assertTrue((output / 'docs/browser-quick-start.it.html').is_file())

    def test_unreleased_version_lists_no_packages(self):
        output = Path(self.tmp.name) / 'site'
        with unittest.mock.patch('builtins.print'):
            self.assertEqual(prepare(['--unreleased', '--output', str(output)]), 0)
        data = json.loads((output / 'downloads.json').read_text())
        self.assertEqual((data['version'], data['packages']), (__version__, []))
        self.assertFalse((output / 'downloads').exists())
        self.assertTrue((output / 'docs/databeat-os.html').is_file())

    def test_checksum_mismatch_is_refused(self):
        Path(str(self.packages / NAMES[0]) + '.sha256').write_text('0' * 64 + '  x\n')
        with self.assertRaises(SystemExit), unittest.mock.patch('sys.stderr'):
            self.build()

    def test_wrapped_user_instructions_stay_inside_the_list_item(self):
        rendered = markdown('- First instruction\n  with its continuation.\n- Second instruction\n')
        self.assertIn('<li>First instruction with its continuation.</li>', rendered)
        self.assertNotIn('<p>', rendered)

    def test_firmware_manual_and_pattern_guide_are_linked_locally(self):
        output, _ = self.build('--download-base', BASE)
        manual = (output / 'docs/databeat-os.html').read_text()
        self.assertIn('DataBeat OS 1.0', manual)
        self.assertIn('id="patterns-and-studio"', manual)
        self.assertIn('href="patterns.html"', manual)
        patterns = (output / 'docs/patterns.html').read_text()
        self.assertIn('DataBeat OS 1.0 pattern format', patterns)
        self.assertNotIn('Convert bank offline', patterns)
        self.assertIn('href="databeat-os.html"', (output / 'docs/firmware.html').read_text())

    def test_generated_site_uses_current_names_only(self):
        output, _ = self.build('--download-base', BASE)
        pages = sorted(output.rglob('*.html')) + [output / 'site.js']
        self.assertGreater(len(pages), 10)
        for page in pages:
            found = RETIRED.findall(page.read_text())
            self.assertEqual(found, [], page.relative_to(output))

    def test_wrapped_control_labels_and_tuning_commands_render_as_markdown(self):
        rendered = markdown('1. Choose **Preview selected\n   sample**, then [tuning](tuning.md).\n\n```sh\nvolcastudio varispeed "sample.wav" --semitones -7\n```\n')
        self.assertIn('<strong>Preview selected sample</strong>', rendered)
        self.assertIn('href="tuning.html"', rendered)
        self.assertIn('<pre><code>volcastudio varispeed', rendered)
        self.assertNotIn('**', rendered)
        self.assertNotIn('```', rendered)

    def test_public_pages_include_their_brand_and_preview_assets(self):
        output, _ = self.build('--download-base', BASE)
        self.assertTrue((output / 'assets/databeat-mark.svg').is_file())
        self.assertTrue((output / 'assets/volcastudio-xl-editions.svg').is_file())
        self.assertTrue((output / 'assets/volcastudio-xl-editions.png').is_file())
        guide = (output / 'docs/browser.html').read_text()
        self.assertIn('../assets/databeat-mark.svg', guide)
        self.assertNotIn('<h2>Developers</h2>', guide)
        self.assertIn('href="firmware.html"', guide)

    def test_firmware_guide_explains_the_korg_download(self):
        output, _ = self.build('--download-base', BASE)
        firmware = (output / 'docs/firmware.html').read_text()
        self.assertIn('https://www.korg.com/us/support/download/software/0/370/1475/', firmware)
        self.assertIn('volcasample_updater_1_42.zip', firmware)
        self.assertIn('href="databeat-os.html"', firmware)
        self.assertIn('dAtAbEAt OS', (output / 'docs/databeat-os.html').read_text())
        index = (output / 'index.html').read_text()
        self.assertIn('docs/firmware.html', index)
        self.assertNotIn('1.0.1', index + (output / 'site.js').read_text())

    @unittest.skipUnless(sync_playwright and browser_binary(), 'Playwright and a Chromium-based browser are required')
    def test_button_picks_the_browser_app_package_for_the_visitors_system(self):
        output, _ = self.build('--download-base', BASE)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        handler = functools.partial(Quiet, directory=str(output))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_address[1]}/'
        agents = {'windows': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36',
                  'linux': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36',
                  'macos': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140.0 Safari/537.36'}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=browser_binary())
            try:
                for system, agent in agents.items():
                    page = browser.new_page(user_agent=agent, locale='it-IT')
                    # Chrome reports the real OS through userAgentData; pin both to the visitor's.
                    platform = {'windows': 'Win32', 'linux': 'Linux x86_64', 'macos': 'MacIntel'}[system]
                    page.add_init_script(f"""
                        Object.defineProperty(Navigator.prototype, 'userAgentData', {{ get: () => undefined }});
                        Object.defineProperty(Navigator.prototype, 'platform', {{ get: () => '{platform}' }});""")
                    page.goto(url)
                    page.wait_for_function("document.querySelectorAll('#download-rows tr').length === 5")
                    href = page.get_attribute('#cta', 'href')
                    self.assertTrue(href.startswith(BASE + f'/VolcaStudio-XL-Browser-{WMC_VERSION}-{system}'), href)
                    self.assertEqual(page.text_content('#cta'), 'Download Browser App')
                    self.assertEqual(page.get_attribute('html', 'lang'), 'en')
                    self.assertEqual(page.get_attribute('#guide-link', 'href'), 'docs/browser-quick-start.html')
                    page.get_by_role('button', name='Italiano', exact=True).click()
                    self.assertEqual(page.text_content('#cta'), 'Scarica la Browser App')
                    self.assertEqual(page.get_attribute('#guide-link', 'href'), 'docs/browser-quick-start.it.html')
                    page.reload()
                    page.wait_for_function("document.querySelectorAll('#download-rows tr').length === 5")
                    self.assertEqual(page.get_attribute('html', 'lang'), 'it')
                    page.get_by_role('button', name='English', exact=True).click()
                    self.assertEqual(page.get_attribute('html', 'lang'), 'en')
                    self.assertIn('Desktop App', page.text_content('#download-rows'))
                    self.assertEqual(page.get_attribute('#repo-link', 'href'),
                                     'https://github.com/MicheleDataBeat/volcastudio-xl-releases')
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),
                                         page.evaluate('window.innerWidth'))
                    page.close()
                phone = browser.new_page(viewport={'width': 375, 'height': 700})
                phone.goto(url)
                phone.wait_for_function("document.querySelectorAll('#download-rows tr').length === 5")
                self.assertLessEqual(phone.evaluate('document.documentElement.scrollWidth'), 375)
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
