"""TMDBHelper source search reuses localization only within the same request."""
import sys
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_episode_playback as support

actions = support.actions


class TMDBHelperLocalizedSearchTests(unittest.TestCase):
    def setUp(self):
        self.addon = MagicMock()
        self.settings = {'trakt_prefer_czech_search': True}
        self.addon.getSettingBool.side_effect = lambda key: self.settings.get(key, False)
        self.addon.getSetting.return_value = ''
        self.client = MagicMock()
        self.client.get_full_details.return_value = {'name': 'Original Show', 'title': 'Original Film'}
        self.client._fetch.return_value = {'name': 'Episode Name'}
        self.client._build_metadata_props.side_effect = lambda data, kind: (
            {'title': 'Episode Name'} if kind == 'episode' else
            {'title': 'Original Show'} if kind == 'tv' else
            {'title': 'Original Film', 'year': '2023'})
        self.client.get_localized_title.return_value = 'Český název'
        self.manager = MagicMock()
        self.manager.get_providers_to_search.return_value = [object()]
        self.instance = SimpleNamespace(addon=self.addon, tmdb_client=self.client,
                                        provider_manager=self.manager, handle=7)
        self.saved = {}
        self.rows = [{'provider': 'prehraj.to', 'link': 'synthetic', 'title': 'Source'}]
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.store = MagicMock(side_effect=self._store)
        utils = MagicMock(store_meta_in_cache=self.store)
        modules = {'xbmc': actions.xbmc, 'xbmcgui': actions.xbmcgui,
                   'xbmcplugin': actions.xbmcplugin, 'xbmcvfs': MagicMock(),
                   'resources.lib.utils': utils, 'resources.lib.utils_logging': MagicMock(),
                   'resources.lib.utils_notification': MagicMock(),
                   'resources.lib.ui_builder': MagicMock()}
        self.stack.enter_context(patch.dict(sys.modules, modules))
        self.stack.enter_context(patch.object(actions, 'store_meta_in_cache', self.store))
        self.stack.enter_context(patch.object(actions, 'get_meta_from_cache', side_effect=lambda key: dict(self.saved)))
        self.stack.enter_context(patch.object(actions, 'cache_manager', MagicMock(cache_get=MagicMock(return_value=None))))
        self.stack.enter_context(patch.object(actions, '_get_context_menu', return_value=[]))
        self.stack.enter_context(patch.object(actions, '_sf_cm_items', return_value=[]))
        self.stack.enter_context(patch.object(actions, 'encode', side_effect=lambda value: value))
        self.search = self.stack.enter_context(patch.object(actions, '_search_providers_parallel', return_value=self.rows))
        self.stack.enter_context(patch.object(actions.xbmcplugin, 'endOfDirectory'))

    def _store(self, meta):
        self.saved = dict(meta)
        return 'synthetic-meta'

    def bridge(self, media_type):
        params = {'tmdb_id': '42', 'media_type': media_type, 'mode': 'search'}
        if media_type == 'episode':
            params.update(season='1', episode='2')
        actions.tmdbh_bridge(params, self.instance)
        self.assertTrue(self.search.called, 'TMDBHelper bridge failed before source search')

    def test_movie_uses_one_localization_and_preserves_search_and_metadata(self):
        self.bridge('movie')
        self.client.get_localized_title.assert_called_once_with('movie', '42', 'cs')
        self.assertEqual(self.search.call_args.args[0], 'Český název 2023')
        self.assertEqual(self.saved['title'], 'Český název')

    def test_episode_uses_one_localization_and_keeps_episode_title(self):
        self.bridge('episode')
        self.client.get_localized_title.assert_called_once_with('tv', '42', 'cs')
        self.assertEqual(self.search.call_args.args[0], 'Český název S01E02')
        self.assertEqual(self.saved['tv_show_title'], 'Český název')
        self.assertEqual(self.saved['title'], 'Episode Name')
        self.assertTrue(self.saved['_play_er_tmdbh_source_search'])

    def test_failed_first_lookup_is_retried(self):
        self.client.get_localized_title.side_effect = [None, 'Druhý pokus']
        self.bridge('episode')
        self.assertEqual(self.client.get_localized_title.call_count, 2)
        self.assertEqual(self.search.call_args.args[0], 'Druhý pokus S01E02')

    def test_missing_titles_keep_original_query(self):
        self.client.get_localized_title.return_value = None
        self.bridge('movie')
        self.assertEqual(self.client.get_localized_title.call_count, 2)
        self.assertEqual(self.search.call_args.args[0], 'Original Film 2023')

    def test_disabled_preference_skips_localization(self):
        self.settings['trakt_prefer_czech_search'] = False
        self.bridge('movie')
        self.client.get_localized_title.assert_not_called()
        self.assertEqual(self.search.call_args.args[0], 'Original Film 2023')

    def test_standalone_source_list_performs_its_own_localization(self):
        self.saved = {'tmdb_id': '42', 'media_type': 'movie', 'title': 'Original Film', 'year': '2023'}
        actions.find_and_list_sources_multi({'meta': 'synthetic-meta'}, self.instance)
        self.client.get_localized_title.assert_called_once_with('movie', '42', 'cs')
        self.assertEqual(self.search.call_args.args[0], 'Český název 2023')

    def test_empty_result_still_tries_english_title(self):
        self.client.get_full_details.side_effect = [
            {'title': 'Original Film'}, {'title': 'English Film'}]
        self.search.side_effect = [[], self.rows]
        self.bridge('movie')
        self.assertEqual([call.args[0] for call in self.search.call_args_list],
                         ['Český název 2023', 'English Film 2023'])
        self.client.get_full_details.assert_any_call('movie', '42', lang='en-US')


if __name__ == '__main__':
    unittest.main()
