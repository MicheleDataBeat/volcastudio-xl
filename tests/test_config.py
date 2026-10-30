import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from volcastudio.config import Config, ROOT
from volcastudio.libraries import registrations


class StandaloneConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {name: str(self.root / directory) for name, directory in (
            ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
            ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'))}
        p = patch.dict(os.environ, self.env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def test_default_configuration_is_application_owned(self):
        config = Config.read()
        self.assertEqual(config.config, self.root / 'config/volcastudio')
        self.assertEqual(config.sources_dir, self.root / 'data/volcastudio/packs')
        self.assertEqual(config.syro_dir, ROOT / 'build/syro')
        self.assertEqual(config.theme_file, config.config / 'colors.toml')
        self.assertEqual(registrations(config), '')
        self.assertFalse(config.config.exists())

    def test_explicit_configuration_and_environment_overrides(self):
        config = Config.read()
        config.config.mkdir(parents=True)
        (config.config / 'config.json').write_text(json.dumps({
            'sources_dir': str(self.root / 'collections'),
            'syro_dir': str(self.root / 'encoder'),
            'theme_file': str(self.root / 'theme.toml')}))
        with patch.dict(os.environ, {'VOLCASTUDIO_SYRO_DIR': str(self.root / 'override')}):
            updated = Config.read()
        self.assertEqual(updated.sources_dir, self.root / 'collections')
        self.assertEqual(updated.syro_dir, self.root / 'override')
        self.assertEqual(updated.theme_file, self.root / 'theme.toml')

