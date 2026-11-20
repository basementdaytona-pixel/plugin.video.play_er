# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: trakt.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 17.10.2026 (Fix: Trakt API OAuth, JSON payload, On-the-fly ID fallback, Kodi 22 Scrobble Guard)
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import os
import re
import hashlib
import time
import json
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from urllib.parse import parse_qsl, urlparse, quote

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin
import xbmcvfs

from resources.lib.monitor_orchestrator import get_orchestrator
from resources.lib.utils_logging import log
from resources.lib.stream_state import get_streams, attach_subtitles, publish_active_streams
from resources.lib.playback_identity import EXPECTED_OWNER, EXPECTED_URL, expect_stream, stream_key
from resources.lib import cache_manager
from resources.lib.utils_files import SafeVFSFile
from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)
from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_int,
    get_setting_str
)
from resources.lib.utils_theme import (
    Colors,
    Icons
)
from resources.lib.utils import (
    add_next_page_item,
    safe_post,
    safe_get,
    get_url
)

TRAKT_OAUTH_URL = "https://api.trakt.tv/oauth/"
TRAKT_AUTHORIZE_URL = TRAKT_OAUTH_URL + "authorize"
TRAKT_TOKEN_URL = TRAKT_OAUTH_URL + "token"
TRAKT_DEVICE_CODE_URL = TRAKT_OAUTH_URL + "device/code"
TRAKT_DEVICE_TOKEN_URL = TRAKT_OAUTH_URL + "device/token"

_addon = xbmcaddon.Addon(id="plugin.video.play_er")
_session = requests.Session()
_handle = None

TRAKT_LOCK = threading.Lock()

# SCROBBLING & MONITOR SETUP
TRAKT_SCROBBLE_URL = "https://api.trakt.tv/scrobble/"
TRAKT_SCROBBLE_TIMEOUT = 10
TRAKT_SCROBBLE_MAX_RETRIES = 2
TRAKT_SCROBBLE_RATE_LIMIT_WAIT = 1
TRAKT_TOKEN_REFRESH_TIMEOUT = 15

_GLOBAL_PLAYER_MONITOR = None


def _trakt_set_globals(addon=None, session=None, handle=None):
    global _addon, _session, _handle
    with TRAKT_LOCK:
        if addon is not None:
            _addon = addon
        if session is not None:
            _session = session
        elif _session is None:
            _session = requests.Session()
        if handle is not None:
            _handle = handle


def save_trakt_cache(cache_name, data, section="TRAKT"):
    cache_manager.cache_set(section, cache_name, data)


def load_trakt_cache(cache_name, ttl_hours=None, section="TRAKT"):
    return cache_manager.cache_get(section, cache_name)


def _personal_list_cache_key(addon, section, key):
    """Keep cached pages specific to an account and Kodi session."""
    token = addon.getSetting("trakt_access_token").strip() or _get_trakt_access_token()
    if not token:
        return None
    identity = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{key}_{identity}_{cache_manager.personal_cache_epoch(section)}"


def _invalidate_personal_list(section):
    # Leave the public Trakt catalogue and persistent user data intact.
    cache_manager.cache_clear(section, notify_success=False)


def _get_trakt_access_token():
    try:
        token = _addon.getSetting("trakt_access_token").strip()
        if token:
            return token
    except Exception:
        pass
    try:
        cached = cache_manager.user_data_get("trakt_access_token")
        if cached:
            return str(cached).strip()
    except Exception:
        pass
    return ""


def _get_trakt_refresh_token():
    try:
        token = _addon.getSetting("trakt_refresh_token").strip()
        if token:
            return token
    except Exception:
        pass
    try:
        cached = cache_manager.user_data_get("trakt_refresh_token")
        if cached:
            return str(cached).strip()
    except Exception:
        pass
    return ""


def _tmdb_show_art(tmdb_client, tmdb_id):
    if not tmdb_id:
        return {}
    try:
        details = tmdb_client.get_full_details("tv", tmdb_id)
        if not details:
            return {}
        poster = details.get("poster_path")
        backdrop = details.get("backdrop_path")
        return {
            "poster": f"{tmdb_client.image_base_url}w500{poster}" if poster else "",
            "fanart": f"{tmdb_client.image_base_url}original{backdrop}" if backdrop else "",
            "thumb": f"{tmdb_client.image_base_url}w500{poster}" if poster else "",
        }
    except Exception as exc:
        log(f"TRAKT ART - TMDB show {tmdb_id}: {exc}", xbmc.LOGWARNING)
        return {}


def process_and_add_item(handle, addon, tmdb_client, media, media_type, tmdb_id, extra_context=None, label_suffix=None, ensure_art=False):
    use_tmdb = addon.getSettingBool('trakt_prefer_czech_search') and tmdb_id
    tmdb_checked = bool(use_tmdb)
    props = {}

    if use_tmdb:
        t_type = "tv" if media_type == "show" else "movie"
        details = tmdb_client.get_full_details(t_type, tmdb_id, lang='cs-CZ')

        if not details:
            t_type_alt = "movie" if t_type == "tv" else "tv"
            details = tmdb_client.get_full_details(t_type_alt, tmdb_id, lang='cs-CZ')
            if details:
                media_type = "show" if t_type_alt == "tv" else "movie"

        if details:
            props = tmdb_client._build_metadata_props(details, "tv" if media_type == "show" else "movie")
        else:
            use_tmdb = False

    if not props:
        props = {
            "tmdb_id": tmdb_id,
            "media_type": "tv" if media_type == "show" else "movie",
            "title": media.get("title", "Neznámý"),
            "original_title": media.get("title"),
            "year": str(media.get("year", "")),
            "plot": media.get("overview", ""),
            "rating": f"{media.get('rating', 0):.1f}" if media.get('rating') else "",
            "votes": str(media.get('votes', "")),
        }

        if isinstance(media.get("images"), dict):
            imgs = media["images"]
            if imgs.get("poster") and isinstance(imgs["poster"], list) and imgs["poster"]:
                props["poster"] = imgs["poster"][0]
            if imgs.get("fanart") and isinstance(imgs["fanart"], list) and imgs["fanart"]:
                props["fanart"] = imgs["fanart"][0]

        for k in ["poster", "fanart"]:
            val = props.get(k)
            if val and isinstance(val, str) and not val.startswith("http"):
                props[k] = "https://" + val

    if ensure_art and not use_tmdb:
        props["poster"] = ""
        props["fanart"] = ""
    if ensure_art and tmdb_id and not use_tmdb and not tmdb_checked:
        try:
            details = tmdb_client.get_full_details("tv" if media_type == "show" else "movie", tmdb_id)
            if details:
                poster = details.get("poster_path")
                backdrop = details.get("backdrop_path")
                if poster:
                    props["poster"] = f"{tmdb_client.image_base_url}w500{poster}"
                    props["thumb"] = props["poster"]
                if backdrop:
                    props["fanart"] = f"{tmdb_client.image_base_url}original{backdrop}"
        except Exception as exc:
            log(f"TRAKT ART - TMDB {media_type} {tmdb_id}: {exc}", xbmc.LOGWARNING)

    title = props.get('title')
    year = props.get('year')
    label = f"{title} ({year})" if year else title
    if label_suffix:
        label += label_suffix

    li = xbmcgui.ListItem(label=label)
    fill_type = "movie" if media_type == "movie" else "tvshow"
    tmdb_client.fill_list_item(li, props, fill_type)
    if ensure_art and not props.get("poster"):
        li.setArt({"icon": Icons.MOVIE if media_type == "movie" else Icons.TVSHOW})

    context = []
    m_type_str = "movie" if media_type == "movie" else "show"
    trakt_id = media.get("ids", {}).get("trakt")

    should_add_trakt_watch = True
    if extra_context:
        try:
            for ex in extra_context:
                if isinstance(ex, (list, tuple)) and len(ex) > 1 and isinstance(ex[1], str):
                    if 'trakt_watchlist' in ex[1] and ('remove=' in ex[1] or 'remove' in ex[1]):
                        should_add_trakt_watch = False
                        break
        except Exception:
            pass

    if extra_context:
        context.extend(extra_context)
    elif should_add_trakt_watch:
        context.append((f"[COLOR {Colors.ORANGE}]► PŘIDAT TRAKTLIST[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist', media_type=m_type_str, media_id=trakt_id)})"))

    if media.get("trailer"):
        tr = media["trailer"]
        if "youtube" in tr or "youtu.be" in tr:
            try:
                vid = tr.split("v=")[-1].split("&")[0] if "v=" in tr else tr.split("/")[-1]
                url = f"plugin://plugin.video.tube_er/?action=play&videoId={vid}"
                context.append((f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILER[/COLOR]", f"PlayMedia({url})"))
            except Exception:
                pass

    context.append((f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL[/COLOR]", f"RunPlugin({get_url(action='search_title', name=title)})"))

    try:
        media_type_param = "movie" if media_type == "movie" else "tv"
        player_menu_params = {
            'action': 'show_player_menu',
            'tmdb_id': tmdb_id or "",
            'media_type': media_type_param,
            'title': title,
            'context': 'trakt',
            'props': json.dumps({}),
        }
        context.append((f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(**player_menu_params)})"))
    except Exception:
        pass

    context.append((f"[COLOR {Colors.LIMEGREEN}][ MENU NASTAVENÍ ][/COLOR]", "Addon.OpenSettings(plugin.video.play_er)"))
    li.addContextMenuItems(_sf_cm_items(context))

    action_props = props if use_tmdb else {
        "tmdb_id": tmdb_id,
        "title": title,
        "year": year,
        "plot": props.get('plot'),
        "media_type": "tv" if media_type == "show" else "movie",
        "poster": props.get("poster"),
        "fanart": props.get("fanart")
    }

    from resources.lib.utils import store_meta_in_cache
    meta_key = store_meta_in_cache(action_props)

    if media_type == "movie":
        url = get_url(action="find_sources", meta=meta_key)
    else:
        url = get_url(action="listing_tmdb_tv", tmdb_id=tmdb_id, meta=meta_key)

    xbmcplugin.addDirectoryItem(handle, url, li, True)


def trakt_refresh_token(addon, session=None):
    _trakt_set_globals(addon=addon, session=session)
    trakt_client_id = _addon.getSetting("trakt_client_id").strip()
    trakt_client_secret = _addon.getSetting("trakt_client_secret").strip()
    trakt_refresh_token_str = _get_trakt_refresh_token()

    if not all([trakt_client_id, trakt_client_secret, trakt_refresh_token_str]):
        log("TRAKT REFRESH - Chybí přihlašovací údaje nebo refresh_token", xbmc.LOGWARNING)
        return False

    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": trakt_client_id
    }
    payload = {
        "client_id": trakt_client_id,
        "client_secret": trakt_client_secret,
        "refresh_token": trakt_refresh_token_str,
        "grant_type": "refresh_token",
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    }

    try:
        response = safe_post(_session, TRAKT_TOKEN_URL, headers=headers, json=payload, timeout=TRAKT_TOKEN_REFRESH_TIMEOUT)
        if response is None or response.status_code != 200:
            log(f"TRAKT REFRESH - Obnova selhala (Status {getattr(response, 'status_code', 'None')})", xbmc.LOGWARNING)
            return False

        token_data = response.json()
        new_access_token = token_data.get("access_token", "")
        new_refresh_token = token_data.get("refresh_token", "")

        if new_access_token and new_refresh_token:
            _addon.setSetting("trakt_access_token", new_access_token)
            _addon.setSetting("trakt_refresh_token", new_refresh_token)

            try:
                cache_manager.user_data_set("trakt_access_token", new_access_token)
                cache_manager.user_data_set("trakt_refresh_token", new_refresh_token)
            except Exception:
                pass

            log("TRAKT REFRESH - Token úspěšně obnoven", xbmc.LOGINFO)
            return True
        return False
    except Exception as e:
        log(f"TRAKT REFRESH - Výjimka při obnově tokenu: {str(e)}", xbmc.LOGERROR)
        return False


def trakt_authenticate(addon, session=None):
    _trakt_set_globals(addon=addon, session=session)
    fresh_addon = xbmcaddon.Addon(id="plugin.video.play_er")
    trakt_client_id = fresh_addon.getSetting("trakt_client_id").strip()
    trakt_client_secret = fresh_addon.getSetting("trakt_client_secret").strip()

    if not trakt_client_id or not trakt_client_secret:
        notify_error("CONFIG Vyplňte osobní CLIENT ID a SECRET v nastavení!", category="TRAKT", sound=True)
        fresh_addon.openSettings()
        return False

    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": trakt_client_id
    }
    data_code = {"client_id": trakt_client_id}

    try:
        response = safe_post(_session, TRAKT_DEVICE_CODE_URL, headers=headers, json=data_code, timeout=30)
        if response is None:
            notify_error("AUTH Trakt API neodpovědělo. Zkontrolujte připojení.", category="TRAKT")
            return False

        if response.status_code == 401:
            notify_error("AUTH API Klíč je neplatný! Zkontrolujte zadané Client ID.", category="TRAKT", time=6000)
            return False

        response.raise_for_status()
        device_data = response.json()

        dialog = xbmcgui.Dialog()
        auth_url = f"https://trakt.tv/activate?code={device_data['user_code']}"

        dialog.textviewer(
            "| TRAKT.TV CONNECT : OVĚŘENÍ ÚČTU |",
            f"\n"
            f" 1. OTEVŘETE URL VE WEBOVÉM PROHLÍŽEČI (MOBIL/PC) :\n"
            f"    [B][COLOR orange]{auth_url}[/COLOR][/B]\n\n"
            f" 2. NEBO JDĚTE NA  :  [B]{device_data['verification_url']}[/B]\n"
            f"    A ZADEJTE KÓD  :  [B][COLOR orange]{device_data['user_code']}[/COLOR][/B]\n\n"
            f"========================================\n"
            f" [B][ TENTO KÓD JE PLATNÝ {device_data['expires_in']//60} MINUT ][/B]\n"
            f" [B][COLOR {Colors.ORANGE}][ PO OVĚŘENÍ STISKNĚTE ESC/ZPĚT ][/COLOR][/B]\n"
            f"========================================\n",
        )

        data_token = {
            "client_id": trakt_client_id,
            "client_secret": trakt_client_secret,
            "code": device_data["device_code"],
        }

        interval = device_data.get("interval", 5)
        expires_in = device_data.get("expires_in", 600)
        start_time = time.time()

        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}]○ TRAKT.TV OVĚŘENÍ ○[/COLOR][/B]", "Čekání na uživatelské ověření ...")

        while (time.time() - start_time) < expires_in:
            if progress.iscanceled():
                break
            progress.update(int(((time.time() - start_time) / expires_in) * 100))
            try:
                response = safe_post(_session, TRAKT_DEVICE_TOKEN_URL, headers=headers, json=data_token, timeout=30)
                if response is None:
                    xbmc.sleep(interval * 1000)
                    continue

                if response.status_code == 200:
                    token_data = response.json()
                    fresh_addon.setSetting("trakt_access_token", token_data["access_token"])
                    fresh_addon.setSetting("trakt_refresh_token", token_data["refresh_token"])
                    try:
                        cache_manager.user_data_set("trakt_access_token", token_data["access_token"])
                        cache_manager.user_data_set("trakt_refresh_token", token_data["refresh_token"])
                    except Exception:
                        pass
                    progress.close()
                    notify_ok("AUTH Úspěšně připojeno k TRAKT.TV", category="TRAKT", time=5000)
                    return True
                elif response.status_code in (400, 404):
                    xbmc.sleep(interval * 1000)
                else:
                    break
            except Exception as e:
                log(f"TRAKT - Authentication loop error: {str(e)}", xbmc.LOGERROR)
                break
        progress.close()
        notify_error("TIMEOUT Čas na ověření vypršel nebo došlo k chybě", category="TRAKT")
    except Exception as e:
        log(f"TRAKT - Authentication failed: {str(e)}", xbmc.LOGERROR)
        notify_error("ERROR Chyba při připojování ke TRAKT.TV", category="TRAKT")
    return False


def trakt_get_headers(addon=None, write=False):
    target_addon = addon or _addon
    _trakt_set_globals(addon=target_addon)
    headers = {
        "Content-Type": "application/json",
        "trakt-api-version": "2",
        "trakt-api-key": get_setting_str(target_addon, "trakt_client_id", ""),
        "Accept-Language": get_setting_str(target_addon, "trakt_language", "cs") or "cs",
    }

    access_token = ""
    if write:
        access_token = _get_trakt_access_token()
        if not access_token and "_session" in globals() and _session is not None:
            try:
                win = xbmcgui.Window(10000)
                if win.getProperty("play_er.trakt_refreshing") != "true":
                    win.setProperty("play_er.trakt_refreshing", "true")
                    trakt_refresh_token(addon=target_addon, session=_session)
                    win.clearProperty("play_er.trakt_refreshing")
                access_token = _get_trakt_access_token()
            except Exception as e:
                log(f"TRAKT HEADERS - Refresh error: {e}", xbmc.LOGWARNING)

    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    return headers


def handle_trakt_401(url, addon, session=None, method="GET", data=None):
    _trakt_set_globals(addon=addon, session=session)
    win = xbmcgui.Window(10000)

    while win.getProperty("play_er.trakt_refreshing") == "true":
        xbmc.sleep(250)

    headers = trakt_get_headers(addon=_addon, write=True)
    try:
        response = _session.request(method, url, headers=headers, json=data, timeout=15)
    except requests.exceptions.RequestException as e:
        log(f"TRAKT - Connection Error: {e}", xbmc.LOGERROR)
        return None

    if response is not None and response.status_code == 429:
        try:
            retry_after = int(response.headers.get("Retry-After", 1))
        except Exception:
            retry_after = 1
        xbmc.sleep(retry_after * 1000)
        try:
            response = _session.request(method, url, headers=headers, json=data, timeout=15)
        except requests.exceptions.RequestException:
            return None

    if response is not None and response.status_code == 401:
        log("TRAKT - 401 Unauthorized, zkouším refresh tokenu...", xbmc.LOGINFO)
        win.setProperty("play_er.trakt_refreshing", "true")
        refresh_success = trakt_refresh_token(addon=_addon, session=_session)
        win.clearProperty("play_er.trakt_refreshing")

        if refresh_success:
            headers = trakt_get_headers(addon=_addon, write=True)
            response = _session.request(method, url, headers=headers, json=data, timeout=15)
            if response and response.status_code == 401:
                notify_error("AUTH API klíče nebo token jsou neplatné, reautorizujte", category="TRAKT")
                return None
        else:
            notify_error("AUTH Obnova tokenu selhala, zkontrolujte přihlášení Trakt", category="TRAKT")
            return None

    return response


def get_tmdb_id(trakt_id, media_type):
    cache_key = f"trakt_to_tmdb_{media_type}_{trakt_id}"
    cached_id = load_trakt_cache(cache_key)
    if cached_id is not None:
        return cached_id

    url = f"https://api.trakt.tv/{media_type}s/{trakt_id}"
    try:
        response = safe_get(_session, url, headers=trakt_get_headers(addon=_addon), timeout=10)
        if response is not None and response.status_code == 200:
            data = response.json()
            tmdb_id = data.get("ids", {}).get("tmdb")
            if tmdb_id:
                save_trakt_cache(cache_key, tmdb_id)
                return tmdb_id
    except Exception:
        pass
    return None


def get_trakt_id(tmdb_id, media_type, session, addon):
    cache_key = f"tmdb_to_trakt_id_{media_type}_{tmdb_id}"
    cached_id = load_trakt_cache(cache_key)
    if cached_id is not None:
        return cached_id

    url = f"https://api.trakt.tv/search/tmdb/{tmdb_id}?type={media_type}"
    try:
        response = safe_get(session, url, headers=trakt_get_headers(addon=addon), timeout=10)
        if response is not None and response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                target_block = data[0].get(media_type, {})
                trakt_id = target_block.get("ids", {}).get("trakt")
                if trakt_id:
                    save_trakt_cache(cache_key, trakt_id)
                    return trakt_id
    except Exception as e:
        log(f"TRAKT get_trakt_id error: {e}", xbmc.LOGWARNING)
    return None


def get_trakt_episode_id(show_tmdb_id, season_num, episode_num, session, addon):
    if not all([show_tmdb_id, season_num is not None, episode_num is not None]):
        return None

    cache_key = f"trakt_episode_id_{show_tmdb_id}_{season_num}_{episode_num}"
    cached_id = load_trakt_cache(cache_key)
    if cached_id:
        return cached_id

    show_trakt_id = get_trakt_id(show_tmdb_id, "show", session, addon)
    if not show_trakt_id:
        return None

    episode_url = f"https://api.trakt.tv/shows/{show_trakt_id}/seasons/{season_num}/episodes/{episode_num}"
    try:
        response = handle_trakt_401(episode_url, addon=addon, session=session, method="GET")
        if response and response.status_code == 200:
            episode_data = response.json()
            trakt_episode_id = episode_data.get("ids", {}).get("trakt")
            if trakt_episode_id:
                save_trakt_cache(cache_key, trakt_episode_id)
                return trakt_episode_id
    except Exception as e:
        log(f"TRAKT get_trakt_episode_id error: {e}", xbmc.LOGWARNING)
    return None


def trakt_trending(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    xbmcplugin.setPluginCategory(_handle, "Trakt Trending")

    if not addon.getSetting("trakt_client_id").strip():
        notify_error("CONFIG Chybí Client ID v nastavení (Osobní API klíč)", category="TRAKT", sound=True)
        addon.openSettings()
        xbmcplugin.endOfDirectory(handle)
        return

    if "category" not in params:
        for cat, label, icon in [("movies", "FILMY", Icons.MOVIE), ("shows", "SERIÁLY", Icons.TVSHOW)]:
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]TRENDY : {label}")
            li.setArt({"icon": icon})
            xbmcplugin.addDirectoryItem(_handle, get_url(action="trakt_trending", category=cat), li, True)
        xbmcplugin.endOfDirectory(_handle)
        return

    category = params.get("category", "movies")
    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)

    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    lang_suffix = "_cs" if use_czech else ""
    cache_key = f"trakt_trending_{category}_{page}{lang_suffix}_limit_{limit}"

    cached_content = load_trakt_cache(cache_key)
    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items_data, headers = cached_content
    else:
        items_data, headers = None, None

    if not items_data:
        url = f"https://api.trakt.tv/{category}/trending?extended=full,images&page={page}&limit={limit}"
        response = safe_get(_session, url, headers=trakt_get_headers(addon=_addon), timeout=10)
        if not response or response.status_code != 200:
            notify_error("ERROR Chyba při načítání trendů", category="TRAKT")
            return
        items_data = response.json()
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items_data, headers))

    for item in items_data:
        media_type_key = "movie" if category == "movies" else "show"
        if media_type_key not in item:
            continue
        media = item[media_type_key]
        tmdb_id = media.get("ids", {}).get("tmdb")
        process_and_add_item(_handle, _addon, tmdb_client, media, media_type_key, tmdb_id)

    add_next_page_item(_handle, "trakt_trending", headers, page, category=category)
    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(_handle)


def trakt_anticipated(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    category = params.get("category", "movies")
    xbmcplugin.setPluginCategory(_handle, f"OČEKÁVANÉ : {category.capitalize()}")

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)

    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    lang_suffix = "_cs" if use_czech else ""
    cache_key = f"trakt_anticipated_{category}_{page}{lang_suffix}_limit_{limit}"

    cached_content = load_trakt_cache(cache_key)
    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items_data, headers = cached_content
    else:
        items_data, headers = None, None

    if not items_data:
        url = f"https://api.trakt.tv/{category}/anticipated?extended=full,images&page={page}&limit={limit}"
        response = safe_get(_session, url, headers=trakt_get_headers(addon), timeout=10)
        if not response or response.status_code != 200:
            notify_error("ERROR Chyba při načítání - ANTICIPATED", category="TRAKT")
            xbmcplugin.endOfDirectory(_handle)
            return
        items_data = response.json()
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items_data, headers))

    for item in items_data:
        media_type_key = "movie" if category == "movies" else "show"
        if media_type_key not in item:
            continue
        media = item[media_type_key]
        tmdb_id = media.get("ids", {}).get("tmdb")
        list_count = item.get('list_count', 0)
        suffix = f"[I][COLOR {Colors.ORANGE}][ {list_count} sleduje ][/COLOR][/I]" if addon.getSettingBool('trakt_show_info') else ""
        process_and_add_item(_handle, _addon, tmdb_client, media, media_type_key, tmdb_id, label_suffix=suffix)

    add_next_page_item(_handle, "trakt_anticipated", headers, page, category=category)
    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(_handle)


def trakt_boxoffice(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    xbmcplugin.setPluginCategory(_handle, "Trakt Box Office")
    cache_key = "trakt_boxoffice_top10"
    items_data = load_trakt_cache(cache_key)
    if isinstance(items_data, tuple):
        items_data = items_data[0]

    if not items_data:
        url = "https://api.trakt.tv/movies/boxoffice?extended=full,images"
        response = safe_get(_session, url, headers=trakt_get_headers(addon), timeout=10)
        if not response or response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle)
            return
        items_data = response.json()
        save_trakt_cache(cache_key, items_data)

    for item in items_data:
        media = item.get('movie')
        if not media:
            continue
        tmdb_id = media.get("ids", {}).get("tmdb")
        revenue = item.get('revenue', 0)
        suffix = f" [I][COLOR {Colors.LIMEGREEN}][ ${revenue:,.0f} ][/COLOR][/I]"
        process_and_add_item(_handle, _addon, tmdb_client, media, "movie", tmdb_id, label_suffix=suffix)

    xbmcplugin.setContent(_handle, "movies")
    xbmcplugin.endOfDirectory(_handle)


def trakt_popular_lists(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    xbmcplugin.setPluginCategory(handle, "Trakt Popular Lists")
    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)

    if "list_id" not in params:
        use_czech = addon.getSettingBool('trakt_prefer_czech_search')
        lang_suffix = "_cs" if use_czech else ""
        cache_key = f"trakt_popular_lists_{page}{lang_suffix}_limit_{limit}"
        cached_content = load_trakt_cache(cache_key)

        if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
            lists_data, headers = cached_content
        else:
            lists_data, headers = None, None

        if not lists_data:
            url = f"https://api.trakt.tv/lists/popular?extended=full&page={page}&limit={limit}"
            response = safe_get(_session, url, headers=trakt_get_headers(addon=addon), timeout=10)
            if not response or response.status_code != 200:
                return
            lists_data = response.json()
            headers = dict(response.headers)
            save_trakt_cache(cache_key, (lists_data, headers))

        for item in lists_data:
            list_data = item["list"]
            title = list_data.get("name", "Neznámý seznam")
            list_id = list_data["ids"]["trakt"]
            label = f"[UPPERCASE]{title}[/UPPERCASE]"
            if addon.getSettingBool('trakt_show_info'):
                likes = list_data.get("likes", 0)
                item_count = list_data.get("item_count", 0)
                label += f" [I][COLOR {Colors.ORANGE}][ {item_count} položek | {likes} likes ][/COLOR][/I]"

            listitem = xbmcgui.ListItem(label=label)
            listitem.setArt({"icon": Icons.FOLDER})
            video_info = listitem.getVideoInfoTag()
            video_info.setTitle(title)
            video_info.setPlot(list_data.get("description", ""))
            xbmcplugin.addDirectoryItem(handle, get_url(action="trakt_popular_lists", list_id=list_id), listitem, True)

        add_next_page_item(handle, "trakt_popular_lists", headers, page)
        xbmcplugin.endOfDirectory(handle)
        return

    list_id = params["list_id"]
    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    lang_suffix = "_cs" if use_czech else ""
    cache_key = f"trakt_list_items_{list_id}_{page}{lang_suffix}_limit_{limit}"
    cached_content = load_trakt_cache(cache_key)

    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items_data, headers = cached_content
    else:
        items_data, headers = None, None

    if not items_data:
        url = f"https://api.trakt.tv/lists/{list_id}/items?extended=full,images&page={page}&limit={limit}"
        response = safe_get(_session, url, headers=trakt_get_headers(addon=addon), timeout=10)
        if not response or response.status_code != 200:
            return
        items_data = response.json()
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items_data, headers))

    for item in items_data:
        media_type = item.get("type")
        if media_type not in ["movie", "show"]:
            continue
        media = item[media_type]
        tmdb_id = media.get("ids", {}).get("tmdb")
        process_and_add_item(handle, addon, tmdb_client, media, media_type, tmdb_id)

    add_next_page_item(handle, "trakt_popular_lists", headers, page, list_id=list_id)
    xbmcplugin.setContent(handle, "movies")
    xbmcplugin.endOfDirectory(handle)


def trakt_list_items(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    list_id = params.get("list_id")
    if not list_id:
        return

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)
    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    lang_suffix = "_cs" if use_czech else ""
    cache_key = f"trakt_personal_list_items_{list_id}_{page}{lang_suffix}_limit_{limit}"

    cached_content = load_trakt_cache(cache_key)
    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items, headers = cached_content
    else:
        items, headers = None, None

    if not items:
        url = f"https://api.trakt.tv/users/me/lists/{list_id}/items?extended=full,images&page={page}&limit={limit}"
        response = handle_trakt_401(url, addon=_addon, session=_session)
        if not response or response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle)
            return
        items = response.json()
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items, headers))

    for item in items:
        media_type = item.get("type")
        if media_type not in ["movie", "show"]:
            continue
        media = item[media_type]
        tmdb_id = media.get("ids", {}).get("tmdb")
        process_and_add_item(_handle, _addon, tmdb_client, media, media_type, tmdb_id)

    add_next_page_item(_handle, "trakt_list_items", headers, page, list_id=list_id)
    xbmcplugin.setContent(_handle, "videos")
    xbmcplugin.endOfDirectory(_handle)


def trakt_genres(params, addon, handle, session=None):
    _trakt_set_globals(session=session)
    category = params.get("category", "movies")

    if "genre" not in params:
        xbmcplugin.setPluginCategory(handle, f"Genres: {category}")
        cache_key = f"trakt_genres_{category}"
        genres = load_trakt_cache(cache_key)
        if not genres:
            url = f"https://api.trakt.tv/genres/{category}"
            resp = safe_get(_session, url, headers=trakt_get_headers(addon))
            if not resp or resp.status_code != 200:
                xbmcplugin.endOfDirectory(handle)
                return
            genres = resp.json()
            save_trakt_cache(cache_key, genres)
        for g in genres:
            li = xbmcgui.ListItem(label=g['name'])
            li.setArt({"icon": Icons.FOLDER})
            url = get_url(action="trakt_genres", category=category, genre=g['slug'])
            xbmcplugin.addDirectoryItem(handle, url, li, True)
        xbmcplugin.endOfDirectory(handle)
        return

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)
    genre = params["genre"]
    year = params.get("year", "")

    if not year and page == 1:
        kb = xbmc.Keyboard("", "○ ROK NEBO ROZSAH (2000-2025) ○")
        kb.doModal()
        if kb.isConfirmed():
            year = kb.getText()

    cache_key = f"trakt_g_{category}_{genre}_{year}_{page}_limit_{limit}"
    cached = load_trakt_cache(cache_key)
    if cached and isinstance(cached, (tuple, list)) and len(cached) == 2:
        items, headers = cached
    else:
        items, headers = None, None

    if not items:
        q = f"genres={genre}"
        if year:
            q += f"&years={year}"
        url = f"https://api.trakt.tv/{category}/popular?extended=full,images&{q}&page={page}&limit={limit}"
        resp = safe_get(_session, url, headers=trakt_get_headers(addon))
        if not resp or resp.status_code != 200:
            xbmcplugin.endOfDirectory(handle)
            return
        items = resp.json()
        headers = dict(resp.headers)
        save_trakt_cache(cache_key, (items, headers))

    from resources.lib.tmdb import TMDB
    tmdb = TMDB(addon, handle, _session)

    xbmcplugin.setPluginCategory(handle, f"{genre.capitalize()} {year}")
    for media in items:
        key = "movie" if category == "movies" else "show"
        target = media[key] if key in media else media
        tmdb_id = target.get("ids", {}).get("tmdb")
        process_and_add_item(handle, addon, tmdb, target, key, tmdb_id)

    add_next_page_item(handle, "trakt_genres", headers, page, category=category, genre=genre, year=year)
    xbmcplugin.setContent(handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(handle)


def trakt_recommended(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    xbmcplugin.setPluginCategory(_handle, "Trakt Recommended")

    if not _addon.getSetting("trakt_access_token").strip():
        notify_error("AUTH Nutné přihlášení k TRAKT.TV", category="TRAKT")
        return

    if "category" not in params:
        for cat, label, icon in [("movies", "FILMY", Icons.MOVIE), ("shows", "SERIÁLY", Icons.TVSHOW)]:
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]DOPORUČENÉ : {label}")
            li.setArt({"icon": icon})
            xbmcplugin.addDirectoryItem(_handle, get_url(action="trakt_recommended", category=cat), li, True)
        xbmcplugin.endOfDirectory(_handle)
        return

    category = params.get("category", "movies")
    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)
    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    lang_suffix = "_cs" if use_czech else ""
    cache_key = f"trakt_recommended_{category}_{page}{lang_suffix}_limit_{limit}"

    cached_content = load_trakt_cache(cache_key)
    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items_data, headers = cached_content
    else:
        items_data, headers = None, None

    if not items_data:
        url = f"https://api.trakt.tv/recommendations/{category}?extended=full,images&page={page}&limit={limit}"
        response = handle_trakt_401(url, addon=_addon, session=_session)
        if not response or response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
            return
        items_data = response.json()
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items_data, headers))

    for media in items_data:
        tmdb_id = media.get("ids", {}).get("tmdb")
        media_type_key = "movie" if category == "movies" else "show"
        process_and_add_item(_handle, _addon, tmdb_client, media, media_type_key, tmdb_id)

    add_next_page_item(_handle, "trakt_recommended", headers, page, category=category)
    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(_handle)


def trakt_watchlist(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session)
    xbmcplugin.setPluginCategory(handle, "Watchlist")

    if "reauth" in params:
        trakt_authenticate(addon, _session)
        return

    if "remove" in params:
        handle_watchlist_remove(params, _session, addon)
        return

    if "show_id" in params:
        if "season" not in params:
            return list_seasons(params, addon, handle, _session)
        else:
            return list_episodes(params, addon, handle, _session)

    if "category" not in params:
        for cat, label in [("movies", "FILMY"), ("shows", "SERIÁLY")]:
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]WATCHLIST : {label}")
            li.setArt({"icon": Icons.WATCH_LATER})
            xbmcplugin.addDirectoryItem(handle, get_url(action="trakt_watchlist", category=cat), li, True)
        xbmcplugin.endOfDirectory(handle)
        return

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)
    category = params["category"]
    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    cache_key = f"trakt_wl_{category}_{page}{'_cs' if use_czech else ''}_limit_{limit}"

    cache_key = _personal_list_cache_key(addon, "TRAKT_WATCHLIST", cache_key)
    cached = load_trakt_cache(cache_key, section="TRAKT_WATCHLIST") if cache_key else None
    if cached and isinstance(cached, (tuple, list)) and len(cached) == 2:
        items, headers = cached
    else:
        items, headers = None, None

    if items is None:
        url = f"https://api.trakt.tv/users/me/watchlist/{category}?extended=full,images&page={page}&limit={limit}"
        resp = handle_trakt_401(url, addon, _session)
        if not resp or resp.status_code != 200:
            xbmcplugin.endOfDirectory(handle)
            return
        items = resp.json()
        headers = dict(resp.headers)
        if cache_key:
            save_trakt_cache(cache_key, (items, headers), section="TRAKT_WATCHLIST")

    items = sorted(items, key=lambda x: x.get("movie", x.get("show", {})).get("title", ""))

    from resources.lib.tmdb import TMDB
    tmdb = TMDB(addon, handle, _session)

    for item in items:
        key = "movie" if category == "movies" else "show"
        if key not in item:
            continue
        media = item[key]
        tmdb_id = media.get("ids", {}).get("tmdb")
        extra = [(f"[COLOR {Colors.RED}]► ODSTRANIT POLOŽKU[/COLOR]", f"RunPlugin({get_url(action='trakt_watchlist', category=category, remove=media['ids']['trakt'])})")]
        process_and_add_item(handle, addon, tmdb, media, key, tmdb_id, extra_context=extra)

    add_next_page_item(handle, "trakt_watchlist", headers, page, category=category)
    xbmcplugin.setContent(handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(handle)


def trakt_favorites(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session)
    xbmcplugin.setPluginCategory(handle, "Favorites")

    if "reauth" in params:
        if trakt_authenticate(addon, _session):
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass
        return

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)

    if "category" not in params:
        return
    if "show_id" in params:
        if "season" not in params:
            return list_seasons(params, addon, handle, _session)
        else:
            return list_episodes(params, addon, handle, _session)

    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    cache_key = f"trakt_fav_{params['category']}_{page}{'_cs' if use_czech else ''}_limit_{limit}"

    cache_key = _personal_list_cache_key(addon, "TRAKT_FAVORITES", cache_key)
    cached = load_trakt_cache(cache_key, section="TRAKT_FAVORITES") if cache_key else None
    if cached and isinstance(cached, (tuple, list)) and len(cached) == 2:
        items, headers = cached
    else:
        items, headers = None, None

    if items is None:
        url = f"https://api.trakt.tv/users/me/favorites/{params['category']}?extended=full,images&page={page}&limit={limit}"
        resp = handle_trakt_401(url, addon, _session)
        if not resp or resp.status_code != 200:
            xbmcplugin.endOfDirectory(handle)
            return
        items = resp.json()
        headers = dict(resp.headers)
        if cache_key:
            save_trakt_cache(cache_key, (items, headers), section="TRAKT_FAVORITES")

    from resources.lib.tmdb import TMDB
    tmdb = TMDB(addon, handle, _session)

    for item in items:
        key = "movie" if params['category'] == "movies" else "show"
        if key not in item:
            continue
        media = item[key]
        tmdb_id = media.get("ids", {}).get("tmdb")
        process_and_add_item(handle, addon, tmdb, media, key, tmdb_id)

    add_next_page_item(handle, "trakt_favorites", headers, page, category=params['category'])
    xbmcplugin.setContent(handle, "movies" if params['category'] == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(handle)


def get_watched_history(media_type, page=1, limit=20):
    url = f'https://api.trakt.tv/users/me/history/{media_type}?page={page}&limit={limit}&extended=full,images'
    response = handle_trakt_401(url, addon=_addon, session=_session)
    if not response or response.status_code != 200:
        return None, None
    return response.json(), {k: v for k, v in response.headers.items()}


def trakt_personal_lists(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    xbmcplugin.setPluginCategory(_handle, "Trakt Personal Lists")

    if not _addon.getSetting("trakt_access_token"):
        notify_error("AUTH Pro zobrazení osobních seznamů je třeba se připojit", category="TRAKT")
        return

    url = 'https://api.trakt.tv/users/me/lists'
    response = handle_trakt_401(url, addon=_addon, session=_session)
    if not response or response.status_code != 200:
        return

    lists = response.json()
    for personal_list in lists:
        list_name = personal_list.get('name')
        list_id = personal_list.get('ids', {}).get('trakt')
        if not list_name or not list_id:
            continue

        listitem = xbmcgui.ListItem(label=list_name)
        listitem.setArt({"icon": Icons.TRAKT_WHITE})
        video_info = listitem.getVideoInfoTag()
        video_info.setTitle(list_name)
        video_info.setPlot(personal_list.get('description', ''))
        url = get_url(action="trakt_list_items", list_id=list_id)
        xbmcplugin.addDirectoryItem(_handle, url, listitem, True)

    xbmcplugin.endOfDirectory(_handle)


def trakt_my_calendar(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    category = params.get("category")
    if not category:
        xbmcplugin.setPluginCategory(_handle, "TRAKT.TV : KALENDÁŘ")
        for media_type, label, icon in (
            ("shows", "SERIÁLY", Icons.TVSHOW),
            ("movies", "FILMY", Icons.MOVIE),
        ):
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]KALENDÁŘ : {label}")
            li.setArt({"icon": icon, "thumb": icon, "poster": icon})
            xbmcplugin.addDirectoryItem(_handle, get_url(action="trakt_calendar", category=media_type), li, True)
        xbmcplugin.endOfDirectory(_handle)
        return

    if category not in ("shows", "movies"):
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return

    xbmcplugin.setPluginCategory(_handle, params.get("title") or f"KALENDÁŘ : {'SERIÁLY' if category == 'shows' else 'FILMY'}")

    if not _get_trakt_access_token() and not _get_trakt_refresh_token():
        notify_error("AUTH Pro kalendář je nutné přihlášení", category="TRAKT")
        xbmcplugin.endOfDirectory(_handle)
        return

    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        days = max(1, min(int(params.get("days", 14)), 30))
    except (TypeError, ValueError):
        days = 14
    cache_key = f"trakt_calendar_my_{category}_{today}_{days}"

    items_data = cache_manager.window_cache_get(cache_key)
    if not items_data:
        items_data = load_trakt_cache(cache_key)
        if isinstance(items_data, tuple):
            items_data = items_data[0]
        if items_data:
            cache_manager.window_cache_set(cache_key, items_data)

    if not items_data:
        url = f"https://api.trakt.tv/calendars/my/{category}/{today}/{days}?extended=full"
        response = handle_trakt_401(url, addon=_addon, session=_session)
        if not response or response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle)
            return
        items_data = response.json()
        save_trakt_cache(cache_key, items_data)
        cache_manager.window_cache_set(cache_key, items_data)

    for item in items_data:
        if category == "movies":
            movie = item.get("movie") or {}
            if not movie:
                continue
            released = str(item.get("released") or "")
            date_label = f" [COLOR {Colors.YELLOW}]|{released[8:10]}.{released[5:7]}|[/COLOR]" if len(released) >= 10 else ""
            process_and_add_item(_handle, _addon, tmdb_client, movie, "movie", movie.get("ids", {}).get("tmdb"), label_suffix=date_label, ensure_art=True)
            continue

        show = item.get("show") or {}
        episode = item.get("episode") or {}
        if not show or not episode:
            continue
        aired_str = str(item.get("first_aired") or "")
        date_label = f" [COLOR {Colors.YELLOW}]|{aired_str[8:10]}.{aired_str[5:7]}|[/COLOR]" if len(aired_str) >= 10 else ""
        try:
            ep_code = f"S{int(episode.get('season')):02d}E{int(episode.get('number')):02d}"
        except (TypeError, ValueError):
            ep_code = ""
        suffix = f" {date_label} [B]{ep_code}[/B] - {episode.get('title') or ''}"
        process_and_add_item(_handle, _addon, tmdb_client, show, "show", show.get("ids", {}).get("tmdb"), label_suffix=suffix, ensure_art=True)

    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "tvshows")
    xbmcplugin.endOfDirectory(_handle)


def trakt_in_progress(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    category = params.get("category")
    if not category:
        xbmcplugin.setPluginCategory(_handle, "TRAKT.TV : IN-PROGRESS")
        for media_type, label, icon in (
            ("movies", "FILMY", Icons.MOVIE),
            ("episodes", "SERIÁLY", Icons.TVSHOW),
        ):
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]IN-PROGRESS : {label}")
            li.setArt({"icon": icon, "thumb": icon, "poster": icon})
            xbmcplugin.addDirectoryItem(_handle, get_url(action="trakt_in_progress", category=media_type), li, True)
        xbmcplugin.endOfDirectory(_handle)
        return

    if category not in ("movies", "episodes"):
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    xbmcplugin.setPluginCategory(_handle, f"IN-PROGRESS : {'FILMY' if category == 'movies' else 'SERIÁLY'}")
    if not _get_trakt_access_token() and not _get_trakt_refresh_token():
        notify_error("AUTH Pro IN-PROGRESS je nutné přihlášení", category="TRAKT")
        xbmcplugin.endOfDirectory(_handle)
        return

    from resources.lib.tmdb import TMDB
    from resources.lib.utils import store_meta_in_cache
    tmdb_client = TMDB(addon, handle, _session)
    try:
        page = max(1, int(params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    limit = get_setting_int_with_bounds(addon, "trakt_page_limit", 20, 1, 100)
    url = f"https://api.trakt.tv/sync/playback/{category}?page={page}&limit={limit}&extended=full"
    response = handle_trakt_401(url, addon=_addon, session=_session)
    if response is None or response.status_code != 200:
        xbmcplugin.endOfDirectory(_handle)
        return

    for item in response.json():
        try:
            progress = float(item.get("progress", 0))
        except (TypeError, ValueError):
            continue
        if not 0 < progress < 100:
            continue
        progress_label = f" [I][COLOR {Colors.ORANGE}][ {progress:.0f} % ][/COLOR][/I]"

        if category == "movies":
            movie = item.get("movie") or {}
            if movie:
                process_and_add_item(_handle, _addon, tmdb_client, movie, "movie", movie.get("ids", {}).get("tmdb"), label_suffix=progress_label, ensure_art=True)
            continue

        episode = item.get("episode") or {}
        show = item.get("show") or {}
        if not episode or not show:
            continue
        try:
            season_num = int(episode.get("season"))
            episode_num = int(episode.get("number"))
        except (TypeError, ValueError):
            continue
        show_title = show.get("title") or "Neznámý seriál"
        episode_title = episode.get("title") or ""
        show_tmdb_id = show.get("ids", {}).get("tmdb")
        label = f"{show_title} - S{season_num:02d}E{episode_num:02d} - {episode_title}{progress_label}"
        props = {
            "tmdb_id": show_tmdb_id,
            "title": episode_title,
            "tv_show_title": show_title,
            "season": season_num,
            "episode": episode_num,
            "media_type": "episode",
            "plot": episode.get("overview") or "",
            "progress": progress,
        }
        props.update(_tmdb_show_art(tmdb_client, show_tmdb_id))
        li = xbmcgui.ListItem(label=label)
        tmdb_client.fill_list_item(li, props, "episode")
        if not props.get("poster"):
            li.setArt({"icon": Icons.TVSHOW})
        meta_key = store_meta_in_cache(props)
        xbmcplugin.addDirectoryItem(_handle, get_url(action="find_sources", meta=meta_key), li, True)

    add_next_page_item(_handle, "trakt_in_progress", dict(response.headers), page, category=category)
    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "episodes")
    xbmcplugin.endOfDirectory(_handle)


def trakt_watched_history(params, addon, handle, session=None):
    _trakt_set_globals(session=session)
    xbmcplugin.setPluginCategory(handle, "History")

    if "reauth" in params:
        if trakt_authenticate(addon, _session):
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass
        return

    if "category" not in params:
        for cat, label, icon in [("movies", "FILMY", Icons.MOVIE), ("shows", "SERIÁLY", Icons.TVSHOW)]:
            api_cat = "movies" if cat == "movies" else "episodes"
            li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]HISTORIE : {label}")
            li.setArt({"icon": icon, "thumb": icon, "poster": icon})
            xbmcplugin.addDirectoryItem(handle, get_url(action="trakt_history", category=api_cat), li, True)
        xbmcplugin.endOfDirectory(handle)
        return

    page = int(params.get("page", 1))
    limit = get_setting_int_with_bounds(addon, 'trakt_page_limit', 20)
    category = "episodes" if params["category"] == "shows" else params["category"]
    if category not in ("movies", "episodes"):
        xbmcplugin.endOfDirectory(handle, succeeded=False)
        return
    use_czech = addon.getSettingBool('trakt_prefer_czech_search')
    cache_key = f"trakt_hist_{category}_{page}{'_cs' if use_czech else ''}_limit_{limit}"

    cached = load_trakt_cache(cache_key)
    if cached and isinstance(cached, (tuple, list)) and len(cached) == 2:
        items, headers = cached
    else:
        items, headers = None, None

    if items is None:
        url = f"https://api.trakt.tv/users/me/history/{category}?page={page}&limit={limit}&extended=full"
        resp = handle_trakt_401(url, addon, _session)
        if not resp or resp.status_code != 200:
            xbmcplugin.endOfDirectory(handle)
            return
        items = resp.json()
        headers = dict(resp.headers)
        save_trakt_cache(cache_key, (items, headers))

    from resources.lib.tmdb import TMDB
    tmdb = TMDB(addon, handle, _session)

    for item in items:
        m_type = item.get("type")
        watched_at_str = item.get('watched_at', '')
        suffix = ""
        if watched_at_str and addon.getSettingBool('trakt_show_time'):
            try:
                dt = datetime.strptime(watched_at_str, '%Y-%m-%dT%H:%M:%S.%fZ')
                suffix = f" [I][COLOR {Colors.GREY}][ {dt.strftime('%d.%m %H:%M')} ][/I][/COLOR]"
            except Exception:
                pass

        if m_type == "movie" and "movie" in item:
            media = item['movie']
            tmdb_id = media.get("ids", {}).get("tmdb")
            process_and_add_item(handle, addon, tmdb, media, "movie", tmdb_id, label_suffix=suffix, ensure_art=True)

        elif m_type == "episode" and "episode" in item:
            media = item['episode']
            show = item.get('show', {})
            show_tmdb = show.get("ids", {}).get("tmdb")
            show_title = show.get('title', 'Neznámý')

            ep_title_full = f"{show_title} - S{media.get('season',0):02d}E{media.get('number',0):02d} - {media.get('title','')}" + suffix
            li = xbmcgui.ListItem(label=ep_title_full)

            props = {
                "tmdb_id": show_tmdb,
                "media_type": "episode",
                "tv_show_title": show_title,
                "season": media.get('season'),
                "episode": media.get('number'),
                "title": media.get('title'),
                "plot": media.get('overview'),
                "rating": media.get('rating'),
                "votes": media.get('votes')
            }
            props.update(_tmdb_show_art(tmdb, show_tmdb))

            tmdb.fill_list_item(li, props, 'episode')

            if not props.get("thumb"):
                li.setArt({"icon": Icons.TVSHOW})

            meta = {
                "tmdb_id": show_tmdb,
                "media_type": "episode",
                "season": props['season'],
                "episode": props['episode'],
                "title": ep_title_full,
                "tv_show_title": show_title
            }
            from resources.lib.utils import store_meta_in_cache
            meta_key = store_meta_in_cache(meta)
            url = get_url(action="find_sources", meta=meta_key)

            try:
                player_menu_params = {
                    'action': 'show_player_menu',
                    'tmdb_id': show_tmdb or "",
                    'media_type': 'tv',
                    'title': show_title,
                    'context': 'trakt',
                    'props': json.dumps({}),
                }
                play_item = (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(**player_menu_params)})")
            except Exception:
                play_item = None

            items_menu = []
            if show_tmdb:
                tmdb_detail_url = get_url(action="listing_tmdb_tv", tmdb_id=show_tmdb, meta=meta_key)
                items_menu.append((f"[COLOR {Colors.YELLOW}]► INFORMACE SERIÁLU[/COLOR]", f"RunPlugin({tmdb_detail_url})"))

            items_menu.append((f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL[/COLOR]", f"RunPlugin({get_url(action='search_title', name=show_title)})"))

            if play_item:
                items_menu.append(play_item)

            items_menu.append((f"[COLOR {Colors.LIMEGREEN}][ MENU NASTAVENÍ ][/COLOR]", "Addon.OpenSettings(plugin.video.play_er)"))
            li.addContextMenuItems(_sf_cm_items(items_menu))
            xbmcplugin.addDirectoryItem(handle, url, li, True)

    add_next_page_item(handle, "trakt_history", headers, page, category=category)
    xbmcplugin.setContent(handle, "movies" if category == "movies" else "episodes")
    xbmcplugin.endOfDirectory(handle)


def trakt_user_history(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    username = params.get("username")
    category = params.get("media_type")
    if not username or not category:
        xbmcplugin.endOfDirectory(_handle)
        return

    api_category = "movies" if category == "movies" else "episodes"
    xbmcplugin.setPluginCategory(_handle, f"Social Feed: {username} - {category.capitalize()}")

    page = int(params.get("page", "1"))
    limit = get_setting_int_with_bounds(addon, 'trakt_social_feed_limit', 20)
    cache_key = f"trakt_social_feed_{username}_{category}_{page}_limit_{limit}"
    cached_content = load_trakt_cache(cache_key)

    if cached_content and isinstance(cached_content, (tuple, list)) and len(cached_content) == 2:
        items_data, headers = cached_content
    else:
        items_data, headers = None, None

    if not items_data:
        url = f"https://api.trakt.tv/users/{quote(username, safe='')}/history/{api_category}?extended=full&page={page}&limit={limit}"
        response = handle_trakt_401(url, addon=_addon, session=_session)
        if not response or response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle)
            return
        items_data = response.json()
        if not items_data:
            xbmcplugin.endOfDirectory(_handle)
            return
        headers = dict(response.headers)
        save_trakt_cache(cache_key, (items_data, headers))

    for item in items_data:
        media_type = item.get("type")
        watched_at_str = item.get('watched_at')
        date_suffix = ""
        if watched_at_str:
            try:
                watched_date = datetime.strptime(watched_at_str, '%Y-%m-%dT%H:%M:%S.%fZ')
                date_suffix = f" [I][COLOR {Colors.GREY}][ {watched_date.strftime('%d.%m.%Y %H:%M')} ][/COLOR][/I]"
            except Exception:
                pass

        if media_type == 'movie' and 'movie' in item:
            media = item['movie']
            tmdb_id = media.get("ids", {}).get("tmdb")
            process_and_add_item(_handle, _addon, tmdb_client, media, 'movie', tmdb_id, label_suffix=date_suffix, ensure_art=True)

        elif media_type == 'episode' and 'episode' in item:
            media = item['episode']
            show = item.get('show', {})
            show_tmdb_id = show.get("ids", {}).get("tmdb")
            show_title = show.get('title', 'Neznámý seriál')

            ep_title_core = media.get('title', '')
            label = f"{show_title} - S{media.get('season'):02d}E{media.get('number'):02d} - {ep_title_core}" + date_suffix

            li = xbmcgui.ListItem(label=label)
            props = {
                "tmdb_id": show_tmdb_id,
                "title": ep_title_core,
                "tv_show_title": show_title,
                "season": media.get('season'),
                "episode": media.get('number'),
                "media_type": "episode",
                "plot": media.get('overview'),
                "rating": media.get('rating')
            }
            props.update(_tmdb_show_art(tmdb_client, show_tmdb_id))

            tmdb_client.fill_list_item(li, props, 'episode')

            if not props.get("thumb"):
                li.setArt({"icon": Icons.TVSHOW})

            meta = {
                "tmdb_id": show_tmdb_id,
                "title": label,
                "tv_show_title": show_title,
                "season": media.get('season'),
                "episode": media.get('number'),
                "media_type": "episode"
            }
            from resources.lib.utils import store_meta_in_cache
            meta_key = store_meta_in_cache(meta)
            url = get_url(action="find_sources", meta=meta_key)
            xbmcplugin.addDirectoryItem(_handle, url, li, True)

    add_next_page_item(_handle, "trakt_user_history", headers, page, username=username, media_type=category)
    xbmcplugin.setContent(_handle, "movies" if category == "movies" else "episodes")
    xbmcplugin.endOfDirectory(_handle)


def list_seasons(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    show_id = params["show_id"]
    cache_key = f"trakt_show_seasons_{show_id}"
    show_details = load_trakt_cache(cache_key)

    if not show_details:
        show_url = f"https://api.trakt.tv/shows/{show_id}?extended=full,images"
        show_response = safe_get(_session, show_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        if not show_response or show_response.status_code != 200:
            return
        show = show_response.json()
        seasons_url = f"https://api.trakt.tv/shows/{show_id}/seasons?extended=full,images,episodes"
        seasons_response = safe_get(_session, seasons_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        if not seasons_response or seasons_response.status_code != 200:
            return
        seasons = seasons_response.json()
        show_details = {"show": show, "seasons": seasons}
        save_trakt_cache(cache_key, show_details)

    show = show_details["show"]
    seasons = show_details["seasons"]
    tmdb_show_id = show.get("ids", {}).get("tmdb")

    show_props = {}
    if tmdb_show_id:
        try:
            raw_show = tmdb_client.get_full_details("tv", tmdb_show_id)
            if raw_show:
                show_props = tmdb_client._build_metadata_props(raw_show, "tv")
        except Exception:
            pass

    xbmcplugin.setPluginCategory(_handle, f"{show.get('title', 'Neznámý název')}")

    for season in sorted(seasons, key=lambda x: x["number"]):
        season_num = season["number"]
        if season_num == 0:
            continue
        episode_count = len(season.get("episodes", []))
        label = f"Sezóna {season_num} ({episode_count} epizod)"
        listitem = xbmcgui.ListItem(label=label)

        poster_url = ""
        if isinstance(season.get("images"), dict):
            images = season["images"]
            if isinstance(images.get("poster"), list) and images["poster"]:
                poster_url = images["poster"][0]
                if poster_url and not poster_url.startswith("http"):
                    poster_url = f"https://{poster_url}"

        if not poster_url:
            poster_url = show_props.get("poster")

        fanart_url = show_props.get("fanart")

        props = {
            "tmdb_id": tmdb_show_id,
            "media_type": "season",
            "title": f"Sezóna {season_num}",
            "tv_show_title": show.get("title"),
            "season": season_num,
            "plot": season.get("overview") or f"Počet epizod: {episode_count}",
            "poster": poster_url,
            "fanart": fanart_url,
            "thumb": poster_url
        }

        tmdb_client.fill_list_item(listitem, props, "season")
        url = get_url(action="trakt_watchlist", show_id=show_id, season=season_num, series_title=show.get("title"), category="shows")
        xbmcplugin.addDirectoryItem(_handle, url, listitem, True)

    xbmcplugin.setContent(_handle, "seasons")
    xbmcplugin.endOfDirectory(_handle)


def list_episodes(params, addon, handle, session=None):
    _trakt_set_globals(addon=addon, session=session, handle=handle)
    from resources.lib.tmdb import TMDB
    tmdb_client = TMDB(addon, handle, _session)

    show_id = params["show_id"]
    season_num = params["season"]
    series_title = params["series_title"]

    xbmcplugin.setPluginCategory(_handle, f"{_addon.getAddonInfo('name')} / Sezóna {season_num}")

    if not _addon.getSetting("trakt_access_token").strip():
        trakt_refresh_token(addon=_addon, session=_session)

    tmdb_show_id = get_tmdb_id(show_id, "show")
    if not tmdb_show_id:
        notify_error("ERROR Nepodařilo se nalézt TMDB ID seriálu", category="TMDB")
        xbmcplugin.endOfDirectory(_handle)
        return

    cache_key = f"trakt_season_episodes_{show_id}_{season_num}"
    episodes_data = load_trakt_cache(cache_key)
    if not episodes_data:
        seasons_url = f"https://api.trakt.tv/shows/{show_id}/seasons/{season_num}?extended=full,images,episodes"
        seasons_response = handle_trakt_401(seasons_url, addon=_addon, session=_session)
        if not seasons_response or seasons_response.status_code != 200:
            xbmcplugin.endOfDirectory(_handle)
            return
        episodes_data = seasons_response.json()
        save_trakt_cache(cache_key, episodes_data)

    episodes = episodes_data if isinstance(episodes_data, list) else []
    tmdb_season_data = {}
    tmdb_show_props = {}

    if tmdb_client:
        try:
            season_raw = tmdb_client.get_season_details_raw(tmdb_show_id, season_num)
            if season_raw and "episodes" in season_raw:
                tmdb_season_data = {ep['episode_number']: ep for ep in season_raw['episodes']}

            show_raw = tmdb_client.get_full_details("tv", tmdb_show_id)
            if show_raw:
                tmdb_show_props = tmdb_client._build_metadata_props(show_raw, "tv")
        except Exception as e:
            log(f"TRAKT LIST EPISODES - Chyba TMDB sync: {e}", xbmc.LOGWARNING)

    today = datetime.now().date()

    for episode in episodes:
        ep_num = episode.get("number")
        tmdb_ep_data = tmdb_season_data.get(ep_num)
        props = {}
        if tmdb_ep_data:
            props = tmdb_client._build_metadata_props(tmdb_ep_data, "episode")
            props['tv_show_title'] = series_title
            if not props.get('cast_full') and tmdb_show_props.get('cast_full'):
                props['cast_full'] = tmdb_show_props['cast_full']
            if not props.get('poster'): props['poster'] = tmdb_show_props.get('poster')
            if not props.get('fanart'): props['fanart'] = tmdb_show_props.get('fanart')
        else:
            ep_title = episode.get("title", f"Epizoda {ep_num}")
            props = {
                "tmdb_id": tmdb_show_id,
                "media_type": "episode",
                "title": ep_title,
                "original_title": ep_title,
                "tv_show_title": series_title,
                "season": season_num,
                "episode": ep_num,
                "plot": episode.get("overview", ""),
                "rating": episode.get("rating", 0.0),
                "premiered": episode.get("first_aired", ""),
                "poster": tmdb_show_props.get("poster", ""),
                "fanart": tmdb_show_props.get("fanart", "")
            }
            if isinstance(episode.get("images"), dict):
                screenshot = episode["images"].get("screenshot", {}).get("full")
                if screenshot:
                    props["thumb"] = screenshot

        ep_air_date = props.get("premiered")
        air_date_str = ""
        is_future = False

        if ep_air_date:
            try:
                date_part = ep_air_date.split("T")[0]
                year, month, day = list(map(int, date_part.split("-")))
                air_date_obj = date(year, month, day)
                if air_date_obj > today:
                    is_future = True
                    air_date_str = f" ({day:02d}.{month:02d}.{year})"
            except Exception:
                pass

        label = props.get("title")
        if is_future:
            label += f"[COLOR {Colors.RED}]{air_date_str}[/COLOR]"
        elif air_date_str:
            label += f"[COLOR {Colors.GRAY}]{air_date_str}[/COLOR]"

        listitem = xbmcgui.ListItem(label=label)
        tmdb_client.fill_list_item(listitem, props, 'episode')

        meta = {
            "tmdb_id": tmdb_show_id,
            "title": f"{series_title} S{int(season_num):02d}E{int(ep_num):02d}",
            "tv_show_title": series_title,
            "season": int(season_num),
            "episode": int(ep_num),
            "plot": props.get("plot", ""),
            "media_type": "episode",
            "poster": props.get("poster"),
            "fanart": props.get("fanart")
        }

        from resources.lib.utils import store_meta_in_cache
        meta_key = store_meta_in_cache(meta)
        url = get_url(action="find_sources", meta=meta_key)

        player_params = {
            'action': 'show_player_menu',
            'tmdb_id': tmdb_show_id,
            'media_type': 'tv',
            'title': series_title,
            'context': 'trakt',
            'props': json.dumps({})
        }
        context_menu = [
            (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(**player_params)})")
        ]

        listitem.addContextMenuItems(_sf_cm_items(context_menu))
        listitem.setProperty("IsPlayable", "true")
        xbmcplugin.addDirectoryItem(_handle, url, listitem, True)

    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_EPISODE)
    xbmcplugin.endOfDirectory(_handle)


def trakt_scrobble(media_id, media_type, progress, action, _addon, _session, meta=None):
    """
    TRAKT SCROBBLE :: Odeslání dat na Trakt API s plnou podporou Trakt ID i přímého TMDB ID.
    """
    if media_type not in ["movie", "episode"]:
        return

    access_token = _get_trakt_access_token()
    if not access_token:
        _trakt_set_globals(addon=_addon, session=_session)
        win = xbmcgui.Window(10000)
        if win.getProperty("play_er.trakt_refreshing") != "true":
            win.setProperty("play_er.trakt_refreshing", "true")
            trakt_refresh_token(addon=_addon, session=_session)
            win.clearProperty("play_er.trakt_refreshing")
        access_token = _get_trakt_access_token()
        if not access_token:
            log("TRAKT SCROBBLE - Chybí platný access token!", xbmc.LOGWARNING)
            return

    try:
        progress = float(progress)
    except Exception:
        progress = 0.0

    progress = round(max(0.0, min(100.0, progress)), 2)
    url = f"https://api.trakt.tv/scrobble/{action}"

    # Sestavení těla dotazu: Pokud máme trakt_id, použijeme jej. Pokud ne, použijeme TMDB ID z meta!
    item_payload = {}
    if media_id and str(media_id).isdigit() and int(media_id) > 0:
        item_payload = {"ids": {"trakt": int(media_id)}}
    elif meta and meta.get("tmdb_id"):
        try:
            tmdb_val = int(meta["tmdb_id"])
            if media_type == "movie":
                item_payload = {"ids": {"tmdb": tmdb_val}}
            else:
                # Pro epizodu Trakt podporuje show ident + season + episode
                s = int(meta.get("season", 1))
                e = int(meta.get("episode", 1))
                data = {
                    "show": {"ids": {"tmdb": tmdb_val}},
                    "episode": {"season": s, "number": e},
                    "progress": progress,
                    "app_version": _addon.getAddonInfo("version"),
                    "app_date": datetime.now().strftime("%Y-%m-%d")
                }
                item_payload = None  # Speciální struktura pro epizodu
        except Exception:
            pass

    if item_payload is not None:
        if not item_payload:
            log(f"TRAKT SCROBBLE - Chybí identifikátor pro {media_type}, nelze scroblovat.", xbmc.LOGWARNING)
            return
        data = {
            media_type: item_payload,
            "progress": progress,
            "app_version": _addon.getAddonInfo("version"),
            "app_date": datetime.now().strftime("%Y-%m-%d")
        }

    attempt = 0
    while attempt < TRAKT_SCROBBLE_MAX_RETRIES:
        attempt += 1
        try:
            headers = trakt_get_headers(addon=_addon, write=True)
            response = safe_post(_session, url, headers=headers, json=data, timeout=TRAKT_SCROBBLE_TIMEOUT)
            if response is None:
                break

            if response.status_code == 401:
                log(f"TRAKT SCROBBLE - 401 Unauthorized při {action}, obnovuji token (Pokus {attempt})...", xbmc.LOGWARNING)
                if attempt < TRAKT_SCROBBLE_MAX_RETRIES:
                    win = xbmcgui.Window(10000)
                    if win.getProperty("play_er.trakt_refreshing") != "true":
                        win.setProperty("play_er.trakt_refreshing", "true")
                        trakt_refresh_token(addon=_addon, session=_session)
                        win.clearProperty("play_er.trakt_refreshing")
                    continue
                else:
                    break

            if response.status_code in [201, 200]:
                log(f"TRAKT SCROBBLE - {action.upper()} OK [ ID/Payload: {media_id or meta.get('tmdb_id')} | {progress}% ]", xbmc.LOGINFO)
                return
            elif response.status_code == 409:
                log(f"TRAKT SCROBBLE - 409 Konflikt (scrobble již probíhá), ignoruji.", xbmc.LOGDEBUG)
                break
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", TRAKT_SCROBBLE_RATE_LIMIT_WAIT))
                xbmc.sleep(retry_after * 1000)
            else:
                log(f"TRAKT SCROBBLE - Neočekávaný status: {response.status_code} - {response.text}", xbmc.LOGWARNING)
                break
        except Exception as e:
            log(f"TRAKT SCROBBLE - Výjimka: {e}", xbmc.LOGWARNING)
            break


def trakt_scrobble_start(media_id, media_type, progress, addon, session, meta=None):
    trakt_scrobble(media_id, media_type, progress, "start", addon, session, meta=meta)


def trakt_scrobble_pause(media_id, media_type, progress, addon, session, meta=None):
    trakt_scrobble(media_id, media_type, progress, "pause", addon, session, meta=meta)


def trakt_scrobble_stop(media_id, media_type, progress, addon, session, meta=None):
    trakt_scrobble(media_id, media_type, progress, "stop", addon, session, meta=meta)


class KodiPlayerMonitor(xbmc.Player):
    """
    CLASS :: KODI PLAYER MONITOR
    -- Sledování přehrávání, scrobble pro Trakt a event-driven refresh pro Kodi 22.
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.session = kwargs.get("session") or requests.Session()
        self.addon = kwargs.get("addon") or xbmcaddon.Addon(id="plugin.video.play_er")
        self.tmdb_client = kwargs.get("tmdb_client")
        self.save_playback_history_func = kwargs.get("save_playback_history_func")
        self.remove_from_watch_later_func = kwargs.get("remove_from_watch_later_func")
        self.mark_watched_func = kwargs.get("mark_watched_func")
        self.scrobbling_in_progress = False
        self.media_id = None
        self.media_type = None
        self.last_known_progress = 0.0
        self._progress_known = False
        self._progress_sample_lock = threading.RLock()
        self._pending_seek = None
        self._seek_was_paused = False
        self._progress_seek_revision = 0
        self.progress_update_timer = None
        self._progress_timer_revision = 0
        self._progress_recheck_on_resume = False
        self.progress_lock = threading.Lock()
        self._playback_action_lock = threading.RLock()
        self._scrobble_executor = None
        self._downgrade_generation = 0
        self._playback_item_generation = 0
        self.scrobble_start_timer = None
        self.subtitle_timer = None
        self.current_meta = None
        self._last_av_started_key = None
        self._last_av_started_at = 0.0
        self.pre_emptive_triggered = False
        self.skip_credits_triggered = False
        self.play_key = None
        self.downgrade_timer = None
        self.is_buffering_since = 0
        # FIX PRE-EMPTIVE AND FILTERS [SINGLE ACTIVE PLAYBACK INVOCATION]
        self._playback_owner = None
        self._playback_confirmed = False
        self._last_owned_meta = None
        # FIX PRE-EMPTIVE AND FILTERS [COALESCE SEEK SCROBBLES]
        self.seek_scrobble_timer = None
        self._seek_generation = 0

        try:
            self.orchestrator = get_orchestrator()
        except Exception:
            self.orchestrator = None

    # FIX PRE-EMPTIVE AND FILTERS [MONITOR HANDOFF BETWEEN PLUGIN INVOCATIONS]
    def claim_playback(self):
        self._playback_owner = f"{id(self)}:{time.time_ns()}"
        self._playback_confirmed = False
        self._last_owned_meta = None
        self._last_av_started_key = None
        self._last_av_started_at = 0.0
        xbmcgui.Window(10000).setProperty('play_er.monitor_owner', self._playback_owner)

    def owns_playback(self):
        return bool(self._playback_owner) and (
            xbmcgui.Window(10000).getProperty('play_er.monitor_owner') == self._playback_owner
        )

    def _reset_progress(self):
        with self._progress_sample_lock:
            self.last_known_progress = 0.0
            self._progress_known = False
            self._pending_seek = None
            self._seek_was_paused = False

    def _set_seek_progress(self, position, duration, paused=False):
        with self._progress_sample_lock:
            target = max(0.0, min(duration, position))
            self.last_known_progress = target / duration * 100.0
            self._progress_known = True
            self._pending_seek = (target, time.monotonic())
            self._seek_was_paused = paused

    def _sample_progress(self, position, duration, paused=False):
        """Ignore the old player clock briefly while a seek is still settling."""
        with self._progress_sample_lock:
            if self._pending_seek:
                target, started = self._pending_seek
                elapsed = max(0.0, time.monotonic() - started)
                if paused:
                    self._seek_was_paused = True
                tolerance = 1.0 if paused else 1.0 + min(elapsed, 3.0)
                if abs(position - target) <= tolerance:
                    self._pending_seek = None
                    self._seek_was_paused = False
                elif paused or elapsed < 3.0 or xbmc.getCondVisibility('Player.Caching'):
                    self.last_known_progress = max(0.0, min(100.0, target / duration * 100.0))
                    self._progress_known = True
                    return self.last_known_progress, False
                else:
                    self._pending_seek = None
                    self._seek_was_paused = False
            self.last_known_progress = max(0.0, min(100.0, position / duration * 100.0))
            self._progress_known = True
            return self.last_known_progress, True

    def _resume_pending_seek(self):
        with self._progress_sample_lock:
            if self._pending_seek and self._seek_was_paused:
                self._pending_seek = (self._pending_seek[0], time.monotonic())
                self._seek_was_paused = False

    def _schedule_progress_update_locked(self, delay, generation):
        self._progress_timer_revision += 1
        self.progress_update_timer = threading.Timer(
            delay, self._update_progress, args=(generation, self._progress_timer_revision))
        self.progress_update_timer.start()

    def _queue_scrobble(self, action, media_id, media_type, progress, meta=None,
                        expected_generation=None):
        """Serialize network events; a stale timer cannot restart a stopped item."""
        with self._playback_action_lock:
            generation = self._playback_item_generation if expected_generation is None else expected_generation
            snapshot = dict(meta) if meta else None
            if action != "stop" and (
                not self.owns_playback() or not self.scrobbling_in_progress
                or generation != self._playback_item_generation
            ):
                return None
            if self._scrobble_executor is None:
                self._scrobble_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="player-scrobble")

            def send():
                if action != "stop":
                    with self._playback_action_lock:
                        if (not self.owns_playback() or not self.scrobbling_in_progress
                                or generation != self._playback_item_generation
                                or (action == "start" and not get_setting_bool(self.addon, "enable_trakt_scrobbling"))):
                            return
                request = {"start": trakt_scrobble_start, "pause": trakt_scrobble_pause,
                           "stop": trakt_scrobble_stop}[action]
                try:
                    request(media_id, media_type, progress, self.addon, self.session, meta=snapshot)
                except Exception as e:
                    log(f"TRAKT - Queued {action} failed: {e}", xbmc.LOGWARNING)

            return self._scrobble_executor.submit(send)

    def _close_scrobble_queue(self):
        # Drain already submitted final stops; never wait for HTTP on a Kodi callback.
        with self._playback_action_lock:
            executor = self._scrobble_executor
            self._scrobble_executor = None
        if executor is not None:
            executor.shutdown(wait=False)

    def release_playback(self, current_item_changed=False):
        try:
            with self._playback_action_lock:
                self._release_playback_locked(current_item_changed)
        finally:
            self._close_scrobble_queue()

    def _release_playback_locked(self, current_item_changed=False):
        self._cancel_pending_scrobble_start()
        self._cancel_pending_subtitles()
        self._cancel_seek_scrobble()
        owns_playback = self.owns_playback()
        # A superseded invoker must not clear the new owner's state/triggers.
        if owns_playback:
            win = xbmcgui.Window(10000)
            if self.scrobbling_in_progress:
                mid = self.media_id
                mtype = self.media_type
                with self._progress_sample_lock:
                    progress = self.last_known_progress
                    progress_known = self._progress_known
                if progress == 0.0 and not progress_known and not current_item_changed and self.isPlaying():
                    try:
                        total = self.getTotalTime()
                        if total > 0:
                            progress = max(0.0, min(100.0, self.getTime() / total * 100.0))
                    except Exception:
                        pass

                if mid or (self.current_meta and self.current_meta.get("tmdb_id")):
                    meta_copy = dict(self.current_meta) if self.current_meta else None
                    try:
                        self._queue_scrobble("stop", mid, mtype, progress, meta_copy)
                    except Exception as e:
                        log(f"TRAKT - Failed to stop scrobble while releasing playback: {e}", xbmc.LOGWARNING)
            win.clearProperty("play_er.seamless_switching")
            if current_item_changed and win.getProperty(EXPECTED_OWNER) == self._playback_owner:
                for key in ('play_er.current_meta', 'play_er.current_meta_uuid',
                            'play_er.current_media_type', 'play_er.current_trakt_id',
                            'play_er.current_stream_qualities', EXPECTED_URL, EXPECTED_OWNER):
                    win.clearProperty(key)
            win.clearProperty('play_er.monitor_owner')
        self._playback_owner = None
        self._playback_confirmed = False
        self._last_owned_meta = None
        with self.progress_lock:
            for timer in (self.progress_update_timer, self.downgrade_timer):
                if timer:
                    timer.cancel()
            self.progress_update_timer = None
            self._progress_timer_revision += 1
            self._progress_recheck_on_resume = False
            self.downgrade_timer = None
            self._downgrade_generation += 1
        self.scrobbling_in_progress = False
        self.current_meta = None
        self._reset_progress()

    # FIX PRE-EMPTIVE AND FILTERS [SEEK PROGRESS WITHOUT FALSE HISTORY ENTRIES]
    def _cancel_seek_scrobble(self):
        self._seek_generation = getattr(self, '_seek_generation', 0) + 1
        timer = getattr(self, 'seek_scrobble_timer', None)
        if timer:
            timer.cancel()
        self.seek_scrobble_timer = None

    def _cancel_pending_scrobble_start(self):
        timer = self.scrobble_start_timer
        if timer:
            timer.cancel()
        self.scrobble_start_timer = None

    def _cancel_pending_subtitles(self):
        timer = self.subtitle_timer
        if timer:
            timer.cancel()
        self.subtitle_timer = None

    def onPlayBackSeek(self, time, seekOffset):
        if not self.owns_playback():
            return
        with self._progress_sample_lock:
            self._progress_seek_revision += 1
        paused = xbmc.getCondVisibility('Player.Paused')
        total = 0
        try:
            total = self.getTotalTime()
            if total > 0:
                # Kodi's callback position is milliseconds; getTotalTime is seconds.
                self._set_seek_progress(float(time) / 1000.0, total, paused)
        except Exception as e:
            total = 0
            log(f'TRAKT - Seek callback failed: {e}', xbmc.LOGWARNING)
        # A seek can jump across the entire credits window between the normal
        # 15-second ticks. Check local features promptly, independently of Trakt.
        with self.progress_lock:
            if self.progress_update_timer:
                self.progress_update_timer.cancel()
            if not paused:
                self._progress_recheck_on_resume = False
                self._schedule_progress_update_locked(0.25, self._playback_item_generation)
            else:
                self.progress_update_timer = None
                self._progress_timer_revision += 1
                self._progress_recheck_on_resume = True
        if total <= 0 or not self.scrobbling_in_progress or self.addon.getSetting('enable_trakt_scrobbling') != 'true':
            return
        try:
            self._cancel_seek_scrobble()
            generation = self._seek_generation
            item_generation = self._playback_item_generation
            started_at = self._last_av_started_at
            meta = dict(self.current_meta or {})
            media_id, media_type = self.media_id, self.media_type

            def sync_seek():
                if (
                    not self.owns_playback() or not self.scrobbling_in_progress
                    or generation != self._seek_generation
                    or started_at != self._last_av_started_at
                    or meta != self.current_meta
                ):
                    return
                try:
                    duration = self.getTotalTime()
                    if duration <= 0:
                        return
                    paused = xbmc.getCondVisibility('Player.Paused')
                    progress, _ = self._sample_progress(self.getTime(), duration, paused)
                    action = 'pause' if paused else 'start'
                    self._queue_scrobble(action, media_id, media_type, progress, meta, item_generation)
                except Exception as e:
                    log(f'TRAKT - Seek progress sync failed: {e}', xbmc.LOGWARNING)

            self.seek_scrobble_timer = threading.Timer(1.0, sync_seek)
            self.seek_scrobble_timer.start()
        except Exception as e:
            log(f'TRAKT - Seek callback failed: {e}', xbmc.LOGWARNING)

    def _update_progress(self, generation=None, timer_revision=None):
        if not self.owns_playback():
            return
        pending_actions = []
        with self.progress_lock:
            if generation is None:
                generation = self._playback_item_generation
            if (generation != self._playback_item_generation
                    or (timer_revision is not None and timer_revision != self._progress_timer_revision)):
                return
            active_timer = self.progress_update_timer
            if not self.isPlaying():
                return
            with self._progress_sample_lock:
                seek_revision = self._progress_seek_revision
            owner = self._playback_owner
            try:
                current_time = self.getTime()
                total_time = self.getTotalTime()
                if total_time > 0:
                    _, settled = self._sample_progress(current_time, total_time)
                    if not settled:
                        self._schedule_progress_update_locked(1, generation)
                        return
                    if seek_revision != self._progress_seek_revision:
                        return
                    remaining = total_time - current_time

                    if self.addon.getSettingBool("enable_pre_emptive_scrape"):
                        try:
                            play_key = self.play_key
                            if not play_key and self.current_meta and self.orchestrator:
                                play_key = self.orchestrator.get_play_key(self.current_meta)
                                self.play_key = play_key
                            if play_key and not self.orchestrator.has_triggered(play_key, 'preemptive') and (self.last_known_progress > 80 or remaining < 300):
                                self.orchestrator.set_triggered(play_key, 'preemptive')
                                pending_actions.append((self._trigger_pre_emptive_scrape, play_key, 'preemptive'))
                        except Exception:
                            pass

                    if self.addon.getSettingBool("enable_skip_credits"):
                        trigger_time = get_setting_int_with_bounds(self.addon, "skip_credits_trigger", 120, 10, 600)
                        try:
                            play_key = self.play_key
                            if not play_key and self.current_meta and self.orchestrator:
                                play_key = self.orchestrator.get_play_key(self.current_meta)
                                self.play_key = play_key
                            if play_key and not self.orchestrator.has_triggered(play_key, 'skip_credits') and 0 < remaining <= trigger_time:
                                self.orchestrator.set_triggered(play_key, 'skip_credits')
                                pending_actions.append((self._trigger_skip_credits, play_key, 'skip_credits'))
                        except Exception:
                            pass
            except Exception:
                pass

        def is_current():
            return (generation == self._playback_item_generation
                    and seek_revision == self._progress_seek_revision
                    and owner == self._playback_owner and self.owns_playback()
                    and self.isPlayingVideo())

        def rearm_after_seek(actions):
            # The flags prevent overlapping ticks while an action is running.
            # Only the same owner and item may clear flags after a seek.
            with self.progress_lock:
                if (generation != self._playback_item_generation or owner != self._playback_owner
                        or not self.owns_playback() or seek_revision == self._progress_seek_revision):
                    return
                for _, play_key, trigger in actions:
                    self.orchestrator.clear_trigger(play_key, trigger)
                if actions and self.isPlayingVideo() and not xbmc.getCondVisibility('Player.Paused'):
                    if self.progress_update_timer:
                        self.progress_update_timer.cancel()
                    self._schedule_progress_update_locked(0.25, generation)

        # Metadata lookup and modal dialogs must not block Stop/Pause cleanup.
        for index, (action, play_key, trigger) in enumerate(pending_actions):
            if not is_current():
                rearm_after_seek(pending_actions[index:])
                return
            try:
                completed = action(is_current)
                if completed is False:
                    rearm_after_seek([(action, play_key, trigger)])
            except Exception as e:
                log(f"PLAYBACK - Progress action failed: {e}", xbmc.LOGWARNING)
                if not is_current():
                    rearm_after_seek([(action, play_key, trigger)])

        with self.progress_lock:
            if (generation != self._playback_item_generation or not self.owns_playback()
                    or (timer_revision is not None and timer_revision != self._progress_timer_revision)
                    or self.progress_update_timer is not active_timer or not self.isPlaying()):
                return
            self._schedule_progress_update_locked(15, generation)

    def _schedule_downgrade_check(self, generation):
        with self.progress_lock:
            if generation != self._downgrade_generation or not self.owns_playback():
                return
            timer = threading.Timer(
                2.0,
                self._check_buffering_and_downgrade,
                args=(generation,),
            )
            self.downgrade_timer = timer
            timer.start()

    def _start_downgrade_check(self, expected_generation=None):
        with self.progress_lock:
            if (
                expected_generation is not None
                and expected_generation != self._downgrade_generation
            ):
                return
            if not self.owns_playback() or not self.isPlayingVideo():
                return
            if self.downgrade_timer:
                self.downgrade_timer.cancel()
            self._downgrade_generation += 1
            self.is_buffering_since = 0
            timer = threading.Timer(
                2.0,
                self._check_buffering_and_downgrade,
                args=(self._downgrade_generation,),
            )
            self.downgrade_timer = timer
            timer.start()

    def _check_buffering_and_downgrade(self, generation=None):
        try:
            self._run_downgrade_check(generation)
        except RuntimeError as e:
            log(f"AUTO-DOWNGRADE - Playback changed during check: {e}", xbmc.LOGDEBUG)

    def _run_downgrade_check(self, generation=None):
        if not self.owns_playback():
            return
        with self.progress_lock:
            if generation is None:
                generation = self._downgrade_generation
            elif generation != self._downgrade_generation:
                return
        if not self.isPlayingVideo():
            return

        try:
            enable_downgrade = self.addon.getSettingBool("enable_auto_downgrade")
            tolerance = int(self.addon.getSetting("downgrade_tolerance") or "5")
        except Exception:
            enable_downgrade = False
            tolerance = 5

        if not enable_downgrade:
            self._schedule_downgrade_check(generation)
            return

        is_caching = xbmc.getCondVisibility('Player.Caching')
        if is_caching:
            if self.is_buffering_since == 0:
                self.is_buffering_since = time.time()
            buffering_duration = time.time() - self.is_buffering_since

            if buffering_duration >= tolerance:
                log("AUTO-DOWNGRADE - Tolerance bufferu překročena! Snižuji kvalitu...", xbmc.LOGINFO)
                self.is_buffering_since = 0

                win = xbmcgui.Window(10000)
                playing_item = self.getPlayingItem()
                current_link = playing_item.getProperty("play_er.link")

                playing_file = self.getPlayingFile().split('|')[0]
                playing_base = playing_file.split('?')[0]

                streams = get_streams(playing_item)
                if not streams:
                    return

                sorted_streams = []
                for k, v in streams.items():
                    if "ORIGINAL" in k.upper():
                        sorted_streams.append((9999, v, k))
                    else:
                        nums = re.findall(r'\d+', k)
                        if nums:
                            sorted_streams.append((int(nums[0]), v, k))
                        else:
                            sorted_streams.append((0, v, k))

                sorted_streams = sorted(sorted_streams, key=lambda x: x[0], reverse=True)
                next_url = None
                next_label = None
                found_current = False

                for q_val, s_url, s_label in sorted_streams:
                    clean_s_url = s_url.split('|')[0]
                    s_url_base = clean_s_url.split('?')[0]

                    if playing_base == s_url_base or playing_base in s_url_base or s_url_base in playing_base:
                        found_current = True
                        continue

                    if found_current:
                        next_url = s_url
                        next_label = s_label
                        break

                if next_url or (not found_current and sorted_streams):
                    if not next_url:
                        next_url = sorted_streams[-1][1]
                        next_label = sorted_streams[-1][2]
                        clean_s_url = next_url.split('|')[0]
                        s_url_base = clean_s_url.split('?')[0]
                        if playing_base == s_url_base or playing_base in s_url_base or s_url_base in playing_base:
                            return

                    notify_info(f"Pomalá síť: Přepínám na {next_label}", category="STREAM", time=5000)

                    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
                    referer = "https://prehraj.to/"
                    accept = "video/mp4,video/*,*/*"
                    clean_next_url = next_url.split('|')[0]
                    final_url = "{0}|User-Agent={1}&Referer={2}&Accept={3}".format(clean_next_url, quote(ua), quote(referer), quote(accept))

                    title = self.current_meta.get('title', '') if self.current_meta else ''
                    li = xbmcgui.ListItem(title, path=final_url)
                    li.setContentLookup(False)
                    current_time = self.getTime()
                    li.setProperty('StartOffset', str(current_time))

                    if self.current_meta and self.tmdb_client:
                        try:
                            self.tmdb_client.fill_list_item(li, self.current_meta, self.current_meta.get('media_type', 'movie'))
                        except Exception:
                            pass

                    li.setProperty('play_er.meta_id', playing_item.getProperty('play_er.meta_id'))
                    li.setProperty('play_er.link', playing_item.getProperty('play_er.link'))
                    li.setProperty('play_er.media_type', playing_item.getProperty('play_er.media_type'))
                    li.setProperty('play_er.trakt_id', playing_item.getProperty('play_er.trakt_id'))

                    attach_subtitles(li, current_link)

                    with self._playback_action_lock:
                        if generation != self._downgrade_generation or not self.owns_playback() or not self.isPlayingVideo():
                            return
                        if self.getPlayingItem().getProperty("play_er.link") != current_link:
                            return
                        win.setProperty("play_er.seamless_switching", "true")
                        switch_count = int(win.getProperty("play_er.switch_count") or "0")
                        win.setProperty("play_er.switch_count", str(switch_count + 1))
                        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                        pos = playlist.getposition()

                        try:
                            if pos >= 0:
                                playlist.add(url=final_url, listitem=li, index=pos + 1)
                                xbmc.executebuiltin("PlayerControl(Next)")
                            else:
                                playlist.add(url=final_url, listitem=li)
                                self.play(playlist, windowed=False, startpos=max(0, playlist.size() - 1))
                        except Exception:
                            win.clearProperty("play_er.seamless_switching")
                            raise

                    for _ in range(50):
                        with self._playback_action_lock:
                            if generation != self._downgrade_generation or not self.owns_playback():
                                return
                            if self.isPlayingVideo():
                                if self.getTime() < 5.0 and current_time > 10.0:
                                    self.seekTime(current_time)
                                break
                        xbmc.sleep(100)
        else:
            self.is_buffering_since = 0

        self._schedule_downgrade_check(generation)

    def _trigger_pre_emptive_scrape(self, is_current=None):
        if not self.current_meta or self.current_meta.get("media_type") != "episode":
            return True
        try:
            generation = self._playback_item_generation
            seek_revision = self._progress_seek_revision
            is_current = is_current or (lambda: generation == self._playback_item_generation
                                        and seek_revision == self._progress_seek_revision
                                        and self.owns_playback() and self.isPlayingVideo())
            if not is_current():
                return False
            meta = dict(self.current_meta)
            tmdb_id = meta.get("tmdb_id")
            current_season = int(meta.get("season", 1))
            current_episode = int(meta.get("episode", 0))

            if self.orchestrator:
                should, _ = self.orchestrator.should_trigger_preemptive(meta, self.tmdb_client, self.addon)
                if not is_current():
                    return False
                if not should:
                    return True

            # FIX PRE-EMPTIVE AND FILTERS [SEARCH BEYOND QUEUED EPISODES]
            # Původní cíl current_episode + 1 znovu hledal zdroj, který už mohl být ve frontě:
            # next_ep_meta["episode"] = current_episode + 1
            from resources.lib.generator import get_preemptive_episode_target
            target = get_preemptive_episode_target(meta, self.tmdb_client)
            if not is_current():
                return False
            if not target:
                return True
            next_ep_meta = meta.copy()
            next_ep_meta["season"], next_ep_meta["episode"] = target
            url = get_url(action="pre_emptive_search", meta=json.dumps(next_ep_meta))
            if not is_current():
                return False
            xbmc.executebuiltin(f"RunPlugin({url})")
            if self.orchestrator:
                self.orchestrator.record_preemptive(tmdb_id, current_season)
            return True
        except Exception:
            return bool(is_current()) if is_current else True

    def _trigger_skip_credits(self, is_current=None):
        if not self.current_meta or self.current_meta.get("media_type") != "episode":
            return True
        try:
            if self.orchestrator:
                generation = self._playback_item_generation
                seek_revision = self._progress_seek_revision
                is_current = is_current or (lambda: generation == self._playback_item_generation
                                            and seek_revision == self._progress_seek_revision
                                            and self.owns_playback() and self.isPlayingVideo())
                if not is_current():
                    return False
                meta = dict(self.current_meta)
                action, reason = self.orchestrator.handle_skip_credits(
                    meta, self.tmdb_client, self.addon, is_current=is_current,
                )
                log(f"SKIP CREDITS - RESULT: {action}; REASON: {reason}; "
                    f"S{meta.get('season')}E{meta.get('episode')}", xbmc.LOGINFO)
                return reason != 'playback_changed' and (action in ('next', 'runplugin') or is_current())
        except Exception:
            return bool(is_current()) if is_current else True
        return True

    def _legacy_episode_matches_playlist(self, key, record):
        """Recognize pre-update queue records only in the active series playlist."""
        previous = self._last_owned_meta or {}
        meta = record.get('meta') or {}
        show_id = previous.get('tmdb_id')
        if (not self._playback_confirmed or previous.get('media_type') != 'episode'
                or meta.get('media_type') != 'episode' or not show_id
                or str(meta.get('tmdb_id')) != str(show_id)):
            return False, False
        try:
            position = xbmc.PlayList(xbmc.PLAYLIST_VIDEO).getposition()
            request = json.dumps({'jsonrpc': '2.0', 'method': 'Playlist.GetItems',
                                  'params': {'playlistid': 1, 'properties': ['file']}, 'id': 1})
            response = json.loads(xbmc.executeJSONRPC(request) or '{}')
            items = response.get('result', {}).get('items', [])
            if isinstance(position, int) and 0 <= position < len(items):
                return stream_key(items[position].get('file', '')) == key, True
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass
        # A Kodi callback can precede the playlist position update. Wait for a
        # later callback instead of treating a plausible legacy item as foreign.
        return False, True

    def _identify_playback(self, playing_item, win):
        """Identify this owner's item without trusting stale global metadata."""
        paths = []
        try:
            paths.append(self.getPlayingFile())
        except Exception:
            pass
        try:
            paths.append(playing_item.getPath())
        except Exception:
            pass
        keys = {stream_key(path) for path in paths} - {''}
        try:
            records = json.loads(win.getProperty('play_er.episode_queue_metadata') or '{}')
        except (TypeError, ValueError):
            records = {}
        queue_record = None
        legacy_pending = False
        if isinstance(records, dict):
            for key in keys:
                candidate = records.get(key)
                if not (isinstance(candidate, dict) and isinstance(candidate.get('meta'), dict)
                        and candidate['meta']):
                    continue
                if candidate.get('owner') == self._playback_owner:
                    queue_record = candidate
                    break
                if 'owner' not in candidate:
                    matched, related = self._legacy_episode_matches_playlist(key, candidate)
                    legacy_pending = legacy_pending or related
                    if matched:
                        queue_record = candidate
                        break
        item_meta = playing_item.getProperty('play_er.meta_id')
        item_link = playing_item.getProperty('play_er.link')
        item_type = playing_item.getProperty('play_er.media_type')
        if queue_record and ((item_meta and item_meta != queue_record.get('meta_id', ''))
                             or (item_link and item_link != queue_record.get('link', ''))):
            queue_record = None
        expected = (win.getProperty(EXPECTED_OWNER) == self._playback_owner
                    and win.getProperty(EXPECTED_URL) in keys)
        def is_own_plugin(path):
            if not isinstance(path, str):
                return False
            try:
                parsed = urlparse(path)
                return parsed.scheme == 'plugin' and parsed.netloc == 'plugin.video.play_er'
            except ValueError:
                return False

        plugin_item = any(is_own_plugin(path) for path in paths)
        switched = False
        if win.getProperty('play_er.seamless_switching') == 'true' and self._playback_confirmed:
            try:
                switched = any(stream_key(url) in keys for url in get_streams(playing_item).values())
            except Exception:
                pass
        owned = bool(item_meta or item_link or item_type or queue_record or expected or plugin_item or switched)
        return owned, queue_record, bool(keys) and not legacy_pending

    # FIX PRE-EMPTIVE AND FILTERS [HANDLE PLAYLIST AV CHANGE]
    def onAVChange(self):
        """Handle playlist item transitions, which Kodi can report via onAVChange."""
        if not self.owns_playback():
            return
        try:
            if not self.isPlayingVideo():
                return

            playing_item = self.getPlayingItem()
            win = xbmcgui.Window(10000)
            owned, queue_record, identifiable = self._identify_playback(playing_item, win)
            if not owned:
                if identifiable and self._playback_confirmed:
                    self.release_playback(current_item_changed=True)
                return
            candidate_meta = {}
            meta_id = playing_item.getProperty("play_er.meta_id")
            if meta_id:
                try:
                    from resources.lib.utils import get_meta_from_cache
                    candidate_meta = get_meta_from_cache(meta_id)
                except Exception:
                    candidate_meta = {}

            if not candidate_meta and queue_record:
                candidate_meta = queue_record.get("meta", {})

            if not candidate_meta or candidate_meta.get("media_type") != "episode":
                return

            candidate_key = (
                f"{candidate_meta.get('tmdb_id')}:"
                f"{candidate_meta.get('season')}:"
                f"{candidate_meta.get('episode')}"
            )
            active_key = ""
            if self.current_meta:
                active_key = (
                    f"{self.current_meta.get('tmdb_id')}:"
                    f"{self.current_meta.get('season')}:"
                    f"{self.current_meta.get('episode')}"
                )
            if candidate_key == active_key:
                return

            log(
                f"TRAKT - Playlist item transition via onAVChange: "
                f"S{candidate_meta.get('season', 0)}E{candidate_meta.get('episode', 0)}",
                xbmc.LOGWARNING
            )
            self.onAVStarted()
        except Exception as e:
            log(f"TRAKT onAVChange error: {e}", xbmc.LOGWARNING)


    def onAVStarted(self):
        if not self.owns_playback():
            return
        with self.progress_lock:
            start_generation = self._downgrade_generation
        previous_meta = dict(self.current_meta) if self.current_meta else None
        with self._progress_sample_lock:
            previous_progress = self.last_known_progress
        try:
            playing_item = self.getPlayingItem()
            win = xbmcgui.Window(10000)
            owned, queue_record, identifiable = self._identify_playback(playing_item, win)
            if not owned:
                if identifiable and self._playback_confirmed:
                    self.release_playback(current_item_changed=True)
                return
            self._playback_confirmed = True
            try:
                expect_stream(win, self.getPlayingFile())
            except Exception:
                pass
            # Consume only a verified switch so an unrelated item cannot inherit it.
            is_seamless = win.getProperty("play_er.seamless_switching") == "true"
            if is_seamless:
                win.clearProperty("play_er.seamless_switching")

            item_meta_id = playing_item.getProperty('play_er.meta_id')
            item_trakt_id = playing_item.getProperty('play_er.trakt_id')
            if queue_record:
                # Direct playlist URLs may omit ListItem properties; use the record for this URL.
                new_trakt_id = item_trakt_id or queue_record.get("trakt_id", "")
                meta_uuid = item_meta_id or queue_record.get("meta_id", "")
                new_media_type = playing_item.getProperty('play_er.media_type') or queue_record.get("media_type", "episode")
                link_history = playing_item.getProperty('play_er.link') or queue_record.get("link", "")
                metadata_source = "queue-url"
            else:
                new_trakt_id = item_trakt_id or win.getProperty("play_er.current_trakt_id")
                meta_uuid = item_meta_id or win.getProperty("play_er.current_meta_uuid")
                new_media_type = playing_item.getProperty('play_er.media_type') or win.getProperty("play_er.current_media_type")
                link_history = playing_item.getProperty('play_er.link')
                metadata_source = "item-properties" if (item_meta_id or item_trakt_id) else "window-fallback"
            source_list = playing_item.getProperty('play_er.source_list')
            publish_active_streams(link_history or playing_item)

            queued_meta = queue_record.get("meta") if queue_record else None
            if isinstance(queued_meta, dict) and queued_meta:
                self.current_meta = queued_meta
            elif meta_uuid:
                from resources.lib.utils import get_meta_from_cache
                self.current_meta = get_meta_from_cache(meta_uuid)
            elif win.getProperty("play_er.current_meta"):
                try:
                    self.current_meta = json.loads(win.getProperty("play_er.current_meta"))
                except Exception:
                    self.current_meta = {}
            else:
                self.current_meta = {}

            if not new_media_type and self.current_meta:
                new_media_type = self.current_meta.get("media_type", "movie")

            if self.current_meta:
                self._last_owned_meta = dict(self.current_meta)
                # Keep global fallback properties in sync as Kodi advances playlist items.
                win.setProperty("play_er.current_meta", json.dumps(self.current_meta, ensure_ascii=False))
                win.setProperty("play_er.current_meta_uuid", str(meta_uuid or ""))
                win.setProperty("play_er.current_media_type", str(new_media_type or self.current_meta.get("media_type", "")))
                win.setProperty("play_er.current_trakt_id", str(new_trakt_id or ""))
                try:
                    info_title = playing_item.getVideoInfoTag().getTitle()
                except Exception:
                    info_title = ""
                has_artwork = bool(
                    playing_item.getProperty("poster")
                    or playing_item.getProperty("thumb")
                    or playing_item.getProperty("fanart")
                )
                log(
                    f"TRAKT - PLAYBACK METADATA : source={metadata_source}, "
                    f"S{self.current_meta.get('season', 0)}E{self.current_meta.get('episode', 0)}, "
                    f"trakt_id={'yes' if new_trakt_id else 'lookup'}, "
                    f"item_title={'yes' if info_title else 'no'}, art={'yes' if has_artwork else 'no'}",
                    xbmc.LOGWARNING
                )

                # Kodi can call onAVChange and onAVStarted for the same item. Process
                # an episode only once, so scrobbling/history timers are not restarted.
                episode_key = (
                    f"{self.current_meta.get('tmdb_id')}:"
                    f"{self.current_meta.get('season')}:"
                    f"{self.current_meta.get('episode')}"
                ) if self.current_meta.get("media_type") == "episode" else ""
                now = time.monotonic()
                if (
                    episode_key
                    and episode_key == self._last_av_started_key
                    and now - self._last_av_started_at < 5.0
                ):
                    return
                if episode_key:
                    self._last_av_started_key = episode_key
                    self._last_av_started_at = now

                # A plugin-resolved URL can have correct ListItem tags while Kodi's
                # active-player tag remains the TMDBHelper placeholder. Push the
                # resolved ListItem tags onto the active player for remote clients.
                if metadata_source != "window-fallback":
                    try:
                        self.updateInfoTag(playing_item)
                    except Exception as e:
                        log(f"TRAKT - Nepodařilo se aktualizovat InfoTag přehrávané položky: {e}", xbmc.LOGWARNING)

            # The duplicate callback returns above, preserving the active start
            # timer; a genuine item transition cancels the previous pending one.
            had_pending_start = self.scrobble_start_timer is not None
            with self._playback_action_lock:
                self._cancel_pending_scrobble_start()
                self._cancel_pending_subtitles()
                self._playback_item_generation += 1
                self._reset_progress()
                with self.progress_lock:
                    self._downgrade_generation += 1
                    start_generation = self._downgrade_generation
                    if self.downgrade_timer:
                        self.downgrade_timer.cancel()
                        self.downgrade_timer = None

            # On-the-fly Trakt ID fallback záchrana, pokud ID nebylo získáno dříve
            tmdb_id = self.current_meta.get("tmdb_id")
            scrobbling_enabled = get_setting_bool(self.addon, "enable_trakt_scrobbling")
            if scrobbling_enabled and (not new_trakt_id or str(new_trakt_id) in ("0", "")) and tmdb_id:
                try:
                    m_type_test = "episode" if "episode" in str(new_media_type).lower() else "movie"
                    if m_type_test == "episode":
                        new_trakt_id = get_trakt_episode_id(tmdb_id, self.current_meta.get("season"), self.current_meta.get("episode"), self.session, self.addon)
                    else:
                        new_trakt_id = get_trakt_id(tmdb_id, "movie", self.session, self.addon)
                    if new_trakt_id:
                        win.setProperty("play_er.current_trakt_id", str(new_trakt_id))
                except Exception as e:
                    log(f"TRAKT onAVStarted on-the-fly lookup error: {e}", xbmc.LOGWARNING)

            if self.addon.getSettingBool("auto_subtitles"):
                has_dubbing = playing_item.getProperty('play_er.has_dubbing')
                if has_dubbing == 'false':
                    item_generation = self._playback_item_generation
                    item_meta = dict(self.current_meta or {})

                    def _enable_subs():
                        if (
                            item_generation == self._playback_item_generation
                            and self.owns_playback()
                            and item_meta == self.current_meta
                            and self.isPlayingVideo()
                        ):
                            try:
                                self.showSubtitles(True)
                            except Exception:
                                pass
                    self.subtitle_timer = threading.Timer(2.0, _enable_subs)
                    self.subtitle_timer.start()

            self.pre_emptive_triggered = False
            self.skip_credits_triggered = False
            try:
                self.play_key = self.orchestrator.get_play_key(self.current_meta) if self.orchestrator else None
            except Exception:
                self.play_key = None

            if source_list == 'watch_later' and self.remove_from_watch_later_func:
                if self.current_meta.get('tmdb_id'):
                    remove_params = {
                        'tmdb_id': self.current_meta.get('tmdb_id'),
                        'media_type': self.current_meta.get('media_type')
                    }
                    if remove_params['media_type'] == 'episode':
                        remove_params['season'] = self.current_meta.get('season')
                        remove_params['episode'] = self.current_meta.get('episode')
                    threading.Thread(target=self.remove_from_watch_later_func, args=(remove_params,)).start()

            if self.current_meta and self.save_playback_history_func:
                final_link = link_history if link_history else self.getPlayingFile().split('|')[0]
                try:
                    self.save_playback_history_func(self.current_meta, final_link, skip_refresh=True)
                except cache_manager.CacheStorageError as e:
                    log(f"PLAYBACK - History not saved: {e}", xbmc.LOGWARNING)

            # The verified queue record also identifies a managed episode when
            # Kodi omits the current ListItem's custom properties.
            queue_managed = playing_item.getProperty("play_er.queue_managed")
            propertyless_queue_item = not queue_managed and bool(queue_record)
            if (
                self.current_meta
                and self.current_meta.get("media_type") == "episode"
                and (queue_managed == "true" or propertyless_queue_item)
                and self.current_meta.get('_play_er_queue_remaining') != 0
            ):
                queue_refill_key = (
                    f"{self.current_meta.get('tmdb_id')}:"
                    f"{self.current_meta.get('season')}:"
                    f"{self.current_meta.get('episode')}"
                )
                if win.getProperty("play_er.queue_refill_requested") != queue_refill_key:
                    win.setProperty("play_er.queue_refill_requested", queue_refill_key)
                    refill_params = {"action": "refill_episode_queue", "meta": json.dumps(self.current_meta)}
                    if propertyless_queue_item:
                        refill_params["verify_future"] = "true"
                    refill_url = get_url(**refill_params)
                    xbmc.executebuiltin(f"RunPlugin({refill_url})")

            if scrobbling_enabled and (new_trakt_id or tmdb_id):
                identity_fields = ("media_type", "tmdb_id", "season", "episode")
                item_changed = any((previous_meta or {}).get(key) != self.current_meta.get(key)
                                   for key in identity_fields)
                if self.scrobbling_in_progress and (str(self.media_id) != str(new_trakt_id) or item_changed):
                    self._queue_scrobble("stop", self.media_id, self.media_type, previous_progress, previous_meta)

                need_start = had_pending_start or not (is_seamless and str(self.media_id) == str(new_trakt_id))
                self.media_id = new_trakt_id
                self.media_type = "episode" if "episode" in str(new_media_type).lower() else "movie"
                self.scrobbling_in_progress = True

                if need_start:
                    # FIX PRE-EMPTIVE AND FILTERS [NO DELAYED START FOR OLD EPISODE]
                    start_meta = dict(self.current_meta)
                    start_id, start_type = self.media_id, self.media_type
                    scrobble_generation = self._playback_item_generation
                    start_at = self._last_av_started_at
                    def delayed_start():
                        try:
                            # Original timer read mutable IDs after another episode started:
                            # trakt_scrobble_start(self.media_id, self.media_type, 0.0,
                            #     self.addon, self.session, meta=self.current_meta)
                            if (
                                self.owns_playback() and self.scrobbling_in_progress
                                and self._last_av_started_at == start_at
                                and self.current_meta == start_meta
                            ):
                                # FIX PRE-EMPTIVE AND FILTERS [RESUME/SEEK BEFORE START TIMER]
                                # trakt_scrobble_start(start_id, start_type, 0.0, ...)
                                duration = self.getTotalTime()
                                if duration > 0:
                                    paused = xbmc.getCondVisibility('Player.Paused')
                                    progress, _ = self._sample_progress(self.getTime(), duration, paused)
                                else:
                                    paused = xbmc.getCondVisibility('Player.Paused')
                                    progress = 0.0
                                action = 'pause' if paused else 'start'
                                self._queue_scrobble(action, start_id, start_type, progress, start_meta, scrobble_generation)
                        except Exception as ex:
                            log(f"TRAKT delayed_start error: {ex}", xbmc.LOGWARNING)
                    self.scrobble_start_timer = threading.Timer(2.0, delayed_start)
                    self.scrobble_start_timer.start()

            else:
                # A previously started Trakt stream must be closed even if the
                # user disabled scrobbling before the next item began.
                if self.scrobbling_in_progress and (
                    self.media_id or (previous_meta and previous_meta.get("tmdb_id"))
                ):
                    self._queue_scrobble("stop", self.media_id, self.media_type, previous_progress, previous_meta)
                self.scrobbling_in_progress = False

            # Local playback features have their own settings and also work
            # without a Trakt account or a catalog identifier.
            self._start_downgrade_check(expected_generation=start_generation)
            try:
                if self.orchestrator and self.play_key:
                    self.orchestrator.set_state(self.play_key, 'PLAYING')
            except Exception:
                pass
            with self.progress_lock:
                if self.progress_update_timer:
                    self.progress_update_timer.cancel()
                self._progress_recheck_on_resume = False
                self._schedule_progress_update_locked(5, self._playback_item_generation)
        except Exception as e:
            log(f"TRAKT onAVStarted error: {e}", xbmc.LOGERROR)
            self.scrobbling_in_progress = False

    def onPlayBackPaused(self):
        if not self.owns_playback():
            return
        self._cancel_seek_scrobble()
        with self.progress_lock:
            if self.progress_update_timer:
                self.progress_update_timer.cancel()
                self.progress_update_timer = None
            self._progress_timer_revision += 1
        try:
            progress = self.last_known_progress
            if self.isPlaying():
                current_time = self.getTime()
                total_time = self.getTotalTime()
                if total_time > 0:
                    progress, _ = self._sample_progress(current_time, total_time, paused=True)
            if self.scrobbling_in_progress:
                self._queue_scrobble("pause", self.media_id, self.media_type, progress, self.current_meta)
        except Exception:
            pass

    def onPlayBackResumed(self):
        if not self.owns_playback():
            return
        self._resume_pending_seek()
        self._cancel_seek_scrobble()
        with self.progress_lock:
            if not self.progress_update_timer:
                delay = 0.25 if self._progress_recheck_on_resume else 15
                self._progress_recheck_on_resume = False
                self._schedule_progress_update_locked(delay, self._playback_item_generation)
        if not self.scrobbling_in_progress or self.addon.getSetting("enable_trakt_scrobbling") != "true":
            return
        try:
            progress = self.last_known_progress
            if self.isPlaying():
                current_time = self.getTime()
                total_time = self.getTotalTime()
                if total_time > 0:
                    progress, _ = self._sample_progress(current_time, total_time)
            self._queue_scrobble("start", self.media_id, self.media_type, progress, self.current_meta)
        except Exception:
            pass

    def onPlayBackStopped(self):
        with self._playback_action_lock:
            self._onPlayBackStopped_locked()

    def _onPlayBackStopped_locked(self):
        if not self.owns_playback():
            return
        win = xbmcgui.Window(10000)
        if win.getProperty("play_er.seamless_switching") == "true":
            return

        try:
            from resources.lib.utils_prediction_handoff import cancel_handoff
            cancel_handoff(self.current_meta or {})
        except Exception:
            pass

        mid = self.media_id
        mtype = self.media_type
        with self._progress_sample_lock:
            prog = self.last_known_progress
            progress_known = self._progress_known
        if prog == 0.0 and not progress_known:
            try:
                prog = (self.getTime() / self.getTotalTime() * 100)
            except Exception:
                prog = 0.0

        try:
            if prog >= 90.0 and self.mark_watched_func and self.current_meta:
                self.mark_watched_func(self.current_meta)
        except Exception:
            pass

        if self.scrobbling_in_progress and (mid or (self.current_meta and self.current_meta.get("tmdb_id"))):
            meta_copy = dict(self.current_meta) if self.current_meta else None
            self._queue_scrobble("stop", mid, mtype, prog, meta_copy)

        if win.getProperty("player.needs_refresh_on_stop") == "true":
            win.clearProperty("player.needs_refresh_on_stop")
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass

        self._cleanup_monitor()

    def onPlayBackError(self):
        """Stop Trakt scrobbling when Kodi terminates playback with an error."""
        if not self.owns_playback():
            return

        # A stop callback during a quality switch is intentionally ignored. An
        # error means playback really ended, so clear that marker before using
        # the regular stop path to report the final progress and clean up.
        xbmcgui.Window(10000).clearProperty("play_er.seamless_switching")
        self.onPlayBackStopped()

    def onPlayBackEnded(self):
        with self._playback_action_lock:
            self._onPlayBackEnded_locked()

    def _onPlayBackEnded_locked(self):
        if not self.owns_playback():
            return
        ended_meta = dict(self.current_meta or {})
        mid = self.media_id
        mtype = self.media_type

        try:
            if self.mark_watched_func and self.current_meta:
                self.mark_watched_func(self.current_meta)
        except Exception:
            pass

        if self.scrobbling_in_progress and (mid or (self.current_meta and self.current_meta.get("tmdb_id"))):
            meta_copy = dict(self.current_meta) if self.current_meta else None
            self._queue_scrobble("stop", mid, mtype, 100.0, meta_copy)

        win = xbmcgui.Window(10000)
        if win.getProperty("player.needs_refresh_on_stop") == "true":
            win.clearProperty("player.needs_refresh_on_stop")
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass

        self._cleanup_monitor()
        try:
            from resources.lib.utils_prediction_handoff import schedule_manual_selection
            schedule_manual_selection(ended_meta, self.addon, self.tmdb_client)
        except Exception:
            pass

    def _cleanup_monitor(self):
        with self._playback_action_lock:
            self._cleanup_monitor_locked()

    def _cleanup_monitor_locked(self):
        self._cancel_pending_scrobble_start()
        self._cancel_pending_subtitles()
        self._cancel_seek_scrobble()
        self._playback_item_generation += 1
        with self.progress_lock:
            if self.progress_update_timer:
                self.progress_update_timer.cancel()
                self.progress_update_timer = None
            self._progress_timer_revision += 1
            self._progress_recheck_on_resume = False
            if self.downgrade_timer:
                self.downgrade_timer.cancel()
                self.downgrade_timer = None
            self._downgrade_generation += 1

        self.scrobbling_in_progress = False
        self.media_id = None
        self.media_type = None
        self._reset_progress()
        self.current_meta = None
        self._last_av_started_key = None
        self._last_av_started_at = 0.0
        self.pre_emptive_triggered = False
        self.skip_credits_triggered = False

        win = xbmcgui.Window(10000)
        win.clearProperty("play_er.switch_count")
        win.clearProperty("play_er.seamless_switching")
        win.clearProperty("play_er.playlist_quality_choice")
        win.clearProperty("play_er.queue_refill_requested")

        try:
            if self.play_key and self.orchestrator:
                self.orchestrator.clear_triggers(self.play_key)
        except Exception:
            pass
        self.play_key = None


def get_player_monitor(session=None, addon=None, tmdb_client=None, save_playback_history_func=None, remove_from_watch_later_func=None, mark_watched_func=None):
    """
    SINGLETON :: KODI PLAYER MONITOR
    -- Jeden monitor v rámci invokeru; router musí udržovat smyčku Kodi callbacků.
    """
    global _GLOBAL_PLAYER_MONITOR
    if _GLOBAL_PLAYER_MONITOR is None:
        _GLOBAL_PLAYER_MONITOR = KodiPlayerMonitor(
            session=session,
            addon=addon,
            tmdb_client=tmdb_client,
            save_playback_history_func=save_playback_history_func,
            remove_from_watch_later_func=remove_from_watch_later_func,
            mark_watched_func=mark_watched_func
        )
    else:
        if session:
            _GLOBAL_PLAYER_MONITOR.session = session
        if addon:
            _GLOBAL_PLAYER_MONITOR.addon = addon
        if tmdb_client:
            _GLOBAL_PLAYER_MONITOR.tmdb_client = tmdb_client
        if save_playback_history_func:
            _GLOBAL_PLAYER_MONITOR.save_playback_history_func = save_playback_history_func
        if remove_from_watch_later_func:
            _GLOBAL_PLAYER_MONITOR.remove_from_watch_later_func = remove_from_watch_later_func
        if mark_watched_func:
            _GLOBAL_PLAYER_MONITOR.mark_watched_func = mark_watched_func

    return _GLOBAL_PLAYER_MONITOR


def trakt_add_to_watchlist(params, addon, handle, session=None):
    _trakt_set_globals(session=session)
    trakt_client_id = addon.getSetting("trakt_client_id").strip()
    access_token = addon.getSetting("trakt_access_token").strip()

    if not trakt_client_id or not access_token:
        notify_error("AUTH Je potřeba vyplnit Client ID a Client Secret v nastavení", category="TRAKT", sound=True)
        return

    media_type = params.get("media_type", "movie")
    media_id = params.get("media_id")
    if not media_id:
        return

    add_url = "https://api.trakt.tv/sync/watchlist"
    add_data = {f"{media_type}s": [{"ids": {"trakt": int(media_id)}}]}
    try:
        response = safe_post(_session, add_url, headers=trakt_get_headers(addon=addon, write=True), json=add_data, timeout=10)
        if response is not None and response.status_code == 401:
            if trakt_refresh_token(addon=addon, session=_session):
                response = safe_post(_session, add_url, headers=trakt_get_headers(addon=addon, write=True), json=add_data, timeout=10)
        if response is not None and response.status_code == 201:
            _invalidate_personal_list("TRAKT_WATCHLIST")
            notify_ok("ACTION Položka přidána do watchlistu", category="TRAKT", time=3000)
        else:
            notify_error("ERROR Chyba při přidávání", category="TRAKT")
    except Exception:
        notify_error("ERROR Chyba při přidávání do watchlistu", category="TRAKT")

    try:
        cache_manager.safe_refresh()
    except Exception:
        pass


def handle_watchlist_remove(params, session, addon):
    access_token = addon.getSetting("trakt_access_token").strip()
    if not access_token:
        return

    media_type_param = "movies" if params.get("category") == "movies" else "shows"
    if "category" not in params and "media_type" in params:
        media_type_param = "movies" if params["media_type"] == "movie" else "shows"

    trakt_id = params.get("remove") or params.get("media_id")
    if not trakt_id:
        return

    remove_url = "https://api.trakt.tv/sync/watchlist/remove"
    remove_data = {media_type_param: [{"ids": {"trakt": int(trakt_id)}}]}
    try:
        response = safe_post(session, remove_url, headers=trakt_get_headers(addon=addon, write=True), json=remove_data, timeout=10)
        if response is not None and response.status_code == 401:
            if trakt_refresh_token(addon=addon, session=session):
                response = safe_post(session, remove_url, headers=trakt_get_headers(addon=addon, write=True), json=remove_data, timeout=10)
        if response is not None and response.status_code == 200:
            _invalidate_personal_list("TRAKT_WATCHLIST")
            notify_ok("ACTION Položka odstraněna z watchlistu", category="TRAKT", time=3000)
            try:
                cache_manager.safe_refresh()
            except Exception:
                pass
    except Exception:
        pass


def trakt_add_to_favorites(params, addon, handle, session=None):
    _trakt_set_globals(session=session)
    trakt_client_id = addon.getSetting("trakt_client_id").strip()
    access_token = addon.getSetting("trakt_access_token").strip()
    if not trakt_client_id or not access_token:
        return

    media_type = params.get("media_type", "movie")
    media_id = params.get("media_id")
    if not media_id:
        return

    url = "https://api.trakt.tv/sync/favorites"
    data = {f"{media_type}s": [{"ids": {"trakt": int(media_id)}}]}
    try:
        response = safe_post(_session, url, headers=trakt_get_headers(addon=addon, write=True), json=data, timeout=10)
        if response is not None and response.status_code == 401:
            if trakt_refresh_token(addon=addon, session=_session):
                response = safe_post(_session, url, headers=trakt_get_headers(addon=addon, write=True), json=data, timeout=10)
        if response is not None and response.status_code == 201:
            _invalidate_personal_list("TRAKT_FAVORITES")
            notify_ok("ACTION Přidáno do Oblíbených", category="TRAKT", time=3000)
    except Exception:
        pass


def play_trailer(params):
    tmdb_id = params.get('tmdb_id')
    media_type = params.get('media_type', 'movie')
    try:
        from resources.lib.utils import play_trailer_from_tmdb_id
        return play_trailer_from_tmdb_id(tmdb_id, media_type)
    except Exception:
        return None
