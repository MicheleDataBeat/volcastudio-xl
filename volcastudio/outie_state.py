"""The Desktop App's own draft; saved kits remain shared with the Browser App."""
import json
import os
import tempfile
from pathlib import Path


def draft_path(config):
    return config.state / 'outie' / 'draft.json'


def save_draft(config, *, sources, name, opened=None, expected=None, saved=None):
    path = draft_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'schema': 1, 'sources': [str(Path(p).resolve()) for p in sources],
               'name': name, 'opened': str(opened) if opened else None,
               'expected': expected, 'saved': str(saved) if saved else None}
    _write_json(path, payload)


def _write_json(path, payload):
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.draft-', delete=False) as stream:
            pending = Path(stream.name)
            json.dump(payload, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def load_draft(config, path=None):
    path = Path(path) if path is not None else draft_path(config)
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('schema') != 1
            or not isinstance(value.get('sources'), list)
            or not all(isinstance(p, str) for p in value['sources'])
            or not isinstance(value.get('name'), str)):
        raise ValueError('Invalid Desktop App draft; its file has been kept.')
    for key in ('opened', 'expected', 'saved'):
        if value.get(key) is not None and not isinstance(value[key], str):
            raise ValueError('Invalid Desktop App draft; its file has been kept.')
    missing = [p for p in value['sources'] if not Path(p).is_file()]
    if missing:
        raise ValueError(f'Desktop App draft has {len(missing)} missing sample files. Its draft file has been kept; restore those files before reopening the Desktop App.')
    return value


def load_preferences(config):
    path = config.state / 'outie' / 'preferences.json'
    if not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError('Invalid Desktop App device preferences')
    return value


def save_preferences(config, value):
    path = config.state / 'outie' / 'preferences.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, value)
