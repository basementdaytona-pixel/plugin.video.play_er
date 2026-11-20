"""Distinct unusable pages must not hide later playable Prehraj results."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests
import test_episode_playback as episode_support
import test_provider_responses as provider_support
from resources.lib.preemptive_scope import source_scope

prehraj = provider_support.prehraj
actions = episode_support.actions


def videos(start, count):
    return [{'id': number, 'name': 'Video %d' % number} for number in range(start, start + count)]


def response(rows, status=200):
    return SimpleNamespace(status_code=status, json=lambda: {'data': rows})


class PrehrajPaginationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'search_pages': '5', 'search_ls': '160', 'max_pages': '5',
                         'enable_filtering': 'false', 'enable_most_watched_cache': 'true'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.getSettingBool.return_value = False
        self.client = object.__new__(prehraj.PrehrajTo)
        self.client.addon = self.addon
        self.client.base_url = 'https://example.invalid'
        self.client._access_token = None
        self.client.get_premium_cookies = MagicMock(return_value={})
        self.client.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)
        self.client._api_get = MagicMock()

    def pages(self, pages):
        self.client._api_get.side_effect = [response(page) for page in pages]

    def test_search_continues_after_full_page_without_playable_sources(self):
        self.pages([[{'name': 'Invalid %d' % i} for i in range(32)], videos(100, 2)])
        rows = self.client.search_sources('Show S01E01', apply_filters=False)
        self.assertEqual([row['id'] for row in rows], [100, 101])
        self.assertEqual([call.kwargs['params']['offset'] for call in self.client._api_get.call_args_list], [0, 32])

    def test_distinct_duplicate_only_page_does_not_hide_later_page(self):
        first = videos(1, 32)
        self.pages([first, first[:16] * 2, videos(99, 1)])
        rows = self.client.search_sources('Show S01E01', apply_filters=False)
        self.assertEqual([row['id'] for row in rows], list(range(1, 33)) + [99])
        self.assertEqual(self.client._api_get.call_count, 3)

    def test_unchanged_page_in_different_order_stops_early(self):
        first = videos(1, 32)
        changed_metadata = [dict(row, thumbs={'global': {'up': 20}}) for row in reversed(first)]
        self.pages([first, changed_metadata, videos(99, 1)])
        rows = self.client.search_sources('Show S01E01', apply_filters=False)
        self.assertEqual([row['id'] for row in rows], list(range(1, 33)))
        self.assertEqual(self.client._api_get.call_count, 2)

    def test_catalogue_and_history_continue_after_unusable_page(self):
        self.client._access_token = 'synthetic-access'
        bad = [{'name': 'Invalid %d' % i} for i in range(32)]
        for kind in ('history', 'most_watched'):
            with self.subTest(kind=kind):
                self.client._api_get.reset_mock(side_effect=True)
                self.pages([bad, videos(100, 2)])
                with patch.object(prehraj.cache_manager, 'cache_get', return_value=None), \
                        patch.object(prehraj.cache_manager, 'cache_set'):
                    rows = self.client.get_user_history() if kind == 'history' else self.client.get_most_watched()
                self.assertEqual([row['id'] for row in rows], [100, 101])
                self.assertEqual(self.client._api_get.call_count, 2)

    def test_catalogue_stops_on_repeated_full_page(self):
        first = videos(1, 32)
        self.pages([first, list(reversed(first)), videos(99, 1)])
        rows = self.client._get_video_pages('videos/most-watched')
        self.assertEqual([row['id'] for row in rows], list(range(1, 33)))
        self.assertEqual(self.client._api_get.call_count, 2)

    def test_short_pages_result_limit_and_page_limit_remain_bounded(self):
        self.pages([videos(1, 1)])
        self.assertEqual(len(self.client.search_sources('Show')), 1)
        self.assertEqual(self.client._api_get.call_count, 1)
        self.client._api_get.reset_mock(side_effect=True)
        self.settings['search_ls'] = '32'
        self.pages([videos(1, 32)])
        self.assertEqual(len(self.client.search_sources('Show')), 32)
        self.assertEqual(self.client._api_get.call_count, 1)
        self.client._api_get.reset_mock(side_effect=True)
        self.settings.update(search_ls='160', search_pages='2')
        self.pages([[{'name': 'Invalid %d' % i} for i in range(32)],
                    [{'name': 'Different %d' % i} for i in range(32)]])
        self.assertEqual(self.client.search_sources('Show'), [])
        self.assertEqual(self.client._api_get.call_count, 2)

    def test_later_http_error_does_not_cache_incomplete_catalogue(self):
        self.client._api_get.side_effect = [response(videos(1, 32)), response([], status=500)]
        with patch.object(prehraj.cache_manager, 'cache_get', return_value=None), \
                patch.object(prehraj.cache_manager, 'cache_set') as save:
            self.assertEqual(self.client.get_most_watched(), [])
        save.assert_not_called()

    def test_old_most_watched_cache_is_not_reused(self):
        old_key = 'prehrajto_most_watched_pages_5_multi_1'
        previous = [{'id': 77, 'title': 'Old'}]
        self.client._get_video_pages = MagicMock(return_value=videos(1, 1))
        with patch.object(prehraj.cache_manager, 'cache_get', side_effect=lambda section, key: previous if key == old_key else None), \
                patch.object(prehraj.cache_manager, 'cache_set'):
            rows = self.client.get_most_watched()
        self.assertEqual([row['id'] for row in rows], [1])
        self.client._get_video_pages.assert_called_once()

    def test_old_preemptive_scope_is_not_reused(self):
        self.settings = {'enable_filtering': 'false', 'prehrajto_api_sort': '1', 'prehrajto_api_quality': '1'}
        old_scope = 'b42d90476d67cc51adaf700726c5f34d413a2d45b99c851accc9eb293504b1bd'
        self.assertNotEqual(source_scope(self.addon, SimpleNamespace(_active_provider_name='prehraj.to')), old_scope)

    def test_tmdbhelper_worker_uses_real_http_across_unusable_page(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlsplit(self.path).query)
                offset = int(params['offset'][0])
                seen.append(offset)
                rows = [{'name': 'Invalid %d' % i} for i in range(32)] if offset == 0 else videos(100, 1)
                data = json.dumps({'data': rows}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.client.api_base = 'http://127.0.0.1:%d/api/v2/' % server.server_port
            self.client.headers = {'user-agent': 'synthetic-test'}
            self.client.session = requests.Session()
            self.client._api_get = prehraj.PrehrajTo._api_get.__get__(self.client)
            with patch.object(actions, 'get_threadpool', return_value=2):
                rows = actions._search_providers_parallel('Show S01E01', [self.client], apply_filters=False)
            self.assertEqual([row['id'] for row in rows], [100])
        finally:
            self.client.session.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(seen, [0, 32])


if __name__ == '__main__':
    unittest.main()
