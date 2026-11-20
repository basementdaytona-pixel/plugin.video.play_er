"""Preemptive caches cannot override current provider configuration."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import resources.lib
import test_episode_playback as episode_support
import test_atomic_user_data as atomic_support
from test_movie_playlist import generator
from resources.lib.preemptive_scope import source_scope

actions = episode_support.actions


class PreemptiveScopeTests(unittest.TestCase):
    def setUp(self):
        self.cached = [{'provider': 'prehraj.to', 'link': 'old', 'title': 'Old'}]
        self.fresh = [{'provider': 'webshare.cz', 'link': 'new', 'title': 'New'}]
        self.cache = MagicMock()
        self.cache.cache_get.return_value = {'timestamp': time.time(), 'results': self.cached, 'query': 'Show S01E02'}
        self.addon = MagicMock()
        self.settings = {'active_provider': 'webshare.cz', 'multi_provider_sort': 'WEBSHARE.CZ'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.getSettingBool.side_effect = lambda key: self.settings.get(key, False) is True
        self.instance = MagicMock(addon=self.addon)
        self.instance.tmdb_client = None
        self.instance.provider_manager._active_provider_name = 'webshare.cz'
        self.instance.provider_manager.get_providers_to_search.return_value = [object()]

    def test_continue_researches_legacy_cache_from_other_provider(self):
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        fake_actions._search_providers_parallel.assert_called_once()

    def test_matching_scope_uses_cache_without_search(self):
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.cached)
        fake_actions._search_providers_parallel.assert_not_called()

    def test_scope_tracks_provider_server_options_and_account_identity(self):
        manager = self.instance.provider_manager
        baseline = source_scope(self.addon, manager)
        self.settings['multi_provider_sort'] = 'PREHRAJ.TO'
        self.settings['filter_global'] = 'local filter'
        self.assertEqual(source_scope(self.addon, manager), baseline)
        for key, value in [('webshare_category', 'AUDIO'), ('webshare_sort', 'RECENT'),
                           ('webshare_search_limit', '96'), ('webshare_username', 'synthetic-account'),
                           ('enable_multi_provider', True), ('enable_filtering', 'false')]:
            with self.subTest(setting=key):
                self.settings[key] = value
                self.assertNotEqual(source_scope(self.addon, manager), baseline)
                del self.settings[key]
        manager._active_provider_name = 'prehraj.to'
        self.assertNotEqual(source_scope(self.addon, manager), baseline)
        baseline = source_scope(self.addon, manager)
        for key, value in [('email', 'synthetic@example.invalid'), ('search_pages', '4'),
                           ('search_ls', '96'), ('prehrajto_api_sort', '1'),
                           ('prehrajto_api_quality', '2'), ('prehrajto_mark_multi_streams', 'true')]:
            with self.subTest(setting=key):
                self.settings[key] = value
                self.assertNotEqual(source_scope(self.addon, manager), baseline)
                del self.settings[key]

    def test_webshare_password_or_token_change_invalidates_scope(self):
        manager = self.instance.provider_manager
        self.settings.update(webshare_token='synthetic-token', webshare_password='first-password')
        baseline = source_scope(self.addon, manager)
        self.settings['webshare_password'] = 'second-password'
        self.assertNotEqual(source_scope(self.addon, manager), baseline)
        self.settings['webshare_password'] = 'first-password'
        self.settings['webshare_token'] = 'new-synthetic-token'
        self.assertNotEqual(source_scope(self.addon, manager), baseline)

    def test_search_setting_change_invalidates_matching_cache(self):
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)
        self.settings['webshare_category'] = 'AUDIO'
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        fake_actions._search_providers_parallel.assert_called_once()

    def test_enabling_multi_provider_invalidates_single_provider_cache(self):
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)
        self.settings['enable_multi_provider'] = True
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        fake_actions._search_providers_parallel.assert_called_once()

    def test_expired_matching_scope_still_researches(self):
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)
        self.cache.cache_get.return_value['timestamp'] = time.time() - 1801
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        fake_actions._search_providers_parallel.assert_called_once()

    def test_writer_discards_result_if_settings_change_during_search(self):
        def search(*args, **kwargs):
            self.settings['webshare_category'] = 'AUDIO'
            return self.fresh
        with patch.object(actions, '_search_providers_parallel', side_effect=search), \
             patch.object(resources.lib, 'cache_manager', self.cache, create=True), \
             patch.dict(sys.modules, {'xbmc': actions.xbmc, 'resources.lib.cache_manager': self.cache,
                                      'resources.lib.utils_logging': MagicMock()}):
            actions._perform_pre_emptive_search({'tmdb_id': 42, 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}, self.instance)
        self.cache.cache_set.assert_not_called()

    def test_writer_records_only_configuration_digest(self):
        self.settings.update(webshare_username='synthetic-account', webshare_password='synthetic-password',
                             webshare_token='synthetic-token')
        with patch.object(actions, '_search_providers_parallel', return_value=self.fresh), \
             patch.object(resources.lib, 'cache_manager', self.cache, create=True), \
             patch.dict(sys.modules, {'xbmc': actions.xbmc, 'resources.lib.cache_manager': self.cache,
                                      'resources.lib.utils_logging': MagicMock()}):
            actions._perform_pre_emptive_search({'tmdb_id': 42, 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}, self.instance)
        payload = self.cache.cache_set.call_args.args[2]
        self.assertEqual(payload['source_scope'], source_scope(self.addon, self.instance.provider_manager))
        for value in ('synthetic-account', 'synthetic-password', 'synthetic-token'):
            self.assertNotIn(value, str(payload))

    def test_real_sqlite_cache_reuses_matching_scope_then_researches_after_change(self):
        cache = atomic_support.cache
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with tempfile.TemporaryDirectory() as directory, \
             patch.multiple(cache, CACHE_DB_PATH=str(Path(directory) / 'cache.db'), DB_TYPE='SQLite', SQLITE_INITIALIZED=False), \
             patch.object(generator, 'cache_manager', cache), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            cache.clear_ram_cache()
            key = 'preemptive_42_S01E02'
            cache.cache_set('PREEMPTIVE_SOURCES', key, {'timestamp': time.time(), 'results': self.cached,
                            'query': 'Show S01E02',
                            'source_scope': source_scope(self.addon, self.instance.provider_manager)})
            cache.clear_ram_cache()
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
            self.assertEqual(result, self.cached)
            fake_actions._search_providers_parallel.assert_not_called()
            self.settings['webshare_category'] = 'AUDIO'
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
            self.assertEqual(result, self.fresh)
            fake_actions._search_providers_parallel.assert_called_once()
            cache.clear_ram_cache()

    def test_tmdbhelper_researches_cache_with_mismatched_scope(self):
        self.cache.cache_get.return_value['source_scope'] = 'old-scope'
        meta = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}
        filters = MagicMock()
        filters.apply_filters.side_effect = lambda rows, **kwargs: rows
        with patch.object(actions, 'cache_manager', self.cache), \
             patch.object(actions, 'get_meta_from_cache', return_value=meta), \
             patch.object(actions, 'FilterUtils', return_value=filters), \
             patch.object(actions, '_search_providers_parallel', return_value=self.fresh) as search, \
             patch.object(actions, '_get_context_menu', return_value=[]), \
             patch.object(actions.xbmcgui, 'ListItem') as item, \
             patch.dict(sys.modules, {'resources.lib.generator': SimpleNamespace(_apply_continue_filters=lambda rows, addon: rows)}):
            actions.find_and_list_sources_multi({'meta': 'key'}, self.instance, tmdbh_search=True)
        search.assert_called_once()
        self.assertEqual([call.kwargs['label'] for call in item.call_args_list], ['New'])

    def test_continue_researches_when_cached_query_has_another_title(self):
        self.cache.cache_get.return_value.update(
            source_scope=source_scope(self.addon, self.instance.provider_manager),
            query='Other Show S01E02')
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        self.assertEqual(fake_actions._search_providers_parallel.call_args.args[0], 'Show S01E02')

    def test_continue_researches_legacy_cache_without_query(self):
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)
        del self.cache.cache_get.return_value['query']
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual(result, self.fresh)
        fake_actions._search_providers_parallel.assert_called_once()

    def test_sqlite_cached_query_must_match_requested_title(self):
        cache = atomic_support.cache
        fake_actions = SimpleNamespace(_search_providers_parallel=MagicMock(return_value=self.fresh))
        with tempfile.TemporaryDirectory() as directory, \
             patch.multiple(cache, CACHE_DB_PATH=str(Path(directory) / 'cache.db'), DB_TYPE='SQLite', SQLITE_INITIALIZED=False), \
             patch.object(generator, 'cache_manager', cache), \
             patch.object(generator, '_apply_continue_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': fake_actions}), \
             patch.object(resources.lib, 'actions', fake_actions, create=True):
            cache.clear_ram_cache()
            cache.cache_set('PREEMPTIVE_SOURCES', 'preemptive_42_S01E02',
                            {'timestamp': time.time(), 'results': self.cached, 'query': 'Other Show S01E02',
                             'source_scope': source_scope(self.addon, self.instance.provider_manager)})
            cache.clear_ram_cache()
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
            self.assertEqual(result, self.fresh)
            self.assertEqual(fake_actions._search_providers_parallel.call_args.args[0], 'Show S01E02')
            cache.clear_ram_cache()

    def test_tmdbhelper_researches_when_localized_title_differs_from_cached_query(self):
        self.cache.cache_get.return_value.update(
            source_scope=source_scope(self.addon, self.instance.provider_manager),
            query='Original Show S01E02')
        meta = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'tv_show_title': 'Original Show'}
        self.settings['trakt_prefer_czech_search'] = True
        self.instance.tmdb_client = MagicMock()
        self.instance.tmdb_client.get_localized_title.return_value = 'Místní seriál'
        filters = MagicMock()
        filters.apply_filters.side_effect = lambda rows, **kwargs: rows
        with patch.object(actions, 'cache_manager', self.cache), \
             patch.object(actions, 'get_meta_from_cache', return_value=meta), \
             patch.object(actions, 'FilterUtils', return_value=filters), \
             patch.object(actions, '_search_providers_parallel', return_value=self.fresh) as search, \
             patch.object(actions, '_get_context_menu', return_value=[]), \
             patch.object(actions.xbmcgui, 'ListItem'), \
             patch.dict(sys.modules, {'resources.lib.generator': SimpleNamespace(_apply_continue_filters=lambda rows, addon: rows)}):
            actions.find_and_list_sources_multi({'meta': 'key'}, self.instance, tmdbh_search=True)
        self.assertEqual(search.call_args.args[0], 'Místní seriál S01E02')


if __name__ == '__main__':
    unittest.main()
