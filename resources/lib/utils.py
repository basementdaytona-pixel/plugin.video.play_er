# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026 (Fix: HTTP request error handling)
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re
import uuid
import json
import math
import time
import hashlib
import requests
import traceback

import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon


from urllib.parse import urlencode
from requests.exceptions import RequestException


from resources.lib.utils_files import ensure_dir
from resources.lib.utils_logging import log
from resources.lib import cache_manager


from resources.lib.utils_notification import (
    notify_error,
    notify_info
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)


def get_url(**kwargs):

    """
    ADDON :: GLOBAL URL
    -- Nastavení globální URL pro addon.
    """

    return f"plugin://plugin.video.play_er/?{urlencode(kwargs)}"


def pop_dialog_select(heading, options, preselect_index=0):

    """
    DIALOG :: MENU SELECT
    -- Zobrazí dialogové okno pro výběr z možností.
    """

    try:
        dialog = xbmcgui.Dialog()
        return dialog.select(heading, options, preselect=preselect_index)
    except Exception as e:
        log(f"UTILS | DIALOG MENU - Chyba při zobrazení dialogu výběru : {e}", xbmc.LOGERROR)
        return -1


DEFAULT_HTTP_TIMEOUT = 15


def get_threadpool(max_workers_requested: int) -> int:
    """
    Compute a safe threadpool size based on CPU count.
    Caps the requested workers to a reasonable upper bound to avoid IO/CPU spikes.
    """
    try:
        cpu = os.cpu_count() or 2
        cap = max(2, cpu * 2)
        return min(max_workers_requested, cap)
    except Exception:
        return min(max_workers_requested, 10)


def safe_get(session_or_url, url=None, timeout=None, retry=2, **kwargs):

    """
    HTTP :: GET
    -- Funkce pro HTTP GET akce s ošetřením.
    """

    _timeout = timeout or DEFAULT_HTTP_TIMEOUT

    for attempt in range(retry + 1):
        try:
            if url is None:
                resp = requests.get(session_or_url, timeout=_timeout, **kwargs)
            else:
                resp = session_or_url.get(url, timeout=_timeout, **kwargs)

            # Původní zrychlení pro 404
            if resp is not None and resp.status_code == 404:
                return resp

            resp.raise_for_status()
            return resp
        except RequestException as e:
            # FIX: Zrychlení - klientské chyby nemá smysl opakovat
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in [400, 401, 403, 404, 409, 422]:
                    return e.response

            if attempt < retry:
                time.sleep(1)
                continue
            try:
                log(f"UTILS | HTTP GET - Error for {url or session_or_url} : {e}", level=xbmc.LOGERROR)
            except Exception:
                pass

            # FIX: Nevracet None, ale samotnou odpověď (aby mohl trakt.py přečíst status_code)
            if hasattr(e, 'response') and e.response is not None:
                return e.response
            return None
    return None


def safe_post(session_or_url, url=None, timeout=None, retry=2, **kwargs):

    """
    HTTP :: POST
    -- Funkce pro HTTP POST akce s ošetřením.
    """

    _timeout = timeout or DEFAULT_HTTP_TIMEOUT

    for attempt in range(retry + 1):
        try:
            if url is None:
                resp = requests.post(session_or_url, timeout=_timeout, **kwargs)
            else:
                session = session_or_url
                resp = session.post(url, timeout=_timeout, **kwargs)

            resp.raise_for_status()
            return resp
        except RequestException as e:
            # FIX: Zrychlení - klientské chyby nemá smysl opakovat
            if hasattr(e, 'response') and e.response is not None:
                if e.response.status_code in [400, 401, 403, 404, 409, 422]:
                    return e.response

            if attempt < retry:
                time.sleep(1)
                continue
            try:
                request_target = str(url or session_or_url)
                request_target = re.sub(r"(/bot)[^/]+(/)", r"\1<redacted>\2", request_target)
                error_text = re.sub(
                    r"(https?://api\.telegram\.org/bot)[^/]+",
                    r"\1<redacted>",
                    str(e)
                )
                log(f"UTILS | HTTP POST - Error for {request_target} : {error_text}", level=xbmc.LOGERROR)
            except Exception:
                pass

            # FIX: Nevracet None, ale samotnou odpověď (aby mohl trakt.py přečíst status_code)
            if hasattr(e, 'response') and e.response is not None:
                return e.response
            return None
    return None


def duration_to_seconds(duration_str):

    """
    WEBSHARE :: TIME
    -- Funkce pro převod času na sekundy.
    """

    if not duration_str:
        return 0

    try:
        parts = duration_str.strip().split(":")
        if len(parts) == 3:
            h, m, s = list(map(int, parts))
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = list(map(int, parts))
            return m * 60 + s
        return 0
    except (ValueError, TypeError):
        return 0


def convert_size_to_bytes(size_str):

    """
    WEBSHARE :: SIZE
    -- Funkce pro konvertaci velikosti souborů.
    """

    size_str = size_str.replace(",", ".").upper().strip()
    match = re.match(r"([\d\.]+)\s*(KB|MB|GB|TB)", size_str)
    if not match:
        return 0
    size, unit = float(match.group(1)), match.group(2)
    factor = {"KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
    return int(size * factor.get(unit, 0))


def convert_size(size_bytes):

    """
    PROVIDER :: SIZE
    -- Funkce pro konvertaci velikosti souborů.
    """

    try:
        size_bytes = float(size_bytes)
    except (TypeError, ValueError):
        return "0.00 GB"
    if size_bytes <= 0:
        return "0.00 GB"
    gb = size_bytes / (1000 ** 3)
    abs_gb = abs(gb)
    integer_digits = len(str(int(abs_gb))) if abs_gb >= 1 else 0
    sig = 3
    decimals = max(0, sig - integer_digits)
    decimals = min(decimals, 6)

    if abs_gb < 1:
        decimals = 2
        factor = 10 ** decimals
        try:
            truncated = math.trunc(gb * factor) / factor
        except Exception:
            truncated = gb
        fmt = f"{{:.{decimals}f}}"
        formatted = fmt.format(truncated)
        return f"{formatted} GB"

    fmt = f"{{:.{decimals}f}}"
    formatted = fmt.format(round(gb, decimals))
    return f"{formatted} GB"


def add_next_page_item(handle, action, headers, current_page, **params):

    """
    NEXT ITEM :: PAGINATION
    -- Funkce pro stránkování seznamů.
    """

    import xbmcplugin

    if not headers or not isinstance(headers, dict):
        return

    headers_lower = {k.lower(): v for k, v in headers.items()}

    try:
        page_count_str = headers_lower.get('x-pagination-page-count')
        if not page_count_str:
            return

        page_count = int(page_count_str)
        if page_count <= 1:
            return

        api_page_str = headers_lower.get('x-pagination-page')
        api_current_page = int(api_page_str) if api_page_str else current_page

        if api_current_page < page_count:
            next_page = api_current_page + 1
            params['page'] = next_page

            label = f"[B][COLOR {Colors.ORANGE}]| STRANA[/B] [ {next_page} ] [B]►[/COLOR][/B]"
            li = xbmcgui.ListItem(label=label)

            art_path = Icons.NEXT_PAGE
            li.setArt({
                "icon": art_path,
                "thumb": art_path
            })

            url = get_url(action=action, **params)
            xbmcplugin.addDirectoryItem(handle, url, li, True)
    except Exception as e:
        log(f"UTILS | PAGING - ERROR : {e}", xbmc.LOGWARNING)


def play_trailer_from_tmdb_id(tmdb_id, media_type='movie', tmdb_client=None, use_vidious_plugin=True):

    """
    TRAILER :: YOUTUBE & MAU_VIDIOUS
    -- Funkce pro přehrávání trailerů z TMDB.
    """

    if not tmdb_id:
        notify_error(f"ERROR Chyba: Chybí TMDB ID", category="SYSTEM")
        return False

    try:
        if tmdb_client is None:

            from resources.lib.tmdb import TMDB

            addon = xbmcaddon.Addon()
            session = requests.Session()
            tmdb_client = TMDB(addon, None, session)

        trailer_url = tmdb_client.get_trailer(media_type, tmdb_id)

        if not trailer_url:
            notify_info(f"[COLOR {Colors.ORANGE}]TRAILER[/COLOR] : TRAILER NENALEZEN")
            return False

        video_id = ""
        if "v=" in trailer_url:
            video_id = trailer_url.split("v=")[-1].split("&")[0]
        elif "/" in trailer_url:
            video_id = trailer_url.split("/")[-1]

        if not video_id:
            notify_info(f"[COLOR {Colors.ORANGE}]TRAILER[/COLOR] : NEZNÁMÝ FORMÁT")
            return False

        if use_vidious_plugin:
            vidious_url = f"plugin://plugin.video.tube_er/?action=play&videoId={video_id}"
            xbmc.executebuiltin(f'PlayMedia("{vidious_url}")')
            xbmc.sleep(3000)
            if xbmc.Player().isPlaying():
                return True

            xbmc.executebuiltin(f'PlayMedia("https://www.youtube.com/watch?v={video_id}")')
            xbmc.sleep(1500)
            return xbmc.Player().isPlaying()
        else:
            xbmc.executebuiltin(f'PlayMedia("https://www.youtube.com/watch?v={video_id}")')
            xbmc.sleep(1500)
            return xbmc.Player().isPlaying()

    except Exception as e:
        try:
            log(f"UTILS | TRAILER ERROR - play_trailer_from_tmdb_id : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        except Exception:
            pass
        notify_error(f"[COLOR {Colors.RED}]TRAILER[/COLOR] : CHYBA PŘI SPUŠTĚNÍ TRAILERU")
        return False


def send_telegram_message(addon, message):

    """
    TELEGRAM :: NOTIFY
    -- Odešle zprávu přes Telegram bota, pokud je funkce povolena a nakonfigurována.
    """

    enabled = addon.getSettingBool("enable_telegram_notifications")
    token = addon.getSettingString("telegram_bot_token").strip()
    chat_id = addon.getSettingString("telegram_chat_id").strip()

    if not enabled or not token or not chat_id:
        if enabled:
            log("UTILS | TELEGRAM - Notifikace povoleny, ale chybí BOT token nebo CHAT ID", xbmc.LOGWARNING)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        response = safe_post(url, json=payload, timeout=10)
        if response and response.status_code == 200:
            log("UTILS | TELEGRAM - Zpráva úspěšně odeslána", xbmc.LOGINFO)
    except Exception as e:
        log(f"UTILS | TELEGRAM - Výjimka při odesílání zprávy : {e}", xbmc.LOGERROR)


def store_meta_in_cache(meta_dict):

    """
    BRIDGE :: STORE META
    -- Uloží metadata do centrální cache  ( RAM + SQL )  a vrátí klíč.
    -- Řeší limit délky URL pro Yatse/JSON-RPC.
    -- OPRAVA : Generování deterministického klíče pro správnou funkčnost Resume Dialogu v Kodi.
    """

    if not meta_dict:
        return ""

    try:
        tmdb_id = meta_dict.get('tmdb_id', '')
        media_type = meta_dict.get('media_type', 'movie')
        if tmdb_id:
            if media_type == 'episode':
                season = meta_dict.get('season', '')
                episode = meta_dict.get('episode', '')
                base_str = f"ep_{tmdb_id}_{season}_{episode}"
            else:
                base_str = f"mov_{tmdb_id}"
            key = hashlib.md5(base_str.encode('utf-8')).hexdigest()
        else:
            key = str(uuid.uuid4())
    except Exception:
        key = str(uuid.uuid4())

    try:
        md = dict(meta_dict) if isinstance(meta_dict, dict) else { 'meta': meta_dict }
        md['meta_id'] = key
        cache_manager.cache_set("URL_CACHE", key, md)
        return key
    except Exception as e:
        log(f"UTILS BRIDGE - Chyba při ukládání do cache : {e}", xbmc.LOGERROR)
        return ""


def get_meta_from_cache(key_or_json):

    """
    BRIDGE :: GET META
    -- Získá metadata z centrální cache.
    """

    if not key_or_json:
        return {}

    key_str = str(key_or_json).strip()

    if key_str.startswith("{"):
        try:
            return json.loads(key_str)
        except:
            return {}

    data = cache_manager.cache_get("URL_CACHE", key_str)

    if data:
        return data

    return {}


def _menu_posters_vfs_dir():
    return "special://masterprofile/DATA--PLAY/POSTERS/"


def get_menu_poster_local(url, timeout=20):

    """
    POSTER :: MENU CACHE
    -- Získá lokální cestu k posteru pro hlavní menu.
    -- Pokud je poster již cachován, vrátí VFS cestu.
    -- Jinak se pokusí stáhnout obrázek a uložit do  `special://userdata/PLAY-DATA/POSTERS/`.
    -- Vrací VFS cestu  ( special://... )  nebo prázdný string.
    """

    if not url or not isinstance(url, str):
        return ""

    try:
        mapping = cache_manager.user_data_get("menu_posters_map") or {}
    except Exception:
        mapping = {}

    vfs_path = mapping.get(url)
    if vfs_path and xbmcvfs.exists(vfs_path):
        return vfs_path

    try:
        ensure_dir(_menu_posters_vfs_dir())
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        filename = f"{h}{ext}"
        vfs_path = f"{_menu_posters_vfs_dir()}{filename}"
        local_path = xbmcvfs.translatePath(vfs_path)

        resp = safe_get(url, stream=True, timeout=timeout)
        if not resp:
            return ""

        content = None
        try:
            content = resp.content
        except Exception:
            content = None

        if not content:
            return ""

        try:
            fh = xbmcvfs.File(vfs_path, "w")
            fh.write(content)
            fh.close()
        except Exception:
            try:
                with open(local_path, "wb") as f:
                    f.write(content)
            except Exception:
                return ""

        try:
            mapping[url] = vfs_path
            cache_manager.user_data_set("menu_posters_map", mapping)
        except Exception:
            pass

        return vfs_path
    except Exception as e:
        try:
            log(f"UTILS | MENU POSTER CACHE - Error for {url} : {e}", xbmc.LOGWARNING)
        except Exception:
            pass
        return ""
