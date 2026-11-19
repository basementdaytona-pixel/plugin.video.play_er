# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: plugin.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 17.10.2026 (Fix: Trakt Scrobbling Lifecycle, Kodi 22 Piers, AF3)
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import os
import posixpath
import re
import sys
import json
import time
import base64
import random
import zipfile
import requests
import datetime
import threading
import traceback
import gc
from xml.sax.saxutils import escape
from urllib.parse import parse_qsl, urlparse, quote

import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon
import xbmcplugin

from resources.lib.settings_monitor import SettingsMonitor
from resources.lib.dialog_menu import display_player_menu
from resources.lib.trakt_episodes import check_new_episodes
from resources.lib.utils_logging import log
from resources.lib.csfd import CSFD
from resources.lib.tmdb import TMDB
from resources.lib import cache_manager
from resources.lib import tmdb_account
from resources.lib import generator
from resources.lib import actions
from resources.lib import trakt
from resources.lib.utils_files import SafeVFSFile
from resources.lib.utils_tmdbhelper import run_tmdbhelper_setup
from resources.lib.utils_settings import (
    SafeAddonWrapper,
    get_setting_float_with_bounds,
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_int,
    get_setting_str
)
from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)
from resources.lib.utils_filter import (
    clean_title_for_tmdb,
    clean_display_title,
    FilterUtils,
    encode
)
from resources.lib.utils_theme import Colors, Icons
from resources.lib.ui_builder import (
    create_episodes_menu,
    create_seasons_menu,
    create_series_menu,
    set_view_mode
)
from resources.lib.utils import (
    get_meta_from_cache,
    store_meta_in_cache,
    pop_dialog_select,
    safe_post,
    safe_get,
    get_url
)

PLUGIN_LOCK = threading.Lock()
telegram_manager = None


def get_telegram_manager():
    global telegram_manager
    with PLUGIN_LOCK:
        if telegram_manager is None:
            from resources.lib.telegram import TelegramManager
            telegram_manager = TelegramManager(addon, log)
        return telegram_manager


_url = sys.argv[0]
_handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1

addon = SafeAddonWrapper(xbmcaddon.Addon(id="plugin.video.play_er"))
profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))

ADDON_NAME = "| PLAY.ER |"
SECURITY_DIR = xbmcvfs.translatePath("special://masterprofile/DATA--PLAY/SECURITY/")
if not xbmcvfs.exists(SECURITY_DIR):
    xbmcvfs.mkdirs(SECURITY_DIR)

IP_LOG_FILE = os.path.join(SECURITY_DIR, "IP.LOG")
IP_CACHE_FILE = os.path.join(SECURITY_DIR, "IP.CACHE")
IP_LAST_SENT_FILE = os.path.join(SECURITY_DIR, "IP.LAST")
IP_LOG_INTERVAL_SECONDS = 12 * 60 * 60

history_path = None
cache_file_path = None
_notification_check_done = False
playback_started_internally = False
main_window = xbmcgui.Window(10000)

SETTING_ID_SECURITY_DIR = "security_dir"
SETTING_ID_HISTORY_DIR = "history_dir"
SETTING_ID_DOWNLOAD_DIR = "download"
SETTING_ID_LIBRARY_DIR = "library_path"
DEFAULT_SECURITY_DIR = "special://masterprofile/DATA--PLAY/SECURITY/"
DEFAULT_HISTORY_DIR = "special://masterprofile/DATA--PLAY/HISTORY/"
DEFAULT_LIBRARY_DIR = "special://masterprofile/Database/PLAY-BASE/LIBRARY/"
DEFAULT_DOWNLOAD_DIR = "special://masterprofile/DATA--PLAY/DOWNLOAD/"


def player_notify(message, level="info", time=5000):
    if level == "ok":
        notify_ok(message, category="PLAY.ER", time=time)
    elif level == "error":
        notify_error(message, category="PLAY.ER", time=time)
    else:
        notify_info(message, category="PLAY.ER", time=time)


def _get_context_menu(menu_type, **kwargs):
    ctx = []
    props = kwargs.get('props', {})
    title = kwargs.get('title') or props.get('title', '')
    tmdb_id = kwargs.get('tmdb_id') or props.get('tmdb_id', '')
    media_type = kwargs.get('media_type') or props.get('media_type', 'movie')
    year = kwargs.get('year') or props.get('year', '')
    poster = kwargs.get('poster') or props.get('poster', '')
    plot = kwargs.get('plot') or props.get('plot', '')
    query = kwargs.get('query', '')
    context_type = kwargs.get('context_type', 'general')
    action = kwargs.get('action', '')

    ITEMS = {
        'player_menu': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu', tmdb_id=tmdb_id, media_type=media_type, title=title, context=context_type, props=json.dumps(props))})"),
        'player_menu_basic': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu')})"),
        'refresh_addon': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='apply_settings_and_refresh')})"),
        'settings': (f"[COLOR {Colors.LIMEGREEN}][ MENU NASTAVENÍ ][/COLOR]", "Addon.OpenSettings(plugin.video.play_er)"),
        'refresh_addon_alt': (f"[COLOR {Colors.ORANGE}][ REFRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='apply_settings_and_refresh')})"),
        'system_metric': (f"[COLOR {Colors.ORANGE}][ SYSTEM METRIC ] [/COLOR]", f"RunPlugin({get_url(action='show_metrics')})"),
        'telegram_backup': (f"[COLOR {Colors.ORANGE}]► TELEGRAM ZÁLOHA[/COLOR]", f"RunPlugin({get_url(action='backup_settings')})"),
        'telegram_report': (f"[COLOR {Colors.ORANGE}]► TELEGRAM REPORT[/COLOR]", f"RunPlugin({get_url(action='send_accounts')})"),
        'clear_caches': (f"[COLOR {Colors.ORCHID}]► CLEAR ALL CACHES[/COLOR]", f"RunPlugin({get_url(action='clear_cache')})"),
        'delete_database': (f"[COLOR {Colors.ORCHID}]► DELETE DATABASE[/COLOR]", f"RunPlugin({get_url(action='reset_database')})"),
        'help_info': (f"[COLOR {Colors.ORANGE}]► HELP : SETTINGS[/COLOR]", f"RunPlugin({get_url(action='show_help')})"),
        'help_trakt': (f"[COLOR {Colors.ORANGE}]► HELP : API TRAKT[/COLOR]", f"RunPlugin({get_url(action='show_account_help')})"),
        'help_filter': (f"[COLOR {Colors.ORANGE}]► HELP : SET FILTER[/COLOR]", f"RunPlugin({get_url(action='show_filter_help')})"),
        'help_telegram': (f"[COLOR {Colors.ORANGE}]► HELP : TELEGRAM[/COLOR]", f"RunPlugin({get_url(action='show_telegram_help')})"),
        'help_command': (f"[COLOR {Colors.ORANGE}]► HELP : COMMAND[/COLOR]", f"RunPlugin({get_url(action='show_command_help')})"),
        'history_search': (f"[COLOR {Colors.ORANGE}]► HISTORIE HLEDÁNÍ[/COLOR]", f"ActivateWindow(Videos,{get_url(action='listing_history')},return)"),
        'play_random': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT NÁHODNĚ[/COLOR]", f"RunPlugin({get_url(action='play_random')})"),
        'quick_play_movie': (f"[COLOR {Colors.ORANGE}][ QUICK : FILM ][/COLOR]", f"RunPlugin({get_url(action=action)})"),
        'quick_play_series': (f"[COLOR {Colors.ORANGE}][ QUICK : SERIÁL ][/COLOR]", f"RunPlugin({get_url(action=action)})"),
        'quick_play_episode': (f"[COLOR {Colors.ORANGE}][ QUICK : EPIZODA ][/COLOR]", f"RunPlugin({get_url(action=action, direct='1')})"),
        'remove_search_item': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODSTRANIT POLOŽKU[/COLOR]", f"RunPlugin({get_url(action='delete_search_history_item', query=query)})"),
        'clear_history': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]VYMAZAT HISTORII[/COLOR]", f"RunPlugin({get_url(action='clear_search_history')})"),
        'watch_later': (f"[COLOR {Colors.ORANGE}]► SLEDOVAT POZDĚJI[/COLOR]", f"RunPlugin({get_url(action='add_to_watch_later', meta=json.dumps(props))})"),
        'find_similar': (f"[COLOR {Colors.YELLOW}]► HLEDAT PODOBNÉ[/COLOR]", f"RunPlugin({get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})"),
        'ai_similar': (f"[COLOR {Colors.ORCHID}]► AI - PODOBNOST[/COLOR]", f"Container.Update({get_url(action='ai_similar', title=title, year=year, media_type=media_type)})"),
        'ai_trivia': (f"[COLOR {Colors.ORCHID}]► AI - ZAJÍMAVOST[/COLOR]", f"RunPlugin({get_url(action='gemini_trivia', title=title, year=year, media_type=media_type)})"),
        'play_trailer': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILER[/COLOR]", f"RunPlugin({get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=media_type)})"),
        'share': _get_community_share_context(title, tmdb_id, media_type, year, poster, plot, show_title=props.get('tv_show_title') or kwargs.get('show_title', '')),
        'library': (f"[COLOR {Colors.ORANGE}]► OSOBNÍ KNIHOVNA[/COLOR]", f"RunPlugin({get_url(action='library', tmdb_id=tmdb_id, media_type=media_type, title=title, year=year)})"),
        'tmdb_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT WATCHLIST[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_favorites': (f"[COLOR {Colors.ORANGE}]► PŘIDAT OBLÍBENÉ[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_rating': (f"[COLOR {Colors.ORANGE}]► PŘIDAT HODNOCENÍ[/COLOR]", f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})"),
        'trakt_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT TRAKTLIST[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist_tmdb', media_type='show' if media_type == 'tv' else 'movie', tmdb_id=tmdb_id)})"),
        'refresh_cache': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='clear_csfd_cache')})"),
        'info_series': (f"[COLOR {Colors.ORANGE}]► INFORMACE SERIÁLU[/COLOR]", f"RunPlugin({get_url(action='listing_tmdb_tv', tmdb_id=tmdb_id, meta=json.dumps({'title': title}))})"),
        'watch_later_remove': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT Z WATCHLATER[/COLOR]", f"RunPlugin({get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type, **({'season': props.get('season'), 'episode': props.get('episode')} if media_type == 'episode' else {}))})"),
        'tmdb_watchlist_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z WATCHLISTU[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_favorites_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z OBLÍBENÝCH[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_rating_remove': (f"[COLOR {Colors.RED}]► ODEBRAT HODNOCENÍ[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_rating', tmdb_id=tmdb_id, media_type=media_type)})"),
    }

    if context_type == 'new_episodes':
        ctx.append((f"[COLOR {Colors.RED}]► ODEBRAT EPIZODU[/COLOR]",
                    f"RunPlugin({get_url(action='remove_new_episode', meta=json.dumps(props))})"))

    if context_type == 'watch_later': ITEMS['watch_later'] = ITEMS['watch_later_remove']
    if context_type == 'watchlist': ITEMS['tmdb_watchlist'] = ITEMS['tmdb_watchlist_remove']
    if context_type == 'favorites': ITEMS['tmdb_favorites'] = ITEMS['tmdb_favorites_remove']
    if context_type == 'rated': ITEMS['tmdb_rating'] = ITEMS['tmdb_rating_remove']

    LAYOUTS = {
        'default': ['player_menu_basic', 'refresh_addon', 'settings'],
        'main_settings': ['refresh_addon_alt', 'system_metric', 'player_menu_basic', 'telegram_backup', 'telegram_report', 'clear_caches', 'delete_database', 'help_info', 'help_trakt', 'help_filter', 'help_telegram', 'help_command', 'settings'],
        'main_search': ['history_search', 'play_random', 'player_menu_basic', 'settings'],
        'search_history': ['remove_search_item', 'clear_history', 'player_menu_basic', 'settings'],
        'csfd_folder': ['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'share', 'library', 'player_menu_basic', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'refresh_cache', 'settings'],
        'continue_watching': ['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'share', 'library', 'player_menu', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'refresh_cache', 'settings'],
        'trakt_next': ['info_series', 'watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'share', 'library', 'player_menu', 'trakt_watchlist', 'refresh_cache', 'settings'],
        'media': ['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'share', 'library', 'player_menu', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'refresh_cache', 'settings'],
    }

    if menu_type == 'quick_play':
        q_key = 'quick_play_episode' if action == 'continue_trigger_main' else ('quick_play_series' if 'series' in action else 'quick_play_movie')
        layout = [q_key, 'player_menu_basic', 'settings']
    else:
        layout = LAYOUTS.get(menu_type, LAYOUTS['default'])

    for key in layout:
        item = ITEMS.get(key)
        if item:
            ctx.append(item)

    return ctx


def _get_main_menu_context(action, quick_action=""):
    """Attach item-specific commands while retaining common menu controls."""
    layout = 'main_search' if action == 'listing_search' else ('main_settings' if action == 'open_settings' else 'default')
    ctx = _get_context_menu(layout)
    commands = {
        'continue_trigger_main': (f'[COLOR {Colors.ORANGE}]► CONTINUE PLAY[/COLOR]', 'continue_quick_play_action', {}),
        'ai_daily_mix': (f'[COLOR {Colors.ORANGE}]► AI-TODAY NEW[/COLOR]', 'ai_daily_refresh', {}),
        'ai_recommend_for_me': (f'[COLOR {Colors.ORANGE}]► AI-WHISP NEW[/COLOR]', 'ai_recommend_for_me', {'force_refresh': 'true'}),
        'search_gemini': (f'[COLOR {Colors.ORANGE}]► AI-SCRIPT OPEN[/COLOR]', 'search_gemini', {}),
        'ai_mood_matcher': (f'[COLOR {Colors.ORANGE}]► AI-MOOD OPEN[/COLOR]', 'ai_mood_matcher', {}),
    }
    if action in commands:
        label, target, params = commands[action]
        url = get_url(action=target, **params)
        command = (f'Container.Update({url})' if action in ('ai_recommend_for_me', 'search_gemini', 'ai_mood_matcher')
                   else f'RunPlugin({url})')
        ctx.insert(0, (label, command))
    elif quick_action:
        label = (f'[COLOR {Colors.ORANGE}][ QUICK : SERIÁL ][/COLOR]' if 'series' in quick_action
                 else f'[COLOR {Colors.ORANGE}][ QUICK : FILM ][/COLOR]')
        ctx.insert(0, (label, f'RunPlugin({get_url(action=quick_action)})'))
    return ctx


def _get_custom_menu_label(action_id, default_label, **kwargs):
    try:
        setting_id = f"menu_label_{action_id}"
        custom_label = addon.getSettingString(setting_id)
        label_to_use = custom_label.strip() if custom_label and custom_label.strip() else default_label
        if kwargs:
            try:
                return label_to_use.format(**kwargs)
            except Exception:
                return label_to_use
        return label_to_use
    except Exception:
        return default_label


def _sort_menu_items_by_order(name_list):
    try:
        order_map = {}
        for item in name_list:
            action = item[1]
            if action == "open_settings":
                continue
            try:
                order_setting = addon.getSettingInt(f"menu_order_{action}")
                order_map[action] = order_setting if order_setting > 0 else 999
            except Exception:
                order_map[action] = 999

        sorted_list = sorted(name_list, key=lambda it: order_map.get(it[1], 999))

        settings_item = None
        for it in sorted_list:
            if it[1] == "open_settings":
                settings_item = it
                break
        if settings_item:
            sorted_list = [it for it in sorted_list if it[1] != "open_settings"]
            sorted_list.append(settings_item)

        return sorted_list
    except Exception:
        return name_list


def _initialize_addon_paths_and_files():
    global cache_file_path, history_path
    from resources.lib.utils_files import ensure_dir, ensure_file

    ensure_dir(profile)

    def get_path_from_setting(setting_id, default_path):
        path_setting = get_setting_str(addon, setting_id, default_path)
        return xbmcvfs.translatePath(path_setting.strip() or default_path)

    security_dir = get_path_from_setting(SETTING_ID_SECURITY_DIR, DEFAULT_SECURITY_DIR)
    history_dir = get_path_from_setting(SETTING_ID_HISTORY_DIR, DEFAULT_HISTORY_DIR)

    ensure_dir(security_dir)
    ensure_dir(history_dir)

    with PLUGIN_LOCK:
        cache_file_path = os.path.join(security_dir, "IP.CACHE") if security_dir else None
        history_path = os.path.join(history_dir, "HISTORY.TXT") if history_dir else None

    for file_p in [cache_file_path, history_path]:
        if file_p:
            ensure_file(file_p)


def _initialize_autoplay_state():
    if main_window.getProperty("play_er.autoplay_initialized") == "true":
        return

    if main_window.getProperty("player.movie.autoplay.enabled") == "":
        is_movie_on = get_setting_bool(addon, "movie_autoplay_default", False)
        main_window.setProperty("player.movie.autoplay.enabled", "true" if is_movie_on else "false")

    if main_window.getProperty("player.series.autoplay.enabled") == "":
        is_series_on = get_setting_bool(addon, "series_autoplay_default", False)
        main_window.setProperty("player.series.autoplay.enabled", "true" if is_series_on else "false")

    main_window.setProperty("play_er.autoplay_initialized", "true")


def _check_and_apply_patches():
    if main_window.getProperty("play_er.auto_repair_done") != "true":
        try:
            from resources.lib.utils_custom import apply_custom_localizations
            apply_custom_localizations()
        except Exception as e:
            log(f"AUTO-REPAIR - Chyba: {e}", xbmc.LOGWARNING)
        finally:
            main_window.setProperty("play_er.auto_repair_done", "true")


_initialize_addon_paths_and_files()
_initialize_autoplay_state()
_check_and_apply_patches()


def set_playback_started_flag():
    global playback_started_internally
    with PLUGIN_LOCK:
        playback_started_internally = True
        main_window.setProperty("player.playback.active", "true")


def playback_was_active():
    return main_window.getProperty("player.playback.active") == "true"


def clear_playback_flag():
    main_window.clearProperty("player.playback.active")
    global playback_started_internally
    with PLUGIN_LOCK:
        playback_started_internally = False


def _install_global_shortcut():
    if not get_setting_bool(addon, "startup_install_shortcut", True):
        return
    try:
        keymaps_dir = xbmcvfs.translatePath('special://profile/keymaps')
        target_file = os.path.join(keymaps_dir, 'PLAY.ER---DIALOG-MENU.xml')
        if not xbmcvfs.exists(target_file):
            if not xbmcvfs.exists(keymaps_dir):
                xbmcvfs.mkdirs(keymaps_dir)
            with SafeVFSFile(target_file, 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<keymap>\n</keymap>\n')
    except Exception:
        pass


_install_global_shortcut()

session = requests.Session()
series_manager = None
csfd_instance = None
tmdb_client = None
provider_manager = None
GLOBAL_TRAKT_MONITOR = None
plugin_instance = None
settings_monitor = None


class ProviderManager:
    """
    CLASS :: PROVIDER MANAGER
    """
    def __init__(self, addon, handle, session, tmdb_client):
        self.addon = addon
        self.handle = handle
        self.session = session
        self.tmdb_client = tmdb_client
        self._providers = {}
        self._providers_lock = threading.Lock()
        self._active_provider_name = (self.addon.getSetting("active_provider") or "prehraj.to").lower()

    def _get_provider_instance(self, name):
        with self._providers_lock:
            if name in self._providers:
                return self._providers[name]
            instance = None
            if name == "prehraj.to":
                from resources.lib.provider_prehrajto import PrehrajTo
                instance = PrehrajTo(self.addon, self.handle, self.session, self.tmdb_client)
            elif name == "webshare.cz":
                from resources.lib.provider_webshare import Webshare
                instance = Webshare(self.addon, self.handle, self.session, self.tmdb_client)
            if instance:
                self._providers[name] = instance
            return instance

    def get_active_provider(self):
        provider = self._get_provider_instance(self._active_provider_name)
        return provider or self._get_provider_instance("prehraj.to")

    def get_provider(self, name):
        return self._get_provider_instance(name)

    def get_providers_to_search(self):
        if self.addon.getSettingBool("enable_multi_provider"):
            return [self._get_provider_instance("prehraj.to"), self._get_provider_instance("webshare.cz")]
        return [self.get_active_provider()]

    def set_active_provider(self, provider_name):
        provider_name = provider_name.lower()
        if provider_name in ["prehraj.to", "webshare.cz"]:
            self._active_provider_name = provider_name
            self.addon.setSetting("active_provider", provider_name)
            notify_info(f"SOURCE Vybrán provider : {provider_name.upper()}", category="PROVIDER")
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass
            return True
        return False

    def get_provider_names(self):
        return ["prehraj.to", "webshare.cz"]


class Plugin:
    """
    CLASS :: PLUGIN
    """
    def __init__(self, addon, handle, session, provider_manager, series_manager, tmdb_client, csfd_instance):
        self.addon = addon
        self.handle = handle
        self.session = session
        self.provider_manager = provider_manager
        self._series_manager = series_manager
        self.tmdb_client = tmdb_client
        self.csfd_instance = csfd_instance
        self.history_path = history_path

    @property
    def series_manager(self):
        if self._series_manager is None:
            from resources.lib.series_manager import SeriesManager
            self._series_manager = SeriesManager(self.addon, profile, self.tmdb_client)
        return self._series_manager

    @series_manager.setter
    def series_manager(self, value):
        self._series_manager = value


def reinitialize_clients():
    global tmdb_client, addon, csfd_instance, provider_manager, series_manager, plugin_instance
    with PLUGIN_LOCK:
        addon = SafeAddonWrapper(xbmcaddon.Addon(id="plugin.video.play_er"))
        tmdb_account._tmdb_set_globals(addon=addon, session=session)
        tmdb_client = TMDB(addon, _handle, session)
        csfd_instance = CSFD(addon, tmdb_client)
        provider_manager = ProviderManager(addon, _handle, session, tmdb_client)
        series_manager = None

    if 'plugin_instance' in globals() and plugin_instance:
        plugin_instance.addon = addon
        plugin_instance.handle = _handle
        plugin_instance.tmdb_client = tmdb_client
        plugin_instance.csfd_instance = csfd_instance
        plugin_instance.provider_manager = provider_manager
        plugin_instance.series_manager = series_manager


def check_new_episodes_notifications():
    if addon.getSettingBool("disable_episode_notify"):
        return

    check_interval_hours = get_setting_int_with_bounds(addon, "episode_notify_interval", 24)
    check_interval_seconds = check_interval_hours * 3600

    last_check_time_str = cache_manager.user_data_get("episode_notify_last_check")
    last_check_time = float(last_check_time_str) if last_check_time_str else 0.0
    current_time = time.time()

    if current_time - last_check_time < check_interval_seconds:
        return

    notified_episodes = cache_manager.user_data_get("notified_episodes_map") or {}
    watchlist_items = tmdb_account.tmdb_get_watchlist('tv')

    if not watchlist_items or 'results' not in watchlist_items or not watchlist_items.get('results'):
        cache_manager.user_data_set("episode_notify_last_check", str(current_time))
        return

    new_episodes = []
    updated_notified_episodes = notified_episodes.copy()
    today = datetime.date.today()
    days_range = get_setting_int_with_bounds(addon, "episode_air_time", 7)
    start_date = today - datetime.timedelta(days=days_range)

    for show in watchlist_items['results']:
        show_id = str(show.get('id'))
        show_name = show.get('name', 'Neznámý seriál')

        show_details = tmdb_client.get_full_details('tv', show_id)
        if not show_details or show_details.get('status') in ['Ended', 'Canceled']:
            continue

        last_episode = show_details.get('last_episode_to_air')
        if not last_episode:
            continue

        last_episode_id = str(last_episode.get('id'))
        air_date_str = last_episode.get('air_date')
        if not air_date_str:
            continue

        try:
            air_date = datetime.datetime.strptime(air_date_str, '%Y-%m-%d').date()
        except Exception:
            continue

        is_in_range = start_date <= air_date <= today
        is_notified = (show_id in updated_notified_episodes and str(updated_notified_episodes[show_id]) == last_episode_id)

        if is_in_range and not is_notified:
            s_number = last_episode.get('season_number')
            e_number = last_episode.get('episode_number')
            episode_title = last_episode.get('name', 'Epizoda bez názvu')
            poster_path = show_details.get('poster_path')
            backdrop_path = show_details.get('backdrop_path')
            still_path = last_episode.get('still_path')

            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""
            fanart_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}" if backdrop_path else poster_url
            thumb_url = f"https://image.tmdb.org/t/p/w500{still_path}" if still_path else poster_url

            notify_info(f"EPISODE {show_name} S{s_number}E{e_number}", category="TMDB", time=6000)

            if addon.getSettingBool("enable_telegram_notifications"):
                msg = f"[ PLAY.ER ] Nová epizoda : <b>{show_name}</b> S{s_number}E{e_number}"
                if episode_title and episode_title != "Epizoda bez názvu":
                    msg += f" – {episode_title}"
                try:
                    get_telegram_manager().send_message(msg, photo_url=poster_url)
                except Exception:
                    pass

            new_episodes.append({
                "tmdb_id": int(show_id),
                "show_name": show_name,
                "season": int(s_number) if s_number else 0,
                "episode": int(e_number) if e_number else 0,
                "episode_title": episode_title,
                "air_date": air_date_str,
                "poster": poster_url,
                "fanart": fanart_url,
                "thumb": thumb_url,
                "plot": show_details.get("overview", "")
            })
            updated_notified_episodes[show_id] = last_episode_id

    try:
        cache_manager.user_data_set("episode_notify_last_check", str(time.time()))
        cache_manager.user_data_set("notified_episodes_map", updated_notified_episodes)
        current_new_episodes = cache_manager.user_data_get("new_episodes") or []
        all_episodes = current_new_episodes + new_episodes

        unique_map = {}
        for ep in all_episodes:
            unique_map[f"{ep['tmdb_id']}_{ep['season']}_{ep['episode']}"] = ep

        final_list = list(unique_map.values())
        final_list.sort(key=lambda x: x.get('air_date', '0000-00-00'), reverse=True)
        cache_manager.user_data_set("new_episodes", final_list)

        if new_episodes:
            cache_manager.safe_refresh()
    except Exception as e:
        log(f"NOTIFY - NEW EPISODES ERROR : {e}", xbmc.LOGERROR)


def list_new_episodes_content(is_widget=False):
    try:
        episodes = cache_manager.user_data_get("new_episodes") or []
        if not episodes:
            xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)
            return

        xbmcplugin.setContent(_handle, "videos")

        for ep in episodes:
            try:
                season_num = int(ep.get('season', 0))
                episode_num = int(ep.get('episode', 0))
                title = f"{ep.get('show_name','Neznámý')} – S{season_num:02d}E{episode_num:02d}"
                if ep.get('episode_title'):
                    title += f" • {ep['episode_title']}"

                li = xbmcgui.ListItem(label=title)
                poster = ep.get("poster", "")
                fanart = ep.get("fanart", poster)
                thumb = ep.get("thumb", poster)

                props = {
                    "tmdb_id": ep.get("tmdb_id"),
                    "media_type": "episode",
                    "title": ep.get("episode_title") or title,
                    "original_title": ep.get("episode_title"),
                    "tv_show_title": ep.get("show_name"),
                    "season": season_num,
                    "episode": episode_num,
                    "plot": ep.get("plot", ""),
                    "premiered": ep.get("air_date"),
                    "year": ep.get("air_date", "")[:4] if ep.get("air_date") else "",
                    "poster": poster,
                    "fanart": fanart,
                    "thumb": thumb
                }

                tmdb_client.fill_list_item(li, props, 'episode')
                meta_key = store_meta_in_cache(props)

                url = get_url(action="find_sources", meta=meta_key, source_list="new_episodes")
                li.setProperty("IsPlayable", "false")

                context_menu = _get_context_menu(
                    'media',
                    context_type='new_episodes',
                    title=ep.get('episode_title') or title,
                    tmdb_id=ep.get('tmdb_id'),
                    media_type='episode',
                    year=props.get('year', ''),
                    poster=poster,
                    plot=ep.get('plot', ''),
                    props=props
                )
                li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
                xbmcplugin.addDirectoryItem(_handle, url, li, isFolder=True)
            except Exception:
                continue

        if not is_widget:
            set_view_mode(_handle, addon, "videos", "episodes")
        xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)
    except Exception as e:
        log(f"LIST NEW EPISODES - Error: {e}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)


def _display_watch_later_list(is_widget=False):
    items = cache_manager.user_data_get("watch_later") or []
    if not items:
        if not is_widget:
            notify_info("INFO CHCI VIDĚT JE PRÁZDNÝ", category="WATCH-IT", time=4000)
        xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)
        return

    xbmcplugin.setContent(_handle, "videos")

    for props in items:
        media_type = props.get("media_type", "movie")
        tmdb_id = props.get("tmdb_id")
        title = props.get('title', 'Neznámý titul')
        year = props.get('year', '')
        label = f"{title} ({year})" if year else title

        list_item = xbmcgui.ListItem(label=label)
        tmdb_client.fill_list_item(list_item, props, media_type)

        meta_key = store_meta_in_cache(props)
        is_folder = True

        if media_type == 'movie':
            is_autoplay = main_window.getProperty("player.movie.autoplay.enabled") == "true"
            if is_autoplay:
                url = get_url(action="create_movie_playlist_action", meta=meta_key, source_list='watch_later')
                is_folder = False
            else:
                url = get_url(action="find_sources", meta=meta_key, source_list='watch_later')
        elif media_type == 'episode':
            is_autoplay = main_window.getProperty("player.series.autoplay.enabled") == "true"
            if is_autoplay:
                url = get_url(action="create_series_playlist_action", meta=meta_key, source_list='watch_later')
                list_item.setProperty("IsPlayable", "true")
                is_folder = False
            else:
                url = get_url(action="find_sources", meta=meta_key, source_list='watch_later')
        else:
            url = get_url(action="listing_tmdb_tv", tmdb_id=tmdb_id, meta=meta_key, source_list='watch_later')

        context_menu = _get_context_menu(
            'media',
            context_type='watch_later',
            title=title,
            tmdb_id=tmdb_id,
            media_type=media_type,
            year=year,
            poster=props.get("poster", ""),
            plot=props.get("plot", ""),
            props=props
        )
        list_item.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=is_folder)

    if not is_widget:
        set_view_mode(_handle, addon, "videos", "episodes")
    xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)


def _remove_episode_from_new_list(meta, force_refresh=False):
    try:
        tmdb_id = meta.get("tmdb_id")
        season = meta.get("season")
        episode = meta.get("episode")
        if not tmdb_id or season is None or episode is None:
            return

        current_episodes = cache_manager.user_data_get("new_episodes") or []
        new_list = [
            ep for ep in current_episodes
            if not (str(ep['tmdb_id']) == str(tmdb_id) and int(ep['season']) == int(season) and int(ep['episode']) == int(episode))
        ]

        if len(new_list) < len(current_episodes):
            cache_manager.user_data_set("new_episodes", new_list)
            if force_refresh or xbmc.getCondVisibility("Container.Content(episodes)"):
                try:
                    cache_manager.safe_refresh()
                except Exception:
                    pass
    except Exception as e:
        log(f"MONITOR - Chyba odebírání z cache : {e}", xbmc.LOGERROR)


def get_public_ip(timeout=5):
    try:
        response = safe_get(session, 'https://api.ipify.org?format=json', timeout=timeout)
        if response:
            return response.json().get('ip')
    except Exception:
        pass
    return None


def log_ip_to_server(ip_address, retries=2, delay=2):
    url = 'https://xbmc.south-fork.uk/SERVER/addon-security.php'
    data = {'ip': ip_address, 'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'), 'addon_name': ADDON_NAME}

    def _worker():
        for attempt in range(retries + 1):
            try:
                response = safe_post(url, data=data, timeout=10)
                txt = response.text.strip() if response is not None else ""
                if "OK" in txt or "SUCCESS" in txt:
                    try:
                        with SafeVFSFile(IP_LAST_SENT_FILE, 'w') as f:
                            f.write(str(time.time()))
                    except Exception:
                        pass
                    return
                if attempt < retries:
                    time.sleep(delay)
            except Exception:
                if attempt < retries:
                    time.sleep(delay)

    threading.Thread(target=_worker, daemon=True).start()


def check_run_file():
    if addon.getSettingBool("security_bypass"):
        return True, False, "127.0.0.1"

    last_check = main_window.getProperty("player.security.last_check")
    cached_status = main_window.getProperty("player.security.status")
    now = time.time()

    if last_check and cached_status:
        try:
            if now - float(last_check) < (12 * 3600):
                status = json.loads(cached_status)
                return status["allowed"], status["ip_banned"], status["public_ip"]
        except Exception:
            pass

    public_ip = get_public_ip()
    if public_ip:
        last_sent = 0
        if os.path.exists(IP_LAST_SENT_FILE):
            try:
                with open(IP_LAST_SENT_FILE, 'r') as f:
                    c = f.read().strip()
                    if c:
                        last_sent = float(c)
            except Exception:
                pass
        if now - last_sent > IP_LOG_INTERVAL_SECONDS:
            log_ip_to_server(public_ip)

    allowed = True
    ip_banned = False

    try:
        response = safe_get("https://xbmc.south-fork.uk/SERVER/addon-security.run", timeout=10)
        lines = response.text.splitlines() if response else []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key, val = key.strip().lower(), val.strip()
                if key == "allowed" and val.lower() == "false":
                    allowed = False
                elif key == "ip_ban" and public_ip and val == public_ip:
                    ip_banned = True
        if ip_banned:
            allowed = False
    except Exception:
        allowed = False

    main_window.setProperty("player.security.last_check", str(now))
    main_window.setProperty("player.security.status", json.dumps({"allowed": allowed, "ip_banned": ip_banned, "public_ip": public_ip}))
    return allowed, ip_banned, public_ip


def get_entry_key(entry):
    meta = entry.get("meta", {})
    media_type = meta.get("media_type", "movie")
    key = str(meta.get("tmdb_id", ""))
    if media_type == "episode":
        key = "episode_" + json.dumps(
            [key, str(meta.get("season", "")), str(meta.get("episode", ""))],
            separators=(",", ":"),
        )
    elif media_type == "movie" and key:
        key = "movie_" + key
    return key


def save_playback_history(meta, link=None, skip_refresh=False):
    media_type = meta.get("media_type", "movie")

    if media_type == "episode" and not meta.get("tv_show_title"):
        return
    if media_type == "movie" and not meta.get("title"):
        return
    if not meta.get("tmdb_id"):
        return

    entry = {"meta": meta, "link": ""}
    entry_key = get_entry_key(entry)
    limit = get_setting_int_with_bounds(addon, "playback_history_limit", 500, 1, 5000)

    def update(history):
        history = [h for h in (history or []) if get_entry_key(h) != entry_key]
        history.insert(0, entry)
        return history[:limit]

    cache_manager.user_data_update("playback_history", update)

    if skip_refresh or xbmc.Player().isPlayingVideo():
        main_window.setProperty("player.needs_refresh_on_stop", "true")
        xbmc.executebuiltin("Dialog.Close(busydialog)")
    else:
        cache_manager.safe_refresh()


def save_playback_history_bulk(items_to_add):
    if not items_to_add:
        return
    limit = get_setting_int_with_bounds(addon, "playback_history_limit", 500, 1, 5000)

    def update(history):
        history = history or []
        existing_keys = {get_entry_key(h) for h in history}
        new_items = [item for item in reversed(items_to_add) if get_entry_key(item) not in existing_keys]
        new_keys = {get_entry_key(item) for item in new_items}
        return (new_items + [h for h in history if get_entry_key(h) not in new_keys])[:limit]

    cache_manager.user_data_update("playback_history", update)


def has_series_in_playback_history():
    history = cache_manager.user_data_get("playback_history")
    if not history or not isinstance(history, list):
        return False
    return any(isinstance(entry.get("meta"), dict) and entry["meta"].get("media_type") == "episode" for entry in history)


def has_watch_later_items():
    items = cache_manager.user_data_get("watch_later")
    return bool(items and isinstance(items, list) and len(items) > 0)


def toggle_movie_autoplay():
    is_enabled = main_window.getProperty("player.movie.autoplay.enabled") == "true"
    new_state = not is_enabled
    main_window.setProperty("player.movie.autoplay.enabled", "true" if new_state else "false")
    addon.setSettingBool("movie_autoplay_default", new_state)
    if new_state:
        notify_ok("MOVIE Filmy zapnuty", category="AUTOPLAY")
    else:
        notify_info("MOVIE Filmy vypnuty", category="AUTOPLAY")
    cache_manager.safe_refresh()


def toggle_series_autoplay():
    is_enabled = main_window.getProperty("player.series.autoplay.enabled") == "true"
    new_state = not is_enabled
    main_window.setProperty("player.series.autoplay.enabled", "true" if new_state else "false")
    addon.setSettingBool("series_autoplay_default", new_state)
    if new_state:
        notify_ok("TV-SHOW Seriály zapnuty", category="AUTOPLAY")
    else:
        notify_info("TV-SHOW Seriály vypnuty", category="AUTOPLAY")
    cache_manager.safe_refresh()


def toggle_filtering():
    is_enabled = addon.getSettingBool("enable_filtering")
    new_state = not is_enabled
    addon.setSettingBool("enable_filtering", new_state)
    if new_state:
        notify_ok("FILTER Regex filtry zapnuty", category="REGEX")
    else:
        notify_info("FILTER Regex filtry vypnuty", category="REGEX")


def _create_menu_item(label, plot, icon, action=None, url_params=None, is_folder=True, context_menu=None):
    list_item = xbmcgui.ListItem(label=label)
    fanart = addon.getAddonInfo('fanart')
    icon_path = icon if icon else Icons.FOLDER
    list_item.setArt({'icon': icon_path, 'thumb': icon_path, 'poster': icon_path, 'fanart': fanart})

    info_tag = list_item.getVideoInfoTag()
    info_tag.setTitle(label)
    info_tag.setPlot(plot or "")
    info_tag.setMediaType("video")

    if context_menu:
        list_item.addContextMenuItems(_sf_cm_items(context_menu))

    url = get_url(action=action, **(url_params or {})) if action and action != "noop" else ""
    xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=list_item, isFolder=is_folder)


def show_help():
    from resources.lib.help import HELP_TEXT
    xbmcgui.Dialog().textviewer(f"[B][COLOR {Colors.ORANGE}]| PLAY.ER | NÁPOVĚDA[/COLOR][/B]", HELP_TEXT)
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def show_account_help():
    from resources.lib.help_account import HELP_ACCOUNT_TEXT
    xbmcgui.Dialog().textviewer(f"[B][COLOR {Colors.ORANGE}]| PLAY.ER | API ÚČTY[/COLOR][/B]", HELP_ACCOUNT_TEXT)
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def show_telegram_help():
    from resources.lib.help_telegram import TELEGRAM_HELP_TEXT
    xbmcgui.Dialog().textviewer(f"[B][COLOR {Colors.ORANGE}]| PLAY.ER | TELEGRAM BOT[/COLOR][/B]", TELEGRAM_HELP_TEXT)
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def show_filter_help():
    from resources.lib.help_filter import HELP_FILTER_TEXT
    xbmcgui.Dialog().textviewer(f"[B][COLOR {Colors.ORANGE}]| PLAY.ER | FILTRY[/COLOR][/B]", HELP_FILTER_TEXT)
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def show_command_help():
    from resources.lib.help_command import HELP_COMMAND_TEXT
    xbmcgui.Dialog().textviewer(f"[B][COLOR {Colors.ORANGE}]| PLAY.ER | PŘÍKAZY[/COLOR][/B]", HELP_COMMAND_TEXT)
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def listing_history():
    if not history_path or not xbmcvfs.exists(history_path):
        notify_error("ERROR Soubor s historií nenalezen", category="HISTORY")
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    try:
        with SafeVFSFile(history_path, "r") as f:
            search_history = f.read().splitlines()
        for query in search_history:
            if not query.strip():
                continue
            list_item = xbmcgui.ListItem(label=query)
            context_menu = _get_context_menu('search_history', query=query)
            list_item.addContextMenuItems(_sf_cm_items(context_menu))
            url = get_url(action="listing_search", name=query)
            xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=True)

        xbmcplugin.setContent(_handle, "files")
        set_view_mode(_handle, addon, "files", "search_history")
        xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)
    except Exception as e:
        log(f"HISTORIE - Chyba: {e}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(_handle, succeeded=False, cacheToDisc=False)


def delete_search_history_item(params):
    query_to_delete = params.get("query")
    if not query_to_delete or not history_path or not xbmcvfs.exists(history_path):
        return
    try:
        with SafeVFSFile(history_path, "r") as f:
            lines = f.read().splitlines()
        if query_to_delete in lines:
            lines.remove(query_to_delete)
            with SafeVFSFile(history_path, "w") as f:
                f.write("\n".join(lines))
            cache_manager.safe_refresh()
            notify_ok("DELETE Položka byla odstraněna", category="PLAY.ER")
    except Exception as e:
        log(f"HISTORIE - Chyba mazání: {e}", xbmc.LOGERROR)


def clear_search_history():
    if xbmcgui.Dialog().yesno(f"[COLOR {Colors.ORANGE}]○ VYČISTIT HISTORII HLEDÁNÍ ○[/COLOR]", "Opravdu chcete vyčistit celou historii hledání?"):
        if history_path and xbmcvfs.exists(history_path):
            if xbmcvfs.delete(history_path):
                from resources.lib.utils_files import ensure_file
                ensure_file(history_path)
                cache_manager.safe_refresh()
                notify_ok("CLEAR Historie byla vyčištěna", category="PLAY.ER")


def handle_csfd_selection(csfd_id, search_type):
    details = csfd_instance.get_detail(csfd_id)
    if not details:
        notify_error(f"LOAD Nepodařilo se načíst detaily ID {csfd_id}", category="CSFD")
        return

    media_type = details.get("media_type", "movie")
    if (search_type == "tv" or media_type == "tv") and details.get("tmdb_id"):
        props = {
            'title': details.get('title'),
            'original_title': details.get('original_title'),
            'year': details.get('year'),
            'tmdb_id': details.get('tmdb_id'),
            'media_type': 'tv',
            'rating': details.get('tmdb_rating', 0),
            'plot': details.get('plot'),
            'poster': details.get('poster'),
            'fanart': details.get('fanart'),
        }
        tmdb_client.show_tv_detail(details.get('tmdb_id'), json.dumps(props), None)
        return

    query = f"{details['title']} {details.get('year', '')}".strip()
    actions.search(query, plugin_instance)


def list_csfd_daily_tips():
    progress = xbmcgui.DialogProgress()
    progress.create(f"[B][COLOR {Colors.ORANGE}]○ ČSFD DNEŠNÍ TIPY ○[/COLOR][/B]", "Stahuji data...")
    try:
        tips = csfd_instance.get_daily_tips(progress_callback=lambda p, m: progress.update(p, m))
        if not tips:
            notify_error("LOAD Nepodařilo se načíst DNEŠNÍ TIPY ČSFD", category="CSFD")
            return

        for tip in tips:
            title = tip.get("title", "Neznámý titul")
            year = tip.get("year") or "????"
            media_type = "tv" if (tip.get("media_type") or tip.get("type")) == "show" else (tip.get("media_type") or tip.get("type", "movie"))
            tmdb_id = tip.get("tmdb_id")

            rating_str = tip.get("rating", "").strip()
            rating_display = f"► [B][COLOR {Colors.ORANGE}]{rating_str or 'N/A'}[/COLOR][/B]"
            time_info = f" [COLOR {Colors.YELLOW}][ {tip['time']} - {tip['channel']} ][/COLOR]" if tip.get("time") and tip.get("channel") else ""

            label = f"{title} ({year}) {rating_display}{time_info}"
            listitem = xbmcgui.ListItem(label=label)

            props = {
                "tmdb_id": tmdb_id,
                "title": title,
                "original_title": tip.get("original_title", title),
                "year": year,
                "plot": tip.get("plot", ""),
                "genre": tip.get("genres", []),
                "rating": tip.get("tmdb_rating", 0.0),
                "poster": tip.get("poster", ""),
                "fanart": tip.get("fanart", ""),
                "thumb": tip.get("poster", ""),
                "cast_full": tip.get("cast_full", []),
                "studio": tip.get("studio", ""),
                "mpaa": tip.get("mpaa", ""),
                "duration": tip.get("duration", "")
            }

            tmdb_client.fill_list_item(listitem, props, "movie" if media_type == "movie" else "tvshow")
            context_menu = _get_context_menu(
                'media',
                context_type='csfd',
                title=title,
                tmdb_id=tmdb_id,
                media_type=media_type,
                year=year,
                poster=tip.get("poster", ""),
                plot=tip.get("plot", ""),
                props=props
            )
            listitem.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
            url = get_url(action="select_csfd", csfd_id=tip.get("id"), search_type=media_type)
            xbmcplugin.addDirectoryItem(_handle, url, listitem, isFolder=True)

        xbmcplugin.setContent(_handle, "movies")
        set_view_mode(_handle, addon, "movies", "csfd_tips")
    finally:
        progress.close()
        xbmcplugin.endOfDirectory(_handle, succeeded=True)


def list_csfd_chart_items(params):
    chart_paths = {
        "filmy/nejlepsi": "Nejlepší filmy",
        "filmy/nejhorsi": "Nejhorší filmy",
        "filmy/nejoblibenejsi": "Nejoblíbenější filmy",
        "filmy/nejrozporuplnejsi": "Nejrozporuplnější filmy",
        "serialy/nejlepsi": "Nejlepší seriály",
        "serialy/nejhorsi": "Nejhorší seriály",
        "serialy/nejoblibenejsi": "Nejoblíbenější seriály",
        "serialy/nejrozporuplnejsi": "Nejrozporuplnější seriály",
    }
    chart_path = params.get("chart_path")
    if chart_path not in chart_paths:
        notify_error(f"ERROR Neznámý žebříček {chart_path}", category="CSFD")
        xbmcplugin.endOfDirectory(_handle, False)
        return

    media_type = "movie" if chart_path.startswith("filmy/") else "tv"
    page = int(params.get("page", 1))
    cache_key = f"csfd_chart_{chart_path}_{page - 1}"
    items = cache_manager.cache_get("CSFD", cache_key)

    if not items:
        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}]○ ČSFD ŽEBŘÍČEK ○[/COLOR][/B]", f"[B]{chart_paths[chart_path]} - Strana {page}[/B]")
        try:
            items = csfd_instance.get_chart(chart_path, page=page, progress_callback=lambda p, m: progress.update(p, f"Načítám: {m}"))
        except Exception:
            items = []
        progress.close()
        if items:
            cache_manager.cache_set("CSFD", cache_key, items)

    if not items:
        notify_error("LOAD Žebříček prázdný", category="CSFD")
        xbmcplugin.endOfDirectory(_handle, False)
        return

    for item in items:
        title = item.get("title", "Neznámý titul")
        year = item.get("year") or "????"
        rating_str = item.get("rating", "").strip()
        rating_display = f"► [B][COLOR {Colors.ORANGE}]{rating_str or 'N/A'}[/COLOR][/B]"
        label = f"{title} ({year}) {rating_display}"

        li = xbmcgui.ListItem(label=label)
        props = {
            "tmdb_id": item.get("tmdb_id"),
            "title": title,
            "original_title": item.get("original_title", title),
            "year": year,
            "plot": item.get("plot", ""),
            "genre": item.get("genres", []),
            "rating": item.get("tmdb_rating", 0.0),
            "poster": item.get("poster", ""),
            "fanart": item.get("fanart", ""),
            "thumb": item.get("poster", ""),
            "cast_full": item.get("cast_full", []),
            "studio": item.get("studio", ""),
            "mpaa": item.get("mpaa", ""),
            "duration": item.get("duration", "")
        }
        tmdb_client.fill_list_item(li, props, "movie" if media_type == "movie" else "tvshow")

        context_menu = _get_context_menu(
            'media',
            context_type='csfd',
            title=title,
            tmdb_id=item.get("tmdb_id"),
            media_type=media_type,
            year=year,
            poster=item.get("poster", ""),
            plot=item.get("plot", ""),
            props=props
        )
        li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
        url = get_url(action="select_csfd", csfd_id=item["id"], search_type=media_type)
        xbmcplugin.addDirectoryItem(_handle, url, li, True)

    if len(items) == 100:
        next_page = page + 1
        next_li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]| STRANA [ {next_page} ] ►[/COLOR][/B]")
        next_li.setArt({"icon": Icons.NEXT_PAGE, "thumb": Icons.NEXT_PAGE})
        next_url = get_url(action="list_csfd_chart_items", chart_path=chart_path, page=next_page)
        xbmcplugin.addDirectoryItem(_handle, next_url, next_li, True)

    xbmcplugin.setContent(_handle, "movies" if media_type == "movie" else "tvshows")
    set_view_mode(_handle, addon, "movies" if media_type == "movie" else "tvshows", "csfd_charts")
    xbmcplugin.endOfDirectory(_handle, True)


def list_csfd_charts_menu():
    charts = [
        ("ČSFD : DNEŠNÍ TIPY", "daily_tips", Icons.CSFD, "Dnešní tipy ČSFD"),
        ("FILMY : TOP-NEJLEPŠÍ", "filmy/nejlepsi", Icons.MOVIE, "Filmy s nejvyšším hodnocením"),
        ("FILMY : TOP-NEJHORŠÍ", "filmy/nejhorsi", Icons.MOVIE, "Filmy s nejnižším hodnocením"),
        ("FILMY : NEJOBLÍBENĚJŠÍ", "filmy/nejoblibenejsi", Icons.MOVIE, "Nejoblíbenější filmy"),
        ("FILMY : NEJROZPORUPLNĚJŠÍ", "filmy/nejrozporuplnejsi", Icons.MOVIE, "Nejkontroverznější filmy"),
        ("SERIÁLY : TOP-NEJLEPŠÍ", "serialy/nejlepsi", Icons.TVSHOW, "Seriály s nejvyšším hodnocením"),
        ("SERIÁLY : TOP-NEJHORŠÍ", "serialy/nejhorsi", Icons.TVSHOW, "Seriály s nejnižším hodnocením"),
        ("SERIÁLY : NEJOBLÍBENĚJŠÍ", "serialy/nejoblibenejsi", Icons.TVSHOW, "Nejoblíbenější seriály"),
        ("SERIÁLY : NEJROZPORUPLNĚJŠÍ", "serialy/nejrozporuplnejsi", Icons.TVSHOW, "Nejkontroverznější seriály"),
    ]

    for label, path, icon, desc in charts:
        li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}")
        li.setArt({'icon': icon, 'fanart': addon.getAddonInfo('fanart')})
        info = li.getVideoInfoTag()
        info.setTitle(label)
        info.setPlot(desc)
        url = get_url(action="list_csfd_daily_tips") if path == "daily_tips" else get_url(action="list_csfd_chart_items", chart_path=path)
        xbmcplugin.addDirectoryItem(_handle, url, li, True)

    set_view_mode(_handle, addon, "files", "main_menu")
    xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)


def list_csfd_category_items(params):
    chart_category = params.get("chart_category")
    detail_id = params.get("detail_id")
    if not chart_category or not detail_id:
        chart_list = params.get("chart_list", "")
        m = re.match(r'^(filmy|serialy)/\?detail=(\d+)$', chart_list)
        if m:
            chart_category, detail_id = m.group(1), m.group(2)
        else:
            notify_error("ERROR Neznámý seznam", category="CSFD")
            xbmcplugin.endOfDirectory(_handle, False)
            return

    media_type = "movie" if chart_category == "filmy" else "tv"
    page = int(params.get("page", 1))
    cache_key = f"csfd_chart_{chart_category}_{detail_id}_{page - 1}"
    items = cache_manager.cache_get("CSFD", cache_key)

    if not items:
        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}]○ ČSFD SEZNAMY ○[/COLOR][/B]", f"Strana {page}")
        try:
            items = csfd_instance.get_lists(f"{chart_category}/?detail={detail_id}", page=page, progress_callback=lambda p, m: progress.update(p, f"Načítám: {m}"))
        except Exception:
            items = []
        progress.close()
        if items:
            cache_manager.cache_set("CSFD", cache_key, items)

    if not items:
        notify_error("LOAD Seznam prázdný", category="CSFD")
        xbmcplugin.endOfDirectory(_handle, False)
        return

    for item in items:
        title = item.get("title", "Neznámý titul")
        year = item.get("year") or "????"
        rating_str = item.get("rating", "").strip()
        label = f"{title} ({year}) ► [B][COLOR {Colors.ORANGE}]{rating_str or 'N/A'}[/COLOR][/B]"
        li = xbmcgui.ListItem(label=label)

        props = {
            "tmdb_id": item.get("tmdb_id"),
            "title": title,
            "original_title": item.get("original_title", title),
            "year": year,
            "plot": item.get("plot", ""),
            "genre": item.get("genres", []),
            "rating": item.get("tmdb_rating", 0.0),
            "poster": item.get("poster", ""),
            "fanart": item.get("fanart", ""),
            "thumb": item.get("poster", ""),
            "cast_full": item.get("cast_full", []),
            "studio": item.get("studio", ""),
            "mpaa": item.get("mpaa", ""),
            "duration": item.get("duration", "")
        }
        tmdb_client.fill_list_item(li, props, "movie" if media_type == "movie" else "tvshow")

        context_menu = _get_context_menu(
            'media',
            context_type='csfd',
            title=title,
            tmdb_id=item.get("tmdb_id"),
            media_type=media_type,
            year=year,
            poster=item.get("poster", ""),
            plot=item.get("plot", ""),
            props=props
        )
        li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
        url = get_url(action="select_csfd", csfd_id=item["id"], search_type=media_type)
        xbmcplugin.addDirectoryItem(_handle, url, li, True)

    if len(items) == 100:
        next_page = page + 1
        next_li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]| STRANA [ {next_page} ] ►[/COLOR][/B]")
        next_li.setArt({"icon": Icons.NEXT_PAGE, "thumb": Icons.NEXT_PAGE})
        next_url = get_url(action="list_csfd_category_items", chart_category=chart_category, detail_id=detail_id, page=next_page)
        xbmcplugin.addDirectoryItem(_handle, next_url, next_li, True)

    content_type = "movies" if media_type == "movie" else "tvshows"
    xbmcplugin.setContent(_handle, content_type)
    set_view_mode(_handle, addon, content_type, "csfd_charts")
    xbmcplugin.endOfDirectory(_handle, True)


def list_csfd_category_menu():
    charts = [
        ("FILMY : Na které se nejvíce těším", "filmy/?detail=1", Icons.MOVIE),
        ("FILMY : Které mě nejvíce rozesmály", "filmy/?detail=2", Icons.MOVIE),
        ("FILMY : Které mě nejvíce dojaly", "filmy/?detail=3", Icons.MOVIE),
        ("FILMY : Které mi vždy zvednou náladu", "filmy/?detail=8", Icons.MOVIE),
        ("FILMY : Které obsahují nejvíce zvratů", "filmy/?detail=10", Icons.MOVIE),
        ("SERIÁLY : Na které se nejvíce těším", "serialy/?detail=21", Icons.TVSHOW),
        ("SERIÁLY : Které nejvíce rozesmály", "serialy/?detail=22", Icons.TVSHOW),
        ("SERIÁLY : Které vždy zvednou náladu", "serialy/?detail=27", Icons.TVSHOW),
        ("SERIÁLY : Které obsahují nejvíce zvratů", "serialy/?detail=29", Icons.TVSHOW),
    ]
    for label, path, icon in charts:
        li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}")
        li.setArt({'icon': icon, 'fanart': addon.getAddonInfo('fanart')})
        m = re.match(r'^(filmy|serialy)/\?detail=(\d+)$', path)
        url = get_url(action="list_csfd_category_items", chart_category=m.group(1), detail_id=m.group(2))
        xbmcplugin.addDirectoryItem(_handle, url, li, True)

    set_view_mode(_handle, addon, "files", "main_menu")
    xbmcplugin.endOfDirectory(_handle)


def movie_category():
    name_list = [
        ("[ ○ HLEDAT FILM ○ ]", "search_tmdb", "movie", Icons.SEARCH_MOVIE, "Vyhledat film"),
        ("DISCOVER", "listing_discover", "movie", Icons.DISCOVER, "Objevujte nové filmy"),
        ("NEJVÍCE HLASŮ", "list_most_voted", "movie", Icons.RATING, "Filmy podle počtu hodnocení"),
        ("NEJLÉPE HODNOCENÉ", "listing_top_rated", "movie", Icons.RATING, "Nejlépe hodnocené"),
        ("NYNÍ V KINECH", "listing_now_playing", "movie", Icons.NEWS, "Aktuálně v kinech"),
        ("TRENDY", "trending_submenu", "movie", Icons.WATCH, "Populární na TMDB"),
        ("ŽÁNRY", "listing_genre_category", "movie", Icons.GENTRE, "Podle žánru"),
        ("ROKY", "listing_year_category", "movie", Icons.YEAR, "Podle roku"),
        ("STUDIA", "listing_studio_category", "movie", Icons.TVSHOW, "Podle studií"),
        ("POSKYTOVATELÉ", "list_providers", "movie", Icons.TVSHOW, "Podle poskytovatelů"),
    ]
    for label, action, item_type, icon, plot in name_list:
        _create_menu_item(f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}", plot, icon, action, url_params={'type': item_type, 'page': '1'})
    set_view_mode(_handle, addon, "files", "movies_submenu")
    xbmcplugin.endOfDirectory(_handle)


def serie_category():
    name_list = [
        ("[ ○ HLEDAT SERIÁL ○ ]", "search_tmdb", "tv", Icons.SEARCH_TVSHOW, "Vyhledat seriál"),
        ("DISCOVER", "listing_discover", "tv", Icons.DISCOVER, "Objevujte nové seriály"),
        ("NEJVÍCE HLASŮ", "list_most_voted", "tv", Icons.RATING, "Seriály podle počtu hodnocení"),
        ("NEJLÉPE HODNOCENÉ", "listing_top_rated", "tv", Icons.RATING, "Nejlépe hodnocené seriály"),
        ("DNES VE VYSÍLÁNÍ", "listing_airing_today", "tv", Icons.NEWS, "Dnes vysílané"),
        ("TRENDY", "trending_submenu", "tv", Icons.WATCH, "Populární seriály"),
        ("ŽÁNRY", "listing_genre_category", "tv", Icons.GENTRE, "Podle žánru"),
        ("ROKY", "listing_year_category", "tv", Icons.YEAR, "Podle roku"),
        ("TV STANICE", "list_random_network", "tv", Icons.TVSHOW, "Podle TV stanic"),
    ]
    for label, action, item_type, icon, plot in name_list:
        _create_menu_item(f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}", plot, icon, action, url_params={'type': item_type, 'page': '1'})
    set_view_mode(_handle, addon, "files", "tvshows_submenu")
    xbmcplugin.endOfDirectory(_handle)


def bonus_menu():
    name_list = [
        ("NÁHODNÝ VÝBĚR PODLE ŽÁNRU (FILMY)", "list_random_genre", "movie", Icons.MOVIE, "Náhodně film dle žánru"),
        ("NÁHODNÝ VÝBĚR PODLE ŽÁNRU (SERIÁLY)", "list_random_genre", "tv", Icons.TVSHOW, "Náhodně seriál dle žánru"),
        ("HERCI : POPULÁRNÍ", "list_actors", None, Icons.GENTRE, "Populární herci"),
        ("HERCI : TRENDY", "trending_actors_submenu", None, Icons.GENTRE, "Trendující herci"),
        ("HERCI : VYHLEDÁVÁNÍ", "search_actor", None, Icons.GENTRE, "Vyhledat herce"),
    ]
    for label, action, media_type, icon, plot in name_list:
        _create_menu_item(f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}", plot, icon, action, url_params={'type': media_type, 'page': '1'})
    set_view_mode(_handle, addon, "files", "movies_submenu")
    xbmcplugin.endOfDirectory(_handle)


def tmdb_menu():
    name_list = [
        ("WATCHLIST FILMY", "tmdb_watchlist_movies", "", Icons.MOVIE, "Filmy ve Watchlistu"),
        ("WATCHLIST SERIÁLY", "tmdb_watchlist_tv", "", Icons.TVSHOW, "Seriály ve Watchlistu"),
        ("DOPORUČENÉ FILMY", "tmdb_recommendations_movies", "", Icons.MOVIE, "Doporučené filmy"),
        ("DOPORUČENÉ SERIÁLY", "tmdb_recommendations_tv", "", Icons.TVSHOW, "Doporučené seriály"),
        ("HODNOCENÉ FILMY", "tmdb_rated_movies", "", Icons.MOVIE, "Hodnocené filmy"),
        ("HODNOCENÉ SERIÁLY", "tmdb_rated_tv", "", Icons.TVSHOW, "Hodnocené seriály"),
        ("OBLÍBENÉ FILMY", "tmdb_favorites_movies", "", Icons.MOVIE, "Oblíbené filmy"),
        ("OBLÍBENÉ SERIÁLY", "tmdb_favorites_tv", "", Icons.TVSHOW, "Oblíbené seriály"),
        ("VLASTNÍ SEZNAMY", "tmdb_user_lists", "", Icons.TMDB, "Vaše seznamy"),
    ]
    for label, action, media_type, icon, plot in name_list:
        _create_menu_item(f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}", plot, icon, action, url_params={'type': media_type, 'page': '1'})

    try:
        if not tmdb_account.load_account_data().get("session_id"):
            _create_menu_item("[  PŘIPOJIT K TMDB  ]", "Přihlásit k TMDB", Icons.TMDB, "tmdb_login")
    except Exception:
        pass
    set_view_mode(_handle, addon, "files", "movies_submenu")
    xbmcplugin.endOfDirectory(_handle)


def menu():
    # FIX PRE-EMPTIVE AND FILTERS [CONTINUE IS A HISTORY DIRECTORY]
    # continue_plot = f"[COLOR {Colors.ORANGE}]Další epizoda posledního seriálu[/COLOR]"
    continue_plot = f"[COLOR {Colors.ORANGE}]Pokračovat v seriálech z historie[/COLOR]"
    continue_icon = Icons.CONTINUE
    try:
        history = cache_manager.user_data_get("playback_history") or []
        for item in history:
            meta = item.get("meta", {})
            if meta.get("media_type") == "episode":
                show_title = meta.get("tv_show_title")
                season = int(meta.get("season", 0))
                episode = int(meta.get("episode", 0))
                if show_title:
                    # The directory contains all shows; this is only its history preview.
                    # continue_plot = f"Pokračovat: [B]{show_title}[/B] S{season:02d}E{episode+1:02d}"
                    continue_plot = f"Seriály z historie. Naposledy: [B]{show_title}[/B] S{season:02d}E{episode:02d}"
                    if meta.get("poster"):
                        continue_icon = meta.get("poster")
                    break
    except Exception:
        pass

    name_list = [
        ("[ ○ TAGY ○ ]", "list_random_keyword_submenu", "", "", "Hledání podle tagů", Icons.SEARCH_TAG),
        ("[ ○ HLEDÁNÍ ○ ]", "listing_search", "", "", "Vyhledávání na serverech", Icons.SEARCHING),
        ("[ ○ AI-SCRIPT ○ ]", "search_gemini", "", "", "Doporučení pomocí AI", Icons.AI_SCRIPT),
        ("[ ○ AI-WHISP ○ ]", "ai_recommend_for_me", "", "", "Doporučení podle historie", Icons.AI_WHISP),
        ("[ ○ AI-TODAY ○ ]", "ai_daily_mix", "", "", "Denní výběr na míru", Icons.AI_TODAY),
        ("[ ○ AI-MOOD ○ ]", "ai_mood_matcher", "", "", "Výběr podle nálady", Icons.AI_MOOD),
        ("||► PLAYBACK", "playback_history", "", "", "Historie přehrávání", Icons.PLAY_BACK),
        ("||► KNIHOVNA", "open_library", "", "", "Knihovna Kodi", Icons.LIBRARY),
        ("||► WATCH MOVIE", "list_recommendations_from_history", "list_recommendations_from_history_quick_play", "", "Doporučené filmy", Icons.PLAY_MOVIE),
        ("||► WATCH SHOW", "list_recommendations_from_history_series", "list_recommendations_from_history_series_quick_play", "", "Doporučené seriály", Icons.PLAY_SERIES),
        ("||► LATER MOVIE", "list_recommendations_from_watch_later", "list_recommendations_from_watch_later_quick_play", "", "Chci vidět: filmy", Icons.WATCH_MOVIE),
        ("||► LATER SHOW", "list_recommendations_from_watch_later_series", "list_recommendations_from_watch_later_series_quick_play", "", "Chci vidět: seriály", Icons.WATCH_SERIES),
        ("||► STREMIO DABING", "stremio_dabing_menu", "", "", "Stremio: CZ Dabing", Icons.STRM_DUBBING),
        ("||► STREMIO CHARTS", "stremio_charts_menu", "", "", "Stremio: Žebříčky", Icons.STRM_CHARTS),
        ("||► STREMIO ČSFD", "stremio_csfd_menu", "", "", "Stremio: ČSFD VOD", Icons.STRM_CSFD),
        ("||► STREMIO IMDB", "stremio_imdb_menu", "", "", "Stremio: IMDB TOP", Icons.STRM_IMDB),
        ("||► STREMIO STUDIA", "stremio_studios_menu", "", "", "Stremio: Studia", Icons.STRM_STUDIO),
        ("||► STREMIO SLUŽBY", "stremio_vod_menu", "", "", "Stremio: VOD", Icons.STRM_SERVICE),
        ("||► STREMIO HLEDÁNÍ", "stremio_search_menu", "", "", "Stremio: Vyhledat", Icons.STRM_SEARCH),
        ("||► RANDOMIZE", "random_trigger_main", "", "", "Náhodný film/seriál", Icons.RANDOMIZED),
        # FIX PRE-EMPTIVE AND FILTERS [RESTORE BROADCAST DIRECTORY]
        ("► BROADCAST", "sharing_history", "", "", "Sdílené tituly od ostatních uživatelů", Icons.BROADCAST),
        ("||► CONTINUE !", "continue_trigger_main", "", "", continue_plot, continue_icon),
        ("••••[ FILMY ]••••", "listing_movie_category", "", "", "Kategorie filmů TMDB", Icons.TMDB_MOVIE),
        ("••••[ SERIÁLY ]••••", "listing_serie_category", "", "", "Kategorie seriálů TMDB", Icons.TMDB_SHOW),
        ("► TMDB USER", "tmdb_menu", "", "", "Osobní TMDB účet", Icons.TMDB_USERS),
        ("► TMDB XTRA", "bonus_menu", "", "", "Doplňky a herci", Icons.TMDB_EXTRA),
        ("► ČSFD TOP'S", "csfd_menu", "", "", "Žebříčky z ČSFD", Icons.CSFD_TOPS),
        ("► ČSFD LIST'S", "csfd_menu_lists", "", "", "Seznamy z ČSFD", Icons.CSFD_LISTS),
        ("► TRAKT . TV", "trakt_menu", "", "", "Synchronizace Trakt.tv", Icons.TRAKT_TV),
        ("► SLEDOVANÉ", "most_watched", "", "", "Nejsledovanější tituly", Icons.PREHRAJ_TO),
        ("► HISTORIE", "prehrajto_history", "", "", "Historie serveru", Icons.PREHRAJ_TO),
        ("||► MANAGER", "series_menu", "", "", "Správce seriálů", Icons.MANAGER),
        ("||► LAUNCHER", "shell_launcher_menu", "", "", "Shell skripty", Icons.SHELL),
        ("||► SPEEDTEST", "diagnose_speed", "", "", "Test rychlosti", Icons.SPEEDTEST),
        ("||► PROVIDERS", "select_provider", "", "", "Výběr serveru", Icons.PROVIDERS),
        ("||► REGISTRACE", "register_play_mail", "", "", "Dočasný VIP účet", Icons.REGISTER),
        ("[ ○ NASTAVENÍ ○ ]", "open_settings", "", "", "Nastavení doplňku", Icons.SETTINGS),
    ]

    filtered_list = []
    for it in name_list:
        action = it[1]
        hide_key = f"menu_hide_{action}"
        if addon.getSetting(hide_key) != "":
            if not addon.getSettingBool(hide_key):
                continue
        if action == "continue_trigger_main" and not has_series_in_playback_history():
            continue
        filtered_list.append(it)

    new_episodes_count = 0
    try:
        episodes = cache_manager.user_data_get("new_episodes") or []
        if episodes:
            new_episodes_count = len(episodes)
            ep_item = (
                f"[B][COLOR {Colors.ORANGE}]||► EPIZODY :: {new_episodes_count}[/COLOR][/B]",
                "list_new_episodes_content",
                "", "",
                f"Nové epizody sledovaných seriálů ({new_episodes_count})",
                episodes[0].get("poster") or Icons.WATCHING
            )
            filtered_list.insert(0, ep_item)
    except Exception:
        pass

    if has_watch_later_items():
        filtered_list.insert(1, (f"[B][COLOR {Colors.ORANGE}]||► CHCI VIDĚT[/COLOR][/B]", "list_watch_later", "", "", "Položky k pozdějšímu zhlédnutí", Icons.WATCH_LATER))

    # Apply visibility after inserting dynamic watch-later/new-episode rows too.
    filtered_list = [item for item in filtered_list
                     if addon.getSetting(f"menu_hide_{item[1]}") == ""
                     or addon.getSettingBool(f"menu_hide_{item[1]}")]
    if addon.getSetting("show_section_mostwatched") != "" and not addon.getSettingBool("show_section_mostwatched"):
        filtered_list = [item for item in filtered_list if item[1] != "most_watched"]
    sorted_list = _sort_menu_items_by_order(filtered_list)
    # FIX PRE-EMPTIVE AND FILTERS [MAIN MENU BACKGROUND]
    # Explicit addon fanart prevents the skin from using a folder background.
    menu_fanart = addon.getAddonInfo("fanart")

    for label, action, name_param, type_param, plot_text, icon_path in sorted_list:
        if not label:
            continue
        custom_label = _get_custom_menu_label(action, label, count=new_episodes_count)
        url = get_url(action=action, name=name_param, type=type_param)
        li = xbmcgui.ListItem(custom_label)
        art_icon = icon_path or Icons.FOLDER
        # li.setArt({"icon": art_icon, "thumb": art_icon})
        li.setArt({"icon": art_icon, "thumb": art_icon, "fanart": menu_fanart})
        info_tag = li.getVideoInfoTag()
        info_tag.setPlot(plot_text)

        # FIX PRE-EMPTIVE AND FILTERS [OPEN CONTINUE AS A FOLDER]
        # Previously 'continue_trigger_main' was included in non_folder_actions.
        non_folder_actions = ("diagnose_speed", "shell_launcher_menu", "select_provider", "register_play_mail", "open_settings", "open_library", "random_trigger_main")
        is_folder = action not in non_folder_actions
        if not is_folder:
            li.setProperty("IsPlayable", "false")

        ctx = _get_main_menu_context(action, quick_action=name_param)
        li.addContextMenuItems(_sf_cm_items(ctx))
        xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=li, isFolder=is_folder)

    set_view_mode(_handle, addon, "files", "main_menu")
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def _handle_select_provider():
    provider_names = provider_manager.get_provider_names()
    is_multi_search_enabled = addon.getSettingBool("enable_multi_provider")
    options = [f"[B][COLOR {Colors.ORANGE}] ► [/COLOR]VÝCHOZÍ SERVER : [/B]{name.upper()}" for name in provider_names]
    options.append(f"[B][COLOR {Colors.ORANGE}] ► [/COLOR]MULTI - SEARCH [{'ZAPNUTO' if is_multi_search_enabled else 'VYPNUTO'}][/B]")

    choice = pop_dialog_select(f"[COLOR {Colors.ORANGE}]○ NASTAVENÍ PROVIDERS ○[/COLOR]", options)
    if choice == -1:
        return

    if choice < len(provider_names):
        selected = provider_names[choice]
        addon.setSettingBool("enable_multi_provider", False)
        addon.setSetting("active_provider", selected.upper())
        notify_ok(f"PROVIDER {selected.upper()}", category="SOURCE", time=2500)
    else:
        new_state = not is_multi_search_enabled
        addon.setSettingBool("enable_multi_provider", new_state)
        notify_ok(f"MULTI-SEARCH ► {'ZAPNUTO' if new_state else 'VYPNUTO'}", category="SOURCE", time=2500)
    reinitialize_clients()


def _handle_search_title(params):
    search_term = params.get("name", "")
    kb = xbmc.Keyboard(search_term, f"[COLOR {Colors.ORANGE}]○ HLEDAT TITUL ○[/COLOR]")
    kb.doModal()
    if kb.isConfirmed() and kb.getText().strip():
        q = kb.getText().strip()
        xbmc.executebuiltin(f"Container.Update({get_url(action='listing_search', name=q)})")


def _handle_movie_playlist(params, start_from_next=False):
    meta_raw = params.get("meta")
    if not meta_raw:
        return
    generator.create_movie_playlist(
        get_meta_from_cache(meta_raw),
        addon,
        provider_manager.get_active_provider(),
        tmdb_client,
        _handle,
        plugin_instance,
        start_from_next=start_from_next,
        source_list=params.get('source_list')
    )


def _handle_series_playlist(params, start_from_next=False, max_items=None):
    meta_json = params.get("meta")
    if not meta_json:
        return
    meta = get_meta_from_cache(meta_json)
    if meta.get("media_type") != "episode":
        return
    # FIX PRE-EMPTIVE AND FILTERS [EXPLICIT PLAY STARTS A NEW SESSION]
    # History may contain an exhausted budget. Only automatic Continue inherits it.
    if params.get('automatic') != 'true':
        meta = dict(meta)
        meta.pop('_play_er_queue_remaining', None)
        if str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
            from resources.lib.utils_prediction_handoff import begin_session
            begin_session(meta, addon, fresh=True)

    # FIX PRE-EMPTIVE AND FILTERS [CONTINUE SELECTION STARTS THE PLAYLIST DIRECTLY]
    # use_resolve = params.get('action') not in ['continue_trigger_main', 'continue_watching_main']
    use_resolve = params.get('action') not in [
        'continue_trigger_main', 'continue_watching_main', 'continue_quick_play_action'
    ]
    guard = params.get('_continue_guard')

    def prepare_automatic_start():
        if not guard.valid():
            return False
        GLOBAL_TRAKT_MONITOR.claim_playback()
        guard.bind_owner(GLOBAL_TRAKT_MONITOR._playback_owner)
        return guard.valid()

    generator.create_series_playlist(
        start_meta=meta,
        addon=addon,
        active_provider=plugin_instance.provider_manager.get_active_provider(),
        tmdb_client=plugin_instance.tmdb_client,
        handle=_handle,
        plugin_instance=plugin_instance,
        start_from_next=start_from_next,
        use_resolve=use_resolve,
        max_items=max_items,
        episodes_count=max_items,
        source_list=params.get('source_list'),
        start_guard=guard.valid if guard else None,
        prepare_start=prepare_automatic_start if guard else None,
        on_started=guard.mark_started if guard else None
    )


def _handle_tmdbh_player_bridge(params, plugin_instance):
    from resources.lib import utils_tmdbhelper_player
    utils_tmdbhelper_player.wait_modal_and_activate(params, plugin_instance)


def list_recommendations_from_history(is_widget=False):
    from resources.lib.recommendations import list_seed_recommendations
    list_seed_recommendations(plugin_instance, "playback_history", "movie", "list_recommendations_from_history")


def list_recommendations_from_history_quick_play():
    from resources.lib.recommendations import quick_play_seed_recommendation
    quick_play_seed_recommendation(plugin_instance, "playback_history", "movie")


def list_recommendations_from_history_series(is_widget=False):
    from resources.lib.recommendations import list_seed_recommendations
    list_seed_recommendations(plugin_instance, "playback_history", "tv", "list_recommendations_from_history_series")


def list_recommendations_from_history_series_quick_play():
    from resources.lib.recommendations import quick_play_seed_recommendation
    quick_play_seed_recommendation(plugin_instance, "playback_history", "tv")


def list_recommendations_from_watch_later(is_widget=False):
    from resources.lib.recommendations import list_seed_recommendations
    list_seed_recommendations(plugin_instance, "watch_later", "movie", "list_recommendations_from_watch_later")


def list_recommendations_from_watch_later_quick_play():
    from resources.lib.recommendations import quick_play_seed_recommendation
    quick_play_seed_recommendation(plugin_instance, "watch_later", "movie")


def list_recommendations_from_watch_later_series(is_widget=False):
    from resources.lib.recommendations import list_seed_recommendations
    list_seed_recommendations(plugin_instance, "watch_later", "tv", "list_recommendations_from_watch_later_series")


def list_recommendations_from_watch_later_series_quick_play():
    from resources.lib.recommendations import quick_play_seed_recommendation
    quick_play_seed_recommendation(plugin_instance, "watch_later", "tv")



def clear_csfd_cache(params=None):
    cache_manager.cache_clear("CSFD")
    notify_ok("CLEAR ČSFD CACHE", category="CSFD")
    cache_manager.safe_refresh()


def _handle_play_random(params):
    # FIX PRE-EMPTIVE AND FILTERS [RESTORE RANDOMIZE WITHOUT GENERATOR CHANGES]
    # actions._handle_play_random(params)  # Missing legacy implementation.
    from resources.lib.randomize import run
    run(plugin_instance)


def _play_from_library(params):
    tmdb_id = params.get("tmdb_id")
    if not tmdb_id:
        return
    actions.tmdbh_bridge(
        {
            "tmdb_id": tmdb_id,
            "media_type": params.get("media_type", "movie"),
            "season": params.get("season"),
            "episode": params.get("episode"),
            "mode": "play",
            "library": "true",
        },
        plugin_instance,
    )


def _handle_library_add(params):
    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "movie")
    title = params.get("title", "Unknown")
    year = params.get("year", "")
    lib_path = xbmcvfs.translatePath(addon.getSetting(SETTING_ID_LIBRARY_DIR) or DEFAULT_LIBRARY_DIR)

    folder_name = f"{title} ({year})".strip()
    target_dir = os.path.join(lib_path, "Movies" if media_type == "movie" else "TV Shows", folder_name)
    if not xbmcvfs.exists(target_dir):
        xbmcvfs.mkdirs(target_dir)

    strm_file = os.path.join(target_dir, f"{folder_name}.strm")
    url = f"plugin://plugin.video.play_er/?action=play_from_library&tmdb_id={tmdb_id}&media_type={media_type}"
    with SafeVFSFile(strm_file, "w") as f:
        f.write(url)
    notify_ok("SAVE Knihovna aktualizována", category="SYSTEM")


def _find_library_exports(tmdb_id, media_type):
    """Find only matching PLAY.ER exports in the configured local library."""
    if not isinstance(tmdb_id, str) or not tmdb_id.isascii() or not tmdb_id.isdecimal() or int(tmdb_id) < 1:
        raise ValueError("Neplatné TMDB ID")
    if media_type not in ("movie", "tv"):
        raise ValueError("Neplatný typ titulu")
    root = xbmcvfs.translatePath(addon.getSetting(SETTING_ID_LIBRARY_DIR) or DEFAULT_LIBRARY_DIR)
    if not root or "://" in root:
        raise ValueError("Odebrání podporuje jen místní knihovnu")
    category = os.path.join(root, "Movies" if media_type == "movie" else "TV Shows")
    if not os.path.exists(category):
        return []
    if os.path.islink(category) or not os.path.isdir(category):
        raise ValueError("Zkontrolujte složku knihovny")
    expected = f"plugin://plugin.video.play_er/?action=play_from_library&tmdb_id={tmdb_id}&media_type={media_type}"
    import stat
    matches = []
    with os.scandir(category) as folders:
        for folder in folders:
            if not folder.is_dir(follow_symlinks=False):
                continue
            path = os.path.join(folder.path, folder.name + ".strm")
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                continue
            # Do not follow symlinks and do not read unrelated large files.
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024:
                continue
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                fd = os.open(path, flags)
                with os.fdopen(fd, "r", encoding="utf-8") as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                        continue
                    if stream.read(1025).strip() == expected:
                        matches.append(path)
            except (FileNotFoundError, UnicodeError):
                continue
    return sorted(matches)


def _handle_library_remove(params):
    tmdb_id = str(params.get("tmdb_id") or "")
    media_type = params.get("media_type")
    try:
        matches = _find_library_exports(tmdb_id, media_type)
        if not matches:
            notify_info("INFO STRM export nebyl nalezen", category="SYSTEM")
            return
        dialog = xbmcgui.Dialog()
        if len(matches) > 1:
            choice = dialog.select("Vyberte STRM export k odebrání", [os.path.basename(os.path.dirname(path)) for path in matches])
            if choice < 0 or choice >= len(matches):
                return
        else:
            choice = 0
        path = matches[choice]
        if not dialog.yesno("ODEBRAT STRM EXPORT", f"Odebrat export {os.path.basename(os.path.dirname(path))}?\nZáznam v knihovně Kodi se neodstraní automaticky."):
            return
        # Recheck the identity and symlink status after the user confirmation.
        if path not in _find_library_exports(tmdb_id, media_type):
            notify_error("ERROR STRM export se změnil", category="SYSTEM")
            return
        os.remove(path)
        notify_ok("STRM export odebrán", category="SYSTEM")
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass
    except ValueError as exc:
        notify_error(f"ERROR {exc}", category="SYSTEM")
    except (OSError, UnicodeError) as exc:
        log(f"LIBRARY - Chyba odebrání STRM exportu: {exc}", xbmc.LOGWARNING)
        notify_error("ERROR STRM export nelze odebrat; zkontrolujte místní knihovnu", category="SYSTEM")


def _handle_download(params):
    notify_info("INFO Stahování zatím není implementováno", category="DOWNLOAD")


def register_play_mail_account():
    actions.register_play_mail_account(plugin_instance)


def _get_community_share_context(title, tmdb_id, media_type, year, poster, plot, show_title=''):
    if not addon.getSettingBool('enable_community_sharing'):
        return None
    try:
        payload = {'title': title, 'tv_show_title': show_title, 'tmdb_id': tmdb_id, 'media_type': media_type, 'year': year, 'poster': poster, 'plot': plot}
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        b64 = base64.urlsafe_b64encode(raw).decode('utf-8')
        return (f"[COLOR {Colors.ORANGE}]► SDÍLET OSTATNÍM[/COLOR]", f"RunPlugin({get_url(action='share_menu', payload=b64)})")
    except Exception:
        return None


def _zip_dir_recursive(zipf, virtual_dir_path, zip_base_name, zip_local_path, stats, visited=None):
    if visited is None:
        visited = set()

    virtual_dir_path = virtual_dir_path.rstrip("/\\") + "/"
    translated_dir = xbmcvfs.translatePath(virtual_dir_path)
    local_directory = bool(translated_dir and os.path.isdir(translated_dir))
    directory_key = os.path.normcase(os.path.realpath(translated_dir)) if local_directory else virtual_dir_path
    if directory_key in visited:
        return
    visited.add(directory_key)

    if local_directory:
        dirs, files = [], []
        for entry in os.listdir(translated_dir):
            local_entry = os.path.join(translated_dir, entry)
            if os.path.isdir(local_entry):
                dirs.append(entry)
            elif os.path.isfile(local_entry):
                files.append(entry)
    else:
        dirs, files = xbmcvfs.listdir(virtual_dir_path)
        if dirs is None or files is None:
            raise OSError("Složku nelze přečíst přes Kodi VFS")

    archive_root = zip_base_name.replace("\\", "/").strip("/")
    if not archive_root:
        raise ValueError("Název složky pro ZIP je prázdný")
    zipf.writestr(f"{archive_root}/", b"")

    archive_real_path = os.path.normcase(os.path.realpath(zip_local_path))
    for file_name in files:
        virtual_file_path = posixpath.join(virtual_dir_path, file_name)
        local_file_path = os.path.join(translated_dir, file_name) if local_directory else xbmcvfs.translatePath(virtual_file_path)
        if local_file_path and os.path.normcase(os.path.realpath(local_file_path)) == archive_real_path:
            continue

        arcname = posixpath.join(archive_root, file_name)
        source_context = open(local_file_path, "rb") if local_directory else SafeVFSFile(virtual_file_path, "rb")
        with source_context as source:
            with zipf.open(arcname, "w", force_zip64=True) as destination:
                while True:
                    chunk = source.read(1024 * 1024) if local_directory else source.readBytes(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
        stats["files"] += 1

    for dir_name in dirs:
        child_path = os.path.join(translated_dir, dir_name) if local_directory else posixpath.join(virtual_dir_path, dir_name) + "/"
        child_archive_path = posixpath.join(archive_root, dir_name)
        _zip_dir_recursive(zipf, child_path, child_archive_path, zip_local_path, stats, visited)


def _zip_backup_file(zipf, virtual_path, archive_name, zip_local_path, stats):
    """Include one selected file without walking its parent directory."""
    local_path = xbmcvfs.translatePath(virtual_path)
    if local_path and os.path.isdir(local_path):
        raise IsADirectoryError("Vybraná cesta není soubor: " + archive_name)
    local_file = bool(local_path and os.path.isfile(local_path))
    if not local_file:
        if not xbmcvfs.exists(virtual_path):
            raise FileNotFoundError("Vybraný soubor neexistuje: " + archive_name)
        if xbmcvfs.Stat(virtual_path).st_mode() & 0o170000 == 0o040000:
            raise IsADirectoryError("Vybraná cesta není soubor: " + archive_name)
    if local_path and os.path.normcase(os.path.realpath(local_path)) == os.path.normcase(os.path.realpath(zip_local_path)):
        return
    source_context = open(local_path, "rb") if local_file else SafeVFSFile(virtual_path, "rb")
    with source_context as source:
        with zipf.open(archive_name, "w", force_zip64=True) as destination:
            while True:
                chunk = source.read(1024 * 1024) if local_file else source.readBytes(1024 * 1024)
                if not chunk:
                    break
                destination.write(chunk)
    stats["files"] += 1



def _normalize_backup_path(path):
    path = (path or "").strip()
    home_userdata = "special://home/userdata"
    if path == home_userdata or path.startswith(home_userdata + "/"):
        return "special://userdata" + path[len(home_userdata):]
    return path


def _backup_settings_to_telegram():
    backup_sources = []
    seen_paths = set()
    for index in range(1, 6):
        path = _normalize_backup_path(addon.getSetting(f"backup_path_{index}"))
        if not path:
            continue
        normalized_path = path.rstrip("/\\") or path
        path_key = os.path.normcase(normalized_path)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)

        folder_name = normalized_path.replace("\\", "/").rsplit("/", 1)[-1] or f"backup_{index}"
        if folder_name in (".", ".."):
            folder_name = f"backup_{index}"
        existing_names = {entry[1] for entry in backup_sources}
        if folder_name in existing_names:
            folder_name = f"{folder_name}_{index}"
        backup_sources.append((normalized_path, folder_name))

    backup_files = []
    archive_names = {entry[1] for entry in backup_sources}
    for index in range(1, 6):
        path = _normalize_backup_path(addon.getSetting(f"backup_file_{index}"))
        if not path:
            continue
        path_key = os.path.normcase(path.rstrip("/\\"))
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        file_name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if file_name in ("", ".", ".."):
            notify_error("Neplatný název souboru pro zálohu", category="TELEGRAM")
            return
        archive_name = file_name
        stem, extension = os.path.splitext(file_name)
        suffix = 2
        while archive_name in archive_names:
            archive_name = f"{stem}_{suffix}{extension}"
            suffix += 1
        archive_names.add(archive_name)
        backup_files.append((path, archive_name))

    if not backup_sources and not backup_files:
        notify_error("Není vybrána žádná složka ani soubor pro zálohu", category="TELEGRAM")
        return

    manager = get_telegram_manager()
    if not manager:
        notify_error("Telegram není dostupný nebo není nakonfigurován", category="TELEGRAM")
        return

    temp_dir = xbmcvfs.translatePath("special://temp/")
    if not temp_dir:
        notify_error("Nelze určit dočasnou složku pro ZIP", category="TELEGRAM")
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_name = f"PLAY.ER__{timestamp}.zip"
    zip_path = os.path.join(temp_dir, zip_name)
    stats = {"files": 0}
    notify_info("Vytvářím ZIP zálohu ...", category="TELEGRAM")

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for virtual_path, folder_name in backup_sources:
                translated_path = xbmcvfs.translatePath(virtual_path)
                if not xbmcvfs.exists(virtual_path) and not (translated_path and os.path.isdir(translated_path)):
                    raise FileNotFoundError(
                        f"Vybraná složka neexistuje: {folder_name} ({translated_path})"
                    )
                _zip_dir_recursive(archive, virtual_path, folder_name, zip_path, stats)

            for virtual_path, archive_name in backup_files:
                _zip_backup_file(archive, virtual_path, archive_name, zip_path, stats)

        if manager.send_backup(
            zip_path,
            caption=(
                "<code>----------------------------------</code>\n"
                "<b>📦  JUDENRAMPE  ::  BACKUPS REPORTER</b>\n"
                "<code>----------------------------------</code>\n\n"
                f"<b>DATE : </b><code>{timestamp}</code>\n"
                f"<b>FOLDERS : </b><code>{len(backup_sources)}</code>\n"
                f"<b>FILES : </b><code>{stats['files']}</code>\n\n"
                "<code>----------------------------------</code>\n\n"
                "<b> SENT FROM YOUR    [ FUCKING ]    PLAY.ER</b>"
            )
        ):
            notify_ok(f"ZIP záloha odeslána na Telegram ({stats['files']} souborů)", category="TELEGRAM")
        else:
            notify_error("ZIP se vytvořil, ale Telegram jej nepřijal. Zkontrolujte nastavení a kodi.log.", category="TELEGRAM")
    except Exception as e:
        log(f"TELEGRAM BACKUP ERROR: {e}", xbmc.LOGERROR)
        notify_error("Telegram ZIP zálohu se nepodařilo vytvořit nebo odeslat. Podrobnosti jsou v kodi.log.", category="TELEGRAM")
    finally:
        try:
            if xbmcvfs.exists(zip_path):
                xbmcvfs.delete(zip_path)
        except Exception as e:
            log(f"TELEGRAM BACKUP CLEANUP ERROR: {e}", xbmc.LOGWARNING)


def _send_accounts_to_telegram():
    gm = get_telegram_manager()
    if gm:
        gm.send_account_report()
        notify_ok("ACCOUNT Report odeslán", category="TELEGRAM")


def _get_trakt_social_users():
    users = []
    seen = set()
    for setting_id in ("trakt_social_user", "trakt_social_user_2", "trakt_social_user_3"):
        username = addon.getSetting(setting_id).strip()
        if username and username.casefold() not in seen:
            users.append(username)
            seen.add(username.casefold())
    return users


def _display_trakt_menu(params):
    menu_items = [
        ("NÁSLEDUJÍCÍ EPIZODY", "trakt_next_episodes_menu", Icons.TRAKT_WHITE, {}),
        ("IN-PROGRESS", "trakt_in_progress", Icons.TRAKT_WHITE, {}),
        ("POPULAR LISTS", "trakt_popular_lists", Icons.TRAKT_WHITE, {}),
        ("TRENDING : FILMY", "trakt_trending", Icons.MOVIE, {"category": "movies"}),
        ("TRENDING : SERIÁLY", "trakt_trending", Icons.TVSHOW, {"category": "shows"}),
        ("WATCHLIST : FILMY", "trakt_watchlist", Icons.MOVIE, {"category": "movies"}),
        ("WATCHLIST : SERIÁLY", "trakt_watchlist", Icons.TVSHOW, {"category": "shows"}),
        ("OBLÍBENÉ : FILMY", "trakt_favorites", Icons.MOVIE, {"category": "movies"}),
        ("OBLÍBENÉ : SERIÁLY", "trakt_favorites", Icons.TVSHOW, {"category": "shows"}),
        ("DOPORUČENÉ : FILMY", "trakt_recommended", Icons.MOVIE, {"category": "movies"}),
        ("DOPORUČENÉ : SERIÁLY", "trakt_recommended", Icons.TVSHOW, {"category": "shows"}),
        ("OČEKÁVANÉ : FILMY", "trakt_anticipated", Icons.MOVIE, {"category": "movies"}),
        ("OČEKÁVANÉ : SERIÁLY", "trakt_anticipated", Icons.TVSHOW, {"category": "shows"}),
        ("BOX OFFICE", "trakt_boxoffice", Icons.MOVIE, {}),
        ("TRAKT.TV HISTORIE", "trakt_history", Icons.TRAKT_RED, {}),
    ]
    for label, action, icon, url_params in menu_items:
        _create_menu_item(f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}", "", icon, action, url_params=url_params)
    for username in _get_trakt_social_users():
        _create_menu_item(
            f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]FOLLOWED : {username}",
            f"Historie sledování uživatele {username} na Trakt.tv",
            Icons.TRAKT_WHITE,
            "build_user_feed_menu",
            url_params={"username": username},
        )
    if not addon.getSetting("trakt_access_token").strip() or not addon.getSetting("trakt_refresh_token").strip():
        _create_menu_item(
            f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PŘIHLÁSIT K TRAKT.TV",
            "Připojit účet Trakt.tv",
            Icons.TRAKT_WHITE,
            "trakt_authenticate",
            is_folder=False,
        )
    xbmcplugin.endOfDirectory(_handle)


def build_social_feed_menu(params):
    xbmcplugin.setPluginCategory(_handle, "TRAKT.TV : SOCIAL FEED")
    for username in _get_trakt_social_users():
        _create_menu_item(
            f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]FOLLOWED : {username}",
            f"Historie sledování uživatele {username} na Trakt.tv",
            Icons.TRAKT_WHITE,
            "build_user_feed_menu",
            url_params={"username": username},
        )
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def build_user_feed_menu(params):
    username = (params.get("username") or "").strip()
    if username:
        xbmcplugin.setPluginCategory(_handle, f"TRAKT.TV : {username}")
        for label, media_type, icon in (
            ("HISTORIE : FILMY", "movies", Icons.MOVIE),
            ("HISTORIE : SERIÁLY", "episodes", Icons.TVSHOW),
        ):
            _create_menu_item(
                f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}",
                f"Historie sledování uživatele {username}",
                icon,
                "trakt_user_history",
                url_params={"username": username, "media_type": media_type},
            )
    xbmcplugin.endOfDirectory(_handle, succeeded=True)


def _display_player_menu(params, menu_page='main'):
    # FIX PRE-EMPTIVE AND FILTERS [EXECUTE XML MENU RESULTS]
    from resources.lib.dialog_menu import run_player_menu
    options = dict(params or {})
    options.setdefault('menu_page', menu_page)
    return run_player_menu(options, addon, session, _handle_select_provider,
                           toggle_filtering, toggle_tmdb_lang_filter)


def toggle_tmdb_lang_filter():
    # FIX PRE-EMPTIVE AND FILTERS [KEEP THE TMDB FILTER ENUM]
    modes = ('OFF', 'SOFT', 'HARD')
    current = (addon.getSetting('filter_tmdb_language') or 'SOFT').upper()
    next_mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else 'SOFT'
    addon.setSetting('filter_tmdb_language', next_mode)
    notify_info(f'TMDB FILTER: {next_mode}', category='TMDB', time=3000)
    cache_manager.safe_refresh()


def play_trailer(params):
    # FIX PRE-EMPTIVE AND FILTERS [RESTORE EXISTING TRAILER HELPER]
    from resources.lib.utils import play_trailer_from_tmdb_id
    media_type = params.get('media_type', 'movie')
    if media_type in ('episode', 'tvshow', 'show', 'season'):
        media_type = 'tv'
    return play_trailer_from_tmdb_id(params.get('tmdb_id'), media_type, tmdb_client)


def _run_speedtest(params):
    from resources.lib import speedtest
    speedtest.diagnose_speed(addon)


def _open_shell_menu():
    from resources.lib.shell_menu import ShellMenu
    ShellMenu.show_shell_menu()


def _apply_settings_and_refresh():
    reinitialize_clients()
    try:
        from resources.lib import sharing_service
        sharing_service.force_check()
    except Exception:
        pass
    notify_info("RE-INICIALIZACE ADDON", category="SYSTEM", time=3000)
    cache_manager.safe_refresh()


def trakt_next_menu(params):
    trakt.trakt_my_calendar(
        {"category": "shows", "days": 30, "title": "NÁSLEDUJÍCÍ EPIZODY"},
        addon=addon,
        handle=_handle,
        session=session,
    )


# FIX PRE-EMPTIVE AND FILTERS [CONTINUE HISTORY LIST AND SEASON ROLLOVER]
# Original item construction (the route still opens this same directory):
# for item in history:
#     meta = item.get("meta", {})
#     if meta.get("media_type") == "episode":
#         tid = meta.get("tmdb_id")
#         if not tid or tid in seen:
#             continue
#         seen.add(tid)
#         title = f"{meta.get('tv_show_title', 'Seriál')} S{int(meta.get('season', 0)):02d}E{int(meta.get('episode', 0))+1:02d}"
#         li = xbmcgui.ListItem(label=title)
#         li.setArt({'icon': meta.get('poster') or Icons.CONTINUE, 'thumb': meta.get('poster') or Icons.CONTINUE})
#         url = get_url(action="continue_quick_play_action", meta=store_meta_in_cache(meta))
#         xbmcplugin.addDirectoryItem(_handle, url, li, isFolder=False)
def list_continue_watching_series(is_widget=False):
    history = cache_manager.user_data_get("playback_history") or []
    seen = set()
    xbmcplugin.setContent(_handle, "episodes")

    for item in history:
        meta = item.get("meta", {}) if isinstance(item, dict) else {}
        if not isinstance(meta, dict) or meta.get("media_type") != "episode":
            continue
        try:
            tid = str(int(meta.get("tmdb_id")))
            season, episode = int(meta.get("season")), int(meta.get("episode"))
            if int(tid) <= 0 or season < 0 or episode < 1:
                continue
        except (TypeError, ValueError):
            continue
        if tid in seen:
            continue
        seen.add(tid)

        coordinates = generator._next_episode_coordinates(tid, season, episode, tmdb_client)
        show_title = meta.get('tv_show_title') or 'Seriál'
        next_label = f"S{coordinates[0]:02d}E{coordinates[1]:02d}" if coordinates else 'Další epizoda není dostupná'
        title = f"{show_title} — {next_label}"
        display_meta = dict(meta, title=title,
                            plot=f"Naposledy přehráno: S{season:02d}E{episode:02d}. Následuje: {next_label}.")
        if coordinates:
            display_meta.update(season=coordinates[0], episode=coordinates[1])
        li = xbmcgui.ListItem(label=title)
        if tmdb_client:
            tmdb_client.fill_list_item(li, display_meta, 'episode')
        li.setArt({k: v for k, v in {
            'icon': meta.get('poster') or Icons.CONTINUE,
            'thumb': meta.get('poster') or Icons.CONTINUE,
            'poster': meta.get('poster'), 'fanart': meta.get('fanart')
        }.items() if v})
        li.getVideoInfoTag().setPlot(display_meta['plot'])
        li.setProperty('IsPlayable', 'false')
        show_props = dict(meta, title=show_title, media_type='tv')
        context_menu = actions._get_context_menu(
            'playback_history_show', addon=addon, props=show_props,
            title=show_title, history_title=meta.get('tv_show_title', show_title),
            tmdb_id=tid, media_type='tv'
        )
        li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
        # Pass the LAST watched episode. The generator advances it exactly once.
        url = get_url(action="continue_quick_play_action", meta=store_meta_in_cache(meta))
        xbmcplugin.addDirectoryItem(_handle, url, li, isFolder=False)

    if not is_widget:
        set_view_mode(_handle, addon, "episodes", "episodes")
    xbmcplugin.endOfDirectory(_handle, succeeded=True, cacheToDisc=False)


def continue_quick_play_action(params):
    # FIX PRE-EMPTIVE AND FILTERS [RESTORE CONTINUE SHOW SELECTION]
    # The former target does not exist in actions.py:
    # actions.continue_quick_play_action(params)
    if not params.get('meta'):
        history = cache_manager.user_data_get("playback_history") or []
        for item in history:
            meta = item.get('meta', {}) if isinstance(item, dict) else {}
            if not isinstance(meta, dict) or meta.get('media_type') != 'episode':
                continue
            try:
                if int(meta.get('tmdb_id')) <= 0 or int(meta.get('season')) < 0 or int(meta.get('episode')) < 1:
                    continue
            except (TypeError, ValueError):
                continue
            params = dict(params, meta=store_meta_in_cache(meta))
            break
        else:
            notify_info("INFO V historii není seriál pro pokračování", category="CONTINUE")
            return
    _handle_series_playlist(params, start_from_next=True)


def random_trigger_main(params):
    # FIX PRE-EMPTIVE AND FILTERS [RESTORE RANDOMIZE WITHOUT GENERATOR CHANGES]
    # actions._handle_play_random(params)  # Missing legacy implementation.
    from resources.lib.randomize import run
    run(plugin_instance)


def _handle_continue_watching(params):
    _handle_series_playlist(params, start_from_next=True)


def _monitor_remove_watch_later(params):
    try:
        actions.remove_from_watch_later(params, plugin_instance)
    except cache_manager.CacheStorageError as e:
        log(f"WATCH LATER - Playback cleanup could not update storage: {e}", xbmc.LOGWARNING)


def find_similar(params, plugin_instance):
    actions.find_similar(params, plugin_instance)


def show_similar_results(params, plugin_instance):
    actions.show_similar_results(params, plugin_instance)


def _create_actions_map():
    return {
        "configure_af3_views": lambda p: __import__('resources.lib.view_modes', fromlist=['configure_af3_views']).configure_af3_views(addon),
        "show_metrics": lambda p: __import__('resources.lib.dialog_metrics', fromlist=['']).show_system_metrics(),
        "show_addon_log": lambda p: __import__('resources.lib.dialog_log', fromlist=['']).show_addon_log(),
        "show_similar_results": lambda p: show_similar_results(p, plugin_instance),
        "find_similar": lambda p: find_similar(p, plugin_instance),
        "go_home": lambda p: menu(),
        "add_to_watch_later": lambda p: actions.add_to_watch_later(p, plugin_instance),
        "open_library": lambda p: xbmc.executebuiltin('ActivateWindow(Videos,videodb://,return)'),
        "remove_from_watch_later": lambda p: actions.remove_from_watch_later(p, plugin_instance),
        "remove_new_episode": lambda p: _remove_episode_from_new_list(get_meta_from_cache(p.get("meta")), force_refresh=True),
        "show_player_menu": lambda p: _display_player_menu(p),
        "clear_cache": lambda p: (cache_manager.cache_clear(), xbmc.executebuiltin("Dialog.Close(busydialog)")),
        "clear_ram_cache": lambda p: (cache_manager.clear_ram_cache(), notify_ok("RAM cache vymazána", category="SYSTEM")),
        "backup_settings": lambda p: _backup_settings_to_telegram(),
        "send_accounts": lambda p: _send_accounts_to_telegram(),
        "tmdb_menu": lambda p: tmdb_menu(),
        "tmdb_login": lambda p: tmdb_account.tmdb_start_auth_flow(addon, handle=_handle),
        "tmdb_watchlist_movies": lambda p: tmdb_client.list_account_items("watchlist", "movie", int(p.get("page", 1))),
        "tmdb_watchlist_tv": lambda p: tmdb_client.list_account_items("watchlist", "tv", int(p.get("page", 1))),
        "tmdb_rated_movies": lambda p: tmdb_client.list_account_items("rated", "movie", int(p.get("page", 1))),
        "tmdb_rated_tv": lambda p: tmdb_client.list_account_items("rated", "tv", int(p.get("page", 1))),
        "tmdb_favorites_movies": lambda p: tmdb_client.list_account_items("favorites", "movie", int(p.get("page", 1))),
        "tmdb_favorites_tv": lambda p: tmdb_client.list_account_items("favorites", "tv", int(p.get("page", 1))),
        "tmdb_recommendations_movies": lambda p: tmdb_client.list_recommendations("movie", int(p.get("page", 1))),
        "tmdb_recommendations_tv": lambda p: tmdb_client.list_recommendations("tv", int(p.get("page", 1))),
        "tmdb_user_lists": lambda p: tmdb_client.list_user_lists(int(p.get("page", 1))),
        "tmdb_user_list_items": lambda p: tmdb_client.list_user_list_items(p.get("list_id"), int(p.get("page", 1))),
        "tmdb_add_watchlist": lambda p: tmdb_account.tmdb_toggle_watchlist(p.get("tmdb_id"), p.get("media_type"), add=True),
        "tmdb_remove_watchlist": lambda p: tmdb_account.tmdb_toggle_watchlist(p.get("tmdb_id"), p.get("media_type"), add=False),
        "tmdb_add_favorite": lambda p: tmdb_account.tmdb_toggle_favorite(p.get("tmdb_id"), p.get("media_type"), add=True),
        "tmdb_remove_favorite": lambda p: tmdb_account.tmdb_toggle_favorite(p.get("tmdb_id"), p.get("media_type"), add=False),
        "tmdb_rate": lambda p: tmdb_account.tmdb_rate_prompt_and_send(p.get("tmdb_id"), p.get("media_type"), handle=_handle),
        "tmdb_remove_rating": lambda p: tmdb_account.tmdb_remove_rating(p.get("tmdb_id"), p.get("media_type")),
        "search_tmdb": lambda p: tmdb_client.search(p.get("name"), p.get("type")),
        "listing_year_category": lambda p: tmdb_client.list_years_category(p.get("type")),
        "listing_year": lambda p: tmdb_client.list_by_year(p.get("page"), p.get("type"), p.get("id")),
        "listing_genre_category": lambda p: tmdb_client.list_genres_category(p.get("type")),
        "listing_studio_category": lambda p: tmdb_client.list_studios_category(p.get("type")),
        "listing_studio": lambda p: tmdb_client.list_by_studio(p.get("page"), p.get("type"), p.get("id")),
        "listing_genre": lambda p: tmdb_client.list_by_genre(p.get("page"), p.get("type"), p.get("id")),
        "listing_trending": lambda p: tmdb_client.list_trending(int(p.get("page", 1)), p.get("type"), p.get("time_window", "week")),
        "list_providers": lambda p: tmdb_client.list_providers(p.get("type")),
        "trending_submenu": lambda p: tmdb_client.trending_submenu(p.get("type")),
        "listing_provider": lambda p: tmdb_client.list_by_provider(p.get("id"), p.get("type"), p.get("page", "1")),
        "listing_discover": lambda p: tmdb_client.list_discover(p.get("page", "1"), p.get("type")),
        "listing_top_rated": lambda p: tmdb_client.list_top_rated(p.get("page", "1"), p.get("type")),
        "listing_now_playing": lambda p: tmdb_client.list_now_playing(p.get("page", "1"), p.get("type")),
        "listing_upcoming": lambda p: tmdb_client.list_upcoming(p.get("page", "1"), p.get("type")),
        "listing_airing_today": lambda p: tmdb_client.list_airing_today(p.get("page", "1"), p.get("type")),
        "list_actors": lambda p: tmdb_client.list_actors(int(p.get("page", 1))),
        "search_actor": lambda p: tmdb_client.search_actor(p.get("name")),
        "browse_by_submenu": lambda p: tmdb_client.browse_by_submenu(p.get("type")),
        "randomised_submenu": lambda p: tmdb_client.randomised_submenu(p.get("type")),
        "list_highest_revenue": lambda p: tmdb_client.list_highest_revenue(p.get("page", "1"), p.get("type")),
        "list_most_voted": lambda p: tmdb_client.list_most_voted(p.get("page", "1"), p.get("type")),
        "list_random_genre": lambda p: tmdb_client.list_random_genre(p.get("type", p.get("media_type"))),
        "actor_detail": lambda p: tmdb_client.actor_detail(p.get("id")),
        "trending_actors_submenu": lambda p: tmdb_client.trending_actors_submenu(),
        "list_trending_actors": lambda p: tmdb_client.list_trending_actors(int(p.get("page", 1)), p.get("time_window")),
        "random_genre_content": lambda p: tmdb_client.list_random_genre_content(p.get("id"), p.get("type"), p.get("page", "1")),
        "list_random_provider": lambda p: tmdb_client.list_random_provider(p.get("type")),
        "random_provider_content": lambda p: tmdb_client.list_random_provider_content(p.get("id"), p.get("type"), p.get("page", "1")),
        "list_random_keyword_submenu": lambda p: tmdb_client.list_random_keyword_submenu(),
        "list_random_keyword": lambda p: tmdb_client.list_random_keyword(p.get("type")),
        "random_keyword_content": lambda p: tmdb_client.list_random_keyword_content(p.get("id"), p.get("type"), p.get("page", "1")),
        "list_random_studio": lambda p: tmdb_client.list_random_studio(p.get("type")),
        "random_studio_content": lambda p: tmdb_client.list_random_studio_content(p.get("id"), p.get("type"), p.get("page", "1")),
        "list_random_network": lambda p: tmdb_client.list_random_network(p.get("type")),
        "random_network_content": lambda p: tmdb_client.list_random_network_content(p.get("id"), p.get("type"), p.get("page", "1")),
        "listing_on_the_air": lambda p: tmdb_client.list_on_the_air(p.get("page", "1"), p.get("type")),
        "find_sources": lambda params: actions.find_and_list_sources_multi(params, plugin_instance),
        "tmdbh_bridge": lambda p: actions.tmdbh_bridge(p, plugin_instance),
        "tmdbh_player_bridge": lambda p: _handle_tmdbh_player_bridge(p, plugin_instance),
        "tmdb_tv_season": lambda p: tmdb_client.show_tv_season(p.get("tmdb_id"), p.get("season"), p.get("meta"), p.get("source_list")),
        "listing_tmdb_tv": lambda p: tmdb_client.show_tv_detail(p.get("tmdb_id"), p.get("meta"), p.get("source_list")),
        "play": lambda p: actions.resolve_video(p.get("link"), p.get("provider"), p.get("meta", "{}"), source_list=p.get("source_list"), plugin_instance=plugin_instance, direct_play=p.get("direct_play") == "true", prediction_ref=p.get("prediction_ref")),
        "create_series_playlist_action": lambda p: _handle_series_playlist(p),
        "create_movie_playlist_action": lambda p: _handle_movie_playlist(p),
        "toggle_series_autoplay": lambda p: toggle_series_autoplay(),
        "toggle_movie_autoplay": lambda p: toggle_movie_autoplay(),
        "toggle_filtering": lambda p: toggle_filtering(),
        "toggle_subscription": lambda p: actions.toggle_subscription(p, plugin_instance),
        "clear_most_watched_cache": lambda p: cache_manager.cache_clear("MOST_WATCHED"),
        "select_csfd": lambda p: handle_csfd_selection(p.get("csfd_id"), p.get("search_type")),
        "csfd_menu": lambda p: list_csfd_charts_menu(),
        "csfd_menu_lists": lambda p: list_csfd_category_menu(),
        "list_csfd_daily_tips": lambda p: list_csfd_daily_tips(),
        "list_csfd_chart_items": lambda p: list_csfd_chart_items(p),
        "list_csfd_category_items": lambda p: list_csfd_category_items(p),
        "trakt_menu": lambda p: _display_trakt_menu(p),
        "trakt_authenticate": lambda p: trakt.trakt_authenticate(addon, session),
        "trakt_history": lambda p: trakt.trakt_watched_history(p, addon, _handle, session),
        "trakt_favorites": lambda p: trakt.trakt_favorites(p, addon, _handle, session),
        "trakt_personal_lists": lambda p: trakt.trakt_personal_lists(p, addon, _handle, session),
        "trakt_calendar": lambda p: trakt.trakt_my_calendar(p, addon=addon, handle=_handle, session=session),
        "trakt_in_progress": lambda p: trakt.trakt_in_progress(p, addon=addon, handle=_handle, session=session),
        "trakt_anticipated": lambda p: trakt.trakt_anticipated(p, addon=addon, handle=_handle, session=session),
        "trakt_boxoffice": lambda p: trakt.trakt_boxoffice(p, addon=addon, handle=_handle, session=session),
        "trakt_list_items": lambda p: trakt.trakt_list_items(p, addon, _handle, session),
        "trakt_social_feed": build_social_feed_menu,
        "trakt_add_to_watchlist_tmdb": lambda p: trakt.trakt_add_to_watchlist({'media_type': p.get("media_type"), 'media_id': trakt.get_trakt_id(p.get("tmdb_id"), "show" if p.get("media_type") == "show" else "movie", session, addon)}, addon=addon, handle=_handle, session=session),
        "build_user_feed_menu": build_user_feed_menu,
        "trakt_add_to_favorites": lambda p: trakt.trakt_add_to_favorites(p, addon=addon, handle=_handle, session=session),
        "play_trailer": play_trailer,
        "trakt_user_history": lambda p: trakt.trakt_user_history(p, addon, _handle, session),
        "trakt_watchlist": lambda p: trakt.trakt_watchlist(p, addon=addon, handle=_handle, session=session),
        "trakt_list_seasons": lambda p: trakt.list_seasons(p, addon=addon, handle=_handle, session=session),
        "trakt_list_episodes": lambda p: trakt.list_episodes(p, addon=addon, handle=_handle, session=session),
        "trakt_add_to_watchlist": lambda p: trakt.trakt_add_to_watchlist(p, addon=addon, handle=_handle, session=session),
        "trakt_popular_lists": lambda p: trakt.trakt_popular_lists(p, addon=addon, handle=_handle, session=session),
        "trakt_recommended": lambda p: trakt.trakt_recommended(p, addon=addon, handle=_handle, session=session),
        "trakt_trending": lambda p: trakt.trakt_trending(p, addon=addon, handle=_handle, session=session),
        "trakt_genres": lambda p: trakt.trakt_genres(p, addon=addon, handle=_handle, session=session),
        "trakt_next_episodes_menu": lambda p: trakt_next_menu(p),
        "listing_search": lambda p: actions.search(p.get("name"), plugin_instance),
        "search_gemini": lambda p: __import__('resources.lib.gemini', fromlist=['']).search_gemini(plugin_instance),
        "ai_daily_mix": lambda p: __import__('resources.lib.gemini', fromlist=['']).ai_daily_mix(plugin_instance, is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "ai_daily_generate": lambda p: __import__('resources.lib.gemini', fromlist=['']).generate_daily_mix(plugin_instance, p),
        "ai_daily_refresh": lambda p: __import__('resources.lib.gemini', fromlist=['']).refresh_daily_mix(plugin_instance),
        "ai_recommend_for_me": lambda p: __import__('resources.lib.gemini', fromlist=['']).ai_recommend_for_me(plugin_instance, is_widget=(p.get('is_widget', 'false') == 'true'), force_refresh=(p.get('force_refresh') == 'true')),
        "ai_mood_matcher": lambda p: __import__('resources.lib.gemini', fromlist=['']).ai_mood_matcher(plugin_instance),
        "ai_similar": lambda p: __import__('resources.lib.gemini', fromlist=['']).ai_similar(plugin_instance, p, is_widget=(p.get('is_widget', 'false') == 'true')),
        "gemini_trivia": lambda p: __import__('resources.lib.gemini', fromlist=['']).gemini_trivia(plugin_instance, p),
        "show_help": lambda p: show_help(),
        "show_account_help": lambda p: show_account_help(),
        "show_telegram_help": lambda p: show_telegram_help(),
        "show_filter_help": lambda p: show_filter_help(),
        "show_command_help": lambda p: show_command_help(),
        "apply_settings_and_refresh": lambda p: _apply_settings_and_refresh(),
        "find_meta_and_resolve": lambda p: actions.find_meta_and_resolve(p, plugin_instance),
        "refresh_search": lambda p: cache_manager.safe_refresh(),
        "play_from_library": lambda p: _play_from_library(p),
        "listing_history": lambda p: listing_history(),
        "delete_search_history_item": delete_search_history_item,
        "clear_search_history": lambda p: clear_search_history(),
        "playback_show_history": lambda p: actions.playback_show_history(p, plugin_instance),
        "search_tmdb_from_history": lambda p: actions.search_tmdb_from_history(p, plugin_instance),
        "remove_playback_item": lambda p: actions.remove_playback_item(p, plugin_instance),
        "listing_movie_category": lambda p: movie_category(),
        "bonus_menu": lambda p: bonus_menu(),
        "listing_serie_category": lambda p: serie_category(),
        "library": lambda p: _handle_library_add(p),
        "library_remove": lambda p: _handle_library_remove(p),
        "download": lambda p: _handle_download(p),
        "search_title": lambda p: _handle_search_title(p),
        "open_settings": lambda p: xbmc.executebuiltin("Addon.OpenSettings(plugin.video.play_er)"),
        "tmdbhelper_setup": lambda p: run_tmdbhelper_setup(p.get("task"), addon),
        "diagnose_speed": lambda p: _run_speedtest(p),
        "series_menu": lambda p: create_series_menu(plugin_instance),
        "series_search": lambda p: actions.search_series(p, plugin_instance),
        "series_refresh": lambda p: plugin_instance.series_manager.search_series(p.get("series_name"), plugin_instance.provider_manager.get_providers_to_search()),
        "series_detail": lambda p: create_seasons_menu(p.get("series_name"), plugin_instance),
        "select_episode_stream": lambda p: actions.select_episode_stream(p, plugin_instance),
        "series_season": lambda p: create_episodes_menu(p.get("series_name"), p.get("season"), plugin_instance),
        "series_episodes": lambda p: create_episodes_menu(p.get("series_name"), p.get("season"), plugin_instance),
        "series_delete": lambda p: actions.delete_series(p, plugin_instance),
        "season_delete": lambda p: actions.delete_season(p, plugin_instance),
        "episode_delete": lambda p: actions.delete_episode(p, plugin_instance),
        "episode_mark_watched": lambda p: actions.mark_episode_watched(p, plugin_instance),
        "episode_mark_unwatched": lambda p: actions.mark_episode_unwatched(p, plugin_instance),
        "shell_launcher_menu": lambda p: _open_shell_menu(),
        "register_play_mail": lambda p: register_play_mail_account(),
        "list_new_episodes_content": lambda p: list_new_episodes_content(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_watch_later": lambda p: _display_watch_later_list(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_recommendations_from_history": lambda p: list_recommendations_from_history(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_recommendations_from_history_series": lambda p: list_recommendations_from_history_series(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_recommendations_from_watch_later": lambda p: list_recommendations_from_watch_later(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_recommendations_from_watch_later_series": lambda p: list_recommendations_from_watch_later_series(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "continue_trigger_main": lambda p: list_continue_watching_series(is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "playback_history": lambda p: actions.playback_history(plugin_instance, is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "most_watched": lambda p: actions.most_watched(plugin_instance, is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "prehrajto_history": lambda p: actions.prehrajto_history(plugin_instance, is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "sharing_history": lambda p: actions.display_community_shares(p, plugin_instance, is_widget=xbmc.getCondVisibility("Window.IsVisible(home)")),
        "list_recommendations_from_history_quick_play": lambda p: list_recommendations_from_history_quick_play(),
        "list_recommendations_from_history_series_quick_play": lambda p: list_recommendations_from_history_series_quick_play(),
        "list_recommendations_from_watch_later_quick_play": lambda p: list_recommendations_from_watch_later_quick_play(),
        "list_recommendations_from_watch_later_series_quick_play": lambda p: list_recommendations_from_watch_later_series_quick_play(),
        "stremio_dabing_menu": lambda p: actions.stremio_submenu({"menu_type": "dabing"}, plugin_instance),
        "stremio_charts_menu": lambda p: actions.stremio_submenu({"menu_type": "charts"}, plugin_instance),
        "stremio_csfd_menu": lambda p: actions.stremio_submenu({"menu_type": "csfd_vod"}, plugin_instance),
        "stremio_imdb_menu": lambda p: actions.stremio_submenu({"menu_type": "imdb"}, plugin_instance),
        "stremio_studios_menu": lambda p: actions.stremio_submenu({"menu_type": "studios"}, plugin_instance),
        "stremio_vod_menu": lambda p: actions.stremio_submenu({"menu_type": "vod"}, plugin_instance),
        "stremio_search_menu": lambda p: actions.stremio_submenu({"menu_type": "search"}, plugin_instance),
        "stremio_search_action": lambda p: actions.stremio_search_action(p, plugin_instance),
        "stremio_genres_menu": lambda p: actions.list_stremio_genres(p, plugin_instance),
        "list_stremio_catalogs": lambda p: actions.list_stremio_catalogs(p, plugin_instance),
        "stremio_items": lambda p: actions.list_stremio_items(p, plugin_instance),
        "select_provider": lambda p: _handle_select_provider(),
        "prehrajto_suggest": lambda p: actions.prehrajto_suggest(p, plugin_instance),
        "clear_csfd_cache": lambda p: clear_csfd_cache(),
        "reset_database": lambda p: cache_manager.reset_database(),
        "menu_refresh": lambda p: menu(),
        "play_context_item": lambda p: actions.play_context_item(p, plugin_instance),
        "pre_emptive_search": lambda p: actions.pre_emptive_search(p, plugin_instance),
        "refill_episode_queue": lambda p: generator.queue_following_episodes_from_tmdbh(
            get_meta_from_cache(p.get("meta", "")), addon, plugin_instance, seed_only=False
        ),
        "play_random": _handle_play_random,
        "random_trigger_main": random_trigger_main,
        "continue_watching_main": _handle_continue_watching,
        "continue_quick_play_action": continue_quick_play_action,
        "share_menu": lambda p: actions.handle_share_menu(p, plugin_instance),
        "remove_community_share": lambda p: actions.remove_community_share(p, plugin_instance),
        "change_stream_quality": lambda p: actions.change_stream_quality(p, plugin_instance),
        "show_stream_menu": lambda p: __import__('resources.lib.dialog_stream', fromlist=['']).show_stream_menu(plugin_instance),
    }


actions_map = _create_actions_map()


# FIX PRE-EMPTIVE AND FILTERS [PLAYBACK INVOKER LIFETIME]
def _is_playback_action(params):
    action = params.get('action')
    if action == 'tmdbh_bridge':
        return params.get('mode', 'play') in ('play', 'smart_play')
    return action in (
        'play', 'create_movie_playlist_action', 'create_series_playlist_action',
        'continue_quick_play_action', 'continue_watching_main',
        'random_trigger_main', 'play_random', 'find_meta_and_resolve',
        'play_context_item', 'play_from_library',
        'list_recommendations_from_history_quick_play',
        'list_recommendations_from_history_series_quick_play',
        'list_recommendations_from_watch_later_quick_play',
        'list_recommendations_from_watch_later_series_quick_play',
    )


def _wait_for_playback_monitor(player):
    """Pump Kodi callbacks through startup and short gaps between playlist items."""
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + 60.0
    try:
        while player.owns_playback() and not monitor.abortRequested():
            if player.isPlayingVideo():
                deadline = time.monotonic() + 30.0
            elif time.monotonic() >= deadline:
                break
            if monitor.waitForAbort(0.25):
                break
    finally:
        player.release_playback()


def shutdown_runtime():
    """Release Kodi callback objects before the plugin interpreter exits."""
    global GLOBAL_TRAKT_MONITOR, settings_monitor

    player_monitor = GLOBAL_TRAKT_MONITOR or getattr(trakt, "_GLOBAL_PLAYER_MONITOR", None)
    try:
        if player_monitor:
            player_monitor.release_playback()
    except Exception as e:
        log(f"RUNTIME SHUTDOWN - Player monitor release failed: {e}", xbmc.LOGWARNING)
    finally:
        GLOBAL_TRAKT_MONITOR = None
        settings_monitor = None
        trakt._GLOBAL_PLAYER_MONITOR = None


def router(paramstring):
    global _handle, plugin_instance, tmdb_client, provider_manager, GLOBAL_TRAKT_MONITOR, settings_monitor, _notification_check_done

    _handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1

    if not addon.getSettingBool("security_bypass"):
        allowed, ip_banned, public_ip = check_run_file()
        if ip_banned:
            xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]| SERVER SAY : IP BANNED |[/COLOR][/B]", f"IP: {public_ip}")
            sys.exit()
        if not allowed:
            xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]| SERVER SAY : DISABLED |[/COLOR][/B]", "Deactivated by developer")
            sys.exit()

    if 'provider_manager' not in globals() or provider_manager is None:
        reinitialize_clients()
    else:
        # Dynamická aktualizace handle pro bezproblémový běh reuselanguageinvoker
        if tmdb_client:
            tmdb_client._handle = _handle
        if provider_manager:
            provider_manager.handle = _handle

    plugin_instance = Plugin(addon, _handle, session, provider_manager, series_manager, tmdb_client, csfd_instance)

    # Inicializace / propojení trvalého singletonu monitoru přehrávače
    def mark_watched_callback(meta):
        if addon.getSettingBool("menu_hide_series_menu") and meta.get("media_type") == "episode":
            s_name = meta.get("tv_show_title")
            sea = meta.get("season")
            epi = meta.get("episode")
            if s_name and sea and epi:
                plugin_instance.series_manager.mark_episode_watched(s_name, sea, epi)
        if meta.get("media_type") == "episode":
            _remove_episode_from_new_list(meta)

    # FIX PRE-EMPTIVE AND FILTERS [ONE MONITOR FOR PLAYBACK, NONE FOR REFILL]
    # Previously every menu/search/refill invocation registered another Player.
    # GLOBAL_TRAKT_MONITOR = trakt.get_player_monitor(...)
    params = dict(parse_qsl(paramstring))
    from resources.lib.view_modes import begin_directory, finish_directory
    directory_url = sys.argv[0].split('?', 1)[0] + ('?' + paramstring if paramstring else '')
    begin_directory(directory_url, params)
    # A guarded automatic handoff must attach before claiming playback. Manual
    # Continue and existing external calls without a token keep their behavior.
    guard = None
    if (params.get('action') == 'continue_watching_main'
            and params.get('automatic') == 'true' and params.get('handoff_token')):
        from resources.lib.continue_handoff import ContinueHandoffGuard
        guard = ContinueHandoffGuard(params['handoff_token'])
        guard.bind_owner(params.get('handoff_owner'))
        try:
            acknowledged = guard.acknowledge()
        except Exception:
            guard.clear()
            raise
        if not acknowledged:
            guard.clear()
            return
        params['_continue_guard'] = guard
    try:
        playback_action = _is_playback_action(params)
        if playback_action:
            GLOBAL_TRAKT_MONITOR = trakt.get_player_monitor(
                session=session,
                addon=addon,
                tmdb_client=plugin_instance.tmdb_client,
                save_playback_history_func=save_playback_history,
                remove_from_watch_later_func=_monitor_remove_watch_later,
                mark_watched_func=mark_watched_callback
            )
            if guard and not guard.valid():
                return
            if not guard:
                GLOBAL_TRAKT_MONITOR.claim_playback()

        if "settings_monitor" not in globals() or globals()["settings_monitor"] is None:
            settings_monitor = SettingsMonitor()

        if not paramstring and not _notification_check_done:
            def _run_background_notifications():
                if not addon.getSettingBool("disable_episode_notify"):
                    try:
                        check_new_episodes_notifications()
                    except Exception as e:
                        log(f"BACKGROUND TASK [TMDB NOTIFY] : {e}", xbmc.LOGWARNING)

                if not addon.getSettingBool("disable_notify_info"):
                    try:
                        check_new_episodes()
                    except Exception as e:
                        log(f"BACKGROUND TASK [TRAKT NOTIFY] : {e}", xbmc.LOGWARNING)

            threading.Thread(target=_run_background_notifications, daemon=True).start()
            _notification_check_done = True

        action = params.get("action")

        if action in actions_map:
            try:
                actions_map[action](params)
            except Exception as e:
                log(f"ROUTER ERROR - ACTION '{action}' FAILED : {e}", xbmc.LOGERROR)
                traceback.print_exc()
        elif not action or action == "None":
            menu()
        else:
            log(f"ROUTER ERROR - UNKNOWN ACTION : {action}", xbmc.LOGWARNING)

    finally:
        if guard:
            # The sender removes the acknowledgement after observing it.
            guard.clear_token()

    # Directory handlers have completed endOfDirectory before requesting a view.
    finish_directory()

    # FIX PRE-EMPTIVE AND FILTERS [KEEP CONTINUE CALLBACKS ALIVE]
    # Original loop omitted continue_watching_main and exited at the first gap:
    # playback_actions = ('play', 'create_movie_playlist_action',
    #     'create_series_playlist_action', 'continue_quick_play_action',
    #     'random_trigger_main', 'find_meta_and_resolve')
    # if action in playback_actions:
    #     monitor = xbmc.Monitor()
    #     player = xbmc.Player()
    #     for _ in range(12):
    #         if player.isPlayingVideo() or monitor.abortRequested(): break
    #         xbmc.sleep(250)
    #     while player.isPlayingVideo() and not monitor.abortRequested():
    #         if monitor.waitForAbort(1): break
    if playback_action:
        if guard and not guard.started:
            GLOBAL_TRAKT_MONITOR.release_playback()
        else:
            _wait_for_playback_monitor(GLOBAL_TRAKT_MONITOR)


if __name__ == '__main__':
    try:
        router(sys.argv[2][1:] if len(sys.argv) > 2 else "")
    finally:
        # Čisté uvolnění bez destrukce monitoru
        try:
            gc.collect()
        except Exception:
            pass
