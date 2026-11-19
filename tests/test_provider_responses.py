"""Provider result normalization with synthetic responses; no real accounts."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

webshare = load_module('resources.lib.provider_webshare', (
    'resources.lib.utils_filter', 'resources.lib.utils_theme', 'resources.lib.utils',
))
prehraj = load_module('resources.lib.provider_prehrajto', (
    'resources.lib.utils_filter', 'resources.lib.utils_theme',
    'resources.lib.play_mail', 'resources.lib.utils_files', 'resources.lib.utils',
))


class WebshareResponsesTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(webshare.Webshare)
        self.client.addon = MagicMock()
        self.client.addon.getSetting.side_effect = lambda key: {
            'webshare_search_limit': '64', 'webshare_category': 'VIDEO',
            'webshare_sort': 'RECENT',
        }.get(key, '')
        self.client._get_auth_token = MagicMock(return_value='synthetic-token')
        self.client._auth_token = 'synthetic-token'
        self.client.session = MagicMock()
        self.client.base_url = 'https://example.invalid/api/'
        self.client.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)

    def test_bad_file_metadata_does_not_hide_following_playable_files(self):
        xml = b'''<response><status>OK</status>
          <file><ident>a</ident><name>first.mkv</name><size>100</size></file>
          <file><ident>b</ident><name>bad.mp4</name><size>unknown</size></file>
          <file><ident>missing-name</ident><name/><size/></file>
          <file><ident/><name>unplayable.mkv</name><size>10</size></file>
          <file><ident> c </ident><name>last.avi</name><size>300</size></file>
        </response>'''
        response = SimpleNamespace(status_code=200, content=xml)
        with patch.object(webshare, 'safe_post', return_value=response) as request, \
                patch.object(webshare, 'encode', side_effect=lambda value: value), \
                patch.object(webshare, 'convert_size', side_effect=lambda size: f'{size} bytes'):
            items = self.client.search_sources('show', apply_filters=False)
        self.assertEqual([v['link'] for v in items], ['a', 'b', 'missing-name', 'c'])
        self.assertEqual([v['title'] for v in items], ['first.mkv', 'bad.mp4', 'Neznámý soubor', 'last.avi'])
        self.assertEqual([v['size_str'] for v in items], ['100 bytes', '', '0 bytes', '300 bytes'])
        self.assertEqual(items[0]['extension'], 'mkv')
        self.client.normalize_and_filter.assert_called_once_with(items, apply_filters=False)
        payload = request.call_args.kwargs['data']
        self.assertEqual((payload['what'], payload['limit'], payload['category'], payload['sort']),
                         ('show', 64, 'video', 'recent'))

    def test_invalid_token_is_cleared_and_missing_error_message_is_safe(self):
        invalid = SimpleNamespace(status_code=200, content=b'<response><status>FAIL</status><message>Invalid token</message></response>')
        with patch.object(webshare, 'safe_post', return_value=invalid), patch.object(webshare, 'encode', side_effect=lambda value: value):
            self.assertEqual(self.client.search_sources('x'), [])
        self.client.addon.setSetting.assert_called_once_with('webshare_token', '')
        self.assertIsNone(self.client._auth_token)
        missing = SimpleNamespace(status_code=200, content=b'<response><status>FAIL</status></response>')
        with patch.object(webshare, 'safe_post', return_value=missing), patch.object(webshare, 'encode', side_effect=lambda value: value):
            self.assertEqual(self.client.search_sources('x'), [])

    def test_resolved_stream_url_is_returned_but_never_logged(self):
        secret_url = 'https://stream.example.invalid/secret?token=synthetic-secret'
        response = SimpleNamespace(status_code=200, content=('<response><status>OK</status><link>' + secret_url + '</link></response>').encode())
        with patch.object(webshare, 'safe_post', return_value=response), patch.object(webshare, 'log') as log:
            self.assertEqual(self.client.get_video_link('example-file'), (secret_url, None))
        self.assertNotIn(secret_url, str(log.call_args_list))
        self.assertNotIn('synthetic-secret', str(log.call_args_list))


class PrehrajCatalogueResponsesTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(prehraj.PrehrajTo)
        self.client.addon = MagicMock()
        self.client.addon.getSetting.side_effect = lambda key: {
            'enable_most_watched_cache': 'true', 'max_pages': '5',
            'prehrajto_mark_multi_streams': 'false',
        }.get(key, '')
        self.client.base_url = 'https://example.invalid'
        self.client._access_token = 'synthetic-token'
        self.client.get_premium_cookies = MagicMock(return_value={})
        self.client._get_video_pages = MagicMock(return_value=[
            {'id': 1, 'title': 'First S01E01', 'thumbs': {'global': {'up': '5'}}, 'size': 100},
            {'id': 2, 'title': None, 'name': 'Fallback', 'thumbs': None},
            {'id': 3, 'title': 'Third', 'thumbs': {'global': []}},
            {'title': 'Unplayable', 'id': None},
            {'id': 4, 'title': 'Fourth', 'thumbs': {'global': {'up': 'bad'}}},
        ])

    def test_most_watched_keeps_following_results_and_caches_complete_list(self):
        memory = {}
        with patch.object(prehraj, 'convert_size', side_effect=lambda size: f'{size} bytes'), \
                patch.object(prehraj.cache_manager, 'cache_get', side_effect=lambda section, key: memory.get((section, key))), \
                patch.object(prehraj.cache_manager, 'cache_set', side_effect=lambda section, key, data: memory.update({(section, key): data})):
            items = self.client.get_most_watched()
            self.assertEqual(items, self.client.get_most_watched())
        self.assertEqual([v['title'] for v in items], ['First S01E01', 'Fallback', 'Third', 'Fourth'])
        self.assertEqual([v['likes'] for v in items], [5, 0, 0, 0])
        self.assertTrue(items[0]['is_series'])
        self.assertEqual(items[0]['size_str'], '100 bytes')
        self.client._get_video_pages.assert_called_once()

    def test_history_preserves_all_valid_results_without_series_field(self):
        with patch.object(prehraj, 'convert_size', side_effect=lambda size: f'{size} bytes'):
            items = self.client.get_user_history()
        self.assertEqual([v['id'] for v in items], [1, 2, 3, 4])
        self.assertTrue(all('is_series' not in v for v in items))
        self.client._get_video_pages.assert_called_once_with('profile/videos/watched', require_auth=True)
