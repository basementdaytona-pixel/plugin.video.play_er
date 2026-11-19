"""Account cache behavior with SQLite and synthetic Kodi/TMDB objects."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

cache = load_module('resources.lib.cache_manager')
account = load_module('resources.lib.tmdb_account', (
    'resources.lib.telegram', 'resources.lib.utils', 'resources.lib.utils_theme',
))


class Window:
    def __init__(self):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, '')

    def setProperty(self, key, value):
        self.properties[key] = value

    def clearProperty(self, key):
        self.properties.pop(key, None)


class AccountCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = Window()
        self.settings = patch.multiple(cache, CACHE_DB_PATH=str(Path(self.temp.name) / 'cache.db'),
                                       DB_TYPE='SQLite', SQLITE_INITIALIZED=False,
                                       WINDOW=self.window, _last_personal_prune=None)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.mocks = [patch.object(account, 'cache_manager', cache),
                      patch.object(account, 'get_tmdb_language', return_value='cs-CZ')]
        for p in self.mocks:
            p.start()
            self.addCleanup(p.stop)
        cache.clear_ram_cache()
        self.identity = {'id': 1, 'session_id': 'synthetic-session-A'}
        self.account_patch = patch.object(account, 'load_account_data', side_effect=lambda: dict(self.identity))
        self.account_patch.start()
        self.addCleanup(self.account_patch.stop)

    def test_toggle_refreshes_private_cache_and_preserves_public_data(self):
        payload = {'results': [{'id': 1}]}
        response = MagicMock()
        response.json.side_effect = lambda: dict(payload)
        post = MagicMock()
        post.json.return_value = {'success': True}
        cache.cache_set('TMDB', 'public', {'id': 23})
        cache.user_data_set('history', [1])
        with patch.object(account, 'safe_get', return_value=response) as get, \
                patch.object(account, 'safe_post', return_value=post), \
                patch.object(cache, 'safe_refresh') as refresh:
            account.tmdb_get_watchlist()
            account.tmdb_get_watchlist()
            self.assertEqual(get.call_count, 1)
            account.tmdb_toggle_watchlist(7)
            payload['results'] = [{'id': 2}]
            self.assertEqual(account.tmdb_get_watchlist()['results'], [{'id': 2}])
            self.assertEqual(get.call_count, 2)
            refresh.assert_called_once()
        self.assertEqual(cache.cache_get('TMDB', 'public'), {'id': 23})
        self.assertEqual(cache.user_data_get('history'), [1])

    def test_other_interpreter_and_inflight_old_response_keep_stale_key(self):
        other = load_module('resources.lib.cache_manager')
        other.CACHE_DB_PATH = cache.CACHE_DB_PATH
        other.DB_TYPE = 'SQLite'
        other.SQLITE_INITIALIZED = False
        other.WINDOW = self.window
        oldkey = account._account_cache_key(self.identity, 'page')
        cache.cache_set('TMDB_ACCOUNT', oldkey, {'old': True})
        self.assertEqual(other.cache_get('TMDB_ACCOUNT', oldkey), {'old': True})
        cache.cache_clear('TMDB_ACCOUNT', notify_success=False)
        cache.cache_set('TMDB_ACCOUNT', oldkey, {'old': True})
        with patch.object(account, 'cache_manager', other):
            newkey = account._account_cache_key(self.identity, 'page')
            self.assertNotEqual(oldkey, newkey)
            self.assertIsNone(other.cache_get('TMDB_ACCOUNT', newkey))
        with patch.object(cache, 'WINDOW', Window()):
            self.assertNotEqual(oldkey, account._account_cache_key(self.identity, 'page'))

    def test_cleanup_failure_can_retry_and_does_not_raise(self):
        cursor, connection = MagicMock(), MagicMock()
        cursor.execute.side_effect = RuntimeError('synthetic cleanup failure')
        connection.rollback.side_effect = RuntimeError('synthetic rollback failure')
        cache._prune_expired_personal_cache(cursor, connection, False)
        self.assertIsNone(cache._last_personal_prune)
        self.assertEqual(cursor.execute.call_count, 1)

    def test_failure_does_not_invalidate_and_account_session_isolation(self):
        response = MagicMock()
        response.json.return_value = {'results': [{'id': 1}]}
        post = MagicMock()
        post.json.return_value = {'success': False, 'status_code': 34}
        with patch.object(account, 'safe_get', return_value=response) as get, \
                patch.object(account, 'safe_post', return_value=post):
            account.tmdb_get_favorites()
            account.tmdb_toggle_favorite(7)
            account.tmdb_get_favorites()
            self.assertEqual(get.call_count, 1)
            self.identity['session_id'] = 'synthetic-session-B'
            account.tmdb_get_favorites()
            self.assertEqual(get.call_count, 2)

    def test_list_items_require_login_even_when_cached(self):
        response = MagicMock()
        response.json.return_value = {'items': [{'id': 1}]}
        with patch.object(account, 'safe_get', return_value=response) as get:
            self.assertIsNotNone(account.tmdb_get_user_list_items(7))
            self.identity['session_id'] = ''
            self.assertIsNone(account.tmdb_get_user_list_items(7))
            self.assertEqual(get.call_count, 1)

    def test_successful_rating_add_and_remove_invalidate_rated_items(self):
        key = account._account_cache_key(self.identity, 'rated')
        cache.cache_set('TMDB_ACCOUNT', key, {'id': 1})
        keyboard = MagicMock()
        keyboard.isConfirmed.return_value = True
        keyboard.getText.return_value = '8.5'
        with patch.object(account.xbmc, 'Keyboard', return_value=keyboard), \
                patch.object(account, 'safe_post', return_value=SimpleNamespace(status_code=201)), \
                patch.object(cache, 'safe_refresh'):
            account.tmdb_rate_prompt_and_send(1)
        next_key = account._account_cache_key(self.identity, 'rated')
        self.assertNotEqual(key, next_key)
        cache.cache_set('TMDB_ACCOUNT', next_key, {'id': 2})
        with patch.object(account, 'SESSION') as session, patch.object(cache, 'safe_refresh'):
            session.delete.return_value.status_code = 200
            account.tmdb_remove_rating(1)
        self.assertNotEqual(next_key, account._account_cache_key(self.identity, 'rated'))

    def test_trakt_and_tmdb_ttl_and_group_clear_remain_separate(self):
        self.assertEqual(cache._folder_ttl('TMDB_ACCOUNT'), cache.TTL_TMDB)
        for section in ('TMDB', 'TMDB_ACCOUNT', 'TRAKT_WATCHLIST'):
            cache.cache_set(section, 'item', section)
        cache.cache_clear('TMDB', notify_success=False)
        self.assertIsNone(cache.cache_get('TMDB', 'item'))
        self.assertIsNone(cache.cache_get('TMDB_ACCOUNT', 'item'))
        self.assertEqual(cache.cache_get('TRAKT_WATCHLIST', 'item'), 'TRAKT_WATCHLIST')

    def test_prune_deletes_only_expired_personal_cache_and_is_rate_limited(self):
        conn = cache._get_sqlite_connection()
        now = time.time()
        for i, (section, expiry) in enumerate([
                ('TMDB_ACCOUNT', now - 5), ('TRAKT_WATCHLIST', now - 5),
                ('TRAKT_FAVORITES', now + 3600), ('USER_DATA', now - 5), ('TMDB', now - 5)]):
            conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)', (str(i), section, '{}', now - 10, expiry))
        conn.commit()
        conn.close()
        with patch.object(cache.time, 'monotonic', return_value=100):
            cache.cache_set('TMDB_ACCOUNT', 'current', {'value': 1})
        conn = cache._get_sqlite_connection()
        sections = [row[0] for row in conn.execute('SELECT section FROM cache_store').fetchall()]
        self.assertNotIn('TRAKT_WATCHLIST', sections)
        self.assertIn('TRAKT_FAVORITES', sections)
        self.assertIn('USER_DATA', sections)
        self.assertIn('TMDB', sections)
        conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)', ('late', 'TRAKT_WATCHLIST', '{}', now - 10, now - 5))
        conn.commit()
        conn.close()
        with patch.object(cache.time, 'monotonic', return_value=101):
            cache.cache_set('TMDB_ACCOUNT', 'next', {'value': 2})
        conn = cache._get_sqlite_connection()
        self.assertEqual(conn.execute("SELECT count(*) FROM cache_store WHERE key_hash='late'").fetchone()[0], 1)
        conn.close()
        with patch.object(cache.time, 'monotonic', return_value=3701):
            cache.cache_set('TMDB_ACCOUNT', 'next', {'value': 3})
        conn = cache._get_sqlite_connection()
        self.assertEqual(conn.execute("SELECT count(*) FROM cache_store WHERE key_hash='late'").fetchone()[0], 0)
        conn.close()
