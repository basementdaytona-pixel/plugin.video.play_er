# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: tmdb_account.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import json
import requests
import threading

import xbmc
import xbmcgui
import xbmcvfs

# --- AUTO-INJECTED KODI 22 VFS PATCH ---
class SafeVFSFile:
    def __init__(self, *args, **kwargs):
        import xbmcvfs
        self.file_obj = xbmcvfs.File(*args, **kwargs)
    def __enter__(self):
        return self.file_obj
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file_obj.close()
        return False
# ---------------------------------------

import xbmcaddon


from resources.lib.utils_logging import log
from resources.lib import cache_manager
from .telegram import TelegramManager


from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)

from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_int,
    get_setting_str,
    get_tmdb_language
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)

from resources.lib.utils import (
    safe_post,
    safe_get
)






TMDB_LOCK = threading.Lock()
ADDON = xbmcaddon.Addon()
API_KEY = ADDON.getSetting("api_key")
LANGUAGE = get_tmdb_language(ADDON)
BASE_URL = "https://api.themoviedb.org/3"
SESSION = requests.Session()




def _tmdb_set_globals(addon=None, session=None):
    global ADDON, API_KEY, LANGUAGE, SESSION
    with TMDB_LOCK:
        if addon is not None:
            ADDON = addon
            try:
                API_KEY = ADDON.getSetting("api_key")
                LANGUAGE = get_tmdb_language(ADDON)
            except Exception:
                pass
        if session is not None:
            SESSION = session
        else:
            if SESSION is None:
                SESSION = requests.Session()




ACCOUNT_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
ACCOUNT_FILE = os.path.join(ACCOUNT_DIR, "TMDB_ACCOUNT.JSON")




def _ensure_account_dir_exists():
    if not xbmcvfs.exists(ACCOUNT_DIR):
        try:
            xbmcvfs.mkdirs(ACCOUNT_DIR)
            log(f"TMDB - Vytvořen adresář pro účet : {ACCOUNT_DIR}", level=xbmc.LOGDEBUG)
            return True
        except Exception as e:
            log(f"TMDB - CHYBA : Nelze vytvořit adresář pro účet : {e}", level=xbmc.LOGERROR)
            return False
    return True


def save_account_data(data):
    if not _ensure_account_dir_exists():
        log(f"TMDB - CHYBA při ukládání : Adresář neexistuje", level=xbmc.LOGERROR)
        return
    try:
        with SafeVFSFile(ACCOUNT_FILE, "w") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        log(f"TMDB - Data účtu uložena  :  [  {ACCOUNT_FILE}  ]", level=xbmc.LOGINFO)
    except Exception as e:
        log(f"TMDB - CHYBA při ukládání dat účtu : {e}", level=xbmc.LOGERROR)


def load_account_data():
    if not xbmcvfs.exists(ACCOUNT_FILE):
        return {}
    try:
        with SafeVFSFile(ACCOUNT_FILE, "r") as f:
            content = f.read()
        return json.loads(content) if content else {}
    except Exception as e:
        log(f"TMDB - CHYBA při načítání dat (reset) : {e}", level=xbmc.LOGERROR)
        return {}


def tmdb_start_auth_flow(addon, handle=None):
    try:
        res = safe_get(f"{BASE_URL}/authentication/token/new", params={"api_key": API_KEY}, timeout=10)
        if res is None:
            raise Exception("Network error")
        res.raise_for_status()
        token = res.json().get("request_token")

        auth_url = f"https://www.themoviedb.org/authenticate/{token}"
        telegram_sent = False
        if addon.getSettingBool("enable_telegram_notifications"):
            photo_path = os.path.join(addon.getAddonInfo('path'), 'resources', 'icons', 'TELE-ACC.webp')
            telegram = TelegramManager(addon, log)
            telegram.send_tmdb_auth_url(auth_url, photo_path)
            telegram_sent = True
        else:
            xbmc.log(f"TMDB AUTH-URL  :  [  {auth_url}  ]", xbmc.LOGINFO)
        
        telegram_info = "\n[COLOR orange][   ►  AUTH-URL BYLA ODESLÁNA NA TVŮJ TELEGRAM ! [/COLOR]" if telegram_sent else ""
        
        xbmcgui.Dialog().ok(
            f"[COLOR {Colors.ORANGE}]○  LOGIN  [ FUCKING ]  ACCOUNT  ○[/COLOR]",
            f"[COLOR orange][   ►  OTEVŘI ODKAZ V PROHLÍŽEČI A POTVRĎ PŘÍSTUP ! [/COLOR]\n{auth_url}{telegram_info}",
        )
        if not xbmcgui.Dialog().yesno("TMDB PŘIHLAŠOVÁNÍ", "POTVRDIL JSI PŘÍSTUP NA WEBU?"):
            return

        session_res = safe_post(f"{BASE_URL}/authentication/session/new", params={"api_key": API_KEY}, json={"request_token": token}, timeout=10)
        session_res.raise_for_status()
        session_id = session_res.json().get("session_id")

        acc_res = safe_get(f"{BASE_URL}/account", params={"api_key": API_KEY, "session_id": session_id}, timeout=10)
        acc_res.raise_for_status()

        account_data = acc_res.json()
        account_data["session_id"] = session_id
        save_account_data(account_data)

        notify_ok(f"AUTH Přihlášen jako {account_data.get('username')}", category="TMDB", time=5000)
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass
    except Exception as e:

        notify_error(f"AUTH ERROR {e}", category="TMDB")


def _make_tmdb_request(endpoint_template, media_type=None, page=1, method="GET", payload=None):
    data = load_account_data()
    session_id = data.get("session_id")
    if not session_id:

        notify_error(f"AUTH Nejsi přihlášen", category="TMDB")
        return None
    account_id = data.get("id")

    endpoint_part = endpoint_template.format(media_endpoint=media_type or "na")
    language = get_tmdb_language(ADDON)
    cache_key = f"tmdb_account_{account_id}_{language}_{endpoint_part}_page_{page}"

    if method == "GET":
        w_data = cache_manager.window_cache_get(cache_key)
        if w_data:
            return w_data

    if method == "GET":
        cached_data = cache_manager.cache_get("TMDB", cache_key)
        if cached_data is not None:
            cache_manager.window_cache_set(cache_key, cached_data)
            return cached_data

    if media_type:
        media_endpoint = "movies" if media_type == "movie" else "tv"
        url = f"{BASE_URL}/account/{account_id}/{endpoint_template.format(media_endpoint=media_endpoint)}"
    else:
        url = f"{BASE_URL}/account/{account_id}/{endpoint_template}"

    params = {
        "api_key": API_KEY,
        "session_id": session_id,
        "language": language,
    }
    if method == "GET":
        params["page"] = page
        params["sort_by"] = "created_at.desc"

    try:
        if method == "GET":
            res = safe_get(SESSION, url, params=params, timeout=15)
        elif method == "POST":
            res = safe_post(SESSION, url, params=params, json=payload, timeout=15)
        else:
            return None

        res.raise_for_status()
        response_data = res.json()

        if method == "GET":
            cache_manager.cache_set("TMDB", cache_key, response_data)
            cache_manager.window_cache_set(cache_key, response_data)

        return response_data
    except Exception as e:
        log(f"TMDB ACCOUNT - API ERROR {url}: {e}", level=xbmc.LOGERROR)
        return None


def tmdb_get_watchlist(media_type="movie", page=1):
    return _make_tmdb_request("watchlist/{media_endpoint}", media_type, page)

def tmdb_get_rated(media_type="movie", page=1):
    return _make_tmdb_request("rated/{media_endpoint}", media_type, page)

def tmdb_get_favorites(media_type="movie", page=1):
    return _make_tmdb_request("favorite/{media_endpoint}", media_type, page)


def tmdb_get_recommendations(media_type="movie", page=1):
    data = load_account_data()
    session_id = data.get("session_id")
    if not session_id:
        return None

    rated_endpoint = "rated/{media_endpoint}".format(media_endpoint="movies" if media_type == "movie" else "tv")
    rated_items_data = _make_tmdb_request(rated_endpoint, media_type, 1)

    if not rated_items_data or not rated_items_data.get("results"):
        return None

    top_rated_item = rated_items_data["results"][0]
    item_id = top_rated_item.get("id")
    if not item_id:
        return None

    language = get_tmdb_language(ADDON)
    cache_key = f"tmdb_recs_for_{language}_{media_type}_{item_id}_page_{page}"

    w_data = cache_manager.window_cache_get(cache_key)
    if w_data:
        return w_data

    cached_data = cache_manager.cache_get("TMDB", cache_key)
    if cached_data is not None:
        cache_manager.window_cache_set(cache_key, cached_data)
        return cached_data

    url = f"{BASE_URL}/{media_type}/{item_id}/recommendations"
    params = {
        "api_key": API_KEY,
        "language": language,
        "page": page,
    }
    try:
        res = safe_get(SESSION, url, params=params, timeout=10)
        if res:
            recs_data = res.json()
            cache_manager.cache_set("TMDB", cache_key, recs_data)
            cache_manager.window_cache_set(cache_key, recs_data)
            return recs_data
        return None
    except Exception:
        return None


def tmdb_get_user_lists(page=1):
    return _make_tmdb_request("lists", media_type=None, page=page)


def tmdb_get_user_list_items(list_id, page=1):
    language = get_tmdb_language(ADDON)
    cache_key = f"tmdb_list_{language}_{list_id}_page_{page}"

    w_data = cache_manager.window_cache_get(cache_key)
    if w_data:
        return w_data

    cached = cache_manager.cache_get("TMDB", cache_key)
    if cached:
        cache_manager.window_cache_set(cache_key, cached)
        return cached

    data = load_account_data()
    session_id = data.get("session_id")
    if not session_id:
        return None

    url = f"{BASE_URL}/list/{list_id}"
    params = {"api_key": API_KEY, "language": language, "page": page}
    res = safe_get(SESSION, url, params=params, timeout=15)
    if res:
        data = res.json()
        cache_manager.cache_set("TMDB", cache_key, data)
        cache_manager.window_cache_set(cache_key, data)
        return data
    return None


def _toggle_tmdb_list(list_name, tmdb_id, media_type, add=True):
    data = load_account_data()
    session_id = data.get("session_id")
    if not session_id:

        notify_error(f"AUTH Nejsi přihlášen", category="TMDB")
        return
    account_id = data.get("id")
    payload = {"media_type": media_type, "media_id": int(tmdb_id), list_name: add}
    url = f"{BASE_URL}/account/{account_id}/{list_name}"
    params = {"api_key": API_KEY, "session_id": session_id}
    try:
        res = safe_post(SESSION, url, params=params, json=payload, timeout=15)
        res.raise_for_status()
        resp_data = res.json()
        if resp_data.get("success") or resp_data.get("status_code") in [1, 12, 13]:
            list_cz = "WATCHLISTU" if list_name == "watchlist" else "OBLÍBENÝCH"
            action_cz = "PŘIDÁNO DO" if add else "ODEBRÁNO Z"

            notify_ok(f"ACTION {action_cz} {list_cz}", category="TMDB", time=3000)
        else:
            raise ValueError("API Fail")
    except Exception as e:
        log(f"TMDB TOGGLE ERROR: {e}", xbmc.LOGERROR)

        notify_error(f"ERROR Chyba při změně seznamu", category="TMDB")


def tmdb_toggle_watchlist(tmdb_id, media_type="movie", add=True):
    _toggle_tmdb_list("watchlist", tmdb_id, media_type, add)

def tmdb_toggle_favorite(tmdb_id, media_type="movie", add=True):
    _toggle_tmdb_list("favorite", tmdb_id, media_type, add)


def tmdb_remove_rating(tmdb_id, media_type="movie"):
    data = load_account_data()
    session_id = data.get("session_id")
    if not session_id:
        return
    url = f"{BASE_URL}/{media_type}/{tmdb_id}/rating"
    params = {"api_key": API_KEY, "session_id": session_id}
    try:
        res = SESSION.delete(url, params=params, timeout=15)
        if res.status_code in [200, 13]:

            notify_ok(f"RATE HODNOCENÍ ODSTRANĚNO", category="TMDB", time=3000)
    except Exception:
        pass


def tmdb_rate_prompt_and_send(tmdb_id, media_type="movie", handle=None):
    kb = xbmc.Keyboard("", "ZADEJ HODNOCENÍ (0.5 - 10)")
    kb.doModal()
    if not kb.isConfirmed():
        return
    try:
        val = float(kb.getText().strip())
        if not (0.5 <= val <= 10):
            raise ValueError

        data = load_account_data()
        sid = data.get("session_id")
        if not sid:

            notify_error(f"AUTH Nejsi přihlášen", category="ACCOUNT")
            return

        url = f"{BASE_URL}/{media_type}/{tmdb_id}/rating"
        params = {"api_key": API_KEY, "session_id": sid}
        res = safe_post(SESSION, url, params=params, json={"value": val}, timeout=15)

        if res.status_code in [200, 201]:

            notify_ok(f"RATE HODNOCENO {val}", category="TMDB", time=3000)
        else:

            notify_error(f"RATE ERROR Chyba hodnocení", category="TMDB")
    except Exception:

        notify_error(f"INPUT Neplatná hodnota (0.5 - 10)", category="SYSTEM")