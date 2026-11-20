"""Exercise history metadata through the actual TMDB and SQLite cache boundary."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_atomic_user_data as atomic
import test_tmdb_fetch as tmdb_support

actions, cache, tmdb = atomic.actions, atomic.cache, tmdb_support.tmdb


class HistoryTMDBCacheTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.multiple(cache, CACHE_DB_PATH=str(Path(directory) / 'history.db'),
                                           DB_TYPE='SQLite', SQLITE_INITIALIZED=False))
        cache.clear_ram_cache()
        stack.enter_context(patch.object(actions, 'cache_manager', cache))
        stack.enter_context(patch.object(tmdb, 'cache_manager', cache))
        stack.enter_context(patch.object(actions, 'get_threadpool', return_value=2))
        stack.enter_context(patch.object(actions, '_get_context_menu', return_value=[]))
        stack.enter_context(patch.object(actions, '_sf_cm_items', return_value=[]))
        stack.enter_context(patch.object(actions, 'get_url', return_value='plugin://test'))
        stack.enter_context(patch.object(actions, 'set_view_mode'))
        self.created = []
        self.items = stack.enter_context(patch.object(actions.xbmcgui, 'ListItem', side_effect=self.make_item))
        stack.enter_context(patch.object(actions.xbmcplugin, 'addDirectoryItem'))
        stack.enter_context(patch.object(actions.xbmcplugin, 'setContent'))
        stack.enter_context(patch.object(actions.xbmcplugin, 'endOfDirectory'))
        self.requests = stack.enter_context(patch.object(tmdb, 'safe_get', side_effect=self.respond))
        self.client = object.__new__(tmdb.TMDB)
        self.client.api_key, self.client.language = 'synthetic-key', 'cs-CZ'
        self.client.base_url, self.client.image_base_url = 'https://example.invalid/3', 'https://example.invalid/img/'
        self.client.session, self.client.addon = MagicMock(), MagicMock()
        self.client.addon.getSetting.return_value = 'OFF'
        self.client.get_genres = lambda media_type: {}
        self.instance = SimpleNamespace(handle=7, addon=MagicMock(), tmdb_client=self.client)
        self.show = {'media_type': 'episode', 'tmdb_id': 42, 'tv_show_title': 'Saved show',
                     'season': 0, 'episode': 1, 'title': 'Saved special'}
        self.movie = {'media_type': 'movie', 'tmdb_id': 99, 'title': 'Saved film'}
        self.history = [{'meta': dict(self.show), 'link': 'episode-a'},
                        {'meta': dict(self.show), 'link': 'episode-b'},
                        {'meta': dict(self.movie), 'link': 'movie-a'},
                        {'meta': dict(self.movie), 'link': 'movie-b'}]
        cache.user_data_set('playback_history', self.history)

    def make_item(self, **kwargs):
        item = MagicMock()
        item.label = kwargs['label']
        self.created.append(item)
        return item

    @staticmethod
    def respond(session, url, params, timeout):
        lang = params['language']
        if url.endswith('/tv/42'):
            data = {'id': 42, 'name': 'Show ' + lang, 'status': 'Ended', 'poster_path': '/show.jpg'}
        elif url.endswith('/movie/99'):
            data = {'id': 99, 'title': 'Film ' + lang, 'poster_path': '/film.jpg'}
        elif url.endswith('/tv/42/season/0/episode/1'):
            data = {'id': 12345, 'name': 'Special ' + lang, 'season_number': 0,
                    'episode_number': 1, 'still_path': '/special.jpg'}
        else:
            raise AssertionError('Unexpected endpoint: ' + url)
        return SimpleNamespace(json=lambda: data)

    def show_episode_history(self):
        actions.playback_show_history({'show_title': 'Saved show', 'tmdb_id': '42'}, self.instance)

    def test_fresh_and_persisted_metadata_and_episode_identity(self):
        actions.playback_history(self.instance)
        self.assertEqual([item.label for item in self.created], ['Show cs-CZ', 'Film cs-CZ', 'Film cs-CZ'])
        self.created.clear()
        self.show_episode_history()
        self.assertEqual([item.label for item in self.created], ['S00E01 - Special cs-CZ'] * 2)
        for item in self.created:
            tag = item.getVideoInfoTag.return_value
            tag.setUniqueIDs.assert_called_with({'tmdb': '42'})
            tag.setSeason.assert_called_with(0)
            tag.setEpisode.assert_called_with(1)
        self.assertEqual(self.requests.call_count, 3)
        self.assertEqual(cache.user_data_get('playback_history'), self.history)
        cache.clear_ram_cache()
        self.created.clear()
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.assertEqual(self.requests.call_count, 3)
        self.assertEqual([item.label for item in self.created],
                         ['Show cs-CZ', 'Film cs-CZ', 'Film cs-CZ', 'S00E01 - Special cs-CZ', 'S00E01 - Special cs-CZ'])

    def test_language_variants_are_not_mixed(self):
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.client.language = 'en-US'
        self.created.clear()
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.assertEqual(self.requests.call_count, 6)
        self.assertEqual([item.label for item in self.created],
                         ['Show en-US', 'Film en-US', 'Film en-US', 'S00E01 - Special en-US', 'S00E01 - Special en-US'])

    def test_filter_variants_are_reused_independently(self):
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.client.addon.getSetting.return_value = 'HARD'
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.assertEqual(self.requests.call_count, 6)
        self.client.addon.getSetting.return_value = 'OFF'
        cache.clear_ram_cache()
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.assertEqual(self.requests.call_count, 6)

    def test_offline_tmdb_keeps_saved_history(self):
        self.requests.side_effect = None
        self.requests.return_value = None
        actions.playback_history(self.instance)
        self.show_episode_history()
        self.assertEqual([item.label for item in self.created],
                         ['Saved show', 'Saved film', 'Saved film', 'S00E01 - Saved special', 'S00E01 - Saved special'])
        self.assertEqual(cache.user_data_get('playback_history'), self.history)

    def test_error_is_not_cached_and_falls_back_then_recovers(self):
        self.requests.side_effect = [SimpleNamespace(json=lambda: {'status_code': 34, 'success': False}),
                                     SimpleNamespace(json=lambda: {'id': 12345, 'name': 'Recovered'})]
        self.show_episode_history()
        self.assertEqual([item.label for item in self.created], ['S00E01 - Saved special'] * 2)
        self.created.clear()
        self.show_episode_history()
        self.assertEqual([item.label for item in self.created], ['S00E01 - Recovered'] * 2)
        self.assertEqual(self.requests.call_count, 2)


if __name__ == '__main__':
    unittest.main()
