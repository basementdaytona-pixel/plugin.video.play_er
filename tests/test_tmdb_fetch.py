import unittest
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module


tmdb = load_module('resources.lib.tmdb', (
    'resources.lib.sf_context_style', 'resources.lib.ui_builder',
    'resources.lib.tmdb_account', 'resources.lib.utils_theme', 'resources.lib.utils',
))


class FetchTests(unittest.TestCase):
    def test_api_key_sent_to_tmdb_but_omitted_from_debug_log(self):
        client = object.__new__(tmdb.TMDB)
        client.api_key = 'synthetic-secret-key'
        client.language = 'cs-CZ'
        client.base_url = 'https://example.invalid/3'
        client.session = MagicMock()
        client.addon = MagicMock()
        client.addon.getSetting.return_value = 'OFF'
        response = MagicMock()
        response.json.return_value = {'id': 123}
        with patch.object(tmdb, 'safe_get', return_value=response) as request, \
                patch.object(tmdb, 'log') as log:
            self.assertEqual(client._fetch('movie/123', params={'region': 'CZ'}), {'id': 123})
        self.assertEqual(request.call_args.kwargs['params']['api_key'], client.api_key)
        self.assertNotIn(client.api_key, str(log.call_args_list))
        self.assertIn('region', str(log.call_args_list))

    def test_cached_catalogues_respect_language_and_filter_changes(self):
        client = object.__new__(tmdb.TMDB)
        client.api_key, client.language = 'synthetic-key', 'cs-CZ'
        client.base_url, client.session = 'https://example.invalid/3', MagicMock()
        client.addon = MagicMock()
        client.addon.getSetting.return_value = 'OFF'
        storage, store = {}, MagicMock()
        store.window_cache_get.side_effect = storage.get
        store.cache_get.side_effect = lambda folder, key: storage.get(key)
        store.cache_set.side_effect = lambda folder, key, data: storage.update({key: data})
        response = MagicMock()
        response.json.side_effect = lambda: {'results': [
            {'id': 1, 'title': 'Example', 'original_language': 'en'},
            {'id': 2, 'title': 'Example 2', 'original_language': 'ja'}]}
        with patch.object(tmdb, 'cache_manager', store), patch.object(tmdb, 'safe_get', return_value=response) as fetch:
            self.assertEqual(len(client._fetch('movie/popular', cache_key='popular_page_1')['results']), 2)
            client.addon.getSetting.return_value = 'HARD'
            self.assertEqual(len(client._fetch('movie/popular', cache_key='popular_page_1')['results']), 1)
            client.language = 'en-GB'
            client._fetch('movie/popular', cache_key='popular_page_1')
            client._fetch('movie/popular', cache_key='popular_page_1')
            self.assertEqual(fetch.call_count, 3)
            client._fetch('movie/popular', cache_key='popular_page_1', skip_filter=True)
            self.assertEqual(fetch.call_count, 4)

    def test_invalid_filter_mode_uses_soft_default_for_results_and_cache(self):
        client = object.__new__(tmdb.TMDB)
        client.api_key, client.language = 'synthetic-key', 'cs-CZ'
        client.base_url, client.session = 'https://example.invalid/3', MagicMock()
        client.addon = MagicMock()
        for mode in ('unknown', '   ', None, ' soft '):
            with self.subTest(mode=mode):
                client.addon.getSetting.return_value = mode
                response = MagicMock()
                response.json.return_value = {'results': [
                    {'id': 1, 'title': 'Example', 'original_language': 'en'},
                    {'id': 2, 'title': 'Translated', 'original_title': 'Original',
                     'original_language': 'ja', 'genre_ids': [16]},
                    {'id': 3, 'title': 'Original', 'original_title': 'Original',
                     'original_language': 'ja', 'genre_ids': [16]}]}
                store = MagicMock()
                store.window_cache_get.return_value = None
                store.cache_get.return_value = None
                with patch.object(tmdb, 'cache_manager', store), \
                     patch.object(tmdb, 'safe_get', return_value=response):
                    result = client._fetch('movie/popular', cache_key='popular_page_1')
                self.assertEqual([item['id'] for item in result['results']], [1, 2])
                self.assertEqual(store.cache_set.call_args.args[1], 'popular_page_1_cs-CZ_SOFT')
        for mode in ('OFF', 'SOFT', 'HARD'):
            client.addon.getSetting.return_value = ' ' + mode.lower() + ' '
            self.assertEqual(client._cache_variant('key'), 'key_cs-CZ_' + mode)
            self.assertEqual(client._cache_variant('key', skip_filter=True), 'key_cs-CZ_OFF')

    def test_catalogue_errors_are_not_reused_or_cached(self):
        for error in ({'status_code': 34}, {'success': False}):
            for layer in ('response', 'disk', 'window'):
                with self.subTest(error=error, layer=layer):
                    client = object.__new__(tmdb.TMDB)
                    client.api_key, client.language = 'synthetic-key', 'cs-CZ'
                    client.base_url, client.session = 'https://example.invalid/3', MagicMock()
                    client.addon = MagicMock()
                    client.addon.getSetting.return_value = 'OFF'
                    store = MagicMock()
                    store.window_cache_get.return_value = error if layer == 'window' else None
                    store.cache_get.return_value = error if layer == 'disk' else None
                    valid = {'results': [], 'page': 1}
                    response = MagicMock()
                    response.json.return_value = error if layer == 'response' else valid
                    with patch.object(tmdb, 'cache_manager', store), \
                         patch.object(tmdb, 'safe_get', return_value=response) as request:
                        result = client._fetch('movie/popular', cache_key='popular_page_1')
                    request.assert_called_once()
                    if layer == 'response':
                        self.assertEqual(result, error)
                        store.cache_set.assert_not_called()
                        store.window_cache_set.assert_not_called()
                    else:
                        self.assertEqual(result, valid)
                        store.cache_set.assert_called_once()
                        self.assertEqual(store.cache_set.call_args.args[-1], valid)
                        store.window_cache_set.assert_called_once()

    def test_detail_cache_uses_same_variant_as_fetch(self):
        client = object.__new__(tmdb.TMDB)
        client.api_key, client.language = 'synthetic-key', 'cs-CZ'
        client.base_url, client.session = 'https://example.invalid/3', MagicMock()
        client.addon = MagicMock()
        client.addon.getSetting.return_value = 'OFF'
        storage, store = {}, MagicMock()
        store.cache_get.side_effect = lambda folder, key: storage.get(key)
        store.cache_set.side_effect = lambda folder, key, data: storage.update({key: data})
        response = MagicMock()
        response.json.side_effect = lambda: {'id': 1, 'credits': {}}
        with patch.object(tmdb, 'cache_manager', store), patch.object(tmdb, 'safe_get', return_value=response) as fetch:
            client.get_full_details('movie', 1)
            client.get_full_details('movie', 1)
            client.get_full_details('movie', 1, lang='en-GB')
            client.get_full_details('movie', 1, lang='en-GB')
            self.assertEqual(fetch.call_count, 2)
