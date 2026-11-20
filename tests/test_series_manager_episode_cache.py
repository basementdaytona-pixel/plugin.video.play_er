"""Series manager episode listings reuse TMDB data without a network request."""
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_atomic_user_data as atomic
import test_tmdb_fetch as tmdb_support
from kodi_test_support import load_module

cache, tmdb = atomic.cache, tmdb_support.tmdb
ui = load_module('resources.lib.ui_builder', (
    'resources.lib.sf_context_style', 'resources.lib.view_modes',
    'resources.lib.utils_theme', 'resources.lib.utils',
))


class SeriesEpisodeCacheTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.multiple(cache, CACHE_DB_PATH=str(Path(directory) / 'cache.db'),
                                           DB_TYPE='SQLite', SQLITE_INITIALIZED=False))
        cache.clear_ram_cache()
        stack.enter_context(patch.object(ui, 'cache_manager', cache))
        stack.enter_context(patch.object(tmdb, 'cache_manager', cache))
        stack.enter_context(patch.object(ui, '_sf_cm_items', side_effect=lambda items: items))
        stack.enter_context(patch.object(ui, 'get_url', side_effect=lambda **kw: json.dumps(kw)))
        stack.enter_context(patch.object(ui, 'set_view_mode'))
        self.items = []
        stack.enter_context(patch.object(ui.xbmcgui, 'ListItem', side_effect=self.make_item))
        self.add = stack.enter_context(patch.object(ui.xbmcplugin, 'addDirectoryItem'))
        self.end = stack.enter_context(patch.object(ui.xbmcplugin, 'endOfDirectory'))
        self.request = stack.enter_context(patch.object(tmdb, 'safe_get', side_effect=self.respond))
        self.client = object.__new__(tmdb.TMDB)
        self.client.api_key, self.client.language = 'synthetic-key', 'cs-CZ'
        self.client.base_url, self.client.image_base_url = 'https://example.invalid/3', 'https://example.invalid/img/'
        self.client.session, self.client.addon, self.client.genres_cache = MagicMock(), MagicMock(), {}
        self.client.addon.getSetting.return_value = 'OFF'
        self.series = {'tmdb_id': 42, 'seasons': {'0': {
            '1': {'name': 'First.Release.mkv', 'ident': 'first-link', 'provider': 'webshare'},
            '2': {'name': 'Second.Release.mp4', 'ident': 'second-link', 'provider': 'provider_prehrajto'},
        }}}
        self.manager = MagicMock()
        self.manager.load_series_data.return_value = self.series
        self.manager.is_episode_watched.return_value = False
        self.instance = SimpleNamespace(handle=7, addon=MagicMock(), series_manager=self.manager, tmdb_client=self.client)

    def make_item(self, **kwargs):
        item = MagicMock()
        item.label = kwargs['label']
        self.items.append(item)
        return item

    @staticmethod
    def respond(session, url, params, timeout):
        if url.endswith('/tv/42'):
            data = {'id': 42, 'name': 'Show', 'poster_path': '/poster.jpg',
                    'backdrop_path': '/fanart.jpg', 'credits': {'cast': []}}
        elif url.endswith(('/tv/42/season/0/episode/1', '/tv/42/season/0/episode/2')):
            data = {'id': 12345, 'name': 'TMDB special', 'genre_ids': [18], 'credits': {'cast': []}}
        elif url.endswith('/genre/tv/list'):
            data = {'genres': [{'id': 18, 'name': 'Drama'}]}
        else:
            raise AssertionError('Unexpected endpoint: ' + url)
        return SimpleNamespace(json=lambda: data)

    def seed_current_cache(self):
        self.client.get_full_details('tv', 42)
        self.client._fetch('tv/42/season/0/episode/1', params={'append_to_response': 'credits'})
        self.client._fetch('genre/tv/list', cache_key='genres_tv')
        cache.clear_ram_cache()
        self.request.reset_mock()

    def render(self):
        ui.create_episodes_menu('Show', 0, self.instance)

    def test_cached_metadata_art_genres_and_identity_preserve_links(self):
        self.seed_current_cache()
        self.render()
        self.assertEqual(len(self.items), 2)
        self.assertIn('First Release', self.items[0].label)
        tag = self.items[0].getVideoInfoTag.return_value
        tag.setTitle.assert_called_with('TMDB special')
        tag.setUniqueIDs.assert_called_with({'tmdb': '42'})
        tag.setSeason.assert_called_with(0)
        tag.setEpisode.assert_called_with(1)
        tag.setGenres.assert_called_with(['Drama'])
        self.items[0].setArt.assert_called_with({'poster': 'https://image.tmdb.org/t/p/w500/poster.jpg',
                                                'fanart': 'https://image.tmdb.org/t/p/w1280/fanart.jpg',
                                                'icon': 'https://image.tmdb.org/t/p/w500/poster.jpg'})
        self.items[1].getVideoInfoTag.return_value.setTitle.assert_called_with('Second Release')
        links = [json.loads(call.args[1]) for call in self.add.call_args_list]
        self.assertEqual([(item['link'], item['provider']) for item in links],
                         [('first-link', 'webshare.cz'), ('second-link', 'prehraj.to')])
        self.assertEqual(json.loads(links[0]['meta'])['tmdb_id'], 42)
        self.request.assert_not_called()
        self.end.assert_called_once_with(7)

    def test_cache_only_works_without_api_key_and_never_fetches(self):
        self.seed_current_cache()
        self.client.api_key = ''
        with patch.object(tmdb, 'notify_error') as notify:
            self.render()
        notify.assert_not_called()
        self.items[0].getVideoInfoTag.return_value.setTitle.assert_called_with('TMDB special')
        self.request.assert_not_called()

    def test_other_language_cache_does_not_replace_local_metadata(self):
        self.client.language = 'en-US'
        self.seed_current_cache()
        self.client.language = 'cs-CZ'
        self.render()
        self.items[0].getVideoInfoTag.return_value.setTitle.assert_called_with('First Release')
        self.request.assert_not_called()

    def test_other_filter_cache_does_not_replace_local_metadata(self):
        self.seed_current_cache()
        self.client.addon.getSetting.return_value = 'HARD'
        self.render()
        self.items[0].getVideoInfoTag.return_value.setTitle.assert_called_with('First Release')
        self.request.assert_not_called()

    def test_episode_without_credits_and_prior_explicit_cache_are_supported(self):
        endpoint = 'tv/42/season/0/episode/1'
        self.client._fetch(endpoint)
        self.client._fetch('tv/42/season/0/episode/2', cache_key='tv_42_s0_e2')
        self.request.reset_mock()
        self.render()
        for item in self.items:
            item.getVideoInfoTag.return_value.setTitle.assert_called_with('TMDB special')
            item.getVideoInfoTag.return_value.setUniqueIDs.assert_called_with({'tmdb': '42'})
        self.request.assert_not_called()

    def test_episode_genres_can_be_used_without_fetching_genres(self):
        cache.cache_set('TMDB', 'tv_42_s0_e1',
                        {'id': 12345, 'name': 'Legacy special', 'genres': [{'id': 18, 'name': 'Drama'}]})
        self.render()
        self.items[0].getVideoInfoTag.return_value.setGenres.assert_called_with(['Drama'])
        self.request.assert_not_called()

    def test_bad_and_missing_cache_are_safe_and_offline(self):
        cache.cache_set('TMDB', self.client._cache_variant('tv_detail_42'), {'status_code': 34})
        cache.cache_set('TMDB', 'tv_42_s0_e1', {'status_code': 34, 'success': False})
        self.request.reset_mock()
        self.render()
        self.assertEqual(len(self.items), 2)
        self.items[0].getVideoInfoTag.return_value.setTitle.assert_called_with('First Release')
        self.request.assert_not_called()

    def test_legacy_cache_preserves_compatibility_and_show_identity(self):
        cache.cache_set('TMDB', 'tv_42', {'poster_path': '/legacy.jpg'})
        cache.cache_set('TMDB', 'tv_42_s0_e1', {'id': 12345, 'name': 'Legacy special'})
        self.request.reset_mock()
        self.render()
        tag = self.items[0].getVideoInfoTag.return_value
        tag.setTitle.assert_called_with('Legacy special')
        tag.setUniqueIDs.assert_called_with({'tmdb': '42'})
        tag.setSeason.assert_called_with(0)
        self.request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
