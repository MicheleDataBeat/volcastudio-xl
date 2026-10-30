#!/usr/bin/env python3
"""Build the Desktop App on the target OS; no cross-compilation or downloads."""
import argparse
import ast
import json
import os
import platform
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import __version__

NAME = 'VolcaStudio XL Desktop App'



def add_macos_privacy(spec):
    """Set bundle metadata before PyInstaller constructs/signs the .app."""
    tree = ast.parse(spec.read_text())
    bundles = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == 'BUNDLE']
    if len(bundles) != 1:
        raise ValueError('Expected one macOS BUNDLE in the generated specification')
    bundle = bundles[0]
    existing = next((kw for kw in bundle.keywords if kw.arg == 'info_plist'), None)
    metadata = ast.literal_eval(existing.value) if existing is not None else {}
    metadata = dict(metadata or {})
    metadata.update(NSMicrophoneUsageDescription='Capture pattern backups from the audio output of your Volca Sample.',
                    NSHighResolutionCapable=True,
                    CFBundleDisplayName=NAME,
                    CFBundleShortVersionString=__version__, CFBundleVersion=__version__)
    value = ast.parse(repr(metadata), mode='eval').body
    if existing is None:
        bundle.keywords.append(ast.keyword(arg='info_plist', value=value))
    else:
        existing.value = value
    ast.fix_missing_locations(tree)
    spec.write_text(ast.unparse(tree) + '\n')

def main():
    subprocess.run([sys.executable, str(ROOT / 'tools/check_product_name.py'), '--root', str(ROOT)], check=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, required=True, help='Licensed target-platform ffmpeg executable to bundle')
    parser.add_argument('--ffprobe', type=Path, required=True, help='Matching target-platform ffprobe executable')
    parser.add_argument('--licenses', type=Path, help='Additional distribution license/source notices, e.g. for the chosen FFmpeg build')
    parser.add_argument('--output-root', type=Path, help='Keep dist, work and generated specs in this separate directory')
    parser.add_argument('--archive', action='store_true', help='Also create the distributable archive and its SHA-256')
    args = parser.parse_args()
    converter = ROOT / 'build/syro/bin'
    native = converter / ('volcastudio-syro.' + platform.machine() + ('.exe' if os.name == 'nt' else ''))
    if not native.is_file() or not os.access(native, os.X_OK):
        parser.error('Build the native SYRO converter first: python tools/build_syro.py')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
               '--name', NAME, '--paths', str(ROOT),
               '--add-data', str(ROOT / 'volcastudio/data') + os.pathsep + 'volcastudio/data',
               '--add-data', str(ROOT / 'packaging/outie.svg') + os.pathsep + 'assets',
               '--add-data', str(ROOT / 'vendor') + os.pathsep + 'vendor',
               '--add-binary', str(native) + os.pathsep + 'build/syro/bin',
               '--collect-all', 'rtmidi',
               '--hidden-import', 'mido.backends.rtmidi',
               '--add-data', str(ROOT / 'docs/desktop.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/grooves.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/tuning.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/firmware.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/databeat-os-manual.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/return-to-korg.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/patterns.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'docs/pattern-audio.md') + os.pathsep + 'docs',
               '--add-data', str(ROOT / 'THIRD_PARTY.md') + os.pathsep + '.',
               '--add-data', str(ROOT / 'LICENSE') + os.pathsep + '.']
    for distribution in ('PySide6', 'shiboken6', 'sounddevice', 'python-rtmidi', 'mido'):
        command += ['--copy-metadata', distribution]
    if args.licenses:
        if not args.licenses.is_dir():
            parser.error('--licenses must be a directory containing distribution notices')
        command += ['--add-data', str(args.licenses.resolve()) + os.pathsep + 'licenses']
    for tool, supplied in [('ffmpeg', args.ffmpeg), ('ffprobe', args.ffprobe)]:
        expected = tool + ('.exe' if os.name == 'nt' else '')
        if supplied.name != expected or not supplied.is_file():
            parser.error(f'{tool} must be an existing target-platform executable named {expected}')
    if args.ffmpeg:
        command += ['--add-binary', str(args.ffmpeg.resolve(strict=True)) + os.pathsep + 'tools-bin']
    if args.ffprobe:
        command += ['--add-binary', str(args.ffprobe.resolve(strict=True)) + os.pathsep + 'tools-bin']
    command.append(str(ROOT / 'tools/outie_entry.py'))
    output_root = args.output_root.resolve() if args.output_root else ROOT
    if args.output_root:
        output_root.mkdir(parents=True, exist_ok=True)
        command[3:3] = ['--distpath', str(output_root / 'dist'),
                        '--workpath', str(output_root / 'work'),
                        '--specpath', str(output_root)]
    if sys.platform == 'darwin' or sys.platform.startswith('linux'):
        # macOS needs bundle metadata; Linux must not ship Ubuntu's libasound,
        # whose compiled-in plugin directory hides the desktop's ALSA/PipeWire
        # devices on other distributions. Both edit the generated specification.
        if sys.platform == 'darwin':
            command[-1:-1] = ['--osx-bundle-identifier', 'studio.volca.xl.outie',
                              '--osx-entitlements-file', str(ROOT / 'packaging/outie-entitlements.plist')]
        options = [arg for arg in command[3:] if arg not in ('--noconfirm', '--clean')]
        for flag in ('--distpath', '--workpath'):
            if flag in options:
                index = options.index(flag)
                del options[index:index + 2]
        subprocess.run([sys.executable, '-m', 'PyInstaller.utils.cliutils.makespec', *options], cwd=ROOT, check=True)
        spec = output_root / f'{NAME}.spec'
        if sys.platform == 'darwin':
            add_macos_privacy(spec)
        else:
            from tools.build_wmc import use_system_alsa
            use_system_alsa(spec)
        build = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean']
        if args.output_root:
            build += ['--distpath', str(output_root / 'dist'), '--workpath', str(output_root / 'work')]
        subprocess.run([*build, str(spec)], cwd=ROOT, check=True)
    else:
        subprocess.run(command, cwd=ROOT, check=True)
    if args.archive:
        dist = output_root / 'dist'
        app = dist / (NAME + ('.app' if sys.platform == 'darwin' else ''))
        target, digest = archive_outie(app, output_root)
        print(json.dumps({'version': __version__, 'archive': str(target), 'sha256': digest,
                          'bytes': target.stat().st_size}, indent=2))


README_FIRST = """VolcaStudio XL Desktop App {version}

1. Keep this whole folder together.
2. Open "VolcaStudio XL Desktop App" ({how}).

Firmware: download the official Korg volca sample 1.42 updater
(volcasample_updater_1_42.zip) from korg.com, then choose Firmware → Add Korg
1.42 updater. Studio builds DataBeat OS 1.0 from it and checks the result.
No firmware is included. Patterns use the DataBeat OS 1.0 pattern format.
Groove templates are in Grooves.
Guides in this download (desktop.md, firmware.md, patterns.md,
databeat-os-manual.md and return-to-korg.md):
- Windows/Linux: _internal/docs/
- macOS: VolcaStudio XL Desktop App.app/Contents/Resources/docs/
All editions: https://github.com/MicheleDataBeat/volcastudio-xl-releases
"""


def archive_outie(app, root):
    """Zip (Windows/macOS) or tar.gz (Linux) the application with READ ME FIRST and LICENSE."""
    import hashlib
    import shutil
    import tarfile
    from tools.build_wmc import platform_tag
    if not app.exists():
        raise SystemExit('The build did not produce the expected application.')
    base = root / f'VolcaStudio-XL-Desktop-{__version__}-{platform_tag()}'
    how = {'win32': 'double-click "VolcaStudio XL Desktop App.exe"',
           'darwin': 'drag it to Applications, then open it'}.get(sys.platform, 'double-click it, or run it from a terminal')
    staging = root / 'archive-staging'
    shutil.rmtree(staging, ignore_errors=True)
    folder = staging / (NAME if sys.platform == 'darwin' else app.name)
    if sys.platform == 'darwin':
        folder.mkdir(parents=True)
        shutil.copytree(app, folder / app.name, symlinks=True)
    else:
        shutil.copytree(app, folder, symlinks=True)
    readme = README_FIRST.format(version=__version__, how=how)
    (folder / 'READ ME FIRST.txt').write_text(readme.replace('\n', '\r\n') if sys.platform == 'win32' else readme)
    shutil.copyfile(ROOT / 'LICENSE', folder / 'LICENSE.txt')
    if sys.platform == 'darwin':
        target = Path(str(base) + '.zip')
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(folder), str(target)], check=True)
    elif sys.platform == 'win32':
        target = Path(str(base) + '.zip')
        shutil.make_archive(str(base), 'zip', staging, folder.name)
    else:
        target = Path(str(base) + '.tar.gz')
        with tarfile.open(target, 'w:gz') as stream:
            stream.add(folder, arcname=folder.name)
    shutil.rmtree(staging)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    Path(str(target) + '.sha256').write_text(f'{digest}  {target.name}\n')
    return target, digest


if __name__ == '__main__':
    main()
