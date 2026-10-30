import json
import os
import random
import struct
import unittest
from volcastudio import lumon_build, updater_codec as codec

REAL_KORG = os.environ.get('VOLCASTUDIO_KORG_UPDATER')


def image(seed, data_pages=40):
    rng = random.Random(seed)
    result = bytearray(b'\xff' * codec.IMAGE_SIZE)
    for page in range(data_pages):
        result[page * 256:(page + 1) * 256] = bytes(rng.randrange(256) for _ in range(256))
    return bytes(result)


class CodecTests(unittest.TestCase):
    def test_synthetic_updater_round_trip(self):
        base = image(1)
        transfer = codec.decode(codec.synthetic_updater(base, (1, 42)))
        self.assertEqual(transfer.binary(), base)
        self.assertEqual(transfer.version, (1, 42))
        self.assertEqual(sum(len(p.payload) == 262 for p in transfer.packets[1:]), 40)

    def test_template_encoding_replaces_only_changed_packets(self):
        base = image(2)
        wav = codec.synthetic_updater(base)
        template = codec.decode(wav)
        target = bytearray(base)
        target[0x100] ^= 0xff
        out = codec.encode_from_template(template, bytes(target), (1, 60))
        self.assertEqual(len(out), len(wav))
        changed = codec.decode(out)
        self.assertEqual(changed.binary(), bytes(target))
        self.assertEqual(changed.version, (1, 60))
        frame = codec.SYMBOL_FRAMES * 4
        # Every page other than the changed page 1 keeps the template PCM exactly.
        for page, packet in enumerate(template.packets[1:]):
            start = 44 + (packet.start_cycle + 2) * frame
            end = start + packet.data_cycles * frame
            if page == 1:
                self.assertNotEqual(out[start:end], wav[start:end])
            else:
                self.assertEqual(out[start:end], wav[start:end])

    def test_fill_page_can_become_data(self):
        base = image(3)
        template = codec.decode(codec.synthetic_updater(base))
        target = bytearray(base)
        target[0x10000:0x10004] = b'LMX2'
        out = codec.encode_from_template(template, bytes(target), (1, 60))
        self.assertGreater(len(out), len(template.wav))
        self.assertEqual(codec.decode(out).binary(), bytes(target))
        riff = struct.unpack_from('<I', out, 4)[0], struct.unpack_from('<I', out, 40)[0]
        self.assertEqual(riff, (len(out) - 8, len(out) - 44))

    def test_damaged_audio_is_rejected(self):
        wav = bytearray(codec.synthetic_updater(image(4)))
        with self.assertRaises(codec.CodecError):
            codec.decode(bytes(wav[:len(wav) // 2]))
        with self.assertRaises(ValueError):
            codec.decode(b'RIFF' + bytes(100))


class PatchTests(unittest.TestCase):
    def test_reused_base_bytes_become_copies_never_literals(self):
        rng = random.Random(5)
        for trial in range(20):
            base = bytearray(image(trial, 64))
            target = bytearray(base)
            for _ in range(30):
                at = rng.randrange(0x8000, 0x1ff00)
                if rng.random() < .5:
                    source = rng.randrange(0, 0x3f00)
                    target[at:at + rng.randrange(8, 60)] = base[source:source + 60][:len(target[at:at + 60])]
                else:
                    target[at:at + rng.randrange(1, 40)] = bytes(rng.randrange(256) for _ in range(40))[:40]
            target = bytes(target[:codec.IMAGE_SIZE])
            operations = lumon_build.make_operations(bytes(base), target)
            self.assertEqual(lumon_build.apply_operations(bytes(base), operations), target)
            self.assertEqual(lumon_build.literal_overlaps(operations, bytes(base)), [])

    def test_patch_document_round_trip_and_build(self):
        korg_wav, patch = lumon_build.synthetic_case()
        self.assertTrue(any(op[0] == 'copy' for op in patch['operations']))
        self.assertEqual(json.loads(lumon_build.dump_patch(patch)), patch)
        wav = lumon_build.build(korg_wav, patch)
        self.assertEqual(lumon_build._sha(wav), patch['result']['wav_sha256'])

    def test_invalid_instructions_are_refused(self):
        base = image(6)
        for operation in (['copy', 0, codec.IMAGE_SIZE - 4, 8], ['lit', codec.IMAGE_SIZE - 1, 'abcd'], ['xor', 0, 'ff']):
            with self.assertRaises(ValueError):
                lumon_build.apply_operations(base, [operation])

    @unittest.skipUnless(REAL_KORG, 'Set VOLCASTUDIO_KORG_UPDATER to the official Korg 1.42 zip')
    def test_shipped_patch_literals_contain_no_korg_bytes(self):
        patch = lumon_build.load_patch()
        korg_wav = lumon_build.read_updater(REAL_KORG, patch)
        korg_image = codec.decode(korg_wav).binary()
        self.assertEqual(lumon_build.literal_overlaps(patch['operations'], korg_image), [])
        self.assertEqual(lumon_build._sha(lumon_build.build(korg_wav, patch)), patch['result']['wav_sha256'])


if __name__ == '__main__':
    unittest.main()
