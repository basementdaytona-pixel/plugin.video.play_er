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
