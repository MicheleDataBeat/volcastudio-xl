"""XL pattern format and catalog compatibility, with independent bit decoding."""
import struct
import unittest
from dataclasses import replace
from fractions import Fraction
from volcastudio.grooves import (load_catalog, apply_pattern, microtiming, plan_grooves,
                                 MICRO_OFFSETS, _apply_resolved)
from volcastudio.patterns import Pattern, blank_pattern
from volcastudio.pattern_transfer import pattern_targets


class XLGroovesTests(unittest.TestCase):
    def test_catalog_extended_profiles(self):
        new = load_catalog()
        self.assertEqual((len(new.profiles),len(new.templates)),(217,270))
        self.assertEqual(new.firmware, 'lumon-xl')
        self.assertEqual(new.resolve('SEXTUPLE_SWING_4_2').microtiming,(0,11)*8)
        self.assertEqual(new.resolve('DILLA_KICK_1_B01').microtiming[1],12)
        self.assertTrue(all(abs(v)<=15 for p in new.profiles for v in p.microtiming))

    def test_all_signed_values_parts_steps_neighbor_preservation(self):
        template=load_catalog().resolve('STRAIGHT')
        original=bytearray(blank_pattern('lumon-xl',0).data)
        # Fill valid XL extension controls to prove preserving loop/scales/EG tags.
        original[0xa24:0xa30]=bytes(range(12))
        original[0xa32:0xa3c]=bytes(range(10))
        pattern=Pattern(0,bytes(original))
        for part in range(1,11):
            for value in range(-15,16):
                vector=tuple(value if step%2 else -value for step in range(16))
                result=_apply_resolved(pattern,[(part,replace(template,microtiming=vector))],'lumon-xl')
                self.assertEqual(microtiming(result,part),vector)
                plane=int.from_bytes(result.data[12+2*(part-1):14+2*(part-1)],'little')
                for step,expected in enumerate(vector):
                    low=result.data[(part-1)*256+MICRO_OFFSETS[step//2]]>>(4*(step%2))&15
                    encoded=low|((plane>>step&1)<<4)
                    self.assertEqual(encoded-32 if encoded>=16 else encoded,expected)
                allowed={0xa30,0xa31,12+2*(part-1),13+2*(part-1)}|{(part-1)*256+o for o in MICRO_OFFSETS}
                self.assertTrue(all(a==b or index in allowed for index,(a,b) in enumerate(zip(pattern.data,result.data))))

    def test_explicit_firmware_rejects_legacy_and_unknown_extensions(self):
        xl = blank_pattern('lumon-xl',0)
        for target in ('lumon', 'pajen7'):
            with self.assertRaises(ValueError): pattern_targets([xl],target)
            with self.assertRaises(ValueError): apply_pattern(xl,{1:'STRAIGHT'},firmware=target)
        for magic in (b'LUM1', b'LMX1', b'LMX3', b'LUM2'):
            raw = bytearray(xl.data); raw[0xa20:0xa24] = magic
            legacy = Pattern(0,bytes(raw))
            with self.assertRaises(ValueError): apply_pattern(legacy,{1:'STRAIGHT'})
            with self.assertRaises(ValueError): pattern_targets([legacy],'lumon-xl')

    def test_initialization_and_reset_need_no_backup(self):
        raw=bytearray(blank_pattern('lumon-xl',0).data);raw[12:32]=b'\xff'*20;raw[0xa20:0xa3c]=b'\xff'*28
        output=apply_pattern(Pattern(0,bytes(raw)),{3:'SEXTUPLE_SWING_4_2'},firmware='lumon-xl')
        self.assertEqual(output.firmware,'lumon-xl')
        self.assertEqual(output.data[12:32],bytes(20))
        self.assertEqual(output.data[0xa24:0xa30],bytes(12))
        self.assertEqual(microtiming(output,3),(0,11)*8)
        plan=plan_grooves(None,{1:'DILLA_KICK_1_B01'},reset=True,firmware='lumon-xl')
        self.assertEqual(plan.as_dict()['firmware'],'lumon-xl')
        self.assertFalse(plan.original_backup_available)
        self.assertTrue(all(p.firmware=='lumon-xl' for p in plan.selected_patterns))

    def test_clear_high_plane_and_native_minus16_clamp(self):
        template=replace(load_catalog().resolve('STRAIGHT'),microtiming=(-15,)*16)
        source=_apply_resolved(blank_pattern('lumon-xl',0),[(1,template)],'lumon-xl')
        result=apply_pattern(source,{1:'STRAIGHT'},firmware='lumon-xl')
        self.assertEqual(result.data[12:14],b'\0\0')
        raw=bytearray(result.data);raw[12:14]=b'\xff\xff'
        self.assertEqual(microtiming(Pattern(0,bytes(raw)),1),(-15,)*16)

if __name__=='__main__':unittest.main()
