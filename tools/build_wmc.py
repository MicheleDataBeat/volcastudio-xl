#!/usr/bin/env python3
"""Build the Browser App local helper on the target OS (no cross-compilation).

The result contains Python, the shared VolcaStudio XL backend, the SYRO
converter, FFmpeg/FFprobe, PortAudio/RtMidi bindings and the Chrome interface.
It does not contain Qt or a browser engine. Users need Google Chrome only.

    python tools/build_syro.py
    python tools/build_wmc.py --ffmpeg /path/to/ffmpeg --ffprobe /path/to/ffprobe --archive

Outputs (under --output-root, default ./build/wmc):
  dist/VolcaStudio XL Browser App/      Windows and Linux application folder
  dist/VolcaStudio XL Browser App.app   macOS application bundle
  VolcaStudio-XL-Browser-<version>-<platform>.zip|.tar.gz (+ .sha256) with --archive
"""
import argparse
import ast
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio.wmc import WMC_VERSION  # noqa: E402

NAME = 'VolcaStudio XL Browser App'
EMBLEM = ('......kkkk......', '....kkkk..kk....', '...kkkkk....k...', '..kkkkkk.....k..',
          '.kkkkkkk......k.', '.kkkkkkk......k.', 'kkkkkkkr.......k', 'kkkkkkrrr......k',
          'kkkkkkkr.......k', 'kkkkkkkk.......k', '.kkkkkkk......k.', '.kkkkkkk......k.',
          '..kkkkkk.....k..', '...kkkkk....k...', '....kkkk..kk....', '......kkkk......')
README_FIRST = """VolcaStudio XL Browser App {version}

1. Keep this whole folder together.
2. Open "VolcaStudio XL Browser App" ({how}).
3. Google Chrome opens the Browser App workspace.

Step by step: "Quick start.md" (English) and "Guida rapida.md" (Italiano),
next to this file. Install Google Chrome separately. No terminal or separate
Python installation is needed.
Firmware: download the official Korg volca sample 1.42 updater
(volcasample_updater_1_42.zip) from korg.com and choose it in Firmware.
The Browser App builds DataBeat OS 1.0 from it and checks the result; no firmware is
included. Patterns use the DataBeat OS 1.0 pattern format.
270 groove templates are in Movement.
"""


def platform_tag():
    machine = platform.machine().lower()
    if sys.platform == 'win32':
        return 'windows-x64' if machine in ('amd64', 'x86_64') else f'windows-{machine}'
    if sys.platform == 'darwin':
        return f'macos-{machine}'
    return f'linux-{machine}'


def write_png(path, size=256):
    """The pixel emblem as a PNG, generated without image libraries."""
    colors = {'k': (28, 34, 49, 255), 'r': (196, 64, 42, 255), '.': (244, 239, 228, 255)}
    cells = 20
    scale = size // cells
    rows = []
    for y in range(size):
        cy = y // scale - 2
        row = bytearray([0])
        for x in range(size):
            cx = x // scale - 2
            key = EMBLEM[cy][cx] if 0 <= cy < 16 and 0 <= cx < 16 else '.'
            row.extend(colors[key])
        rows.append(bytes(row))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def add_macos_metadata(spec):
    """Bundle metadata before PyInstaller builds and signs the .app."""
    tree = ast.parse(spec.read_text())
    bundles = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == 'BUNDLE']
    if len(bundles) != 1:
        raise ValueError('Expected one macOS BUNDLE in the generated specification')
    bundle = bundles[0]
    existing = next((kw for kw in bundle.keywords if kw.arg == 'info_plist'), None)
    metadata = dict(ast.literal_eval(existing.value) if existing is not None else {})
    metadata.update(NSMicrophoneUsageDescription='Record a pattern backup from the headphone output of your Volca Sample.',
                    NSHighResolutionCapable=True, LSUIElement=True,
                    CFBundleDisplayName=NAME, CFBundleName=NAME,
                    CFBundleShortVersionString=WMC_VERSION, CFBundleVersion=WMC_VERSION)
    value = ast.parse(repr(metadata), mode='eval').body
    if existing is None:
        bundle.keywords.append(ast.keyword(arg='info_plist', value=value))
    else:
        existing.value = value
    ast.fix_missing_locations(tree)
    spec.write_text(ast.unparse(tree) + '\n')


def use_system_alsa(spec):
    """Linux: load the desktop's own libasound, so its ALSA/PipeWire plugins match."""
    text = spec.read_text()
    marker = '\npyz = PYZ('
    if marker not in text:
        raise ValueError('Unexpected PyInstaller specification')
    patch = ("\na.binaries = [entry for entry in a.binaries"
             " if not os.path.basename(entry[0]).startswith('libasound.so')]\n")
    spec.write_text('import os\n' + text.replace(marker, patch + marker, 1))


def pyinstaller_options(args, icon):
    converter = ROOT / 'build/syro/bin' / ('volcastudio-syro.' + platform.machine() + ('.exe' if os.name == 'nt' else ''))
    if not converter.is_file() or not os.access(converter, os.X_OK):
        raise SystemExit('Build the native SYRO converter first: python tools/build_syro.py')
    sep = os.pathsep
    options = ['--windowed', '--onedir', '--name', NAME, '--paths', str(ROOT), '--icon', str(icon),
               '--add-data', f'{ROOT / "volcastudio/data"}{sep}volcastudio/data',
               '--add-data', f'{ROOT / "volcastudio/wmc/web"}{sep}volcastudio/wmc/web',
               '--add-data', f'{ROOT / "vendor"}{sep}vendor',
               '--add-binary', f'{converter}{sep}build/syro/bin',
               '--collect-all', 'rtmidi', '--hidden-import', 'mido.backends.rtmidi',
               '--exclude-module', 'PySide6', '--exclude-module', 'shiboken6', '--exclude-module', 'tkinter',
               '--add-data', f'{ROOT / "THIRD_PARTY.md"}{sep}.',
               '--add-data', f'{ROOT / "LICENSE"}{sep}.']
    for doc in ('browser.md', 'browser-quick-start.md', 'browser-quick-start.it.md', 'tuning.md', 'grooves.md',
                'firmware.md', 'patterns.md', 'pattern-audio.md', 'databeat-os-manual.md', 'return-to-korg.md'):
        if (ROOT / 'docs' / doc).is_file():
            options += ['--add-data', f'{ROOT / "docs" / doc}{sep}docs']
    for distribution in ('sounddevice', 'python-rtmidi', 'mido'):
        options += ['--copy-metadata', distribution]
    if args.licenses:
        options += ['--add-data', f'{args.licenses.resolve()}{sep}licenses']
    for supplied in (args.ffmpeg, args.ffprobe):
        options += ['--add-binary', f'{supplied.resolve(strict=True)}{sep}tools-bin']
    return options


def copy_guides(folder):
    shutil.copyfile(ROOT / 'docs/browser-quick-start.md', folder / 'Quick start.md')
    shutil.copyfile(ROOT / 'docs/browser-quick-start.it.md', folder / 'Guida rapida.md')


def archive(app, root):
    tag = platform_tag()
    base = root / f'VolcaStudio-XL-Browser-{WMC_VERSION}-{tag}'
    how = {'win32': 'double-click "VolcaStudio XL Browser App.exe"', 'darwin': 'drag it to Applications, then open it'}.get(
        sys.platform, 'double-click it, or right-click → Run as a program')
    readme = README_FIRST.format(version=WMC_VERSION, how=how)
    if sys.platform == 'darwin':
        target = Path(str(base) + '.zip')
        staging = root / 'archive-staging'
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / 'READ ME FIRST.txt').write_text(readme)
        copy_guides(staging)
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', str(staging), str(target)], check=True)
        shutil.rmtree(staging)
    elif sys.platform == 'win32':
        target = Path(str(base) + '.zip')
        (app / 'READ ME FIRST.txt').write_text(readme.replace('\n', '\r\n'))
        copy_guides(app)
        shutil.make_archive(str(base), 'zip', app.parent, app.name)
    else:
        target = Path(str(base) + '.tar.gz')
        (app / 'READ ME FIRST.txt').write_text(readme)
        copy_guides(app)
        with tarfile.open(target, 'w:gz') as stream:
            stream.add(app, arcname=app.name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    Path(str(target) + '.sha256').write_text(f'{digest}  {target.name}\n')
    return target, digest


def main(argv=None):
    subprocess.run([sys.executable, str(ROOT / 'tools/check_product_name.py'), '--root', str(ROOT)], check=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--ffmpeg', type=Path, required=True, help='Licensed target-platform ffmpeg executable to bundle')
    parser.add_argument('--ffprobe', type=Path, required=True, help='Matching target-platform ffprobe executable')
    parser.add_argument('--licenses', type=Path, help='Directory with notices for the exact FFmpeg build distributed')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'build/wmc')
    parser.add_argument('--archive', action='store_true', help='Also create the distributable archive and its SHA-256')
    args = parser.parse_args(argv)
    for tool, supplied in (('ffmpeg', args.ffmpeg), ('ffprobe', args.ffprobe)):
        expected = tool + ('.exe' if os.name == 'nt' else '')
        if supplied.name != expected or not supplied.is_file():
            parser.error(f'{tool} must be an existing target-platform executable named {expected}')
    if args.licenses and not args.licenses.is_dir():
        parser.error('--licenses must be a directory')
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    icon = write_png(root / 'wmc-icon.png')
    options = pyinstaller_options(args, icon)
    dist, work = root / 'dist', root / 'work'
    entry = str(ROOT / 'tools/wmc_entry.py')
    if sys.platform == 'darwin':
        options += ['--osx-bundle-identifier', 'studio.volca.xl.wmc',
                    '--osx-entitlements-file', str(ROOT / 'packaging/wmc-entitlements.plist')]
        subprocess.run([sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec', '--specpath', str(root),
                        *options, entry], cwd=ROOT, check=True)
        spec = root / f'{NAME}.spec'
        add_macos_metadata(spec)
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', str(dist),
                        '--workpath', str(work), str(spec)], cwd=ROOT, check=True)
        app = dist / f'{NAME}.app'
    else:
        subprocess.run([sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec', '--specpath', str(root),
                        *options, entry], cwd=ROOT, check=True)
        spec = root / f'{NAME}.spec'
        if sys.platform.startswith('linux'):
            use_system_alsa(spec)
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', str(dist),
                        '--workpath', str(work), str(spec)], cwd=ROOT, check=True)
        app = dist / NAME
    if not app.exists():
        raise SystemExit('The build did not produce the expected application.')
    result = {'version': WMC_VERSION, 'platform': platform_tag(), 'application': str(app)}
    if args.archive:
        target, digest = archive(app, root)
        result.update(archive=str(target), sha256=digest, bytes=target.stat().st_size)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
