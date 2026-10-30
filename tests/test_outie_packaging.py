import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import build_outie
from tools.build_outie import add_macos_privacy
from tools.build_wmc import use_system_alsa


class VersionTests(unittest.TestCase):
    def test_static_project_version_changes_together_with_the_package_version(self):
        import re
        import tomllib
        from volcastudio import __version__
        from volcastudio.wmc import WMC_VERSION
        project = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['project']
        # pyproject.toml holds the PEP 440 spelling: a pre-release label becomes local metadata.
        release, _, label = __version__.partition('-')
        expected = release + ('+' + re.sub(r'[^A-Za-z0-9.]', '.', label) if label else '')
        self.assertEqual(project['version'], expected)
        self.assertEqual(WMC_VERSION, __version__)


class PackagingTests(unittest.TestCase):
    def test_mac_metadata_is_inserted_before_build_and_retains_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / 'app.spec'
            spec.write_text("app = BUNDLE(coll, name='VolcaStudio XL Desktop App.app', info_plist={'Existing': 'retained'})\n")
            add_macos_privacy(spec)
            tree = ast.parse(spec.read_text())
            call = tree.body[0].value
            metadata = ast.literal_eval(next(k.value for k in call.keywords if k.arg == 'info_plist'))
            self.assertEqual(metadata['Existing'], 'retained')
            self.assertIn('Volca', metadata['NSMicrophoneUsageDescription'])
            self.assertTrue(metadata['NSHighResolutionCapable'])
            from volcastudio import __version__
            self.assertEqual(metadata['CFBundleShortVersionString'], __version__)
            self.assertEqual(metadata['CFBundleVersion'], __version__)
            self.assertEqual(metadata['CFBundleDisplayName'], 'VolcaStudio XL Desktop App')

    def test_wrong_spec_is_not_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / 'app.spec'
            spec.write_text('app = COLLECT(exe)\n')
            with self.assertRaises(ValueError):
                add_macos_privacy(spec)
            self.assertEqual(spec.read_text(), 'app = COLLECT(exe)\n')

    def test_linux_build_excludes_bundled_libasound(self):
        # The 0.9.3 Linux package carried Ubuntu's libasound, whose plugin
        # directory does not exist elsewhere: only raw hw: devices were listed.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()  # macOS /var -> /private/var, Windows short names
            spec = root / 'VolcaStudio XL Desktop App.spec'
            calls = []
            def run(command, **kwargs):
                calls.append([str(part) for part in command])
                if 'PyInstaller.utils.cliutils.makespec' in command:
                    spec.write_text("a = Analysis(['entry.py'])\npyz = PYZ(a.pure)\n")
            fake_root = root / 'checkout'
            converter = fake_root / 'build/syro/bin'
            converter.mkdir(parents=True)
            import platform
            native = converter / (f'volcastudio-syro.{platform.machine()}' + ('.exe' if os.name == 'nt' else ''))
            native.write_text('#!/bin/sh\n')
            native.chmod(0o755)
            suffix = '.exe' if os.name == 'nt' else ''
            for tool in ('ffmpeg', 'ffprobe'):
                (root / (tool + suffix)).write_text('')
            argv = ['build_outie.py', '--ffmpeg', str(root / ('ffmpeg' + suffix)), '--ffprobe', str(root / ('ffprobe' + suffix)), '--output-root', str(root)]
            with patch.object(build_outie, 'ROOT', fake_root), patch.object(build_outie.subprocess, 'run', side_effect=run), \
                    patch.object(build_outie.sys, 'argv', argv), patch.object(build_outie.sys, 'platform', 'linux'):
                build_outie.main()
            self.assertEqual(len(calls), 3)
            self.assertTrue(calls[0][1].endswith('check_product_name.py'))
            self.assertIn('PyInstaller.utils.cliutils.makespec', calls[1])
            self.assertEqual(Path(calls[2][-1]).resolve(), spec.resolve())
            self.assertIn("startswith('libasound.so')", spec.read_text())
            self.assertIn('pyz = PYZ(', spec.read_text())

    def test_system_alsa_filter_is_inserted_before_pyz(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / 'app.spec'
            spec.write_text("a = Analysis(['entry.py'])\npyz = PYZ(a.pure)\n")
            use_system_alsa(spec)
            text = spec.read_text()
            self.assertTrue(text.startswith('import os\n'))
            self.assertLess(text.index('libasound.so'), text.index('pyz = PYZ('))
            other = Path(tmp) / 'other.spec'
            other.write_text('nothing\n')
            with self.assertRaises(ValueError):
                use_system_alsa(other)
            self.assertEqual(other.read_text(), 'nothing\n')
