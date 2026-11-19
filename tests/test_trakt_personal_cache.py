"""Real SQLite and synthetic Kodi/Trakt for personal-list cache isolation."""
import tempfile
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

cache = load_module('resources.lib.cache_manager')
trakt = load_module('resources.lib.trakt', (
    'resources.lib.sf_context_style', 'resources.lib.monitor_orchestrator',
    'resources.lib.stream_state', 'resources.lib.utils_files',
    'resources.lib.utils_theme', 'resources.lib.utils',
))


class Window:
    def __init__(self):
        self.data = {}

    def getProperty(self, key):
        return self.data.get(key, '')

    def setProperty(self, key, value):
        self.data[key] = value

    def clearProperty(self, key):
        self.data.pop(key, None)


class PersonalListCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.window = Window()
        self.config = patch.multiple(cache, CACHE_DB_PATH=str(Path(self.temp.name) / 'cache.db'),
                                     DB_TYPE='SQLite', SQLITE_INITIALIZED=False, WINDOW=self.window)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.cache_patch = patch.object(trakt, 'cache_manager', cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)
        cache.clear_ram_cache()
        self.addon = MagicMock()
        self.settings = {'trakt_client_id': 'client', 'trakt_access_token': 'synthetic-A', 'trakt_page_limit': '20'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.getSettingBool.return_value = False
        self.epoch = cache.personal_cache_epoch('TRAKT_WATCHLIST')

    def test_key_is_account_and_session_specific_without_raw_token(self):
        first = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
        self.assertNotIn('synthetic-A', first)
        self.settings['trakt_access_token'] = 'synthetic-B'
        self.assertNotEqual(first, trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page'))
        self.settings['trakt_access_token'] = 'synthetic-A'
        with patch.object(cache, 'WINDOW', Window()):
            self.assertNotEqual(first, trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page'))

    def test_successful_mutation_invalidates_only_matching_section(self):
        key = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
        favkey = trakt._personal_list_cache_key(self.addon, 'TRAKT_FAVORITES', 'page')
        cache.cache_set('TRAKT_WATCHLIST', key, ['old'])
        cache.cache_set('TRAKT_FAVORITES', favkey, ['favorite'])
        cache.cache_set('TRAKT', 'public', ['trending'])
        cache.user_data_set('history', ['safe'])
        response = SimpleNamespace(status_code=201)
        with patch.object(trakt, 'safe_post', return_value=response), \
                patch.object(trakt, 'trakt_get_headers', return_value={}):
            trakt.trakt_add_to_watchlist({'media_type': 'movie', 'media_id': '42'}, self.addon, 1)
        newkey = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
        self.assertNotEqual(key, newkey)
        self.assertIsNone(cache.cache_get('TRAKT_WATCHLIST', newkey))
        self.assertEqual(cache.cache_get('TRAKT_FAVORITES', favkey), ['favorite'])
        self.assertEqual(cache.cache_get('TRAKT', 'public'), ['trending'])
        self.assertEqual(cache.user_data_get('history'), ['safe'])
        # Simulate an older in-flight request completing after the mutation.
        cache.cache_set('TRAKT_WATCHLIST', key, ['stale'])
        self.assertIsNone(cache.cache_get('TRAKT_WATCHLIST', newkey))

    def test_shared_window_invalidates_another_interpreters_ram(self):
        other = load_module('resources.lib.cache_manager')
        other.CACHE_DB_PATH = cache.CACHE_DB_PATH
        other.DB_TYPE = 'SQLite'
        other.SQLITE_INITIALIZED = False
        other.WINDOW = self.window
        key = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
        cache.cache_set('TRAKT_WATCHLIST', key, ['old'])
        self.assertEqual(other.cache_get('TRAKT_WATCHLIST', key), ['old'])
        cache.cache_clear('TRAKT_WATCHLIST', notify_success=False)
        with patch.object(trakt, 'cache_manager', other):
            newkey = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
            self.assertNotEqual(newkey, key)
            self.assertIsNone(other.cache_get('TRAKT_WATCHLIST', newkey))

    def test_rejected_mutation_preserves_cached_page(self):
        key = trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page')
        cache.cache_set('TRAKT_WATCHLIST', key, ['kept'])
        with patch.object(trakt, 'safe_post', return_value=SimpleNamespace(status_code=500)), \
                patch.object(trakt, 'trakt_get_headers', return_value={}):
            trakt.trakt_add_to_watchlist({'media_type': 'movie', 'media_id': '42'}, self.addon, 1)
        self.assertEqual(key, trakt._personal_list_cache_key(self.addon, 'TRAKT_WATCHLIST', 'page'))
        self.assertEqual(cache.cache_get('TRAKT_WATCHLIST', key), ['kept'])

    def test_remove_and_favorite_add_invalidate_correct_section(self):
        for method, section, status, params in [
                ('handle_watchlist_remove', 'TRAKT_WATCHLIST', 200, {'category': 'movies', 'remove': '42'}),
                ('trakt_add_to_favorites', 'TRAKT_FAVORITES', 201, {'media_type': 'movie', 'media_id': '42'})]:
            with self.subTest(method=method):
                old = cache.personal_cache_epoch(section)
                with patch.object(trakt, 'safe_post', return_value=SimpleNamespace(status_code=status)), \
                        patch.object(trakt, 'trakt_get_headers', return_value={}):
                    if method == 'handle_watchlist_remove':
                        trakt.handle_watchlist_remove(params, MagicMock(), self.addon)
                    else:
                        trakt.trakt_add_to_favorites(params, self.addon, 1)
                self.assertNotEqual(old, cache.personal_cache_epoch(section))

    def test_menu_refetches_after_mutation_and_account_change(self):
        movie = {'title': 'First', 'ids': {'tmdb': 1, 'trakt': 1}}
        payload = [{'movie': movie}]
        response = MagicMock(status_code=200, headers={})
        response.json.side_effect = lambda: list(payload)
        with patch.dict(sys.modules, {'resources.lib.tmdb': MagicMock()}), \
                patch.object(trakt, 'handle_trakt_401', return_value=response) as get, \
                patch.object(trakt, 'safe_post', return_value=SimpleNamespace(status_code=201)), \
                patch.object(trakt, 'trakt_get_headers', return_value={}), \
                patch.object(trakt, 'process_and_add_item') as render, \
                patch.object(trakt, 'add_next_page_item'):
            params = {'category': 'movies', 'page': 1}
            trakt.trakt_watchlist(params, self.addon, 1)
            trakt.trakt_watchlist(params, self.addon, 1)
            self.assertEqual(get.call_count, 1)
            trakt.trakt_add_to_watchlist({'media_type': 'movie', 'media_id': '2'}, self.addon, 1)
            payload.append({'movie': {'title': 'Second', 'ids': {'tmdb': 2, 'trakt': 2}}})
            render.reset_mock()
            trakt.trakt_watchlist(params, self.addon, 1)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(render.call_count, 2)
            self.settings['trakt_access_token'] = 'synthetic-B'
            trakt.trakt_watchlist(params, self.addon, 1)
            self.assertEqual(get.call_count, 3)

    def test_all_trakt_clear_keeps_user_data_and_uses_trakt_ttl(self):
        for section in ('TRAKT', 'TRAKT_WATCHLIST', 'TRAKT_FAVORITES'):
            self.assertEqual(cache._folder_ttl(section), cache.TTL_TRAKT)
            cache.cache_set(section, 'item', [section])
        cache.user_data_set('history', [1])
        cache.cache_clear('TRAKT')
        for section in ('TRAKT', 'TRAKT_WATCHLIST', 'TRAKT_FAVORITES'):
            self.assertIsNone(cache.cache_get(section, 'item'))
        self.assertEqual(cache.user_data_get('history'), [1])
