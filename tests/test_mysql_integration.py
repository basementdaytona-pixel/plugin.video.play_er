"""Optional real database checks; set PLAY_ER_TEST_MYSQL_PORT on localhost."""
import os
import sys
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from kodi_test_support import load_module


class PausedCursor:
    def __init__(self, cursor, phase, entered, release):
        self.cursor, self.phase = cursor, phase
        self.entered, self.release = entered, release

    def execute(self, sql, *args, **kwargs):
        normalized = sql.lstrip().upper()
        if ((self.phase == 'clear' and normalized.startswith('DELETE FROM CACHE_STORE WHERE SECTION IN')) or
                (self.phase == 'reset' and normalized.startswith('DROP TABLE IF EXISTS CACHE_STORE'))):
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError('test did not release deletion')
        result = self.cursor.execute(sql, *args, **kwargs)
        if self.phase == 'write' and normalized.startswith('INSERT INTO CACHE_STORE'):
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError('test did not release write')
        return result

    def fetchone(self):
        row = self.cursor.fetchone()
        if self.phase == 'read':
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError('test did not release read')
        return row

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class PausedConnection:
    def __init__(self, connection, phase, entered, release):
        self.connection, self.phase = connection, phase
        self.entered, self.release = entered, release

    def cursor(self, *args, **kwargs):
        return PausedCursor(self.connection.cursor(*args, **kwargs), self.phase, self.entered, self.release)

    def __getattr__(self, name):
        return getattr(self.connection, name)


@unittest.skipUnless(os.environ.get('PLAY_ER_TEST_MYSQL_PORT'), 'local disposable MySQL not configured')
class MySQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mysql.connector
        cls.cache = load_module('resources.lib.cache_manager')
        cls.config = dict(host='127.0.0.1', port=int(os.environ['PLAY_ER_TEST_MYSQL_PORT']),
                          user='root', password='', use_pure=True, autocommit=True,
                          connection_timeout=3)
        cls.database = 'play_er_test_' + uuid.uuid4().hex
        cls.admin = mysql.connector.connect(**cls.config)
        cursor = cls.admin.cursor()
        cursor.execute(f'CREATE DATABASE `{cls.database}`')
        cursor.close()

    @classmethod
    def tearDownClass(cls):
        cursor = cls.admin.cursor()
        cursor.execute(f'DROP DATABASE `{cls.database}`')
        cursor.close()
        cls.admin.close()

    def setUp(self):
        self.pool = self.cache.LazyMySQLPool(**self.config, database=self.database,
                                           pool_size=3, pool_timeout=5)
        self.addCleanup(self.pool.close_all)
        conn = self.pool.get_connection()
        self.assertTrue(self.cache._init_db_tables(conn, is_mysql=True))
        self.pool.put_connection(conn)
        self.cache.clear_ram_cache()

    def test_concurrent_persistent_cache_round_trips(self):
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            def write(index):
                return self.cache.user_data_set(f'item-{index}', {'index': index, 'title': 'Příliš žluťoučký'})
            with ThreadPoolExecutor(max_workers=12) as executor:
                self.assertTrue(all(executor.map(write, range(48))))
            self.cache.clear_ram_cache()
            with ThreadPoolExecutor(max_workers=12) as executor:
                values = list(executor.map(lambda index: self.cache.user_data_get(f'item-{index}'), range(48)))
            self.assertEqual([value['index'] for value in values], list(range(48)))
            self.assertTrue(all(value['title'] == 'Příliš žluťoučký' for value in values))
            self.assertEqual(self.cache.MYSQL_CHECKOUT_COUNT, 0)
            self.assertEqual(len(self.pool._available), 3)
            self.assertEqual(self.pool._in_use, set())

    def test_preemptive_searches_are_ordered_across_interpreters(self):
        second = load_module('resources.lib.cache_manager')
        key = 'preemptive-race-' + uuid.uuid4().hex
        now = time.time()
        barrier = threading.Barrier(8)
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
             patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
             patch.object(second, '_get_mysql_pool', return_value=self.pool), \
             patch.object(second, 'DB_TYPE', 'MySQL (MariaDB)'):
            def write(index):
                barrier.wait(timeout=5)
                cache = self.cache if index % 2 else second
                return cache.cache_set_preemptive_if_newer(key, {'results': [index]}, now - 10 + index)
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(write, range(8)))
            self.assertEqual(self.cache.cache_get('PREEMPTIVE_SOURCES', key)['results'], [7])
            self.assertEqual(second.cache_get('PREEMPTIVE_SOURCES', key)['results'], [7])
            self.assertFalse(second.cache_set_preemptive_if_newer(key, {'results': ['old']}, now - 20))
            self.assertEqual(self.cache.cache_get('PREEMPTIVE_SOURCES', key)['results'], [7])

    def test_preemptive_write_failure_rolls_back_and_reuses_connection(self):
        key = 'preemptive-rollback-' + uuid.uuid4().hex
        now = time.time() - 1
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
             patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            with patch.object(self.cache, '_folder_ttl', side_effect=RuntimeError('synthetic failure')):
                self.assertFalse(self.cache.cache_set_preemptive_if_newer(key, {'value': 'bad'}, now))
            self.assertIsNone(self.cache.cache_get('PREEMPTIVE_SOURCES', key))
            self.assertTrue(self.cache.cache_set_preemptive_if_newer(key, {'value': 'good'}, now))
            self.assertEqual(self.cache.cache_get('PREEMPTIVE_SOURCES', key)['value'], 'good')
            self.assertEqual(self.cache.MYSQL_CHECKOUT_COUNT, 0)

    def test_resolver_fallback_key_reads_new_episode_from_mariadb(self):
        import resources.lib
        actions = load_module('resources.lib.actions', (
            'resources.lib.sf_context_style', 'resources.lib.utils_files', 'resources.lib.trakt',
            'resources.lib.stream_state', 'resources.lib.ui_builder', 'resources.lib.utils_filter',
            'resources.lib.utils_theme', 'resources.lib.utils',
        ))
        utils = load_module('resources.lib.utils', ('resources.lib.utils_files', 'resources.lib.utils_theme'))
        fake_filter = MagicMock()
        fake_filter.clean_display_title.return_value = ('Episode', False, [], None)
        instance = MagicMock()
        instance.addon.getSetting.return_value = 'false'
        instance.addon.getSettingBool.return_value = False
        instance.provider_manager.get_provider.return_value.get_video_link.return_value = ('https://example.invalid/video', None)
        props = {'play_er.current_meta_uuid': 'old-movie-key', 'play_er.current_media_type': 'movie'}
        window = MagicMock()
        window.setProperty.side_effect = lambda key, value: props.__setitem__(key, value)
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2,
                   'title': 'Nová epizoda', 'cast_full': ['Actor'], 'poster': 'P', 'plot': 'Plot'}
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(actions, 'cache_manager', self.cache), \
                patch.object(utils, 'cache_manager', self.cache), \
                patch.object(actions.xbmcgui, 'Window', return_value=window), \
                patch.dict(sys.modules, {'resources.lib.utils_filter': fake_filter,
                                         'resources.lib.utils': utils,
                                         'resources.lib.cache_manager': self.cache}), \
                patch.object(resources.lib, 'cache_manager', self.cache, create=True):
            actions.resolve_video('source-id', 'prehraj.to', dict(episode), plugin_instance=instance)
            self.assertEqual(props['play_er.current_media_type'], 'episode')
            self.assertNotEqual(props['play_er.current_meta_uuid'], 'old-movie-key')
            self.cache.clear_ram_cache()
            stored = utils.get_meta_from_cache(props['play_er.current_meta_uuid'])
        self.assertEqual(stored['tmdb_id'], 42)
        self.assertEqual(stored['episode'], 2)
        self.assertEqual(stored['title'], 'Nová epizoda')

    def test_resolver_history_limit_and_idless_source_removal(self):
        import resources.lib
        actions = load_module('resources.lib.actions', (
            'resources.lib.sf_context_style', 'resources.lib.utils_files',
            'resources.lib.trakt', 'resources.lib.stream_state', 'resources.lib.ui_builder',
            'resources.lib.utils_filter', 'resources.lib.utils_theme', 'resources.lib.utils',
        ))
        instance = MagicMock()
        instance.addon.getSetting.side_effect = lambda key: '5000' if key == 'playback_history_limit' else 'false'
        instance.addon.getSettingBool.return_value = False
        instance.provider_manager.get_provider.return_value.get_video_link.return_value = ('https://example.invalid/video', None)
        fake_filter = MagicMock()
        fake_filter.clean_display_title.return_value = ('Film', False, [], None)
        fake_utils = MagicMock()
        fake_utils.store_meta_in_cache.return_value = 'meta-key'
        meta = {'media_type': 'movie', 'title': 'Příliš žluťoučký', 'cast_full': ['A'], 'poster': 'P', 'plot': 'P'}
        initial = [{'meta': {'tmdb_id': n, 'media_type': 'movie', 'title': str(n)}, 'link': ''}
                   for n in range(1, 5002)]
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(actions, 'cache_manager', self.cache), \
                patch.dict(sys.modules, {'resources.lib.utils_filter': fake_filter,
                                         'resources.lib.utils': fake_utils,
                                         'resources.lib.cache_manager': self.cache}), \
                patch.object(resources.lib, 'cache_manager', self.cache, create=True):
            self.assertTrue(self.cache.user_data_set('playback_history', initial))
            for provider in ('webshare.cz', 'prehraj.to', 'webshare.cz'):
                actions.resolve_video('shared', provider, dict(meta), plugin_instance=instance)
            history = self.cache.user_data_get('playback_history')
            self.assertEqual(len(history), 5000)
            self.assertEqual([x['provider'] for x in history[:2]], ['webshare.cz', 'prehraj.to'])
            actions.remove_playback_item({'type': 'movie', 'movie_title': meta['title'], 'history_no_id': '1',
                                          'history_source': '1', 'history_source_link': 'shared',
                                          'history_source_provider': 'webshare.cz'}, None)
            history = self.cache.user_data_get('playback_history')
            self.assertEqual((len(history), history[0]['provider']), (4999, 'prehraj.to'))

    def _pause_connection(self, phase, entered, release):
        original = self.cache._get_db_connection
        def get_connection():
            conn, is_mysql = original()
            if threading.current_thread().name == 'cache-paused':
                conn = PausedConnection(conn, phase, entered, release)
            return conn, is_mysql
        return get_connection

    def test_concurrent_read_and_write_keep_newer_value_and_other_keys_progress(self):
        entered, release, writer_started = threading.Event(), threading.Event(), threading.Event()
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            self.cache.cache_set('TMDB', 'same', {'value': 'old'})
            self.cache.clear_ram_cache()
            slow = self._pause_connection('read', entered, release)
            def read():
                threading.current_thread().name = 'cache-paused'
                return self.cache.cache_get('TMDB', 'same')
            def write():
                writer_started.set()
                return self.cache.cache_set('TMDB', 'same', {'value': 'new'})
            stripe = int(self.cache._hash_key(('TMDB', 'same'))[:8], 16) % 256
            other = next(str(i) for i in range(1000)
                         if int(self.cache._hash_key(('TMDB', str(i)))[:8], 16) % 256 != stripe)
            with patch.object(self.cache, '_get_db_connection', side_effect=slow), ThreadPoolExecutor(max_workers=3) as executor:
                reader = executor.submit(read)
                try:
                    self.assertTrue(entered.wait(2))
                    writer = executor.submit(write)
                    self.assertTrue(writer_started.wait(2))
                    with self.assertRaises(TimeoutError):
                        writer.result(timeout=0.2)
                    independent = executor.submit(self.cache.cache_set, 'TMDB', other, {'value': 'other'})
                    self.assertTrue(independent.result(timeout=2))
                finally:
                    release.set()
                self.assertEqual(reader.result(timeout=3), {'value': 'old'})
                self.assertTrue(writer.result(timeout=3))
            self.assertEqual(self.cache.cache_get('TMDB', 'same'), {'value': 'new'})
            self.cache.clear_ram_cache()
            self.assertEqual(self.cache.cache_get('TMDB', 'same'), {'value': 'new'})

    def test_concurrent_writes_publish_in_database_order(self):
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            slow = self._pause_connection('write', entered, release)
            def first():
                threading.current_thread().name = 'cache-paused'
                return self.cache.cache_set('TMDB', 'same', {'value': 1})
            def second():
                started.set()
                return self.cache.cache_set('TMDB', 'same', {'value': 2})
            with patch.object(self.cache, '_get_db_connection', side_effect=slow), ThreadPoolExecutor(max_workers=2) as executor:
                a = executor.submit(first)
                try:
                    self.assertTrue(entered.wait(2))
                    b = executor.submit(second)
                    self.assertTrue(started.wait(2))
                    with self.assertRaises(TimeoutError):
                        b.result(timeout=0.2)
                finally:
                    release.set()
                self.assertTrue(a.result(timeout=3))
                self.assertTrue(b.result(timeout=3))
            self.assertEqual(self.cache.cache_get('TMDB', 'same'), {'value': 2})
            self.cache.clear_ram_cache()
            self.assertEqual(self.cache.cache_get('TMDB', 'same'), {'value': 2})

    def test_clear_during_sql_read_does_not_restore_deleted_ram_value(self):
        entered, release = threading.Event(), threading.Event()
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            self.cache.cache_set('CSFD', 'same', {'value': 'old'})
            self.cache.clear_ram_cache()
            slow = self._pause_connection('read', entered, release)
            def read():
                threading.current_thread().name = 'cache-paused'
                return self.cache.cache_get('CSFD', 'same')
            with patch.object(self.cache, '_get_db_connection', side_effect=slow), ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(read)
                try:
                    self.assertTrue(entered.wait(2))
                    self.cache.cache_clear('CSFD', notify_success=False)
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=3), {'value': 'old'})
            self.assertIsNone(self.cache.cache_get('CSFD', 'same'))

    def test_read_during_clear_is_evicted_after_delete(self):
        entered, release = threading.Event(), threading.Event()
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            self.cache.cache_set('CSFD', 'same', {'value': 'old'})
            self.cache.clear_ram_cache()
            slow = self._pause_connection('clear', entered, release)
            def clear():
                threading.current_thread().name = 'cache-paused'
                self.cache.cache_clear('CSFD', notify_success=False)
            with patch.object(self.cache, '_get_db_connection', side_effect=slow), ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(clear)
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.cache.cache_get('CSFD', 'same'), {'value': 'old'})
                finally:
                    release.set()
                pending.result(timeout=3)
            self.assertIsNone(self.cache.cache_get('CSFD', 'same'))

    def test_read_during_reset_is_evicted_after_table_recreation(self):
        entered, release = threading.Event(), threading.Event()
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(self.cache.xbmcgui, 'Dialog') as dialog:
            dialog.return_value.yesno.return_value = True
            self.cache.user_data_set('same', {'history': [1]})
            self.cache.clear_ram_cache()
            slow = self._pause_connection('reset', entered, release)
            def reset():
                threading.current_thread().name = 'cache-paused'
                self.cache.reset_database()
            with patch.object(self.cache, '_get_db_connection', side_effect=slow), ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(reset)
                try:
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.cache.user_data_get('same'), {'history': [1]})
                finally:
                    release.set()
                pending.result(timeout=3)
            self.assertIsNone(self.cache.user_data_get('same'))

    def test_provisioning_handles_quoted_database_and_credentials(self):
        import mysql.connector
        tag = uuid.uuid4().hex[:10]
        name = 'play`er_' + tag
        user = "pe'" + tag
        password = "test'\\password"
        connector = SimpleNamespace(connect=lambda **kwargs: mysql.connector.connect(**self.config))
        try:
            with patch.object(self.cache, 'mysql', SimpleNamespace(connector=connector)):
                self.cache._ensure_mysql_database('127.0.0.1', self.config['port'], user, password, name, 3)
            cursor = self.admin.cursor()
            cursor.execute('SELECT User, Host FROM mysql.user WHERE User=%s AND Host=%s', (user, '%'))
            self.assertEqual(cursor.fetchone(), (user, '%'))
            cursor.close()
            login = mysql.connector.connect(host='127.0.0.1', port=self.config['port'],
                                            user=user, password=password, database=name,
                                            use_pure=True, connection_timeout=3)
            try:
                cursor = login.cursor()
                cursor.execute('CREATE TABLE example (id INT)')
                cursor.close()
                self.assertTrue(self.cache._init_db_tables(login, is_mysql=True))
            finally:
                login.close()
            pool = self.cache.LazyMySQLPool(host='127.0.0.1', port=self.config['port'],
                                            user=user, password=password, database=name, use_pure=True,
                                            connection_timeout=3, pool_size=1, pool_timeout=3)
            try:
                with patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                        patch.object(self.cache, '_get_mysql_pool', return_value=pool):
                    self.assertTrue(self.cache.user_data_update('watch_later', lambda current: ['limited-user']))
                    self.assertEqual(self.cache.user_data_get('watch_later'), ['limited-user'])
            finally:
                pool.close_all()
        finally:
            cursor = self.admin.cursor()
            cursor.execute("DROP USER IF EXISTS %s@%s", (user, '%'))
            cursor.execute('DROP DATABASE IF EXISTS `' + name.replace('`', '``') + '`')
            cursor.close()

    def test_clear_section_invalidates_widget_and_preserves_history(self):
        properties = {}
        window = SimpleNamespace(getProperty=lambda key: properties.get(key, ''),
                                 setProperty=lambda key, value: properties.__setitem__(key, value),
                                 clearProperty=lambda key: properties.pop(key, None))
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(self.cache, 'WINDOW', window):
            self.cache.cache_set('CSFD', 'daily_tips', {'title': 'old'})
            self.cache.user_data_set('history', [1])
            self.cache.window_cache_set('daily_tips', {'title': 'old'})
            self.cache.cache_clear('CSFD')
            self.assertIsNone(self.cache.window_cache_get('daily_tips'))
            self.assertIsNone(self.cache.cache_get('CSFD', 'daily_tips'))
            self.assertEqual(self.cache.user_data_get('history'), [1])

    def test_trakt_group_clear_removes_personal_sections_only(self):
        properties = {}
        window = SimpleNamespace(getProperty=lambda key: properties.get(key, ''),
                                 setProperty=lambda key, value: properties.__setitem__(key, value),
                                 clearProperty=lambda key: properties.pop(key, None))
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(self.cache, 'WINDOW', window):
            for section in ('TRAKT', 'TRAKT_WATCHLIST', 'TRAKT_FAVORITES'):
                self.cache.cache_set(section, 'item', [section])
            self.cache.user_data_set('history', [1])
            self.cache.cache_clear('TRAKT', notify_success=False)
            for section in ('TRAKT', 'TRAKT_WATCHLIST', 'TRAKT_FAVORITES'):
                self.assertIsNone(self.cache.cache_get(section, 'item'))
            self.assertEqual(self.cache.user_data_get('history'), [1])

    def test_tmdb_group_clear_and_personal_expiry_prune(self):
        properties = {}
        window = SimpleNamespace(getProperty=lambda key: properties.get(key, ''),
                                 setProperty=lambda key, value: properties.__setitem__(key, value),
                                 clearProperty=lambda key: properties.pop(key, None))
        with patch.object(self.cache, '_get_mysql_pool', return_value=self.pool), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(self.cache, 'WINDOW', window), \
                patch.object(self.cache, '_last_personal_prune', None):
            import time
            expired, persistent = 'expired_' + uuid.uuid4().hex, 'persistent_' + uuid.uuid4().hex
            conn = self.pool.get_connection()
            cursor = conn.cursor()
            now = time.time()
            cursor.execute('INSERT INTO cache_store VALUES (%s, %s, %s, %s, %s)',
                           (expired, 'TRAKT_WATCHLIST', '{}', now - 10, now - 5))
            cursor.execute('INSERT INTO cache_store VALUES (%s, %s, %s, %s, %s)',
                           (persistent, 'USER_DATA', '{}', now - 10, now - 5))
            cursor.close()
            self.pool.put_connection(conn)
            self.cache.cache_set('TMDB_ACCOUNT', 'personal', [1])
            self.cache.cache_set('TMDB', 'public', [2])
            conn = self.pool.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT key_hash FROM cache_store WHERE key_hash IN (%s, %s)', (expired, persistent))
            self.assertEqual({row[0] for row in cursor.fetchall()}, {persistent})
            cursor.close()
            self.pool.put_connection(conn)
            self.cache.cache_clear('TMDB', notify_success=False)
            self.assertIsNone(self.cache.cache_get('TMDB_ACCOUNT', 'personal'))
            self.assertIsNone(self.cache.cache_get('TMDB', 'public'))

    def test_atomic_shared_list_across_interpreters_and_rollback(self):
        other = load_module('resources.lib.cache_manager')
        other.DB_TYPE, other.MYSQL_AVAILABLE = 'MySQL (MariaDB)', True
        second_pool = other.LazyMySQLPool(**self.config, database=self.database, pool_size=2, pool_timeout=5)
        self.addCleanup(second_pool.close_all)
        first = self.cache
        keyhash, legacy = first._hash_key(('USER_DATA', 'watch_later')), first._hash_key('watch_later')
        cursor = self.admin.cursor()
        cursor.execute(f'DELETE FROM `{self.database}`.cache_store WHERE key_hash IN (%s, %s)', (keyhash, legacy))
        cursor.close()
        entered, release, started = threading.Event(), threading.Event(), threading.Event()
        def slow(values):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release updater')
            return (values or []) + ['first']
        def second_write():
            started.set()
            return other.user_data_update('watch_later', lambda values: (values or []) + ['second'])
        with patch.object(first, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(first, '_get_mysql_pool', return_value=self.pool), \
                patch.object(other, '_get_mysql_pool', return_value=second_pool):
            with ThreadPoolExecutor(max_workers=2) as executor:
                a = executor.submit(first.user_data_update, 'watch_later', slow)
                try:
                    self.assertTrue(entered.wait(2))
                    b = executor.submit(second_write)
                    self.assertTrue(started.wait(2))
                    with self.assertRaises(TimeoutError):
                        b.result(timeout=0.2)
                finally:
                    release.set()
                self.assertTrue(a.result(timeout=4))
                self.assertTrue(b.result(timeout=4))
            self.assertEqual(first.user_data_get('watch_later'), ['first', 'second'])
            self.assertEqual(other.user_data_get('watch_later'), ['first', 'second'])
            with self.assertRaises(first.CacheStorageError):
                first.user_data_update('watch_later', lambda values: values + [object()])
            self.assertEqual(first.user_data_get('watch_later'), ['first', 'second'])
            self.assertTrue(first.user_data_update('watch_later', lambda values: values + ['third']))
            self.assertEqual(other.user_data_get('watch_later'), ['first', 'second', 'third'])
            conn = self.pool.get_connection()
            self.assertTrue(conn.autocommit)
            self.assertFalse(conn.in_transaction)
            self.pool.put_connection(conn)

    def test_atomic_different_lists_progress_without_gap_lock_deadlock(self):
        first, other = self.cache, load_module('resources.lib.cache_manager')
        other.DB_TYPE, other.MYSQL_AVAILABLE = 'MySQL (MariaDB)', True
        second_pool = other.LazyMySQLPool(**self.config, database=self.database, pool_size=1, pool_timeout=3)
        self.addCleanup(second_pool.close_all)
        keys = [first._hash_key(('USER_DATA', key)) for key in ('watch_later', 'playback_history')]
        keys += [first._hash_key(key) for key in ('watch_later', 'playback_history')]
        cursor = self.admin.cursor()
        cursor.execute(f'DELETE FROM `{self.database}`.cache_store WHERE key_hash IN (%s,%s,%s,%s)', keys)
        cursor.close()
        entered, release = threading.Event(), threading.Event()
        def slow(values):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test did not release updater')
            return ['watch']
        with patch.object(first, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(first, '_get_mysql_pool', return_value=self.pool), \
                patch.object(other, '_get_mysql_pool', return_value=second_pool):
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending = executor.submit(first.user_data_update, 'watch_later', slow)
                try:
                    self.assertTrue(entered.wait(2))
                    independent = executor.submit(other.user_data_update, 'playback_history', lambda values: ['history'])
                    self.assertTrue(independent.result(timeout=3))
                finally:
                    release.set()
                self.assertTrue(pending.result(timeout=3))
            self.assertEqual(first.user_data_get('watch_later'), ['watch'])
            self.assertEqual(other.user_data_get('playback_history'), ['history'])

    def test_atomic_mysql_migrates_legacy_without_touching_other_section(self):
        import time
        legacy = self.cache._hash_key('watch_later')
        canonical = self.cache._hash_key(('USER_DATA', 'watch_later'))
        cursor = self.admin.cursor()
        cursor.execute(f'DELETE FROM `{self.database}`.cache_store WHERE key_hash IN (%s, %s)', (legacy, canonical))
        now = time.time()
        cursor.execute(f'INSERT INTO `{self.database}`.cache_store VALUES (%s,%s,%s,%s,%s)',
                       (legacy, 'USER_DATA', '["legacy"]', now, now + 30))
        cursor.close()
        with patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                patch.object(self.cache, '_get_mysql_pool', return_value=self.pool):
            self.assertTrue(self.cache.user_data_update('watch_later', lambda values: values + ['new']))
            self.assertEqual(self.cache.user_data_get('watch_later'), ['legacy', 'new'])
        cursor = self.admin.cursor()
        cursor.execute(f'SELECT key_hash FROM `{self.database}`.cache_store WHERE key_hash IN (%s,%s)', (legacy, canonical))
        self.assertEqual({row[0] for row in cursor.fetchall()}, {canonical})
        cursor.close()

    def test_atomic_update_rejects_non_transactional_table(self):
        import mysql.connector
        name = 'play_er_engine_' + uuid.uuid4().hex
        cursor = self.admin.cursor()
        cursor.execute(f'CREATE DATABASE `{name}`')
        cursor.close()
        try:
            conn = mysql.connector.connect(**self.config, database=name)
            cur = conn.cursor()
            cur.execute('CREATE TABLE cache_store (key_hash VARCHAR(64) PRIMARY KEY, section VARCHAR(32), '
                        'data LONGTEXT, created_at DOUBLE, expires_at DOUBLE) ENGINE=MyISAM')
            cur.close()
            conn.close()
            pool = self.cache.LazyMySQLPool(**self.config, database=name, pool_size=1, pool_timeout=3)
            try:
                with patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'), \
                        patch.object(self.cache, '_get_mysql_pool', return_value=pool):
                    with self.assertRaises(self.cache.CacheStorageError):
                        self.cache.user_data_update('watch_later', lambda current: ['must-not-write'])
                    self.assertFalse(self.cache.cache_set_preemptive_if_newer(
                        'must-not-write', {'value': 'unsafe'}, time.time() - 1))
                conn = pool.get_connection()
                cur = conn.cursor()
                cur.execute('SELECT COUNT(*) FROM cache_store')
                self.assertEqual(cur.fetchone()[0], 0)
                cur.close()
                pool.put_connection(conn)
            finally:
                pool.close_all()
        finally:
            cursor = self.admin.cursor()
            cursor.execute(f'DROP DATABASE `{name}`')
            cursor.close()

    def test_container_refresh_reuses_database_connection(self):
        with patch.object(self.cache, 'DB_POOL', self.pool), \
                patch.object(self.cache, 'MYSQL_AVAILABLE', True), \
                patch.object(self.cache, 'DB_TYPE', 'MySQL (MariaDB)'):
            def connection_id():
                connection, _ = self.cache._get_db_connection()
                try:
                    cursor = connection.cursor()
                    cursor.execute('SELECT CONNECTION_ID()')
                    value = cursor.fetchone()[0]
                    cursor.close()
                    return value
                finally:
                    connection.close()
            first = connection_id()
            self.cache.safe_refresh()
            self.assertEqual(connection_id(), first)

    def test_reconnect_killed_idle_connection_restores_autocommit(self):
        conn = self.pool.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT CONNECTION_ID()')
        connection_id = cursor.fetchone()[0]
        cursor.close()
        self.pool.put_connection(conn)
        cursor = self.admin.cursor()
        cursor.execute(f'KILL {int(connection_id)}')
        cursor.close()
        recovered = self.pool.get_connection()
        self.assertTrue(recovered.autocommit)
        cursor = recovered.cursor()
        cursor.execute('SELECT 1')
        self.assertEqual(cursor.fetchone(), (1,))
        cursor.close()
        self.pool.put_connection(recovered)
