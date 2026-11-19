import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

cache = load_module('resources.lib.cache_manager')


class PoolTests(unittest.TestCase):
    def pool(self, size=1):
        return cache.LazyMySQLPool(pool_size=size, pool_timeout=0.03)

    def test_reuses_connection_with_one_health_check(self):
        pool = self.pool()
        conn = MagicMock()
        with patch.object(pool, '_connect', return_value=conn) as connect:
            self.assertIs(pool.get_connection(), conn)
            pool.put_connection(conn)
            self.assertIs(pool.get_connection(), conn)
        connect.assert_called_once()
        conn.ping.assert_called_once_with(reconnect=True, attempts=1, delay=0)
        self.assertIs(conn.autocommit, True)
        pool.put_connection(conn)
        pool.close_all()

    def test_duplicate_return_cannot_checkout_connection_twice(self):
        pool = self.pool()
        with patch.object(pool, '_connect', return_value=MagicMock()):
            conn = pool.get_connection()
        pool.put_connection(conn)
        pool.put_connection(conn)
        self.assertIs(pool.get_connection(), conn)
        with self.assertRaises(cache.MySQLPoolTimeoutError):
            pool.get_connection()
        pool.put_connection(conn)
        pool.close_all()

    def test_failed_health_check_discards_connection_and_releases_capacity(self):
        pool = self.pool()
        stale, fresh = MagicMock(), MagicMock()
        with patch.object(pool, '_connect', side_effect=[stale, fresh]):
            pool.put_connection(pool.get_connection())
            stale.ping.side_effect = OSError('server offline')
            with self.assertRaises(OSError):
                pool.get_connection()
            self.assertIs(pool.get_connection(), fresh)
        stale.close.assert_called_once()
        self.assertEqual(pool._connecting, 0)
        pool.put_connection(fresh)
        pool.close_all()

    def test_failed_connect_releases_capacity(self):
        pool = self.pool()
        with patch.object(pool, '_connect', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                pool.get_connection()
        self.assertEqual(pool._connecting, 0)
        self.assertEqual(pool._in_use, set())

    def test_slow_health_check_does_not_block_return_of_another_connection(self):
        pool = self.pool(2)
        first, second = MagicMock(), MagicMock()
        with patch.object(pool, '_connect', side_effect=[first, second]):
            pool.get_connection()
            pool.get_connection()
        pool.put_connection(first)
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        first.ping.side_effect = lambda **kw: (entered.set(), release.wait(2))
        checked_out = []
        worker = threading.Thread(target=lambda: checked_out.append(pool.get_connection()))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            returner = threading.Thread(target=lambda: (pool.put_connection(second), returned.set()))
            returner.start()
            self.assertTrue(returned.wait(0.5), 'network I/O held the pool condition')
        finally:
            release.set()
            worker.join(2)
            returner.join(2)
            for conn in checked_out:
                pool.put_connection(conn)
            pool.close_all()
        self.assertFalse(worker.is_alive())

    def test_shutdown_during_connect_closes_connection(self):
        pool = self.pool()
        conn = MagicMock()
        def connect():
            pool.close_all()
            return conn
        with patch.object(pool, '_connect', side_effect=connect):
            with self.assertRaises(cache.MySQLPoolClosedError):
                pool.get_connection()
        conn.close.assert_called_once()
        self.assertEqual(pool._connecting, 0)
        self.assertEqual(pool._in_use, set())


class MySQLInitializationTests(unittest.TestCase):
    def test_pool_honors_explicit_empty_password(self):
        addon, pool = MagicMock(), MagicMock()
        addon.getSetting.side_effect = lambda key: {'db_pass': ''}.get(key, '')
        with patch.object(cache, 'DB_POOL', None), patch.object(cache, 'MYSQL_AVAILABLE', True), \
                patch.object(cache, 'ADDON', addon), patch.object(cache, 'LazyMySQLPool', return_value=pool) as factory, \
                patch.object(cache, '_ensure_mysql_database') as provision, \
                patch.object(cache, '_init_db_tables', return_value=True):
            self.assertIs(cache._get_mysql_pool(), pool)
        self.assertEqual(factory.call_args.kwargs['password'], '')
        self.assertEqual(provision.call_args.args[3], '')

    def test_provisioning_uses_timeout_and_parameterized_credentials(self):
        connector = MagicMock()
        mysql = SimpleNamespace(connector=connector)
        user, password, database = "test'user", "secret'with\\slash", "test`database"
        with patch.object(cache, 'MYSQL_AVAILABLE', True), patch.object(cache, 'mysql', mysql, create=True):
            cache._ensure_mysql_database('localhost', 3306, user, password, database, 4)
        connector.connect.assert_called_once_with(host='localhost', port=3306, user=user,
                                                  password=password, autocommit=True,
                                                  connection_timeout=4)
        cursor = connector.connect.return_value.cursor.return_value
        self.assertIn('`test``database`', cursor.execute.call_args_list[0].args[0])
        self.assertEqual(cursor.execute.call_args_list[1].args,
                         ("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, '%', password)))
        self.assertEqual(cursor.execute.call_args_list[2].args[1], (user, '%'))


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = patch.multiple(cache, CACHE_DB_PATH=str(Path(self.tmp.name) / 'cache.db'),
                                       DB_TYPE='SQLite', SQLITE_INITIALIZED=False)
        self.settings.start()
        self.addCleanup(self.settings.stop)
        cache.clear_ram_cache()

    def test_section_isolation_and_persistent_round_trip(self):
        self.assertTrue(cache.cache_set('USER_DATA', 'same', {'history': [1, 2]}))
        self.assertTrue(cache.cache_set('TMDB', 'same', {'title': 'Test'}))
        cache.clear_ram_cache()
        value = cache.user_data_get('same')
        self.assertEqual(value, {'history': [1, 2]})
        value['history'].append(3)
        self.assertEqual(cache.user_data_get('same'), {'history': [1, 2]})
        self.assertEqual(cache.cache_get('TMDB', 'same'), {'title': 'Test'})

    def test_sql_read_returns_independent_nested_data(self):
        self.assertTrue(cache.cache_set('USER_DATA', 'nested', {'items': [{'value': 1}]}))
        cache.clear_ram_cache()
        decoded = cache.user_data_get('nested')
        decoded['items'][0]['value'] = 99
        self.assertEqual(cache.user_data_get('nested'), {'items': [{'value': 1}]})

    def test_legacy_row_migrates_without_deleting_other_section(self):
        conn = cache._get_sqlite_connection()
        conn.execute('INSERT INTO cache_store VALUES (?, ?, ?, ?, ?)',
                     (cache._hash_key('legacy'), 'USER_DATA', '{"value": 1}', 1, 1e12))
        conn.commit()
        conn.close()
        self.assertEqual(cache.cache_get('USER_DATA', 'legacy'), {'value': 1})
        self.assertTrue(cache.cache_set('USER_DATA', 'legacy', {'value': 2}))
        cache.clear_ram_cache()
        self.assertEqual(cache.cache_get('USER_DATA', 'legacy'), {'value': 2})


if __name__ == '__main__':
    unittest.main()
