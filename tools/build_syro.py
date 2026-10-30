#!/usr/bin/env python3
"""Build the bundled Korg SYRO backend offline with a system C compiler."""
import argparse
import sys
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import locking as fcntl
SDK = ROOT / 'vendor' / 'korg-syro'
DEFAULT_OUTPUT = ROOT / 'build' / 'syro'
SOURCES = (
    'syro/korg_syro_comp.c',
    'syro/korg_syro_func.c',
    'syro/korg_syro_volcasample.c',
    'example/korg_syro_volcasample_example.c',
)


def executable_name():
    return 'volcastudio-syro.' + platform.machine() + ('.exe' if os.name == 'nt' else '')


def source_hashes():
    """Hash every bundled build input, including headers and license."""
    files = [SDK / 'COPYING', SDK / 'PROVENANCE.json']
    files.extend(sorted(path for path in SDK.rglob('*') if path.suffix in ('.c', '.h')))
    return {str(path.relative_to(SDK)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def build_syro(output_dir=None, compiler=None, *, force=False):
    """Publish a complete executable only after successful offline compilation.

    Compiler or publication failures retain the previous working executable
    and stamp. A lock serializes builds into the same output directory.
    """
    output = Path(output_dir or DEFAULT_OUTPUT).expanduser().resolve()
    command = shlex.split(compiler or os.environ.get('CC', 'cc'))
    if not command or not shutil.which(command[0]):
        raise ValueError('A C compiler is required; install one or set CC.')
    inputs = {'schema': 1, 'architecture': platform.machine(), 'compiler': command,
              'flags': ['-std=c99', '-O3'], 'sources': source_hashes()}
    output.mkdir(parents=True, exist_ok=True)
    binary_dir = output / 'bin'
    binary_dir.mkdir(exist_ok=True)
    binary = binary_dir / executable_name()
    stamp = binary_dir / 'build.json'
    with (output / '.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            prior = json.loads(stamp.read_text())
        except (OSError, ValueError):
            prior = None
        if not force and os.access(binary, os.X_OK) and prior:
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            if prior == dict(inputs, executable_sha256=digest):
                return binary
        if binary.is_symlink() or (binary.exists() and not binary.is_file()):
            raise ValueError(f'Refusing to replace a non-regular backend: {binary}')
        with tempfile.TemporaryDirectory(prefix='.build-', dir=binary_dir) as temporary:
            stage = Path(temporary)
            pending = stage / binary.name
            result = subprocess.run(
                command + inputs['flags'] + [str(SDK / path) for path in SOURCES]
                + ['-o', str(pending)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout).strip()
                raise ValueError(f'SYRO backend compilation failed: {detail}')
            if not pending.is_file() or pending.stat().st_size == 0:
                raise ValueError('C compiler did not produce a SYRO backend.')
            pending.chmod(0o755)
            pending_stamp = stage / 'build.json'
            pending_stamp.write_text(json.dumps(
                dict(inputs, executable_sha256=hashlib.sha256(pending.read_bytes()).hexdigest()),
                indent=2, sort_keys=True) + '\n')
            backup = stage / 'previous-backend'
            if binary.exists():
                shutil.copy2(binary, backup)
            os.replace(pending, binary)
            try:
                os.replace(pending_stamp, stamp)
            except BaseException:
                if backup.exists():
                    os.replace(backup, binary)
                else:
                    binary.unlink()
                raise
        return binary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--compiler', help='C compiler command; defaults to CC or cc')
    parser.add_argument('--force', action='store_true', help='rebuild even when inputs match')
    options = parser.parse_args(argv)
    try:
        binary = build_syro(options.output_dir, options.compiler, force=options.force)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(binary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
