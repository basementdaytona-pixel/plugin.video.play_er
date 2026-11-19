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
