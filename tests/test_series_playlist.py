"""Series autolist and Continue behavior using a controlled Kodi player."""
import json
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_movie_playlist import FakePlayer, FakeWindow, generator


class SeriesPlaylistTests(unittest.TestCase):
    def setUp(self):
        import resources.lib
        self.window = FakeWindow()
        self.player = FakePlayer()
        self.player.path = 'https://example.invalid/S01E01'
        self.player.play = MagicMock()
        self.playlist = MagicMock()
        self.addon = MagicMock()
        self.settings = {'autolist_enable': 'true', 'autolist_items': '3',
                         'continue_episodes_count': '3', 'enable_trakt_scrobbling': 'false',
                         'autolist_source_selection_enable_ser': 'false',
                         'continue_source_selection_enable': 'false',
                         'auto_prediction_enable': 'false', 'auto_prediction_stop_on_no_match': 'false'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.tmdb = MagicMock()
        self.tmdb.get_full_details.return_value = {'id': 42}

        def fetch(path, **kwargs):
            match = re.fullmatch(r'tv/42/season/(\d+)(?:/episode/(\d+))?', path)
            if not match:
                return None
            season = int(match.group(1))
            if match.group(2) is None:
                return {'episodes': [{}, {}]} if season in (1, 2) else None
            episode = int(match.group(2))
            return {'season': season, 'episode': episode} if season in (1, 2) and 1 <= episode <= 2 else None

        self.tmdb._fetch.side_effect = fetch
        self.tmdb._build_metadata_props.side_effect = lambda raw, kind: (
            {'cast_full': ['Show Actor'], 'title': 'Show'} if kind == 'tv' else
            {'cast_full': [], 'title': 'Episode {}'.format(raw['episode']), 'plot': 'Plot'})
        self.actions = MagicMock()
        self.actions._search_providers_parallel.side_effect = lambda query, *a, **kw: [
            {'link': query.split()[-1], 'provider': 'test', 'title': query}]
        self.actions.resolve_video.side_effect = lambda link, *a, **kw: 'https://example.invalid/' + link + '|Header=value'
        self.plugin = MagicMock()
        self.utils = MagicMock()
        self.saved_meta = []
        def store(meta):
            self.saved_meta.append(dict(meta))
            return 'meta-{}-{}'.format(meta['season'], meta['episode'])
        self.utils.store_meta_in_cache.side_effect = store
        self.cache = MagicMock()
        self.cache.cache_get.return_value = None
        self.instance = MagicMock()
        self.instance.tmdb_client = self.tmdb

        def make_item(*args, **kwargs):
            item = MagicMock()
            properties = {}
            item.setProperty.side_effect = lambda key, value: properties.__setitem__(key, value)
            item.getProperty.side_effect = lambda key: properties.get(key, '')
            return item

        def thread_factory(*, target, args=()):
            return SimpleNamespace(start=lambda: target(*args))

        patches = [
            patch.dict(sys.modules, {'resources.lib.plugin': self.plugin, 'resources.lib.actions': self.actions,
                                     'resources.lib.utils': self.utils}),
            patch.object(resources.lib, 'plugin', self.plugin, create=True),
            patch.object(resources.lib, 'actions', self.actions, create=True),
            patch.object(generator, 'cache_manager', self.cache),
            patch.object(generator, '_apply_continue_filters', side_effect=lambda sources, addon: sources),
            patch.object(generator.xbmcgui, 'Window', return_value=self.window),
            patch.object(generator.xbmcgui, 'ListItem', side_effect=make_item),
            patch.object(generator.xbmc, 'Player', return_value=self.player),
            patch.object(generator.xbmc, 'PlayList', return_value=self.playlist),
            patch.object(generator.xbmc, 'sleep'),
            patch.object(generator.xbmcplugin, 'setResolvedUrl'),
            patch.object(generator.threading, 'Thread', side_effect=thread_factory),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_playlist(self, start_from_next=False, use_resolve=True, remaining=None, source_list=None):
        meta = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Show',
                'season': 1, 'episode': 1, 'title': 'Episode 1'}
        if remaining is not None:
            meta['_play_er_queue_remaining'] = remaining
        generator.create_series_playlist(meta, self.addon, None, self.tmdb, 7, self.instance,
                                         start_from_next=start_from_next, use_resolve=use_resolve, max_items=3,
                                         source_list=source_list)

    def test_sequential_rollover_and_metadata_budget(self):
        self.run_playlist()
        self.assertTrue(generator.xbmcplugin.setResolvedUrl.call_args.args[1])
        self.assertEqual([call.args[0] for call in self.playlist.add.call_args_list],
                         ['https://example.invalid/S01E02|Header=value', 'https://example.invalid/S02E01|Header=value'])
        self.assertEqual([(m['season'], m['episode'], m['_play_er_queue_remaining']) for m in self.saved_meta],
                         [(1, 1, 2), (1, 2, 1), (2, 1, 0)])
        records = json.loads(self.window.getProperty('play_er.episode_queue_metadata'))
        self.assertEqual(len(records), 2)
        self.assertEqual(self.window.getProperty('play_er.bg_series_playlist_building'), '')

    def test_continue_advances_once_and_preserves_remaining_limit(self):
        self.player.path = 'https://example.invalid/S01E02'
        self.run_playlist(start_from_next=True, use_resolve=False, remaining=2)
        self.assertEqual([call.args[0] for call in self.playlist.add.call_args_list],
                         ['https://example.invalid/S01E02|Header=value', 'https://example.invalid/S02E01|Header=value'])
        self.assertEqual([(m['season'], m['episode'], m['_play_er_queue_remaining']) for m in self.saved_meta],
                         [(1, 2, 1), (2, 1, 0)])
        generator.xbmcplugin.setResolvedUrl.assert_not_called()
        self.player.play.assert_called_once()

    def test_initial_episode_keeps_watch_later_context(self):
        self.run_playlist(source_list='watch_later')
        resolved_item = generator.xbmcplugin.setResolvedUrl.call_args.args[2]
        self.assertEqual(resolved_item.getProperty('play_er.source_list'), 'watch_later')
        self.assertEqual(resolved_item.getProperty('play_er.media_type'), 'episode')

    def test_unresolvable_episode_does_not_skip_to_later_episode(self):
        original = self.actions.resolve_video.side_effect
        self.actions.resolve_video.side_effect = lambda link, *a, **kw: None if link == 'S01E02' else original(link, *a, **kw)
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.actions.resolve_video.call_args_list], ['S01E01', 'S01E02'])
        self.playlist.add.assert_not_called()

    def test_switch_during_delay_does_not_search_or_add_other_episode(self):
        generator.xbmc.sleep.side_effect = lambda delay: setattr(self.player, 'path', 'https://other.invalid/video')
        self.run_playlist()
        self.assertEqual(self.actions._search_providers_parallel.call_count, 1)
        self.playlist.add.assert_not_called()

    def test_switch_during_source_search_does_not_resolve_episode(self):
        original = self.actions._search_providers_parallel.side_effect
        def search(query, *a, **kw):
            if query.endswith('S01E02'):
                self.player.path = 'https://other.invalid/video'
            return original(query, *a, **kw)
        self.actions._search_providers_parallel.side_effect = search
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.actions.resolve_video.call_args_list], ['S01E01'])
        self.playlist.add.assert_not_called()

    def test_switch_during_episode_metadata_does_not_search(self):
        original = self.tmdb._fetch.side_effect
        def fetch(path, **kwargs):
            if path.endswith('/episode/2'):
                self.player.path = 'https://other.invalid/video'
            return original(path, **kwargs)
        self.tmdb._fetch.side_effect = fetch
        self.run_playlist()
        self.assertEqual(self.actions._search_providers_parallel.call_count, 1)
        self.playlist.add.assert_not_called()

    def test_switch_during_empty_search_does_not_trigger_prediction_handoff(self):
        self.settings.update({'auto_prediction_enable': 'true', 'auto_prediction_stop_on_no_match': 'true'})
        prediction = MagicMock()
        prediction.REFERENCE = 'prediction-reference'
        handoff = MagicMock()
        original = self.actions._search_providers_parallel.side_effect
        def search(query, *args, **kwargs):
            if query.endswith('S01E02'):
                self.player.path = 'https://other.invalid/video'
                return []
            return original(query, *args, **kwargs)
        self.actions._search_providers_parallel.side_effect = search
        with patch.dict(sys.modules, {'resources.lib.utils_auto_prediction': prediction,
                                      'resources.lib.utils_prediction_handoff': handoff}):
            self.run_playlist()
        prediction.select_source.assert_not_called()
        self.playlist.add.assert_not_called()

    def test_switch_during_resolution_does_not_add_to_other_playback(self):
        original = self.actions.resolve_video.side_effect
        def resolve(link, *a, **kw):
            if link == 'S01E02':
                self.player.path = 'https://other.invalid/video'
            return original(link, *a, **kw)
        self.actions.resolve_video.side_effect = resolve
        self.run_playlist()
        self.playlist.add.assert_not_called()

    def test_advancing_to_queued_episode_keeps_sequential_builder_alive(self):
        self.playlist.add.side_effect = lambda url, item: setattr(self.player, 'path', url.split('|', 1)[0])
        self.run_playlist()
        self.assertEqual(self.playlist.add.call_count, 2)

    def test_changed_quality_remains_in_session_when_item_identity_matches(self):
        self.player.path = 'https://example.invalid/alternate-quality'
        self.player.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'meta-1-1',
                                                                'play_er.link': 'S01E01'}.get(key, '')
        self.run_playlist()
        self.assertEqual(self.playlist.add.call_count, 2)

    def test_position_priority_applies_to_start_and_following_episodes(self):
        self.settings.update({'autolist_source_selection_enable_ser': 'true', 'autolist_source_method_ser': 'PODLE POZICE',
                              'autolist_result_priority_ser': '2'})
        self.player.path = 'https://example.invalid/S01E01-second'
        self.actions._search_providers_parallel.side_effect = lambda query, *a, **kw: [
            {'link': 'unused', 'provider': 'test', 'title': 'First'},
            {'link': query.split()[-1] + '-second', 'provider': 'test', 'title': 'Second'}]
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.actions.resolve_video.call_args_list],
                         ['S01E01-second', 'S01E02-second', 'S02E01-second'])

    def test_stopped_audio_and_exhausted_continue_do_not_build(self):
        with patch.object(self.player, 'isPlayingVideo', return_value=False):
            self.run_playlist()
        self.playlist.add.assert_not_called()
        self.actions._search_providers_parallel.reset_mock()
        self.run_playlist(start_from_next=True, use_resolve=False, remaining=0)
        self.actions._search_providers_parallel.assert_not_called()

    def test_failed_thread_start_keeps_successful_resolver_and_clears_flag(self):
        generator.threading.Thread.side_effect = RuntimeError('cannot start')
        self.run_playlist()
        generator.xbmcplugin.setResolvedUrl.assert_called_once()
        self.assertTrue(generator.xbmcplugin.setResolvedUrl.call_args.args[1])
        self.assertEqual(self.window.getProperty('play_er.bg_series_playlist_building'), '')

    def test_interrupted_delay_clears_background_build_flag(self):
        generator.xbmc.sleep.side_effect = RuntimeError('shutdown')
        self.run_playlist()
        self.assertEqual(self.window.getProperty('play_er.bg_series_playlist_building'), '')


if __name__ == '__main__':
    unittest.main()
