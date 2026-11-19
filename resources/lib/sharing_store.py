# -*- coding: utf-8 -*-
"""Local BROADCAST history shared by the Kodi service and menu invocations."""

# FIX PRE-EMPTIVE AND FILTERS [BROADCAST ATOMIC HISTORY AND CROSS-PROCESS LOCK]
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path


def record_key(record):
    identity = [str(record.get(key, '')) for key in
                ('ts', 'sender_id', 'tmdb_id', 'media_type', 'title')]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()


def normalize_records(records):
    if not isinstance(records, list):
        raise ValueError('Server nevrátil seznam sdílení')
    normalized = []
    for rec in records:
        if not isinstance(rec, dict) or not isinstance(rec.get('title'), str) or not rec['title'].strip():
            continue
        try:
            ts = int(rec.get('ts', 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if ts <= 0 or not rec.get('sender_id'):
            continue
        item = dict(rec, ts=ts, sender_id=str(rec['sender_id']))
        item['media_type'] = 'tv' if rec.get('media_type') in ('tv', 'episode', 'show') else 'movie'
        for key in ('tmdb_id', 'poster', 'plot', 'year'):
            item[key] = str(item.get(key) or '')
        normalized.append(item)
    if records and not normalized:
        raise ValueError('Odpověď neobsahuje platné položky sdílení')
    return normalized


class SharingStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    @contextmanager
    def locked(self):
        # SQLite supplies an OS-backed lock across Kodi Python interpreters.
        # No account data is stored in this database; history remains in JSON.
        self.directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.directory / 'SHARING_LOCK.sqlite'), timeout=20)
        try:
            connection.execute('BEGIN IMMEDIATE')
            yield
        finally:
            connection.rollback()
            connection.close()

    def _read_json(self, name, default):
        try:
            return json.loads((self.directory / name).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return default

    def _write_json(self, name, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='SHARING-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / name)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _history(self):
        history = self._read_json('SHARING_HISTORY.JSON', [])
        if not isinstance(history, list) or any(not isinstance(rec, dict) for rec in history):
            raise ValueError('Neplatný formát historie sdílení')
        return history

    def load_history(self):
        with self.locked():
            return self._history()

    def last_check(self):
        return float(self._read_json('SHARING_CACHE', 0))

    def mark_checked(self, timestamp):
        self._write_json('SHARING_CACHE', timestamp)

    def merge(self, records, device_id, limit):
        """Caller holds locked(). Persist history before advancing the cursor."""
        history = self._history()
        cursor = self._read_json('SHARING.OFFSET', 0)
        # Accept the original integer offset as well as the new cursor format.
        last_ts = int(cursor.get('ts', 0) if isinstance(cursor, dict) else cursor)
        seen = set(cursor.get('seen', []) if isinstance(cursor, dict) else [])
        known = {record_key(rec) for rec in history}
        incoming = []
        latest = last_ts
        for rec in sorted(records, key=lambda item: item['ts']):
            ts, key = rec['ts'], record_key(rec)
            if ts < last_ts or (ts == last_ts and key in seen):
                continue
            if ts > latest:
                latest, seen = ts, set()
            if ts == latest:
                seen.add(key)
            if str(rec.get('sender_id')) != str(device_id) and key not in known:
                incoming.append(rec)
                known.add(key)
        if incoming:
            history = sorted(history + incoming, key=lambda item: int(item.get('ts', 0)), reverse=True)
            self._write_json('SHARING_HISTORY.JSON', history[:max(1, min(500, limit))])
        self._write_json('SHARING.OFFSET', {'ts': latest, 'seen': sorted(seen)})
        return incoming, last_ts

    def remove(self, key):
        """Remove one local record; keep its cursor so refresh cannot restore it."""
        if not key:
            return False
        with self.locked():
            history = self._history()
            kept = [rec for rec in history if record_key(rec) != key]
            if len(kept) == len(history):
                return False
            self._write_json('SHARING_HISTORY.JSON', kept)
            return True
