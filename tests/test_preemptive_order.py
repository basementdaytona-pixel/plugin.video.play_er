"""Preemptive source caches must honor the current provider priority."""
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import resources.lib
import test_episode_playback as episode_support
from test_movie_playlist import generator
from resources.lib.source_order import order_sources
from resources.lib.preemptive_scope import source_scope

actions = episode_support.actions


class PreemptiveOrderTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'provider': 'prehraj.to', 'link': 'p1', 'title': 'P1'},
                     {'provider': 'webshare.cz', 'link': 'w1', 'title': 'W1'},
                     {'provider': 'prehraj.to', 'link': 'p2', 'title': 'P2'},
                     {'provider': 'webshare.cz', 'link': 'w2', 'title': 'W2'}]
        self.cache = MagicMock()
        self.cache.cache_get.return_value = {'timestamp': time.time(), 'results': self.rows}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: 'WEBSHARE.CZ' if key == 'multi_provider_sort' else ''
        self.addon.getSettingBool.return_value = False
        self.instance = MagicMock()
        self.instance.addon = self.addon
        self.instance.tmdb_client = None
        self.instance.provider_manager.get_providers_to_search.return_value = []
        self.cache.cache_get.return_value['source_scope'] = source_scope(self.addon, self.instance.provider_manager)

    def test_continue_cache_uses_current_priority_without_mutating_cache(self):
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': actions}), \
             patch.object(resources.lib, 'actions', actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual([x['link'] for x in result], ['w1', 'w2', 'p1', 'p2'])
        self.assertEqual([x['link'] for x in self.rows], ['p1', 'w1', 'p2', 'w2'])

    def test_priority_can_change_back_without_reordering_cached_rows(self):
        self.cache.cache_get.return_value['results'] = [self.rows[1], self.rows[3], self.rows[0], self.rows[2]]
        self.addon.getSetting.side_effect = lambda key: 'PREHRAJ.TO' if key == 'multi_provider_sort' else ''
        with patch.object(generator, 'cache_manager', self.cache), \
             patch.object(generator, '_apply_continue_source_filters', side_effect=lambda rows, addon: rows), \
             patch.dict(sys.modules, {'resources.lib.actions': actions}), \
             patch.object(resources.lib, 'actions', actions, create=True):
            result = generator._search_continue_sources('Show S01E02', self.addon, self.instance, 42, 1, 2)
        self.assertEqual([x['link'] for x in result], ['p1', 'p2', 'w1', 'w2'])
        self.assertEqual([x['link'] for x in self.cache.cache_get.return_value['results']], ['w1', 'w2', 'p1', 'p2'])

    def test_unknown_provider_remains_in_stable_nonpreferred_order(self):
        rows = self.rows + [{'provider': 'other', 'link': 'o'}]
        self.assertEqual([x['link'] for x in order_sources(rows, 'WEBSHARE.CZ')],
                         ['w1', 'w2', 'p1', 'p2', 'o'])

    def test_tmdbhelper_cached_source_listing_uses_current_priority(self):
        meta = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}
        filters = MagicMock()
        filters.apply_filters.side_effect = lambda rows, **kwargs: rows
        proxy = SimpleNamespace(_apply_continue_filters=lambda rows, addon: rows)
        with patch.object(actions, 'cache_manager', self.cache), \
             patch.object(actions, 'get_meta_from_cache', return_value=meta), \
             patch.object(actions, 'FilterUtils', return_value=filters), \
             patch.object(actions, '_get_context_menu', return_value=[]), \
             patch.object(actions.xbmcgui, 'ListItem') as item, \
             patch.dict(sys.modules, {'resources.lib.generator': proxy}):
            actions.find_and_list_sources_multi({'meta': 'key'}, self.instance, tmdbh_search=True)
        self.assertEqual([call.kwargs['label'] for call in item.call_args_list], ['W1', 'W2', 'P1', 'P2'])

    def test_preemptive_search_uses_configured_priority(self):
        self.instance.provider_manager.get_providers_to_search.return_value = [object()]
        with patch.object(actions, '_search_providers_parallel', return_value=self.rows) as search, \
             patch.object(resources.lib, 'cache_manager', self.cache, create=True), \
             patch.dict(sys.modules, {'xbmc': actions.xbmc, 'resources.lib.cache_manager': self.cache,
                                      'resources.lib.utils_logging': MagicMock()}):
            actions._perform_pre_emptive_search({'tmdb_id': 42, 'season': 1, 'episode': 2, 'tv_show_title': 'Show'}, self.instance)
        self.assertEqual(search.call_args.kwargs['sort_priority'], 'WEBSHARE.CZ')


if __name__ == '__main__':
    unittest.main()
