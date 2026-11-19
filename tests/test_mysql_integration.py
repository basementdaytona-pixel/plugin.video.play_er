"""Optional real database checks; set PLAY_ER_TEST_MYSQL_PORT on localhost."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
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
            finally:
                login.close()
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
