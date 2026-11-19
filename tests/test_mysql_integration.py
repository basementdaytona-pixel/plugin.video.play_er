"""Optional real database checks; set PLAY_ER_TEST_MYSQL_PORT on localhost."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from types import SimpleNamespace

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
