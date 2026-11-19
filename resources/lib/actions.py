# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: actions.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
#  ---------------------------------------------------------------------------
#  --- CENTRALIZED CONTEXT MENU   [ LINE  150 ] ------------------------------
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import re
import json
import random
import traceback
import hashlib

import xbmc
import xbmcvfs

from resources.lib.utils_files import SafeVFSFile

import xbmcgui
import xbmcplugin


from typing import Dict, List, Optional, Any, Tuple


from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

from urllib.parse import (
    parse_qsl,
    urlencode,
    urlparse,
    quote
)


from resources.lib import trakt
from resources.lib import cache_manager
from resources.lib.utils_logging import log
from resources.lib.stream_state import get_streams, attach_subtitles, publish_active_streams
from resources.lib.ui_builder import set_view_mode


from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)

from resources.lib.utils_filter import (
    clean_title_for_tmdb,
    clean_display_title,
    encode,
    FilterUtils
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)

from resources.lib.utils import (
    convert_size_to_bytes,
    get_meta_from_cache,
    store_meta_in_cache,
    get_threadpool,
    convert_size,
    safe_get,
    safe_post,
    get_url
)





def register_play_mail_account(plugin_instance):
    from resources.lib.play_mail import PlayMail

    email, password = PlayMail(plugin_instance.addon).register_account()
    if not email or not password:
        return False
    provider = plugin_instance.provider_manager.get_provider("prehraj.to")
    if not provider:
        notify_error("PREHRAJ.TO Provider není dostupný", category="ACCOUNT")
        return False
    provider.replace_account_credentials(email, password)
    return True


def find_similar(params, plugin_instance):
    from resources.lib.recommendations import catalog_type

    tmdb_id = params.get("tmdb_id")
    if not tmdb_id:
        notify_info("INFO Chybí TMDB ID titulu", category="TMDB")
        return
    url = get_url(action="show_similar_results", tmdb_id=tmdb_id,
                  media_type=catalog_type(params.get("media_type")), title=params.get("title", ""))
    xbmc.executebuiltin(f"Container.Update({url})")


def show_similar_results(params, plugin_instance):
    from resources.lib.recommendations import catalog_type, similar_items

    media_type = catalog_type(params.get("media_type"))
    tmdb_id = params.get("tmdb_id")
    items = similar_items(plugin_instance.tmdb_client, plugin_instance.addon, tmdb_id, media_type) if tmdb_id else []
    plugin_instance.tmdb_client.list_items(
        {"results": items, "total_pages": 1}, media_type, 1, "show_similar_results"
    )


def _get_community_share_context(addon_inst, title, tmdb_id, media_type, year, poster, plot, show_title=''):

    """
    HELPER :: SHARING
    -- Vytvoří kontextové menu pro sdílení přes komunitní server
    """

    if not addon_inst.getSettingBool('enable_community_sharing'):
        return None

    import base64
    from resources.lib.utils import get_url
    from resources.lib.utils_theme import Colors

    payload = {
        'title': title,
        'tv_show_title': show_title,
        'tmdb_id': tmdb_id,
        'media_type': media_type,
        'year': year,
        'poster': poster,
        'plot': plot
    }

    try:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        b64 = base64.urlsafe_b64encode(raw).decode('utf-8')

        url_share = get_url(action='share_menu', payload=b64)



        # --- FIX : ERROR NO URL
        #
        return (f"[COLOR {Colors.ORANGE}]► SDÍLET OSTATNÍM[/COLOR]", f"RunPlugin({url_share})")


        # --- ARCTIC FUSE 3
        #
        # return (f"[COLOR {Colors.ORANGE}]► SDÍLET OSTATNÍM[/COLOR]", f"RunPlugin({share_url})")


        # --- ESTUARY
        #
        # return (f"[COLOR {Colors.ORANGE}]► SDÍLET  OSTATNÍM ◄[/COLOR]", f"RunPlugin({url_share})")


    except Exception as e:
        log(f"SHARE CONTEXT - Chyba při generování: {e}", xbmc.LOGWARNING)
        notify_error("ERROR SHARE CONTEXT - CHYBA PŘI GENEROVÁNÍ", category="SHARING")
        return None





    # ================================================================================== #
    # ---------------------------------------------------------------------------------- #
    # ---                 CENTRÁLNÍ DEFINICE  ::  KONTEXTOVÝCH MENU                  --- #
    # ---------------------------------------------------------------------------------- #
    # ================================================================================== #



def _get_context_menu(menu_type, **kwargs):

    """
    CONTEXT :: CENTRALIZED MENU
    -- Snadno editovatelná sekce pro správu a řazení kontextového menu
    """

    ctx =[]
    props = kwargs.get('props', {})
    title = kwargs.get('title') or props.get('title', '')
    tmdb_id = kwargs.get('tmdb_id') or props.get('tmdb_id', '')
    media_type = kwargs.get('media_type') or props.get('media_type', 'movie')
    year = kwargs.get('year') or props.get('year', '')
    poster = kwargs.get('poster') or props.get('poster', '')
    plot = kwargs.get('plot') or props.get('plot', '')
    query = kwargs.get('query', '')
    context_type = kwargs.get('context_type', 'general')
    addon_inst = kwargs.get('addon')
    video_link = kwargs.get('video_link', '')
    season = kwargs.get('season', '')
    episode = kwargs.get('episode', '')
    show_title = kwargs.get('show_title', '')



    # ================================================================================== #
    # ---  CENTRÁLNÍ SLOVNÍK VŠECH POLOŽEK   ( Pro snadnou úpravu názvů a akcí )     --- #
    # ================================================================================== #



# --- ARCTIC FUSE 3
#
#
#     ITEMS = {
#         'watch_later': (f"[COLOR {Colors.ORANGE}]► SLEDOVAT POZDĚJI ◄[/COLOR]", f"RunPlugin({get_url(action='add_to_watch_later', meta=json.dumps(props))})"),
#         'find_similar': (f"[COLOR {Colors.YELLOW}]► HLEDAT  PODOBNÉ ◄[/COLOR]", f"RunPlugin({get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})"),
#         'ai_similar': (f"[COLOR {Colors.ORCHID}]► AI - PODOBNOST ◄[/COLOR]", f"Container.Update({get_url(action='ai_similar', title=title, year=year, media_type=media_type)})"),
#         'ai_trivia': (f"[COLOR {Colors.ORCHID}]► AI - ZAJÍMAVOST ◄[/COLOR]", f"RunPlugin({get_url(action='gemini_trivia', title=title, year=year, media_type=media_type)})"),
#         'play_trailer': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILERY ◄[/COLOR]", f"RunPlugin({get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=media_type)})"),
#         'share': _get_community_share_context(addon_inst, title, tmdb_id, media_type, year, poster, plot) if addon_inst else None,
#         'library': (f"[COLOR {Colors.ORANGE}]► OSOBNÍ KNIHOVNA ◄[/COLOR]", f"RunPlugin({get_url(action='library', tmdb_id=tmdb_id, media_type=media_type, title=title, year=year)})"),
#
#         'player_menu': (f"[B][COLOR {Colors.LIMEGREEN}] [  ○  PLAY.ER  MENU  ○  ][/COLOR][/B]", f"RunPlugin({get_url(action='show_player_menu', tmdb_id=tmdb_id, media_type=media_type, title=title, props=json.dumps(props))})"),
#         'player_menu_provider': (f"[B][COLOR {Colors.LIMEGREEN}][  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]", f"RunPlugin({get_url(action='show_player_menu', title=title, provider=kwargs.get('provider'), link=video_link)})"),
#         'player_menu_playback': (f"[B][COLOR {Colors.LIMEGREEN}] [  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]", f"RunPlugin({get_url(action='show_player_menu', title=title, provider='playback_history', link='')})"),
#
#         'tmdb_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO WATCHLISTU ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
#         'tmdb_favorites': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO OBLÍBENÝCH ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
#         'tmdb_rating': (f"[COLOR {Colors.ORANGE}]► PŘIDAT SVÉ HODNOCENÍ ◄[/COLOR]", f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})"),
#         'trakt_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT DO TRAKTLIST ◄[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist_tmdb', media_type='show' if media_type == 'tv' else 'movie', tmdb_id=tmdb_id)})"),
#
#         'search_title': (f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL ◄[/COLOR]", f"RunPlugin({get_url(action='search_title', name=title)})"),
#         'refresh_cache': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ][/COLOR]", f"RunPlugin({get_url(action='clear_csfd_cache')})"),
#         'refresh_cache_mw': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ][/COLOR]", f"RunPlugin({get_url(action='clear_most_watched_cache')})"),
#
#         'download_file': (f"[COLOR {Colors.ORANGE}]► STÁHNOUT SOUBOR ◄[/COLOR]", f"RunPlugin({get_url(action='download', url=video_link)})"),
#         'open_seasons': (f"[COLOR {Colors.ORANGE}]► OTEVŘÍT SEZÓNY ◄[/COLOR]", f"RunPlugin({get_url(action='search_tmdb_from_history', show_title=title, tmdb_id=tmdb_id)})"),
#         'next_episodes': (f"[COLOR {Colors.ORANGE}]► DALŠÍ EPIZODY ◄[/COLOR]", f"RunPlugin({get_url(action='continue_watching_main', meta=json.dumps(props))})"),
#
#         'remove_playback_item_show': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='show', show_title=title)})"),
#         'remove_playback_item_movie': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='movie', movie_title=title)})"),
#         'remove_playback_item_episode': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='episode', show_title=show_title, season=str(season), episode=str(episode))})"),
#         'remove_playback_item_share': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_community_share', title=title)})"),
#
#         'settings': (f"[B][COLOR {Colors.LIMEGREEN}][  ○  NASTAVENÍ  ○  ] [/COLOR][/B]", "Addon.OpenSettings(plugin.video.play_er)")
#     }
#
#     if context_type == 'watch_later': ITEMS['watch_later'] = (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT Z WATCH LATER[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type)})")
#
#
#
# --- ARCTIC FUSE 3



    ITEMS = {
        'watch_later': (f"[COLOR {Colors.ORANGE}]► SLEDOVAT POZDĚJI[/COLOR]", f"RunPlugin({get_url(action='add_to_watch_later', meta=json.dumps(props))})"),
        'find_similar': (f"[COLOR {Colors.YELLOW}]► HLEDAT PODOBNÉ[/COLOR]", f"RunPlugin({get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})"),
        'ai_similar': (f"[COLOR {Colors.ORCHID}]► AI - PODOBNOST[/COLOR]", f"Container.Update({get_url(action='ai_similar', title=title, year=year, media_type=media_type)})"),
        'ai_trivia': (f"[COLOR {Colors.ORCHID}]► AI - ZAJÍMAVOST[/COLOR]", f"RunPlugin({get_url(action='gemini_trivia', title=title, year=year, media_type=media_type)})"),
        'play_trailer': (f"[COLOR {Colors.ORANGE}]► PŘEHRÁT TRAILER[/COLOR]", f"RunPlugin({get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=media_type)})"),
        'share': _get_community_share_context(addon_inst, title, tmdb_id, media_type, year, poster, plot, show_title=show_title or props.get('tv_show_title', '')) if addon_inst else None,
        'library': (f"[COLOR {Colors.ORANGE}]► OSOBNÍ KNIHOVNA[/COLOR]", f"RunPlugin({get_url(action='library', tmdb_id=tmdb_id, media_type=media_type, title=title, year=year)})"),

        'player_menu': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu', tmdb_id=tmdb_id, media_type=media_type, title=title, props=json.dumps(props))})"),
        'player_menu_provider': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu', title=title, provider=kwargs.get('provider'), link=video_link)})"),
        'player_menu_playback': (f"[COLOR {Colors.LIMEGREEN}]○  PLAY.ER  MENU  ○[/COLOR]", f"RunPlugin({get_url(action='show_player_menu', title=title, provider='playback_history', link='')})"),

        'tmdb_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT WATCHLIST[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_favorites': (f"[COLOR {Colors.ORANGE}]► PŘIDAT OBLÍBENÉ[/COLOR]", f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
        'tmdb_rating': (f"[COLOR {Colors.ORANGE}]► PŘIDAT HODNOCENÍ[/COLOR]", f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})"),
        'trakt_watchlist': (f"[COLOR {Colors.ORANGE}]► PŘIDAT TRAKTLIST[/COLOR]", f"RunPlugin({get_url(action='trakt_add_to_watchlist_tmdb', media_type='show' if media_type == 'tv' else 'movie', tmdb_id=tmdb_id)})"),

        'search_title': (f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL[/COLOR]", f"RunPlugin({get_url(action='search_title', name=title)})"),
        'refresh_cache': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='clear_csfd_cache')})"),
        'refresh_sharing': (f"[COLOR {Colors.LIMEGREEN}][ OBNOVIT SDÍLENÍ ][/COLOR]", 'Container.Refresh'),
        'refresh_cache_mw': (f"[COLOR {Colors.LIMEGREEN}][ RE-FRESH ADDON ][/COLOR]", f"RunPlugin({get_url(action='clear_most_watched_cache')})"),

        'download_file': (f"[COLOR {Colors.ORANGE}]► STÁHNOUT SOUBOR[/COLOR]", f"RunPlugin({get_url(action='download', url=video_link)})"),
        'open_seasons': (f"[COLOR {Colors.ORANGE}]► OTEVŘÍT SEZÓNY[/COLOR]", f"RunPlugin({get_url(action='search_tmdb_from_history', show_title=title, tmdb_id=tmdb_id)})"),
        'next_episodes': (f"[COLOR {Colors.ORANGE}]► DALŠÍ EPIZODY[/COLOR]", f"RunPlugin({get_url(action='continue_watching_main', meta=json.dumps(props))})"),

        'remove_playback_item_show': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}][/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='show', show_title=kwargs.get('history_title', title))})"),
        'remove_playback_item_movie': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}][/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='movie', movie_title=kwargs.get('history_title', title))})"),
        'remove_playback_item_episode': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}][/COLOR]", f"RunPlugin({get_url(action='remove_playback_item', type='episode', show_title=show_title, season=str(season), episode=str(episode))})"),
        'remove_playback_item_share': (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT POLOŽKU[/COLOR][COLOR {Colors.ORANGE}][/COLOR]", f"RunPlugin({get_url(action='remove_community_share', share_key=kwargs.get('share_key', ''))})"),

        'settings': (f"[COLOR {Colors.LIMEGREEN}][ MENU NASTAVENÍ ][/COLOR]", "Addon.OpenSettings(plugin.video.play_er)")
    }


    if context_type == 'watch_later': ITEMS['watch_later'] = (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT Z WATCHLATER[/COLOR][COLOR {Colors.ORANGE}][/COLOR]", f"RunPlugin({get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type, **({'season': props.get('season'), 'episode': props.get('episode')} if media_type == 'episode' else {}))})")



    # ================================================================================== #
    # ---  DEFINICE ROZLOŽENÍ  ( Podle seznamu přikázaného uživatelem )              --- #
    # ================================================================================== #



    LAYOUTS = {
        'search_results':['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'share', 'library', 'player_menu', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_cache', 'settings'],
        'stremio_items':['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'library', 'share', 'player_menu', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_cache', 'settings'],
        'most_watched':['search_title', 'refresh_cache_mw', 'download_file', 'player_menu_provider', 'settings'],
        'prehrajto_history':['search_title', 'refresh_cache_mw', 'download_file', 'player_menu_provider', 'settings'],
        'playback_history_show':['open_seasons', 'watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'library', 'share', 'player_menu_playback', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_cache_mw', 'remove_playback_item_show', 'settings'],
        'playback_history_movie':['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'library', 'share', 'player_menu_playback', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_cache_mw', 'remove_playback_item_movie', 'settings'],
        'playback_show_episodes':['next_episodes', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'library', 'share', 'player_menu_playback', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_cache_mw', 'remove_playback_item_episode', 'settings'],
        'community_shares':['watch_later', 'find_similar', 'ai_similar', 'ai_trivia', 'play_trailer', 'library', 'share', 'player_menu', 'tmdb_watchlist', 'tmdb_favorites', 'tmdb_rating', 'trakt_watchlist', 'search_title', 'refresh_sharing', 'remove_playback_item_share', 'settings'],
    }



    LAYOUTS['source_results'] = [key if key != 'player_menu' else 'player_menu_provider'
                                 for key in LAYOUTS['search_results']]
    layout = LAYOUTS.get(menu_type,[])
    for key in layout:
        if key == 'search_title' and tmdb_id and menu_type in ('search_results', 'stremio_items'):
            continue  # Vyhledat titul se zobrazí jen tehdy, pokud je tmdb prázdné
        item = ITEMS.get(key)
        if item:
            ctx.append(item)

    return ctx



    # ================================================================================== #
    # ---------------------------------------------------------------------------------- #
    # ---                 CENTRÁLNÍ DEFINICE  ::  KONTEXTOVÝCH MENU                  --- #
    # ---------------------------------------------------------------------------------- #
    # ================================================================================== #




def _search_providers_parallel(query, providers, apply_filters=False, sort_priority="PREHRAJ.TO", unfiltered_results=None):

    """
    HELPER :: PARALLEL SEARCH
    -- Spustí vyhledávání u všech providerů paralelně.
    """

    results =[]
    if not providers: return results


    def _search_worker(provider):
        try:
            cookies = provider.get_premium_cookies() if hasattr(provider, 'get_premium_cookies') else None
            # Only TMDBH source selection captures raw rows. Provider-side API
            # parameters remain unchanged; normalize_and_filter applies the same
            # local filters without repeating the network search.
            capture_raw = unfiltered_results is not None
            res = provider.search_sources(query, cookies=cookies,
                                          apply_filters=False if capture_raw else apply_filters)
            raw = [dict(r) for r in res] if capture_raw else []
            if capture_raw and apply_filters:
                res = provider.normalize_and_filter(res, apply_filters=True)
            p_name = provider.__class__.__name__.lower()
            provider_name = "webshare.cz" if "webshare" in p_name else "prehraj.to"
            for r in res:
                r["provider"] = provider_name
            for r in raw:
                r["provider"] = provider_name
            return res, raw
        except Exception as e:
            log(f"SEARCH - Chyba providera {provider} : {e}", xbmc.LOGERROR)
            return [], []

    max_workers = get_threadpool(len(providers) + 1)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_search_worker, p) for p in providers]
        for future in as_completed(futures):
            filtered, raw = future.result()
            results.extend(filtered)
            if unfiltered_results is not None:
                unfiltered_results.extend(raw)


    try:
        if sort_priority == "WEBSHARE.CZ":
            priority = lambda x: 0 if "webshare" in str(x.get("provider", "")).lower() else 1
        else:
            priority = lambda x: 0 if "prehraj" in str(x.get("provider", "")).lower() else 1
        results.sort(key=priority)
        if unfiltered_results is not None:
            unfiltered_results.sort(key=priority)
    except Exception: pass

    return results



def prehrajto_suggest(params, plugin_instance):

    """
    ACTION :: prehrajto_suggest
    - Jednoduchá akce dostupná přes plugin URL pro použití skinem.
    - Parametr `q` nebo `query` obsahuje frázi.
    """

    import os

    import xbmc
    import xbmcvfs
    import xbmcgui
    import xbmcplugin

    from resources.lib.utils_logging import log


    log(f"PREHRAJTO_SUGGEST - invoked with params: {params}", xbmc.LOGINFO)

    try:
        q = params.get('q') or params.get('query') or ''
        if not q:
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
            return

        providers = plugin_instance.provider_manager.get_providers_to_search()

        # --- Prefer prehrajto provider if available (support both keys)

        suggestions = []
        try:
            preh = plugin_instance.provider_manager.get_provider('prehraj.to') or plugin_instance.provider_manager.get_provider('prehrajto')
            if preh and hasattr(preh, 'suggest'):
                suggestions = preh.suggest(q)
            else:
                for p in providers:
                    try:
                        if hasattr(p, 'suggest'):
                            s = p.suggest(q)
                            if s:
                                suggestions.extend(s)
                    except Exception:
                        continue

            # --- Dedupe preserving order

            seen = set()
            out = []
            for s in suggestions:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
            suggestions = out
        except Exception as e:
            log(f"PREHRAJTO_SUGGEST - Error collecting suggestions: {e}", xbmc.LOGWARNING)

        if not suggestions:
            log(f"PREHRAJTO_SUGGEST - no suggestions for query: {q}", xbmc.LOGINFO)
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
            return

        addon_dir = xbmcvfs.translatePath(plugin_instance.addon.getAddonInfo('path'))
        icons_dir = os.path.join(addon_dir, 'resources', 'icons')
        poster_img = os.path.join(icons_dir, 'POSTER--PLAYER--MAIN.webp')
        clearlogo_img = os.path.join(icons_dir, 'CLEAR--PLAYER--PLAYER.webp')
        fanart_img = os.path.join(icons_dir, 'FANART--DEVELOPMENT.webp')


        # for i, phrase in enumerate(suggestions):
        #     label = phrase
        #     li = xbmcgui.ListItem(label=label)


        for i, phrase in enumerate(suggestions):
            label = phrase.upper()
            li = xbmcgui.ListItem(label=label)

            li.setProperty('IsPlayable', 'false')
            li.setArt({
                'poster': poster_img,
                'icon': os.path.join(icons_dir, 'FUSE--PREHRAJTO.webp'),
                'thumb': os.path.join(icons_dir, 'WIDE--PREHRAJTO.webp'),
                'fanart': fanart_img,
                'clearlogo': clearlogo_img
            })

            # --- Selecting suggestion triggers tmdbh_bridge text_search

            url = get_url(action='tmdbh_bridge', mode='text_search', q=phrase)
            xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, True)

        xbmcplugin.setContent(plugin_instance.handle, 'movies')
        try:
            from resources.lib.ui_builder import set_view_mode
            set_view_mode(plugin_instance.handle, plugin_instance.addon, 'movies', 'search_results')
        except Exception:
            pass

        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True)

    except Exception as e:
        log(f"PREHRAJTO_SUGGEST - Unexpected error: {e}", xbmc.LOGERROR)
        try:
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
        except Exception:
            pass



# ==========================   STREAM SELECTOR :: QUALITY SWITCH   ========================== #
# ------------------------------------------------------------------------------------------- #



def change_stream_quality(params, plugin_instance):

    """
    SEAMLESS SWITCH :: QUALITY
    -- Změní kvalitu videa během přehrávání bez ztráty pozice.
    -- (Plynulé přepínání bez rozbití inputstreamu)
    """


    import json

    import xbmc
    import xbmcgui

    from urllib.parse import quote
    from resources.lib.utils_notification import notify_info, notify_error



    if not xbmc.Player().isPlayingVideo():
        notify_info("INFO Není přehráváno žádné video", category="STREAM")
        return

    win = xbmcgui.Window(10000)
    player = xbmc.Player()
    playing_item = player.getPlayingItem()
    available_links = get_streams(playing_item)
    if not available_links:
        notify_error("ERROR Dostupné kvality streamu nejsou známy", category="STREAM")
        return

    if len(available_links) <= 1:
        notify_info("INFO K dispozici je pouze jeden stream", category="STREAM")
        return

    options = list(available_links.keys())
    urls = list(available_links.values())

    from resources.lib.utils import pop_dialog_select

    choice = pop_dialog_select(f"[COLOR {Colors.ORANGE}] ○  VÝBĚR KVALITY STREAMU  ○ [/COLOR]", options)

    if choice == -1:
        return

    selected_url = urls[choice]
    meta_json = win.getProperty("play_er.current_meta")

    player = xbmc.Player()
    current_time = player.getTime()

    # --- Rekonstrukce čisté URL s hlavičkami pro Kodi

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
    referer = "https://prehraj.to/"
    accept = "video/mp4,video/*,*/*"
    clean_url = selected_url.split('|')[0]
    final_url = "{0}|User-Agent={1}&Referer={2}&Accept={3}".format(clean_url, quote(ua), quote(referer), quote(accept))

    li = xbmcgui.ListItem(path=final_url)
    li.setContentLookup(False)

    if meta_json:
        try:
            meta = json.loads(meta_json)
            plugin_instance.tmdb_client.fill_list_item(li, meta, meta.get('media_type', 'movie'))

            # --- Obnovíme uložené čisté titulky ze speciální složky

            attach_subtitles(li, playing_item.getProperty('play_er.link'))
        except: pass

    # --- Continuity logika - zastavíme video a nepozorovaně načteme to samé jinde

    for key in ('play_er.link', 'play_er.meta_id', 'play_er.media_type', 'play_er.source_list', 'play_er.trakt_id'):
        li.setProperty(key, playing_item.getProperty(key))
    win.setProperty("play_er.seamless_switching", "true")
    player.stop()
    xbmc.sleep(500) # Ochrana proti zablokování threadů přehrávače

    player.play(final_url, listitem=li)

    # --- Počkáme na probuzení přehrávače a aplikujeme časový posun

    for _ in range(50):
        if player.isPlayingVideo():
            player.seekTime(current_time)
            break
        xbmc.sleep(100)



def resolve_video(link, provider_name, meta_json, source_list=None, return_url_only=False, plugin_instance=None, direct_play=False, prediction_ref=None):

    """
    KODI 22 & YATSE CLEAN RESOLVER - FIX ERROR 22 & TRAKT SCROBBLING
    -- Verze s plnou podporou metadat skrze Properties namísto URL.
    """

    if isinstance(meta_json, dict):
        meta = meta_json
    else:
        meta = get_meta_from_cache(meta_json)

    tmdb_id = meta.get("tmdb_id")
    media_type = meta.get("media_type", "movie")

    # --- 1. ZÁCHRANA METADAT PRO YATSE A TRAKT ---
    #     Pokud nemáme herce nebo detaily, dotáhneme je hned, aby je dálkový ovladač viděl.

    if plugin_instance and plugin_instance.tmdb_client and tmdb_id:
        if not meta.get("cast_full") or not meta.get("poster") or not meta.get("plot"):
            try:
                log(f"RESOLVE - YATSE META : Doplňuji metadata [ TMDB ID : {tmdb_id} ]", xbmc.LOGINFO)
                full_props = None
                if media_type == "movie":
                    full_props = plugin_instance.tmdb_client.get_movie_details_raw(tmdb_id)
                elif media_type == "episode":
                    s, e = meta.get("season"), meta.get("episode")
                    if s is not None and e is not None:
                        ep_data = plugin_instance.tmdb_client._fetch(f"tv/{tmdb_id}/season/{s}/episode/{e}", params={"append_to_response": "credits"})
                        if ep_data:
                            full_props = plugin_instance.tmdb_client._build_metadata_props(ep_data, "episode")
                            if not full_props.get("cast_full") or not full_props.get("poster"):
                                show_data = plugin_instance.tmdb_client.get_full_details("tv", tmdb_id)
                                if show_data:
                                    show_props = plugin_instance.tmdb_client._build_metadata_props(show_data, "tv")
                                    if not full_props.get("cast_full"): full_props["cast_full"] = show_props.get("cast_full", [])
                                    if not full_props.get("poster"): full_props["poster"] = show_props.get("poster")
                                    if not full_props.get("fanart"): full_props["fanart"] = show_props.get("fanart")
                if full_props:
                    for k, v in full_props.items():
                        if not meta.get(k) and v:
                            meta[k] = v
            except Exception as e:
                log(f"RESOLVE - Chyba doplnění metadat : {e}", xbmc.LOGWARNING)

    # Only the non-playable TMDBHelper episode selection uses direct playback.
    # Other resolver callers, including movies and URL-only queue builders, keep
    # their existing contract with Kodi.
    direct_play = bool(direct_play and media_type == "episode"
                       and meta.get("_play_er_tmdbh_source_search"))

    # --- 2. ZÍSKÁNÍ ODKAZU OD PROVIDERA

    provider = plugin_instance.provider_manager.get_provider(provider_name)
    if not provider:
        provider = plugin_instance.provider_manager.get_active_provider()

    try:
        file_url, subtitle_url = provider.get_video_link(link)
    except:
        file_url, subtitle_url = None, None

    if not file_url:
        if return_url_only: return None
        notify_error("Nepodařilo se získat odkaz na video")
        if not direct_play:
            xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
        return None

    # --- 3. KONSTRUKCE ČISTÉ URL (FIX ERROR 22) ---
    #     Posíláme User-Agent a Referer za pipe, aby Kodi neprovádělo Stat/Probe požadavky bez nich.

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
    referer = "https://prehraj.to/"
    accept = "video/mp4,video/*,*/*"
    clean_url = file_url.split('|')[0]
    final_url = "{0}|User-Agent={1}&Referer={2}&Accept={3}".format(clean_url, quote(ua), quote(referer), quote(accept))

    if return_url_only: return final_url

    publish_active_streams(str(link))

    # FIX PRE-EMPTIVE AND FILTERS [NEW SOURCE SELECTION STARTS A FINITE SESSION]
    # Persist the budget BEFORE storing metadata for the active item/monitor.
    if meta.get('_play_er_tmdbh_source_search') and media_type == 'episode':
        from resources.lib.utils_settings import get_setting_int_with_bounds
        configured_total = get_setting_int_with_bounds(
            plugin_instance.addon, 'continue_episodes_count', 3, 1, 20
        )
        meta['_play_er_queue_remaining'] = max(0, configured_total - 1)

    if (media_type == 'episode'
            and str(plugin_instance.addon.getSetting('auto_prediction_enable')).lower() == 'true'):
        from resources.lib.utils_auto_prediction import capture_reference, REFERENCE
        # Metadata is shared by all source rows; only the clicked row supplies this.
        if isinstance(prediction_ref, str) and len(prediction_ref) <= 1024:
            try:
                chosen = json.loads(prediction_ref)
                if (isinstance(chosen, dict) and chosen.get('show') == str(tmdb_id)
                        and isinstance(chosen.get('name'), str) and 0 < len(chosen['name']) <= 256):
                    meta = dict(meta)
                    meta[REFERENCE] = chosen
            except (ValueError, TypeError):
                pass
        capture_reference(meta, {'title': meta.get('source_title', '')}, plugin_instance.addon)
        if str(plugin_instance.addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
            from resources.lib.utils_prediction_handoff import begin_session
            begin_session(meta, plugin_instance.addon, fresh=True)

    # --- 4. VYTVOŘENÍ LISTITEM A NASTAVENÍ KODI 22 PARAMETRŮ

    li = xbmcgui.ListItem(path=final_url)

    # --- Zakážeme ověřování souboru (HEAD request), které na podepsaných URL selhává (Error 22)

    li.setContentLookup(False)

    # --- Detekce dabingu z názvu souboru (pro automatické titulky)

    from resources.lib.utils_filter import clean_display_title

    source_title = meta.get("source_title", meta.get("title", ""))
    _, _, parsed_tags, _ = clean_display_title(source_title)
    has_dubbing = 'DAB' in parsed_tags or 'SK' in parsed_tags
    li.setProperty('play_er.has_dubbing', 'true' if has_dubbing else 'false')

    # --- Naplníme InfoTagy (Včetně herců pro Yatse)

    if plugin_instance and plugin_instance.tmdb_client:
        plugin_instance.tmdb_client.fill_list_item(li, meta, media_type)

    try:
        resolved_info_title = li.getVideoInfoTag().getTitle()
    except Exception:
        resolved_info_title = ""
    resolved_has_art = bool(
        li.getProperty("poster") or li.getProperty("thumb") or li.getProperty("fanart")
    )
    log(
        f"FIX PRE-EMPTIVE AND FILTERS - RESOLVED ITEM METADATA: "
        f"type={media_type}, title={'yes' if resolved_info_title else 'no'}, "
        f"art={'yes' if resolved_has_art else 'no'}",
        xbmc.LOGWARNING
    )

    if tmdb_id:
        unique_ids = {'tmdb': str(tmdb_id)}
        if media_type == 'episode':
            # The resolver uses the parent show's TMDB ID for episode lookups.
            unique_ids['tvshow.tmdb'] = str(tmdb_id)
        li.getVideoInfoTag().setUniqueIDs(unique_ids)

    # --- 5. PŘÍPRAVA PRO TRAKT SCROBBLING ---
    #     Musíme zjistit Trakt ID a uložit ho do Property, aby ho monitor v trakt.py viděl.

    trakt_id = ""
    if plugin_instance.addon.getSettingBool("enable_trakt_scrobbling") and tmdb_id:
        try:
            from resources.lib import trakt as trakt_lib
            if media_type == "episode":
                trakt_id = trakt_lib.get_trakt_episode_id(tmdb_id, meta.get("season"), meta.get("episode"), plugin_instance.session, plugin_instance.addon)
            else:
                trakt_id = trakt_lib.get_trakt_id(tmdb_id, "movie", plugin_instance.session, plugin_instance.addon)
        except Exception as e:
            log(f"RESOLVE - Nepodařilo se získat Trakt ID: {e}", xbmc.LOGWARNING)


    # --- 6. UKLÁDÁNÍ DO PROPERTIES  ( Klíčové pro Monitor )

    from resources.lib.utils import store_meta_in_cache
    meta_uuid = store_meta_in_cache(meta)

    # --- ULOŽENÍ METADAT PRO SEAMLESS SWITCH OSD

    xbmcgui.Window(10000).setProperty("play_er.current_meta", json.dumps(meta))
    xbmcgui.Window(10000).setProperty("play_er.current_trakt_id", str(trakt_id))

    li.setProperty('play_er.link', str(link))
    li.setProperty('play_er.meta_id', str(meta_uuid))
    li.setProperty('play_er.media_type', str(media_type))
    li.setProperty('play_er.source_list', str(source_list))
    li.setProperty('play_er.trakt_id', str(trakt_id)) # <--- DŮLEŽITÉ PRO TRAKT.PY

    if subtitle_url:
        if isinstance(subtitle_url, list) and len(subtitle_url) > 0:
            li.setSubtitles(subtitle_url)
        elif isinstance(subtitle_url, str):
            li.setSubtitles([subtitle_url])

    log(f"RESOLVE - PŘEHRÁVÁM : CLEAN URL & TRAKT ID : {trakt_id}", xbmc.LOGINFO)
    if direct_play:
        li.setLabel(meta.get("title") or source_title)
        # Keep the active item's identity on the stream, as CONTINUE does.
        # Resolving a plugin item preserves its plugin path in Kodi; GetItem
        # then replaces its episode tag with the files-only database record.
        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        playlist.clear()
        playlist.add(final_url, li)
        xbmc.Player().play(playlist)
    else:
        xbmcplugin.setResolvedUrl(plugin_instance.handle, True, li)

    # FIX PRE-EMPTIVE AND FILTERS [TMDBHELPER FIRST EPISODE QUEUE]
    # Ostatní cesty resolve_video nemění své chování; pouze TMDBH source search
    # spustí sestavení správného playlistu epizod po zahájení zvoleného streamu.
    if meta.get("_play_er_tmdbh_source_search") and media_type == "episode":
        try:
            from resources.lib.generator import queue_following_episodes_from_tmdbh
            queue_following_episodes_from_tmdbh(
                meta, plugin_instance.addon, plugin_instance, seed_only=True
            )
        except Exception as e:
            log(f"FIX PRE-EMPTIVE AND FILTERS - Nelze spustit TMDBH episode queue: {e}", xbmc.LOGWARNING)


    # ====================================================================== #
    # ===           TMDBH :: Zápis do historie při spuštění              === #
    # ====================================================================== #


    try:
        import time
        from resources.lib import cache_manager

        history = cache_manager.user_data_get("playback_history") or []

        # --- Filtrační funkce - odstraníme případný starý záznam pro stejný titul (posuneme ho tak úplně nahoru)

        def is_same_item(item):
            imeta = item.get("meta", {})
            if str(imeta.get("tmdb_id")) != str(tmdb_id):
                return False
            if media_type == "episode":
                return str(imeta.get("season")) == str(meta.get("season")) and str(imeta.get("episode")) == str(meta.get("episode"))
            return imeta.get("media_type") == media_type

        history = [x for x in history if not is_same_item(x)]

        # --- Vložíme na začátek seznamu

        history.insert(0, {
            "meta": meta,
            "link": str(link),
            "timestamp": int(time.time())
        })

        # --- Ponecháme pouze max 100 posledních záznamů

        cache_manager.user_data_set("playback_history", history[:100])
        log("RESOLVE - PLAYBACK HISTORIE PŘEHRÁVÁNÍ BYLA ULOŽENA / AKTUALIZOVÁNA", xbmc.LOGINFO)

    except Exception as e:
        log(f"RESOLVE - Chyba zápisu historie: {e}", xbmc.LOGWARNING)

    return None



def _get_tmdb_metadata_for_search(query, tmdb_client, interactive=True):

    """
    PLUGIN :: TMDB METADATA
    -- Získává metadata pro vyhledávací funkce obsahu.
    """

    if not tmdb_client: return None

    clean, year, season, episode, _ = clean_title_for_tmdb(query)
    if not clean: return None

    media_type = "tv" if season is not None else "movie"

    try:
        search_res = tmdb_client.search_raw(clean, year=year, media_type=media_type)
        if not search_res or not search_res.get("results"):
            return None

        results = search_res["results"]
        selected = None

        if len(results) == 1:
            selected = results[0]
        elif len(results) > 1:
            opts =[]
            for r in results:
                typ = r.get('media_type', media_type).upper()
                tit = r.get('title') or r.get('name')
                dat = r.get('release_date') or r.get('first_air_date')
                y = dat[:4] if dat else "????"
                opts.append(f"[{typ}] {tit} ({y})")

            opts.append(f"[B][COLOR {Colors.ORANGE}][ ► [/COLOR][COLOR {Colors.RED}] NEPOUŽÍVAT METADATA [/COLOR][COLOR {Colors.ORANGE}] ◄ ][/COLOR][/B]")

            if interactive:
                sel = xbmcgui.Dialog().select(f"[UPPERCASE][B][COLOR orange]○  UPŘESNIT NÁZEV  |[/COLOR]|[/B] {clean}[/UPPERCASE]", opts)
            else:
                sel = 0

            if sel != -1 and sel < len(results):
                selected = results[sel]
            else:
                return None

        if selected:
            mid = selected.get("id")
            mtype = selected.get("media_type", media_type)
            full = tmdb_client.get_details_raw(mid, mtype)

            if full:
                props = tmdb_client._build_metadata_props(full, mtype)
                if season is not None:
                    props.update({'season': season, 'episode': episode, 'media_type': 'episode'})
                    ep = tmdb_client._fetch(f"tv/{mid}/season/{season}/episode/{episode}")
                    if ep and ep.get("name"): props["title"] = ep["name"]

                notify_info(f"TMDB: {props.get('title')}", category="METADATA", time=1000)
                return props

    except Exception as e:
        log(f"SEARCH META ERROR : {e}", xbmc.LOGERROR)

    return None


def find_meta_and_resolve(params, plugin_instance):

    """
    ROUTER :: METADATA RESOLVE
    -- Find Meta And Resolve
    """

    title = params.get('title')
    link = params.get('link')
    provider = params.get('provider')
    meta_raw = params.get('meta')

    meta = get_meta_from_cache(meta_raw)

    if meta:
        try:
            if not meta.get('media_type'):
                clean_title, year, season, episode, _ = clean_title_for_tmdb(meta.get('title') or title or '')
                if season is not None:
                    meta['media_type'] = 'episode'
                    meta['season'] = season
                    meta['episode'] = episode
                    meta.setdefault('tv_show_title', clean_title)
                else:
                    meta.setdefault('media_type', 'movie')
        except Exception:
            pass

        if link and provider:
            try:

                resolve_video(link, provider, json.dumps(meta), plugin_instance=plugin_instance)
                return
            except Exception:
                pass

    return search(title, plugin_instance, resolve_first=True)



def search(name, plugin_instance, return_results=False, resolve_first=False):

    log(f"SEARCH - START : Spouštění funkce search() pro '{name}'", xbmc.LOGDEBUG)
    log(f"SEARCH - PARAMETRY : return_results={return_results}, resolve_first={resolve_first}", xbmc.LOGDEBUG)

    q = ""
    if not name or name == "None":
        kb = xbmc.Keyboard("", f"[B][COLOR {Colors.ORANGE}]○ HLEDAT [ FUCKING ] VÝRAZ ○[/COLOR][/B]")
        kb.doModal()
        if not kb.isConfirmed() or not kb.getText().strip():
            log("SEARCH - Uživatel zrušil zadávání dotazu nebo zadal prázdný dotaz.", xbmc.LOGDEBUG)
            if not return_results: xbmcplugin.endOfDirectory(plugin_instance.handle, False)
            return None
        q = kb.getText().strip()
    else:
        q = encode(name)
    log(f"SEARCH - Skutečný hledaný dotaz (q): '{q}'", xbmc.LOGDEBUG)

    meta_for_playback = _get_tmdb_metadata_for_search(q, plugin_instance.tmdb_client)
    if meta_for_playback:
        log(f"SEARCH - Získaná metadata pro přehrávání: {json.dumps(meta_for_playback)}", xbmc.LOGDEBUG)
    else:
        log("SEARCH - Nelze získat metadata pro přehrávání.", xbmc.LOGDEBUG)

    search_query = re.sub(r"S(\d+)E(\d+)", lambda m: f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}", q, flags=re.IGNORECASE)
    log(f"SEARCH - Upravený search_query pro providery: '{search_query}'", xbmc.LOGDEBUG)

    if not return_results:
        try:
            history_path = plugin_instance.history_path
            if xbmcvfs.exists(history_path):
                with SafeVFSFile(history_path, "r") as f:
                    lh = f.read().splitlines()
                if search_query not in lh:
                    if len(lh) >= 10:
                        del lh[-1]
                    lh.insert(0, search_query)
                    with SafeVFSFile(history_path, "w") as f:
                        f.write("\n".join(lh))
            else:
                with SafeVFSFile(history_path, "w") as f:
                    f.write(search_query)
        except Exception as e:
            log(f"ACTIONS SEARCH - Chyba při ukládání do historie hledání : {e}", xbmc.LOGERROR)

    providers = plugin_instance.provider_manager.get_providers_to_search()
    log(f"SEARCH - Nalezeno {len(providers)} providerů k prohledání.", xbmc.LOGDEBUG)
    sort_priority = plugin_instance.addon.getSetting("multi_provider_sort")
    log(f"SEARCH - Volám _search_providers_parallel s dotazem '{search_query}'", xbmc.LOGDEBUG)
    all_videos = _search_providers_parallel(search_query, providers, apply_filters=False, sort_priority=sort_priority)
    log(f"SEARCH - _search_providers_parallel vrátil {len(all_videos)} výsledků.", xbmc.LOGDEBUG)

    if return_results:
        log(f"SEARCH - return_results je True, vracím výsledky.", xbmc.LOGDEBUG)
        return all_videos

    if resolve_first and all_videos:
        log(f"SEARCH - resolve_first je True a nalezeny výsledky.", xbmc.LOGDEBUG)
        first = all_videos[0]
        log(f"SEARCH - První výsledek: {json.dumps(first)}", xbmc.LOGDEBUG)

        if not meta_for_playback:
            log("SEARCH - Chybí metadata pro přehrávání, zkouším dohledat interaktivně.", xbmc.LOGDEBUG)
            dialog_title = f"[B][COLOR {Colors.ORANGE}]○ TMDB METADATA ○[/COLOR][/B]"
            dialog_message = f"Pro '{name}' se nenašly informace.\nChcete zadat název ručně ?"
            if xbmcgui.Dialog().yesno(dialog_title, dialog_message):
                kb_title = f"[B][COLOR {Colors.ORANGE}]○ UPŘESNIT[ FUCKING ] NÁZEV ○[/COLOR][/B]"
                kb = xbmc.Keyboard(name, kb_title)
                kb.doModal()
                if kb.isConfirmed() and kb.getText():
                    meta_for_playback = _get_tmdb_metadata_for_search(kb.getText(), plugin_instance.tmdb_client)
                log(f"SEARCH - Interaktivně získaná metadata: {json.dumps(meta_for_playback)}", xbmc.LOGDEBUG)
            else:
                log("SEARCH - Uživatel odmítl zadat název ručně, pokračuji bez metadat.", xbmc.LOGDEBUG)


        final_meta = meta_for_playback if meta_for_playback else {"title": first["title"], "media_type": "movie"}
        final_meta["source_title"] = first["title"]
        log(f"SEARCH - Volám resolve_video s metadaty: {json.dumps(final_meta)}", xbmc.LOGDEBUG)
        resolve_video(first["link"], first.get("provider"), json.dumps(final_meta), plugin_instance=plugin_instance)
        log("SEARCH - Volání resolve_video dokončeno (resolve_first branch).", xbmc.LOGDEBUG)
        return

    if not all_videos:
        log("SEARCH - Žádné výsledky od providerů, končím.", xbmc.LOGDEBUG)
        notify_info("INFO Nic nenalezeno", category="SEARCH")
        xbmcplugin.endOfDirectory(plugin_instance.handle, False)
        return

    # FIX : Plně implementováno nastavení zobrazení velikosti a délky

    show_size = plugin_instance.addon.getSettingBool("show_size")
    show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
    filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_search")

    # Použijeme enumerate pro získání unikátního indexu 'i'

    for i, video in enumerate(all_videos):
        prov = video.get("provider", "")
        color = Colors.LIMEGREEN if "webshare" in prov else Colors.ORANGE

        size_tag = ""
        duration_tag = ""
        likes_tag = ""

        if show_size and video.get("size_str"):
            raw_size = video.get("size_str")
            try:
                size_bytes = convert_size_to_bytes(raw_size)
                normalized = convert_size(size_bytes) if size_bytes else raw_size
            except Exception:
                normalized = raw_size
            size_tag = f'[LIGHT][COLOR {color}][{normalized}][/LIGHT][/COLOR] '

        if show_duration and video.get("duration_str") and video["duration_str"] != "0":
            duration_tag = f'[LIGHT][COLOR gray][{video["duration_str"]}][/COLOR][/LIGHT] '


        if filter_enabled:
            try:
                cleaned_title, _, _, _ = clean_display_title(
                    video["title"],
                    explicit_tags=video.get("tags", []),
                    extension=video.get("extension"),
                    likes=video.get("likes", 0)
                )
                label = f'{size_tag}{duration_tag}{cleaned_title}'.strip()
            except Exception:
                label = f'{size_tag}{duration_tag}{video["title"]}'.strip()
        else:
            label = f'{size_tag}{duration_tag}{video["title"]}'.strip()


        li = xbmcgui.ListItem(label=label)
        li.setProperty("IsPlayable", "true")

        if meta_for_playback and plugin_instance.tmdb_client:
            m_type = meta_for_playback.get('media_type', 'movie')
            plugin_instance.tmdb_client.fill_list_item(li, meta_for_playback, m_type)
        else:
            if meta_for_playback:
                li.setArt({"poster": meta_for_playback.get("poster"), "fanart": meta_for_playback.get("fanart")})

        final_meta = meta_for_playback if meta_for_playback else {"title": video["title"], "media_type": "movie"}
        final_meta['source_title'] = f"{prov.upper()} - {video['title']}"


        # =========================================================================
        # CRUCIAL FIX: ZABRÁNĚNÍ SLUČOVÁNÍ V REŽIMU "MOVIES"
        # =========================================================================


        info_tag = li.getVideoInfoTag()
        info_tag.setTitle(label)
        info_tag.setUniqueIDs({'tmdb': f"stream_{i}"})

        # --- CONTEXT MENU Z CENTRALIZACE

        context_menu = _get_context_menu(
            'search_results',
            addon=plugin_instance.addon,
            title=final_meta.get("title", video["title"]),
            tmdb_id=final_meta.get("tmdb_id", ""),
            media_type=final_meta.get("media_type", "movie"),
            year=final_meta.get("year", ""),
            poster=final_meta.get("poster", ""),
            plot=final_meta.get("plot", ""),
            props=final_meta,
            provider=video.get("provider"),
            video_link=video.get("link")
        )
        li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

        url = get_url(action="play", link=video["link"], provider=video.get("provider"), meta=json.dumps(final_meta))
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)


    # === ZÁVĚR FUNKCE S TVRDÝM FALLBACKEM NA 507 ===

    # Nastavíme natvrdo na movies, abychom oklamali skin

    xbmcplugin.setContent(plugin_instance.handle, "movies")

    # --- UI Builder

    try:
        from resources.lib.ui_builder import set_view_mode
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "search_results")
    except Exception:
        pass

    # --- FALLBACK NA 507, pokud máš UI Builder vypnutý

    if "arctic.fuse" in xbmc.getSkinDir() and not xbmc.getCondVisibility("Window.IsVisible(home)"):
        if not plugin_instance.addon.getSettingBool("enable_view_modes"):
            xbmc.executebuiltin("Container.SetViewMode(507)")

    log("SEARCH - Končím (listing výsledků).", xbmc.LOGDEBUG)
    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True)



def _tmdbh_empty_search_fallback(query, meta, providers, sort_priority, raw_results, plugin_instance, apply_continue_filters=False):

    """
    TMDBH :: EMPTY EN FALLBACK
    -- Try an EN title lazily, then offer known locally hidden rows for this call.
    """

    client = plugin_instance.tmdb_client
    media_type = meta.get("media_type")
    tmdb_id = meta.get("tmdb_id")
    if providers and client and tmdb_id:
        try:
            lookup_type = "tv" if media_type in ("episode", "show") else media_type
            details = client.get_full_details(lookup_type, tmdb_id, lang="en-US")
            english_title = (details.get("title") or details.get("name") or "").strip() if details else ""
            if english_title:
                if media_type == "episode":
                    season, episode = int(meta.get("season")), int(meta.get("episode"))
                    english_query = f"{english_title} S{season:02d}E{episode:02d}"
                else:
                    english_query = f"{english_title} {meta.get('year', '')}".strip()
                normalize = lambda value: " ".join(encode(value).casefold().split())
                if normalize(english_query) != normalize(query):
                    log(f"TMDBH SEARCH - Bez výsledků pro '{query}', zkouším EN: '{english_query}'", xbmc.LOGINFO)
                    results = _search_providers_parallel(
                        english_query, providers, apply_filters=True,
                        sort_priority=sort_priority, unfiltered_results=raw_results)
                    if apply_continue_filters:
                        # A pre-emptive cache selection also carries Continue filters.
                        from resources.lib.generator import _apply_continue_filters
                        results = _apply_continue_filters(results, plugin_instance.addon)
                    if results:
                        return results
        except Exception as exc:
            log(f"TMDBH SEARCH - EN fallback není dostupný: {exc}", xbmc.LOGWARNING)

    # --- No server rows means there is no evidence that local filters hid content.
    #     Never modify persistent settings or bypass server/category/quality limits.

    hidden, seen = [], set()
    for video in raw_results:
        key = (video.get("provider"), video.get("link"))
        if key not in seen:
            seen.add(key)
            hidden.append(video)
    if hidden and xbmcgui.Dialog().yesno(
            "[ PLAY.ER ] :: FILTRY SKRYLY VÝSLEDKY",
            f"Nalezeno  [ {len(hidden)} ]  zdrojů, ale žádný nevyhovuje nastaveným filtrům. "
            "Zobrazit skryté výsledky? Nastavení filtrů se nezmění.",
            nolabel="PONECHAT", yeslabel="ZOBRAZIT"):
        return hidden
    return []



def find_and_list_sources_multi(params, plugin_instance, tmdbh_search=False):

    """
    PLUGIN :: MULTI-PROVIDER SOURCES
    -- Hledání zdrojů  ( MULTI-PROVIDER ).
    """

    meta_raw = params.get("meta")
    if not meta_raw: return

    meta = get_meta_from_cache(meta_raw)
    media_type = meta.get("media_type")
    tmdb_id = meta.get("tmdb_id")

    search_title = meta.get("title", "")
    tv_show_title = meta.get("tv_show_title", "")

    if plugin_instance.addon.getSettingBool('trakt_prefer_czech_search') and tmdb_id:
        lookup_type = 'tv' if media_type == 'episode' else media_type
        if plugin_instance.tmdb_client:
            try:
                loc_title = plugin_instance.tmdb_client.get_localized_title(lookup_type, tmdb_id, 'cs')
                if loc_title:
                    log(f"SEARCH - LOKALIZOVANÝ NÁZEV : {loc_title}", xbmc.LOGINFO)
                    if media_type == 'episode': tv_show_title = loc_title
                    else: search_title = loc_title
            except Exception as e:
                log(f"SEARCH - CHYBA LOKALIZACE NÁZVU : {e}", xbmc.LOGWARNING)

    query = f"{search_title} {meta.get('year', '')}".strip()
    if media_type == "episode":
        try:
            s, e = int(meta.get("season")), int(meta.get("episode"))
            query = f"{tv_show_title} S{s:02d}E{e:02d}"
        except: pass

    providers = plugin_instance.provider_manager.get_providers_to_search()
    sort_priority = plugin_instance.addon.getSetting("multi_provider_sort")

    cached_results = None
    if media_type == "episode" and tmdb_id:
        try:
            season = int(meta.get("season", 0))
            episode = int(meta.get("episode", 0))
            cache_key = f"preemptive_{tmdb_id}_S{season:02d}E{episode:02d}"
            cached_data = cache_manager.cache_get("PREEMPTIVE_SOURCES", cache_key)

            if cached_data and isinstance(cached_data, dict):
                import time
                cache_age = time.time() - cached_data.get("timestamp", 0)
                if 0 <= cache_age < 1800 and isinstance(cached_data.get("results"), list):
                    cached_results = cached_data.get("results",[])
                    log(f"SOURCES - Načteno {len(cached_results)} zdrojů z pre-emptive cache", xbmc.LOGINFO)
        except Exception as e:
            log(f"SOURCES - Chyba při čtení pre-emptive cache: {e}", xbmc.LOGWARNING)

    # --- FIX PRE-EMPTIVE AND FILTERS [PRE-EMPTIVE CACHE FILTERS]
    #     Původní zkratka vracela cache bez globálních ani Continue filtrů:
    #     results = cached_results if cached_results else _search_providers_parallel(query, providers, apply_filters=True, sort_priority=sort_priority)

    unfiltered_results = [] if tmdbh_search else None
    if cached_results:
        if tmdbh_search:
            unfiltered_results.extend(dict(video) for video in cached_results)
        results = FilterUtils(plugin_instance.addon).apply_filters(
            cached_results,
            enable_setting_id="enable_filtering",
            invert_enable_logic=False,
            include_setting_ids=["filter_global"],
            exclude_setting_ids=["exclude_global"]
        )
        from resources.lib.generator import _apply_continue_filters
        results = _apply_continue_filters(results, plugin_instance.addon)
    else:
        results = _search_providers_parallel(query, providers, apply_filters=True,
                                            sort_priority=sort_priority, unfiltered_results=unfiltered_results)

    if tmdbh_search and not results:
        results = _tmdbh_empty_search_fallback(
            query, meta, providers, sort_priority, unfiltered_results, plugin_instance,
            apply_continue_filters=bool(cached_results))

    if not results:
        notify_info("INFO Žádné zdroje nenalezeny", category="SOURCES")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
        return

    show_size = plugin_instance.addon.getSettingBool("show_size")
    show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
    filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_tmdb")

    meta_key = store_meta_in_cache(meta)

    for i, vid in enumerate(results):
        color = Colors.LIMEGREEN if vid.get("provider") == "webshare.cz" else Colors.ORANGE

        size_tag = ""
        duration_tag = ""

        if show_size and vid.get("size_str"):
            raw = vid.get("size_str")
            try:
                from resources.lib.utils import convert_size_to_bytes, convert_size
                b = convert_size_to_bytes(raw)
            except Exception:
                b = None
            normalized = convert_size(b) if b else raw
            size_tag = f'[LIGHT][COLOR {color}][{normalized}][/LIGHT][/COLOR] '

        if show_duration and vid.get("duration_str") and vid["duration_str"] != "0":
            duration_tag = f'[LIGHT][COLOR gray][{vid["duration_str"]}][/COLOR][/LIGHT] '

        if filter_enabled:
            try:
                from resources.lib.utils_filter import clean_display_title
                cleaned_title, _, _, _ = clean_display_title(
                    vid["title"],
                    explicit_tags=vid.get("tags", []),
                    extension=vid.get("extension"),
                    likes=vid.get("likes", 0)
                )
                label = f'{size_tag}{duration_tag}{cleaned_title}'.strip()
            except Exception:
                label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()
        else:
            label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()

        li = xbmcgui.ListItem(label=label)
        li.setProperty("IsPlayable", "true")

        if plugin_instance.tmdb_client:
            plugin_instance.tmdb_client.fill_list_item(li, meta, media_type)
        else:
            li.setArt({"poster": meta.get("poster"), "fanart": meta.get("fanart")})

        # FIX PRE-EMPTIVE AND FILTERS [SOURCE LABEL IS NOT EPISODE METADATA]
        # Keep the release filename in the directory label, not in the video tag.
        # info_tag = li.getVideoInfoTag()
        # info_tag.setTitle(label)
        # info_tag.setUniqueIDs({'tmdb': f"stream_{i}"})
        # Kodi checks OverrideInfotag on THIS item before merging the resolver
        # result. Setting it only on setResolvedUrl's item would be too late.

        context_menu = _get_context_menu(
            'source_results', addon=plugin_instance.addon, props=meta,
            provider=vid.get('provider'), video_link=vid['link']
        )
        li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

        li.setProperty('OverrideInfotag', 'true')
        li.setProperty('play_er.source_index', str(i))

        url_params = {'action': 'play', 'link': vid["link"], 'provider': vid.get("provider"), 'meta': meta_key}
        # URL_CACHE is keyed by episode, not source: keep each choice's small
        # fingerprint on its action URL instead of overwriting shared metadata.
        if (tmdbh_search and media_type == 'episode'
                and str(plugin_instance.addon.getSetting('auto_prediction_enable')).lower() == 'true'):
            from resources.lib.utils_auto_prediction import capture_reference, REFERENCE
            choice_meta = dict(meta)
            choice_meta.pop(REFERENCE, None)
            capture_reference(choice_meta, vid, plugin_instance.addon)
            if REFERENCE in choice_meta:
                url_params['prediction_ref'] = json.dumps(choice_meta[REFERENCE], ensure_ascii=False)
        if params.get('source_list'): url_params['source_list'] = params.get('source_list')

        # Run the selected TMDBHelper episode as an action, matching CONTINUE.
        # Kodi must not resolve it as a plugin playlist item: its files record
        # can replace the active episode tag exposed to JSON-RPC clients.
        if tmdbh_search and media_type == 'episode':
            li.setProperty('IsPlayable', 'false')
            url_params['direct_play'] = 'true'
        url = get_url(**url_params)
        if media_type == 'episode' and not tmdbh_search:
            li.setProperty('original_listitem_url', url)
            url = get_url(**url_params, live_metadata='true')
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)

    # 1. Vyčištění zablokovaného stavu okna z TMDBHelperu

    videos_window = xbmcgui.Window(10025)
    videos_window.clearProperty('tmdbhelper.windowmanager')
    videos_window.clearProperty('tmdbhelper.isupdating')
    videos_window.setProperty('is_source_select', 'true')

    # 2. Nastavení obsahu na "movies" namísto "files"

    xbmcplugin.setContent(plugin_instance.handle, "movies")

    # 3. Pokus o nastavení přes UI Builder, pokud je zapnutý

    try:
        from resources.lib.ui_builder import set_view_mode
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "search_results")
    except Exception:
        pass

    # 4. FALLBACK: VYNUCENÍ ZOBRAZENÍ 507

    if "arctic.fuse" in xbmc.getSkinDir() and not xbmc.getCondVisibility("Window.IsVisible(home)"):
        if not plugin_instance.addon.getSettingBool("enable_view_modes"):
            xbmc.executebuiltin("Container.SetViewMode(507)")

    # 5. Závěr sestavení adresáře (TADY JE OPRAVA PRO AF3)

    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)



# def find_and_list_sources_multi(params, plugin_instance):
#
#     """
#     PLUGIN :: MULTI-PROVIDER SOURCES
#     -- Hledání zdrojů  ( MULTI-PROVIDER ).
#     -- Čisté a rychlé volání bez zdržujících dialogů.
#     """
#
#     meta_raw = params.get("meta")
#     if not meta_raw: return
#
#     meta = get_meta_from_cache(meta_raw)
#     media_type = meta.get("media_type")
#     tmdb_id = meta.get("tmdb_id")
#
#     search_title = meta.get("title", "")
#     tv_show_title = meta.get("tv_show_title", "")
#
#     if plugin_instance.addon.getSettingBool('trakt_prefer_czech_search') and tmdb_id:
#         lookup_type = 'tv' if media_type == 'episode' else media_type
#         if plugin_instance.tmdb_client:
#             try:
#                 loc_title = plugin_instance.tmdb_client.get_localized_title(lookup_type, tmdb_id, 'cs')
#                 if loc_title:
#                     log(f"SEARCH - LOKALIZOVANÝ NÁZEV : {loc_title}", xbmc.LOGINFO)
#                     if media_type == 'episode': tv_show_title = loc_title
#                     else: search_title = loc_title
#             except Exception as e:
#                 log(f"SEARCH - CHYBA LOKALIZACE NÁZVU : {e}", xbmc.LOGWARNING)
#
#     query = f"{search_title} {meta.get('year', '')}".strip()
#     if media_type == "episode":
#         try:
#             s, e = int(meta.get("season")), int(meta.get("episode"))
#             query = f"{tv_show_title} S{s:02d}E{e:02d}"
#         except: pass
#
#     providers = plugin_instance.provider_manager.get_providers_to_search()
#     sort_priority = plugin_instance.addon.getSetting("multi_provider_sort")
#
#     cached_results = None
#     if media_type == "episode" and tmdb_id:
#         try:
#             season = int(meta.get("season", 0))
#             episode = int(meta.get("episode", 0))
#             cache_key = f"preemptive_{tmdb_id}_S{season:02d}E{episode:02d}"
#             cached_data = cache_manager.cache_get("PREEMPTIVE_SOURCES", cache_key)
#
#             if cached_data and isinstance(cached_data, dict):
#                 import time
#                 cache_age = time.time() - cached_data.get("timestamp", 0)
#                 if cache_age < 1800:
#                     cached_results = cached_data.get("results",[])
#                     log(f"SOURCES - Načteno {len(cached_results)} zdrojů z pre-emptive cache", xbmc.LOGINFO)
#         except Exception as e:
#             log(f"SOURCES - Chyba při čtení pre-emptive cache: {e}", xbmc.LOGWARNING)
#
#     # Čisté vyhledání - žádné zdržující dialogy
#     results = cached_results if cached_results else _search_providers_parallel(query, providers, apply_filters=True, sort_priority=sort_priority)
#
#     if not results:
#         notify_info("INFO Žádné zdroje nenalezeny", category="SOURCES")
#         xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
#         return
#
#     show_size = plugin_instance.addon.getSettingBool("show_size")
#     show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
#     filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_tmdb")
#
#     meta_key = store_meta_in_cache(meta)
#
#     for i, vid in enumerate(results):
#         from resources.lib.utils_theme import Colors
#         color = Colors.LIMEGREEN if vid.get("provider") == "webshare.cz" else Colors.ORANGE
#
#         size_tag = ""
#         duration_tag = ""
#
#         if show_size and vid.get("size_str"):
#             raw = vid.get("size_str")
#             try:
#                 from resources.lib.utils import convert_size_to_bytes, convert_size
#                 b = convert_size_to_bytes(raw)
#             except Exception:
#                 b = None
#             normalized = convert_size(b) if b else raw
#             size_tag = f'[LIGHT][COLOR {color}][{normalized}][/LIGHT][/COLOR] '
#
#         if show_duration and vid.get("duration_str") and vid["duration_str"] != "0":
#             duration_tag = f'[LIGHT][COLOR gray][{vid["duration_str"]}][/COLOR][/LIGHT] '
#
#         if filter_enabled:
#             try:
#                 from resources.lib.utils_filter import clean_display_title
#                 cleaned_title, _, _, _ = clean_display_title(
#                     vid["title"],
#                     explicit_tags=vid.get("tags", []),
#                     extension=vid.get("extension"),
#                     likes=vid.get("likes", 0)
#                 )
#                 label = f'{size_tag}{duration_tag}{cleaned_title}'.strip()
#             except Exception:
#                 label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()
#         else:
#             label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()
#
#         li = xbmcgui.ListItem(label=label)
#         li.setProperty("IsPlayable", "true")
#
#         if plugin_instance.tmdb_client:
#             plugin_instance.tmdb_client.fill_list_item(li, meta, media_type)
#         else:
#             li.setArt({"poster": meta.get("poster"), "fanart": meta.get("fanart")})
#
#         info_tag = li.getVideoInfoTag()
#         info_tag.setTitle(label)
#         info_tag.setUniqueIDs({'tmdb': f"stream_{i}"})
#
#         url_params = {'action': 'play', 'link': vid["link"], 'provider': vid.get("provider"), 'meta': meta_key}
#         if params.get('source_list'): url_params['source_list'] = params.get('source_list')
#
#         url = get_url(**url_params)
#         xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)
#
#     # 1. Vyčištění zablokovaného stavu okna z TMDBHelperu
#
#     videos_window = xbmcgui.Window(10025)
#     videos_window.clearProperty('tmdbhelper.windowmanager')
#     videos_window.clearProperty('tmdbhelper.isupdating')
#     videos_window.setProperty('is_source_select', 'true')
#
#     # 2. Nastavení obsahu na "movies" namísto "files"
#
#     xbmcplugin.setContent(plugin_instance.handle, "movies")
#
#     # 3. Pokus o nastavení přes UI Builder, pokud je zapnutý
#
#     try:
#         from resources.lib.ui_builder import set_view_mode
#         set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "search_results")
#     except Exception:
#         pass
#
#     # 4. FALLBACK: VYNUCENÍ ZOBRAZENÍ 507
#
#     if "arctic.fuse" in xbmc.getSkinDir() and not xbmc.getCondVisibility("Window.IsVisible(home)"):
#         if not plugin_instance.addon.getSettingBool("enable_view_modes"):
#             xbmc.executebuiltin("Container.SetViewMode(507)")
#
#     # 5. Závěr sestavení adresáře s parametry pro AF3 Skin
#
#     xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)



def most_watched(plugin_instance, is_widget=False):

    """
    PLUGIN :: MOST WATCHED
    -- Zobrazí nejsledovanější  ( pouze pro PREHRAJ.TO ).
    """

    prov = plugin_instance.provider_manager._get_provider_instance("prehraj.to")

    if not prov:
        if not is_widget:
            notify_error("ERROR PREHRAJ.TO NENÍ K DISPOZICI", category="PROVIDER")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
        return

    try:
        videos = prov.get_most_watched()
    except Exception:
        videos = []

    if videos:
        show_size = plugin_instance.addon.getSettingBool("show_size")
        show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
        filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_watch")

        for vid in videos:
            prov = vid.get('provider', '')
            color = Colors.LIMEGREEN if vid.get('is_series') else Colors.ORANGE

            size_tag = ""
            duration_tag = ""
            likes_tag = ""

            if show_size and vid.get('size_str'):
                raw = vid.get('size_str')
                try:
                    b = convert_size_to_bytes(raw)
                except Exception:
                    b = None
                normalized = convert_size(b) if b else raw
                size_tag = f'[LIGHT][COLOR {color}][{normalized}][/LIGHT][/COLOR] '

            if show_duration and vid.get("duration_str") and vid["duration_str"] != "0":
                duration_tag = f'[LIGHT][COLOR gray][{vid["duration_str"]}][/COLOR][/LIGHT] '


            if filter_enabled:
                try:
                    cleaned, is_series, suffix_parts, year = clean_display_title(
                        vid.get('title', ''),
                        likes=vid.get("likes", 0)
                    )
                    label = f"{size_tag}{duration_tag}{cleaned}".strip()
                except Exception:
                    label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()
            else:
                label = f'{size_tag}{duration_tag}{vid["title"]}'.strip()


            meta_title = vid.get('title')

            li = xbmcgui.ListItem(label=label)
            li.setProperty("IsPlayable", "true")

            m_type = 'episode' if vid.get('is_series') else 'movie'
            props = {}

            if plugin_instance.tmdb_client:
                props = {
                    "title": meta_title,
                    "plot": "[COLOR orange]Nejsledovanější na serveru[/COLOR]"
                }

                plugin_instance.tmdb_client.fill_list_item(li, props, m_type)
            else:
                li.setArt({"icon": Icons.PLAYER})

            video_link = vid["link"]

            context_menu = _get_context_menu(
                'most_watched',
                addon=plugin_instance.addon,
                title=meta_title,
                tmdb_id=props.get("tmdb_id", "") if plugin_instance.tmdb_client else "",
                media_type=m_type,
                year=props.get("year", "") if plugin_instance.tmdb_client else "",
                poster=props.get("poster", "") if plugin_instance.tmdb_client else "",
                plot=props.get("plot", "") if plugin_instance.tmdb_client else "",
                props=props,
                provider=vid.get('provider'),
                video_link=video_link
            )
            li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

            meta = {"title": meta_title, "from_most_watched": True}

            url = get_url(action="find_meta_and_resolve", title=vid["title"], link=vid["link"], provider="prehraj.to", meta=json.dumps(meta))
            xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)

    xbmcplugin.setContent(plugin_instance.handle, "videos")
    if not is_widget:
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "videos", "most_watched")

    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)



def prehrajto_history(plugin_instance, is_widget=False):

    """
    PLUGIN :: PREHRAJ.TO HISTORY
    -- Zobrazí historii sledování z webu Prehraj.to.
    """

    prov = plugin_instance.provider_manager._get_provider_instance("prehraj.to")

    if not prov:
        if not is_widget:
            notify_error("ERROR PREHRAJ.TO NENÍ K DISPOZICI", category="PROVIDER")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
        return

    try:
        videos = prov.get_user_history()
    except Exception:
        videos = []

    if videos:
        show_size = plugin_instance.addon.getSettingBool("show_size")
        show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
        filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_history")

        for vid in videos:
            color = Colors.ORANGE

            size_tag = ""
            duration_tag = ""
            likes_tag = ""

            if show_size and vid.get('size_str'):
                size_tag = f'[LIGHT][COLOR {color}][{vid.get("size_str")}][/LIGHT][/COLOR] '

            if show_duration and vid.get("duration_str") and vid["duration_str"] != "0":
                duration_tag = f'[LIGHT][COLOR gray][{vid["duration_str"]}][/COLOR][/LIGHT] '


            if filter_enabled:
                try:
                    display_title, _, _, _ = clean_display_title(
                        vid["title"],
                        likes=vid.get("likes", 0)
                    )
                except Exception:
                    pass

            label = f'{size_tag}{duration_tag}{display_title}'.strip()


            meta_title = vid.get('title')

            li = xbmcgui.ListItem(label=label)
            li.setProperty("IsPlayable", "true")

            props = {}
            if plugin_instance.tmdb_client:
                props = {
                    "title": meta_title,
                    "plot": "[COLOR orange]Historie prehrávání na serveru[/COLOR]"
                }

                plugin_instance.tmdb_client.fill_list_item(li, props, 'movie')
            else:
                li.setArt({"icon": Icons.HISTORY})

            video_link = vid["link"]

            context_menu = _get_context_menu(
                'prehrajto_history',
                addon=plugin_instance.addon,
                title=meta_title,
                tmdb_id=props.get("tmdb_id", "") if plugin_instance.tmdb_client else "",
                media_type='movie',
                year=props.get("year", "") if plugin_instance.tmdb_client else "",
                poster=props.get("poster", "") if plugin_instance.tmdb_client else "",
                plot=props.get("plot", "") if plugin_instance.tmdb_client else "",
                props=props,
                provider=vid.get('provider'),
                video_link=video_link
            )
            li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)
            meta = {"title": meta_title}
            url = get_url(action="find_meta_and_resolve", title=vid["title"], link=vid["link"], provider="prehraj.to", meta=json.dumps(meta))
            xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)

    xbmcplugin.setContent(plugin_instance.handle, "videos")
    if not is_widget:
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "videos", "most_watched")

    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)



def playback_history(plugin_instance, is_widget=False):

    """
    PLUGIN :: PLAYBACK HISTORY
    -- Zobrazí historii funkce PLAYBACK  ( Nyní z SQL cache ).
    """

    try:
        history = cache_manager.user_data_get("playback_history") or []
    except Exception:
        history = []

    if not history:
        if not is_widget:
            notify_info("INFO ŽÁDNÁ HISTORIE PŘEHRÁVÁNÍ", category="PLAYBACK")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
        return

    from collections import defaultdict
    shows_dict = defaultdict(list)
    shows_order = []
    seen_shows = set()
    movies = []

    for item in history:
        meta = item.get("meta", {})
        media_type = meta.get("media_type", "movie")
        if media_type == "episode":
            show_title = meta.get("tv_show_title", "Neznámý seriál")
            shows_dict[show_title].append(item)
            if show_title not in seen_shows:
                shows_order.append(show_title)
                seen_shows.add(show_title)
        else:
            movies.append(item)

    items_to_fetch = []

    for show_title in shows_order:
        if shows_dict[show_title]:
            first_meta = shows_dict[show_title][0].get("meta", {})
            tmdb_id = first_meta.get("tmdb_id")
            if tmdb_id: items_to_fetch.append(('tv', tmdb_id))

    for item in movies:
        meta = item.get("meta", {})
        tmdb_id = meta.get("tmdb_id")
        if tmdb_id: items_to_fetch.append(('movie', tmdb_id))

    def _fetch_meta_worker(item):
        m_type, m_id = item
        client = plugin_instance.tmdb_client
        if not client: return
        try:
            if m_type == 'tv':
                cache_key = f"tv_{m_id}"
                client._fetch(f"tv/{m_id}", params={'append_to_response': 'credits'}, cache_key=cache_key)
            elif m_type == 'movie':
                cache_key = f"movie_{m_id}"
                client._fetch(f"movie/{m_id}", params={'append_to_response': 'credits'}, cache_key=cache_key)
        except: pass

    if items_to_fetch:
        max_workers = get_threadpool(10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(_fetch_meta_worker, items_to_fetch)

    for show_title in shows_order:
        first_meta = shows_dict[show_title][0].get("meta", {})
        tmdb_id = first_meta.get("tmdb_id")

        show_data_raw = {}
        if plugin_instance.tmdb_client and tmdb_id:
            cache_key = f"tv_{tmdb_id}"
            show_data_raw = cache_manager.cache_get("TMDB", cache_key) or {}

        if show_data_raw:
            props = plugin_instance.tmdb_client._build_metadata_props(show_data_raw, 'tv')
        else:
            props = {
                'title': show_title,
                'tmdb_id': tmdb_id,
                'poster': first_meta.get("poster"),
                'fanart': first_meta.get("fanart"),
                'media_type': 'tv'
            }

        list_item = xbmcgui.ListItem(label=props.get('title', show_title))
        list_item.setProperty("IsPlayable", "false")
        plugin_instance.tmdb_client.fill_list_item(list_item, props, 'tvshow')

        status = show_data_raw.get("status")
        if status:
            list_item.setProperty("status", status)
            list_item.getVideoInfoTag().setTvShowStatus(status)

        context_menu = _get_context_menu(
            'playback_history_show',
            history_title=show_title,
            addon=plugin_instance.addon,
            title=props.get('title', show_title),
            tmdb_id=tmdb_id,
            media_type='tv',
            year=props.get("year", ""),
            poster=props.get("poster", ""),
            plot=props.get("plot", ""),
            props=props
        )
        list_item.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

        url = get_url(action="playback_show_history", show_title=show_title)
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, list_item, isFolder=True)

    for item in movies:
        meta = item.get("meta", {})
        link = item["link"]
        tmdb_id = meta.get("tmdb_id")

        movie_data_raw = {}
        if plugin_instance.tmdb_client and tmdb_id:
            cache_key = f"movie_{tmdb_id}"
            movie_data_raw = cache_manager.cache_get("TMDB", cache_key) or {}

        if movie_data_raw:
            props = plugin_instance.tmdb_client._build_metadata_props(movie_data_raw, 'movie')
        else:
            props = meta.copy()
            props['media_type'] = 'movie'

        label = props.get("title", "Neznámý titul")
        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty("IsPlayable", "true")
        plugin_instance.tmdb_client.fill_list_item(list_item, props, 'movie')

        context_menu = _get_context_menu(
            'playback_history_movie',
            history_title=meta.get('title', label),
            addon=plugin_instance.addon,
            title=props.get('title', label),
            tmdb_id=tmdb_id,
            media_type='movie',
            year=props.get("year", ""),
            poster=props.get("poster", ""),
            plot=props.get("plot", ""),
            props=props,
            provider=meta.get('provider', ''),
            video_link=link
        )
        list_item.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

        url = get_url(action="find_sources", meta=json.dumps(meta))
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, list_item, isFolder=True)

    xbmcplugin.setContent(plugin_instance.handle, "movies")
    if not is_widget:
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "playback_history")

    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)



def playback_show_history(params, plugin_instance):

    """
    PLUGIN :: PLAYBACK SHOW HISTORY
    -- Zobrazí historii funkce PLAYBACK  ( epizody seriálu ).
    """

    show_title = params["show_title"]

    try:
        history = cache_manager.user_data_get("playback_history") or[]
    except Exception:
        history = []

    episodes =[
        item
        for item in history
        if item["meta"].get("media_type") == "episode"
        and item["meta"].get("tv_show_title") == show_title
    ]

    def _fetch_ep_worker(item):
        meta = item.get("meta", {})
        tmdb_id = meta.get("tmdb_id")
        s = meta.get("season")
        e = meta.get("episode")
        if tmdb_id and s and e:
            cache_key = f"tv_{tmdb_id}_s{s}_e{e}"
            try:
                plugin_instance.tmdb_client._fetch(f"tv/{tmdb_id}/season/{s}/episode/{e}", params={'append_to_response': 'credits'}, cache_key=cache_key)
            except: pass

    max_workers = get_threadpool(10)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(_fetch_ep_worker, episodes)

    for item in episodes:
        meta = item.get("meta", {})
        link = item["link"]
        media_type = meta.get("media_type", "episode")

        tmdb_id = meta.get("tmdb_id")
        season = meta.get("season")
        episode = meta.get("episode")

        episode_data_raw = {}
        if tmdb_id and season and episode and plugin_instance.tmdb_client:
            cache_key = f"tv_{tmdb_id}_s{season}_e{episode}"
            episode_data_raw = cache_manager.cache_get("TMDB", cache_key) or {}

        if episode_data_raw:
            props = plugin_instance.tmdb_client._build_metadata_props(episode_data_raw, 'episode')

            props['tv_show_title'] = meta.get("tv_show_title")
        else:

            props = meta.copy()
            props['media_type'] = 'episode'

        ep_name = props.get("title", meta.get("title", "Neznámý titul"))
        label = f"S{int(season or 0):02d}E{int(episode or 0):02d} - {ep_name}"

        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty("IsPlayable", "true")

        plugin_instance.tmdb_client.fill_list_item(list_item, props, 'episode')

        # --- CONTEXT MENU Z CENTRALIZACE

        context_menu = _get_context_menu(
            'playback_show_episodes',
            addon=plugin_instance.addon,
            title=ep_name,
            tmdb_id=tmdb_id,
            media_type='episode',
            year=props.get("year", ""),
            poster=props.get("poster", ""),
            plot=props.get("plot", ""),
            props=props,
            show_title=show_title,
            season=str(season),
            episode=str(episode),
            provider=meta.get('provider', ''),
            video_link=link
        )
        list_item.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

        url = get_url(action="find_sources", meta=json.dumps(meta))
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, list_item, isFolder=True)

    xbmcplugin.setContent(plugin_instance.handle, "episodes")
    set_view_mode(plugin_instance.handle, plugin_instance.addon, "episodes", "episodes")
    xbmcplugin.endOfDirectory(plugin_instance.handle)


def search_tmdb_from_history(params, plugin_instance):

    """
    PLUGIN :: SEARCH TMDB FROM PLAYBACK HISTORY
    -- Hledá v historii TMDB.
    """

    show_title = params.get('show_title')
    tmdb_id = params.get('tmdb_id')

    if not show_title and not tmdb_id:
        notify_info("Chybný parametr: show_title nebo tmdb_id chybí")
        return

    tmdb_client = plugin_instance.tmdb_client
    if not tmdb_client:
        notify_info("TMDB klient není dostupný")
        return

    try:
        if tmdb_id:
            props = None
            try:
                details = tmdb_client.get_full_details('tv', tmdb_id)
                if details:
                    props = tmdb_client._build_metadata_props(details, 'tv')
            except Exception: pass

            if not props:
                props = {'tmdb_id': tmdb_id, 'media_type': 'tv', 'title': show_title or ''}

            meta_json = json.dumps(props, ensure_ascii=False)
            try:
                url = get_url(action='listing_tmdb_tv', tmdb_id=str(tmdb_id), meta=meta_json)
                xbmc.executebuiltin(f"Container.Update({url})")
                return
            except Exception:
                tmdb_client.show_tv_detail(tmdb_id, meta_json, None)
                return

        if show_title:
            url = get_url(action='search_tmdb', name=show_title, type='tv')
            xbmc.executebuiltin(f"RunPlugin({url})")
            return

    except Exception:
        notify_error('Chyba při dotazu TMDB')
    return


def remove_playback_item(params, plugin_instance):

    """
    PLUGIN :: PLAYBACK REMOVE ITEM
    -- Odstraní položku z historie  ( SQL cache ).
    """

    item_type = params.get("type")
    show_title_param = params.get("show_title")
    episode_season = params.get("season")
    episode_episode = params.get("episode")
    movie_title = params.get("movie_title")

    try:
        history = cache_manager.user_data_get("playback_history") or[]
    except: return

    new_hist =[]
    for item in history:
        m = item.get("meta", {})
        remove = False
        if item_type == "movie" and m.get("title") == movie_title: remove = True
        elif item_type == "show" and m.get("tv_show_title") == show_title_param and m.get("media_type") == "episode": remove = True
        elif item_type == "episode" and m.get("tv_show_title") == show_title_param and str(m.get("season")) == episode_season and str(m.get("episode")) == episode_episode: remove = True

        if not remove: new_hist.append(item)

    cache_manager.user_data_set("playback_history", new_hist)
    cache_manager.safe_refresh()


def select_episode_stream(params, plugin_instance):
    series_name = params.get("series_name")
    season = params.get("season")
    episode = params.get("episode")

    if not all([series_name, season, episode]): return

    series_data = plugin_instance.series_manager.load_series_data(series_name)
    if not series_data: return

    try:
        ep_data = series_data["seasons"][str(season)][str(episode)]
        streams = ep_data.get("streams",[])
    except KeyError: return

    if not streams:
        notify_info("ŽÁDNÉ DALŠÍ STREAMY K DISPOZICI")
        return

    filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_manager")

    labels =[]
    for s in streams:
        color = Colors.LIMEGREEN if s.get("provider", "").lower().startswith("web") else Colors.ORANGE

        display_name = s['name']
        if filter_enabled:
            try:
                cleaned_title, _, _, _ = clean_display_title(s['name'])
                display_name = cleaned_title
            except Exception: pass

        label = f"[COLOR {color}][ {s.get('size','?')} ][/COLOR] {display_name}"
        labels.append(label)

    choice = xbmcgui.Dialog().select(f"○  ZVOLIT ZDROJ  ○[  S{season}E{episode}  ]", labels)
    if choice >= 0:
        plugin_instance.series_manager.update_active_stream(series_name, season, episode, choice)
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def search_series(params, plugin_instance):
    series_name = params.get("series_name")
    if not series_name:
        kb = xbmc.Keyboard("", f"[COLOR {Colors.ORANGE}]○  ZADEJTE NÁZEV SERIÁLU  ○[/COLOR]")
        kb.doModal()
        if not kb.isConfirmed() or not kb.getText().strip(): return
        series_name = kb.getText().strip()

    providers = plugin_instance.provider_manager.get_providers_to_search()
    plugin_instance.series_manager.search_series(series_name, providers)
    try:
        cache_manager.safe_refresh()
    except Exception:
        pass


def delete_episode(params, plugin_instance):
    if plugin_instance.series_manager.delete_episode(params.get("series_name"), params.get("season"), params.get("episode")):
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def delete_season(params, plugin_instance):
    if plugin_instance.series_manager.delete_season(params.get("series_name"), params.get("season")):
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def delete_series(params, plugin_instance):
    if plugin_instance.series_manager.delete_series(params.get("series_name")):
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def mark_episode_watched(params, plugin_instance):
    if plugin_instance.series_manager.mark_episode_watched(params.get("series_name"), params.get("season"), params.get("episode")):
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def mark_episode_unwatched(params, plugin_instance):
    if plugin_instance.series_manager.mark_episode_unwatched(params.get("series_name"), params.get("season"), params.get("episode")):
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass


def _watch_later_episode_coordinates(meta):
    """Use show ID plus season and episode, including season zero."""
    try:
        values = [str(meta.get(key, '')).strip() for key in ('season', 'episode')]
        if not all(value.isascii() and value.isdecimal() for value in values):
            return None
        season, episode = map(int, values)
        return (season, episode) if episode >= 1 else None
    except (TypeError, ValueError):
        return None


def add_to_watch_later(params, plugin_instance):

    """
    WATCH LATER :: ADD ITEM
    -- Přidá položku ze seznamu "CHCI VIDĚT".
    """

    meta_json = params.get('meta')
    if not meta_json:
        notify_error("Chybí metadata pro přidání", category="WATCH LATER")
        return

    try:
        meta = json.loads(meta_json)
        tmdb_id = meta.get('tmdb_id')
        media_type = meta.get('media_type')

        items = cache_manager.user_data_get("watch_later") or[]

        episode_coordinates = _watch_later_episode_coordinates(meta) if media_type == 'episode' else None
        if any(
            str(item.get('tmdb_id')) == str(tmdb_id)
            and item.get('media_type') == media_type
            and (media_type != 'episode' or _watch_later_episode_coordinates(item) == episode_coordinates)
            for item in items
        ):
            notify_info("INFO Položka již existuje", category="WATCH LATER")
            return

        items.insert(0, meta)
        cache_manager.user_data_set("watch_later", items)

        notify_ok("Položka byla přidána", category="WATCH LATER")
        try:
            cache_manager.safe_refresh()
        except Exception:
            pass

    except Exception as e:
        log(f"WATCH LATER - Chyba při přidávání položky : {e}", xbmc.LOGERROR)
        notify_error("Chyba při přidávání položky", category="WATCH LATER")


def remove_from_watch_later(params, plugin_instance=None):

    """
    WATCH LATER :: REMOVE ITEM
    -- Odebere položku ze seznamu "CHCI VIDĚT".
    """

    tmdb_id = params.get('tmdb_id')
    media_type = params.get('media_type')

    if not tmdb_id:
        return

    items = cache_manager.user_data_get("watch_later") or []

    matches = [item for item in items
               if str(item.get('tmdb_id')) == str(tmdb_id)
               and item.get('media_type') == media_type]
    if media_type == 'episode':
        coordinates = _watch_later_episode_coordinates(params)
        if coordinates is None:
            # Older callers may supply only an ID. Do not guess among episodes.
            if len(matches) > 1 or any(params.get(key) not in (None, '') for key in ('season', 'episode')):
                notify_error("Nelze určit epizodu k odebrání", category="WATCH LATER")
                return
        else:
            matches = [item for item in matches if _watch_later_episode_coordinates(item) == coordinates]
    if not matches:
        return
    items = [item for item in items if item not in matches]
    cache_manager.user_data_set("watch_later", items)

    try:
        cache_manager.safe_refresh()
    except Exception:
        pass


def toggle_subscription(params, plugin_instance):

    """
    SUBSCRIPTION :: TOGGLE
    -- Přidá nebo odebere seriál ze seznamu odebíraných ( pro auto-download ).
    """

    tmdb_id = params.get("tmdb_id")
    title = params.get("title")

    if not tmdb_id: return

    subs = cache_manager.user_data_get("subscriptions") or[]

    exists = False
    for s in subs:
        if str(s.get("tmdb_id")) == str(tmdb_id):
            exists = True
            break

    if exists:
        subs =[s for s in subs if str(s.get("tmdb_id")) != str(tmdb_id)]
        notify_info(f"Odběr zrušen: {title}", category="SUBSCRIPTION")
    else:
        subs.append({"tmdb_id": tmdb_id, "title": title})
        notify_ok(f"Odběr aktivní: {title}", category="SUBSCRIPTION")

    cache_manager.user_data_set("subscriptions", subs)
    try:
        cache_manager.safe_refresh()
    except Exception:
        pass


def play_context_item(params, plugin_instance):

    """
    CONTEXT MENU :: PLAY
    -- Spustí přehrávání položky z kontextového menu Kodi knihovny.
    """

    tmdb_id = xbmc.getInfoLabel("ListItem.Property(tmdb_id)")
    db_type = xbmc.getInfoLabel("ListItem.DBType")
    title = xbmc.getInfoLabel("ListItem.Title")
    year = xbmc.getInfoLabel("ListItem.Year")
    season = xbmc.getInfoLabel("ListItem.Season")
    episode = xbmc.getInfoLabel("ListItem.Episode")
    tv_show_title = xbmc.getInfoLabel("ListItem.TVShowTitle")

    meta = {
        "tmdb_id": tmdb_id,
        "title": title,
        "year": year,
        "media_type": "episode" if db_type == "episode" else "movie"
    }

    if db_type == "episode":
        meta["season"] = season
        meta["episode"] = episode
        meta["tv_show_title"] = tv_show_title

    if tmdb_id:
        find_meta_and_resolve({"meta": json.dumps(meta)}, plugin_instance)
    else:
        search(title, plugin_instance, resolve_first=True)



# ===========================  PRE-EMPTIVE  ============================ #
# ---------------------------------------------------------------------- #



def pre_emptive_search(params, plugin_instance):

    """
    PRE-EMPTIVE :: SEARCH
    -- Vyhledá zdroje na pozadí a uloží je do cache pro okamžité použití.
    """

    import xbmc
    import xbmcgui

    from resources.lib.utils_notification import notify_ok, notify_info, notify_error
    from resources.lib.utils_logging import log
    from resources.lib.utils_theme import Colors


    meta_json = params.get("meta")
    if not meta_json: return

    try:
        meta = json.loads(meta_json)
        if meta.get("media_type") != "episode":
            log("PRE-EMPTIVE SEARCH - Pouze pro epizody", xbmc.LOGINFO)
            notify_info(f"ACTION ONLY FOR EPISODES", category="EMPTIVE", time=5000)
            return

        import threading
        thread = threading.Thread(target=_perform_pre_emptive_search, args=(meta, plugin_instance))
        thread.start()

        log("PRE-EMPTIVE SEARCH - VLÁKNO SPUŠTĚNO", xbmc.LOGINFO)
        notify_info(f"ACTION FIBER STARTED", category="EMPTIVE", time=5000)

    except Exception as e:
        log(f"PRE-EMPTIVE SEARCH - Chyba inicializace : {e}", xbmc.LOGERROR)
        notify_error(f"ACTION INITIALIZATION ERROR - {e}", category="EMPTIVE", time=5000)



def _perform_pre_emptive_search(meta, plugin_instance):

    """
    PRE-EMPTIVE :: PERFORM SEARCH
    -- Provede skutečné vyhledávání zdrojů pro další epizodu na pozadí.
    """

    import xbmc
    import time
    from resources.lib.utils_logging import log
    from resources.lib import cache_manager

    try:
        next_ep_meta = meta

        tv_show_title = next_ep_meta.get("tv_show_title", "")
        season = int(next_ep_meta.get("season", 0))
        episode = int(next_ep_meta["episode"])

        query = f"{tv_show_title} S{season:02d}E{episode:02d}"

        log(f"PRE-EMPTIVE SEARCH - HLEDÁM : {query}", xbmc.LOGINFO)
        notify_info(f"ACTION SEARCHING : {query}", category="EMPTIVE", time=5000)

        providers = plugin_instance.provider_manager.get_providers_to_search()

        if not providers:
            log("PRE-EMPTIVE SEARCH - Žádní providers k dispozici", xbmc.LOGWARNING)
            notify_info(f"ACTION NO PROVIDERS", category="EMPTIVE", time=5000)
            return

        results = _search_providers_parallel(query, providers, apply_filters=False)

        if not results:
            log(f"PRE-EMPTIVE SEARCH - Žádné výsledky pro: {query}", xbmc.LOGWARNING)
            notify_info(f"ACTION MISSING : {query}", category="EMPTIVE", time=5000)
            return

        cache_key = f"preemptive_{meta['tmdb_id']}_S{season:02d}E{episode:02d}"

        cache_manager.cache_set("PREEMPTIVE_SOURCES", cache_key, {
            "query": query,
            "results": results,
            "timestamp": int(time.time()),
            "meta": next_ep_meta
        })

        log(f"PRE-EMPTIVE SEARCH - DOKONČENO : {len(results)} zdrojů uloženo do cache klíče: {cache_key}", xbmc.LOGINFO)
        notify_info(f"ACTION COMPLETED - {len(results)}", category="EMPTIVE", time=5000)


    except Exception as e:
        log(f"PRE-EMPTIVE SEARCH - Chyba při vyhledávání: {e}", xbmc.LOGERROR)
        notify_error(f"ACTION ERROR - {e}", category="EMPTIVE", time=5000)



# ==============================  STREMIO  ============================= #
# ---------------------------------------------------------------------- #



def stremio_submenu(params, plugin_instance):

    """
    STREMIO BRIDGE :: SUBMENU
    -- Vytvoří standardní Kodi složku pro výběr.
    """

    menu_type = params.get("menu_type")
    items = []

    if menu_type == "dabing":
        items = [
            ("FILMY S DABINGEM (VŠECHNY)", get_url(action="stremio_items", cat_id="czdabing_movies", cat_type="movie", skip=0), Icons.MOVIE, "[COLOR orange]Všechny filmy s potvrzeným českým dabingem[/COLOR]"),
            ("FILMY S DABINGEM (ŽÁNRY)", get_url(action="stremio_genres_menu", cat_id="czdabing_movies", cat_type="movie"), Icons.GENTRE, "[COLOR orange]Filmy s dabingem rozdělené podle žánru[/COLOR]"),
            ("SERIÁLY S DABINGEM (VŠECHNY)", get_url(action="stremio_items", cat_id="czdabing_series", cat_type="series", skip=0), Icons.TVSHOW, "[COLOR orange]Všechny seriály s potvrzeným českým dabingem[/COLOR]"),
            ("SERIÁLY S DABINGEM (ŽÁNRY)", get_url(action="stremio_genres_menu", cat_id="czdabing_series", cat_type="series"), Icons.GENTRE, "[COLOR orange]Seriály s dabingem rozdělené podle žánru[/COLOR]")
        ]
    elif menu_type == "charts":
        items = [
            ("FILMOVÉ ŽEBŘÍČKY", get_url(action="list_stremio_catalogs", cat_type="movie", cat_group="charts"), Icons.MOVIE, "[COLOR orange]PROCHÁZET NEJNAVŠTĚVOVANĚJŠÍ A TRENDY FILMY[/COLOR]"),
            ("SERIÁLOVÉ ŽEBŘÍČKY", get_url(action="list_stremio_catalogs", cat_type="series", cat_group="charts"), Icons.TVSHOW, "[COLOR orange]PROCHÁZET NEJNAVŠTĚVOVANĚJŠÍ A TRENDY SERIÁLY[/COLOR]")
        ]
    elif menu_type == "csfd_vod":
        items = [
            ("ČSFD : FILMY STARTUJÍ NA VOD", get_url(action="stremio_items", cat_id="vod_starting_movies", cat_type="movie", skip=0), Icons.MOVIE, "[COLOR orange]Nové filmy startující na VOD službách dle ČSFD[/COLOR]"),
            ("ČSFD : SERIÁLY STARTUJÍ NA VOD", get_url(action="stremio_items", cat_id="vod_starting_series", cat_type="series", skip=0), Icons.TVSHOW, "[COLOR orange]Nové seriály startující na VOD službách dle ČSFD[/COLOR]"),
            ("ČSFD : NEJNAVŠTĚVOVANĚJŠÍ FILMY", get_url(action="stremio_items", cat_id="most_visited_movies", cat_type="movie", skip=0), Icons.MOVIE, "[COLOR orange]Aktuálně nejnavštěvovanější filmy na ČSFD[/COLOR]"),
            ("ČSFD : NEJNAVŠTĚVOVANĚJŠÍ SERIÁLY", get_url(action="stremio_items", cat_id="most_visited_series", cat_type="series", skip=0), Icons.TVSHOW, "[COLOR orange]Aktuálně nejnavštěvovanější seriály na ČSFD[/COLOR]")
        ]
    elif menu_type == "imdb":
        items = [
            ("IMDB : NEJPOPULÁRNĚJŠÍ FILMY", get_url(action="stremio_items", cat_id="imdb_popular_movies", cat_type="movie", skip=0), Icons.MOVIE, "[COLOR orange]Populární filmy podle IMDB[/COLOR]"),
            ("IMDB : FILMY PODLE ŽÁNRU", get_url(action="stremio_genres_menu", cat_id="imdb_popular_movies", cat_type="movie"), Icons.GENTRE, "[COLOR orange]Filtrovat IMDB filmy podle žánru[/COLOR]"),
            ("IMDB : NEJPOPULÁRNĚJŠÍ SERIÁLY", get_url(action="stremio_items", cat_id="imdb_popular_series", cat_type="series", skip=0), Icons.TVSHOW, "[COLOR orange]Populární seriály podle IMDB[/COLOR]"),
            ("IMDB : SERIÁLY PODLE ŽÁNRU", get_url(action="stremio_genres_menu", cat_id="imdb_popular_series", cat_type="series"), Icons.GENTRE, "[COLOR orange]Filtrovat IMDB seriály podle žánru[/COLOR]")
        ]
    elif menu_type == "studios":
        items = [
            ("FILMOVÁ STUDIA", get_url(action="list_stremio_catalogs", cat_type="movie", cat_group="studios"), Icons.MOVIE, "[COLOR orange]KOLEKCE: DISNEY, MARVEL, PIXAR, DC, LUCASFILM A DALŠÍ[/COLOR]"),
            ("SERIÁLOVÁ STUDIA", get_url(action="list_stremio_catalogs", cat_type="series", cat_group="studios"), Icons.TVSHOW, "[COLOR orange]KOLEKCE: DISNEY, MARVEL, PIXAR, DC, LUCASFILM A DALŠÍ[/COLOR]")
        ]
    elif menu_type == "vod":
        items = [
            ("FILMY Z VOD", get_url(action="list_stremio_catalogs", cat_type="movie", cat_group="vod"), Icons.MOVIE, "[COLOR orange]OBSAH Z NETFLIX, HBO MAX, APPLE TV+, AMAZON...[/COLOR]"),
            ("SERIÁLY Z VOD", get_url(action="list_stremio_catalogs", cat_type="series", cat_group="vod"), Icons.TVSHOW, "[COLOR orange]OBSAH Z NETFLIX, HBO MAX, APPLE TV+, AMAZON...[/COLOR]")
        ]
    elif menu_type == "search":
        items = [
            ("HLEDAT FILM", get_url(action="stremio_search_action", cat_type="movie"), Icons.SEARCH_MOVIE, "[COLOR orange]NATIVNÍ VYHLEDÁVÁNÍ FILMŮ V KATALOGU STREMIO[/COLOR]"),
            ("HLEDAT SERIÁL", get_url(action="stremio_search_action", cat_type="series"), Icons.SEARCH_TVSHOW, "[COLOR orange]NATIVNÍ VYHLEDÁVÁNÍ SERIÁLŮ V KATALOGU STREMIO[/COLOR]")
        ]

    for label, url, icon, plot in items:
        li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{label}")
        li.setArt({"icon": icon})
        li.getVideoInfoTag().setPlot(plot)

        # TOTO JE KLÍČ PROTI ZACYKLENÍ: Hledání musí běžet jako skript (isFolder=False)

        is_folder = False if menu_type == "search" else True
        if not is_folder:
            li.setProperty("IsPlayable", "false")

        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, isFolder=is_folder)

    xbmcplugin.setContent(plugin_instance.handle, "files")
    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)


def stremio_search_action(params, plugin_instance):

    """
    STREMIO BRIDGE :: SEARCH ACTION
    -- Skript, který vyvolá klávesnici a teprve po potvrzení otevře složku s výsledky.
    """

    cat_type = params.get("cat_type", "movie")
    cat_id = "search_movies" if cat_type == "movie" else "search_series"

    kb = xbmc.Keyboard("", f"[COLOR {Colors.ORANGE}]○  ZADEJTE HLEDANÝ NÁZEV  ○[/COLOR]")
    kb.doModal()

    # Pokud uživatel text potvrdí, přesměrujeme ho do složky s výsledky

    if kb.isConfirmed() and kb.getText().strip():
        query = kb.getText().strip()
        url = get_url(action="stremio_items", cat_id=cat_id, cat_type=cat_type, skip=0, query=query)
        xbmc.executebuiltin(f"Container.Update({url})")

    # Pokud uživatel zmáčkne ESC (Zrušit), skript prostě skončí (Kodi neudělá nic, klávesnice zmizí).

    return


def _get_stremio_manifest(plugin_instance, addon_url=None):
    addon_url = addon_url or plugin_instance.addon.getSettingString("stremio_manifest_url").strip()
    if not addon_url or "manifest.json" not in addon_url:
        log("STREMIO MANIFEST - Neplatná URL manifestu", xbmc.LOGWARNING)
        return None, addon_url

    cache_key = "stremio_manifest_" + hashlib.sha256(addon_url.encode("utf-8")).hexdigest()
    manifest = cache_manager.cache_get("STREMIO", cache_key)
    if not manifest:
        response = safe_get(plugin_instance.session, addon_url, timeout=12)
        if not response or response.status_code != 200:
            return None, addon_url
        try:
            manifest = response.json()
            cache_manager.cache_set("STREMIO", cache_key, manifest)
        except Exception as e:
            log(f"STREMIO MANIFEST - CHYBA JSON: {e}", xbmc.LOGERROR)
            return None, addon_url
    return manifest, addon_url


def list_stremio_genres(params, plugin_instance):
    cat_id = params.get("cat_id")
    cat_type = params.get("cat_type", "movie")
    manifest, addon_url = _get_stremio_manifest(plugin_instance)
    if not manifest:
        notify_error("ERROR Nelze načíst Stremio manifest", category="STREMIO")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
        return

    genres = []
    catalog_name = "Katalog"
    for catalog in manifest.get("catalogs", []):
        if catalog.get("id") == cat_id:
            catalog_name = catalog.get("name", catalog_name)
            genre_extra = next((extra for extra in (catalog.get("extra") or []) if extra.get("name") == "genre"), {})
            genres = genre_extra.get("options", []) or []
            break

    if not genres:
        notify_info("Tento katalog nemá dostupné žánry", category="STREMIO")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
        return

    for genre in genres:
        genre = str(genre)
        li = xbmcgui.ListItem(label=f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B]{genre.upper()}")
        li.setArt({"icon": Icons.MOVIE if cat_type == "movie" else Icons.TVSHOW})
        li.getVideoInfoTag().setPlot(f"[COLOR orange]{catalog_name} : {genre}[/COLOR]")
        url = get_url(action="stremio_items", cat_id=cat_id, cat_type=cat_type, genre=genre, skip=0, addon_url=addon_url)
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, isFolder=True)

    set_view_mode(plugin_instance.handle, plugin_instance.addon, "files", "movies_submenu")
    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)


def list_stremio_catalogs(params, plugin_instance):

    """
    STREMIO BRIDGE :: VOD MANIFEST
    -- Načte služby, studia a žebříčky z manifestu Stremio addonu.
    -- Manifest je nyní bezpečně cachován přes cache_manager!
    """

    cat_type_filter = params.get("cat_type", "movie")
    cat_group = params.get("cat_group", "vod")

    addon_url = plugin_instance.addon.getSettingString("stremio_manifest_url").strip()
    if not addon_url:
        addon_url = "https://katalog.streamstr.stream/eyJtb3ZpZXNfbmFtZSI6IsSMRVNLw50gREFCSU5HICA6OiAgRklMTVkiLCJzZXJpZXNfbmFtZSI6IsSMRVNLw50gREFCSU5HICA6OiAgU0VSScOBTFkiLCJzb3J0X2J5X3llYXIiOiJ0cnVlIiwic29ydF9vcmRlciI6Im1vdmllc19maXJzdCIsInByb3ZpZGVyX2RhdGEiOlsxLDIsNCw4LDExLDEzLDE4LDE5LDIxLDI0XSwiY3pkYWJpbmdfbW92aWVzX2VuYWJsZWQiOnRydWUsImN6ZGFiaW5nX3Nlcmllc19lbmFibGVkIjp0cnVlLCJhb21kYl9wb3N0ZXJzX2VuYWJsZWQiOmZhbHNlLCJtb3N0X3Zpc2l0ZWRfbW92aWVzX2VuYWJsZWQiOnRydWUsIm1vc3RfdmlzaXRlZF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwibW9zdF92aXNpdGVkX21vdmllc19uYW1lIjoixIxTRkQ6IE5lam5hdsWhdMSbdm92YW7Em2rFocOtIiwibW9zdF92aXNpdGVkX3Nlcmllc19uYW1lIjoixIxTRkQ6IE5lam5hdsWhdMSbdm92YW7Em2rFocOtIiwicG9wdWxhcl9tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwicG9wdWxhcl9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwidHJlbmRpbmdfbW92aWVzX2VuYWJsZWQiOnRydWUsInRyZW5kaW5nX3Nlcmllc19lbmFibGVkIjp0cnVlLCJzdHVkaW9fY29sbGVjdGlvbl9lbmFibGVkIjpmYWxzZSwibHVjYXNmaWxtX21vdmllc19lbmFibGVkIjp0cnVlLCJsdWNhc2ZpbG1fc2VyaWVzX2VuYWJsZWQiOnRydWUsIndhbHRfZGlzbmV5X21vdmllc19lbmFibGVkIjp0cnVlLCJ3YWx0X2Rpc25leV9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwicGl4YXJfbW92aWVzX2VuYWJsZWQiOnRydWUsInBpeGFyX3Nlcmllc19lbmFibGVkIjp0cnVlLCJwYXJhbW91bnRfbW92aWVzX2VuYWJsZWQiOnRydWUsInBhcmFtb3VudF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwiY29sdW1iaWFfbW92aWVzX2VuYWJsZWQiOnRydWUsImNvbHVtYmlhX3Nlcmllc19lbmFibGVkIjp0cnVlLCJ1bml2ZXJzYWxfbW92aWVzX2VuYWJsZWQiOnRydWUsInVuaXZlcnNhbF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwid2FybmVyX2Jyb3NfbW92aWVzX2VuYWJsZWQiOnRydWUsIndhcm5lcl9icm9zX3Nlcmllc19lbmFibGVkIjp0cnVlLCJtYXJ2ZWxfc3R1ZGlvc19tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwibWFydmVsX3N0dWRpb3Nfc2VyaWVzX2VuYWJsZWQiOnRydWUsImRyZWFtd29ya3NfbW92aWVzX2VuYWJsZWQiOnRydWUsImRyZWFtd29ya3Nfc2VyaWVzX2VuYWJsZWQiOnRydWUsImxlZ2VuZGFyeV9tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwibGVnZW5kYXJ5X3Nlcmllc19lbmFibGVkIjp0cnVlLCJkY19lbnRlcnRhaW5tZW50X21vdmllc19lbmFibGVkIjp0cnVlLCJkY19lbnRlcnRhaW5tZW50X3Nlcmllc19lbmFibGVkIjp0cnVlLCJzZWFyY2hfY2F0YWxvZ19lbmFibGVkIjp0cnVlLCJwb3B1bGFyX21vdmllc19uYW1lIjoiUE9QVUzDgVJOw40iLCJwb3B1bGFyX3Nlcmllc19uYW1lIjoiUE9QVUzDgVJOw40iLCJ0cmVuZGluZ19tb3ZpZXNfbmFtZSI6IlRSRU5EWSIsInRyZW5kaW5nX3Nlcmllc19uYW1lIjoiVFJFTkRZIiwic3R1ZGlvX2NvbGxlY3Rpb25fbmFtZSI6IlNUVURJQSIsImx1Y2FzZmlsbV9tb3ZpZXNfbmFtZSI6IkxVQ0FTRklMTSIsImx1Y2FzZmlsbV9zZXJpZXNfbmFtZSI6IkxVQ0FTRklMTSIsIndhbHRfZGlzbmV5X21vdmllc19uYW1lIjoiV0FMVCBESVNORVkgUElDVFVSRVMiLCJ3YWx0X2Rpc25leV9zZXJpZXNfbmFtZSI6IldBTFQgRElTTkVZIFBJQ1RVUkVTIiwicGl4YXJfbW92aWVzX25hbWUiOiJQSVhBUiIsInBpeGFyX3Nlcmllc19uYW1lIjoiUElYQVIiLCJwYXJhbW91bnRfbW92aWVzX25hbWUiOiJQQVJBTU9VTlQgUElDVFVSRVMiLCJwYXJhbW91bnRfc2VyaWVzX25hbWUiOiJQQVJBTU9VTlQgUElDVFVSRVMiLCJjb2x1bWJpYV9tb3ZpZXNfbmFtZSI6IkNPTFVNQklBIFBJQ1RVUkVTIiwiY29sdW1iaWFfc2VyaWVzX25hbWUiOiJDT0xVTUJJQSBQSUNUVVJFUyIsInVuaXZlcnNhbF9tb3ZpZXNfbmFtZSI6IlVOSVZFUlNBTCBQSUNUVVJFUyIsInVuaXZlcnNhbF9zZXJpZXNfbmFtZSI6IlVOSVZFUlNBTCBQSUNUVVJFUyIsIndhcm5lcl9icm9zX21vdmllc19uYW1lIjoiV0FSTkVSIEJST1MuIiwid2FybmVyX2Jyb3Nfc2VyaWVzX25hbWUiOiJXQVJORVIgQlJPUy4iLCJtYXJ2ZWxfc3R1ZGlvc19tb3ZpZXNfbmFtZSI6Ik1BUlZFTCBTVFVESU9TIiwibWFydmVsX3N0dWRpb3Nfc2VyaWVzX25hbWUiOiJNQVJWRUwgU1RVRElPUyIsImRyZWFtd29ya3NfbW92aWVzX25hbWUiOiJEUkVBTVdPUktTIEFOSU1BVElPTiIsImRyZWFtd29ya3Nfc2VyaWVzX25hbWUiOiJEUkVBTVdPUktTIEFOSU1BVElPTiIsImxlZ2VuZGFyeV9tb3ZpZXNfbmFtZSI6IkxFR0VOREFSWSBQSUNUVVJFUyIsImxlZ2VuZGFyeV9zZXJpZXNfbmFtZSI6IkxFR0VOREFSWSBQSUNUVVJFUyIsImRjX2VudGVydGFpbm1lbnRfbW92aWVzX25hbWUiOiJEQyBFTlRFUlRBSU5NRU5UIiwiZGNfZW50ZXJ0YWlubWVudF9zZXJpZXNfbmFtZSI6IkRDIEVOVEVSVEFJTk1FTlQiLCJzZWFyY2hfY2F0YWxvZ19uYW1lIjoiU0VBUkNIIE1BTklGRVNUIiwiY2F0YWxvZ19vcmRlciI6WyJtb3ZpZTpjemRhYmluZ19tb3ZpZXMiLCJzZXJpZXM6Y3pkYWJpbmdfc2VyaWVzIiwibW92aWU6cG9wdWxhcl9tb3ZpZXMiLCJtb3ZpZTp0cmVuZGluZ19tb3ZpZXMiLCJzZXJpZXM6cG9wdWxhcl9zZXJpZXMiLCJzZXJpZXM6dHJlbmRpbmdfc2VyaWVzIiwibW92aWU6bW9zdF92aXNpdGVkX21vdmllcyIsInNlcmllczptb3N0X3Zpc2l0ZWRfc2VyaWVzIiwibW92aWU6bHVjYXNmaWxtX21vdmllcyIsIm1vdmllOndhbHRfZGlzbmV5X21vdmllcyIsIm1vdmllOnBpeGFyX21vdmllcyIsIm1vdmllOnBhcmFtb3VudF9tb3ZpZXMiLCJtb3ZpZTpjb2x1bWJpYV9tb3ZpZXMiLCJtb3ZpZTp1bml2ZXJzYWxfbW92aWVzIiwibW92aWU6d2FybmVyX2Jyb3NfbW92aWVzIiwibW92aWU6bWFydmVsX3N0dWRpb3NfbW92aWVzIiwibW92aWU6ZHJlYW13b3Jrc19tb3ZpZXMiLCJtb3ZpZTpsZWdlbmRhcnlfbW92aWVzIiwibW92aWU6ZGNfZW50ZXJ0YWlubWVudF9tb3ZpZXMiLCJzZXJpZXM6bHVjYXNmaWxtX3NlcmllcyIsInNlcmllczp3YWx0X2Rpc25leV9zZXJpZXMiLCJzZXJpZXM6cGl4YXJfc2VyaWVzIiwic2VyaWVzOnBhcmFtb3VudF9zZXJpZXMiLCJzZXJpZXM6Y29sdW1iaWFfc2VyaWVzIiwic2VyaWVzOnVuaXZlcnNhbF9zZXJpZXMiLCJzZXJpZXM6d2FybmVyX2Jyb3Nfc2VyaWVzIiwic2VyaWVzOm1hcnZlbF9zdHVkaW9zX3NlcmllcyIsInNlcmllczpkcmVhbXdvcmtzX3NlcmllcyIsInNlcmllczpsZWdlbmRhcnlfc2VyaWVzIiwic2VyaWVzOmRjX2VudGVydGFpbm1lbnRfc2VyaWVzIiwibW92aWU6cHJvdmlkZXJfMV9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzJfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl80X21vdmllIiwibW92aWU6cHJvdmlkZXJfOF9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzExX21vdmllIiwibW92aWU6cHJvdmlkZXJfMTNfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl8xOF9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzE5X21vdmllIiwibW92aWU6cHJvdmlkZXJfMjFfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl8yNF9tb3ZpZSIsInNlcmllczpwcm92aWRlcl8xX3NlcmllcyIsInNlcmllczpwcm92aWRlcl8yX3NlcmllcyIsInNlcmllczpwcm92aWRlcl80X3NlcmllcyIsInNlcmllczpwcm92aWRlcl84X3NlcmllcyIsInNlcmllczpwcm92aWRlcl8xMV9zZXJpZXMiLCJzZXJpZXM6cHJvdmlkZXJfMTNfc2VyaWVzIiwic2VyaWVzOnByb3ZpZGVyXzE4X3NlcmllcyIsInNlcmllczpwcm92aWRlcl8xOV9zZXJpZXMiLCJzZXJpZXM6cHJvdmlkZXJfMjFfc2VyaWVzIiwic2VyaWVzOnByb3ZpZGVyXzI0X3NlcmllcyIsIm1vdmllOnNlYXJjaF9tb3ZpZXMiLCJzZXJpZXM6c2VhcmNoX3NlcmllcyJdfQ==/manifest.json"

    progress = xbmcgui.DialogProgress()
    progress.create(f"[B][COLOR {Colors.ORANGE}] ○  PLAY.ER  ::  STREMIO CATALOG  ○ [/COLOR][/B]", f"[B][COLOR {Colors.ORANGE}]► [/COLOR] NAČÍTÁM  [ FUCKING ]  STREMIO KATALOGY ...[/B]")

    try:
        manifest, addon_url = _get_stremio_manifest(plugin_instance, addon_url)
        if not manifest:
            notify_error("ERROR Nelze načíst Stremio manifest", category="STREMIO")
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
            return

        catalogs = manifest.get("catalogs", [])

        for cat in catalogs:
            c_id = str(cat.get("id", ""))
            c_type = cat.get("type", "movie")
            if c_type in ("series", "tv", "tvshows"):
                c_type = "tv"

            expected_type = "tv" if cat_type_filter in ("series", "tv", "tvshows") else "movie"
            if c_type != expected_type:
                continue

            is_dabing = c_id.startswith("czdabing")
            is_search = c_id.startswith("search")
            is_vod = c_id.startswith("provider_")
            is_csfd = c_id.startswith(("most_visited", "vod_starting"))
            is_imdb = c_id.startswith("imdb_popular")
            is_charts = c_id.startswith(("popular", "trending"))
            is_studio = c_id.startswith(("lucasfilm", "walt_disney", "pixar", "paramount", "columbia", "universal", "warner_bros", "marvel_studios", "dreamworks", "legendary", "dc_entertainment"))

            if cat_group == "vod" and not is_vod: continue
            if cat_group == "charts" and not is_charts: continue
            if cat_group == "csfd" and not is_csfd: continue
            if cat_group == "imdb" and not is_imdb: continue
            if cat_group == "studios" and not is_studio: continue
            if cat_group == "dabing" and not is_dabing: continue

            if is_dabing or is_search: continue

            c_name = cat.get("name", "NEZNÁMÝ KATALOG")
            icon = Icons.MOVIE if c_type == "movie" else Icons.TVSHOW

            label = f"[B][COLOR {Colors.ORANGE}]► [/COLOR][/B] {c_name.upper()}"

            li = xbmcgui.ListItem(label=label)
            li.setArt({"icon": icon})

            stremio_api_type = "series" if c_type == "tv" else "movie"

            if any(ex.get("name") == "genre" for ex in (cat.get("extra") or [])):
                genre_url = get_url(action="stremio_genres_menu", cat_id=c_id, cat_type=stremio_api_type)
                li.addContextMenuItems(_sf_cm_items([(f"[COLOR {Colors.ORANGE}]► FILTROVAT PODLE ŽÁNRU[/COLOR]", f"Container.Update({genre_url})")]))

            u = get_url(action="stremio_items", cat_id=c_id, cat_type=stremio_api_type, skip=0, addon_url=addon_url)
            xbmcplugin.addDirectoryItem(plugin_instance.handle, u, li, isFolder=True)

        set_view_mode(plugin_instance.handle, plugin_instance.addon, "files", "movies_submenu")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)

    except Exception as e:
        log(f"STREMIO - CHYBA NAČTENÍ KATALOGŮ : {e}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
    finally:
        progress.close()


def list_stremio_items(params, plugin_instance):

    """
    STREMIO BRIDGE :: ITEMS
    -- Otevírá konkrétní seznam filmů/seriálů a překládá je do TMDB.
    """

    cat_id = params.get("cat_id")
    cat_type = params.get("cat_type")
    skip = int(params.get("skip", 0))
    query = params.get("query", "")
    genre = params.get("genre", "")

    addon_url = params.get("addon_url")
    if not addon_url:
        addon_url = plugin_instance.addon.getSettingString("stremio_manifest_url").strip()
        if not addon_url:
            addon_url = "https://katalog.streamstr.stream/eyJtb3ZpZXNfbmFtZSI6IsSMRVNLw50gREFCSU5HICA6OiAgRklMTVkiLCJzZXJpZXNfbmFtZSI6IsSMRVNLw50gREFCSU5HICA6OiAgU0VSScOBTFkiLCJzb3J0X2J5X3llYXIiOiJ0cnVlIiwic29ydF9vcmRlciI6Im1vdmllc19maXJzdCIsInByb3ZpZGVyX2RhdGEiOlsxLDIsNCw4LDExLDEzLDE4LDE5LDIxLDI0XSwiY3pkYWJpbmdfbW92aWVzX2VuYWJsZWQiOnRydWUsImN6ZGFiaW5nX3Nlcmllc19lbmFibGVkIjp0cnVlLCJhb21kYl9wb3N0ZXJzX2VuYWJsZWQiOmZhbHNlLCJtb3N0X3Zpc2l0ZWRfbW92aWVzX2VuYWJsZWQiOnRydWUsIm1vc3RfdmlzaXRlZF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwibW9zdF92aXNpdGVkX21vdmllc19uYW1lIjoixIxTRkQ6IE5lam5hdsWhdMSbdm92YW7Em2rFocOtIiwibW9zdF92aXNpdGVkX3Nlcmllc19uYW1lIjoixIxTRkQ6IE5lam5hdsWhdMSbdm92YW7Em2rFocOtIiwicG9wdWxhcl9tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwicG9wdWxhcl9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwidHJlbmRpbmdfbW92aWVzX2VuYWJsZWQiOnRydWUsInRyZW5kaW5nX3Nlcmllc19lbmFibGVkIjp0cnVlLCJzdHVkaW9fY29sbGVjdGlvbl9lbmFibGVkIjpmYWxzZSwibHVjYXNmaWxtX21vdmllc19lbmFibGVkIjp0cnVlLCJsdWNhc2ZpbG1fc2VyaWVzX2VuYWJsZWQiOnRydWUsIndhbHRfZGlzbmV5X21vdmllc19lbmFibGVkIjp0cnVlLCJ3YWx0X2Rpc25leV9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwicGl4YXJfbW92aWVzX2VuYWJsZWQiOnRydWUsInBpeGFyX3Nlcmllc19lbmFibGVkIjp0cnVlLCJwYXJhbW91bnRfbW92aWVzX2VuYWJsZWQiOnRydWUsInBhcmFtb3VudF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwiY29sdW1iaWFfbW92aWVzX2VuYWJsZWQiOnRydWUsImNvbHVtYmlhX3Nlcmllc19lbmFibGVkIjp0cnVlLCJ1bml2ZXJzYWxfbW92aWVzX2VuYWJsZWQiOnRydWUsInVuaXZlcnNhbF9zZXJpZXNfZW5hYmxlZCI6dHJ1ZSwid2FybmVyX2Jyb3NfbW92aWVzX2VuYWJsZWQiOnRydWUsIndhcm5lcl9icm9zX3Nlcmllc19lbmFibGVkIjp0cnVlLCJtYXJ2ZWxfc3R1ZGlvc19tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwibWFydmVsX3N0dWRpb3Nfc2VyaWVzX2VuYWJsZWQiOnRydWUsImRyZWFtd29ya3NfbW92aWVzX2VuYWJsZWQiOnRydWUsImRyZWFtd29ya3Nfc2VyaWVzX2VuYWJsZWQiOnRydWUsImxlZ2VuZGFyeV9tb3ZpZXNfZW5hYmxlZCI6dHJ1ZSwibGVnZW5kYXJ5X3Nlcmllc19lbmFibGVkIjp0cnVlLCJkY19lbnRlcnRhaW5tZW50X21vdmllc19lbmFibGVkIjp0cnVlLCJkY19lbnRlcnRhaW5tZW50X3Nlcmllc19lbmFibGVkIjp0cnVlLCJzZWFyY2hfY2F0YWxvZ19lbmFibGVkIjp0cnVlLCJwb3B1bGFyX21vdmllc19uYW1lIjoiUE9QVUzDgVJOw40iLCJwb3B1bGFyX3Nlcmllc19uYW1lIjoiUE9QVUzDgVJOw40iLCJ0cmVuZGluZ19tb3ZpZXNfbmFtZSI6IlRSRU5EWSIsInRyZW5kaW5nX3Nlcmllc19uYW1lIjoiVFJFTkRZIiwic3R1ZGlvX2NvbGxlY3Rpb25fbmFtZSI6IlNUVURJQSIsImx1Y2FzZmlsbV9tb3ZpZXNfbmFtZSI6IkxVQ0FTRklMTSIsImx1Y2FzZmlsbV9zZXJpZXNfbmFtZSI6IkxVQ0FTRklMTSIsIndhbHRfZGlzbmV5X21vdmllc19uYW1lIjoiV0FMVCBESVNORVkgUElDVFVSRVMiLCJ3YWx0X2Rpc25leV9zZXJpZXNfbmFtZSI6IldBTFQgRElTTkVZIFBJQ1RVUkVTIiwicGl4YXJfbW92aWVzX25hbWUiOiJQSVhBUiIsInBpeGFyX3Nlcmllc19uYW1lIjoiUElYQVIiLCJwYXJhbW91bnRfbW92aWVzX25hbWUiOiJQQVJBTU9VTlQgUElDVFVSRVMiLCJwYXJhbW91bnRfc2VyaWVzX25hbWUiOiJQQVJBTU9VTlQgUElDVFVSRVMiLCJjb2x1bWJpYV9tb3ZpZXNfbmFtZSI6IkNPTFVNQklBIFBJQ1RVUkVTIiwiY29sdW1iaWFfc2VyaWVzX25hbWUiOiJDT0xVTUJJQSBQSUNUVVJFUyIsInVuaXZlcnNhbF9tb3ZpZXNfbmFtZSI6IlVOSVZFUlNBTCBQSUNUVVJFUyIsInVuaXZlcnNhbF9zZXJpZXNfbmFtZSI6IlVOSVZFUlNBTCBQSUNUVVJFUyIsIndhcm5lcl9icm9zX21vdmllc19uYW1lIjoiV0FSTkVSIEJST1MuIiwid2FybmVyX2Jyb3Nfc2VyaWVzX25hbWUiOiJXQVJORVIgQlJPUy4iLCJtYXJ2ZWxfc3R1ZGlvc19tb3ZpZXNfbmFtZSI6Ik1BUlZFTCBTVFVESU9TIiwibWFydmVsX3N0dWRpb3Nfc2VyaWVzX25hbWUiOiJNQVJWRUwgU1RVRElPUyIsImRyZWFtd29ya3NfbW92aWVzX25hbWUiOiJEUkVBTVdPUktTIEFOSU1BVElPTiIsImRyZWFtd29ya3Nfc2VyaWVzX25hbWUiOiJEUkVBTVdPUktTIEFOSU1BVElPTiIsImxlZ2VuZGFyeV9tb3ZpZXNfbmFtZSI6IkxFR0VOREFSWSBQSUNUVVJFUyIsImxlZ2VuZGFyeV9zZXJpZXNfbmFtZSI6IkxFR0VOREFSWSBQSUNUVVJFUyIsImRjX2VudGVydGFpbm1lbnRfbW92aWVzX25hbWUiOiJEQyBFTlRFUlRBSU5NRU5UIiwiZGNfZW50ZXJ0YWlubWVudF9zZXJpZXNfbmFtZSI6IkRDIEVOVEVSVEFJTk1FTlQiLCJzZWFyY2hfY2F0YWxvZ19uYW1lIjoiU0VBUkNIIE1BTklGRVNUIiwiY2F0YWxvZ19vcmRlciI6WyJtb3ZpZTpjemRhYmluZ19tb3ZpZXMiLCJzZXJpZXM6Y3pkYWJpbmdfc2VyaWVzIiwibW92aWU6cG9wdWxhcl9tb3ZpZXMiLCJtb3ZpZTp0cmVuZGluZ19tb3ZpZXMiLCJzZXJpZXM6cG9wdWxhcl9zZXJpZXMiLCJzZXJpZXM6dHJlbmRpbmdfc2VyaWVzIiwibW92aWU6bW9zdF92aXNpdGVkX21vdmllcyIsInNlcmllczptb3N0X3Zpc2l0ZWRfc2VyaWVzIiwibW92aWU6bHVjYXNmaWxtX21vdmllcyIsIm1vdmllOndhbHRfZGlzbmV5X21vdmllcyIsIm1vdmllOnBpeGFyX21vdmllcyIsIm1vdmllOnBhcmFtb3VudF9tb3ZpZXMiLCJtb3ZpZTpjb2x1bWJpYV9tb3ZpZXMiLCJtb3ZpZTp1bml2ZXJzYWxfbW92aWVzIiwibW92aWU6d2FybmVyX2Jyb3NfbW92aWVzIiwibW92aWU6bWFydmVsX3N0dWRpb3NfbW92aWVzIiwibW92aWU6ZHJlYW13b3Jrc19tb3ZpZXMiLCJtb3ZpZTpsZWdlbmRhcnlfbW92aWVzIiwibW92aWU6ZGNfZW50ZXJ0YWlubWVudF9tb3ZpZXMiLCJzZXJpZXM6bHVjYXNmaWxtX3NlcmllcyIsInNlcmllczp3YWx0X2Rpc25leV9zZXJpZXMiLCJzZXJpZXM6cGl4YXJfc2VyaWVzIiwic2VyaWVzOnBhcmFtb3VudF9zZXJpZXMiLCJzZXJpZXM6Y29sdW1iaWFfc2VyaWVzIiwic2VyaWVzOnVuaXZlcnNhbF9zZXJpZXMiLCJzZXJpZXM6d2FybmVyX2Jyb3Nfc2VyaWVzIiwic2VyaWVzOm1hcnZlbF9zdHVkaW9zX3NlcmllcyIsInNlcmllczpkcmVhbXdvcmtzX3NlcmllcyIsInNlcmllczpsZWdlbmRhcnlfc2VyaWVzIiwic2VyaWVzOmRjX2VudGVydGFpbm1lbnRfc2VyaWVzIiwibW92aWU6cHJvdmlkZXJfMV9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzJfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl80X21vdmllIiwibW92aWU6cHJvdmlkZXJfOF9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzExX21vdmllIiwibW92aWU6cHJvdmlkZXJfMTNfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl8xOF9tb3ZpZSIsIm1vdmllOnByb3ZpZGVyXzE5X21vdmllIiwibW92aWU6cHJvdmlkZXJfMjFfbW92aWUiLCJtb3ZpZTpwcm92aWRlcl8yNF9tb3ZpZSIsInNlcmllczpwcm92aWRlcl8xX3NlcmllcyIsInNlcmllczpwcm92aWRlcl8yX3NlcmllcyIsInNlcmllczpwcm92aWRlcl80X3NlcmllcyIsInNlcmllczpwcm92aWRlcl84X3NlcmllcyIsInNlcmllczpwcm92aWRlcl8xMV9zZXJpZXMiLCJzZXJpZXM6cHJvdmlkZXJfMTNfc2VyaWVzIiwic2VyaWVzOnByb3ZpZGVyXzE4X3NlcmllcyIsInNlcmllczpwcm92aWRlcl8xOV9zZXJpZXMiLCJzZXJpZXM6cHJvdmlkZXJfMjFfc2VyaWVzIiwic2VyaWVzOnByb3ZpZGVyXzI0X3NlcmllcyIsIm1vdmllOnNlYXJjaF9tb3ZpZXMiLCJzZXJpZXM6c2VhcmNoX3NlcmllcyJdfQ==/manifest.json"

    base_url = addon_url.replace("/manifest.json", "")

    extra_parts = []
    if query:
        extra_parts.append(f"search={quote(query, safe='')}")
    if genre:
        extra_parts.append(f"genre={quote(genre, safe='')}")
    if skip > 0:
        extra_parts.append(f"skip={skip}")

    if extra_parts:
        extra_string = "&".join(extra_parts)
        url = f"{base_url}/catalog/{cat_type}/{cat_id}/{extra_string}.json"
        cache_key = f"stremio_{cat_type}_{cat_id}_{extra_string}"
    else:
        url = f"{base_url}/catalog/{cat_type}/{cat_id}.json"
        cache_key = f"stremio_{cat_type}_{cat_id}_0"

    cache_scope = hashlib.sha256(addon_url.encode("utf-8")).hexdigest()
    cache_key = f"{cache_scope}:{cache_key}"

    cached_data = cache_manager.cache_get("STREMIO", cache_key)

    if cached_data:
        log(f"STREMIO ITEMS - NAČÍTÁM Z CACHE [ QUICK START ] : {cache_key}", xbmc.LOGINFO)
        resolved_items = cached_data.get("items", [])
        has_next = cached_data.get("has_next", False)
        next_skip = cached_data.get("next_skip", 0)
    else:
        log(f"STREMIO ITEMS - NAČÍTÁM Z WEB URL : {url}", xbmc.LOGINFO)

        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}] ○  PLAY.ER  ::  STREMIO CATALOG  ○ [/COLOR][/B]", f"[B][COLOR {Colors.ORANGE}]► [/COLOR] NAČÍTÁM  [ FUCKING ]  STREMIO POLOŽKY ...[/B]")

        try:
            resp = safe_get(plugin_instance.session, url, timeout=10)
            if not resp or resp.status_code != 200:
                notify_error("ERROR NELZE NAČÍST POLOŽKY", category="STREMIO")
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
                return

            data = resp.json()
            metas = data.get("metas", [])

            has_next = len(metas) > 0 and data.get("hasMore", len(metas) >= 50)
            next_skip = skip + len(metas)

            if not metas:
                notify_info("INFO ŽÁDNÉ DALŠÍ POLOŽKY NENALEZENY", category="STREMIO")
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
                return

            def _resolve_meta(meta):
                stremio_id = meta.get("id")
                title = meta.get("name")
                poster = meta.get("poster")
                year = meta.get("releaseInfo")
                plot = meta.get("description", "")

                tmdb_id = None
                media_type = "movie" if cat_type == "movie" else "tv"

                if str(stremio_id).startswith("tt"):
                    res = plugin_instance.tmdb_client._fetch(f"find/{stremio_id}", params={"external_source": "imdb_id"})
                    if res:
                        if cat_type == "movie" and res.get("movie_results"):
                            tmdb_id = res["movie_results"][0].get("id")
                        elif cat_type in ("series", "tv") and res.get("tv_results"):
                            tmdb_id = res["tv_results"][0].get("id")
                elif str(stremio_id).startswith("tmdb:"):
                    tmdb_id = str(stremio_id).split(":")[1]

                if not tmdb_id: return None

                try:
                    full_details = plugin_instance.tmdb_client.get_full_details(media_type, tmdb_id)
                    if full_details:
                        return plugin_instance.tmdb_client._build_metadata_props(full_details, media_type)
                except Exception: pass

                props = {
                    "tmdb_id": tmdb_id,
                    "media_type": media_type,
                    "title": title,
                    "original_title": title,
                    "year": str(year)[:4] if year else "",
                    "plot": plot,
                    "poster": poster,
                    "fanart": poster
                }
                return props

            resolved_items = []

            max_workers = get_threadpool(20)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for result in executor.map(_resolve_meta, metas):
                    if result: resolved_items.append(result)

            if resolved_items:
                cache_manager.cache_set("STREMIO", cache_key, {
                    "items": resolved_items,
                    "has_next": has_next,
                    "next_skip": next_skip
                })

        except Exception as e:
            log(f"STREMIO ITEMS - CHYBA NAČTENÍ POLOŽEK: {e}", xbmc.LOGERROR)
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
            return
        finally:
            progress.close()

    try:
        if not resolved_items:
            notify_info("INFO ŽÁDNÉ PLATNÉ POLOŽKY K ZOBRAZENÍ", category="STREMIO")
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
            return

        for props in resolved_items:
            m_type = props["media_type"]
            t_id = props["tmdb_id"]

            label = f"{props.get('title')} ({props.get('year')})" if props.get('year') else props.get('title')
            li = xbmcgui.ListItem(label=label.upper())
            plugin_instance.tmdb_client.fill_list_item(li, props, "movie" if m_type == "movie" else "tvshow")

            if m_type == "movie":
                u = get_url(action="find_sources", meta=json.dumps(props))
                is_folder = True
                li.setProperty("IsPlayable", "false")
            else:
                u = get_url(action="listing_tmdb_tv", tmdb_id=t_id, meta=json.dumps(props))
                is_folder = True

            ctx = _get_context_menu(
                'stremio_items',
                addon=plugin_instance.addon,
                title=props.get('title'),
                tmdb_id=t_id,
                media_type=m_type,
                year=props.get('year', ''),
                poster=props.get('poster', ''),
                plot=props.get('plot', ''),
                props=props
            )
            li.addContextMenuItems(_sf_cm_items(ctx))
            xbmcplugin.addDirectoryItem(plugin_instance.handle, u, li, is_folder)

        if has_next and not query:
            next_label = f"[B][COLOR {Colors.ORANGE}]| STRANA[/B] [ DALŠÍ ][B]►[/COLOR][/B]"
            li_next = xbmcgui.ListItem(label=next_label)
            li_next.setArt({"icon": Icons.NEXT_PAGE})
            u_next = get_url(action="stremio_items", cat_id=cat_id, cat_type=cat_type, skip=next_skip, query=query, genre=genre, addon_url=addon_url)
            xbmcplugin.addDirectoryItem(plugin_instance.handle, u_next, li_next, True)

        xbmcplugin.setContent(plugin_instance.handle, "movies" if cat_type == "movie" else "tvshows")
        set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies" if cat_type == "movie" else "tvshows", "movies")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)

    except Exception as e:
        log(f"STREMIO ITEMS :: CHYBA VYKRESLOVÁNÍ : {e}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)



# =========================  SERVER SHARE  ============================= #
# ---------------------------------------------------------------------- #



def validate_share_payload(payload):
    try:
        if not isinstance(payload, dict):
            return None
        title = payload.get('title')
        if not title or not isinstance(title, str):
            return None
        tmdb_id = payload.get('tmdb_id')
        if tmdb_id is not None:
            try:
                tmdb_id = str(int(tmdb_id)) if isinstance(tmdb_id, (int, float)) or str(payload.get('tmdb_id')).isdigit() else str(payload.get('tmdb_id'))
            except Exception:
                tmdb_id = str(payload.get('tmdb_id'))
        media_type = (payload.get('media_type') or 'movie')
        # FIX PRE-EMPTIVE AND FILTERS [SHARED EPISODES REFER TO THE SHOW]
        if media_type in ('episode', 'show'):
            media_type = 'tv'
            title = payload.get('tv_show_title') or title
        if media_type not in ('movie', 'tv'):
            return None
        poster = payload.get('poster') or ''
        plot = payload.get('plot') or ''
        year = payload.get('year') or ''
        return {
            'title': title.strip(),
            'tmdb_id': tmdb_id,
            'media_type': media_type,
            'poster': poster,
            'plot': plot,
            'year': year
        }
    except Exception as e:
        log(f"SHARE PAYLOAD VALIDATION - Error: {e}", xbmc.LOGERROR)
        return None


def handle_share_menu(params, plugin_instance):
    import requests, base64, json
    from resources.lib.telegram import get_device_id

    try:
        payload_b64 = params.get('payload')
        if not payload_b64:
            notify_error("ERROR Chybí payload pro sdílení", category="SHARING")
            return

        try:
            raw = base64.urlsafe_b64decode(payload_b64.encode('utf-8'))
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            notify_error("ERROR Neplatný payload sdílení", category="SHARING")
            return

        if not isinstance(payload, dict):
            notify_error('Neplatný payload sdílení.', category='SHARING')
            return

        # FIX PRE-EMPTIVE AND FILTERS [CORRECT SERIES TITLE FOR EPISODE SHARING]
        if payload.get('media_type') == 'episode' and not payload.get('tv_show_title'):
            if payload.get('tmdb_id') and plugin_instance.tmdb_client:
                details = plugin_instance.tmdb_client.get_full_details('tv', payload['tmdb_id']) or {}
                payload['tv_show_title'] = details.get('name', '')
            if not payload.get('tv_show_title'):
                notify_error('Nelze určit seriál pro sdílení této epizody.', category='SHARING')
                return

        validated = validate_share_payload(payload)
        if not validated:
            notify_error("ERROR Neplatný nebo neúplný payload", category="SHARING")
            return

        if not plugin_instance.addon.getSettingBool('enable_community_sharing'):
            notify_info("INFO Sdílení není povoleno v nastavení", category="SHARING")
            return

        validated['sender_id'] = get_device_id()
        validated['api_key'] = plugin_instance.addon.getSettingString("community_api_key").strip() or "plugin.video.player"

        API_URL = plugin_instance.addon.getSettingString("community_api_url").strip() or "https://xbmc.south-fork.uk/SERVER/addon-sharing.php"

        response = safe_post(API_URL, json=validated, timeout=10)

        if response is not None and response.status_code == 200 and response.json().get('status') == 'success':
            notify_ok("OK TITUL BYL NASDÍLEN PŘEZ SERVER", category="SHARING")
        else:
            notify_error("ERROR Chyba při odeslání na server", category="SHARING")

    except Exception as e:
        log(f"SHARE MENU - Chyba při sdílení: {e}", xbmc.LOGERROR)
        notify_error('ERROR CHYBA SERVERU PŘI SDÍLENÍ', category='SHARING')


def display_community_shares(params, plugin_instance, is_widget=False):

    import json, datetime

    # FIX PRE-EMPTIVE AND FILTERS [BROADCAST MANUAL FETCH AND ATOMIC HISTORY]
    from resources.lib import sharing_service
    from resources.lib.sharing_store import record_key

    if not is_widget and plugin_instance.addon.getSettingBool('enable_community_sharing'):
        if not sharing_service.force_check():
            notify_error('Server sdílení není dostupný. Zobrazuji uloženou historii.', category='SHARING')

    try:
        items = sharing_service.get_store().load_history()

        xbmcplugin.setContent(plugin_instance.handle, 'movies')

        from resources.lib.telegram import get_device_id

        my_device_id = get_device_id()

        filtered_items = [rec for rec in items if str(rec.get('sender_id')) != str(my_device_id)]

        if not filtered_items:
            if not is_widget:
                notify_info('INFO Historie sdílení je prázdná', category='SHARING')
                li = xbmcgui.ListItem("[I][COLOR gray]Zatím zde nejsou žádná sdílení serveru ...[/COLOR][/I]")
                li.setProperty("IsPlayable", "false")
                li.setArt({'icon': Icons.BROADCAST, 'fanart': plugin_instance.addon.getAddonInfo('fanart')})
                li.addContextMenuItems(_sf_cm_items([('[COLOR limegreen][ OBNOVIT SDÍLENÍ ][/COLOR]', 'Container.Refresh')]))
                xbmcplugin.addDirectoryItem(plugin_instance.handle, "", li, isFolder=False)
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
            return

        for rec in filtered_items:
            title = rec.get('title') or 'NEZNÁMÝ'
            year = rec.get('year') or ''
            media_type = rec.get('media_type', 'movie')
            tmdb_id = rec.get('tmdb_id')

            share_time = "NEDÁVNO"
            if rec.get('ts'):
                share_time = datetime.datetime.fromtimestamp(int(rec['ts'])).strftime('%d.%m - %H:%M')

            label = f"[COLOR {Colors.LIMEGREEN}][ {share_time} ][/COLOR]  {title}  ({year})"
            li = xbmcgui.ListItem(label=label)

            poster = rec.get('poster') or ''
            if poster:
                li.setArt({'thumb': poster, 'poster': poster, 'icon': poster})
            li.setArt({'fanart': plugin_instance.addon.getAddonInfo('fanart')})

            info = li.getVideoInfoTag()
            info.setTitle(title)
            info.setPlot(f"[B][COLOR {Colors.ORANGE}]SDÍLEL UŽIVATEL ID [/COLOR][ {rec.get('sender_id', 'NEZNÁMÝ UŽIVATEL')} ][/B]\n\n" + rec.get('plot', ''))

            context_menu = _get_context_menu(
                'community_shares',
                addon=plugin_instance.addon,
                share_key=record_key(rec),
                title=title,
                tmdb_id=tmdb_id,
                media_type=media_type,
                year=year,
                poster=poster,
                plot=rec.get('plot', ''),
                props={'title': title, 'tmdb_id': tmdb_id, 'media_type': media_type, 'year': year, 'poster': poster, 'plot': rec.get('plot', '')}
            )
            li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

            if tmdb_id and media_type == 'tv':
                url = get_url(action='listing_tmdb_tv', tmdb_id=tmdb_id, meta=json.dumps({'title': title}))
            else:
                url = get_url(action='search_tmdb', name=title, type=media_type)

            xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, isFolder=True)

        if not is_widget:
            set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "playback_history")

        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)

    except Exception as e:
        log(f"COMMUNITY SHARES - Error: {e}", xbmc.LOGERROR)
        notify_error('Nelze načíst historii sdílení.', category='SHARING')
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)



# FIX PRE-EMPTIVE AND FILTERS [REMOVE ONE LOCAL BROADCAST RECORD]
def remove_community_share(params, plugin_instance):
    from resources.lib.sharing_service import get_store
    try:
        if get_store().remove(params.get('share_key', '')):
            notify_ok('Položka odebrána z místní historie.', category='SHARING')
            xbmc.executebuiltin('Container.Refresh')
        else:
            notify_info('Položka již není v historii. Obnovte seznam.', category='SHARING')
    except Exception as exc:
        log(f'SHARING - Odebrání selhalo: {exc}', xbmc.LOGWARNING)
        notify_error('Položku nelze odebrat z historie.', category='SHARING')


# ===========================  TMDBHELPER BRIDGE  ============================ #
# ---------------------------------------------------------------------------- #



def _tmdbh_next_episode(show_details, history, tmdb_id):
    """Continue the most recent valid episode through the known season list."""
    from resources.lib.utils_tmdbhelper import normalise_episode_numbers
    seasons = {}
    for row in show_details.get("seasons", []) or []:
        try:
            season, count = normalise_episode_numbers(
                row.get("season_number"), row.get("episode_count"))
            if int(season) > 0:
                seasons[int(season)] = int(count)
        except (AttributeError, ValueError):
            continue
    for item in history:
        meta = item.get("meta", {}) if isinstance(item, dict) else {}
        if not isinstance(meta, dict):
            continue
        if str(meta.get("tmdb_id")) != tmdb_id or meta.get("media_type") != "episode":
            continue
        try:
            season, episode = map(int, normalise_episode_numbers(
                meta.get("season"), meta.get("episode")))
        except ValueError:
            continue
        if season not in seasons:
            continue
        if episode < seasons[season]:
            return season, episode + 1
        following = [number for number in seasons if number > season]
        return (min(following), 1) if following else None
    regular = [number for number in seasons if number > 0]
    return (min(regular), 1) if regular else None


def _select_library_source(sources, addon):
    """Respect library filters and keep STRM selection inside its resolver call."""
    from resources.lib.utils_settings import get_setting_bool, get_setting_str
    from resources.lib.utils_filter import clean_display_title

    autoplay = get_setting_bool(addon, 'library_autoplay_enable', True)
    method = get_setting_str(addon, 'library_source_method', 'INTELIGENTNÍ')
    intelligent = not autoplay or method != 'PRVNÍ DOSTUPNÝ'
    if get_setting_bool(addon, 'library_filters_header', True):
        ranked = FilterUtils(addon).apply_filters(
            sources, enable_setting_id='library_filters_header',
            include_setting_ids=['include_library'], exclude_setting_ids=['exclude_library'])
        # First available preserves provider/global ordering after exclusions.
        allowed = {id(source) for source in ranked}
        sources = ranked if intelligent else [source for source in sources if id(source) in allowed]
    if not sources:
        return None
    if autoplay:
        return sources[0]

    clean_titles = get_setting_bool(addon, 'filter_display_title_library', True)
    labels = []
    for source in sources:
        title = source.get('title', '')
        if clean_titles:
            title, _, _, _ = clean_display_title(
                title, explicit_tags=source.get('tags', []),
                extension=source.get('extension'), likes=source.get('likes', 0))
        details = ' | '.join(str(source[key]) for key in ('provider', 'size_str') if source.get(key))
        labels.append(f'{title}  [ {details} ]' if details else title)
    selected = xbmcgui.Dialog().select(addon.getLocalizedString(32810), labels)
    return sources[selected] if 0 <= selected < len(sources) else None


def tmdbh_bridge(params, plugin_instance):

    """
    TMDBHELPER :: SILENT SMART BRIDGE
    -- Dokonalé propojení TMDbH a play_er
    """


    import os
    import json
    import traceback

    import xbmc
    import xbmcvfs
    import xbmcgui
    import xbmcplugin

    from resources.lib.utils_logging import log
    from resources.lib.utils_notification import notify_error, notify_info, notify_ok
    from resources.lib.utils import store_meta_in_cache



    params = dict(params)
    tmdb_id = params.get('tmdb_id')
    media_type = params.get('media_type', 'movie')
    mode = params.get('mode', 'play')

    is_playback_request = mode in ('play', 'smart_play')
    library_request = str(params.get('library', '')).lower() == 'true'
    force_lang = str(params.get('lang') or '').lower()
    force_quality = str(params.get('quality') or '').lower()

    query = str(params.get('q') or params.get('query') or '').strip()

    try:
        if mode not in ('play', 'smart_play', 'search', 'suggest', 'text_search'):
            raise ValueError('Nepodporovaný režim TMDBHelper')
        if media_type not in ('movie', 'episode', 'tv', 'show'):
            raise ValueError('Nepodporovaný typ média TMDBHelper')
        if mode in ('suggest', 'text_search') and tmdb_id:
            raise ValueError('Textové vyhledávání nepřijímá TMDB ID')

        # ======================================================================
        # --- MODE SUGGEST :: RETURN QUICK SUGGESTIONS FOR SKIN INTEGRATION
        # ======================================================================

        if mode == 'suggest' and not tmdb_id:
            if not query:
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
                return

            providers = plugin_instance.provider_manager.get_providers_to_search()
            suggestions = []
            try:
                for p in providers:
                    try:
                        if hasattr(p, 'suggest'):
                            s = p.suggest(query)
                            if s:
                                suggestions.extend(s)
                    except Exception:
                        continue
                seen = set()
                out = []
                for s in suggestions:
                    if s not in seen:
                        seen.add(s)
                        out.append(s)
                suggestions = out
            except Exception as e:
                log(f"TMDBH BRIDGE - Suggest aggregate error: {e}", xbmc.LOGWARNING)

            if not suggestions:
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
                return

            addon_dir = xbmcvfs.translatePath(plugin_instance.addon.getAddonInfo('path'))
            icons_dir = os.path.join(addon_dir, "resources", "icons")
            poster_img = os.path.join(icons_dir, "POSTER--PLAYER--MAIN.webp")
            clearlogo_img = os.path.join(icons_dir, "CLEAR--PLAYER--PLAYER.webp")
            fanart_img = os.path.join(icons_dir, "FANART--DEVELOPMENT.webp")

            for i, phrase in enumerate(suggestions):
                label = phrase
                li = xbmcgui.ListItem(label=label)
                li.setProperty("IsPlayable", "false")
                li.setArt({
                    "poster": poster_img,
                    "icon": os.path.join(icons_dir, "FUSE--PREHRAJTO.webp"),
                    "thumb": os.path.join(icons_dir, "WIDE--PREHRAJTO.webp"),
                    "fanart": fanart_img,
                    "clearlogo": clearlogo_img
                })

                url = get_url(action="tmdbh_bridge", mode="text_search", q=phrase)
                xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, True)

            xbmcplugin.setContent(plugin_instance.handle, "movies")
            try:
                from resources.lib.ui_builder import set_view_mode
                set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "search_results")
            except Exception:
                pass

            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
            return

        # ======================================================================
        # --- MODE DIRECT :: TEXT SEARCH ( ARCTIC FUSE 3 INTEGRATION )
        # ======================================================================

        if (mode == 'text_search' or query) and not tmdb_id:
            log(f"TMDBH BRIDGE - DIRECT TEXT SEARCH | Dotaz : '{query}'", xbmc.LOGINFO)

            if not query:
                notify_info("INFO Prázdný vyhledávací dotaz.", category="SEARCH")
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
                return

            providers = plugin_instance.provider_manager.get_providers_to_search()
            sort_priority = str(plugin_instance.addon.getSetting("multi_provider_sort"))

            # ČISTÉ VOLÁNÍ: Žádný busydialog, žádný delay. Skin AF3 si počká sám.

            all_videos = _search_providers_parallel(query, providers, apply_filters=False, sort_priority=sort_priority)

            if not all_videos:
                notify_info("INFO Nic nenalezeno", category="SEARCH")
                xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
                return

            show_size = plugin_instance.addon.getSettingBool("show_size")
            show_duration = plugin_instance.addon.getSettingBool("show_duration_time")
            filter_enabled = plugin_instance.addon.getSettingBool("filter_display_title_search")

            addon_dir = xbmcvfs.translatePath(plugin_instance.addon.getAddonInfo('path'))
            icons_dir = os.path.join(addon_dir, "resources", "icons")

            poster_img = os.path.join(icons_dir, "POSTER--PLAYER--MAIN.webp")
            clearlogo_img = os.path.join(icons_dir, "CLEAR--PLAYER--PLAYER.webp")
            fanart_img = os.path.join(icons_dir, "FANART--DEVELOPMENT.webp")

            for i, video in enumerate(all_videos):
                prov = video.get("provider", "")
                is_ws = "webshare" in prov
                color = Colors.LIMEGREEN if is_ws else Colors.ORANGE

                size_tag = ""
                duration_tag = ""

                if show_size and video.get("size_str"):
                    raw_size = video.get("size_str")
                    try:
                        from resources.lib.utils import convert_size_to_bytes, convert_size
                        size_bytes = convert_size_to_bytes(raw_size)
                        normalized = convert_size(size_bytes) if size_bytes else raw_size
                    except Exception:
                        normalized = raw_size
                    size_tag = f'[LIGHT][COLOR {color}][{normalized}][/LIGHT][/COLOR] '

                if show_duration and video.get("duration_str") and video["duration_str"] != "0":
                    duration_tag = f'[LIGHT][COLOR gray][{video["duration_str"]}][/COLOR][/LIGHT] '

                if filter_enabled:
                    try:
                        from resources.lib.utils_filter import clean_display_title
                        cleaned_title, _, _, _ = clean_display_title(
                            video["title"],
                            explicit_tags=video.get("tags", []),
                            extension=video.get("extension"),
                            likes=video.get("likes", 0)
                        )
                        label = f'{size_tag}{duration_tag}{cleaned_title}'.strip()
                    except Exception:
                        label = f'{size_tag}{duration_tag}{video["title"]}'.strip()
                else:
                    label = f'{size_tag}{duration_tag}{video["title"]}'.strip()

                li = xbmcgui.ListItem(label=label)
                li.setProperty("IsPlayable", "true")

                wide_img = os.path.join(icons_dir, "WIDE--WEBSHARE.webp") if is_ws else os.path.join(icons_dir, "WIDE--PREHRAJTO.webp")
                icon_img = os.path.join(icons_dir, "FUSE--WEBSHARE.webp") if is_ws else os.path.join(icons_dir, "FUSE--PREHRAJTO.webp")

                li.setArt({
                    "poster": poster_img,
                    "icon": icon_img,
                    "thumb": wide_img,
                    "landscape": wide_img,
                    "fanart": fanart_img,
                    "clearlogo": clearlogo_img
                })

                final_meta = {"title": video["title"], "media_type": "movie"}
                final_meta['source_title'] = f"{prov.upper()} - {video['title']}"

                info_tag = li.getVideoInfoTag()
                info_tag.setTitle(label)
                info_tag.setUniqueIDs({'tmdb': f"stream_{i}"})

                context_menu = _get_context_menu(
                    'search_results',
                    addon=plugin_instance.addon,
                    title=final_meta.get("title", video["title"]),
                    tmdb_id="",
                    media_type="movie",
                    year="",
                    poster="",
                    plot="",
                    props=final_meta,
                    provider=video.get("provider"),
                    video_link=video.get("link")
                )
                li.addContextMenuItems(_sf_cm_items(context_menu), replaceItems=False)

                meta_key = store_meta_in_cache(final_meta)
                url = get_url(action="play", link=video["link"], provider=video.get("provider"), meta=meta_key)
                xbmcplugin.addDirectoryItem(plugin_instance.handle, url, li, False)

            xbmcplugin.setContent(plugin_instance.handle, "movies")

            try:
                from resources.lib.ui_builder import set_view_mode
                set_view_mode(plugin_instance.handle, plugin_instance.addon, "movies", "search_results")
            except Exception:
                pass

            if "arctic.fuse" in xbmc.getSkinDir() and not xbmc.getCondVisibility("Window.IsVisible(home)"):
                if not plugin_instance.addon.getSettingBool("enable_view_modes"):
                    xbmc.executebuiltin("Container.SetViewMode(507)")

            log("TMDBH BRIDGE - DIRECT TEXT SEARCH | Dokončeno zobrazení výsledků.", xbmc.LOGINFO)
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, cacheToDisc=False)
            return

        # ======================================================================
        # --- PŮVODNÍ KONTROLA TMDB ID PRO BĚŽNÉ MÓDY
        # ======================================================================

        from resources.lib.utils_tmdbhelper import normalise_tmdb_id
        tmdb_id = normalise_tmdb_id(tmdb_id)

        if media_type == 'episode':
            from resources.lib.utils_tmdbhelper import normalise_episode_numbers
            try:
                params['season'], params['episode'] = normalise_episode_numbers(
                    params.get('season'), params.get('episode'))
            except ValueError as exc:
                notify_error(f"ERROR {exc}", category="TMDB-HELP")
                if is_playback_request:
                    xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
                else:
                    xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
                return

        client = plugin_instance.tmdb_client
        props = {}
        search_title = ""
        search_query = ""
        show_details = None

        if mode == 'smart_play' and media_type in ['tv', 'show']:
            from resources.lib import cache_manager
            history = cache_manager.user_data_get("playback_history") or []
            show_details = client.get_full_details("tv", tmdb_id)
            if not show_details:
                raise ValueError(f"Nelze načíst detaily seriálu: {tmdb_id}")
            coordinates = _tmdbh_next_episode(show_details, history, tmdb_id)
            if coordinates is None:
                notify_info("INFO Není dostupná následující epizoda.", category="TMDB-HELP")
                xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
                return
            next_season, next_episode = coordinates

            media_type = 'episode'
            params['season'] = str(next_season)
            params['episode'] = str(next_episode)
            mode = 'play'

        if media_type == 'movie':
            details = client.get_full_details("movie", tmdb_id)
            if not details: raise ValueError(f"Nelze načíst detaily filmu: {tmdb_id}")
            props = client._build_metadata_props(details, "movie")
            props['media_type'] = 'movie'
            props['tmdb_id'] = tmdb_id
            search_title = props.get('title', '')
            search_query = f"{search_title} {props.get('year', '')}".strip()

        elif media_type == 'episode':
            season = params.get('season')
            episode = params.get('episode')

            if show_details is None:
                show_details = client.get_full_details("tv", tmdb_id)
            if not show_details:
                raise ValueError(f"Nelze načíst detaily seriálu: {tmdb_id}")
            ep_details = client._fetch(f"tv/{tmdb_id}/season/{season}/episode/{episode}", params={"append_to_response": "credits"})

            if not ep_details:
                raise ValueError(f"Nelze načíst detaily epizody: S{int(season):02d}E{int(episode):02d}")
            show_props = client._build_metadata_props(show_details, 'tv')
            ep_props = client._build_metadata_props(ep_details, 'episode') if ep_details else {}

            props = ep_props.copy()
            for key, value in show_props.items():
                if not props.get(key): props[key] = value

            tv_show_title = show_props.get('title') or (show_details.get('name', '') if show_details else 'Neznámý seriál')
            props.update({
                'media_type': 'episode',
                'tv_show_title': tv_show_title,
                'title': ep_details.get('name', f"Epizoda {episode}") if ep_details else f"Epizoda {episode}",
                'season': int(season),
                'episode': int(episode),
                'tmdb_id': tmdb_id
            })
            search_title = tv_show_title
            search_query = f"{search_title} S{int(season):02d}E{int(episode):02d}"

        elif media_type in ['tv', 'show']:
            details = client.get_full_details("tv", tmdb_id)
            if not details: raise ValueError(f"Nelze načíst detaily seriálu: {tmdb_id}")
            props = client._build_metadata_props(details, "tv")
            props['media_type'] = 'tv'
            props['tmdb_id'] = tmdb_id
            search_title = props.get('title', '')
            search_query = search_title.strip()

        if plugin_instance.addon.getSettingBool('trakt_prefer_czech_search'):
            lookup_type = 'tv' if media_type in ['episode', 'show'] else media_type
            loc_title = client.get_localized_title(lookup_type, tmdb_id, 'cs')
            if loc_title:
                search_title = loc_title
                if media_type == 'episode':
                    props['tv_show_title'] = loc_title
                    search_query = f"{loc_title} S{int(params.get('season')):02d}E{int(params.get('episode')):02d}"
                else:
                    props['title'] = loc_title
                    search_query = f"{loc_title} {props.get('year', '')}".strip()

        if mode == 'search':
            if media_type == 'episode':
                # FIX PRE-EMPTIVE AND FILTERS [TMDBHELPER SOURCE MARKER]
                # Značka omezuje úpravu Kodi playlistu na explicitní výběr TMDBH zdroje.
                props["_play_er_tmdbh_source_search"] = True
            meta_key = store_meta_in_cache(props)
            find_and_list_sources_multi({'meta': meta_key}, plugin_instance, tmdbh_search=True)
            return

        providers = plugin_instance.provider_manager.get_providers_to_search()
        sort_priority = str(plugin_instance.addon.getSetting("multi_provider_sort"))
        sources = _search_providers_parallel(search_query, providers, apply_filters=True, sort_priority=sort_priority)

        if not sources:
            notify_info(f"AUTO-PLAY Nenalezen žádný stream odpovídající filtrům.", category="TMDB-HELP")
            xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
            return

        selected_source = (_select_library_source(sources, plugin_instance.addon)
                           if library_request else sources[0])
        if selected_source is None:
            xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
            return

        if not library_request and (force_lang or force_quality):
            for s in sources:
                tags = s.get('tags', [])
                title_up = s.get('title', '').upper()

                has_lang = True
                if force_lang == 'cz':
                    has_lang = ('DAB' in tags or 'SK' in tags or 'DAB' in title_up or 'CZ ' in title_up)

                has_qual = True
                if force_quality == '1080p':
                    has_qual = ('1080P' in tags or '1080' in title_up)
                elif force_quality == '4k':
                    has_qual = ('4K' in tags or '2160' in title_up or 'UHD' in title_up)
                elif force_quality == '720p':
                    has_qual = ('720P' in tags or '720' in title_up)

                if has_lang and has_qual:
                    selected_source = s
                    break

        if not library_request or plugin_instance.addon.getSettingBool('library_autoplay_enable'):
            notify_ok(f"AUTO-PLAY {props.get('title')}", category="LIBRARY" if library_request else "TMDB-HELP", time=3000)

        win = xbmcgui.Window(10000)
        win.setProperty("play_er.tmdbh_autoplay", "true")

        try:
            resolve_video(
                selected_source["link"],
                selected_source.get("provider"),
                json.dumps(props),
                return_url_only=False,
                plugin_instance=plugin_instance
            )
        finally:
            win.clearProperty("play_er.tmdbh_autoplay")

    except Exception as e:
        log(f"TMDBH BRIDGE - Kritická chyba : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        message = f"ERROR {e}" if isinstance(e, ValueError) else "ERROR Selhalo přemostění z TMDB-HELPER."
        notify_error(message, category="TMDB-HELP")
        if is_playback_request: xbmcplugin.setResolvedUrl(plugin_instance.handle, False, xbmcgui.ListItem())
        else: xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, cacheToDisc=False)
