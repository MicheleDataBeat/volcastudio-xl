"""Downloadable offline preparations, confined to the Browser App's export cache.

The shared encoders make the files. An opaque identifier grants access to one
completed ZIP in this helper session; an HTTP caller cannot request a disk path.
"""
import secrets
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path

from .. import desktop_audio


class PreparedExports:
    def __init__(self, cache):
        self.cache = Path(cache) / 'exports'
        self.files = {}
        self.lock = threading.Lock()

    def prepare(self, label, encoder, job):
        self.cache.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='prepared-', dir=self.cache))
        try:
            output = folder / 'signals'
            job.progress('Preparing SYRO files offline; nothing is sent', 0, 1)
            manifest = encoder(output)
            desktop_audio.check_cancelled()
            archive = folder / 'signals.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(output.rglob('*')):
                    desktop_audio.check_cancelled()
                    if path.is_file():
                        bundle.write(path, path.relative_to(output).as_posix())
            desktop_audio.check_cancelled()
            ident = secrets.token_urlsafe(24)
            name = f'{label}-syro.zip'
            with self.lock:
                self.files[ident] = (archive, name)
            return {'id': ident, 'name': name, 'bytes': archive.stat().st_size,
                    'manifest': manifest, 'download': '/api/prepared/download?id=' + ident}
        except BaseException:
            shutil.rmtree(folder)
            raise

    def download(self, ident):
        with self.lock:
            record = self.files.get(ident) if isinstance(ident, str) else None
        if record is None or not record[0].is_file():
            raise ValueError('Prepared download is unavailable. Prepare the signals again.')
        return record
