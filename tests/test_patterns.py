import json
import random
import tempfile
import unittest
from pathlib import Path

from volcastudio.patterns import (Pattern, PATTERN_SIZE, SYSEX_HEADER, blank_pattern,
    pack7, unpack7, parse_sysex, encode_sysex, bank_to_json, bank_from_json,
    load_bank, save_bank, request_current_dump, request_stored_dump)


class PatternTests(unittest.TestCase):
    def test_complete_raw_data_survives_bank_and_midi(self):
        rng = random.Random(91)
        data = bytearray(blank_pattern('lumon-xl', 8).data)
        data[0x20:0xa20] = rng.randbytes(0xa00)
        # Full microtiming/slicing/echo metadata, including currently unused bytes.
        data[0xa24:0xa3c] = rng.randbytes(24)
        pattern = Pattern(8, bytes(data))
        self.assertEqual(bank_from_json(bank_to_json([pattern])), [pattern])
        stored = SYSEX_HEADER + bytes([0x4c, 8]) + pack7(pattern.data) + b'\xf7'
        self.assertEqual(parse_sysex(stored), [pattern])
        current = parse_sysex(encode_sysex(pattern))[0]
        self.assertEqual(current.data, pattern.data)
        self.assertIsNone(current.slot)
        self.assertEqual(encode_sysex(pattern)[6], 0x40)
        self.assertEqual(len(stored), 3008)
        self.assertEqual(len(encode_sysex(pattern)), 3007)

    def test_7bit_high_bits_all_values_and_realtime(self):
        raw = bytes(range(256)) * 11
        self.assertEqual(unpack7(pack7(raw), len(raw)), raw)
        p = blank_pattern('lumon-xl')
        message = encode_sysex(p)
        interleaved = b'\xf8'.join(message[i:i+19] for i in range(0, len(message), 19))
        self.assertEqual(parse_sysex(interleaved), [p])
        with self.assertRaises(ValueError):
            unpack7(b'\x7f\x00')
        with self.assertRaises(ValueError):
            parse_sysex(message[:-1])
        with self.assertRaises(ValueError):
            parse_sysex(message[:2] + b'\x31' + message[3:])

    def test_reset_defaults_are_neutral_for_every_part(self):
        for profile in ('lumon-xl',):
            p = blank_pattern(profile)
            self.assertEqual(p.firmware, profile)
            self.assertEqual(len(p.data), PATTERN_SIZE)
            self.assertEqual(p.data[10] & 1, 0, 'Drone must be off')
            for part in range(10):
                q = p.data[part*256:part*256+256]
                self.assertEqual(q[0x35], 0, 'Predictability ALL')
                self.assertEqual(q[0x36:0x40], bytes(10))
                self.assertEqual(q[0x34], 0)
                self.assertEqual(q[0x40:], bytes(192), 'All notes and motion must be empty')
                self.assertEqual(q[0x26:0x28], bytes(2))
                self.assertEqual(q[0x28], 127)
            self.assertEqual(p.data[0xa24:0xa3c], bytes(24))

    def test_bank_corruption_and_duplicates_fail(self):
        p = blank_pattern('lumon-xl', 0)
        value = json.loads(bank_to_json([p]))
        value['patterns'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            bank_from_json(json.dumps(value))
        value = json.loads(bank_to_json([p]))
        value['patterns'][0]['firmware'] = 'unsupported'
        with self.assertRaises(ValueError):
            bank_from_json(json.dumps(value))
        with self.assertRaises(ValueError):
            bank_to_json([p, p])
        with self.assertRaises(ValueError):
            Pattern(True, p.data)
        with self.assertRaises(ValueError):
            Pattern(10, p.data)
        with self.assertRaises(ValueError):
            Pattern(0, p.data[:-1])
        with self.assertRaises(ValueError):
            Pattern(None, bytes(PATTERN_SIZE))

    def test_uninitialized_memory_is_archived_without_normalizing(self):
        p = Pattern(3, bytes([255]) * PATTERN_SIZE)
        self.assertEqual(p.firmware, 'opaque')
        self.assertFalse(p.initialized)
        self.assertEqual(bank_from_json(bank_to_json([p])), [p])
        stored = SYSEX_HEADER + bytes([0x4c, 3]) + pack7(p.data) + b'\xf7'
        self.assertEqual(parse_sysex(stored), [p])

    def test_publication_is_atomic_exclusive_and_formats_import(self):
        patterns = [blank_pattern('lumon-xl', n) for n in range(10)] + [blank_pattern('lumon-xl')]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'bank.vspatterns'
            save_bank(path, patterns)
            original = path.read_bytes()
            self.assertEqual(load_bank(path), patterns)
            with self.assertRaises(FileExistsError):
                save_bank(path, [blank_pattern()])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(td).glob('.pattern-bank-*')), [])
            raw = Path(td) / 'pattern.bin'
            raw.write_bytes(patterns[0].data)
            self.assertEqual(load_bank(raw), [Pattern(None, patterns[0].data)])
            syx = Path(td) / 'pattern.syx'
            syx.write_bytes(encode_sysex(patterns[0]))
            self.assertEqual(load_bank(syx), load_bank(raw))

    def test_dump_requests_match_native_parser(self):
        self.assertEqual(request_current_dump(), bytes.fromhex('f0 42 30 00 01 2d 10 f7'))
        self.assertEqual(request_stored_dump(9), bytes.fromhex('f0 42 30 00 01 2d 1c 09 f7'))


if __name__ == '__main__':
    unittest.main()
