"""Bounded, account-scoped Trakt context for AI generation, never widget rendering."""
import hashlib
import json
import os
import sqlite3
from contextlib import closing
import math
import time
from urllib.parse import urlencode

SOURCES = ('trakt_watched', 'trakt_in_progress', 'trakt_ratings')
STALE_SECONDS = 86400
RETRY_SECONDS = 300


def _warn(message):
    try:
        import xbmc
        from resources.lib.utils_logging import log
        log('AI CONTEXT - ' + message, xbmc.LOGWARNING)
    except Exception:
        pass


def _number(value, default=0):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _identity(item):
    return item['media_type'], str(item.get('tmdb_id') or item.get('trakt_id')
                                   or (item['title'].casefold(), item.get('year')))


def _normalise(rows, source):
    items, seen = [], set()
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        media = row.get('movie') or row.get('show')
        if not isinstance(media, dict) or not isinstance(media.get('title'), str):
            continue
        title = ' '.join(media['title'].split())[:200]
        if not title:
            continue
        rating, progress = _number(row.get('rating')), _number(row.get('progress'))
        if source == 'trakt_ratings' and not 7 <= rating <= 10:
            continue
        if source == 'trakt_in_progress' and not 0 < progress < 100:
            continue
        ids = media.get('ids') if isinstance(media.get('ids'), dict) else {}
        item = {'title': title, 'year': media.get('year'),
                'media_type': 'movie' if row.get('movie') else 'tv',
                'tmdb_id': ids.get('tmdb'), 'trakt_id': ids.get('trakt'),
                'activity': str(row.get('watched_at') or row.get('paused_at')
                                or row.get('rated_at') or '')}
        if source == 'trakt_ratings':
            item['rating'] = rating
        if source == 'trakt_in_progress':
            item['progress'] = progress
        identity = _identity(item)
        if identity not in seen:
            seen.add(identity)
            items.append(item)
    return items


def _account_scope(addon):
    from resources.lib import cache_manager
    access = addon.getSetting('trakt_access_token') or ''
    refresh = addon.getSetting('trakt_refresh_token') or ''
    if not access:
        try:
            access = cache_manager.user_data_get('trakt_access_token') or ''
        except Exception:
            pass
    if not access and not refresh:
        return None
    # Token refresh may cause one cache miss; account changes can never reuse
    # private preferences. Raw tokens are never cache keys or log messages.
    value = '\0'.join((str(addon.getSetting('trakt_client_id') or ''), str(access), str(refresh)))
    return hashlib.sha256(value.encode()).hexdigest()



def _local_cache(key, entry=None):
    """Mirror only AI context in the configured base SQLite DB, even in MySQL mode.

    This dedicated table never changes the cache backend/global connection or
    touches playback history and metadata tables. It also keeps MySQL outages
    from turning repeated context reads into repeated network requests.
    """
    from resources.lib import cache_manager
    path = getattr(cache_manager, 'CACHE_DB_PATH', None)
    if not path:
        return None
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with closing(sqlite3.connect(path, timeout=1)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS ai_context_cache '
                       '(cache_key TEXT PRIMARY KEY, payload TEXT, stored_at REAL)')
            if entry is None:
                row = db.execute('SELECT payload FROM ai_context_cache WHERE cache_key=? '
                                 'AND stored_at>=?', (key, time.time() - STALE_SECONDS)).fetchone()
                return json.loads(row[0]) if row else None
            db.execute('INSERT OR REPLACE INTO ai_context_cache VALUES (?,?,?)',
                       (key, json.dumps(entry, ensure_ascii=False), time.time()))
            db.execute('DELETE FROM ai_context_cache WHERE stored_at<?',
                       (time.time() - STALE_SECONDS,))
            db.commit()
    except (OSError, sqlite3.Error, ValueError):
        # Primary cache/API can still work if the local disk is unavailable.
        return None


def _valid_entry(entry):
    return entry if isinstance(entry, dict) and isinstance(entry.get('items'), list) else {}


def _fresh_items(entry, now, ttl):
    if not entry:
        return None
    age = now - _number(entry.get('fetched_at'))
    old = entry['items'] if 0 <= age <= STALE_SECONDS else []
    if (0 <= age < ttl) or _number(entry.get('retry_after')) > now:
        return old
    return None

def _feed(addon, source, endpoint, scope, ttl):
    from resources.lib import cache_manager
    now = time.time()
    key = 'v1:' + scope + ':' + source + ':' + endpoint
    local = _valid_entry(_local_cache(key))
    ready = _fresh_items(local, now, ttl)
    if ready is not None:
        return ready
    try:
        shared = _valid_entry(cache_manager.cache_get('AI_CONTEXT', key, max_age=STALE_SECONDS))
    except Exception:
        shared = {}
    cached = max((local, shared), key=lambda e: _number(e.get('updated_at', e.get('fetched_at'))))
    ready = _fresh_items(cached, now, ttl)
    if ready is not None:
        _local_cache(key, cached)
        return ready
    age = now - _number(cached.get('fetched_at'))
    old = cached.get('items', []) if 0 <= age <= STALE_SECONDS else []
    try:
        from resources.lib.trakt import handle_trakt_401
        response = handle_trakt_401('https://api.trakt.tv/' + endpoint, addon=addon)
        if response is None or response.status_code != 200:
            raise RuntimeError('Trakt response unavailable')
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError('Invalid Trakt response')
        items = _normalise(rows, source)
        entry = {'fetched_at': now, 'items': items, 'retry_after': 0}
    except Exception as exc:
        _warn(source + ' unavailable (' + type(exc).__name__ + '); same-account cache retained')
        entry = {'fetched_at': cached.get('fetched_at', 0),
                 'items': old, 'retry_after': now + RETRY_SECONDS}
        items = old
    entry['updated_at'] = now
    _local_cache(key, entry)
    try:
        cache_manager.cache_set('AI_CONTEXT', key, entry)
    except Exception:
        _warn('Context cache unavailable; generation can continue')
    return items


def get_source_items(addon, source):
    """Read/refresh only the selected source, with bounded GETs and no UI calls."""
    if source not in SOURCES:
        return []
    scope = _account_scope(addon)
    if not scope:
        return []
    if source == 'trakt_watched':
        feeds = ('sync/history/movies', 'sync/history/episodes')
    elif source == 'trakt_in_progress':
        feeds = ('sync/playback/movies', 'sync/playback/episodes')
    else:
        feeds = ('users/me/ratings/movies', 'users/me/ratings/shows')
    ttl = 900 if source == 'trakt_in_progress' else 3600
    result, seen = [], set()
    for feed in feeds:
        endpoint = feed + '?' + urlencode({'extended': 'full', 'page': 1, 'limit': 100})
        for item in _feed(addon, source, endpoint, scope, ttl):
            if not isinstance(item, dict) or not isinstance(item.get('title'), str):
                continue
            identity = _identity(item)
            if identity not in seen:
                seen.add(identity)
                result.append(item)
    return sorted(result, key=lambda item: str(item.get('activity', '')), reverse=True)[:20]


def format_context(source, items):
    labels = {
        'trakt_watched': 'Na TRAKT.TV nedávno zhlédnuté (samotné zhlédnutí není kladné hodnocení)',
        'trakt_in_progress': 'Na TRAKT.TV rozkoukané filmy a seriály s uloženým průběhem přehrávání',
        'trakt_ratings': 'Na TRAKT.TV uživatelem kladně hodnocené (vlastní hodnocení 7–10/10)',
    }
    titles = []
    for item in items:
        title = item['title'] + (f" ({item['year']})" if item.get('year') else '')
        if source == 'trakt_ratings':
            title += f" — vlastní hodnocení {item['rating']:g}/10"
        titles.append(title)
    return labels[source] + ' : ' + ', '.join(titles) if titles else ''



def select_daily_results(items, limit):
    """Preserve ranking, but use a resolved reserve to include both media kinds."""
    selected = list(items[:limit])
    if limit < 2 or not selected:
        return selected
    present = {item['media_type'] for item in selected}
    if present == {'movie', 'tv'}:
        return selected
    missing = 'tv' if 'movie' in present else 'movie'
    replacement = next((item for item in items[limit:] if item['media_type'] == missing), None)
    if replacement is None:
        return []  # Worker failure keeps the previous valid daily selection.
    if len(selected) < limit:
        selected.append(replacement)
    else:
        selected[-1] = replacement
    return selected
