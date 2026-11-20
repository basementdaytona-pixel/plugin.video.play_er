"""Exercise settings with Kodi's native type restrictions and changing values."""
import sys
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import ROOT, load_module

settings = load_module('resources.lib.utils_settings')
account = load_module('resources.lib.tmdb_account', (
    'resources.lib.telegram', 'resources.lib.utils', 'resources.lib.utils_theme',
))
gemini = load_module('resources.lib.gemini', (
    'resources.lib.sf_context_style', 'resources.lib.monitor_orchestrator',
    'resources.lib.utils_theme', 'resources.lib.utils',
))


class NativeSettings:
    definitions = {s.get('id'): s for s in ET.parse(ROOT / 'resources/settings.xml').iter('setting')}

    def __init__(self, **values):
        self.values = values

    def getSetting(self, key):
        return self.values.get(key, self.definitions[key].findtext('default') or '')

    def getSettingString(self, key):
        if self.definitions[key].get('type') != 'string':
            raise TypeError('Invalid setting type')
        return self.getSetting(key)


class LanguageTests(unittest.TestCase):
    def test_catalogue_language_preserves_explicit_and_auto_preferences(self):
        kodi = MagicMock()
        with patch.dict(sys.modules, {'xbmc': kodi}):
            for stored, expected in [('cs_CZ', 'cs-CZ'), ('en_GB', 'en-GB'), ('en_US', 'en-US')]:
                self.assertEqual(settings.get_tmdb_language(NativeSettings(tmdb_language=stored)), expected)
            for code, expected in [('cs', 'cs-CZ'), ('en', 'en-US'), ('nl', 'nl-NL'), ('', 'en-US')]:
                kodi.getLanguage.return_value = code
                self.assertEqual(settings.get_tmdb_language(NativeSettings(tmdb_language='auto')), expected)

    def test_account_cache_changes_with_language_and_account(self):
        addon = NativeSettings(tmdb_language='cs_CZ')
        cache, responses = {}, []
        store = MagicMock()
        store.window_cache_get.side_effect = cache.get
        store.cache_get.return_value = None
        store.window_cache_set.side_effect = lambda key, value: cache.update({key: value})
        identity = {'session_id': 'synthetic-session', 'id': 17}

        def fetch(*args, **kwargs):
            language = kwargs['params']['language']
            responses.append(language)
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'results': [{'title': language}]})

        with patch.object(account, 'ADDON', addon), patch.object(account, 'cache_manager', store), \
                patch.object(account, 'load_account_data', return_value=identity), \
                patch.object(account, 'safe_get', side_effect=fetch):
            self.assertEqual(account.tmdb_get_watchlist()['results'][0]['title'], 'cs-CZ')
            addon.values['tmdb_language'] = 'en_GB'
            self.assertEqual(account.tmdb_get_watchlist()['results'][0]['title'], 'en-GB')
            account.tmdb_get_watchlist()
            identity['id'] = 18
            account.tmdb_get_watchlist()
        self.assertEqual(responses, ['cs-CZ', 'en-GB', 'en-GB'])

    def test_account_lists_and_recommendations_use_resolved_auto_language(self):
        addon, kodi = NativeSettings(tmdb_language='auto'), MagicMock()
        kodi.getLanguage.return_value = 'cs'
        store, fetch = MagicMock(), MagicMock()
        store.window_cache_get.return_value = None
        store.cache_get.return_value = None
        fetch.return_value.json.return_value = {'results': [{'id': 42}]}
        with patch.dict(sys.modules, {'xbmc': kodi}), patch.object(account, 'ADDON', addon), \
                patch.object(account, 'cache_manager', store), patch.object(account, 'safe_get', fetch), \
                patch.object(account, 'load_account_data', return_value={'session_id': 'synthetic', 'id': 1}):
            account.tmdb_get_user_list_items(4)
            account.tmdb_get_recommendations()
        self.assertEqual(fetch.call_count, 3)
        self.assertTrue(all(call.kwargs['params']['language'] == 'cs-CZ' for call in fetch.call_args_list))


class AISettingsTests(unittest.TestCase):
    def test_integer_preferences_affect_reason_limit_and_cache_identity(self):
        addon = NativeSettings(ai_reason_words='48', gemini_temperature='3')
        plugin = SimpleNamespace(addon=addon)
        self.assertEqual(gemini._reason_words(plugin), 48)
        original = gemini._request_key(plugin, 'synthetic prompt')
        addon.values['gemini_temperature'] = '9'
        self.assertNotEqual(original, gemini._request_key(plugin, 'synthetic prompt'))


class NumericSettingsTests(unittest.TestCase):
    def test_non_finite_values_use_default_with_and_without_bounds(self):
        for raw in ('NaN', 'nan', 'inf', '-inf', 'Infinity', '1e9999', '-1e9999'):
            for bounds in ({}, {'min_val': 1, 'max_val': 100}):
                with self.subTest(raw=raw, bounds=bounds):
                    addon = NativeSettings(trakt_page_limit=raw)
                    self.assertEqual(settings.get_setting_float_with_bounds(
                        addon, 'trakt_page_limit', default=20, **bounds), 20.0)
                    self.assertEqual(settings.get_setting_int_with_bounds(
                        addon, 'trakt_page_limit', default=20, **bounds), 20)

    def test_finite_values_preserve_decimal_conversion_clamping_and_defaults(self):
        for raw, expected in [('12.5', 12.5), ('0', 1), ('200', 100),
                              ('', 20), ('broken', 20)]:
            with self.subTest(raw=raw):
                addon = NativeSettings(trakt_page_limit=raw)
                self.assertEqual(settings.get_setting_float_with_bounds(
                    addon, 'trakt_page_limit', 20, 1, 100), expected)
                self.assertEqual(settings.get_setting_int_with_bounds(
                    addon, 'trakt_page_limit', 20, 1, 100), int(expected))
