# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: provider_webshare.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import hashlib
import xml.etree.ElementTree as ET


import xbmc
import xbmcgui
import xbmcplugin


from resources.lib.provider_base import BaseProvider
from resources.lib.utils_logging import log
from resources.lib.md5crypt import md5crypt
from resources.lib.utils_theme import Colors

from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_acc
)

from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_str
)

from resources.lib.utils_filter import (
    FilterUtils,
    encode
)

from resources.lib.utils import (
    convert_size,
    store_meta_in_cache,
    get_meta_from_cache,
    safe_post,
    get_url
)





class Webshare(BaseProvider):

    """
    CLASS :: WEBSHARE.CZ
    -- Třída providera Webshare.cz pro API vyhledávání a přehrávání.
    """

    def __init__(self, addon, handle, session, tmdb_client):
        super(Webshare, self).__init__(addon, handle, session, tmdb_client)

        self.utils_filter = FilterUtils(addon)
        self.base_url = "https://webshare.cz/api/"
        self.username = get_setting_str(self.addon, "webshare_username", "")
        self.password = get_setting_str(self.addon, "webshare_password", "")
        self._auth_token = get_setting_str(self.addon, "webshare_token", "")
        self._login_failed = False

        if not self.username or not self.password:
            log("WEBSHARE - Chybí uživatelské jméno nebo heslo v nastavení.", xbmc.LOGERROR)
            notify_info("WEBSHARE.CZ CHYBÍ PŘIHLAŠOVACÍ ÚDAJE", "PROVIDER")
            self._auth_token = None
            self._login_failed = True
            return

        if not self._auth_token:
            try:
                self._login()
            except Exception as e:
                log(f"WEBSHARE - Výjimka při přihlašování: {e}", xbmc.LOGERROR)
                notify_error("WEBSHARE.CZ CHYBA PŘIHLÁŠENÍ", "PROVIDER")
                self._auth_token = None
                self._login_failed = True

    def _login(self):
        try:
            salt_response = safe_post(
                self.session,
                f"{self.base_url}salt/",
                data={'username_or_email': self.username},
                timeout=10
            )

            if not salt_response or salt_response.status_code != 200:
                log("WEBSHARE - Chyba při komunikaci se serverem (salt)", xbmc.LOGERROR)
                self._login_failed = True
                return False

            salt_xml = ET.fromstring(salt_response.content)
            if salt_xml.find('status').text != 'OK':
                log(f"WEBSHARE - Chyba při získávání salt-pass: {salt_xml.find('message').text}", xbmc.LOGERROR)
                notify_error("WEBSHARE.CZ CHYBA ZÍSKÁVÁNÍ SALT-PASS", "PROVIDER")
                self._login_failed = True
                return False

            salt = salt_xml.find('salt').text
            password_crypted = md5crypt(self.password, salt)
            password_hashed = hashlib.sha1(password_crypted.encode('utf-8')).hexdigest()

            login_payload = {
                'username_or_email': self.username,
                'password': password_hashed,
            }

            login_response = safe_post(
                self.session,
                f"{self.base_url}login/",
                data=login_payload,
                timeout=10
            )

            if not login_response or login_response.status_code != 200:
                log("WEBSHARE - Chyba při komunikaci se serverem (login)", xbmc.LOGERROR)
                self._login_failed = True
                return False

            login_xml = ET.fromstring(login_response.content)

            if login_xml.find('status').text == 'OK':
                self._auth_token = login_xml.find('token').text
                if self._auth_token:
                    self.addon.setSetting("webshare_token", self._auth_token)
                    log("PROVIDER :: WEBSHARE.CZ - TOKEN & LOGIN OK", xbmc.LOGINFO)
                    notify_acc("WEBSHARE.CZ AKTIVNÍ", category="SOURCE")
                    return True

            msg = login_xml.find('message').text if login_xml.find('message') is not None else "Unknown"
            log(f"WEBSHARE - Chyba při přihlášení: {msg}", xbmc.LOGERROR)
            notify_error("WEBSHARE.CZ CHYBA PŘIHLÁŠENÍ", "PROVIDER")
            self._login_failed = True
            return False

        except Exception as e:
            log(f"WEBSHARE - login exception: {e}", xbmc.LOGERROR)
            notify_error("WEBSHARE.CZ CHYBA PŘIHLÁŠENÍ", "PROVIDER")
            self._login_failed = True
            return False

    def _get_auth_token(self):
        if self._auth_token:
            return self._auth_token

        token = get_setting_str(self.addon, "webshare_token", "")
        if token:
            self._auth_token = token
            return self._auth_token

        if self.username and self.password:
            if self._login():
                return self._auth_token

        return None

    def search_sources(self, query, cookies=None, apply_filters=True):

        """
        WEBSHARE :: API SEARCH
        -- Vyhledává soubory na WEBSHARE.CZ pomocí API metody.
        """

        token = self._get_auth_token()
        if not token:
            return []

        raw_limit = get_setting_int_with_bounds(self.addon, "webshare_search_limit", 32, 32, 416)
        search_limit = max(1, min(int(raw_limit), 500))


        CATEGORIES = ['', 'video', 'images', 'audio', 'archives', 'docs', 'adult']
        SORTS = ['', 'recent', 'rating', 'largest', 'smallest']


        cat_map = {
            "": "",
            "VIDEO": "video",
            "OBRAZKY": "images",
            "AUDIO": "audio",
            "ARCHIVY": "archives",
            "DOKUMENTY": "docs",
            "PRO DOSPELE": "adult",
            "PRODOSPELE": "adult",
        }


        sort_map = {
            "": "",
            "RELEVANCE": "",
            "RECENT": "recent",
            "HODNOCENI": "rating",
            "NEJVETSI": "largest",
            "NEJMENSI": "smallest",
        }


        raw_cat = get_setting_str(self.addon, "webshare_category", "VIDEO")
        raw_sort = get_setting_str(self.addon, "webshare_sort", "RELEVANCE")

        raw_cat_norm = encode(raw_cat.strip("'")).upper()
        raw_sort_norm = encode(raw_sort.strip("'")).upper()

        if raw_cat.isdigit():
            idx = int(raw_cat)
            category = CATEGORIES[idx] if 0 <= idx < len(CATEGORIES) else ''
        else:
            category = cat_map.get(raw_cat_norm, '')

        if raw_sort.isdigit():
            idx = int(raw_sort)
            sort = SORTS[idx] if 0 <= idx < len(SORTS) else ''
        else:
            sort = sort_map.get(raw_sort_norm, '')

        payload = {
            'what': '' if not query else query,
            'category': category,
            'sort': sort,
            'limit': search_limit,
            'offset': 0,
            'wst': token,
            'maybe_removed': 'true'
        }

        url = f"{self.base_url}search/"
        all_videos = []

        try:
            response = safe_post(self.session, url, data=payload, timeout=15)
            if response and response.status_code == 200:
                xml_response = ET.fromstring(response.content)
                if xml_response.findtext('status') == 'OK':
                    for item_xml in xml_response.iter('file'):
                        item = {child.tag: child.text for child in item_xml}
                        ident = (item.get("ident") or "").strip()
                        if not ident:
                            continue
                        try:
                            size_str = convert_size(int(item.get("size") or 0))
                        except (TypeError, ValueError, OverflowError):
                            size_str = ""
                        name = item.get("name") or "Neznámý soubor"
                        ext = name.split('.')[-1].lower() if '.' in name else ''

                        all_videos.append({
                            "title": name,
                            "link": ident,
                            "size_str": size_str,
                            "duration_str": "",
                            "file_id": ident,
                            "provider": "webshare.cz",
                            "provider_color": Colors.LIMEGREEN,
                            "tags": [],
                            "extension": ext
                        })
                else:
                    message = xml_response.findtext('message') or ''
                    log(f"WEBSHARE - Chyba při vyhledávání: {message}", xbmc.LOGERROR)
                    if message == "Invalid token":
                        self.addon.setSetting("webshare_token", "")
                        self._auth_token = None
                        notify_error("WEBSHARE.CZ NEPLATNÝ TOKEN", "PROVIDER")
            else:
                log(f"WEBSHARE - Chyba HTTP: {response.status_code if response is not None else 'žádná odpověď'}", xbmc.LOGERROR)
        except Exception as e:
            log(f"WEBSHARE - Výjimka při vyhledávání: {e}", xbmc.LOGERROR)

        return self.normalize_and_filter(all_videos, apply_filters=apply_filters)

    def find_and_list_sources(self, meta_json):

        """
        SOURCES :: WEBSHARE
        -- Vyhledá zdroje a zobrazí je jako seznam v Kodi.
        """

        if isinstance(meta_json, dict):
            meta = meta_json
        else:
            meta = get_meta_from_cache(meta_json)

        media_type = meta.get("media_type", "movie")
        search_query = f"{meta.get('title', '')} {meta.get('year', '')}"

        if media_type == "episode":
            try:
                season_num = int(meta.get("season", 0))
                episode_num = int(meta.get("episode", 0))
                search_query = f"{meta.get('tv_show_title', '')} S{season_num:02d}E{episode_num:02d}"
            except (ValueError, TypeError):
                search_query = f"{meta.get('tv_show_title', '')} {meta.get('title', '')}"

        log(f"WEBSHARE - Hledám zdroje pro : '{search_query}'", xbmc.LOGINFO)
        results = self.search_sources(search_query, apply_filters=True)

        if not results:
            notify_info("WEBSHARE.CZ ZDROJE NENALEZENY", "PROVIDER")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return

        show_size = get_setting_bool(self.addon, "show_size", True)
        filter_enabled = get_setting_bool(self.addon, "filter_display_title_tmdb", True)
        from resources.lib.utils_filter import clean_display_title

        meta_key = store_meta_in_cache(meta)

        for video in results:
            size_display = (
                f'[LIGHT][COLOR {Colors.LIMEGREEN}][{video["size_str"]}][/LIGHT][/COLOR] '
                if show_size and video.get("size_str")
                else ""
            )

            display_title = video["title"]
            if filter_enabled:
                try:
                    cleaned, _, _, _ = clean_display_title(display_title)
                    display_title = cleaned
                except Exception:
                    pass

            label = f'{size_display}{display_title}'.strip()

            list_item = xbmcgui.ListItem(label=label)
            list_item.setProperty("IsPlayable", "true")

            if self.tmdb_client:
                self.tmdb_client.fill_list_item(list_item, meta, media_type)
            else:
                list_item.setArt({
                    "poster": meta.get("poster"),
                    "fanart": meta.get("fanart"),
                })

            play_url = get_url(action="play", link=video["link"], provider="webshare.cz", meta=meta_key)
            xbmcplugin.addDirectoryItem(handle=self._handle, url=play_url, listitem=list_item, isFolder=False)

        xbmcplugin.endOfDirectory(self._handle)

    def get_video_link(self, file_id):

        """
        GET VIDEO :: WEBSHARE
        -- Získá přímý odkaz na video soubor z Webshare.cz.
        """

        token = self._get_auth_token()
        if not token:
            return None, None

        payload = {
            "wst": token,
            "ident": file_id,
        }
        url = f"{self.base_url}file_link/"

        try:
            response = safe_post(self.session, url, data=payload, timeout=15)
            if response and response.status_code == 200:
                xml = ET.fromstring(response.content)
                if xml.find('status').text == 'OK':
                    direct_url = xml.find('link').text
                    log(f"WEBSHARE - Získán přímý odkaz pro {file_id}", xbmc.LOGINFO)
                    return direct_url, None
                else:
                    log(f"WEBSHARE - Chyba při získávání odkazu: {xml.find('message').text}", xbmc.LOGERROR)
                    notify_error("WEBSHARE.CZ CHYBA ODKAZU", "PROVIDER")
            else:
                log(f"WEBSHARE - Chyba HTTP při získávání odkazu: {response.status_code if response is not None else 'žádná odpověď'}", xbmc.LOGERROR)
        except Exception as e:
            log(f"WEBSHARE - Výjimka při získávání odkazu: {e}", xbmc.LOGERROR)
        return None, None
