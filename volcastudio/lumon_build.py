"""Build DataBeat OS on the user's computer from the user's own Korg updater.

Studio ships no Korg firmware. Its DataBeat OS patch holds only bytes that DataBeat OS
adds or changes; where DataBeat OS reuses Korg bytes elsewhere in the image, the patch
records a copy from the user's own Korg image instead of the bytes themselves.
Studio checks the result: every stage is checked against pinned SHA-256 values
(the Korg updater, its decoded image, the patched image and the final updater).
"""
import contextlib
import hashlib
import json
import random
import zipfile
from io import BytesIO
from pathlib import Path

from . import updater_codec as codec

KORG_DOWNLOAD_PAGE = 'https://www.korg.com/us/support/download/software/0/370/1475/'
# The only firmware patch Studio ships: DataBeat OS 1.0 (tools/make_lumon_patch.py).
PATCH_FILE = Path(__file__).with_name('data') / 'firmware' / 'databeat-os-1.0.patch.json'
# Pinned so a changed or damaged patch is never used under the release's name.
PATCH_SHA256 = 'c1830ac872540859f97ead12e21ecc3dca25b8c405c93c718c2a79092de84149'
PATCH_KIND = 'databeat-os-patch'
MIN_COPY = 8
MAX_UPDATER_BYTES = 64 * 1024 * 1024

_override = None


class BuildError(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def override(patch):
    """Use another patch (offline self-checks and tests only)."""
    global _override
    previous, _override = _override, patch
    try:
        yield patch
    finally:
        _override = previous


def load_patch():
    if _override is not None:
        return _override
    raw = PATCH_FILE.read_bytes()
    if _sha(raw) != PATCH_SHA256:
        raise BuildError('The DataBeat OS patch shipped with Studio is damaged; reinstall VolcaStudio XL')
    return json.loads(raw)


def make_operations(base, target, min_copy=MIN_COPY):
    """Describe `target` as changes to `base`.

    Only differing bytes are recorded. Inside them, any span of at least
    `min_copy` bytes that also occurs in `base` becomes a copy from the user's
    image, so literal data never contains such a span of Korg bytes.
    """
    if len(base) != len(target):
        raise BuildError('Images differ in size')
    index = {}
    for offset in range(len(base) - min_copy + 1):
        index.setdefault(base[offset:offset + min_copy], []).append(offset)
    operations = []
    literal, literal_at = bytearray(), None

    def flush():
        nonlocal literal, literal_at
        if literal:
            operations.append(['lit', literal_at, literal.hex()])
        literal, literal_at = bytearray(), None

    position = 0
    while position < len(target):
        if base[position] == target[position]:
            flush()
            position += 1
            continue
        end = position
        while end < len(target) and base[end] != target[end]:
            end += 1
        cursor = position
        while cursor < end:
            best = (0, 0)
            # Every candidate matches min_copy bytes, so a cap only affects copy length.
            candidates = index.get(target[cursor:cursor + min_copy], ()) if end - cursor >= min_copy else ()
            for source in candidates[:256]:
                length = min_copy
                while cursor + length < end and source + length < len(base) and base[source + length] == target[cursor + length]:
                    length += 1
                if length > best[1]:
                    best = (source, length)
            if best[1]:
                flush()
                operations.append(['copy', cursor, best[0], best[1]])
                cursor += best[1]
            else:
                if literal_at is None:
                    literal_at = cursor
                literal.append(target[cursor])
                cursor += 1
        flush()
        position = end
    return operations


def apply_operations(base, operations):
    image = bytearray(base)
    for operation in operations:
        kind, offset = operation[0], operation[1]
        if kind == 'lit':
            data = bytes.fromhex(operation[2])
        elif kind == 'copy':
            source, length = operation[2], operation[3]
            if source < 0 or length <= 0 or source + length > len(base):
                raise BuildError('Invalid copy instruction in the firmware patch')
            data = base[source:source + length]
        else:
            raise BuildError('Unknown instruction in the firmware patch')
        if offset < 0 or offset + len(data) > len(image):
            raise BuildError('Firmware patch instruction outside the image')
        image[offset:offset + len(data)] = data
    return bytes(image)


def literal_overlaps(operations, base, length=MIN_COPY):
    """Offsets of literal patch data containing `length` contiguous bytes of `base`."""
    grams = {base[i:i + length] for i in range(len(base) - length + 1)}
    found = []
    for operation in operations:
        if operation[0] != 'lit':
            continue
        data = bytes.fromhex(operation[2])
        found += [operation[1] + i for i in range(len(data) - length + 1) if data[i:i + length] in grams]
    return found


def read_updater(source, patch=None):
    """Return the exact Korg updater WAV from the downloaded zip or the WAV itself."""
    patch = patch or load_patch()
    base = patch['base']
    source = Path(source).expanduser()
    if not source.is_file():
        raise BuildError(f'{source} is not a file')
    if source.stat().st_size > MAX_UPDATER_BYTES:
        raise BuildError('This file is too large to be the Korg volca sample updater')
    raw = source.read_bytes()
    if raw[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                members = [m for m in archive.infolist()
                           if Path(m.filename).name.lower() == base['updater_wav'].lower()]
                if len(members) != 1 or members[0].file_size > MAX_UPDATER_BYTES:
                    raise BuildError(f'The zip does not contain {base["updater_wav"]}; download '
                                     f'{base["updater_zip"]} from Korg')
                raw = archive.read(members[0])
        except zipfile.BadZipFile as exc:
            raise BuildError('The zip file is damaged; download it again from Korg') from exc
    elif raw[:4] != b'RIFF':
        raise BuildError(f'Choose {base["updater_zip"]} or the {base["updater_wav"]} it contains')
    if _sha(raw) != base['wav_sha256']:
        raise BuildError(f'This is not the official Korg volca sample {base["version"]} updater '
                         f'({base["updater_wav"]}). Download {base["updater_zip"]} from Korg and '
                         'choose it unchanged.')
    return raw


def build(korg_wav, patch=None):
    """Return the DataBeat OS updater WAV built from the exact Korg updater."""
    patch = patch or load_patch()
    base, result = patch['base'], patch['result']
    if _sha(korg_wav) != base['wav_sha256']:
        raise BuildError('Unexpected Korg updater')
    template = codec.decode(korg_wav)
    image = template.binary()
    if _sha(image) != base['image_sha256']:
        raise BuildError('The Korg updater decodes to an unexpected image')
    built_image = apply_operations(image, patch['operations'])
    if _sha(built_image) != result['image_sha256']:
        raise BuildError('The patched image differs from DataBeat OS; nothing was saved')
    wav = codec.encode_from_template(template, built_image, result['header_version'])
    if _sha(wav) != result['wav_sha256'] or len(wav) != result['wav_bytes']:
        raise BuildError('The built updater did not pass Studio\'s check; nothing was saved')
    return wav


def make_patch(korg_wav, release_image, *, release, base, header_version):
    """Create a patch document from the Korg updater and the release image."""
    template = codec.decode(korg_wav)
    image = template.binary()
    operations = make_operations(image, release_image)
    if apply_operations(image, operations) != release_image:
        raise BuildError('Patch does not reproduce the release image')
    if literal_overlaps(operations, image):
        raise BuildError('Literal patch data would contain Korg bytes')
    wav = codec.encode_from_template(template, release_image, header_version)
    return {
        'schema': 1, 'kind': PATCH_KIND, 'release': dict(release),
        'base': dict(base, wav_sha256=_sha(korg_wav), image_sha256=_sha(image)),
        'result': {'image_sha256': _sha(release_image), 'wav_sha256': _sha(wav), 'wav_bytes': len(wav),
                   'header_version': list(header_version)},
        'min_copy': MIN_COPY,
        'operations': operations,
    }


def dump_patch(patch):
    """Canonical bytes of a patch document (one instruction per line)."""
    head = {k: v for k, v in patch.items() if k != 'operations'}
    lines = [json.dumps(op, separators=(',', ':')) for op in patch['operations']]
    text = json.dumps(head, indent=1)[:-2] + ',\n "operations": [\n  ' + ',\n  '.join(lines) + '\n ]\n}\n'
    if json.loads(text) != json.loads(json.dumps(patch)):
        raise BuildError('Patch serialization changed its content')
    return text.encode()


def synthetic_case(seed=7):
    """A self-contained base updater and patch with no real firmware, for self-checks."""
    rng = random.Random(seed)
    base = bytearray(b'\xff' * codec.IMAGE_SIZE)
    for page in range(0, 160):
        base[page * 256:(page + 1) * 256] = bytes(rng.randrange(256) for _ in range(256))
    target = bytearray(base)
    for offset in range(0x400, 0x8000, 0x777):
        target[offset:offset + 40] = bytes(rng.randrange(256) for _ in range(40))
    target[0x9000:0x9030] = base[0x100:0x130]       # reused base bytes: must become a copy
    target[0x3fc:0x3fe] = bytes((1, 60))
    korg_wav = codec.synthetic_updater(bytes(base), (1, 42))
    patch = make_patch(korg_wav, bytes(target), header_version=(1, 60),
                       release={'name': 'Synthetic OS', 'version': '0.0-selfcheck', 'status': 'SELF_CHECK',
                                'experimental': False, 'hardware_tested': False},
                       base={'name': 'Synthetic base', 'version': '0.0', 'updater_zip': 'synthetic.zip',
                             'updater_wav': 'synthetic.wav', 'download_page': 'offline self-check'})
    return korg_wav, patch
