# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: tmdb.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
#  ---------------------------------------------------------------------------
#  --- CENTRALIZED CONTEXT MENU   [ LINE  750 ] ------------------------------
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import re
import hashlib
import json
import random
import base64
import urllib.parse

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

import xbmcplugin


from datetime import datetime


from resources.lib.ui_builder import set_view_mode
from resources.lib.utils_logging import log
from resources.lib import cache_manager
from resources.lib import tmdb_account


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
    store_meta_in_cache,
    get_meta_from_cache,
    add_next_page_item,
    safe_get,
    get_url
)






class TMDB:

    """
    CLASS :: TMDB
    -- Class module TMDB database with SSD/RAM caching.
    """


    def __init__(self, addon, handle, session):

        self.addon = addon
        self._handle = handle
        self.session = session
        self.api_key = get_setting_str(self.addon, "api_key", "")
        self.genres_cache = {}
        self.language = get_tmdb_language(addon)
        log(
            f"TMDB FETCH : L A N G U A G E : INICIALIZACE - JAZYK NASTAVEN NA[ '{self.language}' ]",
            xbmc.LOGDEBUG,
        )
        self.enable_trakt_context = self.addon.getSettingBool("enable_trakt_context")
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/"
        self.main_window = xbmcgui.Window(10000)



    def _cache_variant(self, key, language=None, skip_filter=False):
        """Keep cached translations and filter preferences independent."""
        try:
            mode = (self.addon.getSetting("filter_tmdb_language") or "SOFT").strip().upper()
        except Exception:
            mode = "SOFT"
        return f"{key}_{language or self.language}_{'OFF' if skip_filter else mode}"


    def _fetch(self, endpoint, params=None, cache_key=None, skip_filter=False, language_override=None):


        if not self.api_key:
            log("TMDB FETCH - CACHE : Chybí TMDB API klíč v nastavení !", xbmc.LOGERROR)


            notify_error("ERROR: Chyba při načítání - Chybí TMDB API klíč v nastavení !", category="TMDB")
            return None


        # Reuse season/episode details across Continue, credits and queue checks.
        # Keep credits and language variants separate; honour the configured TMDB TTL.
        params = dict(params or {})
        lang_to_use = language_override if language_override else self.language
        if lang_to_use:
            params["language"] = lang_to_use
        automatic_detail_cache = cache_key is None and re.fullmatch(
            r"tv/\d+/season/\d+(?:/episode/\d+)?", endpoint
        ) is not None
        if automatic_detail_cache:
            identity = [endpoint, {k: v for k, v in params.items() if k != "api_key"}, skip_filter]
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
            cache_key = "tv_detail_" + digest

        if cache_key:
            cache_key = self._cache_variant(cache_key, lang_to_use, skip_filter)

        if cache_key and "page" in cache_key:
            w_data = cache_manager.window_cache_get(cache_key)
            if w_data:
                log(f"TMDB - CACHE HIT | WIDGET : {cache_key}", xbmc.LOGDEBUG)
                return w_data


        if cache_key:
            cached_data = cache_manager.cache_get("TMDB", cache_key)
            if cached_data is not None:
                log(f"TMDB - CACHE HIT | SSD : {cache_key}", xbmc.LOGDEBUG)
                if "page" in cache_key:
                    cache_manager.window_cache_set(cache_key, cached_data)
                return cached_data


        params["api_key"] = self.api_key
        url = f"{self.base_url}/{endpoint}"
        log_params = {key: value for key, value in params.items() if key != "api_key"}
        log(f"TMDB - FETCH : {url} params: {log_params}", xbmc.LOGDEBUG)


        try:
            response = safe_get(self.session, url, params=params, timeout=15)
            if not response: return None
            data = response.json()


            try:
                mode = (self.addon.getSetting("filter_tmdb_language") or "SOFT").strip().upper()
            except Exception:
                mode = "SOFT"
            if not skip_filter and mode != "OFF":
                if isinstance(data, dict) and "results" in data:
                    asian_pattern = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")
                    asian_langs = {"ja", "ko", "zh"}
                    allowed_langs = {"en", "cs", "sk", "de", "fr", "pl", "es", "it"}
                    animation_genre_id = 16
                    before = len(data["results"])
                    filtered =[]
                    label = "VIETCONG FILTER"


                    # for item in data["results"]:
                    #     if "known_for_department" in item:
                    #         filtered.append(item)
                    #         continue
                    #     title = (item.get("title") or item.get("name") or "").strip()


                    # --- 1. KONTROLA PRO HERCE (OSOBY)

                    for item in data["results"]:
                        if "known_for_department" in item:
                            name = item.get("name", "")
                            if asian_pattern.search(name):
                                continue
                            filtered.append(item)
                            continue

                        # --- 2. KONTROLA PRO FILMY A SERIÁLY

                        title = (item.get("title") or item.get("name") or "").strip()

                        orig_title = (item.get("original_title") or item.get("original_name") or title).strip()
                        lang = (item.get("original_language") or "").lower()
                        genre_ids = item.get("genre_ids",[])

                        if asian_pattern.search(title):
                            continue

                        if mode == "SOFT":
                            is_asian = lang in asian_langs
                            is_animation = animation_genre_id in genre_ids
                            if is_asian and is_animation:
                                if title.lower() == orig_title.lower():
                                    continue
                            filtered.append(item)

                        elif mode == "HARD":
                            if lang not in allowed_langs:
                                continue
                            filtered.append(item)

                    after = len(filtered)
                    if before != after:
                        log(f"TMDB FILTER - Odstraněno {before - after} položek [ {label} - {mode} ].", xbmc.LOGINFO)
                    data["results"] = filtered


            cacheable_detail = (isinstance(data, dict) and "status_code" not in data
                                and data.get("success") is not False)
            if cache_key and (not automatic_detail_cache or cacheable_detail):
                cache_manager.cache_set("TMDB", cache_key, data)
                if "page" in cache_key:
                    cache_manager.window_cache_set(cache_key, data)
            return data
        except Exception as e:
            log(f"TMDB - FETCH ERROR: {str(e)}", xbmc.LOGERROR)
            return None


    def get_genres(self, media_type):

        lookup_type = "tv" if media_type == "episode" else media_type

        if lookup_type in self.genres_cache:
            return self.genres_cache[lookup_type]

        cache_key = f"genres_{lookup_type}"
        endpoint = f"genre/{lookup_type}/list"

        data = self._fetch(endpoint, cache_key=cache_key)

        if not data or "genres" not in data:
            return {}

        genres_dict = {g["id"]: g["name"] for g in data.get("genres", [])}
        self.genres_cache[lookup_type] = genres_dict
        return genres_dict


    def get_localized_title(self, media_type, tmdb_id, lang_code):

        """
        TMDB :: LOCALE
        -- Získá lokalizovaný název (např. český) pro dané TMDB ID.
        -- Slouží k tomu, aby se při hledání zdrojů (např. z Traktu) použil český název místo anglického.
        """

        if not tmdb_id:
            return None

        lang_formatted = f"{lang_code}-{lang_code.upper()}"

        details = self.get_full_details(media_type, tmdb_id, lang=lang_formatted)

        if details:
            title = details.get('title') or details.get('name')
            log(f"TMDB LOKALIZACE - Nalezen název : '{title}' pro ID {tmdb_id} v jazyce {lang_formatted}", xbmc.LOGDEBUG)
            return title

        log(f"TMDB LOKALIZACE - Lokalizovaný název nenalezen pro ID {tmdb_id}", xbmc.LOGWARNING)
        return None


    def list_items(
        self,
        data,
        media_type,
        page,
        action_name,
        context_type="general",
        extra_params=None,
    ):
        results = data.get("results",[])
        total_pages = data.get("total_pages", 1)
        current_page = data.get("page", page)

        for r in results:
            item_media_type = r.get("media_type", media_type)
            if item_media_type not in ["movie", "tv"]:
                continue
            tmdb_id = r.get("id")

            item_data = r
            props = self._build_metadata_props(item_data, item_media_type)
            props["tmdb_id"] = tmdb_id
            title = props.get("title", "Neznámý titul")
            label = (
                f"{props.get('title', 'Neznámý titul')} ({props.get('year', '????')})"
            )
            list_item = xbmcgui.ListItem(label=label)
            self._populate_list_item(
                list_item, props, item_media_type, context_type=context_type,
                source_list=context_type if context_type in ('watch_later', 'watchlist', 'favorites', 'rated') else None
            )


        if total_pages > 1 and current_page < total_pages:
            headers_for_paging = {
                'x-pagination-page-count': str(total_pages),
                'x-pagination-page': str(current_page)
            }
            paging_params = {
                "type": media_type,
                "page": str(int(current_page) + 1),
            }
            if extra_params:
                paging_params.update(extra_params)

            add_next_page_item(self._handle, action_name, headers_for_paging, current_page, **paging_params)
        content_type = "movies" if media_type == "movie" else "tvshows"
        view_type = "movies" if media_type == "movie" else "tvshows"
        xbmcplugin.setContent(self._handle, content_type)
        set_view_mode(self._handle, self.addon, content_type, view_type)
        xbmcplugin.endOfDirectory(self._handle)


    def get_recommendations_raw(self, media_type, tmdb_id):

        """
        TMDB :: RAW
        -- Vrátí surový seznam doporučení pro dané TMDB ID.
        """

        endpoint = f"{media_type}/{tmdb_id}/recommendations"
        cache_key = f"recs_raw_{media_type}_{tmdb_id}"
        data = self._fetch(endpoint, params={"page": 1}, cache_key=cache_key)
        return data.get("results", []) if data else[]


    def search_raw(self, query, year=None, media_type=None, page=1):
        endpoint = "search/multi" if not media_type else f"search/{media_type}"
        params = {"query": query, "page": page}
        if year:
            params["year"] = year
        cache_key = f"search_raw_{media_type}_{query}_{year}_{page}"
        return self._fetch(endpoint, params, cache_key=cache_key)


    def browse_by_submenu(self, media_type=None):

        if not media_type:
            media_type = "movie"

        options =[
            ("ŽÁNRY", "listing_genre_category", Icons.GENTRE),
            ("ROKY", "listing_year_category", Icons.YEAR),
            ("STUDIA", "listing_studio_category", Icons.MOVIE),
            ("POSKYTOVATELÉ", "list_providers", Icons.PROVIDER),
            ("TRENDY", "trending_submenu", Icons.RATING),
            ("NEJLEPŠÍ HODNOCENÍ", "listing_top_rated", Icons.TOP),
            ("NOW PLAYING / UPCOMING", "listing_now_playing", Icons.PLAY),
            ("NAJDĚTE OBSAH (DISCOVER)", "listing_discover", Icons.DISCOVER),
        ]

        for label, action, icon in options:
            list_item = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]►[/COLOR][/B]{label}")
            try:
                list_item.setArt({"icon": icon, "fanart": self.addon.getAddonInfo('fanart')})
            except Exception:
                pass
            url = get_url(action=action, type=media_type, page="1")
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)


        list_item = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]NÁHODNÝ VÝBĚR")
        try:
            list_item.setArt({"icon": Icons.RANDOM, "fanart": self.addon.getAddonInfo('fanart')})
        except Exception:
            pass
        url = get_url(action="randomised_submenu", type=media_type)
        xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        set_view_mode(self._handle, self.addon, "files", "movies_submenu" if media_type == "movie" else "tvshows_submenu")
        xbmcplugin.endOfDirectory(self._handle)


    def randomised_submenu(self, media_type=None):

        if not media_type:
            media_type = "movie"

        options =[
            ("NÁHODNÝ PODLE ŽÁNRU", "list_random_genre", Icons.GENTRE),
            ("NÁHODNÝ PODLE POSKYTOVATELE", "list_random_provider", Icons.PROVIDER),
            ("NÁHODNÝ PODLE STUDIA", "list_random_studio", Icons.MOVIE),
            ("NÁHODNÝ PODLE KLÍČOVÉHO SLOVA", "list_random_keyword", Icons.KEYWORD),
            ("NÁHODNÝ PODLE SÍTĚ (TV)", "list_random_network", Icons.NETWORK),
        ]

        for label, action, icon in options:
            list_item = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}")
            try:
                list_item.setArt({"icon": icon, "fanart": self.addon.getAddonInfo('fanart')})
            except Exception:
                pass
            url = get_url(action=action, type=media_type, page="1")
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        set_view_mode(self._handle, self.addon, "files", "movies_submenu" if media_type == "movie" else "tvshows_submenu")
        xbmcplugin.endOfDirectory(self._handle)


    def get_full_details(self, media_type, tmdb_id, lang=None):

        """
        TMDB :: FULL DETAILS
        -- Centrální funkce pro načtení kompletních detailů ( včetně credits ) pro film nebo seriál.
        -- Plně integrováno s cache_manager (RAM + SQL).
        -- Validuje kompletnost dat (fix pro chybějící herce).
        """

        if not tmdb_id or not media_type:
            return None


        cache_key_lang_suffix = f"_{lang}" if lang and lang != self.language else ""
        cache_key = f"{media_type}_detail_{tmdb_id}{cache_key_lang_suffix}"

        endpoint = f"{media_type}/{tmdb_id}"


        detail_data = cache_manager.cache_get("TMDB", self._cache_variant(cache_key, lang))


        is_valid = False
        if detail_data:


            if "credits" in detail_data or "aggregate_credits" in detail_data:
                is_valid = True


            if not is_valid:
                log(f"TMDB CACHE - Data pro ID {tmdb_id} jsou nekompletní (chybí herci). Vynucuji stažení.", xbmc.LOGINFO)

        if is_valid:
            return detail_data


        detail_data = self._fetch(
            endpoint,
            params={"append_to_response": "credits,aggregate_credits"},
            cache_key=cache_key,
            language_override=lang
        )

        return detail_data


    def get_season_details_raw(self, tmdb_id, season_number):
        endpoint = f"tv/{tmdb_id}/season/{season_number}"
        cache_key = f"tv_season_{tmdb_id}_{season_number}"
        return self._fetch(endpoint, cache_key=cache_key)


    def get_details_raw(self, tmdb_id, media_type):
        return self.get_full_details(media_type, tmdb_id)


    def get_movie_details_raw(self, tmdb_id):
        detail_data = self.get_full_details("movie", tmdb_id)
        return self._build_metadata_props(detail_data, "movie") if detail_data else None


    def _build_metadata_props(self, item_data, media_type, genre_names=None):
        props = {}
        props["tmdb_id"] = item_data.get("id")
        props["media_type"] = media_type
        props["title"] = item_data.get("title") or item_data.get("name") or ""
        props["original_title"] = (
            item_data.get("original_title") or item_data.get("original_name") or ""
        )
        rd = (item_data.get("air_date") if media_type == "episode" else
              item_data.get("release_date") or item_data.get("first_air_date")) or ""
        props["year"] = rd[:4] if rd else ""
        props["premiered"] = rd
        props["plot"] = item_data.get("overview") or ""
        props["tagline"] = item_data.get("tagline") or ""
        vote = item_data.get("vote_average")
        props["rating"] = f"{vote:.1f}" if vote is not None else ""
        props["votes"] = str(item_data.get("vote_count") or "")
        runtime = item_data.get("runtime") or (
            item_data.get("episode_run_time", [0])[0]
            if item_data.get("episode_run_time")
            else 0
        )
        props["duration"] = str(runtime * 60) if runtime else ""
        genre_ids = item_data.get("genre_ids", []) or[
            g.get("id") for g in item_data.get("genres", [])
        ]
        genres_dict = genre_names if genre_names is not None else self.get_genres(media_type)
        props["genre"] = ", ".join([genres_dict.get(gid) for gid in genre_ids if gid in genres_dict]
        )
        studios = item_data.get("production_companies", []) or item_data.get(
            "networks", []
        )
        props["studio"] = ", ".join([p.get("name") for p in studios])
        mpaa = ""
        country_code = self.language.split("-")[1].upper()
        if media_type == "movie":
            release_dates = item_data.get("release_dates", {}).get("results",[])
            for country in release_dates:
                if country.get("iso_3166_1") == country_code:
                    mpaa = country.get("release_dates", [{}])[0].get(
                        "certification", ""
                    )
                    if mpaa:
                        break
        elif media_type == "tv":
            content_ratings = item_data.get("content_ratings", {}).get("results",[])
            for country in content_ratings:
                if country.get("iso_3166_1") == country_code:
                    mpaa = country.get("rating", "")
                    if mpaa:
                        break
        props["mpaa"] = mpaa
        ext = item_data.get("external_ids") or {}
        props["imdb_id"] = ext.get("imdb_id") or ""
        props["tvdb_id"] = ext.get("tvdb_id") or ""


        credits = item_data.get("credits") or item_data.get("aggregate_credits") or {}
        cast_list = credits.get("cast",[])
        crew_list = credits.get("crew", [])


        props["cast"] = " / ".join([c.get("name") for c in cast_list[:10]])


        cast_full =[]
        for c in cast_list:
            actor_dict = {
                "name": c.get("name", ""),
                "character": c.get("character", ""),
                "order": c.get("order", 0)
            }
            pp = c.get("profile_path")
            if pp:


                actor_dict["thumbnail"] = f"{self.image_base_url}w185{pp}"
            cast_full.append(actor_dict)
        props["cast_full"] = cast_full

        directors =[c.get("name") for c in crew_list if c.get("job") == "Director"]
        creators =[c.get("name") for c in item_data.get("created_by", [])]
        props["director"] = ", ".join(directors or creators)

        poster_path = item_data.get("poster_path")
        backdrop_path = item_data.get("backdrop_path")
        props["poster"] = (
            f"{self.image_base_url}w500{poster_path}" if poster_path else ""
        )
        props["fanart"] = (
            f"{self.image_base_url}original{backdrop_path}" if backdrop_path else ""
        )
        props["thumb"] = props["poster"]
        if media_type == "episode":
            still_path = item_data.get("still_path")
            if still_path:
                props["thumb"] = f"{self.image_base_url}w500{still_path}"
        if media_type == "tv":
            props["number_of_seasons"] = str(item_data.get("number_of_seasons") or "")
            props["number_of_episodes"] = str(item_data.get("number_of_episodes") or "")
        return props


    def fill_list_item(self, list_item, props, media_type):

        """
        TMDB :: FILL LIST ITEM (KODI 22 & YATSE OPTIMIZED)
        -- Centralizovaná metoda pro nastavení metadat a herců.
        """

        info_tag = list_item.getVideoInfoTag()

        normalized_type = media_type
        if media_type in ("tv", "show"):
            normalized_type = "tvshow"
        info_tag.setMediaType(normalized_type)

        if props.get("tmdb_id"):
            info_tag.setUniqueIDs({'tmdb': str(props["tmdb_id"])})

        if props.get("title"): info_tag.setTitle(props["title"])
        if props.get("original_title"): info_tag.setOriginalTitle(props["original_title"])
        if props.get("plot"): info_tag.setPlot(props["plot"])
        if props.get("tagline"): info_tag.setTagLine(props["tagline"])
        if props.get("mpaa"): info_tag.setMpaa(props["mpaa"])
        if props.get("imdb_id"): info_tag.setIMDBNumber(props["imdb_id"])
        if props.get("premiered"): info_tag.setPremiered(props["premiered"])
        if props.get("tv_show_title"): info_tag.setTvShowTitle(props["tv_show_title"])

        if props.get("year") and str(props["year"]).isdigit():
            info_tag.setYear(int(props["year"]))

        if props.get("genre"):
            genres = props["genre"] if isinstance(props["genre"], list) else[g.strip() for g in str(props["genre"]).split(",")]
            info_tag.setGenres(genres)

        if props.get("duration") and str(props["duration"]).isdigit():
            info_tag.setDuration(int(props["duration"]))

        if props.get("rating"):
            try: info_tag.setRating(float(props["rating"]))
            except: pass

        if props.get("votes") and str(props["votes"]).isdigit():
            info_tag.setVotes(int(props["votes"]))

        if props.get("studio"):
            studios = props["studio"] if isinstance(props["studio"], list) else[s.strip() for s in str(props["studio"]).split(",")]
            info_tag.setStudios(studios)

        if props.get("director"):
            directors = props["director"] if isinstance(props["director"], list) else [d.strip() for d in str(props["director"]).split(",")]
            info_tag.setDirectors(directors)

        if props.get("season") is not None:
            try: info_tag.setSeason(int(props["season"]))
            except: pass

        if props.get("episode"):
            try: info_tag.setEpisode(int(props["episode"]))
            except: pass

        # --- SEKCE HERCŮ (MODERNÍ KODI 22 OBJEKTY)

        cast_list = []
        for actor in props.get("cast_full",[]):
            a = xbmc.Actor(
                name=actor.get("name", "Neznámý"),
                role=actor.get("character", ""),
                thumbnail=actor.get("thumbnail", "")
            )
            cast_list.append(a)

        if cast_list:
            info_tag.setCast(cast_list)

        # --- GRAFIKA (ART)

        art = {
            "poster": props.get("poster"),
            "fanart": props.get("fanart"),
            "thumb": props.get("thumb"),
            "icon": props.get("thumb") or props.get("poster")
        }
        list_item.setArt({k: v for k, v in art.items() if v})

        # --- DODATEČNÉ VLASTNOSTI

        for key, val in props.items():
            if key == "cast_full": continue
            vs = val if isinstance(val, str) else str(val)
            list_item.setProperty(key, vs)


    def _populate_list_item(self, list_item, props, media_type, source_list=None, context_menu_to_add=None, context_type="general", is_ai_daily=False):

        self.fill_list_item(list_item, props, media_type)


        meta_key = store_meta_in_cache(props)

        is_folder = True

        if media_type == "movie":
            is_movie_autoplay_on = (self.main_window.getProperty("player.movie.autoplay.enabled") == "true")

            if is_movie_autoplay_on:
                url = get_url(action="create_movie_playlist_action", meta=meta_key)
                is_folder = False
                list_item.setProperty("IsPlayable", "true")
            else:
                url_params = {'action': 'find_sources', 'meta': meta_key}
                if source_list: url_params['source_list'] = source_list
                url = get_url(**url_params)
                is_folder = True
                list_item.setProperty("IsPlayable", "false")
        else:
            url_params = {
                'action': "listing_tmdb_tv",
                'tmdb_id': str(props.get("tmdb_id", "")),
                'meta': meta_key,
            }
            if source_list: url_params['source_list'] = source_list

            url = get_url(**url_params)
            is_folder = True
            list_item.setProperty("IsPlayable", "false")

        try:
            list_item.setProperty("context", str(context_type or "general"))
        except Exception: pass

        context_menu_items = self._build_context_menu(
            props.get("tmdb_id"), media_type, props.get("title"), context_type or "general", props,
            is_ai_daily=is_ai_daily
        )
        if context_menu_to_add:
            context_menu_items = context_menu_to_add + context_menu_items

        list_item.addContextMenuItems(_sf_cm_items(context_menu_items), replaceItems=False)
        list_item.setProperty("tmdb_id", str(props.get("tmdb_id", "")))
        list_item.setProperty("dbid", str(props.get("tmdb_id", "")))
        list_item.setProperty("dbtype", "tmdb")
        list_item.setProperty("mediatype", media_type)
        xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=is_folder)





    # ================================================================================== #
    # ---------------------------------------------------------------------------------- #
    # ---                 CENTRÁLNÍ DEFINICE  ::  KONTEXTOVÝCH MENU                  --- #
    # ---------------------------------------------------------------------------------- #
    # ================================================================================== #



    def _build_context_menu(self, tmdb_id, media_type, title, context_type="general", props=None, is_ai_daily=False):

        """
        CONTEXT :: CENTRAL MENU BUILDER
        -- CENTRÁLNÍ FUNKCE PRO GENEROVÁNÍ KONTEXTOVÉHO MENU (TMDB KATALOGY)
        """

        import base64
        context_menu_items =[]
        props = props or {}

        # Bezpečné předpočítání payloadu
        share_payload = ""
        if self.addon.getSettingBool('enable_community_sharing'):
            try:
                share_data = {
                    'title': props.get('title'),
                    'tmdb_id': props.get('tmdb_id'),
                    'media_type': media_type,
                    'year': props.get('year'),
                    'poster': props.get('poster'),
                    'plot': props.get('plot')
                }
                raw = json.dumps(share_data, ensure_ascii=False).encode('utf-8')
                share_payload = base64.urlsafe_b64encode(raw).decode('utf-8')
            except Exception:
                pass



        # ================================================================================== #
        # ---  CENTRÁLNÍ SLOVNÍK VŠECH POLOŽEK   ( Pro snadnou úpravu názvů a akcí )     --- #
        # ================================================================================== #



# --- ESTUARY
#
#
#         ITEMS = {
#             'watch_later': (f"[COLOR {Colors.ORANGE}]► SLEDOVAT POZDĚJI ◄[/COLOR]", f"RunPlugin({get_url(action='add_to_watch_later', meta=json.dumps(props))})"),
#             'watch_later_remove': (f"[COLOR {Colors.ORANGE}]►[/COLOR][COLOR {Colors.RED}]ODEBRAT Z WATCH LATER[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'find_similar': (f"[COLOR {Colors.YELLOW}]► HLEDAT  PODOBNÉ ◄[/COLOR]", f"RunPlugin({get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})"),
#             'ai_similar': (f"[COLOR {Colors.ORCHID}]► AI - PODOBNOST ◄[/COLOR]", f"Container.Update({get_url(action='ai_similar', title=title, year=props.get('year', ''), media_type=media_type)})"),
#             'ai_trivia': (f"[COLOR {Colors.ORCHID}]► AI - ZAJÍMAVOST ◄[/COLOR]", f"RunPlugin({get_url(action='gemini_trivia', title=title, year=props.get('year', ''), media_type=media_type)})"),
#             'play_trailer': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILERY ◄[/COLOR]", f"RunPlugin({get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'share': (f"[COLOR {Colors.ORANGE}]► SDÍLET  OSTATNÍM ◄[/COLOR]", f"RunPlugin({get_url(action='share_menu', payload=share_payload)})") if share_payload else None,
#             'library': (f"[COLOR {Colors.ORANGE}]► OSOBNÍ KNIHOVNA ◄[/COLOR]", f"RunPlugin({get_url(action='library', tmdb_id=tmdb_id, media_type=media_type, title=title, year=props.get('year', ''))})"),
#             'player_menu': (f"[B][COLOR {Colors.LIMEGREEN}][  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]", f"RunPlugin({get_url(action='show_player_menu', tmdb_id=tmdb_id, media_type=media_type, title=title, context=context_type, props=json.dumps(props))})"),
#             
#             'tmdb_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO WATCHLISTU ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'tmdb_watchlist_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z WATCHLISTU ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'tmdb_favorites': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO OBLÍBENÝCH ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'tmdb_favorites_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z OBLÍBENÝCH ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'tmdb_rating': (f"[COLOR {Colors.ORANGE}]► PŘIDAT SVÉ HODNOCENÍ ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})"),
#             'tmdb_rating_remove': (f"[COLOR {Colors.RED}]► ODEBRAT SVÉ HODNOCENÍ ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_rating', tmdb_id=tmdb_id, media_type=media_type)})"),
#             
#             'trakt_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO TRAKTLIST ◄[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist_tmdb', media_type='show' if media_type == 'tv' else 'movie', tmdb_id=tmdb_id)})"),
#             'refresh_cache': (f"[COLOR {Colors.LIMEGREEN}]► RE-FRESH  CACHE ◄[/COLOR]", f"RunPlugin({get_url(action='clear_csfd_cache')})"),
#             'settings': (f"[B][COLOR {Colors.LIMEGREEN}][  ○  NASTAVENÍ  ○  ] [/COLOR][/B]", "Addon.OpenSettings(plugin.video.play_er)")
#         }
#
#
# --- ARCTIC FUSE 3


        ITEMS = {
            'ai_daily_load': (f"[COLOR {Colors.ORCHID}]► AI - TODAY LOAD[/COLOR]", f"RunPlugin({get_url(action='ai_daily_refresh')})") if is_ai_daily else None,
            'watch_later': (f"[COLOR {Colors.ORANGE}]► SLEDOVAT POZDĚJI[/COLOR]", f"RunPlugin({get_url(action='add_to_watch_later', meta=json.dumps(props))})"),
            'watch_later_remove': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT Z WATCHLATER[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type, **({'season': props.get('season'), 'episode': props.get('episode')} if media_type == 'episode' else {}))})"),
            'find_similar': (f"[COLOR {Colors.ORANGE}]► HLEDAT PODOBNÉ[/COLOR]", f"RunPlugin({get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})"),
            'ai_similar': (f"[COLOR {Colors.ORCHID}]► AI - PODOBNOST[/COLOR]", f"Container.Update({get_url(action='ai_similar', title=title, year=props.get('year', ''), media_type=media_type)})"),
            'ai_trivia': (f"[COLOR {Colors.ORCHID}]► AI - ZAJÍMAVOST[/COLOR]", f"RunPlugin({get_url(action='gemini_trivia', title=title, year=props.get('year', ''), media_type=media_type)})"),
            'play_trailer': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILER[/COLOR]", f"RunPlugin({get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=media_type)})"),
            'share': (f"[COLOR {Colors.ORANGE}]► SDÍLET OSTATNÍM[/COLOR]", f"RunPlugin({get_url(action='share_menu', payload=share_payload)})") if share_payload else None,
            'library': (f"[COLOR {Colors.ORANGE}]► OSOBNÍ KNIHOVNA[/COLOR]", f"RunPlugin({get_url(action='library', tmdb_id=tmdb_id, media_type=media_type, title=title, year=props.get('year', ''))})"),
            'player_menu': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu', tmdb_id=tmdb_id, media_type=media_type, title=title, context=context_type, props=json.dumps(props))})"),
            
            'tmdb_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT WATCHLIST[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
            'tmdb_watchlist_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z WATCHLISTU[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
            'tmdb_favorites': (f"[COLOR {Colors.ORANGE}]► PŘIDAT OBLÍBENÉ[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
            'tmdb_favorites_remove': (f"[COLOR {Colors.RED}]► ODEBRAT Z OBLÍBENÝCH[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
            'tmdb_rating': (f"[COLOR {Colors.ORANGE}]► PŘIDAT HODNOCENÍ[/COLOR]", f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})"),
            'tmdb_rating_remove': (f"[COLOR {Colors.RED}]► ODEBRAT HODNOCENÍ[/COLOR]", f"RunPlugin({get_url(action='tmdb_remove_rating', tmdb_id=tmdb_id, media_type=media_type)})"),
            
            'trakt_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT TRAKTLIST[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist_tmdb', media_type='show' if media_type == 'tv' else 'movie', tmdb_id=tmdb_id)})"),
            'refresh_cache': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='clear_csfd_cache')})"),
            'settings': (f"[COLOR {Colors.LIMEGREEN}][ MENU NASTAVENÍ ][/COLOR]", "Addon.OpenSettings(plugin.video.play_er)")
        }


        # --- Override pro odstraňování

        if context_type == 'watch_later': ITEMS['watch_later'] = ITEMS['watch_later_remove']
        if context_type == 'watchlist': ITEMS['tmdb_watchlist'] = ITEMS['tmdb_watchlist_remove']
        if context_type == 'favorites': ITEMS['tmdb_favorites'] = ITEMS['tmdb_favorites_remove']
        if context_type == 'rated': ITEMS['tmdb_rating'] = ITEMS['tmdb_rating_remove']


        layout = ['watch_later', 'ai_daily_load', 'ai_trivia', 'ai_similar', 'find_similar', 'share', 'play_trailer', 'library', 'player_menu', 'tmdb_watchlist', 'trakt_watchlist', 'tmdb_rating', 'tmdb_favorites', 'refresh_cache', 'settings']
        if context_type == 'ai_daily_empty':
            layout = ['ai_daily_load']


        for key in layout:
            if ITEMS.get(key):
                context_menu_items.append(ITEMS[key])

        return context_menu_items



    # ================================================================================== #
    # ---------------------------------------------------------------------------------- #
    # ---                 CENTRÁLNÍ DEFINICE  ::  KONTEXTOVÉHO MENU                  --- #
    # ---------------------------------------------------------------------------------- #
    # ================================================================================== #





    def search(self, name=None, media_type=None):
        if not name:
            kb = xbmc.Keyboard(
                "",
                f"[COLOR {Colors.ORANGE}] ○  ZADEJTE [ FUCKING ] NÁZEV  ○ [/COLOR]",
            )
            kb.doModal()
            if not kb.isConfirmed() or not kb.getText().strip():
                try:
                    xbmcplugin.endOfDirectory(self._handle, succeeded=False)
                except Exception:
                    pass
                return
            name = kb.getText().strip()
        try:
            history_path = xbmcvfs.translatePath(
                "special://userdata/DATA--PLAY/HISTORY/HISTORY.TXT"
            )
            if xbmcvfs.exists(history_path):
                with SafeVFSFile(history_path, "r") as f:
                    lh = f.read().splitlines()
                if name not in lh:
                    if len(lh) >= 10:
                        del lh[-1]
                    lh.insert(0, name)
                    with SafeVFSFile(history_path, "w") as f:
                        f.write("\n".join(lh))
            else:
                with SafeVFSFile(history_path, "w") as f:
                    f.write(name)
        except Exception as e:
            log(f"TMDB SEARCH - Chyba při ukládání do historie hledání : {e}", xbmc.LOGERROR)
        endpoint = "search/multi" if not media_type else f"search/{media_type}"
        params = {"query": name, "page": 1}
        data = self._fetch(endpoint, params)
        if not data or not data.get("results"):


            notify_info("Žádné výsledky nenalezeny", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        self.list_items(data, media_type or "multi", 1, "search_tmdb")


    def list_trending(self, page, media_type, time_window="week"):
        endpoint = f"trending/{media_type}/{time_window}"
        cache_key = f"trending_{media_type}_{time_window}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(
                data, media_type, page, "listing_trending", extra_params={"time_window": time_window}
            )

    def trending_submenu(self, media_type):
        options =[
            (
                "DNES",
                "day",
                Icons.RATING,
            ),
            (
                "TENTO TÝDEN",
                "week",
                Icons.RATING,
            ),
        ]
        for label, time_window, icon in options:
            list_item = xbmcgui.ListItem(
                label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}"
            )
            list_item.setArt({"icon": icon, "fanart": self.addon.getAddonInfo('fanart')})
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(label)
            info_tag.setPlot(f"Zobrazit trendy {media_type} za poslední den/týden.")
            url = get_url(
                action="listing_trending",
                type=media_type,
                time_window=time_window,
                page="1",
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        pass

        xbmcplugin.endOfDirectory(self._handle)

    def list_discover(self, page, media_type):
        endpoint = f"discover/{media_type}"
        cache_key = f"discover_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page, "sort_by": "popularity.desc"}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_discover")

    def list_top_rated(self, page, media_type):
        endpoint = f"{media_type}/top_rated"
        cache_key = f"top_rated_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_top_rated")

    def list_now_playing(self, page, media_type):
        if media_type != "movie":
            return
        endpoint = f"{media_type}/now_playing"
        cache_key = f"now_playing_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_now_playing")

    def list_upcoming(self, page, media_type):
        if media_type != "movie":
            return
        endpoint = f"{media_type}/upcoming"
        cache_key = f"upcoming_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_upcoming")

    def list_airing_today(self, page, media_type):
        if media_type != "tv":
            return
        endpoint = f"{media_type}/airing_today"
        cache_key = f"airing_today_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_airing_today")

    def list_on_the_air(self, page, media_type):
        if media_type != "tv":
            return
        endpoint = f"{media_type}/on_the_air"
        cache_key = f"on_the_air_{media_type}_page_{page}"
        data = self._fetch(endpoint, params={"page": page}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_on_the_air")

    def list_by_genre(self, page, media_type, genre_id):
        endpoint = f"discover/{media_type}"
        cache_key = f"genre_{media_type}_{genre_id}_page_{page}"
        data = self._fetch(endpoint, params={"page": page, "with_genres": genre_id}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_genre", extra_params={"id": genre_id})

    def list_by_year(self, page, media_type, year):
        endpoint = f"discover/{media_type}"
        year_param = (
            "primary_release_year" if media_type == "movie" else "first_air_date_year"
        )
        cache_key = f"year_{media_type}_{year}_page_{page}"
        data = self._fetch(endpoint, params={"page": page, year_param: year}, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "listing_year", extra_params={"id": year})

    def list_genres_category(self, media_type):
        genres = self.get_genres(media_type)
        for genre_id, genre_name in genres.items():

            if not genre_name:
                continue

            list_item = xbmcgui.ListItem(label=str(genre_name).strip())
            list_item.setArt(
                {
                    "icon": Icons.GENTRE
                }
            )
            url = get_url(
                action="listing_genre", type=media_type, id=str(genre_id), page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        set_view_mode(
            self._handle, self.addon, "files", "movies_submenu" if media_type == "movie" else "tvshows_submenu"
        )
        xbmcplugin.endOfDirectory(self._handle)


    def list_years_category(self, media_type):
        current_year = datetime.now().year
        years = list(range(current_year, current_year - 30, -1))
        for year in years:
            list_item = xbmcgui.ListItem(label=str(year))
            list_item.setArt(
                {
                    "icon": Icons.YEAR
                }
            )
            url = get_url(
                action="listing_year", type=media_type, id=str(year), page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        set_view_mode(
            self._handle, self.addon, "files", "movies_submenu" if media_type == "movie" else "tvshows_submenu"
        )
        xbmcplugin.endOfDirectory(self._handle)

    def list_studios_category(self, media_type):
        if media_type != "movie":


            notify_info("Filtr je dostupný pouze pro filmy", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return

        studios = {
            3: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PIXAR",
            4: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PARAMOUNT PICTURES",
            5: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]COLUMBIA PICTURES",
            12: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]NEW LINE CINEMA",
            14: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MIRAMAX",
            21: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MGM",
            25: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]20TH CENTURY FOX",
            33: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]UNIVERSAL PICTURES",
            41: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]ORION PICTURES",
            49: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]HBO",
            174: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]WARNER BROS.",
            420: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]A24",
            443: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MARVEL STUDIOS",
            521: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]DREAMWORKS",
            694: f"[B][COLOR {Colors.ORANGE}]►[/COLOR][/B]STUDIOCANAL",
            856: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]WILD BUNCH",
            1632: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]LIONSGATE",
            2221: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]SUMMIT ENTERTAINMENT",
            7295: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]RELATIVITY MEDIA",
            7493: f"[B][COLOR {Colors.ORANGE}]►[/COLOR][/B]BBC FILMS",
            10104: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]REGENCY ENTERTAINMENT",
            10146: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]FOCUS FEATURES",
            13240: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]ANNAPURNA PICTURES",
        }
        for studio_id, studio_name in sorted(studios.items(), key=lambda item: item[1]):
            list_item = xbmcgui.ListItem(label=studio_name)
            list_item.setArt(
                {
                    "icon": Icons.MOVIE
                }
            )
            url = get_url(
                action="listing_studio", type=media_type, id=str(studio_id), page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        set_view_mode(self._handle, self.addon, "files", "movies_submenu")
        xbmcplugin.endOfDirectory(self._handle)

    def list_by_studio(self, page, media_type, studio_id):
        endpoint = f"discover/{media_type}"
        params = {
            "page": page,
            "with_companies": studio_id,
            "sort_by": "popularity.desc",
        }
        cache_key = f"studio_{media_type}_{studio_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data and data.get("results"):
            self.list_items(data, media_type, page, "listing_studio", extra_params={"id": studio_id})
        else:


            notify_info("Nebyly nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)

    def list_providers(self, media_type):
        endpoint = f"watch/providers/{media_type}"
        params = {"watch_region": self.language.split("-")[1]}
        data = self._fetch(endpoint, params, skip_filter=True)
        if data and data.get("results"):
            for provider in sorted(
                data["results"], key=lambda x: x.get("provider_name", "")
            ):
                list_item = xbmcgui.ListItem(label=provider.get("provider_name"))
                logo = (
                    f"{self.image_base_url}w92{provider.get('logo_path')}"
                    if provider.get("logo_path")
                    else ""
                )
                list_item.setArt({"icon": logo, "thumb": logo})
                url = get_url(
                    action="listing_provider",
                    id=provider.get("provider_id"),
                    type=media_type,
                    page="1",
                )
                xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        else:


            notify_info("Poskytovatelé nenalezeni", category="TMDB")

        set_view_mode(
            self._handle, self.addon, "files", "movies_submenu" if media_type == "movie" else "tvshows_submenu"
        )
        xbmcplugin.endOfDirectory(self._handle)

    def list_by_provider(self, provider_id, media_type, page):
        endpoint = f"discover/{media_type}"
        params = {
            "with_watch_providers": provider_id,
            "watch_region": self.language.split("-")[1],
            "page": page,
            "sort_by": "popularity.desc",
        }
        data = self._fetch(endpoint, params)
        if data and data.get("results"):
            self.list_items(
                data, media_type, page, "listing_provider", extra_params={"id": provider_id}
            )
        else:


            notify_info("Nebyly nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)

    def list_highest_revenue(self, page, media_type):
        if media_type != "movie":
            return
        endpoint = "discover/movie"
        params = {"sort_by": "revenue.desc", "page": page}


        cache_key = f"highest_revenue_movie_page_{page}"

        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data:
            self.list_items(data, "movie", page, "list_highest_revenue")

    def list_most_voted(self, page, media_type):
        endpoint = f"discover/{media_type}"
        params = {"sort_by": "vote_count.desc", "page": page}


        cache_key = f"most_voted_{media_type}_page_{page}"

        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data:
            self.list_items(data, media_type, page, "list_most_voted")

    def list_random_genre(self, media_type):
        if not media_type:
            log("TMDB | RANDOM : Funkce list_random_genre voláno bez media_type", xbmc.LOGERROR)
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        genres = self.get_genres(media_type)
        for genre_id, name in sorted(genres.items(), key=lambda item: item[1]):
            list_item = xbmcgui.ListItem(label=name)
            url = get_url(
                action="random_genre_content", id=genre_id, type=media_type, page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)
        xbmcplugin.endOfDirectory(self._handle)

    def list_random_genre_content(self, genre_id, media_type, page):
        endpoint = f"discover/{media_type}"
        params = {"with_genres": genre_id, "page": page}
        cache_key = f"random_genre_{media_type}_{genre_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data and data.get("results"):
            random.shuffle(data["results"])
            self.list_items(
                data,
                media_type,
                page,
                "random_genre_content",
                extra_params={"id": genre_id},
            )
        else:


            notify_info("Nebyly nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)

    def list_random_provider(self, media_type):
        endpoint = f"watch/providers/{media_type}"
        params = {"watch_region": self.language.split("-")[1]}
        data = self._fetch(endpoint, params, skip_filter=True)
        if data and data.get("results"):
            for provider in sorted(
                data["results"], key=lambda x: x.get("provider_name", "")
            ):
                list_item = xbmcgui.ListItem(label=provider.get("provider_name"))
                logo = (
                    f"{self.image_base_url}w92{provider.get('logo_path')}"
                    if provider.get("logo_path")
                    else ""
                )
                list_item.setArt({"icon": logo, "thumb": logo})
                url = get_url(
                    action="random_provider_content",
                    id=provider.get("provider_id"),
                    type=media_type,
                    page="1",
                )
                xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        else:


            notify_info("Poskytovatelé nenalezeni", category="TMDB")
        xbmcplugin.endOfDirectory(self._handle)

    def list_random_provider_content(self, provider_id, media_type, page):
        endpoint = f"discover/{media_type}"
        params = {
            "with_watch_providers": provider_id,
            "watch_region": self.language.split("-")[1],
            "page": page,
        }
        cache_key = f"random_provider_{media_type}_{provider_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data and data.get("results"):
            random.shuffle(data["results"])
            self.list_items(
                data,
                media_type,
                page,
                "random_provider_content",
                extra_params={"id": provider_id},
            )
        else:


            notify_info("Nebyly nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)


    def list_random_keyword_submenu(self):

        """
        SUBMENU :: NÁHODNÉ KLÍČOVÉ SLOVO
        -- Nabídne výběr: Filmy nebo Seriály.
        -- Pak se zavolá list_random_keyword s vybraným typem.
        """

        options =[
            (
                "FILMY",
                "movie",
                Icons.MOVIE,
            ),
            (
                "SERIÁLY",
                "tv",
                Icons.TVSHOW,
            ),
        ]
        for label, media_type, icon in options:
            list_item = xbmcgui.ListItem(
                label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}"
            )
            list_item.setArt({"icon": icon, "fanart": self.addon.getAddonInfo('fanart')})
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(label)
            info_tag.setPlot(f"[COLOR {Colors.ORANGE}]► Podle klíčových slov : {label}[/COLOR]")
            url = get_url(
                action="list_random_keyword",
                type=media_type,
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        xbmcplugin.endOfDirectory(self._handle)


    def list_random_keyword(self, media_type):
        kb = xbmc.Keyboard("", f"[COLOR {Colors.ORANGE}]○ ZADEJTE [ FUCKING ] TAGY ○[/COLOR]")
        kb.doModal()
        if not kb.isConfirmed() or not kb.getText().strip():
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        query = kb.getText().strip()
        endpoint = "search/keyword"
        data = self._fetch(endpoint, {"query": query}, skip_filter=True)
        if data and data.get("results"):
            for keyword in data.get("results",[]):
                list_item = xbmcgui.ListItem(label=keyword.get("name"))
                url = get_url(
                    action="random_keyword_content",
                    id=keyword.get("id"),
                    type=media_type,
                    page="1",
                )
                xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        else:


            notify_info("Klíčová slova nenalezena", category="TMDB")
        xbmcplugin.endOfDirectory(self._handle)

    def list_random_keyword_content(self, keyword_id, media_type, page):
        endpoint = f"discover/{media_type}"
        params = {"with_keywords": keyword_id, "page": page}
        cache_key = f"random_keyword_{media_type}_{keyword_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data and data.get("results"):
            random.shuffle(data["results"])
            self.list_items(
                data,
                media_type,
                page,
                "random_keyword_content",
                extra_params={"id": keyword_id},
            )
        else:
            notify_info("Pro klíčové slovo nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)

    def list_random_studio(self, media_type):
        if media_type != "movie":
            return
        studios = {
            3: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PIXAR",
            4: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PARAMOUNT PICTURES",
            5: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]COLUMBIA PICTURES",
            12: f"[B][COLOR {Colors.ORANGE}]►[/COLOR][/B]NEW LINE CINEMA",
            14: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MIRAMAX",
            21: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MGM",
            25: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]20TH CENTURY FOX",
            33: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]UNIVERSAL PICTURES",
            41: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]ORION PICTURES",
            174: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]WARNER BROS.",
            420: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]A24",
            443: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]MARVEL STUDIOS",
            521: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]DREAMWORKS",
            1632: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]LIONSGATE",
        }

        for studio_id, name in sorted(studios.items(), key=lambda item: item[1]):
            list_item = xbmcgui.ListItem(label=name)
            list_item.setArt({"icon": Icons.NETWORK})
            url = get_url(
                action="random_studio_content", id=studio_id, type=media_type, page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        xbmcplugin.endOfDirectory(self._handle)

    def list_random_studio_content(self, studio_id, media_type, page):
        self.list_by_studio(page, media_type, studio_id)

    def list_random_network(self, media_type):
        if media_type != "tv":
            return

        networks = {
            6: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]NBC",
            10: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]AXN",
            16: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]CINEMAX",
            43: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]NATIONAL GEOGRAPHIC",
            49: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]HBO",
            64: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]DISCOVERY CHANNEL",
            67: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]SHOWTIME",
            68: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]TBS",
            71: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]THE CW",
            83: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]TLC",
            91: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]ANIMAL PLANET",
            213: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]NETFLIX",
            318: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]STARZ",
            392: f"[B][COLOR {Colors.ORANGE}]►[/COLOR][/B]STARZPLAY",
            2552: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]APPLE TV+",
            2739: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]DISNEY+",
            3186: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]HBO MAX",
            3353: f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]PEACOCK",
        }

        for network_id, name in sorted(networks.items(), key=lambda item: item[1]):
            list_item = xbmcgui.ListItem(label=name)
            list_item.setArt({"icon": Icons.NETWORK})
            url = get_url(
                action="random_network_content",
                id=network_id,
                type=media_type,
                page="1",
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        xbmcplugin.endOfDirectory(self._handle)

    def list_random_network_content(self, network_id, media_type, page):
        endpoint = f"discover/{media_type}"
        params = {"with_networks": network_id, "page": page}
        cache_key = f"random_network_{media_type}_{network_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key=cache_key)
        if data and data.get("results"):
            random.shuffle(data["results"])
            self.list_items(
                data,
                media_type,
                page,
                "random_network_content",
                extra_params={"id": network_id},
            )
        else:


            notify_info("Nebyly nalezeny žádné položky", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)

    def list_actors(self, page=1):
        cache_key = f"actors_popular_page_{page}"
        data = self._fetch("person/popular", {"page": page}, cache_key=cache_key)
        if data:
            self._list_people(data, page, "list_actors")

    def trending_actors_submenu(self):
        options =[
            (
                "DNES",
                "day",
                Icons.WATCH,
            ),
            (
                "TENTO TÝDEN",
                "week",
                Icons.WATCH,
            ),
        ]
        for label, time_window, icon in options:
            list_item = xbmcgui.ListItem(
                label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}"
            )
            list_item.setArt({"icon": icon})
            url = get_url(
                action="list_trending_actors", time_window=time_window, page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)
        xbmcplugin.endOfDirectory(self._handle)

    def list_trending_actors(self, page, time_window="week"):
        cache_key = f"actors_trending_{time_window}_page_{page}"
        data = self._fetch(f"trending/person/{time_window}", {"page": page}, cache_key=cache_key)
        if data:
            self._list_people(
                data, page, "list_trending_actors", extra_params={"time_window": time_window}
            )

    def search_actor(self, name=None):
        if not name:
            kb = xbmc.Keyboard("", f"[COLOR {Colors.ORANGE}]○ ZADEJTE JMÉNO [ FUCKING ] HERCE ○[/COLOR]")
            kb.doModal()
            if not kb.isConfirmed() or not kb.getText().strip():
                xbmcplugin.endOfDirectory(self._handle, succeeded=False)
                return
            name = kb.getText().strip()
        cache_key = f"actor_search_{name.replace(' ', '_')}"
        data = self._fetch("search/person", {"query": name, "page": 1}, cache_key=cache_key)
        if not data or not data.get("results"):

            notify_info("Žádný herec nenalezen", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        self._list_people(data, 1, "search_actor", extra_params={"name": name})


    def _list_people(self, data, page, action_name, extra_params=None):
        results = data.get("results",[])
        total_pages = data.get("total_pages", 1)
        for person in results:
            name = person.get("name")
            if not name:
                continue
            profile_path = person.get("profile_path")
            poster = (
                f"{self.image_base_url}w500{profile_path}"
                if profile_path
                else Icons.CAST
            )
            list_item = xbmcgui.ListItem(label=name)
            list_item.setArt({"icon": poster, "thumb": poster, "poster": poster})
            known_for_titles =[
                kf.get("title") or kf.get("name")
                for kf in person.get("known_for", [])
                if kf.get("title") or kf.get("name")
            ]
            plot = (
                f"[B][COLOR orange] ► [/COLOR] ZNÁMÉ PROJEKTY : [/B]\n\n{', '.join(known_for_titles)}"
                if known_for_titles
                else "[B][COLOR orange] ► [/COLOR] Žádné další informace ...[/B]"
            )
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(name)
            info_tag.setPlot(plot)
            url = get_url(action="actor_detail", id=person.get("id"))
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        total_pages = data.get("total_pages", 1)
        current_page = page
        if total_pages > 1 and current_page < total_pages:
            headers_for_paging = {
                'x-pagination-page-count': str(total_pages),
                'x-pagination-page': str(current_page)
            }
            paging_params = {
                "page": str(int(current_page) + 1),
            }

            if extra_params:
                paging_params.update(extra_params)

            add_next_page_item(self._handle, action_name, headers_for_paging, current_page, **paging_params)

        xbmcplugin.setContent(self._handle, "actors")

        # --- ADD FIX : Vynutí grafické zobrazení, které umí ukázat poster a info
        set_view_mode(self._handle, self.addon, "actors", "movies")
        # --- ADD FIX : Vynutí grafické zobrazení, které umí ukázat poster a info

        xbmcplugin.endOfDirectory(self._handle)


    def actor_detail(self, person_id):
        endpoint = f"person/{person_id}"
        append_to_response = "movie_credits,tv_credits"
        cache_key = f"actor_detail_{person_id}"

        data = self._fetch(
            endpoint, {"append_to_response": append_to_response},
            cache_key=cache_key, skip_filter=True
        )
        if not data:
            return

        filter_tv_shows = self.addon.getSettingBool("filter_actor_tv_shows")
        tv_show_genre_ids_to_exclude = {10767, 10764, 10763}

        movie_credits = data.get("movie_credits", {}).get("cast",[])
        tv_credits = data.get("tv_credits", {}).get("cast",[])

        if filter_tv_shows:
            original_tv_count = len(tv_credits)
            tv_credits =[
                credit
                for credit in tv_credits
                if not tv_show_genre_ids_to_exclude.intersection(
                    credit.get("genre_ids", [])
                )
            ]
            filtered_count = original_tv_count - len(tv_credits)
            if filtered_count > 0:
                log(
                    f"TMDB ACTORS - Filtr herců odstranil {filtered_count} TV pořadů ( Talk/Reality/News )",
                    xbmc.LOGINFO,
                )

        credits = movie_credits + tv_credits
        credits.sort(key=lambda x: x.get("popularity", 0), reverse=True)

        for i, credit in enumerate(credits):
            media_type = credit.get("media_type", "movie" if "release_date" in credit else "tv")


            props = self._build_metadata_props(credit, media_type)


            character = credit.get("character", "")
            title = props.get("title")
            year = props.get("year")

            label = f"{title} ({year})"
            if character:
                label += f" [I]- jako {character}[/I]"

            list_item = xbmcgui.ListItem(label=label)


            self.fill_list_item(list_item, props, media_type)


            if media_type == "movie":
                url = get_url(action="find_sources", meta=json.dumps(props))
            else:
                url = get_url(action="listing_tmdb_tv", tmdb_id=props.get("tmdb_id"), meta=json.dumps(props))


            context_menu = self._build_context_menu(props.get("tmdb_id"), media_type, title, props=props)
            list_item.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        xbmcplugin.setContent(self._handle, "movies")
        xbmcplugin.endOfDirectory(self._handle)


    def show_tv_detail(self, tmdb_id, meta_json, source_list=None):


        parent_meta = get_meta_from_cache(meta_json)

        use_czech = self.addon.getSettingBool('trakt_prefer_czech_search')
        lang_override = 'cs-CZ' if use_czech else None


        data = self.get_full_details("tv", tmdb_id, lang=lang_override)

        if not data:
            return

        for season in data.get("seasons",[]):
            season_number = season.get("season_number")
            if season_number == 0:
                continue

            season_name = season.get("name", f"Sezóna {season_number}")

            poster_path = season.get("poster_path")
            poster = (
                f"{self.image_base_url}w500{poster_path}"
                if poster_path
                else parent_meta.get("poster")
            )

            props = {
                "tmdb_id": tmdb_id,
                "media_type": "season",
                "title": season_name,
                "tv_show_title": parent_meta.get("title"),
                "season": season_number,
                "plot": season.get("overview", ""),
                "premiered": season.get("air_date", ""),
                "year": (season.get("air_date") or "")[:4],
                "episode_count": season.get("episode_count"),
                "poster": poster,
                "fanart": parent_meta.get("fanart"),
                "thumb": poster
            }

            list_item = xbmcgui.ListItem(label=season_name)

            self.fill_list_item(list_item, props, "season")


            meta_key = store_meta_in_cache(parent_meta)

            url = get_url(
                action="tmdb_tv_season",
                tmdb_id=tmdb_id,
                season=season_number,
                meta=meta_key,
                source_list=source_list,
            )

            is_series_autoplay_on = self.main_window.getProperty("player.series.autoplay.enabled") == "true"
            toggle_label = f"[B][COLOR {Colors.ORANGE}][ [/COLOR][COLOR {Colors.RED}]AUTOLIST VYPNOUT[/COLOR][COLOR {Colors.ORANGE}] ][/COLOR][/B]" if is_series_autoplay_on else f"[B][COLOR {Colors.ORANGE}][ [/COLOR][COLOR {Colors.LIMEGREEN}]AUTOLIST ZAPNOUT[/COLOR][COLOR {Colors.ORANGE}] ][/COLOR][/B]"

            # Keep actions on the parent show available throughout its seasons.
            context_menu_items = [
                (toggle_label, f"RunPlugin({get_url(action='toggle_series_autoplay')})")
            ] + self._build_context_menu(
                tmdb_id, 'tv', parent_meta.get('title', ''),
                context_type=source_list if source_list in ('watch_later', 'watchlist', 'favorites', 'rated') else 'general',
                props=dict(parent_meta, tmdb_id=tmdb_id, media_type='tv')
            )
            list_item.addContextMenuItems(_sf_cm_items(context_menu_items), replaceItems=False)

            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        xbmcplugin.setContent(self._handle, "seasons")
        set_view_mode(self._handle, self.addon, "seasons", "seasons")
        xbmcplugin.endOfDirectory(self._handle)


    def show_tv_season(self, tmdb_id, season_number, meta_json, source_list=None):


        parent_meta = get_meta_from_cache(meta_json)

        use_czech = self.addon.getSettingBool('trakt_prefer_czech_search')
        lang_override = 'cs-CZ' if use_czech else None
        cache_key_lang_suffix = f"_{lang_override}" if lang_override else ""
        cache_key = f"tv_season_{tmdb_id}_{season_number}{cache_key_lang_suffix}"

        data = self._fetch(f"tv/{tmdb_id}/season/{season_number}", params={"append_to_response": "credits"}, cache_key=cache_key, language_override=lang_override)

        if not data:
            return

        for episode in data.get("episodes",[]):
            episode_number = episode.get("episode_number")
            ep_title = episode.get("name", f"Epizoda {episode_number}")

            ep_props = self._build_metadata_props(episode, "episode")

            if not ep_props.get("tv_show_title"): ep_props["tv_show_title"] = parent_meta.get("title")
            # Internal episode metadata uses the show's TMDB ID plus S/E coordinates.
            ep_props["tmdb_id"] = tmdb_id
            if not ep_props.get("season"): ep_props["season"] = season_number
            if not ep_props.get("episode"): ep_props["episode"] = episode_number

            if not ep_props.get("poster"): ep_props["poster"] = parent_meta.get("poster")
            if not ep_props.get("fanart"): ep_props["fanart"] = parent_meta.get("fanart")
            if not ep_props.get("thumb"): ep_props["thumb"] = parent_meta.get("fanart")

            if parent_meta.get("cast_full"):
                 ep_props["cast_full"] = ep_props.get("cast_full", []) + parent_meta.get("cast_full",[])

            list_item = xbmcgui.ListItem(label=f"{episode_number}. {ep_title}")

            episode_meta = parent_meta.copy()
            episode_meta.update(ep_props)
            for key in ("genre", "studio", "mpaa", "poster", "fanart"):
                if not episode_meta.get(key):
                    episode_meta[key] = parent_meta.get(key, "")

            episode_meta.update({
                "media_type": "episode",
                "title": ep_title,
                "plot": ep_props.get("plot", ""),
                "thumb": ep_props.get("thumb"),
                "season": season_number,
                "episode": episode_number,
                "tv_show_title": parent_meta.get("title"),
                "rating": ep_props.get("rating", 0.0),
                "cast_full": ep_props.get("cast_full")
            })


            self.fill_list_item(list_item, episode_meta, "episode")
            meta_key = store_meta_in_cache(episode_meta)

            main_window = xbmcgui.Window(10000)
            is_autoplay_on = (
                main_window.getProperty("player.series.autoplay.enabled") == "true"
            )

            if is_autoplay_on:
                url = get_url(
                    action="create_series_playlist_action",
                    meta=meta_key,
                    source_list=source_list,
                )
                is_folder = False
                toggle_label = f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]AUTOLIST VYPNOUT[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]"
                list_item.setProperty("IsPlayable", "true")
            else:
                url = get_url(action="find_sources", meta=meta_key, source_list=source_list)
                is_folder = True
                toggle_label = f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.LIMEGREEN}]AUTOLIST ZAPNOUT[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]"
                list_item.setProperty("IsPlayable", "false")

            # Catalog episode rows also expose operations on their parent show.
            context_menu_items = [
                (toggle_label, f"RunPlugin({get_url(action='toggle_series_autoplay')})")
            ] + self._build_context_menu(
                tmdb_id, 'tv', parent_meta.get('title', ''),
                context_type=source_list if source_list in ('watch_later', 'watchlist', 'favorites', 'rated') else 'general',
                props=dict(parent_meta, tmdb_id=tmdb_id, media_type='tv')
            )

            list_item.addContextMenuItems(_sf_cm_items(context_menu_items), replaceItems=False)
            xbmcplugin.addDirectoryItem(
                self._handle, url, list_item, isFolder=is_folder
            )

        xbmcplugin.setContent(self._handle, "episodes")
        set_view_mode(self._handle, self.addon, "episodes", "episodes")
        xbmcplugin.endOfDirectory(self._handle)


    def list_account_items(self, list_type, media_type, page=1):
        if list_type == "watchlist":
            data = tmdb_account.tmdb_get_watchlist(media_type, page)
        elif list_type == "rated":
            data = tmdb_account.tmdb_get_rated(media_type, page)
        elif list_type == "favorites":
            data = tmdb_account.tmdb_get_favorites(media_type, page)
        else:
            return
        if data:
            action_name = f"tmdb_{list_type}_{media_type}"
            self.list_items(data, media_type, page, action_name, context_type=list_type)

    def list_user_lists(self, page=1):
        data = tmdb_account.tmdb_get_user_lists(page)
        if not data or not data.get("results"):


            notify_info("Žádné seznamy nenalezeny", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        for list_data in data.get("results",[]):
            list_item = xbmcgui.ListItem(label=list_data.get("name"))
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType("video")
            info_tag.setTitle(list_data.get("name", ""))
            info_tag.setPlot(list_data.get("description", ""))
            list_item.setArt({"icon": Icons.FOLDER})
            url = get_url(
                action="tmdb_user_list_items", list_id=list_data.get("id"), page="1"
            )
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=True)

        total_pages = data.get("total_pages", 1)
        current_page = page
        if total_pages > 1 and current_page < total_pages:
            headers_for_paging = {
                'x-pagination-page-count': str(total_pages),
                'x-pagination-page': str(current_page)
            }
            paging_params = {
                "page": str(int(current_page) + 1),
            }

            add_next_page_item(self._handle, "tmdb_user_lists", headers_for_paging, current_page, **paging_params)
        xbmcplugin.setContent(self._handle, "files")
        xbmcplugin.endOfDirectory(self._handle)

    def list_user_list_items(self, list_id, page=1):
        data = tmdb_account.tmdb_get_user_list_items(list_id, page)
        if not data or not data.get("items"):

            notify_info("Tento seznam je prázdný", category="TMDB")
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        adapted_data = {
            "results": data["items"],
            "total_pages": data.get("total_pages", 1),
        }
        self.list_items(
            adapted_data, "multi", page, "tmdb_user_list_items", extra_params={"list_id": list_id}
        )

    def list_recommendations(self, media_type, page=1):
        data = tmdb_account.tmdb_get_recommendations(media_type, page)
        if data and data.get("results"):
            action_suffix = "movies" if media_type == "movie" else "tv"
            action_name = f"tmdb_recommendations_{action_suffix}"
            self.list_items(
                data, media_type, page, action_name
            )
        else:
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)


    def get_trailer(self, media_type, tmdb_id):

        """
        TMDB :: TRAILER GET
        -- Získá URL na YouTube trailer z TMDB. Využívá SSD/RAM cache_manager.
        """

        cache_key = f"trailer_{media_type}_{tmdb_id}_{self.language}"
        cached = cache_manager.cache_get("TMDB", cache_key)
        if cached:
            return cached

        endpoint = f"{media_type}/{tmdb_id}/videos"
        trailer = None
        data = None

        data = self._fetch(endpoint, language_override="cs-CZ", skip_filter=True)
        if data:
            trailer = self._find_trailer(data)

        if not trailer:
            data = self._fetch(endpoint, language_override="en-US", skip_filter=True)
            if data:
                trailer = self._find_trailer(data)

        if not trailer:
            data = self._fetch(endpoint, skip_filter=True)
            if data:
                trailer = self._find_trailer(data)

        if trailer:
            cache_manager.cache_set("TMDB", cache_key, trailer)
            log(f"TMDB TRAILER - Nalezen : {trailer}", xbmc.LOGINFO)
            return trailer

        log(f"TMDB TRAILER - Nebyl nalezen pro {tmdb_id}", xbmc.LOGWARNING)
        return None


    def _find_trailer(self, data):

        """
        TMDB :: TRAILER FIND
        -- Vrátí první YouTube trailer nebo None.
        """

        if not data:
            return None

        for video in data.get("results",[]):
            if video.get("site") == "YouTube" and video.get("type") in ["Trailer", "Teaser"]:
                return f"https://www.youtube.com/watch?v={video['key']}"
        return None
