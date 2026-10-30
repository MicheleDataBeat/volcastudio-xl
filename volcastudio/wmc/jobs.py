"""One background operation at a time, with progress, confirmation and cancel.

The browser polls a snapshot. Device work runs inside the shared
``desktop_audio.audio_operation`` so cancellation reaches FFmpeg, the SYRO
converter and every PCM block exactly as in the Desktop App. Outcomes keep three
different facts apart: offline results, prepared signals and signals sent.
"""
import itertools
import subprocess
import threading
import time
import traceback

from .. import desktop_audio

_IDS = itertools.count(1)

CONFIRM_TIMEOUT = 600  # an unanswered confirmation is declined, releasing the shared lock

# Outcome vocabulary shared with the interface. "signals_sent" is never a
# device receipt: SYRO audio is one-way.
OUTCOMES = ('done', 'failed', 'cancelled', 'cancelled_before_sending', 'interrupted', 'signals_sent')


class Busy(ValueError):
    pass


def describe_error(exc):
    if isinstance(exc, subprocess.CalledProcessError):
        detail = exc.stderr.decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        tool = str(exc.cmd[0]) if exc.cmd else 'tool'
        name = tool.replace('\\', '/').rsplit('/', 1)[-1]
        return f'{name} stopped (exit {exc.returncode}). {detail.strip()[-400:]}'.strip()
    if isinstance(exc, FileExistsError):
        return f'Already exists, nothing was overwritten: {exc.filename or exc}'
    if isinstance(exc, PermissionError):
        return f'Permission denied: {exc.filename or exc}. Check folder permissions or system privacy settings.'
    text = str(exc) or type(exc).__name__
    return text


class Job:
    def __init__(self, kind, title, *, device=False, streams=None, labels=None):
        self.id = next(_IDS)
        self.kind = kind
        self.title = title
        self.device = device
        self.state = 'running'
        self.cancel_event = threading.Event()
        self.answer_event = threading.Event()
        self.approved = False
        self.decided = False
        self.decision = threading.Lock()
        self.sending = False
        self.manifest = None
        self.result = None
        self.error = None
        self.outcome = None
        self.started = time.time()
        self.finished = None
        self.message = 'Working…'
        self.current = 0
        self.total = 0
        self.streams = streams
        self.stream_index = 0
        self.labels = labels
        self._last = None

    # Called from the worker thread by backend transfers.
    def confirm(self, manifest):
        self.manifest = manifest
        if callable(self.streams):
            self.streams = self.streams(manifest)
        with self.decision:
            self.answer_event.clear()
            self.approved = self.decided = False
            self.state = 'confirm'
        self.message = 'Waiting for your decision. Nothing has been sent.'
        deadline = time.monotonic() + CONFIRM_TIMEOUT
        while not self.answer_event.wait(.1):
            if self.cancel_event.is_set() or time.monotonic() > deadline:
                break
        with self.decision:
            # The decision is taken once, atomically; a late answer is ignored.
            approved = self.approved and not self.cancel_event.is_set()
            self.decided = True
            self.approved = self.sending = approved
            self.state = 'running'
        self.message = 'Sending signals…' if approved else 'Stopped before sending.'
        return approved

    def answer(self, approve):
        with self.decision:
            if self.state != 'confirm' or self.decided:
                raise ValueError('This operation is not waiting for confirmation.')
            self.approved = bool(approve)
            self.answer_event.set()

    def progress(self, message, current=0, total=0):
        # desktop_audio reports each signal separately; count streams so the
        # browser can show "signal k of n" across a complete transfer.
        if self.sending and message == 'Sending signal':
            if self._last is None or current < self._last:
                self.stream_index += 1
            self._last = current
            label = self.labels(self.stream_index, self.streams) if self.labels else f'Signal {self.stream_index}'
            self.message = label
        else:
            self.message = str(message)
        self.current, self.total = int(current), int(total)

    def snapshot(self):
        return {'id': self.id, 'kind': self.kind, 'title': self.title, 'state': self.state,
                'device': self.device, 'message': self.message, 'current': self.current,
                'total': self.total, 'stream_index': self.stream_index,
                'streams': self.streams if isinstance(self.streams, int) else None,
                'manifest': self.manifest if self.state == 'confirm' else None,
                'outcome': self.outcome, 'result': self.result, 'error': self.error,
                'cancel_requested': self.cancel_event.is_set(), 'sending': self.sending,
                'elapsed': round((self.finished or time.time()) - self.started, 1)}


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.last = None

    @property
    def active(self):
        job = self.current
        return job is not None and job.state in ('running', 'confirm')

    def start(self, kind, title, operation, *, device_target=None, on_success=None,
              streams=None, labels=None):
        """``operation(job)`` or, with ``device_target``, ``operation(job, target)``."""
        with self.lock:
            if self.active:
                raise Busy('Another operation is in progress. Wait for it or cancel it first.')
            job = Job(kind, title, device=device_target is not None, streams=streams, labels=labels)
            self.current = job

        def run():
            try:
                if device_target is not None:
                    with desktop_audio.audio_operation(cancel_event=job.cancel_event,
                                                       progress_callback=job.progress):
                        result = operation(job, device_target)
                    if job.sending and job.cancel_event.is_set():
                        job.outcome = 'interrupted'
                    elif not job.sending or (isinstance(result, dict) and result.get('phase') == 'cancelled'):
                        job.outcome = 'cancelled_before_sending'
                    else:
                        job.outcome = 'signals_sent'
                else:
                    with desktop_audio.audio_operation(cancel_event=job.cancel_event,
                                                       progress_callback=job.progress):
                        result = operation(job)
                    if job.cancel_event.is_set():
                        raise desktop_audio.TransferCancelled('Cancelled')
                    job.outcome = 'done'
                if on_success is not None and job.outcome in ('done', 'signals_sent'):
                    result = on_success(result)
                job.result = result
            except (Exception, KeyboardInterrupt) as exc:
                if isinstance(exc, KeyboardInterrupt):
                    job.outcome = 'interrupted' if job.sending else (
                        'cancelled_before_sending' if job.device else 'cancelled')
                    job.error = ('Stopped while sending. Signals already played cannot be undone; check the Volca.'
                                 if job.sending else 'Cancelled. Nothing was changed.' if not job.device else
                                 'Cancelled before sending. Nothing reached the Volca.')
                else:
                    job.outcome = 'interrupted' if job.sending else 'failed'
                    job.error = describe_error(exc)
                    if job.sending:
                        job.error += ' Some signals may already have reached the Volca; check it before retrying.'
                    job.trace = traceback.format_exc(limit=6)
            finally:
                job.finished = time.time()
                job.state = 'finished'
                with self.lock:
                    self.last = job

        threading.Thread(target=run, name=f'wmc-job-{job.id}', daemon=True).start()
        return job

    def find(self, ident):
        job = self.current
        if job is None or job.id != ident:
            raise ValueError('This operation is no longer active.')
        return job

    def answer(self, ident, approve):
        job = self.find(ident)
        job.answer(approve)
        return job.snapshot()

    def cancel(self, ident):
        job = self.find(ident)
        if job.state in ('running', 'confirm'):
            job.cancel_event.set()
            job.answer_event.set()
        return job.snapshot()

    def snapshot(self):
        job = self.current
        return job.snapshot() if job else None
