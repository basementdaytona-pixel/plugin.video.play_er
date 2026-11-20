"""Exercise movie autolist lifecycle with deterministic Kodi and provider stubs."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module


generator = load_module('resources.lib.generator', (
    'resources.lib.utils_filter', 'resources.lib.utils_theme', 'resources.lib.stream_state',
))


class FakeWindow:
    def __init__(self):
        self.properties = {}

    def getProperty(self, key):
        return self.properties.get(key, '')

    def setProperty(self, key, value):
        self.properties[key] = value

    def clearProperty(self, key):
        self.properties.pop(key, None)


class FakePlayer:
    def __init__(self):
        self.path = 'https://example.invalid/start'
        self.playing = True
        self.item = MagicMock()
        self.item.getProperty.return_value = ''

    def isPlaying(self):
        return self.playing

    def isPlayingVideo(self):
        return self.playing

    def getPlayingFile(self):
        return self.path

    def getPlayingItem(self):
        return self.item


class MoviePlaylistTests(unittest.TestCase):
    def setUp(self):
        import resources.lib
        self.window = FakeWindow()
        self.player = FakePlayer()
        self.progress = MagicMock()
        self.playlist = MagicMock()
        self.addon = MagicMock()
        self.settings = {'movie_autoplay_enable': 'true', 'movie_autoplay_erems': '3',
                         'autolist_source_selection_enable': 'false', 'autolist_source_method': '',
                         'autolist_result_priority': '1', 'enable_trakt_scrobbling': 'false'}
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.tmdb = MagicMock()
        self.tmdb.get_full_details.side_effect = lambda kind, ident: {'id': ident}
        self.tmdb._build_metadata_props.side_effect = lambda raw, kind: {
            'tmdb_id': raw['id'], 'media_type': 'movie', 'title': 'Film {}'.format(raw['id']), 'year': '2020'}
        self.tmdb.get_recommendations_raw.return_value = []
        self.actions = MagicMock()
        self.actions._search_providers_parallel.side_effect = lambda query, *args, **kwargs: [
            {'link': 'start' if query.startswith('Start ') else query.split()[1],
             'provider': 'test', 'title': 'Source'}]
        self.actions.resolve_video.side_effect = lambda link, *args, **kwargs: (
            ('https://example.invalid/' + link + '|Header=value', None) if kwargs.get('return_view_identity')
            else 'https://example.invalid/' + link + '|Header=value')
        self.plugin = MagicMock()
        self.plugin.get_entry_key.side_effect = lambda entry: '{}_{}'.format(
            entry['meta'].get('media_type', 'movie'), entry['meta'].get('tmdb_id'))
        self.utils = MagicMock()
        self.utils.store_meta_in_cache.return_value = 'meta-key'
        self.filter_module = MagicMock()
        self.cache = MagicMock()
        self.cache.user_data_get.return_value = []
        self.instance = MagicMock()

        def thread_factory(*, target, args):
            return SimpleNamespace(start=lambda: target(*args))

        patches = [
            patch.dict(sys.modules, {'resources.lib.plugin': self.plugin, 'resources.lib.actions': self.actions,
                                     'resources.lib.utils': self.utils, 'resources.lib.utils_filter': self.filter_module}),
            patch.object(resources.lib, 'plugin', self.plugin, create=True),
            patch.object(resources.lib, 'actions', self.actions, create=True),
            patch.object(generator, 'cache_manager', self.cache),
            patch.object(generator.xbmcgui, 'Window', return_value=self.window),
            patch.object(generator.xbmcgui, 'DialogProgress', return_value=self.progress),
            patch.object(generator.xbmcgui, 'ListItem', side_effect=lambda *a, **kw: MagicMock()),
            patch.object(generator.xbmc, 'Player', return_value=self.player),
            patch.object(generator.xbmc, 'PlayList', return_value=self.playlist),
            patch.object(generator.xbmc, 'sleep'),
            patch.object(generator.xbmcplugin, 'setResolvedUrl'),
            patch.object(generator.threading, 'Thread', side_effect=thread_factory),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_playlist(self, handle=7, source_list=None):
        meta = {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Start', 'year': '2020', 'cast_full': ['A']}
        generator.create_movie_playlist(meta, self.addon, None, self.tmdb, handle, self.instance, source_list=source_list)

    def test_existing_lock_is_not_released_by_a_second_invocation(self):
        self.window.setProperty('player.movie_playlist_active', 'true')
        self.run_playlist()
        self.assertEqual(self.window.getProperty('player.movie_playlist_active'), 'true')
        self.actions._search_providers_parallel.assert_not_called()

    def test_progress_closes_if_no_sources_or_search_fails(self):
        self.actions._search_providers_parallel.return_value = []
        self.actions._search_providers_parallel.side_effect = None
        self.run_playlist()
        self.progress.close.assert_called_once()
        self.assertFalse(generator.xbmcplugin.setResolvedUrl.call_args.args[1])
        self.assertEqual(self.window.getProperty('player.movie_playlist_active'), '')
        self.progress.reset_mock()
        self.actions._search_providers_parallel.side_effect = RuntimeError('offline')
        with self.assertRaises(RuntimeError):
            self.run_playlist()
        self.progress.close.assert_called_once()
        self.assertEqual(self.window.getProperty('player.movie_playlist_active'), '')

    def test_direct_start_replaces_old_queue_with_selected_movie(self):
        self.settings['movie_autoplay_erems'] = '1'
        self.player.play = MagicMock()
        self.run_playlist(handle=0, source_list='watch_later')
        self.playlist.clear.assert_called_once()
        self.playlist.add.assert_called_once()
        url, item = self.playlist.add.call_args.args
        self.assertEqual(url, 'https://example.invalid/start|Header=value')
        item.setProperty.assert_any_call('play_er.source_list', 'watch_later')
        item.setProperty.assert_any_call('play_er.media_type', 'movie')
        self.player.play.assert_called_once_with(self.playlist)
        generator.xbmcplugin.setResolvedUrl.assert_not_called()

    def test_initial_movie_attaches_selected_source_subtitles(self):
        with patch.object(generator, 'attach_subtitles') as attach, \
             patch.object(generator, 'publish_active_streams') as publish:
            self.run_playlist()
        first = generator.xbmcplugin.setResolvedUrl.call_args.args[2]
        attach.assert_any_call(first, 'start', provider='test')
        first.setProperty.assert_any_call('play_er.provider', 'test')
        publish.assert_called_once_with('start', provider='test')

    def test_movie_playlist_carries_each_resolved_view_identity(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        self.actions.resolve_video.side_effect = lambda link, *a, **kw: (
            'https://example.invalid/' + link + '|Header=value', (link, 'binding-' + link))
        self.run_playlist()
        first = generator.xbmcplugin.setResolvedUrl.call_args.args[2]
        first.setProperty.assert_any_call('play_er.view_video_id', 'start')
        first.setProperty.assert_any_call('play_er.view_binding', 'binding-start')
        queued = self.playlist.add.call_args.args[1]
        queued.setProperty.assert_any_call('play_er.view_video_id', '3')
        queued.setProperty.assert_any_call('play_er.view_binding', 'binding-3')
        self.assertEqual(self.window.getProperty('play_er.expected_view_binding'), 'binding-start')

    def test_movie_start_and_queued_recommendation_publish_owned_identity(self):
        import json
        from resources.lib.playback_identity import EXPECTED_OWNER, EXPECTED_URL, stream_key
        self.window.setProperty('play_er.monitor_owner', 'movie-owner')
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        self.run_playlist()
        self.assertEqual(self.window.getProperty(EXPECTED_OWNER), 'movie-owner')
        self.assertEqual(self.window.getProperty(EXPECTED_URL), stream_key('https://example.invalid/start'))
        self.assertEqual(json.loads(self.window.getProperty('play_er.current_meta'))['tmdb_id'], 1)
        records = json.loads(self.window.getProperty('play_er.episode_queue_metadata'))
        queued = records[stream_key('https://example.invalid/3')]
        self.assertEqual((queued['owner'], queued['media_type'], queued['meta']['tmdb_id']),
                         ('movie-owner', 'movie', 3))
        self.assertEqual(queued['provider'], 'test')

    def test_failed_direct_start_does_not_clear_existing_queue(self):
        self.actions.resolve_video.side_effect = lambda *a, **kw: (None, None) if kw.get('return_view_identity') else None
        self.run_playlist(handle=0)
        self.playlist.clear.assert_not_called()
        self.playlist.add.assert_not_called()

    def test_history_duplicates_and_missing_sources_do_not_block_later_recommendations(self):
        self.cache.user_data_get.return_value = [{'meta': {'media_type': 'movie', 'tmdb_id': 2}}]
        self.tmdb.get_recommendations_raw.return_value = [None, {}, {'id': 1}, {'id': 2}, {'id': 3}, {'id': 3}, {'id': 4}, {'id': 5}]
        original_search = self.actions._search_providers_parallel.side_effect
        self.actions._search_providers_parallel.side_effect = lambda query, *args, **kwargs: (
            [] if query.startswith('Film 4 ') else original_search(query, *args, **kwargs))
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.playlist.add.call_args_list],
                         ['https://example.invalid/3|Header=value', 'https://example.invalid/5|Header=value'])
        self.assertEqual(self.tmdb.get_full_details.call_count, 3)
        self.assertEqual(self.window.getProperty('play_er.bg_playlist_active'), '')
        self.progress.close.assert_called_once()

    def test_queue_can_continue_after_advancing_to_a_recommendation(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}, {'id': 5}]
        self.playlist.add.side_effect = lambda url, item: setattr(self.player, 'path', url.split('|', 1)[0])
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.playlist.add.call_args_list],
                         ['https://example.invalid/3|Header=value', 'https://example.invalid/5|Header=value'])

    def test_changed_stream_url_is_accepted_when_item_identity_matches(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        self.player.path = 'https://example.invalid/alternate-quality'
        self.player.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'meta-key', 'play_er.link': 'start'}.get(key, '')
        self.run_playlist()
        self.playlist.add.assert_called_once()

    def test_item_identity_remains_usable_when_current_url_is_unavailable(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        self.player.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'meta-key', 'play_er.link': 'start'}.get(key, '')
        with patch.object(self.player, 'getPlayingFile', side_effect=RuntimeError('temporarily unavailable')):
            self.run_playlist()
        self.playlist.add.assert_called_once()

    def test_source_priority_applies_to_start_and_recommendation(self):
        self.settings.update({'autolist_source_selection_enable': 'true', 'autolist_source_method': 'PODLE POZICE',
                              'autolist_result_priority': '2'})
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        self.player.path = 'https://example.invalid/start-second'
        self.actions._search_providers_parallel.side_effect = lambda query, *args, **kwargs: [
            {'link': 'unused', 'provider': 'test', 'title': 'First'},
            {'link': 'start-second' if query.startswith('Start ') else '3-second', 'provider': 'test', 'title': 'Second'}]
        self.run_playlist()
        self.assertEqual([call.args[0] for call in self.actions.resolve_video.call_args_list], ['start-second', '3-second'])
        self.assertEqual(self.playlist.add.call_args.args[0], 'https://example.invalid/3-second|Header=value')

    def test_audio_or_stopped_playback_is_not_extended(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        with patch.object(self.player, 'isPlayingVideo', return_value=False):
            self.run_playlist()
        self.playlist.add.assert_not_called()
        self.tmdb.get_recommendations_raw.assert_not_called()

    def test_invalid_recommendations_response_finishes_without_adding_items(self):
        self.tmdb.get_recommendations_raw.return_value = {'status_code': 7, 'success': False}
        self.run_playlist()
        self.playlist.add.assert_not_called()
        self.assertEqual(self.window.getProperty('play_er.bg_playlist_active'), '')

    def test_switch_during_delay_does_not_modify_another_playlist(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        generator.xbmc.sleep.side_effect = lambda duration: setattr(self.player, 'path', 'https://other.invalid/video')
        self.run_playlist()
        self.tmdb.get_recommendations_raw.assert_not_called()
        self.playlist.add.assert_not_called()

    def test_switch_during_recommendation_details_does_not_search_sources(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        details = self.tmdb.get_full_details.side_effect

        def switch_on_details(kind, tmdb_id):
            result = details(kind, tmdb_id)
            if tmdb_id == 3:
                self.player.path = 'https://other.invalid/video'
            return result

        self.tmdb.get_full_details.side_effect = switch_on_details
        self.run_playlist()
        self.assertEqual(self.actions._search_providers_parallel.call_count, 1)
        self.assertEqual(self.actions.resolve_video.call_count, 1)
        self.playlist.add.assert_not_called()
        self.assertEqual(self.window.getProperty('play_er.bg_playlist_active'), '')

    def test_switch_during_source_search_does_not_resolve_recommendation(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        search = self.actions._search_providers_parallel.side_effect

        def switch_on_search(query, *args, **kwargs):
            results = search(query, *args, **kwargs)
            if not query.startswith('Start '):
                self.player.path = 'https://other.invalid/video'
            return results

        self.actions._search_providers_parallel.side_effect = switch_on_search
        self.run_playlist()
        self.assertEqual(self.actions._search_providers_parallel.call_count, 2)
        self.assertEqual(self.actions.resolve_video.call_count, 1)
        self.playlist.add.assert_not_called()
        self.assertEqual(self.window.getProperty('play_er.bg_playlist_active'), '')

    def test_switch_during_source_resolution_does_not_add_to_new_playback(self):
        self.tmdb.get_recommendations_raw.return_value = [{'id': 3}]
        def resolve(link, *args, **kwargs):
            if link == '3':
                self.player.path = 'https://other.invalid/video'
            url = 'https://example.invalid/' + link + '|Header=value'
            return (url, None) if kwargs.get('return_view_identity') else url
        self.actions.resolve_video.side_effect = resolve
        self.run_playlist()
        self.playlist.add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
