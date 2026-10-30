import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from volcastudio.config import Config
from volcastudio.outie_state import draft_path, load_draft, save_draft


class OutieStateTests(unittest.TestCase):
    def test_atomic_failure_keeps_previous_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            save_draft(cfg,sources=[],name='first')
            original = draft_path(cfg).read_bytes()
            with patch('pathlib.Path.replace', side_effect=OSError('fixture disk failure')), self.assertRaises(OSError):
                save_draft(cfg,sources=[],name='second')
            self.assertEqual(draft_path(cfg).read_bytes(),original)
            self.assertEqual(list(draft_path(cfg).parent.glob('.draft-*')),[])

    def test_missing_sources_do_not_change_recovery_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            cfg=Config(p/'config',p/'data',p/'state',p/'cache',p/'packs',p/'syro')
            save_draft(cfg,sources=[p/'missing.wav'],name='recover-me')
            before=draft_path(cfg).read_bytes()
            with self.assertRaisesRegex(ValueError,'missing sample'):
                load_draft(cfg)
            self.assertEqual(draft_path(cfg).read_bytes(),before)
