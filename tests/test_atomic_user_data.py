"""Atomic shared-list updates against real SQLite and synthetic Kodi objects."""
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

cache = load_module('resources.lib.cache_manager')
actions = load_module('resources.lib.actions', (
    'resources.lib.sf_context_style', 'resources.lib.utils_files',
    'resources.lib.trakt', 'resources.lib.stream_state', 'resources.lib.ui_builder',
    'resources.lib.utils_filter', 'resources.lib.utils_theme', 'resources.lib.utils',
))
plugin_mocks = ('resources.lib.sf_context_style', 'resources.lib.settings_monitor',
                'resources.lib.dialog_menu', 'resources.lib.trakt_episodes', 'resources.lib.csfd',
                'resources.lib.tmdb', 'resources.lib.tmdb_account', 'resources.lib.generator',
                'resources.lib.actions', 'resources.lib.trakt', 'resources.lib.utils_files',
                'resources.lib.utils_tmdbhelper', 'resources.lib.utils_filter',
                'resources.lib.utils_theme', 'resources.lib.ui_builder', 'resources.lib.utils',
                'resources.lib.utils_custom')
with patch.object(sys, 'argv', ['plugin://plugin.video.play_er', '-1', '']):
    plugin = load_module('resources.lib.plugin', plugin_mocks)


class AtomicSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'cache.db')
        self.settings = patch.multiple(cache, CACHE_DB_PATH=self.path, DB_TYPE='SQLite', SQLITE_INITIALIZED=False)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        cache.clear_ram_cache()

    def test_two_interpreters_do_not_lose_simultaneous_updates(self):
        first, second = cache, load_module('resources.lib.cache_manager')
        second.CACHE_DB_PATH, second.DB_TYPE, second.SQLITE_INITIALIZED = self.path, 'SQLite', False
        conn = first._get_sqlite_connection()
        conn.close()
        second.SQLITE_INITIALIZED = True
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        def slow(values):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release updater')
            return (values or []) + ['first']
        def second_write():
            started.set()
            return second.user_data_update('watch_later', lambda values: (values or []) + ['second'])
        with ThreadPoolExecutor(max_workers=2) as workers:
            a = workers.submit(first.user_data_update, 'watch_later', slow)
            try:
                self.assertTrue(entered.wait(2))
                b = workers.submit(second_write)
                self.assertTrue(started.wait(2))
                with self.assertRaises(TimeoutError):
                    b.result(timeout=0.2)
            finally:
                release.set()
            self.assertTrue(a.result(timeout=3))
            self.assertTrue(b.result(timeout=3))
        self.assertEqual(first.user_data_get('watch_later'), ['first', 'second'])
        self.assertEqual(second.user_data_get('watch_later'), ['first', 'second'])

    def test_reads_skip_stale_ram_for_shared_lists_only(self):
        cache.user_data_set('watch_later', ['old'])
        stale = 'USER_DATA:' + cache._hash_key(('USER_DATA', 'watch_later'))
        with cache.CACHE_LOCK:
            cache._store_in_ram(stale, ['wrong'], 1, 1e12)
        cache.user_data_set('watch_later', ['new'])
        self.assertEqual(cache.user_data_get('watch_later'), ['new'])
        self.assertNotIn(stale, cache.CACHE_RAM)
        self.assertTrue(cache.cache_set('TMDB', ['list', 1], {'value': 1}))
        self.assertEqual(cache.cache_get('TMDB', ['list', 1]), {'value': 1})

    def test_legacy_migration_and_unrelated_section_are_preserved(self):
        conn = cache._get_sqlite_connection()
        now = __import__('time').time()
        conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)',
                     (cache._hash_key('watch_later'), 'USER_DATA', '["legacy"]', now, now + 60))
        conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)',
                     (cache._hash_key('playback_history'), 'OTHER', '["untouched"]', now, now + 60))
        conn.commit()
        conn.close()
        cache.user_data_update('watch_later', lambda value: value + ['new'])
        cache.user_data_update('playback_history', lambda value: ['history'])
        self.assertEqual(cache.user_data_get('watch_later'), ['legacy', 'new'])
        conn = cache._get_sqlite_connection()
        self.assertEqual(conn.execute('SELECT data FROM cache_store WHERE key_hash=?',
                                     (cache._hash_key('playback_history'),)).fetchone()[0], '["untouched"]')
        self.assertIsNone(conn.execute('SELECT 1 FROM cache_store WHERE key_hash=?',
                                      (cache._hash_key('watch_later'),)).fetchone())
        conn.close()

    def test_noop_and_failed_updates_rollback_without_overwriting(self):
        cache.user_data_set('watch_later', ['safe'])
        self.assertFalse(cache.user_data_update('watch_later', lambda value: cache.NO_USER_DATA_CHANGE))
        with self.assertRaises(cache.CacheStorageError):
            cache.user_data_update('watch_later', lambda value: value + [object()])
        self.assertEqual(cache.user_data_get('watch_later'), ['safe'])
        with self.assertRaises(cache.CacheStorageError):
            cache.user_data_update('playback_history', lambda value: (_ for _ in ()).throw(ValueError('failure')))
        self.assertIsNone(cache.user_data_get('playback_history'))

    def test_invalid_stored_json_is_not_overwritten(self):
        conn = cache._get_sqlite_connection()
        now = __import__('time').time()
        conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)',
                     (cache._hash_key(('USER_DATA', 'watch_later')), 'USER_DATA', '{bad', now, now + 60))
        conn.commit()
        conn.close()
        with self.assertRaises(cache.CacheStorageError):
            cache.user_data_update('watch_later', lambda value: ['replacement'])
        conn = cache._get_sqlite_connection()
        self.assertEqual(conn.execute('SELECT data FROM cache_store WHERE key_hash=?',
                                      (cache._hash_key(('USER_DATA', 'watch_later')),)).fetchone()[0], '{bad')
        conn.close()


class AtomicFailureTests(unittest.TestCase):
    def test_failed_mysql_rollback_discards_connection(self):
        import time
        pool = cache.LazyMySQLPool(pool_size=1, pool_timeout=0.1)
        conn = MagicMock()
        conn.cursor.return_value.fetchone.side_effect = [('InnoDB',), ('[]', time.time())]
        conn.rollback.side_effect = RuntimeError('synthetic rollback failure')
        with patch.object(cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(cache, 'MYSQL_AVAILABLE', True), \
                patch.object(cache, '_get_mysql_pool', return_value=pool), \
                patch.object(pool, '_connect', return_value=conn):
            with self.assertRaises(cache.CacheStorageError):
                cache.user_data_update('watch_later', lambda value: (_ for _ in ()).throw(ValueError()))
        conn.close.assert_called_once()
        self.assertEqual(pool._in_use, set())
        self.assertEqual(pool._available, [])
        self.assertEqual(cache.MYSQL_CHECKOUT_COUNT, 0)
        pool.close_all()


class ConsumerBehaviorTests(unittest.TestCase):
    def setUp(self):
        AtomicSQLiteTests.setUp(self)
        self.patches = [patch.object(actions, 'cache_manager', cache), patch.object(plugin, 'cache_manager', cache),
                        patch.object(plugin, 'get_setting_int_with_bounds', return_value=3),
                        patch.object(cache, 'safe_refresh')]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _resolve_history(self, instance, source, provider, meta, **kwargs):
        import resources.lib
        fake_filter = MagicMock()
        fake_filter.clean_display_title.return_value = ('Film', False, [], None)
        fake_utils = MagicMock()
        fake_utils.store_meta_in_cache.return_value = 'meta-key'
        with patch.dict(sys.modules, {'resources.lib.utils_filter': fake_filter,
                                      'resources.lib.utils': fake_utils,
                                      'resources.lib.cache_manager': cache}), \
                patch.object(resources.lib, 'cache_manager', cache, create=True):
            return actions.resolve_video(source, provider, dict(meta), plugin_instance=instance, **kwargs)

    def _resolver_instance(self, limit):
        instance = MagicMock()
        instance.handle = 7
        instance.addon.getSetting.side_effect = lambda key: limit if key == 'playback_history_limit' else 'false'
        instance.addon.getSettingBool.return_value = False
        instance.provider_manager.get_provider.return_value.get_video_link.return_value = ('https://example.invalid/video', None)
        return instance

    def test_watch_later_episode_identity_duplicate_and_ambiguity(self):
        one = {'tmdb_id': 8, 'media_type': 'episode', 'season': 0, 'episode': 1}
        two = dict(one, episode=2)
        actions.add_to_watch_later({'meta': json.dumps(one)}, None)
        actions.add_to_watch_later({'meta': json.dumps(one)}, None)
        actions.add_to_watch_later({'meta': json.dumps(two)}, None)
        self.assertEqual(cache.user_data_get('watch_later'), [two, one])
        actions.remove_from_watch_later({'tmdb_id': 8, 'media_type': 'episode'}, None)
        self.assertEqual(cache.user_data_get('watch_later'), [two, one])
        actions.remove_from_watch_later(dict(one), None)
        self.assertEqual(cache.user_data_get('watch_later'), [two])

    def test_resolver_keeps_existing_history_format_and_kodi_resolution(self):
        import resources.lib
        from types import SimpleNamespace
        meta = {'tmdb_id': 7, 'media_type': 'movie', 'title': 'Film',
                'cast_full': ['Actor'], 'poster': 'poster', 'plot': 'Plot'}
        client = MagicMock()
        client.get_video_link.return_value = ('https://example.invalid/video', None)
        instance = MagicMock()
        instance.provider_manager.get_provider.return_value = client
        instance.addon.getSettingBool.return_value = False
        fake_filter = MagicMock()
        fake_filter.clean_display_title.return_value = ('Film', False, [], None)
        fake_utils = MagicMock()
        fake_utils.store_meta_in_cache.return_value = 'meta-key'
        with patch.dict(sys.modules, {'resources.lib.utils_filter': fake_filter,
                                      'resources.lib.utils': fake_utils,
                                      'resources.lib.cache_manager': cache}), \
                patch.object(resources.lib, 'cache_manager', cache, create=True):
            actions.resolve_video('source-id', 'prehraj.to', dict(meta), plugin_instance=instance)
        item = cache.user_data_get('playback_history')[0]
        self.assertEqual(item['meta'], meta)
        self.assertEqual(item['link'], 'source-id')
        self.assertIsInstance(item['timestamp'], int)
        actions.xbmcplugin.setResolvedUrl.assert_called()
        self.assertTrue(actions.xbmcplugin.setResolvedUrl.call_args.args[1])

    def test_resolver_respects_limit_and_default_above_100(self):
        meta = {'tmdb_id': 999, 'media_type': 'movie', 'title': 'Film',
                'cast_full': ['Actor'], 'poster': 'poster', 'plot': 'Plot'}
        initial = [{'meta': {'tmdb_id': n, 'media_type': 'movie', 'title': str(n)}, 'link': ''} for n in range(1, 161)]
        instance = self._resolver_instance('150')
        cache.user_data_set('playback_history', initial)
        self._resolve_history(instance, 'source', 'prehraj.to', meta)
        self.assertEqual(len(cache.user_data_get('playback_history')), 150)
        instance = self._resolver_instance('50')
        self._resolve_history(instance, 'source', 'prehraj.to', meta)
        self.assertEqual(len(cache.user_data_get('playback_history')), 50)
        instance = self._resolver_instance('')
        cache.user_data_set('playback_history', initial)
        self._resolve_history(instance, 'source', 'prehraj.to', meta)
        self.assertEqual(len(cache.user_data_get('playback_history')), 161)
        large_history = [{'meta': {'tmdb_id': n, 'media_type': 'movie', 'title': str(n)}, 'link': ''}
                         for n in range(1, 5002)]
        instance = self._resolver_instance('5000')
        cache.user_data_set('playback_history', large_history)
        self._resolve_history(instance, 'source', 'prehraj.to', dict(meta, tmdb_id=9999))
        items = cache.user_data_get('playback_history')
        self.assertEqual(len(items), 5000)
        self.assertEqual((items[0]['meta']['tmdb_id'], items[-1]['meta']['tmdb_id']), (9999, 4999))

    def test_playlist_history_writers_use_the_same_limit_and_default(self):
        initial = [{'meta': {'tmdb_id': n, 'media_type': 'movie', 'title': str(n)}, 'link': ''} for n in range(1, 161)]
        instance = self._resolver_instance('')
        with patch.object(plugin, 'addon', instance.addon), \
                patch.object(plugin, 'get_setting_int_with_bounds', actions.get_setting_int_with_bounds):
            cache.user_data_set('playback_history', initial)
            plugin.save_playback_history({'tmdb_id': 999, 'media_type': 'movie', 'title': 'Film'}, skip_refresh=True)
            self.assertEqual(len(cache.user_data_get('playback_history')), 161)
            instance.addon.getSetting.side_effect = lambda key: '50' if key == 'playback_history_limit' else 'false'
            plugin.save_playback_history_bulk([{'meta': {'tmdb_id': 1000, 'media_type': 'movie', 'title': 'Next'}, 'link': ''}])
            self.assertEqual(len(cache.user_data_get('playback_history')), 50)

    def test_playlist_history_treats_missing_media_type_as_movie(self):
        movie = {'tmdb_id': 7, 'media_type': 'movie', 'title': 'Film'}
        implicit = {'tmdb_id': '7', 'title': 'Film'}
        cache.user_data_set('playback_history', [{'meta': implicit, 'link': ''}])
        plugin.save_playback_history(movie, skip_refresh=True)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [movie])
        plugin.save_playback_history(implicit, skip_refresh=True)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [implicit])

    def test_resolver_does_not_merge_distinct_idless_sources(self):
        old = {'meta': {'media_type': 'movie', 'title': 'Same'}, 'link': 'shared'}
        cache.user_data_set('playback_history', [old])
        instance = self._resolver_instance('150')
        one = {'media_type': 'movie', 'title': 'Same', 'cast_full': ['A'], 'poster': 'P', 'plot': 'P'}
        two = dict(one, title='Different')
        for source, provider, meta in [('shared', 'webshare.cz', one), ('shared', 'prehraj.to', one),
                                       ('other', 'webshare.cz', two), ('shared', 'webshare.cz', one)]:
            self._resolve_history(instance, source, provider, meta)
        items = cache.user_data_get('playback_history')
        self.assertEqual([(x['meta']['title'], x.get('provider'), x['link']) for x in items],
                         [('Same', 'webshare.cz', 'shared'), ('Different', 'webshare.cz', 'other'),
                          ('Same', 'prehraj.to', 'shared'), ('Same', None, 'shared')])
        actions.remove_playback_item({'type': 'movie', 'movie_title': 'Same', 'history_no_id': '1'}, None)
        self.assertEqual(len(cache.user_data_get('playback_history')), 4)
        actions.remove_playback_item({'type': 'movie', 'movie_title': 'Same', 'history_no_id': '1',
                                      'history_source': '1', 'history_source_link': 'shared',
                                      'history_source_provider': 'webshare.cz'}, None)
        self.assertEqual([(x['meta']['title'], x.get('provider')) for x in cache.user_data_get('playback_history')],
                         [('Different', 'webshare.cz'), ('Same', 'prehraj.to'), ('Same', None)])

    def test_resolver_episode_matching_does_not_remove_movie(self):
        movie = {'tmdb_id': 42, 'media_type': 'movie', 'title': 'Movie', 'season': 1, 'episode': 1}
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Show', 'season': 1, 'episode': 1,
                   'title': 'Episode', 'cast_full': ['A'], 'poster': 'P', 'plot': 'P'}
        cache.user_data_set('playback_history', [{'meta': movie, 'link': ''}, {'meta': episode, 'link': ''}])
        self._resolve_history(self._resolver_instance('150'), 'ep', 'prehraj.to', episode)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [episode, movie])

    def test_unidentified_provider_does_not_merge_sources(self):
        instance = self._resolver_instance('150')
        instance.provider_manager.get_active_provider.return_value = instance.provider_manager.get_provider.return_value
        instance.provider_manager.get_provider.return_value = None
        meta = {'media_type': 'movie', 'title': 'Film', 'cast_full': ['A'], 'poster': 'P', 'plot': 'P'}
        for _ in range(2):
            self._resolve_history(instance, 'source', 'unavailable', meta)
        self.assertEqual(len(cache.user_data_get('playback_history')), 2)
        self.assertTrue(all('provider' not in item for item in cache.user_data_get('playback_history')))

    def test_url_only_and_failed_resolution_do_not_write_history(self):
        instance = self._resolver_instance('150')
        meta = {'tmdb_id': 7, 'media_type': 'movie', 'title': 'Film', 'cast_full': ['A'], 'poster': 'P', 'plot': 'P'}
        cache.user_data_set('playback_history', [{'meta': meta, 'link': 'previous'}])
        result = self._resolve_history(instance, 'source', 'prehraj.to', meta, return_url_only=True)
        self.assertTrue(result.startswith('https://example.invalid/video|'))
        instance.provider_manager.get_provider.return_value.get_video_link.return_value = (None, None)
        self._resolve_history(instance, 'source', 'prehraj.to', meta)
        self.assertEqual(cache.user_data_get('playback_history'), [{'meta': meta, 'link': 'previous'}])

    def test_playback_history_order_limit_and_bulk_semantics(self):
        def meta(i):
            return {'tmdb_id': i, 'media_type': 'movie', 'title': str(i)}
        with patch.object(plugin.xbmc, 'Player') as player:
            player.return_value.isPlayingVideo.return_value = False
            for i in (1, 2, 1, 3, 4):
                plugin.save_playback_history(meta(i))
        self.assertEqual([item['meta']['tmdb_id'] for item in cache.user_data_get('playback_history')], [4, 3, 1])
        plugin.save_playback_history_bulk([{'meta': meta(5), 'link': ''}, {'meta': meta(6), 'link': ''}])
        self.assertEqual([item['meta']['tmdb_id'] for item in cache.user_data_get('playback_history')], [6, 5, 4])
        actions.remove_playback_item({'type': 'movie', 'movie_title': '5'}, None)
        self.assertEqual([item['meta']['tmdb_id'] for item in cache.user_data_get('playback_history')], [6, 4])

    def test_playback_history_keeps_distinct_episodes_and_replaces_duplicates(self):
        first = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Show',
                 'season': 1, 'episode': 11}
        second = dict(first, season=11, episode=1)
        duplicate = dict(first, tmdb_id='42', season='1', episode='11', title='Updated')
        with patch.object(plugin.xbmc, 'Player') as player:
            player.return_value.isPlayingVideo.return_value = False
            for item in (first, second, duplicate):
                plugin.save_playback_history(item)
        self.assertEqual([item['meta'] for item in cache.user_data_get('playback_history')],
                         [duplicate, second])

    def test_bulk_history_does_not_drop_episode_with_colliding_digits(self):
        first = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Show',
                 'season': 1, 'episode': 11}
        second = dict(first, season=11, episode=1)
        third = dict(first, tmdb_id=421, episode=1)
        plugin.save_playback_history(first, skip_refresh=True)
        plugin.save_playback_history_bulk([{'meta': second, 'link': ''},
                                           {'meta': third, 'link': ''}])
        self.assertEqual([item['meta'] for item in cache.user_data_get('playback_history')],
                         [third, second, first])

    def test_removal_uses_id_and_media_type_even_with_matching_names(self):
        show = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Same', 'season': 1, 'episode': 1, 'title': 'Same'}
        renamed = dict(show, tv_show_title='Renamed', episode=2)
        other_show = dict(show, tmdb_id=43)
        movie = {'tmdb_id': 42, 'media_type': 'movie', 'title': 'Same'}
        other_movie = dict(movie, tmdb_id=44)
        cache.user_data_set('playback_history', [{'meta': m, 'link': ''} for m in (show, renamed, other_show, movie, other_movie)])
        actions.remove_playback_item({'type': 'episode', 'tmdb_id': '42', 'show_title': 'Same', 'season': '1', 'episode': '1'}, None)
        actions.remove_playback_item({'type': 'movie', 'tmdb_id': '42', 'movie_title': 'Same'}, None)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [renamed, other_show, other_movie])
        actions.remove_playback_item({'type': 'show', 'tmdb_id': '42', 'show_title': 'Same'}, None)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [other_show, other_movie])

    def test_legacy_removal_is_safe_for_ambiguous_and_idless_items(self):
        first = {'tmdb_id': 1, 'media_type': 'movie', 'title': 'Same'}
        second = dict(first, tmdb_id=2)
        idless = {'media_type': 'movie', 'title': 'Same'}
        cache.user_data_set('playback_history', [{'meta': m, 'link': ''} for m in (first, second, idless)])
        actions.remove_playback_item({'type': 'movie', 'movie_title': 'Same'}, None)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [first, second, idless])
        actions.remove_playback_item({'type': 'movie', 'movie_title': 'Same', 'history_no_id': '1'}, None)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [first, second])
        actions.remove_playback_item({'type': 'movie', 'tmdb_id': '2', 'movie_title': 'Same'}, None)
        actions.remove_playback_item({'type': 'movie', 'movie_title': 'Same'}, None)
        self.assertEqual(cache.user_data_get('playback_history'), [])

    def test_legacy_episode_and_show_removal_do_not_guess_between_series(self):
        first = {'tmdb_id': 1, 'media_type': 'episode', 'tv_show_title': 'Same', 'season': 0, 'episode': 1}
        second = dict(first, tmdb_id=2)
        idless = dict(first, tmdb_id=None)
        cache.user_data_set('playback_history', [{'meta': m, 'link': ''} for m in (first, second, idless)])
        params = {'type': 'episode', 'show_title': 'Same', 'season': '0', 'episode': '1'}
        actions.remove_playback_item(params, None)
        actions.remove_playback_item({'type': 'show', 'show_title': 'Same'}, None)
        actions.remove_playback_item({'type': 'episode', 'tmdb_id': '1', 'season': '0'}, None)
        self.assertEqual([x['meta'] for x in cache.user_data_get('playback_history')], [first, second, idless])
        actions.remove_playback_item(dict(params, history_no_id='1'), None)
        actions.remove_playback_item(dict(params, tmdb_id='1'), None)
        actions.remove_playback_item({'type': 'show', 'show_title': 'Same'}, None)
        self.assertEqual(cache.user_data_get('playback_history'), [])

    def test_history_show_links_and_context_use_stable_identity(self):
        from urllib.parse import parse_qs, urlencode, urlsplit

        first = {'tmdb_id': 42, 'media_type': 'episode', 'tv_show_title': 'Same', 'season': 1, 'episode': 1, 'title': 'Episode'}
        renamed = dict(first, tv_show_title='Renamed', episode=2)
        second = dict(first, tmdb_id=43)
        idless = dict(first, tmdb_id=None)
        movie = {'tmdb_id': 42, 'media_type': 'movie', 'title': 'Same'}
        movie_idless = {'media_type': 'movie', 'title': 'Same'}
        cache.user_data_set('playback_history', [{'meta': m, 'link': ''} for m in (first, renamed, second, idless, movie, movie_idless)])
        instance = MagicMock()
        instance.handle = 1
        list_items = []

        def make_item(*args, **kwargs):
            item = MagicMock()
            list_items.append(item)
            return item

        def make_url(**kwargs):
            return 'plugin://plugin.video.play_er/?' + urlencode(kwargs)

        with patch.object(actions, 'get_url', side_effect=make_url), \
                patch.object(actions, 'get_threadpool', return_value=1), \
                patch.object(actions, '_get_community_share_context', return_value=None), \
                patch.object(actions, '_sf_cm_items', side_effect=lambda items: items), \
                patch.object(actions.xbmcgui, 'ListItem', side_effect=make_item), \
                patch.object(actions.xbmcplugin, 'addDirectoryItem') as add:
            actions.playback_history(instance)
            self.assertEqual(add.call_count, 5)
            urls = [call.args[1] for call in add.call_args_list[:3]]
            params = [{key: values[0] for key, values in parse_qs(urlsplit(url).query).items()} for url in urls]
            self.assertEqual([p.get('tmdb_id') for p in params], ['42', '43', None])
            self.assertEqual(params[2].get('history_no_id'), '1')
            menus = [item.addContextMenuItems.call_args.args[0] for item in list_items]
            remove = [next(command for _, command in menu if 'action=remove_playback_item&' in command) for menu in menus]
            self.assertIn('tmdb_id=42', remove[0])
            self.assertIn('history_no_id=1', remove[2])
            self.assertIn('tmdb_id=42', remove[3])
            self.assertIn('history_no_id=1', remove[4])

            for url_params, expected_count in zip(params, (2, 1, 1)):
                add.reset_mock()
                list_items.clear()
                actions.playback_show_history(url_params, instance)
                self.assertEqual(add.call_count, expected_count)
                episode_menu = list_items[0].addContextMenuItems.call_args.args[0]
                remove_episode = next(command for _, command in episode_menu if 'action=remove_playback_item&' in command)
                self.assertIn('tmdb_id=' + url_params['tmdb_id'] if url_params.get('tmdb_id') else 'history_no_id=1', remove_episode)

            add.reset_mock()
            actions.playback_show_history({'show_title': 'Same'}, instance)
            self.assertEqual(add.call_count, 3)

    def test_idless_history_context_removes_only_selected_source(self):
        from urllib.parse import parse_qsl, urlencode, urlsplit

        movie = {'media_type': 'movie', 'title': 'Same'}
        episode = {'media_type': 'episode', 'tv_show_title': 'Show', 'season': 0, 'episode': 1, 'title': 'Pilot'}
        movies = [{'meta': movie, 'link': 'x&y=1', 'provider': name} for name in ('webshare.cz', 'prehraj.to')]
        episodes = [{'meta': episode, 'link': 'z&v=2', 'provider': name} for name in ('webshare.cz', 'prehraj.to')]
        cache.user_data_set('playback_history', episodes + movies)
        instance = MagicMock()
        instance.handle = 1
        list_items = []

        def make_item(*args, **kwargs):
            item = MagicMock()
            list_items.append(item)
            return item

        def removal_params(item):
            menu = item.addContextMenuItems.call_args.args[0]
            command = next(command for _, command in menu if 'action=remove_playback_item&' in command)
            return dict(parse_qsl(urlsplit(command[len('RunPlugin('):-1]).query))

        with patch.object(actions, 'get_url', side_effect=lambda **kwargs: 'plugin://addon/?' + urlencode(kwargs)), \
                patch.object(actions, 'get_threadpool', return_value=1), \
                patch.object(actions, '_get_community_share_context', return_value=None), \
                patch.object(actions, '_sf_cm_items', side_effect=lambda items: items), \
                patch.object(actions.xbmcgui, 'ListItem', side_effect=make_item):
            actions.playback_history(instance)
            params = removal_params(list_items[1])
            self.assertEqual(params['history_source_link'], 'x&y=1')
            self.assertEqual(params['history_source_provider'], 'webshare.cz')
            actions.remove_playback_item(params, None)
            self.assertEqual(cache.user_data_get('playback_history'), episodes + movies[1:])

            list_items.clear()
            actions.playback_show_history({'show_title': 'Show', 'history_no_id': '1'}, instance)
            params = removal_params(list_items[0])
            self.assertEqual(params['history_source_link'], 'z&v=2')
            actions.remove_playback_item(params, None)
            self.assertEqual(cache.user_data_get('playback_history'), episodes[1:] + movies[1:])
