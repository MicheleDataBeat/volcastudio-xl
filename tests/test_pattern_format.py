"""LMX2 preservation and rejection checks, using independent raw decoding."""
import struct
import json
import unittest
from unittest.mock import patch

from volcastudio.grooves import apply_pattern, microtiming, plan_grooves
from volcastudio.pattern_audio import AudioPatternDecoder
from volcastudio.pattern_format import (convert_native, motion_value, predictability,
    set_motion_value, set_predictability, set_microtiming, validate_lmx2,
    PREDICTABILITY_MASKS, PREDICTABILITY_LABELS)
from volcastudio.patterns import Pattern, blank_pattern, bank_to_json, bank_from_json
from volcastudio.pattern_transfer import pattern_targets, prepare_patterns
from test_grooves import populated
from test_pattern_audio import frame_bytes


def decoded(raw, part, step):
    base = part * 256
    code = int.from_bytes(bytes((raw[base + 0xa0 + step], raw[base + 0xb0 + step], raw[base + 0x110 + step] & 63)), 'little')
    a = code % 129
    b = code // 129 % 129
    c = code // 16641
    return tuple(index + 127 if index else 0 for index in (a, b, c))


class PatternFormatTests(unittest.TestCase):
    def test_defaults_and_per_step_eight_bar_meaning(self):
        pattern = blank_pattern()
        self.assertEqual(pattern.data[0xa20:0xa24], b'LMX2')
        for part in range(1, 11):
            self.assertEqual(predictability(pattern, part), (0,) * 16)
            self.assertEqual(pattern.data[(part - 1) * 256 + 0x3b], 0)
        self.assertEqual(PREDICTABILITY_MASKS, (255, 1, 128, 17, 136, 85, 170, 119, 238, 81, 21, 69, 87, 174, 234, 168))
        for mask, label in zip(PREDICTABILITY_MASKS[1:], PREDICTABILITY_LABELS[1:]):
            self.assertEqual(''.join('X' if mask & (1 << bar) else '0' for bar in range(8)), label)
        self.assertEqual([bool(PREDICTABILITY_MASKS[1] & (1 << (bar & 7))) for bar in range(16)], [True] + [False] * 7 + [True] + [False] * 7)

    def test_all_160_modes_preserve_every_motion_triplet(self):
        source = populated()
        before = [[decoded(source.data, part, step) for step in range(16)] for part in range(10)]
        for mode in range(16):
            result = source
            for part in range(1, 11):
                values = tuple((mode + part + step) % 16 for step in range(16))
                result = set_predictability(result, part, values)
                self.assertEqual(predictability(result, part), values)
            validate_lmx2(result)
            for part in range(10):
                self.assertEqual([decoded(result.data, part, step) for step in range(16)], before[part])
            allowed = {part * 256 + offset for part in range(10) for offset in (0x35, 0x36, 0x37, 0x39)}
            allowed |= {part * 256 + 0x110 + step for part in range(10) for step in range(16)}
            self.assertTrue(all(a == b or index in allowed for index, (a, b) in enumerate(zip(source.data, result.data))))
            self.assertEqual(bank_from_json(bank_to_json([result])), [result])

    def test_all_raw_motion_values_and_all_modes_preserve_neighbors(self):
        source = populated()
        for mode in range(16):
            source = set_predictability(source, 10, (mode,) * 16)
            for param_index, param in enumerate((3, 4, 10)):
                for value in (0, *range(128, 256)):
                    result = set_motion_value(source, 10, 16, param, value)
                    expected = list(decoded(source.data, 9, 15)); expected[param_index] = value
                    self.assertEqual(decoded(result.data, 9, 15), tuple(expected))
                    for index, other in enumerate((3, 4, 10)):
                        self.assertEqual(motion_value(result, 10, 16, other), expected[index])
                    self.assertEqual(predictability(result, 10), (mode,) * 16)
                    allowed = {0x900 + 0xa0 + 15, 0x900 + 0xb0 + 15, 0x900 + 0x110 + 15}
                    self.assertTrue(all(a == b or index in allowed for index, (a, b) in enumerate(zip(source.data, result.data))))

    def test_grooves_preserve_all_packed_data_bar_filters_and_extensions(self):
        source = populated()
        plan = plan_grooves([source], {1: 'SEXTUPLE_SWING_4_2', 10: 'DILLA_KICK_1_B01'}, [0])
        output = plan.selected_patterns[0]
        for part in range(1, 11):
            self.assertEqual(predictability(output, part), predictability(source, part))
            for step in range(1, 17):
                for param in range(11):
                    self.assertEqual(motion_value(output, part, step, param), motion_value(source, part, step, param))
            self.assertEqual(output.data[(part - 1) * 256 + 0x3b], source.data[(part - 1) * 256 + 0x3b])
        self.assertEqual(microtiming(output, 1), (0, 11) * 8)
        reset = plan_grooves(None, {1: 'SEXTUPLE_SWING_4_2'}, reset=True)
        self.assertFalse(reset.original_backup_available)
        for pattern in reset.selected_patterns:
            for part in range(1, 11):
                self.assertEqual(predictability(pattern, part), (0,) * 16)
                self.assertEqual(pattern.data[(part - 1) * 256 + 0x3b], 0)

    def test_native_low_speed_and_eg_slice_tags_preserve_paired_rows(self):
        source = populated()
        raw = bytearray(source.data)
        struct.pack_into('<H', raw, 0xa24, 0x8001)  # musical EG and part-one slicing
        for index in (0x84, 0xd4, 0xf4):
            raw[index] = 0
        source = Pattern(source.slot, bytes(raw))
        for param, value, offset in ((2, 37, 0x80), (6, 2, 0xd0), (8, 16, 0xf0)):
            result = set_motion_value(source, 1, 5, param, value)
            self.assertEqual(motion_value(result, 1, 5, param), value)
            self.assertEqual(result.data[0xa24:0xa26], source.data[0xa24:0xa26])
            changes = {index for index, (before, after) in enumerate(zip(source.data, result.data)) if before != after}
            self.assertEqual(changes, {offset + 4})
            for part in range(1, 11):
                self.assertEqual(predictability(result, part), predictability(source, part))
                for step in range(1, 17):
                    for packed_param in (3, 4, 10):
                        self.assertEqual(motion_value(result, part, step, packed_param), motion_value(source, part, step, packed_param))
            self.assertEqual(result.data[0x90:0xa0], source.data[0x90:0xa0], 'SPEED secondary row')

    def test_historical_bank_metadata_is_archived_only_for_its_exact_marker(self):
        source = populated()
        for marker, label in ((b'LUM1', 'lumon'), (b'LMX1', 'lumon-xl')):
            raw = bytearray(source.data); raw[0xa20:0xa24] = marker
            legacy = Pattern(0, bytes(raw))
            document = json.loads(bank_to_json([legacy]))
            document['patterns'][0]['firmware'] = label
            loaded = bank_from_json(json.dumps(document))
            self.assertEqual(loaded, [legacy])
            self.assertEqual(loaded[0].data, bytes(raw))
            self.assertEqual(bank_from_json(bank_to_json(loaded)), [legacy])
            with self.assertRaises(ValueError): pattern_targets(loaded, 'lumon-xl')
            with self.assertRaises(ValueError): apply_pattern(loaded[0], {1: 'STRAIGHT'})
            document['patterns'][0]['firmware'] = 'lumon-xl' if label == 'lumon' else 'lumon'
            with self.assertRaisesRegex(ValueError, 'checksum/profile'): bank_from_json(json.dumps(document))
        raw = bytearray(source.data); raw[0xa20:0xa24] = b'LMX9'
        unknown = Pattern(0, bytes(raw))
        document = json.loads(bank_to_json([unknown])); document['patterns'][0]['firmware'] = 'lumon-xl'
        with self.assertRaisesRegex(ValueError, 'checksum/profile'): bank_from_json(json.dumps(document))

    def test_bad_packed_motion_refused_before_encoder(self):
        source = blank_pattern(slot=0)
        for part in range(10):
            for step in (0, 15):
                raw = bytearray(source.data)
                base = part * 256
                raw[base + 0xa0 + step] = 255
                raw[base + 0xb0 + step] = 255
                raw[base + 0x110 + step] = 63
                corrupt = Pattern(0, bytes(raw))
                with patch('volcastudio.pattern_transfer.converter') as encoder:
                    with self.assertRaises(ValueError): prepare_patterns([corrupt], '/unused', '/unused', 'lumon-xl')
                encoder.assert_not_called()
                with self.assertRaises(ValueError): apply_pattern(corrupt, {1: 'STRAIGHT'})
                self.assertEqual(corrupt.data, bytes(raw))

    def test_native_conversion_is_lossless_and_noncanonical_input_is_untouched(self):
        source = populated(firmware='native')
        result = convert_native(source)
        self.assertEqual(pattern_targets([source], 'lumon-xl'), [(0, result)])
        for part in range(1, 11):
            for step in range(1, 17):
                for param, offset in ((3, 0xa0), (4, 0xb0), (10, 0x110)):
                    self.assertEqual(motion_value(result, part, step, param), source.data[(part - 1) * 256 + offset + step - 1])
        for value in (1, 127):
            raw = bytearray(source.data); raw[0xb0] = value
            invalid = Pattern(0, bytes(raw))
            with self.assertRaisesRegex(ValueError, 'Noncanonical'): convert_native(invalid)
            self.assertEqual(invalid.data, bytes(raw))
        for marker in (b'LMX1', b'LUM1', b'LMX9'):
            raw = bytearray(source.data); raw[0xa20:0xa24] = marker
            legacy = Pattern(0, bytes(raw))
            self.assertEqual(bank_from_json(bank_to_json([legacy])), [legacy])
            with self.assertRaisesRegex(ValueError, 'Legacy'): convert_native(legacy)

    def test_audio_protocol_preserves_full_lmx2_bank_and_edit_buffer(self):
        decoder = AudioPatternDecoder()
        expected = [populated(slot) for slot in range(10)] + [populated(None)]
        for index, pattern in enumerate(expected):
            for byte in b'\x55' * 48 + frame_bytes(index, pattern.data):
                for bit in (0, *(byte >> shift & 1 for shift in range(8)), 1):
                    decoder._symbol(bit)
        recovered = [Pattern(frame.slot, frame.data) for frame in decoder.finish()]
        self.assertEqual(recovered, expected)
        self.assertEqual(bank_from_json(bank_to_json(recovered)), expected)
        for pattern in recovered:
            validate_lmx2(pattern)

    def test_validation_rejects_invalid_indices_values_and_types(self):
        source = blank_pattern()
        for bad in (-1, 16, True):
            with self.assertRaises(ValueError): set_predictability(source, 1, (bad,) * 16)
        for bad in (1, 127, 256, True):
            with self.assertRaises(ValueError): set_motion_value(source, 1, 1, 3, bad)
        for part in (0, 11, True):
            with self.assertRaises(ValueError): predictability(source, part)
        for step in (0, 17, True):
            with self.assertRaises(ValueError): motion_value(source, 1, step, 3)
        for values in ((16,) * 16, (-16,) * 16, (0,) * 15):
            with self.assertRaises(ValueError): set_microtiming(source, 1, values)


if __name__ == '__main__':
    unittest.main()
