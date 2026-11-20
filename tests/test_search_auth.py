"""Provider searches authenticate exactly as often as their contract needs."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
import test_episode_playback as episode_support
import test_provider_responses as provider_support
from kodi_test_support import load_module

prehraj = provider_support.prehraj
actions = episode_support.actions
series_manager = load_module('resources.lib.series_manager', ('resources.lib.utils_filter',))


class SearchAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.addon = MagicMock()
        self.settings = {'email': 'synthetic@example.invalid', 'password': 'synthetic-password',
                         'enable_auto_register': 'true', 'notify_premium_expiry': 'false',
                         'search_pages': '1'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.setSetting.side_effect = lambda key, value: self.settings.__setitem__(key, value)
        self.session = MagicMock()
        self.session.cookies = requests.cookies.RequestsCookieJar()
        self.provider = prehraj.PrehrajTo(self.addon, 1, self.session, None)
        self.provider._auth_loaded = True
        self.provider._auth_credentials = self.provider._credentials()
        self.provider._set_tokens('synthetic-access', 'synthetic-refresh')
        self.provider._fetch_and_set_premium_days = MagicMock(return_value=30)
        self.provider._api_get = MagicMock(return_value=SimpleNamespace(
            status_code=200, json=lambda: {'data': [{'id': 123456, 'title': 'Show S01E01'}]}))
        self.provider.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)

    def test_tmdbhelper_search_checks_premium_once(self):
        with patch.object(actions, 'get_threadpool', return_value=2):
            results = actions._search_providers_parallel('Show S01E01', [self.provider], apply_filters=False)
        self.assertEqual([row['title'] for row in results], ['Show S01E01'])
        self.provider._fetch_and_set_premium_days.assert_called_once()
        self.provider._api_get.assert_called_once()

    def test_series_search_checks_premium_once_per_query(self):
        manager = series_manager.SeriesManager(self.addon, '/tmp', None)
        manager.filter_utils.apply_filters.side_effect = lambda rows, **kwargs: rows
        manager._save_series_data = MagicMock()
        result = manager.search_series('Show', [self.provider])
        self.assertEqual(self.provider._fetch_and_set_premium_days.call_count, 4)
        self.assertEqual(self.provider._api_get.call_count, 4)
        self.assertIn('1', result['seasons'])

    def test_generic_provider_still_receives_prepared_cookies(self):
        cookie_jar = object()
        provider = SimpleNamespace(get_premium_cookies=MagicMock(return_value=cookie_jar),
                                   search_sources=MagicMock(return_value=[{'title': 'Found', 'link': 'x'}]))
        with patch.object(actions, 'get_threadpool', return_value=2):
            results = actions._search_providers_parallel('query', [provider], apply_filters=False)
        self.assertEqual(results[0]['title'], 'Found')
        provider.get_premium_cookies.assert_called_once_with()
        self.assertIs(provider.search_sources.call_args.kwargs['cookies'], cookie_jar)

    def test_auth_failure_and_later_retry_are_still_handled_inside_provider(self):
        self.provider._set_tokens(None, None)
        self.session.post.return_value = SimpleNamespace(status_code=401)
        with patch.object(actions, 'get_threadpool', return_value=2):
            actions._search_providers_parallel('Show S01E01', [self.provider], apply_filters=False)
        self.session.post.assert_called_once()
        with patch.object(actions, 'get_threadpool', return_value=2):
            actions._search_providers_parallel('Show S01E01', [self.provider], apply_filters=False)
        self.assertEqual(self.session.post.call_count, 2)

    def test_expired_token_is_refreshed_before_search(self):
        self.provider._token_needs_refresh = MagicMock(return_value=True)
        self.provider._refresh_access_token = MagicMock(return_value=True)
        with patch.object(actions, 'get_threadpool', return_value=2):
            results = actions._search_providers_parallel('Show S01E01', [self.provider])
        self.assertEqual(len(results), 1)
        self.provider._refresh_access_token.assert_called_once_with()
        self.provider._fetch_and_set_premium_days.assert_called_once()

    def test_expiring_account_still_registers_and_logs_in_before_search(self):
        self.provider._fetch_and_set_premium_days.side_effect = [1, 30]
        self.provider._auto_register_new_account = MagicMock(
            side_effect=lambda: (self.provider.replace_account_credentials('new@example.invalid', 'new-password') or True))
        self.provider._save_auth_state = MagicMock(return_value=True)
        self.session.post.return_value = SimpleNamespace(status_code=200, json=lambda: {
            'data': {'access': 'new-synthetic-access', 'refresh': 'new-synthetic-refresh'}})
        with patch.object(actions, 'get_threadpool', return_value=2):
            results = actions._search_providers_parallel('Show S01E01', [self.provider])
        self.assertEqual(len(results), 1)
        self.provider._auto_register_new_account.assert_called_once()
        self.assertEqual(self.session.post.call_args.kwargs['json'],
                         {'email': 'new@example.invalid', 'password': 'new-password'})
        self.assertEqual(self.provider._access_token, 'new-synthetic-access')


if __name__ == '__main__':
    unittest.main()
