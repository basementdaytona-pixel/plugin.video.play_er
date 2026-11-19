"""Optional real database checks; set PLAY_ER_TEST_MYSQL_PORT on localhost."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from kodi_test_support import load_module


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
