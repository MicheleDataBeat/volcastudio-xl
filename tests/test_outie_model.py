import tempfile
import unittest
import wave
from pathlib import Path

from volcastudio.config import Config
from volcastudio.outie_model import save_ordered_kit, parse_slots


class OutieModelTests(unittest.TestCase):
    def test_slots(self):
        self.assertEqual(parse_slots('1,3-5,10'), (0, 2, 3, 4, 9))
        self.assertEqual(parse_slots('all'), tuple(range(10)))
        for invalid in ('', '0', '11', '4-2', '1,,2', '1;2'):
            with self.assertRaises(ValueError):
                parse_slots(invalid)

    def test_edit_existing_pack_archives_and_rejects_stale_edits(self):
        from volcastudio.outie_model import open_ordered_kit
        from volcastudio.transfer import device_lock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = Config(root/'config', root/'data', root/'state', root/'cache', root/'packs', root/'syro')
            config.initialize()
            kit = config.sources_dir / 'Factory Drums'
            kit.mkdir(parents=True)
            for name, value in [('00-kick.wav', 12), ('nested/01-snare.wav', 20)]:
                path = kit/name
                path.parent.mkdir(exist_ok=True)
                with wave.open(str(path), 'wb') as f:
                    f.setparams((1, 2, 31250, 100, 'NONE', 'not compressed'))
                    f.writeframes(bytes([value, 0])*100)
            (kit/'README.txt').write_text('Fixture credit')
            (kit/'00-kick.json').write_text('{"fixture": true}')
            opened, sources, expected = open_ordered_kit(config, kit)
            self.assertEqual([p.relative_to(kit).as_posix() for p in sources], ['00-kick.wav', 'nested/01-snare.wav'])
            before = {p.relative_to(kit).as_posix():p.read_bytes() for p in kit.rglob('*') if p.is_file()}
            with device_lock(config.state), self.assertRaisesRegex(ValueError, 'transfer is active'):
                save_ordered_kit(config, kit.name, sources[::-1], edit=kit, expected=expected)
            self.assertFalse((config.data/'trash').exists())
            save_ordered_kit(config, kit.name, sources[::-1], edit=kit, expected=expected)
            archive = next((config.data/'trash').glob('*/kit'))
            self.assertEqual({p.relative_to(archive).as_posix():p.read_bytes() for p in archive.rglob('*') if p.is_file()}, before)
            self.assertEqual((kit/'README.txt').read_text(), 'Fixture credit')
            self.assertTrue((kit/'01-00-kick.json').is_file())
            _, latest, current = open_ordered_kit(config, kit)
            (kit/'README.txt').write_text('Concurrent edit')
            with self.assertRaisesRegex(ValueError, 'changed during editing'):
                save_ordered_kit(config, kit.name, latest, edit=kit, expected=current)
            self.assertEqual((kit/'README.txt').read_text(), 'Concurrent edit')
            self.assertEqual(len(list((config.data/'trash').iterdir())), 1)
            self.assertEqual(list(kit.parent.glob('.volcastudio-*')), [])

    def test_independent_ordered_kit_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(root/'config', root/'data', root/'state', root/'cache', root/'packs', root/'syro')
            sources = []
            for name, value in [('z.wav', 12), ('a.wav', 20)]:
                path = root / name
                with wave.open(str(path), 'wb') as f:
                    f.setparams((1, 2, 31250, 100, 'NONE', 'not compressed'))
                    f.writeframes(bytes([value, 0])*100)
                sources.append(path)
            before = [p.read_bytes() for p in sources]
            target = save_ordered_kit(config, 'ordered-kit', sources)
            self.assertEqual([p.name for p in sorted(target.glob('*.wav'))], ['00-z.wav', '01-a.wav'])
            self.assertEqual([p.read_bytes() for p in sources], before)
            with self.assertRaises(ValueError):
                save_ordered_kit(config, 'ordered-kit', sources[::-1])
            self.assertEqual((target/'00-z.wav').read_bytes(), before[0])
            self.assertEqual(list(config.kits.glob('.volcastudio-*')), [])


class PredictabilitySummaryTests(unittest.TestCase):
    def test_summary_reports_all_and_per_step_modes_without_changing_bank(self):
        from volcastudio.outie_model import predictability_summary
        from volcastudio.patterns import blank_pattern
        from volcastudio.pattern_format import set_predictability
        empty = blank_pattern()
        self.assertEqual(predictability_summary(empty), 'Predictability ALL on every step/part')
        pattern = set_predictability(empty, 3, tuple(range(16)))
        before = pattern.data
        self.assertIn('part 3: ALL P.01 P.02 P.03 P.04 P.05 P.06 P.07 P.08 P.09 P.10 P.11 P.12 P.13 P.14 P.15', predictability_summary(pattern))
        self.assertEqual(pattern.data, before)
