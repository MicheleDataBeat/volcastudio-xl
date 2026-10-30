#!/usr/bin/env python3
"""Check current product names, with finite, counted compatibility exceptions.

Public names: "DataBeat OS" (firmware) and "VolcaStudio XL" (Studio). The
internal codename, the edition names and the two-word Studio spelling are
never public names. They may appear only as:

* an exact technical token listed in product-name-policy.json (module, path,
  storage/wire identifier, environment variable, test name);
* a counted line exception (history or frozen evidence), pinned by the hash of
  the complete line;
* a counted rename backlog per file, which may only shrink; --strict requires
  it to be empty;
* a file that is never exported (internal instructions, internal records).

Checks working files (including untracked), the Git index, or an exact commit.
Binary media need separate review.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

CANONICAL = 'DataBeat OS'
STUDIO = 'VolcaStudio XL'
# Built from parts so this file never spells a retired name in full.
CODENAME = 'lu' + 'mon'
EDITIONS = ('out' + 'ie', 'inn' + 'ie', 'w' + 'mc', 'whole ' + 'mind collective')
NAMES = re.compile('|'.join([CODENAME, *EDITIONS, r'Volca[ -]Studio']), re.I)
PATH_NAMES = re.compile('|'.join([CODENAME, *EDITIONS[:3]]), re.I)
STUDIO_TWO_WORDS = re.compile(r'Volca[ -]Studio')
FIRMWARE_NAME = re.compile(r'data[ _-]*beat[ _-]*os\b', re.I)
FIRMWARE_ALLOWED = ('DataBeat OS', 'dAtAbEAt OS', 'databeat-os', 'databeat_os')
TOKEN_CHAR = re.compile(r'[A-Za-z0-9_./:@-]')
ENCODED = 64  # longer runs without a dot are encoded data (base64), not names


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout


def _token(line, start, end):
    a, b = start, end
    while a and TOKEN_CHAR.fullmatch(line[a - 1]):
        a -= 1
    while b < len(line) and TOKEN_CHAR.fullmatch(line[b]):
        b += 1
    return line[a:b].rstrip('.,:'), a


def violations(line, technical):
    for match in NAMES.finditer(line):
        start = match.start()
        token, a = _token(line, *match.span())
        if len(token) >= ENCODED and '.' not in token:
            continue  # encoded data
        if start > a and line[start - 1].isalnum() and not (start >= 2 and line[start - 2:start] in ('\\n', '\\t', '\\r')):
            continue  # substring of an unrelated word or identifier
        if STUDIO_TWO_WORDS.match(line, start):
            yield start + 1, match.group(0)
            continue
        if token in technical:
            continue
        yield start + 1, token or match.group(0)
    for match in FIRMWARE_NAME.finditer(line):
        if match.group(0) not in FIRMWARE_ALLOWED:
            yield match.start() + 1, match.group(0)


def legacy_path(name):
    return any(m.start() == 0 or not name[m.start() - 1].isalnum() for m in PATH_NAMES.finditer(name))


def read_tree(root, mode, ref):
    if mode == 'worktree':
        names = git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').decode().split('\0')
        for name in sorted(set(filter(None, names))):
            path = root / name
            if path.is_symlink():
                yield name, path.readlink().as_posix().encode()
            elif path.is_file():
                yield name, path.read_bytes()
    else:
        revision = ref if mode == 'ref' else None
        if revision:
            names = git(root, 'ls-tree', '-r', '--name-only', '-z', revision).decode().split('\0')
        else:
            names = git(root, 'ls-files', '-z').decode().split('\0')
        for name in sorted(set(filter(None, names))):
            yield name, git(root, 'show', f'{revision or ""}:{name}')


def load_policy(raw):
    if raw is None:
        raise ValueError('Missing product-name-policy.json')
    policy = json.loads(raw)
    if policy.get('schema') != 2 or policy.get('canonical') != CANONICAL or policy.get('studio') != STUDIO:
        raise ValueError('Invalid product naming policy')
    technical = set(policy.get('technical_tokens', []))
    bare = {CODENAME, CODENAME + 'os', CODENAME + ' os', *EDITIONS, 'volca' + ' studio', 'volca' + '-studio'}
    if any(token.lower() in bare for token in technical):
        raise ValueError('A bare product or edition name cannot be a technical exception')
    backlog = policy.get('rename_backlog', {})
    if any(type(count) is not int or count < 1 for count in backlog.values()):
        raise ValueError('Rename backlog counts must be positive integers')
    return policy, technical


def check(root, mode='worktree', ref=None, strict=False):
    entries = dict(read_tree(root, mode, ref))
    policy, technical = load_policy(entries.get('product-name-policy.json'))
    exceptions = policy.get('line_exceptions', {})
    backlog = policy.get('rename_backlog', {})
    unexported = set(policy.get('not_exported', []))
    findings, pending, exempt = [], {}, Counter()
    text_count = binary_count = 0
    for name, data in entries.items():
        if name == 'product-name-policy.json':
            continue
        if legacy_path(name) and name not in policy.get('legacy_paths', []):
            findings.append(f'{name}: retired product or edition name in a new path')
        if b'\0' in data:
            binary_count += 1
            continue
        try:
            content = data.decode('utf-8')
        except UnicodeError:
            binary_count += 1
            continue
        text_count += 1
        used = Counter()
        lines = []
        for number, line in enumerate(content.splitlines(), 1):
            bad = list(violations(line, technical))
            if not bad:
                continue
            key = digest(line)
            allowance = exceptions.get(name, {}).get(key)
            used[key] += 1
            if allowance and allowance.get('reason') and used[key] <= allowance['count']:
                continue
            lines.append((number, bad))
        if not lines:
            continue
        if name in unexported:
            exempt[name] = len(lines)
            continue
        allowed = backlog.get(name, 0)
        if len(lines) <= allowed and not strict:
            pending[name] = len(lines)
            continue
        if allowed:
            findings.append(f'{name}: {len(lines)} lines with retired names; the rename backlog allows {0 if strict else allowed}')
        for number, bad in lines[:20]:
            for col, token in bad:
                findings.append(f'{name}:{number}:{col}: {token!r}; use {CANONICAL} / {STUDIO}')
    stale = {name: count for name, count in backlog.items() if pending.get(name, 0) < count}
    if text_count == 0:
        raise ValueError('No text files checked')
    return {'status': 'FAIL' if findings else 'PASS', 'mode': mode, 'ref': ref, 'strict': strict,
            'text_files': text_count, 'binary_files_requiring_separate_review': binary_count,
            'rename_backlog_lines': sum(pending.values()), 'rename_backlog_files': len(pending),
            'stale_backlog_allowances': stale,
            'not_exported_lines': sum(exempt.values()),
            'findings': findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--strict', action='store_true', help='Fail while any rename backlog remains')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--index', action='store_true')
    choice.add_argument('--ref')
    args = parser.parse_args(argv)
    try:
        result = check(args.root.resolve(), 'index' if args.index else 'ref' if args.ref else 'worktree',
                       args.ref, args.strict)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Product naming check cannot run: {error}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
