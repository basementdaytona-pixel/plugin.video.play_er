"""Concurrent preemptive writers must preserve the latest started search."""
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import resources.lib
from kodi_test_support import load_module
import test_episode_playback as support

actions = support.actions


class PreemptiveRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'cache.db')
        self.first = load_module('resources.lib.cache_manager')
        self.second = load_module('resources.lib.cache_manager')
        for cache in (self.first, self.second):
            cache.CACHE_DB_PATH = self.path
            cache.DB_TYPE = 'SQLite'
            cache.SQLITE_INITIALIZED = False
        conn = self.first._get_sqlite_connection()
        conn.close()
        self.second.SQLITE_INITIALIZED = True
        addon = MagicMock()
        addon.getSetting.return_value = ''
        addon.getSettingBool.return_value = False
        manager = SimpleNamespace(_active_provider_name='prehraj.to', get_providers_to_search=lambda: [object()])
        self.instance = SimpleNamespace(addon=addon, provider_manager=manager)
        self.key = 'preemptive_42_S01E02'
        self.meta = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}

    def test_slow_earlier_search_cannot_overwrite_later_result(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def search(query, *args, **kwargs):
            calls.append(query)
            if len(calls) == 1:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('earlier search did not finish')
                return [{'provider': 'prehraj.to', 'link': 'older', 'title': 'older'}]
            return [{'provider': 'prehraj.to', 'link': 'newer', 'title': 'newer'}]
        with patch.object(actions, '_search_providers_parallel', side_effect=search), \
             patch.object(resources.lib, 'cache_manager', self.first, create=True), \
             patch.dict('sys.modules', {'xbmc': actions.xbmc, 'resources.lib.cache_manager': self.first,
                                       'resources.lib.utils_logging': MagicMock()}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                earlier = pool.submit(actions._perform_pre_emptive_search, dict(self.meta), self.instance)
                try:
                    self.assertTrue(entered.wait(2))
                    later = pool.submit(actions._perform_pre_emptive_search, dict(self.meta), self.instance)
                    later.result(timeout=3)
                finally:
                    release.set()
                earlier.result(timeout=3)
        saved = self.second.cache_get('PREEMPTIVE_SOURCES', self.key)
        self.assertEqual(saved['results'][0]['link'], 'newer')

    def test_separate_interpreters_read_latest_preemptive_row(self):
        self.first.cache_set('PREEMPTIVE_SOURCES', self.key, {'results': ['first']})
        self.assertEqual(self.second.cache_get('PREEMPTIVE_SOURCES', self.key)['results'], ['first'])
        self.first.cache_set('PREEMPTIVE_SOURCES', self.key, {'results': ['second']})
        self.assertEqual(self.second.cache_get('PREEMPTIVE_SOURCES', self.key)['results'], ['second'])

    def test_conditional_writes_from_independent_interpreters_preserve_newest(self):
        now = time.time()
        barrier = threading.Barrier(8)
        def write(index):
            barrier.wait(timeout=5)
            cache = self.first if index % 2 else self.second
            return cache.cache_set_preemptive_if_newer(self.key, {'results': [index]}, now - 10 + index)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(8)))
        self.assertEqual(self.first.cache_get('PREEMPTIVE_SOURCES', self.key)['results'], [7])
        self.assertFalse(self.second.cache_set_preemptive_if_newer(self.key, {'results': ['old']}, now - 20))
        self.assertEqual(self.second.cache_get('PREEMPTIVE_SOURCES', self.key)['results'], [7])

    def test_future_timestamp_after_clock_rollback_can_be_replaced(self):
        now = time.time()
        with patch.object(self.first.time, 'time', return_value=now + 100):
            self.first.cache_set('PREEMPTIVE_SOURCES', self.key, {'results': ['future']})
        self.assertTrue(self.second.cache_set_preemptive_if_newer(self.key, {'results': ['current']}, now - 1))
        self.assertEqual(self.first.cache_get('PREEMPTIVE_SOURCES', self.key)['results'], ['current'])

    def test_failed_transaction_rolls_back_and_next_search_can_write(self):
        now = time.time() - 1
        with patch.object(self.first, '_folder_ttl', side_effect=RuntimeError('synthetic failure')):
            self.assertFalse(self.first.cache_set_preemptive_if_newer(self.key, {'value': 'bad'}, now))
        self.assertIsNone(self.second.cache_get('PREEMPTIVE_SOURCES', self.key))
        self.assertTrue(self.second.cache_set_preemptive_if_newer(self.key, {'value': 'good'}, now))
        self.assertEqual(self.first.cache_get('PREEMPTIVE_SOURCES', self.key)['value'], 'good')

    def test_expired_search_does_not_write_or_report_completion(self):
        mock_cache = MagicMock()
        with patch.object(actions, '_search_providers_parallel', return_value=[{'link': 'source'}]), \
             patch.object(resources.lib, 'cache_manager', mock_cache, create=True), \
             patch.dict('sys.modules', {'xbmc': actions.xbmc, 'resources.lib.cache_manager': mock_cache,
                                       'resources.lib.utils_logging': MagicMock()}):
            actions._perform_pre_emptive_search(dict(self.meta), self.instance, time.time() - 1801)
        mock_cache.cache_set_preemptive_if_newer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
