"""LMX3 backup/restore: generated complete payloads, independent byte oracle."""
import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from volcastudio import pattern_transfer
from volcastudio.config import Config
from volcastudio.grooves import apply_pattern
from volcastudio.outie_model import predictability_summary
from volcastudio.pattern_audio import AudioPatternDecoder
from volcastudio.pattern_format import (motion_value,predictability,validate_lmx3,
                                       set_predictability,set_motion_value,set_microtiming)
from volcastudio.patterns import (Pattern,blank_pattern,bank_to_json,bank_from_json,
                                 save_bank,load_bank,archive_kind)
from test_pattern_audio import frame_bytes,modulate,feed_chunks
from test_pattern_transfer import native_syro_blocks

PROFILE='lumon-xl-internal'


def raw_joint(raw,part,step,number):
    octets=number.to_bytes(4,'little')
    for row,value in zip((0xa0,0xb0,0x110),octets[:3]):
        raw[part*256+row+step]=value
    at=part*256+(0x35,0x36,0x37,0x39)[step//4]
    shift=2*(step%4)
    raw[at]=(raw[at]&~(3<<shift)) | (octets[3]<<shift)


def lmx3(slot=0,mode=0,seed=71):
    rng=random.Random(seed)
    raw=bytearray(rng.randbytes(2624))
    raw[:6]=b'PTST\xb8\x33';raw[-4:]=b'PTED';raw[0xa20:0xa24]=b'LMX3'
    cells={}
    for part in range(10):
        raw[part*256+0x3b]=(part*31+7)&255
        for step in range(16):
            triplet=tuple(rng.randrange(129) for _ in range(3))
            number=mode*2146689+triplet[0]+129*triplet[1]+16641*triplet[2]
            raw_joint(raw,part,step,number)
            cells[part,step]=tuple(v+127 if v else 0 for v in triplet)
    return Pattern(slot,bytes(raw)),cells


def mixed_bank():
    patterns=[lmx3(n,16+n)[0] for n in range(4)]
    patterns += [blank_pattern(slot=n) for n in range(4,8)]
    native=bytearray(blank_pattern(slot=8).data);native[0xa20:0xa24]=bytes(4)
    patterns += [Pattern(8,bytes(native)),Pattern(9,b'\xff'*2624),lmx3(None,23)[0]]
    return patterns


class Lmx3Tests(unittest.TestCase):
    def test_all_24_modes_at_all_160_positions_and_motion_cells(self):
        for mode in range(24):
            pattern,cells=lmx3(mode=mode)
            self.assertEqual(pattern.firmware,PROFILE)
            self.assertIs(validate_lmx3(pattern),pattern)
            for part in range(10):
                self.assertEqual(predictability(pattern,part+1),(mode,)*16)
                for step in range(16):
                    actual=tuple(motion_value(pattern,part+1,step+1,p) for p in (3,4,10))
                    self.assertEqual(actual,cells[part,step])
            self.assertEqual(bank_from_json(bank_to_json([pattern])),[pattern])
        self.assertIn('P.23',predictability_summary(pattern))

    def test_invalid_joint_codes_archive_exactly_but_fail_before_encoder_or_audio(self):
        pattern,_=lmx3(mode=23)
        for value in (51520536,67108863):
            raw=bytearray(pattern.data);raw_joint(raw,9,15,value)
            invalid=Pattern(0,bytes(raw))
            self.assertEqual(bank_from_json(bank_to_json([invalid])),[invalid])
            self.assertIn('invalid LMX3',predictability_summary(invalid))
            with patch('volcastudio.pattern_transfer.converter') as encoder, \
                 patch('volcastudio.pattern_transfer.audio_dependencies') as audio:
                with self.assertRaises(ValueError):
                    pattern_transfer.prepare_patterns([invalid],'/unused','/unused',PROFILE)
                with self.assertRaises(ValueError):
                    pattern_transfer.transfer_patterns([invalid],object(),PROFILE,confirm_callback=lambda _:True)
            encoder.assert_not_called();audio.assert_not_called()

    def test_historical_unsupported_lmx3_label_is_accepted_only_for_exact_marker(self):
        pattern,_=lmx3()
        doc=json.loads(bank_to_json([pattern]));doc['patterns'][0]['firmware']='unsupported'
        self.assertEqual(bank_from_json(json.dumps(doc)),[pattern])
        doc['patterns'][0]['firmware']='lumon-xl'
        with self.assertRaises(ValueError):bank_from_json(json.dumps(doc))

    def test_cross_profile_restore_and_existing_lmx2_editors_fail_closed(self):
        internal,_=lmx3()
        for patterns,target in (([internal],'lumon-xl'),([blank_pattern(slot=0)],PROFILE)):
            with patch('volcastudio.pattern_transfer.converter') as encoder, \
                 patch('volcastudio.pattern_transfer.audio_dependencies') as audio:
                with self.assertRaises(ValueError):pattern_transfer.prepare_patterns(patterns,'/unused','/unused',target)
                with self.assertRaises(ValueError):pattern_transfer.transfer_patterns(patterns,object(),target,confirm_callback=lambda _:True)
            encoder.assert_not_called();audio.assert_not_called()
        for edit in (lambda:set_predictability(internal,1,(0,)*16),
                     lambda:set_motion_value(internal,1,1,3,128),
                     lambda:apply_pattern(internal,{1:'STRAIGHT'})):
            with self.assertRaises(ValueError):edit()
        # Timing is the one edit shared by both formats (groove editor): marker kept.
        timed=set_microtiming(internal,1,(0,)*16)
        self.assertEqual(timed.data[0xa20:0xa24],b'LMX3')

    def test_audio_mixed_bank_remains_complete_raw_bytes_and_one_session(self):
        expected=mixed_bank()
        wires=[frame_bytes(i,p.data) for i,p in enumerate(expected)]
        frames=feed_chunks(AudioPatternDecoder(31250),modulate(wires)).finish()
        actual=[Pattern(f.slot,f.data) for f in frames]
        self.assertEqual(actual,expected)
        self.assertEqual(archive_kind(actual),'mixed')
        self.assertEqual(bank_from_json(bank_to_json(actual)),expected)
        self.assertEqual(archive_kind([expected[0],expected[9]]),'lmx3')
        bad=AudioPatternDecoder()
        for i,p in enumerate(expected):
            wire=frame_bytes(i,p.data,session=2 if i==10 else 1)
            with self.assertRaises(ValueError) if i==10 else contextlib.nullcontext():
                for octet in b'\x55'*48+wire:
                    for bit in (0,*(octet>>k&1 for k in range(8)),1):bad._symbol(bit)

    def test_native_syro_decodes_to_all_2624_original_lmx3_bytes(self):
        home=Config.read().syro_dir
        try:pattern_transfer.converter(home)
        except ValueError:self.skipTest('Native encoder unavailable')
        with tempfile.TemporaryDirectory() as temp,patch('volcastudio.pattern_transfer.play_stream') as play:
            expected=[lmx3(0,23)[0],lmx3(9,22,99)[0]]
            output=Path(temp)/'prepared'
            manifest=pattern_transfer.prepare_patterns(expected,output,home,PROFILE)
            self.assertEqual(manifest['slots'],[0,9])
            for p in expected:
                header,payload=native_syro_blocks(output/f'pattern-{p.slot:02d}.wav')
                self.assertEqual(header[20:22],bytes((0x20,p.slot)))
                self.assertEqual(payload,p.data)
                self.assertEqual(payload[0x3b],p.data[0x3b])
            play.assert_not_called()

    def test_blank_internal_and_current_snapshot_target_remain_explicit(self):
        blank=blank_pattern(PROFILE)
        self.assertEqual(blank.pattern_format,'LMX3')
        validate_lmx3(blank)
        p,_=lmx3(None,23)
        with self.assertRaises(ValueError):pattern_transfer.pattern_targets([p],PROFILE)
        self.assertEqual(pattern_transfer.pattern_targets([p],PROFILE,9),[(9,p)])
        stored=lmx3(0,21)[0]
        self.assertEqual(pattern_transfer.pattern_targets([stored,p],PROFILE),[(0,stored)])

    def test_current_midi_message_preserves_lmx3_and_uses_explicit_profile(self):
        from volcastudio.pattern_device import send_current
        from volcastudio.patterns import parse_sysex
        p,_=lmx3(None,23)
        messages=[]
        def send(port,wire,directory):messages.append((port,wire))
        with patch('volcastudio.pattern_device.portable_audio',return_value=False), \
             patch('volcastudio.pattern_device._required'),patch('volcastudio.pattern_device._send_midi',side_effect=send):
            send_current('fake',p,firmware=PROFILE)
        self.assertEqual(parse_sysex(messages[0][1]),[p])
        with self.assertRaises(ValueError):send_current('fake',p)


if __name__=='__main__':unittest.main()
