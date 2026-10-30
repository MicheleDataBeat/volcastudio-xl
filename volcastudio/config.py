import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def xdg(variable, fallback):
    if variable in os.environ:
        return Path(os.environ[variable]).expanduser()
    home = Path.home()
    if sys.platform == 'darwin':
        return home / 'Library' / ('Caches' if variable == 'XDG_CACHE_HOME' else 'Application Support')
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA' if variable == 'XDG_CONFIG_HOME' else 'LOCALAPPDATA', str(home / 'AppData' / 'Local')))
    return home / fallback


def setting_path(value):
    return Path(value).expanduser().resolve()


@dataclass
class Config:
    config: Path
    data: Path
    state: Path
    cache: Path
    sources_dir: Path
    syro_dir: Path
    theme_file: Path | None = None

    @classmethod
    def read(cls):
        cfg = xdg('XDG_CONFIG_HOME', '.config') / 'volcastudio'
        if os.environ.get('VOLCASTUDIO_CONFIG_DIR'):
            cfg = setting_path(os.environ['VOLCASTUDIO_CONFIG_DIR'])
        options = json.loads((cfg / 'config.json').read_text()) if (cfg / 'config.json').exists() else {}
        def path(name, default):
            return setting_path(os.environ.get('VOLCASTUDIO_' + name.upper(), options.get(name, str(default))))
        data = path('data_dir', xdg('XDG_DATA_HOME', '.local/share') / 'volcastudio')
        return cls(cfg, data,
                   path('state_dir', xdg('XDG_STATE_HOME', '.local/state') / 'volcastudio'),
                   path('cache_dir', xdg('XDG_CACHE_HOME', '.cache') / 'volcastudio'),
                   path('sources_dir', data / 'packs'), path('syro_dir', ROOT / 'build/syro'),
                   path('theme_file', cfg / 'colors.toml'))

    @property
    def kits(self):
        return self.data / 'kits'

    @property
    def patterns(self):
        return self.data / 'patterns'

    @property
    def libraries(self):
        return self.config / 'libraries'

    def initialize(self):
        for p in (self.config, self.kits, self.state, self.cache):
            p.mkdir(parents=True, exist_ok=True)
