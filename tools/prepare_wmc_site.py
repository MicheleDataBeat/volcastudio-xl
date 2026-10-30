#!/usr/bin/env python3
"""Assemble the VolcaStudio XL download page into a NEW folder.

    python tools/prepare_wmc_site.py --packages DIR_WITH_ARCHIVES --output NEW_DIR \
        [--download-base https://github.com/OWNER/REPO/releases/download/vX.Y.Z]
    python tools/prepare_wmc_site.py --unreleased --output NEW_DIR

Browser App and Desktop App archives of the current version are listed with their
SHA-256. With --download-base the page links to the release assets instead
of copying the archives into the folder (static hosts limit file sizes).
With --unreleased the page lists no packages: use it before the version's
release exists, so the page never links to missing files.
The folder can be checked locally through any static web server. This script
publishes nothing: publishing is a separate, explicit step.
"""
import argparse
import subprocess
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from volcastudio import __version__  # noqa: E402
from volcastudio.wmc import WMC_VERSION  # noqa: E402

SYSTEMS = (('windows', 'windows-'), ('macos', 'macos-'), ('linux', 'linux-'))
EDITIONS = (('browser', f'VolcaStudio-XL-Browser-{WMC_VERSION}-'), ('desktop', f'VolcaStudio-XL-Desktop-{__version__}-'))
RELEASES = 'https://github.com/MicheleDataBeat/volcastudio-xl-releases'
PAGES = {'browser-quick-start.md': 'browser-quick-start.html',
         'browser-quick-start.it.md': 'browser-quick-start.it.html',
         'browser.md': 'browser.html', 'desktop.md': 'desktop.html', 'tuning.md': 'tuning.html',
         'firmware.md': 'firmware.html', 'return-to-korg.md': 'return-to-korg.html',
         'databeat-os-manual.md': 'databeat-os.html',
         'patterns.md': 'patterns.html', 'pattern-audio.md': 'pattern-audio.html',
         'grooves.md': 'grooves.html'}


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<![\w*])\*([^*]+)\*(?![\w*])', r'<em>\1</em>', text)
    def link(match):
        target = match.group(2)
        page, _, anchor = target.partition('#')
        if page in PAGES:
            target = PAGES[page] + (f'#{anchor}' if anchor else '')
        elif not re.match(r'https?://|#', target):
            return match.group(1)  # documents that are not on the site stay plain text
        return f'<a href="{html.escape(target)}">{match.group(1)}</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)', link, text)


def markdown(text):
    """A deliberately small converter for the quick-start pages."""
    out, paragraph, listing = [], [], None
    heading_ids = {}
    last_item = None
    def flush():
        nonlocal listing
        if paragraph:
            out.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()
        if listing:
            out.append(f'</{listing}>')
            listing = None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if stripped.startswith('```'):
            flush()
            code = []
            while index < len(lines) and not lines[index].strip().startswith('```'):
                code.append(lines[index])
                index += 1
            index += 1
            out.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
            continue
        if stripped.startswith('|') and index < len(lines) and re.fullmatch(r'\|[\s:|-]+\|', lines[index].strip()):
            flush()
            cells = lambda row: [c.strip() for c in row.strip().strip('|').split('|')]
            rows = ['<tr>' + ''.join(f'<th>{inline(c)}</th>' for c in cells(stripped)) + '</tr>']
            index += 1
            while index < len(lines) and lines[index].strip().startswith('|'):
                rows.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in cells(lines[index])) + '</tr>')
                index += 1
            out.append('<div style="overflow-x: auto;" tabindex="0"><table>' + ''.join(rows) + '</table></div>')
            continue
        heading = re.match(r'(#{1,3}) (.*)', stripped)
        item = re.match(r'(?:[-*]|\d+\.) (.*)', stripped)
        if not stripped:
            flush()
        elif heading:
            flush()
            level = len(heading.group(1))
            anchor = re.sub(r'[^\w\s-]', '', heading.group(2).lower()).replace(' ', '-')
            occurrence = heading_ids.get(anchor, 0)
            heading_ids[anchor] = occurrence + 1
            if occurrence:
                anchor += f'-{occurrence}'
            out.append(f'<h{level} id="{anchor}">{inline(heading.group(2))}</h{level}>')
        elif item:
            if paragraph:
                out.append('<p>' + inline(' '.join(paragraph)) + '</p>')
                paragraph.clear()
            kind = 'ol' if stripped[0].isdigit() else 'ul'
            if listing != kind:
                if listing:
                    out.append(f'</{listing}>')
                out.append(f'<{kind}>')
                listing = kind
            last_item = item.group(1)
            out.append('<li>' + inline(last_item) + '</li>')
        elif listing and line.startswith(('  ', '\t')):
            last_item += ' ' + stripped
            out[-1] = '<li>' + inline(last_item) + '</li>'
        else:
            paragraph.append(stripped)
    flush()
    return '\n'.join(out)


def page(title, body, lang):
    return (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)} — DataBeat</title><link rel="stylesheet" href="../site.css"></head>'
            '<body><main class="doc"><header class="top"><a class="brand" '
            'href="https://micheledatabeat.github.io/"><img src="../assets/databeat-mark.svg" '
            'alt="DataBeat" width="32" height="32"><span>DataBeat · VolcaStudio XL</span></a></header>'
            f'{body}<p><a href="../index.html">← VolcaStudio XL</a></p>'
            '<footer>© 2026 Michele Ibba · <a href="https://micheledatabeat.github.io/">DataBeat</a>'
            '</footer></main></body></html>\n')


def main(argv=None):
    subprocess.run([sys.executable, str(ROOT / 'tools/check_product_name.py'), '--root', str(ROOT)], check=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--packages', type=Path)
    source.add_argument('--unreleased', action='store_true', help='List no packages (release not published yet)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download-base', help='Link packages to this URL instead of copying them')
    parser.add_argument('--release-url', default=RELEASES, help='Page with all versions and release notes')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('--output must be a new folder')
    if args.download_base and not args.download_base.startswith('https://'):
        parser.error('--download-base must be an https:// URL')
    found = []
    for edition, prefix in EDITIONS if args.packages else ():
        for archive in sorted(args.packages.glob(prefix + '*')):
            if not archive.name.endswith(('.zip', '.tar.gz')):
                continue
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            sidecar = Path(str(archive) + '.sha256')
            if sidecar.is_file() and sidecar.read_text().split()[0] != digest:
                parser.error(f'Checksum mismatch: {archive.name}')
            tag = archive.name[len(prefix):]
            system = next((name for name, start in SYSTEMS if tag.startswith(start)), None)
            if system:
                found.append((edition, system, archive, digest))
    if args.unreleased and args.download_base:
        parser.error('--download-base needs --packages')
    if args.packages and not any(edition == 'browser' for edition, *_ in found):
        parser.error('No Browser App archives for this version were found')
    args.output.mkdir(parents=True)
    for name in ('index.html', 'site.css', 'site.js', 'browser-app-icon.svg'):
        shutil.copy2(ROOT / 'site' / name, args.output / name)
    shutil.copytree(ROOT / 'site' / 'assets', args.output / 'assets')
    (args.output / 'docs').mkdir()
    packages = []
    for edition, system, archive, digest in found:
        if args.download_base:
            link = args.download_base.rstrip('/') + '/' + archive.name
        else:
            (args.output / 'downloads').mkdir(exist_ok=True)
            shutil.copy2(archive, args.output / 'downloads' / archive.name)
            (args.output / 'downloads' / (archive.name + '.sha256')).write_text(f'{digest}  {archive.name}\n')
            link = f'downloads/{archive.name}'
        packages.append({'edition': edition, 'system': system, 'file': link, 'sha256': digest,
                         'bytes': archive.stat().st_size})
    (args.output / 'downloads.json').write_text(json.dumps({'version': __version__, 'release_url': args.release_url,
                                                            'packages': packages}, indent=2) + '\n')
    for source, target, lang, title in (('browser-quick-start.md', 'browser-quick-start.html', 'en', 'Browser App quick start'),
                                        ('browser-quick-start.it.md', 'browser-quick-start.it.html', 'it', 'Browser App: guida rapida'),
                                        ('browser.md', 'browser.html', 'en', 'VolcaStudio XL Browser App guide'),
                                        ('desktop.md', 'desktop.html', 'en', 'VolcaStudio XL Desktop App guide'),
                                        ('tuning.md', 'tuning.html', 'en', 'Varispeed and key alignment'),
                                        ('firmware.md', 'firmware.html', 'en', 'Firmware: DataBeat OS and the Korg updater'),
                                        ('return-to-korg.md', 'return-to-korg.html', 'en', 'Return to Korg firmware'),
                                        ('patterns.md', 'patterns.html', 'en', 'Pattern banks'),
                                        ('pattern-audio.md', 'pattern-audio.html', 'en', 'Pattern audio backup'),
                                        ('grooves.md', 'grooves.html', 'en', 'Groove templates'),
                                        ('databeat-os-manual.md', 'databeat-os.html', 'en', 'DataBeat OS 1.0 manual')):
        text = (ROOT / 'docs' / source).read_text(encoding='utf-8')
        (args.output / 'docs' / target).write_text(page(title, markdown(text), lang), encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'packages': packages}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
