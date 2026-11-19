# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_menu.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 17.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import json
import base64

import xbmc
import xbmcgui
import xbmcaddon


from resources.lib.utils_logging import log
from resources.lib.utils import get_url

from resources.lib.utils_notification import (
    notify_error,
    notify_info
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)







def display_player_menu(params, menu_page='main', addon=None, session=None):

    # FIX PRE-EMPTIVE AND FILTERS [NORMALIZE MENU CONTEXT BEFORE BUILDING ACTIONS]
    addon = addon or xbmcaddon.Addon(id='plugin.video.play_er')
    params = dict(params or {})
    props = params.get('props') or '{}'
    try:
        meta_dict = dict(props) if isinstance(props, dict) else json.loads(props)
    except (TypeError, ValueError):
        meta_dict = {}
    if not isinstance(meta_dict, dict):
        meta_dict = {}
    # A fullscreen invocation has no focused library item. Use active metadata.
    if not any(params.get(k) or meta_dict.get(k) for k in ('tmdb_id', 'title')) and xbmc.Player().isPlayingVideo():
        try:
            current = json.loads(xbmcgui.Window(10000).getProperty('play_er.current_meta') or '{}')
            if isinstance(current, dict):
                meta_dict.update(current)
        except (TypeError, ValueError):
            pass
    context = params.get('context') or meta_dict.get('context') or xbmc.getInfoLabel('ListItem.Property(context)') or 'general'
    params['context'] = context
    tmdb_id = params.get('tmdb_id') or params.get('alt_tmdb') or meta_dict.get('tmdb_id') or xbmc.getInfoLabel('ListItem.Property(tmdb_id)') or xbmc.getInfoLabel('ListItem.UniqueID(tmdb)')
    raw_media = params.get('media_type') or params.get('alt_media') or meta_dict.get('media_type') or xbmc.getInfoLabel('ListItem.Property(mediatype)') or xbmc.getInfoLabel('ListItem.DBType')
    media_type = {'show': 'tv', 'tvshow': 'tv'}.get(raw_media, raw_media) or 'movie'
    title = params.get('title') or meta_dict.get('title') or xbmc.getInfoLabel('ListItem.Title') or ''
    year = params.get('year') or meta_dict.get('year') or xbmc.getInfoLabel('ListItem.Year') or ''
    poster = params.get('poster') or meta_dict.get('poster') or xbmc.getInfoLabel('ListItem.Art(poster)') or addon.getAddonInfo('icon')
    plot = params.get('plot') or meta_dict.get('plot') or xbmc.getInfoLabel('ListItem.Plot') or ''
    meta_dict.update(tmdb_id=tmdb_id, media_type=media_type, title=title, year=year, poster=poster, plot=plot)
    for key, label in (('season', 'ListItem.Season'), ('episode', 'ListItem.Episode'), ('tv_show_title', 'ListItem.TVShowTitle')):
        if meta_dict.get(key) in (None, ''):
            value = params.get(key)
            meta_dict[key] = xbmc.getInfoLabel(label) if value in (None, '') else value

    catalog_media_type = 'tv' if media_type in ('tv', 'season', 'episode') else 'movie'
    catalog_title = (meta_dict.get('tv_show_title') or title) if catalog_media_type == 'tv' else title

    b64_payload = ""
    if title and tmdb_id:
        share_payload = {
            'title': title,
            'tv_show_title': meta_dict.get('tv_show_title', ''),
            'tmdb_id': tmdb_id,
            'media_type': media_type or 'movie',
            'year': year,
            'poster': poster,
            'plot': plot
        }
        try:
            raw_payload = json.dumps(share_payload, ensure_ascii=False).encode('utf-8')
            b64_payload = base64.urlsafe_b64encode(raw_payload).decode('utf-8')
        except Exception as e:
            log(f"DIALOG MENU - Chyba sestavení Payloadu sdílení: {e}", xbmc.LOGWARNING)

    # 6. MENU ROUTING

    actions = []
    dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  GENERAL MENU   ○ [/COLOR][/B]'

    if menu_page == 'main' and not tmdb_id:
        menu_page = 'system'





    # ========================================================================= #
    #  MEDIA MENU
    # ========================================================================= #


    if menu_page == 'main':
        display_title = title.upper() if title else "NEZNÁMÝ TITUL"
        display_year = f" ({year})" if year else ""
        dialog_title = f'[B][COLOR {Colors.LIMEGREEN}] ○   PLAY.ER  [/COLOR][COLOR {Colors.ORANGE}] ||   {display_title} {display_year}   ○ [/COLOR][/B]'

        # actions.append({'label': f'[B][COLOR orange] ========= |   PLAY.ER MENU   | ========= [/COLOR][/B]', 'action': 'stay'})

        from resources.lib.utils import store_meta_in_cache
        meta_key = store_meta_in_cache(meta_dict)
        source_params = {'source_list': context} if context in ('watch_later', 'watchlist', 'favorites', 'rated') else {}

        if media_type in ['tv', 'show']:
            play_plugin_url = get_url(action='listing_tmdb_tv', tmdb_id=tmdb_id, meta=meta_key, **source_params)
        elif media_type == 'season':
            season_num = meta_dict.get('season')
            if season_num in (None, ''):
                season_num = 1
            play_plugin_url = get_url(action='tmdb_tv_season', tmdb_id=tmdb_id, season=season_num, meta=meta_key, **source_params)
        else:
            play_plugin_url = get_url(action='find_sources', meta=meta_key, **source_params)


        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] OTEVŘÍT TITUL', 'action': 'browse', 'plugin_url': play_plugin_url})

        if xbmc.Player().isPlayingVideo():
            actions.append({'label': f'[COLOR {Colors.YELLOW}]►  ZMĚNA KVALITY[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='show_stream_menu')})


        # actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.LIMEGREEN}] PŘEHRÁT : [/COLOR] POLOŽKU  /  HLEDAT ZDROJE', 'action': 'run_plugin', 'plugin_url': play_plugin_url})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.LIMEGREEN}] PŘEHRÁT : [/COLOR] TRAILER', 'action': 'run_plugin', 'plugin_url': get_url(action='play_trailer', tmdb_id=tmdb_id, media_type=catalog_media_type)})


        # --- KNIHOVNA & WATCH LATER

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        
        if context != 'watch_later':
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] WATCHLATER PŘIDAT', 'action': 'run_plugin', 'plugin_url': get_url(action='add_to_watch_later', meta=json.dumps(meta_dict))})
        else:
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] WATCHLATER [COLOR {Colors.RED}]ODEBRAT[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='remove_from_watch_later', tmdb_id=tmdb_id, media_type=media_type, **({'season': meta_dict.get('season'), 'episode': meta_dict.get('episode')} if media_type == 'episode' else {}))})

        if b64_payload and addon and addon.getSettingBool('enable_community_sharing'):
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] NASDÍLET TITUL OSTATNÍM', 'action': 'run_plugin', 'plugin_url': get_url(action='share_menu', payload=b64_payload)})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] PŘIDAT DO KNIHOVNY', 'action': 'run_plugin', 'plugin_url': get_url(action='library', tmdb_id=tmdb_id, media_type=catalog_media_type, title=catalog_title, year=year)})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] ODEBRAT STRM EXPORT', 'action': 'run_plugin', 'plugin_url': get_url(action='library_remove', tmdb_id=tmdb_id, media_type=catalog_media_type)})


        # --- AI & PODOBNOST

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORCHID}]► [/COLOR] AI - ZAJÍMAVOSTI', 'action': 'run_plugin', 'plugin_url': get_url(action='gemini_trivia', title=catalog_title, year=year, media_type=catalog_media_type)})
        actions.append({'label': f'[COLOR {Colors.ORCHID}]► [/COLOR] AI - PODOBNOST', 'action': 'browse', 'plugin_url': get_url(action='ai_similar', title=catalog_title, year=year, media_type=catalog_media_type)})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] TMDB - PODOBNÉ TITULY', 'action': 'browse', 'plugin_url': get_url(action='show_similar_results', tmdb_id=tmdb_id, media_type=catalog_media_type, title=catalog_title)})

        # actions.append({'label': f'[COLOR {Colors.YELLOW}]► [/COLOR] TMDB - HLEDAT PODOBNÉ TITULY', 'action': 'run_plugin', 'plugin_url': get_url(action='find_similar', tmdb_id=tmdb_id, media_type=media_type, title=title)})


        # --- TMDB LISTS

        actions.append({'label': (f'[B][COLOR {Colors.ORANGE}]TMDB • SERIÁL[/COLOR][/B]' if media_type in ('season', 'episode') else '[B][COLOR gray]--------------------------------------------------[/COLOR][/B]'), 'action': 'stay'})

        if context != 'watchlist':
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] WATCHLIST PŘIDAT', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=catalog_media_type)})
        else:
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] WATCHLIST [COLOR {Colors.RED}]ODEBRAT[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_remove_watchlist', tmdb_id=tmdb_id, media_type=catalog_media_type)})

        if context != 'favorites':
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] OBLÍBENÉ PŘIDAT', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=catalog_media_type)})
        else:
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] OBLÍBENÉ [COLOR {Colors.RED}]ODEBRAT[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_remove_favorite', tmdb_id=tmdb_id, media_type=catalog_media_type)})

        if context != 'rated':
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] HODNOCENÍ PŘIDAT', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=catalog_media_type)})
        else:
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] HODNOCENÍ [COLOR {Colors.RED}]ODEBRAT[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='tmdb_remove_rating', tmdb_id=tmdb_id, media_type=catalog_media_type)})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[B][COLOR {Colors.ORANGE}]►  SYSTÉMOVÉ MENU ADDONU[/COLOR][/B]', 'action': 'submenu', 'menu_page': 'system'})


        # --- DISABLED :: TRAKT LISTS

        # if trakt_id:
        #     trakt_mt = 'show' if media_type in ['tv', 'episode', 'season'] else 'movie'
        #     actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] TRAKT  :  PŘIDAT DO TRAKTLISTU', 'action': 'run_plugin', 'plugin_url': get_url(action='trakt_add_to_watchlist', media_type=trakt_mt, media_id=trakt_id)})
        #     actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] TRAKT  :  PŘIDAT DO OBLÍBENÝCH', 'action': 'run_plugin', 'plugin_url': get_url(action='trakt_add_to_favorites', media_type=trakt_mt, media_id=trakt_id)})
        #
        #     actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})
        #
        # if media_type in ['tv', 'show', 'episode', 'season']:
        #     actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] MANAGER SERIÁLŮ', 'action': 'run_plugin', 'plugin_url': get_url(action='series_detail', series_name=title)})
        #
        #     actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})


    # ========================================================================= #
    # SYSTEM MENU
    # ========================================================================= #


    elif menu_page == 'system':
        dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  SYSTÉMOVÉ MENU   ○ [/COLOR][/B]'

        # actions.append({'label': f'[B][COLOR orange] ========= |   MAIN MENU   | ========= [/COLOR][/B]', 'action': 'stay'})

        # actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] POKRAČOVAT VE SLEDOVÁNÍ', 'action': 'run_plugin', 'plugin_url': get_url(action='continue_trigger_main')})
        # actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] VYHLEDÁVAT NA SERVERECH', 'action': 'run_plugin', 'plugin_url': get_url(action='search_title')})

        # actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] NASTAVENÍ ADDONU', 'action': 'submenu', 'menu_page': 'settings'})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] NASTAVENÍ PROVIDERŮ', 'action': 'submenu', 'menu_page': 'providers_menu'})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] RE-FRESH ADDON SETTINGS', 'action': 'run_plugin', 'plugin_url': get_url(action='apply_settings_and_refresh')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] NÁSTROJE A DIAGNOSTIKA', 'action': 'submenu', 'menu_page': 'tools'})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SPRÁVA CACHE MEZIPAMĚTI', 'action': 'submenu', 'menu_page': 'cache'})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[B][COLOR {Colors.ORANGE}]► [/COLOR] NÁPOVĚDA ADDONU[/B]', 'action': 'run_plugin', 'plugin_url': get_url(action='show_help')})


    # ========================================================================= #
    # PROVIDERS MENU  ( Pomocné submenu pro router )
    # ========================================================================= #
    

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SDÍLENÉ TITULY', 'action': 'browse', 'plugin_url': get_url(action='sharing_history')})
        if xbmc.Player().isPlayingVideo():
            actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] PLAYBACK DASHBOARD', 'action': 'run_plugin', 'plugin_url': get_url(action='show_stream_menu')})

    elif menu_page == 'providers_menu':
        dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  PROVIDERS   ○ [/COLOR][/B]'
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] VÝBĚR ZDROJE', 'action': 'select_provider'})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] REGISTRACE ÚČTU', 'action': 'run_plugin', 'plugin_url': get_url(action='register_play_mail')})


    # ========================================================================= #
    # SETTINGS MENU
    # ========================================================================= #


    elif menu_page == 'settings':
        dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  NASTAVENÍ   ○ [/COLOR][/B]'

        is_filter_enabled = addon.getSettingBool("enable_filtering") if addon else False
        filter_label = f"[COLOR {Colors.ORANGE}]► [/COLOR] FILTR : [COLOR {Colors.LIMEGREEN}] ZAPNUTO [/COLOR]" if is_filter_enabled else f"[COLOR {Colors.ORANGE}]► [/COLOR] FILTR : [COLOR {Colors.RED}] VYPNUTO [/COLOR]"
        actions.append({'label': filter_label, 'action': 'toggle_filtering'})

        lang_mode = (addon.getSetting('filter_tmdb_language') or 'SOFT').upper()
        is_lang_filter_enabled = lang_mode != 'OFF'
        lang_filter_label = f'[COLOR {Colors.ORANGE}]► [/COLOR] TMDB FILTER : [COLOR {Colors.LIMEGREEN if is_lang_filter_enabled else Colors.RED}]{lang_mode}[/COLOR]'
        actions.append({'label': lang_filter_label, 'action': 'toggle_tmdb_lang_filter'})

        main_window = xbmcgui.Window(10000)
        is_movie_auto = main_window.getProperty("player.movie.autoplay.enabled") == "true"
        movie_auto_label = f"[COLOR {Colors.ORANGE}]► [/COLOR] AUTOLIST FILM : [COLOR {Colors.LIMEGREEN}] ZAPNUTO [/COLOR]" if is_movie_auto else f"[COLOR {Colors.ORANGE}]► [/COLOR] AUTOLIST FILM : [COLOR {Colors.RED}] VYPNUTO [/COLOR]"
        actions.append({'label': movie_auto_label, 'action': 'run_plugin', 'plugin_url': get_url(action='toggle_movie_autoplay')})

        is_series_auto = main_window.getProperty("player.series.autoplay.enabled") == "true"
        series_auto_label = f"[COLOR {Colors.ORANGE}]► [/COLOR] AUTOLIST TV : [COLOR {Colors.LIMEGREEN}] ZAPNUTO [/COLOR]" if is_series_auto else f"[COLOR {Colors.ORANGE}]► [/COLOR] AUTOLIST TV : [COLOR {Colors.RED}] VYPNUTO [/COLOR]"
        actions.append({'label': series_auto_label, 'action': 'run_plugin', 'plugin_url': get_url(action='toggle_series_autoplay')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [B][/COLOR] HLAVNÍ NASTAVENÍ[/B]', 'action': 'open_settings'})
        actions.append({'label': f'[COLOR {Colors.LIMEGREEN}]► [B] RE-FRESH ADDONU A SLUŽEB[/COLOR][/B]', 'action': 'run_plugin', 'plugin_url': get_url(action='apply_settings_and_refresh')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})


    # ========================================================================= #
    # TOOLS MENU
    # ========================================================================= #


    elif menu_page == 'tools':
        dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  NÁSTROJE   ○ [/COLOR][/B]'

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SYSTEM METRIC', 'action': 'run_plugin', 'plugin_url': get_url(action='show_metrics')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] ADDON DEBUG LOG', 'action': 'run_plugin', 'plugin_url': get_url(action='show_addon_log')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SPEEDTEST', 'action': 'run_plugin', 'plugin_url': get_url(action='diagnose_speed')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SHELL LAUNCHER', 'action': 'run_plugin', 'plugin_url': get_url(action='shell_launcher_menu')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] TELEGRAM ZÁLOHA', 'action': 'run_plugin', 'plugin_url': get_url(action='backup_settings')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] TELEGRAM REPORT', 'action': 'run_plugin', 'plugin_url': get_url(action='send_accounts')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})


    # ========================================================================= #
    # CACHE MENU
    # ========================================================================= #


    elif menu_page == 'cache':
        dialog_title = f'[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  |  SPRÁVA CACHE   ○ [/COLOR][/B]'

        actions.append({'label': f'[COLOR {Colors.ORANGE}]►  INFORMACE O CACHE[/COLOR]', 'action': 'run_plugin', 'plugin_url': get_url(action='show_metrics')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] VYMAZAT IN-MEMORY  [ RAM ]', 'action': 'run_plugin', 'plugin_url': get_url(action='clear_ram_cache')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SMAZAT CACHE ČSFD', 'action': 'run_plugin', 'plugin_url': get_url(action='clear_csfd_cache')})
        actions.append({'label': f'[COLOR {Colors.ORANGE}]► [/COLOR] SMAZAT CACHE SLEDOVANÉ', 'action': 'run_plugin', 'plugin_url': get_url(action='clear_most_watched_cache')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})

        actions.append({'label': f'[COLOR {Colors.RED}]► [B] SMAZAT VŠECHNY CACHE[/COLOR][/B]', 'action': 'run_plugin', 'plugin_url': get_url(action='clear_cache')})
        actions.append({'label': f'[COLOR {Colors.RED}]► [B] SMAZAT DATABÁZI[/COLOR][/B]', 'action': 'run_plugin', 'plugin_url': get_url(action='reset_database')})

        actions.append({'label': f'[B][COLOR gray]--------------------------------------------------[/COLOR][/B]', 'action': 'stay'})


    # ========================================================================= #
    # BACK BUTTON & XML DIALOG EXECUTION
    # ========================================================================= #





    if menu_page != 'main' and (menu_page != 'system' or tmdb_id):
        actions.append({'label': f'◄ [B][COLOR {Colors.ORANGE}] [   ZPĚT   ][/COLOR][/B]', 'action': 'back'})

    if not actions:
        notify_info(f"INFO NEJSOU DOSTUPNÉ ŽÁDNÉ AKCE", category="DIALOG", time=3000)
        return None

    # --- Získání cesty doplňku pro správné načtení XML souboru
    
    addon_instance = xbmcaddon.Addon(id="plugin.video.play_er")
    addon_path = addon_instance.getAddonInfo('path')

    try:
        from resources.lib.dialog_menu_xml import PlayErDialogMenuXML
    except ImportError:
        log("DIALOG MENU - Nepodařilo se naimportovat PlayErDialogMenuXML", xbmc.LOGERROR)
        notify_error("ERROR NAČTENÍ XML ROZHRANÍ MENU", category="DIALOG", time=3000)
        return None

    positions = params.get('_menu_positions')
    if not isinstance(positions, dict):
        positions = {}

    # --- Inicializace okna

    xml_dialog = PlayErDialogMenuXML(
        "script-play_er-dialog_menu.xml",
        addon_path,
        "Default",
        "1080i",
        actions=actions,
        dialog_title=dialog_title,
        meta_dict=meta_dict,
        poster=poster,
        selected_index=positions.get(menu_page, 0)
    )

    # --- Zobrazení okna (blokuje běh scriptu dokud se okno nezavře)

    xml_dialog.doModal()

    # --- Načtení výběru uživatele

    choice = xml_dialog.selected_choice

    # --- Uvolnění z paměti po zavření

    del xml_dialog

    if choice == -1:
        return {'action': 'back', 'menu_page': menu_page}

    if not 0 <= choice < len(actions):
        return {'action': 'back'}
    positions[menu_page] = choice
    selected_action = actions[choice]

    # --- Header a oddělovače nemají akci, jen znovu otevřou menu na stejné pozici

    if selected_action.get('action') == 'stay':
        return display_player_menu(params, menu_page=menu_page, addon=addon, session=session)

    # --- ZDE POUZE VRACÍME VÝSLEDEK, LOGIKA ZPRACOVÁNÍ JE VE VOLAJÍCÍ FUNKCI V PLUGIN.PY

    if selected_action.get('action') == 'submenu':
        selected_action = dict(selected_action, parent_page=menu_page)
    return selected_action


# FIX PRE-EMPTIVE AND FILTERS [ITERATIVE DIALOG NAVIGATION AND ACTION DISPATCH]
def run_player_menu(params, addon, session, select_provider, toggle_filtering, toggle_language):
    params = dict(params or {})
    params['_menu_positions'] = {}
    page = params.get('menu_page', 'main')
    history = []
    while True:
        selected = display_player_menu(params, menu_page=page, addon=addon, session=session)
        if not selected:
            return
        action = selected.get('action')
        if action == 'submenu':
            history.append(selected.get('parent_page', page))
            page = selected['menu_page']
        elif action in ('back', 'stay'):
            if not history:
                return
            page = history.pop()
        elif action == 'toggle_filtering':
            toggle_filtering()
        elif action == 'toggle_tmdb_lang_filter':
            toggle_language()
        elif action == 'select_provider':
            select_provider()
        elif action == 'open_settings':
            addon.openSettings()
        elif action == 'browse':
            xbmc.executebuiltin(f"ActivateWindow(videos,{selected['plugin_url']},return)")
            return
        elif action == 'run_plugin':
            xbmc.executebuiltin(f"RunPlugin({selected['plugin_url']})")
            return
        else:
            return
