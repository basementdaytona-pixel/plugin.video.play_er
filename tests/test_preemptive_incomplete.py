"""Interrupted provider searches must not poison preemptive episode caches."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from resources.lib.preemptive_scope import source_scope

import resources.lib
import test_episode_playback as episode_support
import test_provider_responses as provider_support

actions = episode_support.actions
prehraj = provider_support.prehraj
webshare = provider_support.webshare


def response(rows, status=200):
    return SimpleNamespace(status_code=status, json=lambda: {'data': rows})


def videos(start, count):
    return [{'id': n, 'name': 'Source %d' % n} for n in range(start, start + count)]


class IncompletePreemptiveTests(unittest.TestCase):
    def setUp(self):
        self.addon = MagicMock()
        self.settings = {'search_pages': '2', 'search_ls': '160', 'enable_filtering': 'false',
                         'active_provider': 'prehraj.to', 'multi_provider_sort': 'PREHRAJ.TO'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.getSettingBool.side_effect = lambda key: key == 'enable_multi_provider'
        self.p = object.__new__(prehraj.PrehrajTo)
        self.p.addon = self.addon
        self.p.base_url = 'https://example.invalid'
        self.p._access_token = None
        self.p.get_premium_cookies = MagicMock(return_value=None)
        self.p.normalize_and_filter = lambda rows, **kwargs: rows
        self.p._api_get = MagicMock()
        self.instance = SimpleNamespace(addon=self.addon, provider_manager=SimpleNamespace(
            _active_provider_name='prehraj.to', get_providers_to_search=lambda: self.providers))
        self.meta = {'tmdb_id': 42, 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}
        self.cache = MagicMock()

    def write(self):
        with patch.object(actions, 'get_threadpool', return_value=2), \
             patch.object(resources.lib, 'cache_manager', self.cache, create=True), \
             patch.dict('sys.modules', {'xbmc': actions.xbmc, 'resources.lib.cache_manager': self.cache,
                                       'resources.lib.utils_logging': MagicMock()}):
            actions._perform_pre_emptive_search(self.meta, self.instance)

    def test_later_prehraj_failure_preserves_sources_but_prevents_cache(self):
        self.p._api_get.side_effect = [response(videos(1, 32)), response([], 503)]
        rows = self.p.search_sources('Show S01E02', apply_filters=False)
        self.assertEqual(len(rows), 32)
        self.assertIs(rows.complete, False)
        self.p._api_get.side_effect = [response(videos(1, 32)), response([], 503)]
        self.providers = [self.p]
        self.write()
        self.cache.cache_set_preemptive_if_newer.assert_not_called()
        self.p._api_get.side_effect = [response(videos(1, 1))]
        self.write()
        self.assertEqual(self.cache.cache_set_preemptive_if_newer.call_count, 1)
        self.assertEqual(self.cache.cache_set_preemptive_if_newer.call_args.args[1]['results'][0]['id'], 1)

    def test_interrupted_preemptive_search_does_not_write_cache(self):
        self.p._api_get.side_effect = [response(videos(1, 32)), response([], 503)]
        self.providers = [self.p]
        self.write()
        self.cache.cache_set_preemptive_if_newer.assert_not_called()

    def test_webshare_xml_failure_is_incomplete(self):
        import xml.etree.ElementTree as ET
        w = object.__new__(webshare.Webshare)
        w.addon = self.addon
        w.base_url = 'https://example.invalid/api/'
        w._get_auth_token = lambda: 'synthetic'
        w._post_with_token_retry = lambda *args: (SimpleNamespace(status_code=200), ET.fromstring('<response><status>FAIL</status></response>'))
        w.normalize_and_filter = lambda rows, **kwargs: rows
        rows = w.search_sources('Show')
        self.assertEqual(rows, [])
        self.assertIs(rows.complete, False)

    def test_unavailable_or_malformed_webshare_response_is_incomplete(self):
        w = object.__new__(webshare.Webshare)
        w.addon = self.addon
        w.base_url = 'https://example.invalid/api/'
        w._get_auth_token = lambda: 'synthetic'
        w.normalize_and_filter = lambda rows, **kwargs: rows
        for outcome in ((None, None), ValueError('invalid XML')):
            with self.subTest(outcome=outcome):
                w._post_with_token_retry = MagicMock(side_effect=outcome if isinstance(outcome, Exception) else None,
                                                       return_value=outcome)
                rows = w.search_sources('Show')
                self.assertEqual(rows, [])
                self.assertIs(rows.complete, False)

    def test_suggestion_failure_is_incomplete_but_empty_success_is_complete(self):
        self.p._api_get.side_effect = [response([]), response([], 503)]
        failed = self.p.search_sources('Show', apply_filters=False)
        self.assertEqual(failed, [])
        self.assertIs(failed.complete, False)
        self.p._api_get.side_effect = [response([]), response([])]
        empty = self.p.search_sources('Show', apply_filters=False)
        self.assertEqual(empty, [])
        self.assertIs(empty.complete, True)

    def test_old_scope_does_not_reuse_potentially_incomplete_cache(self):
        old = 'dd28ee0df8610f34adec1e1207b4e706abd9a795fed965c58b8bdcf5a9c312f9'
        self.assertNotEqual(source_scope(self.addon, self.instance.provider_manager), old)

    def test_failed_webshare_does_not_cache_other_provider_results(self):
        self.p._api_get.return_value = response(videos(1, 1))
        w = object.__new__(webshare.Webshare)
        w.addon = self.addon
        w.base_url = 'https://example.invalid/api/'
        w._get_auth_token = lambda: None
        self.providers = [self.p, w]
        with patch.object(actions, 'get_threadpool', return_value=2):
            rows = actions._search_providers_parallel('Show', self.providers)
        self.assertEqual([row['id'] for row in rows], [1])
        self.assertIs(rows.complete, False)
        self.write()
        self.cache.cache_set_preemptive_if_newer.assert_not_called()

    def test_valid_empty_webshare_results_can_be_cached_with_prehraj(self):
        self.p._api_get.return_value = response(videos(1, 1))
        w = object.__new__(webshare.Webshare)
        w.addon = self.addon
        w.base_url = 'https://example.invalid/api/'
        w._get_auth_token = lambda: 'synthetic'
        import xml.etree.ElementTree as ET
        w._post_with_token_retry = lambda *args: (SimpleNamespace(status_code=200), ET.fromstring('<response><status>OK</status></response>'))
        w.normalize_and_filter = lambda rows, **kwargs: rows
        self.providers = [self.p, w]
        self.write()
        self.cache.cache_set_preemptive_if_newer.assert_called_once()

    def test_raised_provider_exception_marks_combined_results_incomplete(self):
        self.p._api_get.return_value = response(videos(1, 1))
        failing = SimpleNamespace(search_handles_auth=True, search_sources=MagicMock(side_effect=RuntimeError('offline')))
        with patch.object(actions, 'get_threadpool', return_value=2):
            rows = actions._search_providers_parallel('Show', [self.p, failing])
        self.assertEqual([row['id'] for row in rows], [1])
        self.assertIs(rows.complete, False)

    def test_shared_provider_searches_keep_completion_state_separate(self):
        barrier = threading.Barrier(2)
        def get_page(endpoint, params=None, **kwargs):
            if params['offset'] == 0:
                barrier.wait(timeout=3)
                return response(videos(1, 32) if params['phrase'] == 'broken' else videos(100, 1))
            return response([], 503)
        self.p._api_get.side_effect = get_page
        with ThreadPoolExecutor(max_workers=2) as executor:
            broken = executor.submit(self.p.search_sources, 'broken', apply_filters=False)
            healthy = executor.submit(self.p.search_sources, 'healthy', apply_filters=False)
            bad_rows, good_rows = broken.result(), healthy.result()
        self.assertEqual(len(bad_rows), 32)
        self.assertEqual([r['id'] for r in good_rows], [100])
        self.assertIs(bad_rows.complete, False)
        self.assertIs(good_rows.complete, True)


if __name__ == '__main__':
    unittest.main()
