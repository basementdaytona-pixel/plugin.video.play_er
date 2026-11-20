import json
import unittest
from unittest.mock import MagicMock, patch

from kodi_test_support import ROOT, load_module


generator = load_module('resources.lib.generator', (
    'resources.lib.utils_filter', 'resources.lib.utils_theme',
    'resources.lib.stream_state',
))
actions = load_module('resources.lib.actions', (
    'resources.lib.sf_context_style', 'resources.lib.utils_files',
    'resources.lib.trakt', 'resources.lib.stream_state', 'resources.lib.ui_builder',
    'resources.lib.utils_filter', 'resources.lib.utils_theme', 'resources.lib.utils',
))


class EpisodeSequenceTests(unittest.TestCase):
    def test_continue_uses_next_episode_when_season_metadata_is_unavailable(self):
        client = MagicMock()
        client._fetch.return_value = None
        self.assertEqual(generator._next_episode_coordinates(42, 1, 3, client), (1, 4))
        client._fetch.side_effect = OSError('offline')
        self.assertEqual(generator._next_episode_coordinates(42, 1, 3, client), (1, 4))

    def test_continue_rolls_over_and_preserves_last_episode_behavior(self):
        client = MagicMock()
        client._fetch.side_effect = [{'episodes': [1, 2]}, {'episodes': [1]}]
        self.assertEqual(generator._next_episode_coordinates(42, 1, 2, client), (2, 1))
        client._fetch.side_effect = [{'episodes': [1, 2]}, None]
        self.assertIsNone(generator._next_episode_coordinates(42, 1, 2, client))

    def test_numbered_season_uses_last_episode_number_not_row_count(self):
        client = MagicMock()
        season = {'episodes': [{'episode_number': 1}, {'episode_number': 3}, {'episode_number': 4}]}
        client._fetch.side_effect = lambda path: season if path.endswith('/season/1') else {'episodes': [{'episode_number': 1}]}
        self.assertEqual(generator._next_episode_coordinates(42, 1, 3, client), (1, 4))
        self.assertEqual(generator._next_episode_coordinates(42, 1, 4, client), (2, 1))

    def test_partially_numbered_season_falls_back_to_next_episode(self):
        client = MagicMock()
        client._fetch.side_effect = lambda path: {'episodes': [{'episode_number': 1}, {}, {'episode_number': 3}]} if path.endswith('/season/1') else None
        self.assertEqual(generator._next_episode_coordinates(42, 1, 3, client), (1, 4))
        client._fetch.assert_called_once()

    def test_smart_play_uses_existing_history_contract(self):
        show = {'seasons': [{'season_number': 1, 'episode_count': 2},
                            {'season_number': 2, 'episode_count': 1}]}
        history = [{'meta': {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2}}]
        self.assertEqual(actions._tmdbh_next_episode(show, history, '42'), (2, 1))
        self.assertEqual(actions._tmdbh_next_episode(show, [], '42'), (1, 1))

    def test_every_bundled_player_is_installed(self):
        from resources.lib.utils_tmdbhelper import PLAYER_FILES
        self.assertEqual(set(PLAYER_FILES), {path.name for path in (ROOT / 'resources/custom/players').glob('*.json')})
        for filename in PLAYER_FILES:
            data = json.loads((ROOT / 'resources/custom/players' / filename).read_text())
            self.assertEqual(data['plugin'], 'plugin.video.play_er')


class TMDBHelperEndpointTests(unittest.TestCase):
    def test_error_episode_response_finishes_resolver_without_searching(self):
        plugin = MagicMock()
        plugin.handle = 7
        plugin.addon.getSettingBool.return_value = False
        plugin.tmdb_client.get_full_details.return_value = {'name': 'Series'}
        plugin.tmdb_client._fetch.return_value = {'status_code': 34, 'success': False}
        modules = {name: MagicMock() for name in ('xbmc', 'xbmcgui', 'xbmcvfs', 'xbmcplugin',
                   'resources.lib.utils_logging', 'resources.lib.utils_notification', 'resources.lib.utils')}
        with patch.dict('sys.modules', modules), patch.object(actions, '_search_providers_parallel') as search:
            actions.tmdbh_bridge({'tmdb_id': '42', 'media_type': 'episode',
                                  'season': '0', 'episode': '2', 'mode': 'play'}, plugin)
        search.assert_not_called()
        plugin.tmdb_client._fetch.assert_called_once_with('tv/42/season/0/episode/2',
                                                         params={'append_to_response': 'credits'})
        resolved = modules['xbmcplugin'].setResolvedUrl
        resolved.assert_called_once()
        self.assertEqual(resolved.call_args.args[:2], (7, False))

    def test_invalid_coordinates_do_not_reach_tmdb(self):
        plugin = MagicMock()
        plugin.handle = 7
        modules = {name: MagicMock() for name in ('xbmc', 'xbmcgui', 'xbmcvfs', 'xbmcplugin',
                   'resources.lib.utils_logging', 'resources.lib.utils_notification', 'resources.lib.utils')}
        with patch.dict('sys.modules', modules):
            actions.tmdbh_bridge({'tmdb_id': '42', 'media_type': 'episode',
                                  'season': '1', 'episode': '{episode}', 'mode': 'play'}, plugin)
        plugin.tmdb_client.get_full_details.assert_not_called()
        self.assertEqual(modules['xbmcplugin'].setResolvedUrl.call_args.args[:2], (7, False))


if __name__ == '__main__':
    unittest.main()
