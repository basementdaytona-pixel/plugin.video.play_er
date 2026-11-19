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


def client_with_seasons(seasons):
    client = MagicMock()
    client._fetch.side_effect = lambda path, **kw: {
        'episodes': [{'episode_number': number} for number in seasons[int(path.rsplit('/', 1)[-1])]]
    }
    client.get_full_details.return_value = {'seasons': [
        {'season_number': season, 'episode_count': len(numbers)}
        for season, numbers in seasons.items()
    ]}
    return client


class EpisodeSequenceTests(unittest.TestCase):
    def test_non_contiguous_episode_numbers(self):
        client = client_with_seasons({1: [1, 3, 7]})
        self.assertEqual(generator._next_episode_coordinates(42, 1, 3, client), (1, 7))

    def test_specials_continue_within_season_zero(self):
        client = client_with_seasons({0: [1, 2], 1: [1, 2]})
        self.assertEqual(generator._next_episode_coordinates(42, 0, 1, client), (0, 2))
        self.assertEqual(generator._next_episode_coordinates(42, 0, 2, client), (1, 1))

    def test_rollover_skips_empty_and_missing_seasons(self):
        client = client_with_seasons({1: [1, 2], 3: [], 5: [2, 4]})
        self.assertEqual(generator._next_episode_coordinates(42, 1, 2, client), (5, 2))
        self.assertIsNone(generator._next_episode_coordinates(42, 5, 4, client))

    def test_unknown_or_error_metadata_never_invents_successor(self):
        for data in (None, {}, {'status_code': 34}, {'episodes': None}):
            with self.subTest(data=data):
                client = MagicMock()
                client._fetch.return_value = data
                self.assertIsNone(generator._next_episode_coordinates(42, 1, 2, client))
        client._fetch.side_effect = OSError('offline')
        self.assertIsNone(generator._next_episode_coordinates(42, 1, 2, client))

    def test_smart_play_uses_shared_sequence_for_history(self):
        client = client_with_seasons({0: [1, 2], 1: [1, 2]})
        history = [{'meta': {'tmdb_id': 42, 'media_type': 'episode', 'season': 0, 'episode': 1}}]
        with patch.dict('sys.modules', {'resources.lib.generator': generator}):
            self.assertEqual(actions._tmdbh_next_episode(client.get_full_details(), history, '42', client), (0, 2))

    def test_smart_play_without_history_uses_first_actual_regular_episode(self):
        client = client_with_seasons({0: [1], 2: [3, 4]})
        with patch.dict('sys.modules', {'resources.lib.generator': generator}):
            self.assertEqual(actions._tmdbh_next_episode(client.get_full_details(), [], '42', client), (2, 3))

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


class BackgroundPlaylistTests(unittest.TestCase):
    def run_loader(self, change_during_resolve=False, changed_before_load=False):
        addon = MagicMock()
        addon.getSetting.return_value = 'false'
        addon.getSetting.side_effect = lambda key: 'true' if key == 'autolist_enable' else 'false'
        win = generator.xbmcgui.Window.return_value
        win.getProperty.return_value = ''
        player = generator.xbmc.Player.return_value
        player.isPlayingVideo.return_value = True
        player.getPlayingFile.return_value = 'https://example.invalid/first'
        player.getPlayingItem.return_value.getProperty.return_value = ''
        client = MagicMock()
        client.get_full_details.return_value = {'name': 'Series'}
        client._build_metadata_props.return_value = {'title': 'Episode', 'cast_full': []}
        client._fetch.return_value = {'name': 'Episode 2'}
        plugin = MagicMock()
        meta = {'media_type': 'episode', 'tmdb_id': 42, 'season': 1, 'episode': 1, 'tv_show_title': 'Series'}
        current = json.dumps(meta)
        def current_meta(key):
            return current if key == 'play_er.current_meta' else ''
        win.getProperty.side_effect = current_meta
        utils = MagicMock()
        utils.store_meta_in_cache.return_value = 'id'
        fake_actions = MagicMock()
        def resolve(*args, **kwargs):
            nonlocal current
            if change_during_resolve and fake_actions.resolve_video.call_count > 1:
                current = json.dumps(dict(meta, tmdb_id=99))
                player.getPlayingFile.return_value = 'https://example.invalid/other'
            return 'https://example.invalid/resolved'
        fake_actions.resolve_video.side_effect = resolve
        dependencies = {'resources.lib.utils': utils, 'resources.lib.actions': fake_actions}
        import resources.lib
        with patch.dict('sys.modules', dependencies), patch.object(resources.lib, 'actions', fake_actions, create=True), \
                patch.object(generator, '_next_episode_coordinates', side_effect=lambda tid, season, episode, client: (season, episode + 1)), \
                patch.object(generator, '_search_continue_sources', return_value=[{'link': 'source', 'title': 'source'}]), \
                patch.object(generator.threading, 'Thread') as thread:
            generator.xbmc.PlayList.return_value.add.reset_mock()
            generator.create_series_playlist(meta, addon, None, client, 1, plugin,
                                             start_from_next=True, max_items=2)
            current = json.dumps(dict(meta, episode=2))
            loader = thread.call_args.kwargs['target']
            if changed_before_load:
                current = json.dumps(dict(meta, tmdb_id=99))
            loader()
            return generator.xbmc.PlayList.return_value.add.call_count

    def test_loader_adds_successor_for_current_episode(self):
        self.assertEqual(self.run_loader(), 1)

    def test_loader_stops_if_playback_changed_during_delay(self):
        self.assertEqual(self.run_loader(changed_before_load=True), 0)

    def test_loader_stops_if_playback_changed_during_source_resolution(self):
        self.assertEqual(self.run_loader(change_during_resolve=True), 0)


if __name__ == '__main__':
    unittest.main()
