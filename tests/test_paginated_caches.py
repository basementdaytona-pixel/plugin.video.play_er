"""Exercise cache reuse across real menu handlers with synthetic API responses."""
import sys
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

from kodi_test_support import load_module

trakt = load_module('resources.lib.trakt', (
    'resources.lib.sf_context_style', 'resources.lib.monitor_orchestrator',
    'resources.lib.stream_state', 'resources.lib.utils_files',
    'resources.lib.utils_theme', 'resources.lib.utils',
))
provider = load_module('resources.lib.provider_prehrajto', (
    'resources.lib.utils_filter', 'resources.lib.utils_theme',
    'resources.lib.play_mail', 'resources.lib.utils_files', 'resources.lib.utils',
))


class TraktPaginationTests(unittest.TestCase):
    def test_page_size_cache_variants_cover_paginated_menus(self):
        cases = [
            ('trakt_trending', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_anticipated', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_popular_lists', {}, 'trakt_page_limit'),
            ('trakt_popular_lists', {'list_id': '42'}, 'trakt_page_limit'),
            ('trakt_list_items', {'list_id': '42'}, 'trakt_page_limit'),
            ('trakt_genres', {'category': 'movies', 'genre': 'action', 'year': '2020'}, 'trakt_page_limit'),
            ('trakt_recommended', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_watchlist', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_favorites', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_watched_history', {'category': 'movies'}, 'trakt_page_limit'),
            ('trakt_user_history', {'username': 'example', 'media_type': 'movies'}, 'trakt_social_feed_limit'),
        ]
        for name, params, setting in cases:
            with self.subTest(route=name, params=params):
                self.check_route(name, params, setting)

    def check_route(self, name, params, setting):
        values = {'trakt_client_id': 'test-client', 'trakt_access_token': 'synthetic-token',
                  'trakt_page_limit': '10', 'trakt_social_feed_limit': '30'}
        addon = MagicMock()
        addon.getSetting.side_effect = lambda key: values.get(key, '')
        addon.getSettingBool.return_value = False
        cached, requested, rendered = {}, [], []

        def request(*args, **kwargs):
            url = next(value for value in args if isinstance(value, str) and value.startswith('http'))
            query = parse_qs(urlparse(url).query)
            limit, page = int(query['limit'][0]), int(query['page'][0])
            requested.append((limit, page))
            movie = {'title': str(limit), 'ids': {'tmdb': 42, 'trakt': 42}}
            item = {'type': 'movie', 'movie': movie, 'ids': movie['ids'],
                    'list': {'name': str(limit), 'ids': {'trakt': 42}}, 'title': str(limit)}
            response = MagicMock(status_code=200, headers={'X-Pagination-Page': str(page)})
            response.json.return_value = [item]
            return response

        fake_tmdb = MagicMock()
        with patch.dict(sys.modules, {'resources.lib.tmdb': fake_tmdb}), \
                patch.object(trakt, 'load_trakt_cache', side_effect=lambda key, **kw: cached.get((kw.get('section', 'TRAKT'), key))), \
                patch.object(trakt, 'save_trakt_cache', side_effect=lambda key, value, **kw: cached.update({(kw.get('section', 'TRAKT'), key): value})), \
                patch.object(trakt, 'safe_get', side_effect=request), \
                patch.object(trakt, 'handle_trakt_401', side_effect=request), \
                patch.object(trakt, 'trakt_get_headers', return_value={}), \
                patch.object(trakt, 'process_and_add_item', side_effect=lambda *a, **kw: rendered.append(a)), \
                patch.object(trakt, 'add_next_page_item'):
            fn = getattr(trakt, name)
            fn(dict(params, page=1), addon, 1, MagicMock())
            fn(dict(params, page=1), addon, 1, MagicMock())
            initial = int(values[setting])
            values[setting] = '50'
            fn(dict(params, page=1), addon, 1, MagicMock())
            fn(dict(params, page=2), addon, 1, MagicMock())
        self.assertEqual(requested, [(initial, 1), (50, 1), (50, 2)])
        self.assertGreater(len(rendered) + trakt.xbmcplugin.addDirectoryItem.call_count, 0)


class ProviderCacheTests(unittest.TestCase):
    def test_most_watched_cache_separates_multi_stream_marker(self):
        instance = object.__new__(provider.PrehrajTo)
        values = {'enable_most_watched_cache': 'true', 'max_pages': '2',
                  'prehrajto_mark_multi_streams': 'true'}
        instance.addon = MagicMock()
        instance.addon.getSetting.side_effect = lambda key: values.get(key, '')
        instance._access_token, instance.base_url = None, 'https://example.invalid'
        instance.get_premium_cookies = MagicMock()
        instance._get_video_pages = MagicMock(return_value=[
            {'id': 42, 'title': 'Film', 'link': 'https://example.invalid/42', 'extension': 'mkv'}])
        cached = {}
        with patch.object(provider.cache_manager, 'cache_get', side_effect=lambda section, key: cached.get((section, key))), \
                patch.object(provider.cache_manager, 'cache_set', side_effect=lambda section, key, value: cached.update({(section, key): value})):
            self.assertEqual(instance.get_most_watched()[0]['title'], '► Film')
            self.assertEqual(instance.get_most_watched()[0]['title'], '► Film')
            values['prehrajto_mark_multi_streams'] = 'false'
            self.assertEqual(instance.get_most_watched()[0]['title'], 'Film')
            self.assertEqual(instance.get_most_watched()[0]['title'], 'Film')
        self.assertEqual(instance._get_video_pages.call_count, 2)
