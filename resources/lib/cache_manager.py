# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: cache_manager.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import sys
import json
import time
import copy
import sqlite3
import hashlib
import threading
import traceback

import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

from contextlib import contextmanager
from collections import OrderedDict


try:
    import mysql.connector
    from mysql.connector import pooling
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False


from resources.lib.utils_logging import log

from resources.lib.utils_notification import (
    notify_error,
    notify_ok
)

from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_int,
    get_setting_str
)





CACHE_LOCK = threading.Lock()
DB_LOCK = threading.Lock()





try:
    ADDON = xbmcaddon.Addon()
    ADDON_ID = ADDON.getAddonInfo("id")
except Exception:
    ADDON = None
    ADDON_ID = None

IN_MEMORY_CACHE_STATS = {
    "misses": 0,
    "hits": 0,
    "sets": 0,
}





DB_POOL = None
DB_TYPE = "SQLite"
CACHE_DB_PATH = ""
SQLITE_CONN = None
TTL_USER_DATA = 31536000
WINDOW = xbmcgui.Window(10000)

SQLITE_INITIALIZED = False
MYSQL_CHECKOUT_COUNT = 0





def _cache_set_globals(addon=None):
    global ADDON, ADDON_ID, TTL_WATCH, TTL_TRAKT, TTL_TMDB, TTL_CSFD, RAM_TTL, RAM_SIZE, CACHE_DB_PATH, DB_TYPE, TTL_USER_DATA

    with CACHE_LOCK:
        if addon is not None:
            ADDON = addon
            try:
                ADDON_ID = ADDON.getAddonInfo("id")
            except Exception:
                pass

        try:
            if ADDON:
                TTL_WATCH = get_setting_int_with_bounds(ADDON, "cache_ttl_watch", 1) * 3600
                TTL_TRAKT = get_setting_int_with_bounds(ADDON, "cache_ttl_trakt", 24) * 3600
                TTL_TMDB = get_setting_int_with_bounds(ADDON, "cache_ttl_tmdb", 24) * 3600
                TTL_CSFD = get_setting_int_with_bounds(ADDON, "cache_ttl_csfd", 24) * 3600
                RAM_TTL = get_setting_int_with_bounds(ADDON, "cache_ram_ttl", 1) * 3600
                TTL_USER_DATA = get_setting_int_with_bounds(ADDON, "cache_ttl_userdata", 365) * 86400

                raw_ram_size = ADDON.getSetting("cache_ram_size") or "2000"
                RAM_SIZE = int(raw_ram_size) if raw_ram_size.isdigit() else 2000

                DB_TYPE = ADDON.getSetting("db_type") or "SQLite"
                cache_ssd_setting = ADDON.getSetting("cache_data_path")
                base_path = cache_ssd_setting if cache_ssd_setting else "special://userdata/DATA--PLAY/CACHE-DATA/"

                translated_base = xbmcvfs.translatePath(base_path)
                if not xbmcvfs.exists(translated_base):
                    xbmcvfs.mkdirs(translated_base)

                CACHE_DB_PATH = os.path.join(translated_base, "XBMC--PLAY.ER--CACHE.DB")
            else:
                raise Exception("No ADDON available")

        except Exception:
            TTL_USER_DATA = 31536000
            TTL_TRAKT = 86400
            TTL_TMDB = 86400
            TTL_CSFD = 86400
            TTL_WATCH = 3600
            RAM_TTL = 3600
            RAM_SIZE = 1000
            DB_TYPE = "SQLite"
            CACHE_DB_PATH = xbmcvfs.translatePath("special://userdata/DATA--PLAY/CACHE-DATA/XBMC--PLAY.ER--CACHE.DB")



CACHE_RAM = OrderedDict()
_cache_set_globals()



class CacheStorageError(RuntimeError):
    """Persistent data could not be read or committed to its configured backend."""


PERSISTENT_SECTIONS = frozenset(("USER_DATA", "SERIES_DB", "WATCHED_DB", "URL_CACHE"))


class MySQLPoolTimeoutError(TimeoutError):
    """Raised when every configured MySQL connection stays checked out."""


class MySQLPoolClosedError(RuntimeError):
    """Raised when a caller tries to acquire from a shut down pool."""


class LazyMySQLPool:
    def __init__(self, **dbconfig):
        self.pool_size = max(1, int(dbconfig.pop("pool_size", 10)))
        self.pool_name = dbconfig.pop("pool_name", "XBMC--PLAY.ER--POOL-LAZY")
        self.pool_timeout = max(
            0.01,
            float(dbconfig.pop("pool_timeout", dbconfig.get("connection_timeout", 10))),
        )
        self.dbconfig = dbconfig
        self._available = []
        self._in_use = set()
        self._connecting = 0
        self._closed = False
        self._condition = threading.Condition()

    def get_connection(self):
        deadline = time.monotonic() + self.pool_timeout
        while True:
            with self._condition:
                if self._closed:
                    raise MySQLPoolClosedError("MySQL pool is closed")
                if self._available:
                    conn = self._available.pop()
                    self._in_use.add(id(conn))
                    is_new = False
                elif len(self._in_use) + self._connecting < self.pool_size:
                    conn = None
                    self._connecting += 1
                    is_new = True
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MySQLPoolTimeoutError(
                            f"Timed out waiting for a MySQL connection from {self.pool_name}"
                        )
                    self._condition.wait(remaining)
                    continue

            # Connector health checks perform network I/O. Reserve capacity
            # under the condition, then validate without blocking other workers.
            try:
                if conn is None:
                    conn = self._connect()
                    conn.autocommit = True
                else:
                    conn.ping(reconnect=True, attempts=1, delay=0)
                    # Reconnection can restore the connector's default session.
                    conn.autocommit = True
            except Exception:
                with self._condition:
                    if conn is not None:
                        self._in_use.discard(id(conn))
                    # Only new connection attempts consume _connecting.
                    # Existing connections were already counted in _in_use.
                    if is_new:
                        self._connecting -= 1
                    self._condition.notify_all()
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                raise

            with self._condition:
                if is_new:
                    self._connecting -= 1
                if self._closed:
                    should_close = True
                    self._in_use.discard(id(conn))
                else:
                    self._in_use.add(id(conn))
                    should_close = False
                self._condition.notify_all()
            if should_close:
                conn.close()
                raise MySQLPoolClosedError("MySQL pool was closed while opening a connection")
            return conn

    def _connect(self):
        return mysql.connector.connect(**self.dbconfig)

    def put_connection(self, conn):
        if conn is None:
            return
        with self._condition:
            # Duplicate or foreign returns must never make a connection
            # available to two workers at the same time.
            if id(conn) not in self._in_use:
                return
            self._in_use.remove(id(conn))
            if not self._closed:
                self._available.append(conn)
                should_close = False
            else:
                should_close = True
            self._condition.notify_all()
        if should_close:
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self):
        with self._condition:
            self._closed = True
            available, self._available = self._available, []
            self._condition.notify_all()
        for conn in available:
            try:
                conn.close()
            except Exception:
                pass


def _ensure_mysql_database(host, port, user, password, db_name, timeout=10):
    if not MYSQL_AVAILABLE:
        return
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            autocommit=True,
            connection_timeout=timeout
        )
        cursor = conn.cursor()
        # Identifiers cannot be bound as SQL parameters; escape backticks.
        database_identifier = db_name.replace("`", "``")
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database_identifier}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        try:
            cursor.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, "%", password))
        except Exception:
            pass
        try:
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{database_identifier}`.* TO %s@%s", (user, "%"))
            cursor.execute("FLUSH PRIVILEGES;")
        except Exception:
            pass
        log(f"CACHE - MYSQL DATABASE ENSURED SUCCESFULLY [ {db_name} ]", xbmc.LOGINFO)
    except Exception as e:
        log(f"CACHE - PRE-INIT MYSQL DATABASE CHECK/CREATION FAILED: {e}", xbmc.LOGWARNING)
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _get_mysql_pool():
    global DB_POOL
    if DB_POOL:
        return DB_POOL
    if not MYSQL_AVAILABLE:
        return None
    with DB_LOCK:
        if DB_POOL:
            return DB_POOL
        try:
            cfg_pool_size = get_setting_int_with_bounds(ADDON, "db_pool_size", 10)
            db_host = ADDON.getSetting("db_host") if ADDON and ADDON.getSetting("db_host") else "127.0.0.1"
            db_port = get_setting_int_with_bounds(ADDON, "db_port", 3306) if ADDON else 3306
            db_user = ADDON.getSetting("db_user") if ADDON and ADDON.getSetting("db_user") else "root"
            db_pass = ADDON.getSetting("db_pass") if ADDON else "PLAYER123!"
            db_name = ADDON.getSetting("db_name") if ADDON and ADDON.getSetting("db_name") else "XBMC--PLAY.ER"
            db_timeout = get_setting_int_with_bounds(ADDON, "db_timeout", 10) if ADDON else 10

            _ensure_mysql_database(db_host, db_port, db_user, db_pass, db_name, db_timeout)

            dbconfig = {
                "host": db_host,
                "port": db_port,
                "user": db_user,
                "password": db_pass,
                "database": db_name,
                "autocommit": True,
                "connection_timeout": db_timeout,
                "pool_timeout": db_timeout,
                "pool_size": max(1, cfg_pool_size),
                "pool_name": "XBMC--PLAY.ER--POOL-CACHE",
            }
            pool = LazyMySQLPool(**dbconfig)
            conn = None
            initialized = False
            try:
                conn = pool.get_connection()
                initialized = _init_db_tables(conn, is_mysql=True)
            except Exception as e:
                log(f"CACHE - MySQL Init Table Error : {e}", xbmc.LOGWARNING)
            finally:
                if not initialized:
                    pool.close_all()
                if conn is not None:
                    pool.put_connection(conn)
            if not initialized:
                return None
            # Publish only a completely initialized pool.
            DB_POOL = pool
            return DB_POOL
        except Exception as e:
            log(f"CACHE - MYSQL POOL CONNECTION FAILED : {e}", xbmc.LOGERROR)
            DB_POOL = None
            return None


def _get_db_connection():
    global SQLITE_CONN, MYSQL_CHECKOUT_COUNT

    if DB_TYPE == "MySQL (MariaDB)":
        pool = _get_mysql_pool()
        if pool:
            try:
                for attempt in range(5):
                    conn = None
                    try:
                        conn = pool.get_connection()
                        with DB_LOCK:
                            MYSQL_CHECKOUT_COUNT += 1

                        class _WrappedConnection(object):
                            def __init__(self, real_conn, real_pool):
                                self._real = real_conn
                                self._pool = real_pool
                                self._closed = False

                            def close(self):
                                global MYSQL_CHECKOUT_COUNT
                                if self._closed:
                                    return
                                self._closed = True
                                try:
                                    self._pool.put_connection(self._real)
                                finally:
                                    try:
                                        with DB_LOCK:
                                            MYSQL_CHECKOUT_COUNT = max(0, MYSQL_CHECKOUT_COUNT - 1)
                                    except Exception:
                                        pass

                            def __getattr__(self, name):
                                return getattr(self._real, name)

                        return _WrappedConnection(conn, pool), True

                    except (MySQLPoolTimeoutError, MySQLPoolClosedError) as inner_e:
                        log(f"CACHE - MYSQL POOL UNAVAILABLE : {inner_e}", xbmc.LOGWARNING)
                        return None, True
                    except Exception as inner_e:
                        log(f"CACHE - MYSQL ATTEMPT {attempt + 1} FAILED : {inner_e}", xbmc.LOGWARNING)
                        try:
                            if conn:
                                pool.put_connection(conn)
                        except Exception:
                            pass
                        time.sleep(min(0.25 * (2 ** attempt), 1.0))
                        continue
                return None, True
            except Exception as e:
                log(f"CACHE - MYSQL CONNECTION ERROR : {e}", xbmc.LOGERROR)
                return None, True
        return None, True
    return _get_sqlite_connection(), False


@contextmanager
def db_connection():
    conn, is_mysql = _get_db_connection()
    try:
        yield conn, is_mysql
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _get_sqlite_connection():
    try:
        db_dir = os.path.dirname(CACHE_DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(CACHE_DB_PATH, check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row

        global SQLITE_INITIALIZED
        if not SQLITE_INITIALIZED:
            try:
                SQLITE_INITIALIZED = _init_db_tables(conn, is_mysql=False)
            except Exception as e:
                log(f"CACHE - SQLITE INIT FAILED DURING FIRST CONNECTION: {e}", xbmc.LOGERROR)

        return conn
    except Exception as e:
        log(f"CACHE - SQLITE INITIALIZATION FAILED : {e}", xbmc.LOGERROR)
        return None


def _ensure_mysql_index(cursor, index_name, column_name):
    cursor.execute(
        "SELECT 1 FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s "
        "AND index_name = %s LIMIT 1",
        ("cache_store", index_name),
    )
    if cursor.fetchone():
        return

    try:
        cursor.execute(
            f"CREATE INDEX `{index_name}` ON `cache_store` (`{column_name}`)"
        )
    except Exception as e:
        # Another Kodi process may have created the index after our metadata
        # check. Ignore only that duplicate-name race; surface other SQL errors.
        if getattr(e, "errno", None) != 1061:
            raise


def _init_db_tables(conn, is_mysql=False):
    cursor = conn.cursor()
    try:
        if is_mysql:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_store (
                    key_hash VARCHAR(64) PRIMARY KEY,
                    section VARCHAR(32),
                    data LONGTEXT,
                    created_at DOUBLE,
                    expires_at DOUBLE
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
            """)
            _ensure_mysql_index(cursor, "idx_section", "section")
            _ensure_mysql_index(cursor, "idx_expires", "expires_at")
        else:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA cache_size=-10000;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_store (
                    key_hash TEXT PRIMARY KEY,
                    section TEXT,
                    data TEXT,
                    created_at REAL,
                    expires_at REAL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_section ON cache_store (section)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache_store (expires_at)")

        if not is_mysql:
            conn.commit()
        return True
    except Exception as e:
        log(f"CACHE - TABLE INITIALIZATION ERROR : {e}", xbmc.LOGERROR)
        return False
    finally:
        cursor.close()


def _hash_key(key):
    try:
        if isinstance(key, (dict, list, tuple)):
            key = json.dumps(key, sort_keys=True)
        return hashlib.md5(str(key).encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.md5(repr(key).encode("utf-8")).hexdigest()


def _folder_ttl(folder):
    if folder in ["USER_DATA", "SERIES_DB", "WATCHED_DB", "URL_CACHE"]:
        return TTL_USER_DATA
    if folder == "WATCH":
        return TTL_WATCH
    if folder == "TRAKT":
        return TTL_TRAKT
    if folder == "CSFD":
        return TTL_CSFD
    if folder == "TMDB":
        return TTL_TMDB
    return 86400


# =========================================================================
#  WINDOW PROPERTY CACHE (PRO BLESKOVÝ ARCTIC FUSE 3 WIDGET START)
# =========================================================================


def window_cache_get(key):

    """
    MEMORY CACHE :: AF3 WIDGETS
    -- Rychlá paměťová cache v Kodi Window (10000) pro bleskové načítání AF3 widgetů.
    """

    try:
        prop = WINDOW.getProperty(f"play_er.wcache.{key}")
        if prop:
            item = json.loads(prop)
            if time.time() < item.get("exp", 0):
                return item.get("data")
            WINDOW.clearProperty(f"play_er.wcache.{key}")
    except Exception:
        pass
    return None


def window_cache_set(key, data, ttl=300):
    try:
        payload = json.dumps({"exp": time.time() + ttl, "data": data}, ensure_ascii=False)
        WINDOW.setProperty(f"play_er.wcache.{key}", payload)
    except Exception:
        pass


def user_data_get(key):
    return cache_get("USER_DATA", key, max_age=TTL_USER_DATA)


def user_data_set(key, data):
    return cache_set("USER_DATA", key, data)


def get_all_from_section(section):
    items = []
    conn, is_mysql = _get_db_connection()
    if not conn:
        return items
    lock_context = DB_LOCK if not is_mysql else threading.RLock()
    try:
        with lock_context:
            cursor = conn.cursor()
            sql = "SELECT data FROM cache_store WHERE section = %s" if is_mysql else "SELECT data FROM cache_store WHERE section = ?"
            cursor.execute(sql, (section,))
            rows = cursor.fetchall()
            for row in rows:
                try:
                    val = row[0] if is_mysql else row['data']
                    items.append(json.loads(val))
                except Exception:
                    pass
    except Exception as e:
        log(f"CACHE - GET SECTION ERROR: {e}", xbmc.LOGERROR)
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return items


def cache_get(folder, key, max_age=None):
    global IN_MEMORY_CACHE_STATS
    key_hash = _hash_key((folder, key))
    ram_key = f"{folder}:{key_hash}"
    with CACHE_LOCK:
        if ram_key in CACHE_RAM:
            value, cached_at, created_at, expires_at = CACHE_RAM[ram_key]
            now = time.time()
            if (now - cached_at) < RAM_TTL and not _cache_expired(now, created_at, expires_at, max_age):
                IN_MEMORY_CACHE_STATS["hits"] += 1
                CACHE_RAM.move_to_end(ram_key)
                return copy.deepcopy(value) if isinstance(value, (dict, list)) else value
            else:
                del CACHE_RAM[ram_key]
        IN_MEMORY_CACHE_STATS["misses"] += 1

    conn, is_mysql = _get_db_connection()
    if not conn:
        if folder in PERSISTENT_SECTIONS:
            raise CacheStorageError(f"Cannot read {folder}: configured database unavailable")
        return None
    lock_context = DB_LOCK if not is_mysql else threading.RLock()
    try:
        with lock_context:
            cursor = conn.cursor()
            now = time.time()
            placeholder = "%s" if is_mysql else "?"
            # Read legacy keys only from their original section. New writes use
            # a section-qualified key, without a destructive database migration.
            sql = (
                "SELECT data, created_at, expires_at FROM cache_store "
                f"WHERE section = {placeholder} AND key_hash IN ({placeholder}, {placeholder}) "
                f"ORDER BY CASE WHEN key_hash = {placeholder} THEN 0 ELSE 1 END LIMIT 1"
            )
            cursor.execute(sql, (folder, key_hash, _hash_key(key), key_hash))
            row = cursor.fetchone()
            if row:
                if is_mysql:
                    data_json, created_at, expires_at = row
                else:
                    data_json, created_at, expires_at = row['data'], row['created_at'], row['expires_at']

                if _cache_expired(now, created_at, expires_at, max_age):
                    # A caller's shorter max_age must not delete data still
                    # usable by another caller (or race with a fresh write).
                    return None

                try:
                    data = json.loads(data_json)
                    with CACHE_LOCK:
                        _store_in_ram(ram_key, data, created_at, expires_at)
                    # _store_in_ram keeps its own copy, so this freshly decoded
                    # value can be returned without a second deep copy.
                    return data
                except Exception as e:
                    if folder in PERSISTENT_SECTIONS:
                        raise CacheStorageError(f"Invalid stored data in {folder}") from e
                    return None
            return None
    except Exception as e:
        log(f"CACHE - READ ERROR: {e}", xbmc.LOGERROR)
        if folder in PERSISTENT_SECTIONS:
            raise CacheStorageError(f"Cannot read {folder}") from e
        return None
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def _cache_expired(now, created_at, expires_at, max_age):
    """Keep the explicit max_age override consistent between RAM and SQL."""
    return now - created_at >= max_age if max_age is not None else now >= expires_at


def _store_in_ram(ram_key, data, created_at, expires_at):
    """Caller holds CACHE_LOCK; retain source age separately from RAM residency."""
    if RAM_SIZE <= 0:
        return
    CACHE_RAM[ram_key] = (copy.deepcopy(data), time.time(), created_at, expires_at)
    CACHE_RAM.move_to_end(ram_key)
    while len(CACHE_RAM) > RAM_SIZE:
        CACHE_RAM.popitem(last=False)


def cache_set(folder, key, data):
    global IN_MEMORY_CACHE_STATS
    key_hash = _hash_key((folder, key))
    ram_key = f"{folder}:{key_hash}"
    now = time.time()
    ttl = _folder_ttl(folder)
    expires_at = now + ttl
    data = copy.deepcopy(data)
    conn, is_mysql = _get_db_connection()
    if not conn:
        if folder in PERSISTENT_SECTIONS:
            raise CacheStorageError(f"Cannot write {folder}: configured database unavailable")
        return False
    lock_context = DB_LOCK if not is_mysql else threading.RLock()
    try:
        with lock_context:
            data_json = json.dumps(data, ensure_ascii=False)
            cursor = conn.cursor()
            if is_mysql:
                cursor.execute("""
                    INSERT INTO cache_store (key_hash, section, data, created_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        data = VALUES(data),
                        created_at = VALUES(created_at),
                        expires_at = VALUES(expires_at)
                """, (key_hash, folder, data_json, now, expires_at))
            else:
                cursor.execute("""
                    INSERT OR REPLACE INTO cache_store (key_hash, section, data, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (key_hash, folder, data_json, now, expires_at))
            # Only retire this section's legacy row after its replacement is
            # written; unrelated sections and unread legacy data remain intact.
            placeholder = "%s" if is_mysql else "?"
            cursor.execute(
                f"DELETE FROM cache_store WHERE key_hash = {placeholder} AND section = {placeholder}",
                (_hash_key(key), folder),
            )
            if not is_mysql:
                conn.commit()
            with CACHE_LOCK:
                _store_in_ram(ram_key, data, now, expires_at)
                IN_MEMORY_CACHE_STATS["sets"] += 1
            return True
    except Exception as e:
        log(f"CACHE - WRITE ERROR : {e}", xbmc.LOGERROR)
        if folder in PERSISTENT_SECTIONS:
            raise CacheStorageError(f"Cannot write {folder}") from e
        return False
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


# FIX PRE-EMPTIVE AND FILTERS [RAM MENU ACTION MUST NOT CLEAR DATABASE]
def clear_ram_cache():
    global IN_MEMORY_CACHE_STATS
    with CACHE_LOCK:
        CACHE_RAM.clear()
        IN_MEMORY_CACHE_STATS = {'hits': 0, 'misses': 0, 'sets': 0}


def cache_clear(folder=None):
    global CACHE_RAM, IN_MEMORY_CACHE_STATS
    with CACHE_LOCK:
        if folder:
            keys_to_del = [k for k in CACHE_RAM.keys() if k.startswith(f"{folder}:")]
            for k in keys_to_del:
                del CACHE_RAM[k]
        else:
            CACHE_RAM.clear()
            IN_MEMORY_CACHE_STATS = {"hits": 0, "misses": 0, "sets": 0}

    conn, is_mysql = _get_db_connection()
    if not conn:
        notify_error("Nelze se připojit k nastavené databázi", "CACHE")
        return False
    lock_context = DB_LOCK if not is_mysql else threading.RLock()
    try:
        with lock_context:
            cursor = conn.cursor()
            if folder:
                sql = "DELETE FROM cache_store WHERE section = %s" if is_mysql else "DELETE FROM cache_store WHERE section = ?"
                cursor.execute(sql, (folder,))
                if not is_mysql:
                    conn.commit()
            else:
                sql = "DELETE FROM cache_store WHERE section NOT IN ('USER_DATA', 'SERIES_DB', 'WATCHED_DB', 'URL_CACHE')"
                cursor.execute(sql)
                if not is_mysql:
                    conn.commit()
                    cursor.execute("VACUUM")

        notify_ok(f"CACHE CLEAR ({folder or 'ALL'}) - HOTOVO", "CACHE")
    except Exception as e:
        log(f"CACHE - CLEAR ERROR: {e}", xbmc.LOGERROR)
        notify_error("Chyba při mazání cache", "CACHE")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def reset_database():
    if not xbmcgui.Dialog().yesno(
        f"[B][COLOR orange]○○○ DELETE DATABASE ○○○[/COLOR][/B]",
        f"[B][COLOR orange]Opravdu chcete smazat SQLite/MySQL/RAM databáze ?[/COLOR][/B]\n\n"
        "[B]NÁSLEDUJÍCÍ DATA BUDOU NAVŽDY ZTRACENA :[/B]\n\n"
        " - Historie přehrávání (PLAYBACK)\n"
        " - Položky CHCI VIDĚT (WATCH LATER)\n"
        " - Cache metadat (TMDB, ČSFD, TRAKT)\n"
        " - Cache funkce SLEDOVANÉ (MOST WATCHED)\n"
        " - Obsah paměťové cache RAM\n"
    ):
        return

    global CACHE_RAM, IN_MEMORY_CACHE_STATS
    with CACHE_LOCK:
        CACHE_RAM.clear()
        IN_MEMORY_CACHE_STATS = {"hits": 0, "misses": 0, "sets": 0}

    conn, is_mysql = _get_db_connection()
    if not conn:
        notify_error("ERROR : NELZE SE PŘIPOJIT K DATABÁZI", "RESET-DB")
        return

    lock_context = DB_LOCK if not is_mysql else threading.RLock()
    try:
        with lock_context:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS cache_store")
            if not _init_db_tables(conn, is_mysql):
                raise RuntimeError("cache_store could not be recreated")
            if not is_mysql:
                conn.commit()
                cursor.execute("VACUUM")
        log(f"CACHE - RESET DATABASE COMPLETE ({DB_TYPE})", xbmc.LOGINFO)
        notify_ok("COMPLETE Databáze byla úspěšně resetována", category="SYSTEM", time=5000)
        safe_refresh()
    except Exception as e:
        log(f"CACHE - RESET FAILED : {e}", xbmc.LOGERROR)
        notify_error(f"ERROR Chyba resetování databáze: {e}", category="SYSTEM")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def get_db_stats():
    count = 0
    size_mb = 0.0
    conn_status = "DISCONNECTED"
    conn = None
    cursor = None
    try:
        conn, is_mysql = _get_db_connection()
        if conn:
            conn_status = "CONNECTED"
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cache_store")
            row = cursor.fetchone()
            if row:
                count = row[0]
            if not is_mysql and xbmcvfs.exists(CACHE_DB_PATH):
                size_mb = xbmcvfs.Stat(CACHE_DB_PATH).st_size() / (1024 * 1024)
            elif is_mysql:
                try:
                    db_name = ADDON.getSetting("db_name")
                    cursor.execute("SELECT SUM(data_length + index_length) / 1024 / 1024 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'cache_store'", (db_name,))
                    row_size = cursor.fetchone()
                    if row_size and row_size[0]:
                        size_mb = float(row_size[0])
                except Exception:
                    pass
        else:
            conn_status = "ERROR"
    except Exception:
        conn_status = "EXCEPTION"
    finally:
        try:
            if cursor:
                cursor.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass
    return count, size_mb, conn_status


def close_mysql_pool():
    global DB_POOL
    if not MYSQL_AVAILABLE:
        return
    with DB_LOCK:
        try:
            if DB_POOL:
                try:
                    DB_POOL.close_all()
                except Exception as e:
                    log(f"CACHE - Error closing MySQL pool : {e}", xbmc.LOGWARNING)
                DB_POOL = None
                log("CACHE - MYSQL POOL CLOSED", xbmc.LOGINFO)
        except Exception as e:
            log(f"CACHE - close_mysql_pool error : {e}", xbmc.LOGERROR)


def safe_refresh():
    try:
        close_mysql_pool()
    except Exception:
        pass
    try:
        xbmc.executebuiltin("Container.Refresh()")
    except Exception:
        pass
