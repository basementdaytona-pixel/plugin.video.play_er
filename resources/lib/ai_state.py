"""Small per-Kodi-profile AI cache, protected across plugin invocations.

Daily selection is independent of shared media databases: profiles retain their
own preferences and quota. No credentials or raw prompts are written here.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
from contextlib import contextmanager


class AIState:
    LEASE_SECONDS = 1800

    def __init__(self, root, now=time.time, today=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = now
        self.today = today or (lambda: datetime.date.today().isoformat())

    @contextmanager
    def guard(self, name='daily', blocking=True):
        name = hashlib.sha256(name.encode()).hexdigest()
        with (self.root / (name + '.lock')).open('a+b') as handle:
            acquired = False
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    if not handle.read(1):
                        handle.write(b'0'); handle.flush()
                    handle.seek(0)
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                    except OSError:
                        if blocking: raise
                        yield False
                        return
                else:
                    import fcntl
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                    except BlockingIOError:
                        yield False
                        return
                acquired = True
                yield True
            finally:
                if acquired:
                    if os.name == 'nt':
                        handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self, name):
        path = self.root / name
        if not path.exists(): return {}
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError('AI cache is too large')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict): raise ValueError('Invalid AI cache')
        return data

    def _write(self, name, data):
        serialized = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if len(serialized.encode('utf-8')) > 16 * 1024 * 1024:
            raise ValueError('AI cache size limit exceeded; previous selection retained')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root,
                                             prefix='.ai-', delete=False) as output:
                temporary = output.name
                output.write(serialized)
                output.flush(); os.fsync(output.fileno())
            os.replace(temporary, self.root / name)
            temporary = None
        finally:
            if temporary and os.path.exists(temporary): os.unlink(temporary)

    def read(self):
        # Atomic replacement permits reads while a worker is calculating.
        return self._read('daily.json')

    def seed(self, results, date):
        with self.guard():
            state = self.read()
            if not state.get('results') and results:
                state.update(results=results, date=date)
                self._write('daily.json', state)

    def request(self, force=False):
        with self.guard():
            state = self.read()
            pending = state.get('pending') or {}
            if pending and self.now() - pending.get('time', 0) < self.LEASE_SECONDS:
                return None
            today = self.today()
            if not force and (state.get('date') == today or state.get('auto_attempt_date') == today):
                return None
            token = uuid.uuid4().hex
            state['revision'] = int(state.get('revision', 0)) + 1
            state['pending'] = {'token': token, 'time': self.now(), 'claimed': False}
            if not force: state['auto_attempt_date'] = today
            self._write('daily.json', state)
            return token

    def claim(self, token):
        with self.guard():
            state = self.read(); pending = state.get('pending') or {}
            if (not token or pending.get('token') != token or pending.get('claimed')
                    or self.now() - pending.get('time', 0) >= self.LEASE_SECONDS):
                return False
            pending['claimed'] = True
            self._write('daily.json', state)
            return True

    def complete(self, token, results, settings=None, stats=None):
        if not results: return False
        with self.guard():
            state = self.read(); pending = state.get('pending') or {}
            if pending.get('token') != token or not pending.get('claimed'): return False
            today = self.today()
            cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=21)).isoformat()
            history = {(r.get('media_type'), str(r.get('id'))): r for r in state.get('history', [])
                       if r.get('date', '') > cutoff}
            for item in results:
                row = {'id': item['id'], 'media_type': item['media_type'],
                       'title': item.get('title') or item.get('name', ''), 'date': today}
                history[(row['media_type'], str(row['id']))] = row
            state.update(results=results, date=today, pending=None, error=False,
                         history=sorted(history.values(), key=lambda r:r['date'], reverse=True))
            if settings is not None: state['settings'] = settings
            if stats is not None: state['stats'] = stats
            self._write('daily.json', state)
            return True

    def fail(self, token):
        with self.guard():
            state = self.read()
            if (state.get('pending') or {}).get('token') == token:
                state.update(pending=None, error=True)
                self._write('daily.json', state)

    def _key(self, key):
        return 'request-' + hashlib.sha256(key.encode()).hexdigest() + '.json'

    def get(self, key):
        entry = self._read(self._key(key))
        return entry.get('value') if entry.get('expires', 0) > self.now() else None

    def put(self, key, value, ttl=86400):
        with self.guard('requests'):
            self._write(self._key(key), {'expires': self.now() + ttl, 'value': value})
            files = sorted(self.root.glob('request-*.json'), key=lambda p:p.stat().st_mtime, reverse=True)
            for path in files[64:]: path.unlink(missing_ok=True)

    def is_cooling(self, provider):
        return self._read('cooldown.json').get(provider, 0) > self.now()

    def cooldown(self, provider, seconds=900):
        with self.guard('cooldown'):
            state = self._read('cooldown.json')
            state[provider] = self.now() + max(60, min(86400, seconds))
            self._write('cooldown.json', state)
