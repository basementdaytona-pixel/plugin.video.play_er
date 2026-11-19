# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: ui_builder.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import json
import traceback

import xbmc
import xbmcgui
import xbmcplugin

from resources.lib import cache_manager
from resources.lib.utils_logging import log
from resources.lib.utils_theme import Colors, Icons
from resources.lib.utils import convert_size_to_bytes, get_url
from resources.lib.utils_notification import notify_error, notify_info





def create_series_menu(plugin_instance):

    """
    SERIES MANAGER :: MAIN MENU
    -- Zobrazí hlavní menu pro SERIES MANAGER.
    """

    try:
        listitem_search = xbmcgui.ListItem(
            label=f"[B][COLOR {Colors.ORANGE}][ ○ VYHLEDAT SERIÁL ○ ][/COLOR][/B]"
        )
        listitem_search.setArt({"icon": Icons.SEARCH_TVSHOW})
        xbmcplugin.addDirectoryItem(
            plugin_instance.handle,
            get_url(action="series_search"),
            listitem_search,
            False
        )

        series_list = plugin_instance.series_manager.get_all_series()

        if series_list:
            series_list.sort(key=lambda x: x.get("name", "").lower())

            for series in series_list:
                series_name = series.get("name")
                if not series_name:
                    continue
                local_data = plugin_instance.series_manager.load_series_data(series_name)
                tmdb_id = local_data.get("tmdb_id") if local_data else None

                props = {}
                if tmdb_id and plugin_instance.tmdb_client:
                    try:
                        show_details = plugin_instance.tmdb_client.get_full_details("tv", tmdb_id)
                        if show_details:
                            props = plugin_instance.tmdb_client._build_metadata_props(show_details, "tv")
                    except Exception:
                        pass

                if not props.get("title"):
                    props["title"] = series_name
                if not props.get("tmdb_id"):
                    props["tmdb_id"] = tmdb_id
                props["media_type"] = "tv"

                listitem = xbmcgui.ListItem(label=props["title"])

                if plugin_instance.tmdb_client:
                    plugin_instance.tmdb_client.fill_list_item(listitem, props, "tvshow")
                else:
                    listitem.setArt({"icon": Icons.TVSHOW})

                url_delete = get_url(action="series_delete", series_name=series_name)
                url_refresh = get_url(action="series_refresh", series_name=series_name)

                try:
                    play_item = (
                        f"[B][COLOR {Colors.LIMEGREEN}] [  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]",
                        f"RunPlugin({get_url(action='show_player_menu', title=series_name, provider='series', link='')})"
                    )
                except Exception:
                    play_item = None

                context_menu = [
                    (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT SERIÁL[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({url_delete})"),
                    (f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL ◄[/COLOR]", f"RunPlugin({get_url(action='search_title', name=series_name)})"),
                    (f"[COLOR {Colors.ORANGE}]► AKTUALIZOVAT OBSAH ◄[/COLOR]", f"RunPlugin({url_refresh})")
                ]
                if play_item:
                    context_menu.append(play_item)

                context_menu.append((f"[B][COLOR {Colors.LIMEGREEN}] [ MENU NASTAVENÍ ] [/COLOR][/B]", "Addon.OpenSettings(plugin.video.play_er)"))
                listitem.addContextMenuItems(_sf_cm_items(context_menu))

                url_detail = get_url(action="series_detail", series_name=series_name)
                xbmcplugin.addDirectoryItem(plugin_instance.handle, url_detail, listitem, True)

        set_view_mode(plugin_instance.handle, plugin_instance.addon, "tvshows", "tvshows")

    except Exception as e:
        log(f"| PLAY.ER :: MANAGER - Chyba při vytváření menu TV-MANAGER : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        notify_error("SERIES-MENU Chyba při vytváření menu", "MANAGER")
    finally:
        xbmcplugin.endOfDirectory(plugin_instance.handle)


def create_seasons_menu(series_name, plugin_instance):

    """
    SERIES MANAGER :: SEASONS MENU
    -- Zobrazí seznam sérií pro vybraný seriál.
    """

    series_data = plugin_instance.series_manager.load_series_data(series_name)
    if not series_data:
        notify_info("SEASON-MENU Data pro sezóny nenalezena", "MANAGER")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
        return

    tmdb_id = series_data.get("tmdb_id")
    show_props = {}
    tmdb_seasons_map = {}

    if tmdb_id and plugin_instance.tmdb_client:
        try:
            show_details = plugin_instance.tmdb_client.get_full_details("tv", tmdb_id)
            if show_details:
                show_props = plugin_instance.tmdb_client._build_metadata_props(show_details, "tv")
                if "seasons" in show_details:
                    for s in show_details["seasons"]:
                        tmdb_seasons_map[str(s.get("season_number"))] = s
        except Exception as e:
            log(f"SEASON MENU - Chyba TMDB sync: {e}", xbmc.LOGWARNING)

    listitem_refresh = xbmcgui.ListItem(label=f"[COLOR {Colors.ORANGE}][ ○ AKTUALIZOVAT ○ ][/COLOR]")
    listitem_refresh.setArt({"icon": Icons.SEARCH})
    xbmcplugin.addDirectoryItem(
        plugin_instance.handle,
        get_url(action="series_refresh", series_name=series_name),
        listitem_refresh,
        True
    )

    for season_num in sorted(series_data["seasons"].keys(), key=int):
        season_name = f"{season_num}. SEZÓNA"
        tmdb_season = tmdb_seasons_map.get(str(season_num), {})

        poster_url = ""
        if tmdb_season.get("poster_path"):
            poster_url = f"https://image.tmdb.org/t/p/w500{tmdb_season['poster_path']}"
        if not poster_url:
            poster_url = show_props.get("poster", "")

        fanart_url = show_props.get("fanart", "")
        local_ep_count = len(series_data["seasons"][season_num])

        plot = tmdb_season.get("overview") or show_props.get("plot", "")
        if not plot:
            plot = f"Počet uložených epizod: {local_ep_count}"

        label = f"Sezóna {season_num} [COLOR {Colors.GRAY}]({local_ep_count} ep.)[/COLOR]"
        listitem = xbmcgui.ListItem(label=label)

        props = {
            "tmdb_id": tmdb_id,
            "media_type": "season",
            "title": f"Sezóna {season_num}",
            "tv_show_title": series_name,
            "season": int(season_num),
            "plot": plot,
            "premiered": tmdb_season.get("air_date"),
            "year": (tmdb_season.get("air_date") or "")[:4],
            "poster": poster_url,
            "fanart": fanart_url,
            "thumb": poster_url
        }

        if plugin_instance.tmdb_client:
            plugin_instance.tmdb_client.fill_list_item(listitem, props, "season")
        else:
            listitem.setArt({"icon": Icons.FOLDER})

        url_delete = get_url(action="season_delete", series_name=series_name, season=season_num)

        try:
            play_item = (
                f"[B][COLOR {Colors.LIMEGREEN}] [  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]",
                f"RunPlugin({get_url(action='show_player_menu', title=season_name, provider='series', link='')})"
            )
        except Exception:
            play_item = None

        context_menu = [
            (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT SEZÓNU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({url_delete})")
        ]
        if play_item:
            context_menu.append(play_item)

        context_menu.append((f"[B][COLOR {Colors.LIMEGREEN}] [ MENU NASTAVENÍ ] [/COLOR][/B]", "Addon.OpenSettings(plugin.video.play_er)"))
        listitem.addContextMenuItems(_sf_cm_items(context_menu))

        url_season = get_url(action="series_episodes", series_name=series_name, season=season_num)
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url_season, listitem, True)

    set_view_mode(plugin_instance.handle, plugin_instance.addon, "seasons", "seasons")
    xbmcplugin.endOfDirectory(plugin_instance.handle)


def create_episodes_menu(series_name, season_num, plugin_instance):

    """
    SERIES MANAGER :: EPISODES MENU
    -- Zobrazí seznam epizod pro vybranou sezónu.
    """

    series_data = plugin_instance.series_manager.load_series_data(series_name)
    if not series_data or str(season_num) not in series_data["seasons"]:
        notify_info("EPISODE-MENU Data pro epizody nenalezena", "MANAGER")
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
        return

    season_num = str(season_num)
    season = series_data["seasons"][season_num]
    tmdb_id = series_data.get("tmdb_id")

    poster_url = None
    fanart_url = None

    if tmdb_id and plugin_instance.tmdb_client:
        try:
            show_details = cache_manager.cache_get("TMDB", f"tv_{tmdb_id}")
            if show_details:
                if show_details.get("poster_path"):
                    poster_url = f"https://image.tmdb.org/t/p/w500{show_details['poster_path']}"
                if show_details.get("backdrop_path"):
                    fanart_url = f"https://image.tmdb.org/t/p/w1280{show_details['backdrop_path']}"
        except Exception:
            pass

    for episode_num in sorted(season.keys(), key=int):
        episode = season[episode_num]
        is_watched = plugin_instance.series_manager.is_episode_watched(series_name, season_num, episode_num)

        episode_label = (
            f"[COLOR {Colors.LIMEGREEN}]EPIZODA {episode_num}[/COLOR]"
            if is_watched
            else f"EPIZODA {episode_num}"
        )

        size = episode.get("size", "")
        provider = episode.get("provider", "")
        size_tag = ""

        try:
            size_nonzero = bool(size and convert_size_to_bytes(size) > 0)
        except Exception:
            size_nonzero = bool(size and size not in ("0", "0 MB", "0.00 GB", "0 B"))

        if size_nonzero:
            prov_color = Colors.LIMEGREEN if "webshare" in str(provider).lower() else Colors.ORANGE
            size_tag = f"[B][COLOR {prov_color}][{size}][/COLOR][/B] "

        raw_name = episode.get("name", "")
        for ext in ['.mkv', '.mp4', '.avi', '.MKV', '.MP4', '.AVI']:
            if raw_name.endswith(ext):
                raw_name = raw_name[:-len(ext)]
                break

        clean_name = raw_name.replace("_", " ").replace(".", " ").replace("-", " ").replace("+", " ")
        clean_name = " ".join(clean_name.split())

        episode_name = f"{episode_label} [COLOR {Colors.ORANGE}]:[/COLOR] {size_tag}{clean_name}"
        if episode.get("quality") and episode.get("quality") != "unknown":
            episode_name += f" [COLOR {Colors.GRAY}]({episode['quality']})[/COLOR]"

        listitem = xbmcgui.ListItem(label=episode_name)
        listitem.setProperty("IsPlayable", "true")

        episode_props = {}
        if tmdb_id and plugin_instance.tmdb_client:
            cache_key = f"tv_{tmdb_id}_s{season_num}_e{episode_num}"
            cached_ep = cache_manager.cache_get("TMDB", cache_key)
            if cached_ep:
                episode_props = plugin_instance.tmdb_client._build_metadata_props(cached_ep, 'episode')

        if not episode_props.get('title'):
            episode_props['title'] = clean_name
        if not episode_props.get('tmdb_id'):
            episode_props['tmdb_id'] = tmdb_id
        if not episode_props.get('tv_show_title'):
            episode_props['tv_show_title'] = series_name
        if not episode_props.get('season'):
            episode_props['season'] = season_num
        if not episode_props.get('episode'):
            episode_props['episode'] = episode_num
        if not episode_props.get('poster') and poster_url:
            episode_props['poster'] = poster_url
        if not episode_props.get('fanart') and fanart_url:
            episode_props['fanart'] = fanart_url

        if plugin_instance.tmdb_client:
            plugin_instance.tmdb_client.fill_list_item(listitem, episode_props, 'episode')
        else:
            listitem.setArt({"icon": Icons.VIDEO})

        meta = {
            "title": clean_name,
            "tv_show_title": series_name,
            "season": season_num,
            "episode": episode_num,
            "media_type": "episode",
            "tmdb_id": tmdb_id
        }
        if poster_url:
            meta["poster"] = poster_url
        if fanart_url:
            meta["fanart"] = fanart_url

        # --- DEFINICE URL PRO KONTEXTOVÉ AKCE (OPRAVA NAE/UNBOUND ERRORŮ) ---

        url_search = get_url(action="search_title", name=clean_name)
        url_watch = get_url(action="episode_mark_watched", series_name=series_name, season=season_num, episode=episode_num)
        url_unwatch = get_url(action="episode_mark_unwatched", series_name=series_name, season=season_num, episode=episode_num)
        url_select = get_url(action="select_episode_stream", series_name=series_name, season=season_num, episode=episode_num)
        url_del = get_url(action="episode_delete", series_name=series_name, season=season_num, episode=episode_num)

        context_menu = [
            (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.LIMEGREEN}]OZNAČIT ZHLÉDNUTO[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({url_watch})"),
            (f"[COLOR {Colors.ORANGE}]► OZNAČ NEZHLÉDNUTO ◄[/COLOR]", f"RunPlugin({url_unwatch})"),
            (f"[COLOR {Colors.ORANGE}]► VYBRAT JINÝ ZDROJ ◄[/COLOR]", f"RunPlugin({url_select})"),
            (f"[COLOR {Colors.ORANGE}]► [/COLOR][COLOR {Colors.RED}]ODEBRAT EPIZODU[/COLOR][COLOR {Colors.ORANGE}] ◄[/COLOR]", f"RunPlugin({url_del})"),
            (f"[COLOR {Colors.ORANGE}]► VYHLEDAT TITUL ◄[/COLOR]", f"RunPlugin({url_search})")
        ]

        try:
            play_item = (
                f"[B][COLOR {Colors.LIMEGREEN}][  ○  PLAY.ER  MENU  ○  ] [/COLOR][/B]",
                f"RunPlugin({get_url(action='show_player_menu', title=clean_name, provider=provider, link=episode.get('ident',''))})"
            )
        except Exception:
            play_item = None

        if play_item:
            context_menu.append(play_item)

        context_menu.append((f"[B][COLOR {Colors.LIMEGREEN}] [ MENU NASTAVENÍ ] [/COLOR][/B]", "Addon.OpenSettings(plugin.video.play_er)"))
        listitem.addContextMenuItems(_sf_cm_items(context_menu))

        play_params = {
            "action": "play",
            "link": episode["ident"],
            "meta": json.dumps(meta, ensure_ascii=False)
        }
        if episode.get("provider"):
            play_params["provider"] = episode["provider"]
            if episode["provider"].lower() == "webshare":
                play_params["provider"] = "webshare.cz"
            elif episode["provider"].lower() == "provider_prehrajto":
                play_params["provider"] = "prehraj.to"

        url_play = get_url(**play_params)
        xbmcplugin.addDirectoryItem(plugin_instance.handle, url_play, listitem, False)

    set_view_mode(plugin_instance.handle, plugin_instance.addon, "episodes", "episodes")
    xbmcplugin.endOfDirectory(plugin_instance.handle)


def set_view_mode(handle, addon, content_type, view_type_key):

    """
    SET :: VIEW MODE
    -- Nastaví režim zobrazení (View Mode) na základě aktuálního skinu.
    -- Odemknuto pro plnou podporu Arctic Fuse 3 (AF3) a Estuary.
    -- VŽDY korektně nastavuje setContent(), i když je změna pohledů vypnuta.
    """

    if handle is None or handle < 0:
        return

    # 1. content_type nastavujeme VŽDY, aby Kodi správně formátovalo metadata pro skiny a widgety

    try:
        xbmcplugin.setContent(handle, content_type)
    except Exception:
        pass

    if not addon.getSettingBool("enable_view_modes"):
        return

    # --- Ochrana proti pádům Kodi u widgetů na Home screenu

    if xbmc.getCondVisibility("Window.IsVisible(home)"):
        return

    current_skin = xbmc.getSkinDir()

    default_ids = {
        "list": 50, "poster": 51, "iconwall": 52, "shift": 53, "infowall": 54, "widelist": 55, "wall": 500, "banner": 57, "fanart": 502, "gallery": 503,
    }
    ah2_ids = {
        "list": 50, "widelist": 55, "poster": 51, "shift": 53, "infowall": 54, "wall": 500, "iconwall": 52, "banner": 58, "fanart": 502, "gallery": 503,
    }
    estuary_mod_ids = {
        "list": 50, "poster": 51, "iconwall": 52, "shift": 53, "infowall": 54, "widelist": 55, "wall": 500, "banner": 57, "fanart": 502, "gallery": 503,
    }

    fuse_ids = {
        "list": 506,           # View_506_Basic_List
        "poster": 507,         # View_507_Media_List
        "infowall": 508,       # View_508_Expanded_List
        "widelist": 509,       # View_509_Flixart_List
        "shift": 549,          # View_549_Flixart_List
        "wall": 512,           # View_512_Poster_Wall
        "iconwall": 510,       # View_510_Square_Wall
        "banner": 501,         # View_501_Landscape_Row
        "fanart": 511,         # View_511_Landscape_Wall
        "gallery": 502,        # View_502_Poster_Row
    }

    if "arctic.horizon.2" in current_skin:
        view_modes = ah2_ids
    elif "arctic.fuse" in current_skin:
        view_modes = fuse_ids
    elif "estuary.mod" in current_skin:
        view_modes = estuary_mod_ids
    else:
        view_modes = default_ids

    view_mode_labels_to_keys = {
        "Seznam": "list", "Nízký seznam": "list", "Základní seznam": "list",
        "Řádek na šířku": "list", "Štítky": "list", "Podnabídka": "list",
        "Široký seznam": "widelist", "Flixart": "widelist",
        "Banner": "banner", "Velký banner": "banner",
        "Plakát": "poster", "Velký seznam plakátů": "poster", "Seznam médií": "poster",
        "Informační seznam plakátů": "poster",
        "Zeď plakátů": "wall",
        "Dlaždice": "iconwall", "Vesla čtvercová zeď": "iconwall",
        "Fanart": "fanart", "Velká zeď na šířku": "fanart",
        "InfoWall": "infowall", "Zeď s informacemi o médiích": "infowall", "Rozšířený seznam": "infowall",
        "Základní informace o médiích": "infowall", "Seznam informací o médiích": "infowall",
        "Seznam skladeb s informacemi": "infowall",
        "Shift": "shift", "Posun": "shift",
        "Galerie": "gallery", "Velký čtvercový řádek": "gallery",
    }

    setting_id_map = {
        "main_menu": "view_mode_main_menu",
        "movies": "view_mode_movies",
        "movies_submenu": "view_mode_movies_submenu",
        "tvshows": "view_mode_tvshows",
        "tvshows_submenu": "view_mode_tvshows_submenu",
        "seasons": "view_mode_seasons",
        "episodes": "view_mode_episodes",
        "most_watched": "view_mode_most_watched",
        "history": "view_mode_playback_history",
        "playback_history": "view_mode_playback_history",
        "search": "view_mode_search",
        "search_results": "view_mode_search",
        "sources": "view_mode_search",
        "search_history": "view_mode_search_history",
        "csfd_tips": "view_mode_csfd_tips",
        "new_episodes": "view_mode_episodes",
        "csfd_charts": "view_mode_csfd_tips"
    }

    setting_key = setting_id_map.get(view_type_key)
    if not setting_key:
        return

    view_label = addon.getSettingString(setting_key)
    view_mode_key = view_mode_labels_to_keys.get(view_label, "list")

    if view_mode_key in view_modes:
        target_id = view_modes[view_mode_key]
        xbmc.executebuiltin(f"Container.SetViewMode({target_id})")
