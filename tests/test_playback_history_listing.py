"""History remains navigable when TMDB data is absent or partially invalid."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_episode_playback as support

actions = support.actions


class PlaybackHistoryListingTests(unittest.TestCase):
    def setUp(self):
        self.show = {'media_type': 'episode', 'tmdb_id': 42, 'tv_show_title': 'Show',
                     'season': 0, 'episode': 1, 'title': 'Special', 'poster': 'poster.jpg'}
        self.movie = {'media_type': 'movie', 'tmdb_id': 99, 'title': 'Film', 'poster': 'film.jpg'}
        self.history = [{'meta': dict(self.show), 'link': 'episode-a'},
                        {'meta': dict(self.movie), 'link': 'movie-a'}]
        self.cache = MagicMock()
        self.cache.user_data_get.side_effect = lambda key: self.history
        self.cache.cache_get.return_value = None
        self.client = MagicMock()
        self.client._fetch.return_value = None
        self.instance = SimpleNamespace(handle=7, addon=MagicMock(), tmdb_client=self.client)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(actions, 'cache_manager', self.cache))
        stack.enter_context(patch.object(actions, 'get_threadpool', return_value=1))
        stack.enter_context(patch.object(actions, '_get_context_menu', return_value=[]))
        stack.enter_context(patch.object(actions, '_sf_cm_items', return_value=[]))
        stack.enter_context(patch.object(actions, 'get_url', side_effect=lambda **kw: str(kw)))
        stack.enter_context(patch.object(actions, 'set_view_mode'))
        self.items = stack.enter_context(patch.object(actions.xbmcgui, 'ListItem'))
        self.add = stack.enter_context(patch.object(actions.xbmcplugin, 'addDirectoryItem'))
        self.end = stack.enter_context(patch.object(actions.xbmcplugin, 'endOfDirectory'))

    def test_history_lists_movies_and_shows_without_tmdb_client(self):
        self.instance.tmdb_client = None
        actions.playback_history(self.instance)
        self.assertEqual([c.kwargs['label'] for c in self.items.call_args_list], ['Show', 'Film'])
        self.assertEqual(self.add.call_count, 2)
        tag = self.items.return_value.getVideoInfoTag.return_value
        self.assertEqual([c.args[0] for c in tag.setMediaType.call_args_list], ['tvshow', 'movie'])
        tag.setUniqueIDs.assert_any_call({'tmdb': '42'})
        tag.setUniqueIDs.assert_any_call({'tmdb': '99'})
        self.items.return_value.setArt.assert_any_call({'poster': 'poster.jpg'})
        self.items.return_value.setArt.assert_any_call({'poster': 'film.jpg'})
        self.end.assert_called_once_with(7, succeeded=True, cacheToDisc=False)

    def test_episode_history_renders_without_tmdb_client(self):
        self.instance.tmdb_client = None
        actions.playback_show_history({'show_title': 'Show', 'tmdb_id': '42'}, self.instance)
        self.assertEqual(self.items.call_args.kwargs['label'], 'S00E01 - Special')
        self.items.return_value.getVideoInfoTag.return_value.setSeason.assert_called_once_with(0)
        self.items.return_value.getVideoInfoTag.return_value.setEpisode.assert_called_once_with(1)
        self.add.assert_called_once()
        self.end.assert_called_once_with(7)

    def test_specials_load_episode_metadata_and_deduplicate_same_episode(self):
        self.history.insert(1, {'meta': dict(self.show), 'link': 'episode-b'})
        actions.playback_show_history({'show_title': 'Show', 'tmdb_id': '42'}, self.instance)
        self.client._fetch.assert_called_once_with('tv/42/season/0/episode/1',
                                                   params={'append_to_response': 'credits'}, cache_key='tv_42_s0_e1',
                                                   _cache_validator=actions._history_tmdb_details)
        self.assertEqual(self.add.call_count, 2)

    def test_duplicate_movies_load_tmdb_metadata_once_without_merging_history(self):
        self.history.append({'meta': dict(self.movie), 'link': 'movie-b'})
        actions.playback_history(self.instance)
        calls = [call.args[0] for call in self.client._fetch.call_args_list]
        self.assertEqual(calls.count('movie/99'), 1)
        self.assertEqual(calls.count('tv/42'), 1)
        self.assertEqual(self.add.call_count, 3)

    def test_bad_records_do_not_hide_valid_history_and_are_not_deleted(self):
        valid = list(self.history)
        self.history[:] = [None, {'meta': None}, 'invalid', {'meta': dict(self.movie)}, *valid]
        actions.playback_history(self.instance)
        self.assertEqual(self.add.call_count, 3)
        self.assertEqual(len(self.history), 6)
        self.cache.user_data_set.assert_not_called()
        self.cache.user_data_update.assert_not_called()

    def test_bad_episode_records_do_not_hide_specials(self):
        self.history[:] = [None, {'meta': None}, {'meta': dict(self.show, season='invalid'), 'link': 'bad'},
                           {'meta': dict(self.show)}, {'meta': dict(self.show), 'link': 'good'}]
        actions.playback_show_history({'show_title': 'Show', 'tmdb_id': '42'}, self.instance)
        self.assertEqual(self.add.call_count, 2)
        self.assertEqual([c.kwargs['label'] for c in self.items.call_args_list], ['S00E01 - Special'] * 2)
        self.assertEqual(len(self.history), 5)
        self.cache.user_data_update.assert_not_called()

    def test_error_payload_is_not_used_as_tmdb_metadata(self):
        self.client._fetch.return_value = {'status_code': 34, 'success': False}
        actions.playback_history(self.instance)
        self.client._build_metadata_props.assert_not_called()
        self.assertEqual([c.kwargs['label'] for c in self.items.call_args_list], ['Show', 'Film'])

    def test_error_episode_payload_falls_back_to_saved_metadata(self):
        self.client._fetch.return_value = {'status_code': 34, 'success': False}
        actions.playback_show_history({'show_title': 'Show', 'tmdb_id': '42'}, self.instance)
        self.client._build_metadata_props.assert_not_called()
        self.assertEqual(self.items.call_args.kwargs['label'], 'S00E01 - Special')

    def test_failing_tmdb_renderer_keeps_history_accessible(self):
        self.client.fill_list_item.side_effect = ValueError('bad metadata')
        actions.playback_history(self.instance)
        self.assertEqual(self.add.call_count, 2)
        self.items.return_value.getVideoInfoTag.return_value.setTitle.assert_any_call('Film')

    def test_empty_tmdb_metadata_keeps_saved_titles(self):
        self.client._fetch.return_value = {'name': 'unusable'}
        self.client._build_metadata_props.return_value = {}
        actions.playback_history(self.instance)
        self.assertEqual([c.kwargs['label'] for c in self.items.call_args_list], ['Show', 'Film'])
        self.items.reset_mock()
        actions.playback_show_history({'show_title': 'Show', 'tmdb_id': '42'}, self.instance)
        self.assertEqual(self.items.call_args.kwargs['label'], 'S00E01 - Special')


if __name__ == '__main__':
    unittest.main()
