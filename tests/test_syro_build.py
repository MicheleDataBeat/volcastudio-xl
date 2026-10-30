import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from tools import build_syro as builder
from volcastudio import transfer
from volcastudio.patterns import blank_pattern


class SyroBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native_temporary = tempfile.TemporaryDirectory(prefix='studio-native-sdk-')
        cls.addClassCleanup(cls.native_temporary.cleanup)
        cls.native = Path(cls.native_temporary.name) / 'backend'
        cls.binary = builder.build_syro(cls.native)

    @classmethod
    def tearDownClass(cls):
        cls.native_temporary.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='studio-sdk-build-')
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def existing_build(self):
        output = self.root / 'backend'
        shutil.copytree(self.native, output)
        return output, output / 'bin' / builder.executable_name(), output / 'bin' / 'build.json'

    def test_vendor_sources_retain_upstream_checksums_and_license(self):
        provenance = json.loads((builder.SDK / 'PROVENANCE.json').read_text())
        self.assertEqual(provenance['revision'], 'b0ed615f18c230a18b378d9ddc6a936971597e4e')
        self.assertEqual(provenance['license'], 'BSD-3-Clause')
        self.assertEqual(provenance['modifications'], [])
        for name, expected in provenance['files'].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((builder.SDK / name).read_bytes()).hexdigest(), expected)
        self.assertEqual({path.suffix for path in builder.SDK.rglob('*') if path.is_file()},
                         {'.c', '.h', '.md', '.json', ''})

    def test_real_bundled_backend_encodes_samples_erase_and_patterns_offline(self):
        sample = self.root / 'normalized sample.wav'
        with wave.open(str(sample), 'wb') as audio:
            audio.setparams((1, 2, 31250, 0, 'NONE', 'not compressed'))
            audio.writeframes(struct.pack('<64h', *range(-32, 32)))
        pattern = self.root / 'pattern.bin'
        pattern.write_bytes(blank_pattern('lumon-xl', 9).data)
        self.assertEqual(transfer.converter(self.native), self.binary)
        with patch.object(transfer, 'play_stream') as player:
            for argument in (f's0c:{sample}', 'e99:', f'p10:{pattern}'):
                signal = self.root / (argument[0] + '.wav')
                transfer.checked([self.binary, signal, argument],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                transfer.verify_stream(signal)
        player.assert_not_called()
        stamp = json.loads((self.native / 'bin' / 'build.json').read_text())
        self.assertIn('-std=c99', stamp['flags'])
        self.assertEqual(stamp['executable_sha256'], hashlib.sha256(self.binary.read_bytes()).hexdigest())

    def test_unchanged_build_is_reused_without_running_the_compiler(self):
        output, binary, stamp = self.existing_build()
        before = (binary.stat().st_mtime_ns, stamp.stat().st_mtime_ns)
        with patch.object(builder.subprocess, 'run', side_effect=AssertionError('unnecessary compile')):
            self.assertEqual(builder.build_syro(output), binary)
        self.assertEqual((binary.stat().st_mtime_ns, stamp.stat().st_mtime_ns), before)

    def test_tampered_binary_is_rebuilt_from_sources(self):
        output, binary, _ = self.existing_build()
        binary.write_bytes(b'broken executable')
        rebuilt = builder.build_syro(output)
        self.assertEqual(rebuilt.read_bytes(), self.binary.read_bytes())

    def test_changed_header_invalidates_the_cached_backend(self):
        output, binary, stamp = self.existing_build()
        sdk = self.root / 'sdk'
        shutil.copytree(builder.SDK, sdk)
        header = sdk / 'syro' / 'korg_syro_type.h'
        header.write_bytes(header.read_bytes() + b'\n/* changed build input */\n')
        real_run = subprocess.run
        with patch.object(builder, 'SDK', sdk), \
                patch.object(builder.subprocess, 'run', wraps=real_run) as compiler:
            self.assertEqual(builder.build_syro(output), binary)
        compiler.assert_called_once()
        self.assertEqual(json.loads(stamp.read_text())['sources']['syro/korg_syro_type.h'],
                         hashlib.sha256(header.read_bytes()).hexdigest())

    def test_missing_compiler_fails_before_creating_output(self):
        output = self.root / 'missing'
        with patch.object(builder.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'C compiler'):
                builder.build_syro(output, 'missing-compiler')
        self.assertFalse(output.exists())

    def test_compilation_failure_preserves_previous_backend_and_stamp(self):
        output, binary, stamp = self.existing_build()
        original = binary.read_bytes(), stamp.read_bytes()
        with patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess(
                ['cc'], 1, stdout='', stderr='compile error')):
            with self.assertRaisesRegex(ValueError, 'compile error'):
                builder.build_syro(output, force=True)
        self.assertEqual((binary.read_bytes(), stamp.read_bytes()), original)
        self.assertEqual(list(binary.parent.glob('.build-*')), [])

    def test_success_without_executable_does_not_replace_previous_build(self):
        output, binary, stamp = self.existing_build()
        original = binary.read_bytes(), stamp.read_bytes()
        with patch.object(builder.subprocess, 'run', return_value=subprocess.CompletedProcess(
                ['cc'], 0, stdout='', stderr='')):
            with self.assertRaisesRegex(ValueError, 'did not produce'):
                builder.build_syro(output, force=True)
        self.assertEqual((binary.read_bytes(), stamp.read_bytes()), original)

    def test_stamp_publication_failure_restores_previous_executable(self):
        output, binary, stamp = self.existing_build()
        original = binary.read_bytes(), stamp.read_bytes()
        real_replace = os.replace

        def replace(source, destination):
            if Path(destination) == stamp:
                raise OSError('stamp publication failed')
            return real_replace(source, destination)

        def compile_backend(command, **kwargs):
            Path(command[command.index('-o') + 1]).write_bytes(b'new compiled executable')
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

        with patch.object(builder.subprocess, 'run', side_effect=compile_backend), \
                patch.object(builder.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'stamp publication'):
                builder.build_syro(output, force=True)
        self.assertEqual((binary.read_bytes(), stamp.read_bytes()), original)
        self.assertEqual(list(binary.parent.glob('.build-*')), [])

    def test_initial_publication_failure_removes_only_new_backend(self):
        output = self.root / 'backend'
        stamp = output / 'bin' / 'build.json'
        real_replace = os.replace

        def replace(source, destination):
            if Path(destination) == stamp:
                raise OSError('stamp publication failed')
            return real_replace(source, destination)

        def compile_backend(command, **kwargs):
            Path(command[command.index('-o') + 1]).write_bytes(b'compiled executable')
            return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

        with patch.object(builder.subprocess, 'run', side_effect=compile_backend), \
                patch.object(builder.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError):
                builder.build_syro(output)
        self.assertFalse((stamp.parent / builder.executable_name()).exists())
        self.assertEqual(list(stamp.parent.iterdir()), [])

    def test_symlink_backend_cannot_overwrite_another_file(self):
        output, binary, _ = self.existing_build()
        target = self.root / 'unrelated'
        target.write_bytes(b'keep')
        binary.unlink()
        binary.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            builder.build_syro(output, force=True)
        self.assertTrue(binary.is_symlink())
        self.assertEqual(target.read_bytes(), b'keep')

    def test_compiler_command_with_spaces_is_passed_without_a_shell(self):
        output = self.root / 'output with spaces'
        compiler = self.root / 'custom compiler.py'
        compiler.write_text('import pathlib,sys\n'
                            'assert "-std=c99" in sys.argv\n'
                            'pathlib.Path(sys.argv[sys.argv.index("-o")+1]).write_bytes(b"compiler output")\n')
        command = shlex.quote(sys.executable) + ' ' + shlex.quote(str(compiler))
        with patch.dict(os.environ, {'CC': command}):
            binary = builder.build_syro(output)
        self.assertEqual(binary.read_bytes(), b'compiler output')
        self.assertEqual(json.loads((binary.parent / 'build.json').read_text())['compiler'],
                         [sys.executable, str(compiler)])

    def test_missing_backend_reports_standalone_build_command(self):
        with self.assertRaisesRegex(ValueError, 'python3 tools/build_syro.py'):
            transfer.converter(self.root / 'missing')


if __name__ == '__main__':
    unittest.main()
