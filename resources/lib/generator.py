# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: generator.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import json
import hashlib
import traceback
import threading


from typing import Dict, List, Optional, Any, Generator
from dataclasses import dataclass, asdict
from contextlib import contextmanager


import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin


from resources.lib.utils_settings import get_setting_int_with_bounds
from resources.lib.utils_filter import FilterUtils
from resources.lib.utils_logging import log
from resources.lib import cache_manager
from resources.lib.utils_notification import notify_info, notify_error
from resources.lib.utils_theme import Colors
from resources.lib.stream_state import attach_subtitles, publish_active_streams
from resources.lib.playback_identity import publish_fallback, set_view_identity
from resources.lib.source_order import order_sources
from resources.lib.preemptive_scope import source_scope


def _remember_playlist_item(url, meta, meta_id, trakt_id, source_link, provider=None, view_identity=None):
    """Retain per-URL metadata if Kodi omits custom properties on direct playlist URLs."""
    try:
        url_key = hashlib.sha256(str(url).split("|", 1)[0].encode("utf-8")).hexdigest()
        win = xbmcgui.Window(10000)
        try:
            # Preserve the existing property name for queue consumers.
            records = json.loads(win.getProperty("play_er.episode_queue_metadata") or "{}")
        except Exception:
            records = {}
        if not isinstance(records, dict):
            records = {}
        records[url_key] = {
            "meta": dict(meta or {}),
            "meta_id": str(meta_id or ""),
            "trakt_id": str(trakt_id or ""),
            "media_type": str((meta or {}).get("media_type") or "episode"),
            "link": str(source_link or ""),
            "provider": str(provider or ""),
            "view_id": view_identity[0] if view_identity else "",
            "view_binding": view_identity[1] if view_identity else "",
            "owner": win.getProperty("play_er.monitor_owner")
        }
        while len(records) > 25:
            records.pop(next(iter(records)))
        win.setProperty("play_er.episode_queue_metadata", json.dumps(records, ensure_ascii=False))
    except Exception as e:
        log(f"FIX PRE-EMPTIVE AND FILTERS - Nelze uložit metadata položky fronty: {e}", xbmc.LOGWARNING)



@contextmanager
def tmdb_error_handler(operation: str) -> Generator[None, None, None]:
    try:
        yield
    except Exception as e:
        log(f"TMDB {operation} - Chyba: {e}", xbmc.LOGWARNING)


def validate_tmdb_id(tmdb_id: Any) -> Optional[int]:
    if not tmdb_id:
        return None
    try:
        tmdb_id_int = int(tmdb_id)
        if 0 < tmdb_id_int < 10000000:
            return tmdb_id_int
        return None
    except (ValueError, TypeError):
        return None


@dataclass
class EpisodeMetadata:
    media_type: str = "episode"
    title: str = ""
    plot: str = ""
    rating: float = 0.0
    premiered: str = ""
    tv_show_title: str = ""
    season: int = 0
    episode: int = 0
    poster: str = ""
    fanart: str = ""
    thumb: str = ""
    cast_full: List[Dict[str, Any]] = None
    source_title: str = ""
    tmdb_id: Optional[int] = None

    def __post_init__(self):
        if self.cast_full is None:
            self.cast_full = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _apply_autolist_filters(videos, addon):
    original_count = len(videos)
    is_filter_enabled = addon.getSetting("enable_autolist_filters") == "true"
    filter_status_msg = f"[B][COLOR {Colors.LIMEGREEN}]ZAPNUTO[/COLOR][/B]" if is_filter_enabled else f"[B][COLOR {Colors.RED}]VYPNUTO[/COLOR][/B]"

    filtered_videos = FilterUtils(addon).apply_filters(
        videos,
        enable_setting_id="enable_autolist_filters",
        invert_enable_logic=False,
        include_setting_ids=["include_autolist"],
        exclude_setting_ids=["exclude_autolist"]
    )
    filtered_count = original_count - len(filtered_videos)
    log(f"AUTOLIST [MOVIE FILTER] - Původní: {original_count}, po filtru: {len(filtered_videos)} (Odebráno: {filtered_count})", xbmc.LOGINFO)
    notify_info(f"MOVIE : {filter_status_msg} ODEBRÁNO : [B][COLOR {Colors.RED}]{filtered_count}[/COLOR][/B] Z {original_count} ZDROJŮ", category="SYSTEM", time=3000)
    return filtered_videos


def _apply_autolist_filters_ser(videos, addon):
    original_count = len(videos)
    is_filter_enabled = addon.getSetting("enable_autolist_filters_ser") == "true"
    filter_status_msg = f"[B][COLOR {Colors.LIMEGREEN}]ZAPNUTO[/COLOR][/B]" if is_filter_enabled else f"[B][COLOR {Colors.RED}]VYPNUTO[/COLOR][/B]"

    filtered_videos = FilterUtils(addon).apply_filters(
        videos,
        enable_setting_id="enable_autolist_filters_ser",
        invert_enable_logic=False,
        include_setting_ids=["include_autolist_ser"],
        exclude_setting_ids=["exclude_autolist_ser"]
    )
    filtered_count = original_count - len(filtered_videos)
    log(f"AUTOLIST [SERIES FILTER] - Původní: {original_count}, po filtru: {len(filtered_videos)} (Odebráno: {filtered_count})", xbmc.LOGINFO)
    notify_info(f"SERIES : {filter_status_msg} ODEBRÁNO : [B][COLOR {Colors.RED}]{filtered_count}[/COLOR][/B] Z {original_count} ZDROJŮ", category="SYSTEM", time=3000)
    return filtered_videos


def _apply_continue_filters(videos, addon):
    original_count = len(videos)
    is_filter_enabled = addon.getSetting("enable_continue_filters") == "true"
    filter_status_msg = f"[B][COLOR {Colors.LIMEGREEN}]ZAPNUTO[/COLOR][/B]" if is_filter_enabled else f"[B][COLOR {Colors.RED}]VYPNUTO[/COLOR][/B]"

    filtered_videos = FilterUtils(addon).apply_filters(
        videos,
        enable_setting_id="enable_continue_filters",
        invert_enable_logic=False,
        include_setting_ids=["include_continue"],
        exclude_setting_ids=["exclude_continue"]
    )
    filtered_count = original_count - len(filtered_videos)
    log(f"CONTINUE [DEDICATED FILTER] - Původní: {original_count}, po filtru: {len(filtered_videos)} (Odebráno: {filtered_count})", xbmc.LOGINFO)
    notify_info(f"CONTINUE : {filter_status_msg} [ ODEBRÁNO [B][COLOR {Colors.RED}]{filtered_count}[/COLOR][/B] z {original_count} zdrojů ]", category="SYSTEM", time=3000)
    return filtered_videos


# FIX PRE-EMPTIVE AND FILTERS [CACHED CONTINUE FILTERS]
def _apply_continue_source_filters(videos, addon):
    """Apply global provider filters and the dedicated Continue rules to cached sources."""
    global_filtered = FilterUtils(addon).apply_filters(
        videos,
        enable_setting_id="enable_filtering",
        invert_enable_logic=False,
        include_setting_ids=["filter_global"],
        exclude_setting_ids=["exclude_global"]
    )
    return _apply_continue_filters(global_filtered, addon)


# FIX PRE-EMPTIVE AND FILTERS [SHARED CONTINUE SOURCE SEARCH]
def _search_continue_sources(query, addon, plugin_instance, tmdb_id, season, episode):
    """Search or consume pre-emptive sources, applying the same Continue filters either way."""
    from resources.lib import actions
    import time

    try:
        cache_key = f"preemptive_{tmdb_id}_S{int(season):02d}E{int(episode):02d}"
        cached = cache_manager.cache_get("PREEMPTIVE_SOURCES", cache_key)
        if (isinstance(cached, dict)
                and 0 <= time.time() - cached.get("timestamp", 0) < 1800
                and cached.get("source_scope") == source_scope(addon, plugin_instance.provider_manager)
                and cached.get("query") == query
                and isinstance(cached.get("results"), list)):
            sources = order_sources(cached.get("results") or [], str(addon.getSetting("multi_provider_sort")))
            log(f"CONTINUE - Používám pre-emptive cache: {len(sources)} zdrojů", xbmc.LOGINFO)
            return _apply_continue_source_filters(sources, addon)
    except Exception as e:
        log(f"FIX PRE-EMPTIVE AND FILTERS - Cache Continue nedostupná, hledám znovu: {e}", xbmc.LOGWARNING)

    providers = plugin_instance.provider_manager.get_providers_to_search()
    sort_priority = str(addon.getSetting("multi_provider_sort"))
    sources = actions._search_providers_parallel(
        query, providers, apply_filters=True, sort_priority=sort_priority
    )
    return _apply_continue_filters(sources, addon)


# FIX PRE-EMPTIVE AND FILTERS [PLAYLIST QUEUE INSPECTION]
def _get_video_playlist_snapshot():
    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
    position = playlist.getposition()
    request = json.dumps({
        "jsonrpc": "2.0",
        "method": "Playlist.GetItems",
        "params": {
            "playlistid": 1,
            "properties": ["customproperties", "episode", "season", "showtitle", "uniqueid", "title"]
        },
        "id": "play_er_episode_queue"
    })
    response = json.loads(xbmc.executeJSONRPC(request) or "{}")
    if response.get("error"):
        raise RuntimeError(response["error"])
    items = response.get("result", {}).get("items", [])
    return playlist, position, items


def _playlist_item_properties(item):
    properties = item.get("customproperties", {}) if isinstance(item, dict) else {}
    if isinstance(properties, list):
        properties = {
            str(entry.get("key", "")): entry.get("value", "")
            for entry in properties if isinstance(entry, dict)
        }
    return properties if isinstance(properties, dict) else {}


def _managed_future_episode_items(meta, items, position):
    tmdb_id = str(meta.get("tmdb_id", ""))
    managed = []
    for item in items[max(0, position + 1):]:
        properties = _playlist_item_properties(item)
        item_tmdb_id = properties.get("play_er.tmdb_id")
        if (
            str(properties.get("play_er.queue_managed", "")).lower() != "true"
            or str(item_tmdb_id or "") != tmdb_id
        ):
            continue
        try:
            managed.append({
                "season": int(properties.get("play_er.season", item.get("season"))),
                "episode": int(properties.get("play_er.episode", item.get("episode"))),
                "title": item.get("title", "")
            })
        except (TypeError, ValueError):
            continue
    return managed


def _next_episode_coordinates(tmdb_id, season, episode, tmdb_client):
    season = int(season)
    episode = int(episode)
    if season < 1:
        return 1, 1
    try:
        season_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season}")
        episode_count = len(season_data.get("episodes", [])) if season_data else 0
        if episode_count and episode >= episode_count:
            next_season = season + 1
            next_season_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{next_season}")
            if not next_season_data or not next_season_data.get("episodes"):
                return None
            return next_season, 1
    except Exception:
        pass
    return season, episode + 1


def is_next_episode_queued(meta, tmdb_client):
    """Return true only when the immediate Kodi playlist item is the expected managed episode."""
    try:
        tmdb_id = str(meta.get("tmdb_id", ""))
        expected = _next_episode_coordinates(
            tmdb_id, meta.get("season", 0), meta.get("episode", 0), tmdb_client
        )
        if not expected:
            return False
        _, position, items = _get_video_playlist_snapshot()
        if position < 0 or position + 1 >= len(items):
            return False
        item = items[position + 1]
        properties = _playlist_item_properties(item)
        return (
            str(properties.get("play_er.queue_managed", "")).lower() == "true"
            and str(properties.get("play_er.tmdb_id", "")) == tmdb_id
            and int(properties.get("play_er.season", -1)) == expected[0]
            and int(properties.get("play_er.episode", -1)) == expected[1]
        )
    except Exception as e:
        log(f"FIX PRE-EMPTIVE AND FILTERS - Nelze ověřit další epizodu v playlistu: {e}", xbmc.LOGDEBUG)
        return False


# FIX PRE-EMPTIVE AND FILTERS [FINITE EPISODE SESSION]
def get_episode_queue_remaining(meta):
    """Remaining successors in this session; None means no session limit yet."""
    value = (meta or {}).get('_play_er_queue_remaining')
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def get_preemptive_episode_target(meta, tmdb_client):
    """Choose the first episode beyond the managed playlist queue for pre-emptive search."""
    remaining = get_episode_queue_remaining(meta)
    if remaining == 0:
        return None
    try:
        _, position, items = _get_video_playlist_snapshot()
        future = _managed_future_episode_items(meta, items, position)
        if remaining is not None and len(future) >= remaining:
            return None
        base = future[-1] if future else meta
        return _next_episode_coordinates(
            meta.get("tmdb_id"), base.get("season", 0), base.get("episode", 0), tmdb_client
        )
    except Exception as e:
        log(f"FIX PRE-EMPTIVE AND FILTERS - Nelze zjistit cíl pre-emptive hledání: {e}", xbmc.LOGDEBUG)
        return _next_episode_coordinates(
            meta.get("tmdb_id"), meta.get("season", 0), meta.get("episode", 0), tmdb_client
        )


def _playlist_playback_is_current(player, allowed_urls, allowed_sources):
    """Only extend a queue while one of its items is still playing."""
    try:
        if not player.isPlayingVideo():
            return False
    except Exception:
        return False
    try:
        if str(player.getPlayingFile()).split('|', 1)[0] in allowed_urls:
            return True
    except Exception:
        pass
    try:
        item = player.getPlayingItem()
        identity = (item.getProperty('play_er.meta_id'), item.getProperty('play_er.link'))
        return bool(all(identity) and identity in allowed_sources)
    except Exception:
        return False


def create_movie_playlist(start_meta, addon, active_provider, tmdb_client, handle, plugin_instance, start_from_next=False, source_list=None):
    from resources.lib import plugin as plugin_module
    from resources.lib import actions
    from resources.lib.utils_filter import clean_title_for_tmdb
    from resources.lib.utils import store_meta_in_cache

    if str(addon.getSetting("movie_autoplay_enable")).lower() == "false":
        log("AUTOLIST [ MOVIE ] - FUNKCE JE DEAKTIVOVÁNA V NASTAVENÍ", xbmc.LOGINFO)
        fallback_params = {'meta': json.dumps(start_meta)}
        if source_list:
            fallback_params['source_list'] = source_list
        actions.find_and_list_sources_multi(fallback_params, plugin_instance)
        return

    win = xbmcgui.Window(10000)
    if win.getProperty("player.movie_playlist_active") == "true":
        return
    win.setProperty("player.movie_playlist_active", "true")
    progress_dialog = None
    try:
        tmdb_id = start_meta.get("tmdb_id")
        title = start_meta.get("title", "")

        if not tmdb_id and title:
            try:
                clean_title, year, _, _, _ = clean_title_for_tmdb(title)
                results = tmdb_client.search_raw(clean_title, year=year, media_type="movie")
                if results and results.get("results"):
                    top = results["results"][0]
                    tmdb_id = top.get("id")
                    start_meta["tmdb_id"] = tmdb_id
                    start_meta["title"] = top.get("title")
                    if top.get("poster_path"):
                        start_meta["poster"] = f"https://image.tmdb.org/t/p/w500{top['poster_path']}"
            except Exception:
                pass

        if tmdb_id and not start_meta.get("cast_full"):
            try:
                detail_data = tmdb_client.get_full_details("movie", tmdb_id)
                if detail_data:
                    movie_props = tmdb_client._build_metadata_props(detail_data, 'movie')
                    start_meta.update(movie_props)
                    start_meta["tmdb_id"] = tmdb_id
            except Exception:
                pass

        if not tmdb_id:
            notify_error("ERROR TMDB ID není k dispozici", category="AUTOLIST", time=4000, sound=True)
            if handle and handle > 0:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return

        history_keys = {plugin_module.get_entry_key({"meta": start_meta})}
        try:
            history = cache_manager.user_data_get("playback_history") or []
            for entry in history:
                history_keys.add(plugin_module.get_entry_key(entry))
        except Exception:
            pass

        try:
            max_playlist_items = get_setting_int_with_bounds(addon, "movie_autoplay_erems", 3)
        except Exception:
            max_playlist_items = 3

        progress_dialog = xbmcgui.DialogProgress()
        progress_dialog.create(
            f"[COLOR {Colors.ORANGE}]○  VYTVÁŘÍM  AUTOLIST  FILMŮ  ▼[/COLOR]",
            f"[B][COLOR orange]POČET NÁSLEDUJÍCÍCH FILMŮ V AUTOLISTU[/COLOR]    [COLOR limegreen][  {max_playlist_items}  ][/COLOR][/B]",
        )
        progress_dialog.update(5, f"SERVER ► HLEDÁM ZDROJE [COLOR limegreen][ {max_playlist_items} ][/COLOR] : {start_meta.get('title')}")

        search_query_start = f"{start_meta.get('title')} {start_meta.get('year', '')}"
        providers = plugin_instance.provider_manager.get_providers_to_search()
        sort_priority = str(addon.getSetting("multi_provider_sort"))

        source_selection_enabled = str(addon.getSetting("autolist_source_selection_enable")).lower() == "true"
        method_str = addon.getSetting("autolist_source_method")
        apply_global_filters = not (source_selection_enabled and method_str == "INTELIGENTNÍ")

        results_start = actions._search_providers_parallel(search_query_start, providers, apply_filters=apply_global_filters, sort_priority=sort_priority)

        if results_start:
            selected_source = None
            if source_selection_enabled:
                if method_str == "PODLE POZICE":
                    try:
                        priority = get_setting_int_with_bounds(addon, "autolist_result_priority", 1, 1, 5)
                    except Exception:
                        priority = 1
                    index = min(max(0, priority - 1), len(results_start) - 1)
                    selected_source = results_start[index]
                elif method_str == "INTELIGENTNÍ":
                    results_start = _apply_autolist_filters(results_start, addon)
                    selected_source = results_start[0] if results_start else None
                else:
                    selected_source = results_start[0]
            else:
                selected_source = results_start[0]

            if selected_source:
                start_meta['source_title'] = selected_source['title']

            playable_url, view_identity = actions.resolve_video(
                selected_source["link"],
                selected_source.get("provider"),
                json.dumps(start_meta),
                return_url_only=True,
                return_view_identity=True,
                plugin_instance=plugin_instance
            ) if selected_source else (None, None)

            if playable_url and selected_source:
                li = xbmcgui.ListItem(label=start_meta.get("title"))
                li.setContentLookup(False)
                tmdb_client.fill_list_item(li, start_meta, 'movie')
                li.setProperty("IsPlayable", "true")
                li.setPath(playable_url)
                set_view_identity(li, view_identity)
                attach_subtitles(li, selected_source["link"], provider=selected_source.get("provider"))

                trakt_id_movie = ""
                try:
                    tmdb_movie_id = start_meta.get("tmdb_id")
                    if str(addon.getSetting("enable_trakt_scrobbling")).lower() == "true" and tmdb_movie_id:
                        from resources.lib import trakt as trakt_lib
                        trakt_id_movie = trakt_lib.get_trakt_id(
                            tmdb_movie_id, "movie", plugin_instance.session, addon
                        )
                except Exception as e:
                    log(f"AUTOLIST[ MOVIE ] - Chyba při získání trakt_id: {e}", xbmc.LOGWARNING)

                meta_uuid = store_meta_in_cache(start_meta)
                li.setProperty('play_er.meta_id', str(meta_uuid))
                li.setProperty('play_er.link', str(selected_source["link"]))
                li.setProperty('play_er.provider', str(selected_source.get("provider") or ""))
                li.setProperty('play_er.media_type', 'movie')
                li.setProperty('play_er.trakt_id', str(trakt_id_movie))
                if source_list and not start_from_next:
                    li.setProperty('play_er.source_list', str(source_list))

                try:
                    progress_dialog.close()
                except Exception:
                    pass
                progress_dialog = None

                publish_active_streams(selected_source["link"], provider=selected_source.get("provider"))
                publish_fallback(win, playable_url, start_meta, meta_uuid, 'movie', trakt_id_movie,
                                 source_link=str(selected_source['link']), provider=selected_source.get('provider'),
                                 view_identity=view_identity)
                if handle and handle > 0:
                    xbmcplugin.setResolvedUrl(handle, True, li)
                else:
                    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    playlist.clear()
                    playlist.add(playable_url, li)
                    xbmc.Player().play(playlist)

                try:
                    plugin_module.save_playback_history(start_meta, selected_source.get('link'), skip_refresh=True)
                except Exception:
                    pass

                if max_playlist_items > 1:
                    def _background_loader(start_tmdb_id, max_count):
                        xbmc.sleep(8000)
                        win_bg = xbmcgui.Window(10000)
                        win_bg.setProperty("play_er.bg_playlist_active", "true")

                        try:
                            player = xbmc.Player()
                            allowed_urls = {str(playable_url).split('|', 1)[0]}
                            allowed_sources = {(str(meta_uuid), str(selected_source['link']))} if meta_uuid and selected_source.get('link') else set()
                            if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                                return

                            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                            bg_added = 1

                            recommendations = tmdb_client.get_recommendations_raw("movie", start_tmdb_id)
                            if not isinstance(recommendations, list) or not recommendations:
                                return

                            for rec_item in recommendations[:50]:
                                if bg_added >= max_count or not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                                    break

                                if not isinstance(rec_item, dict):
                                    continue

                                rec_tmdb_id = rec_item.get("id")
                                if not rec_tmdb_id:
                                    continue

                                rec_key = plugin_module.get_entry_key({
                                    "meta": {"media_type": "movie", "tmdb_id": rec_tmdb_id}
                                })
                                if rec_key in history_keys:
                                    continue

                                rec_meta_raw = tmdb_client.get_full_details("movie", rec_tmdb_id)
                                if not rec_meta_raw:
                                    continue

                                rec_meta_full = tmdb_client._build_metadata_props(rec_meta_raw, 'movie')
                                rec_meta_full['tmdb_id'] = rec_tmdb_id

                                search_query_rec = f"{rec_meta_full.get('title')} {rec_meta_full.get('year', '')}"

                                if source_selection_enabled and method_str == "INTELIGENTNÍ":
                                    results_rec_raw = actions._search_providers_parallel(search_query_rec, providers, apply_filters=False, sort_priority=sort_priority)
                                    results_rec = _apply_autolist_filters(results_rec_raw, addon)
                                else:
                                    results_rec = actions._search_providers_parallel(search_query_rec, providers, apply_filters=True, sort_priority=sort_priority)

                                if not results_rec:
                                    continue

                                if source_selection_enabled and method_str == "PODLE POZICE":
                                    selected_rec = results_rec[min(priority - 1, len(results_rec) - 1)]
                                else:
                                    selected_rec = results_rec[0]
                                rec_meta_full['source_title'] = selected_rec['title']

                                playable_url_rec, rec_view_identity = actions.resolve_video(
                                    selected_rec["link"],
                                    selected_rec.get("provider"),
                                    json.dumps(rec_meta_full),
                                    return_url_only=True,
                                    return_view_identity=True,
                                    plugin_instance=plugin_instance
                                )

                                if playable_url_rec:
                                    li_rec = xbmcgui.ListItem(label=rec_meta_full.get("title"))
                                    li_rec.setContentLookup(False)
                                    tmdb_client.fill_list_item(li_rec, rec_meta_full, 'movie')
                                    li_rec.setProperty("IsPlayable", "true")
                                    li_rec.setPath(playable_url_rec)
                                    set_view_identity(li_rec, rec_view_identity)
                                    attach_subtitles(li_rec, selected_rec["link"], provider=selected_rec.get("provider"))

                                    rec_meta_uuid = ''
                                    try:
                                        rec_trakt_id = ""
                                        if str(addon.getSetting("enable_trakt_scrobbling")).lower() == "true":
                                            from resources.lib import trakt as trakt_lib
                                            rec_trakt_id = trakt_lib.get_trakt_id(
                                                rec_tmdb_id, "movie", plugin_instance.session, addon
                                            )

                                        rec_meta_uuid = store_meta_in_cache(rec_meta_full)
                                        li_rec.setProperty('play_er.meta_id', str(rec_meta_uuid))
                                        li_rec.setProperty('play_er.link', str(selected_rec["link"]))
                                        li_rec.setProperty('play_er.provider', str(selected_rec.get("provider") or ""))
                                        li_rec.setProperty('play_er.media_type', 'movie')
                                        li_rec.setProperty('play_er.trakt_id', str(rec_trakt_id))
                                    except Exception:
                                        pass

                                    if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                                        break
                                    allowed_urls.add(str(playable_url_rec).split('|', 1)[0])
                                    if rec_meta_uuid and selected_rec.get('link'):
                                        allowed_sources.add((str(rec_meta_uuid), str(selected_rec['link'])))
                                    _remember_playlist_item(
                                        playable_url_rec, rec_meta_full, rec_meta_uuid,
                                        rec_trakt_id, selected_rec.get('link'), selected_rec.get('provider'), rec_view_identity)
                                    playlist.add(playable_url_rec, li_rec)
                                    history_keys.add(rec_key)
                                    bg_added += 1

                        finally:
                            win_bg.clearProperty("play_er.bg_playlist_active")

                    t = threading.Thread(target=_background_loader, args=(tmdb_id, max_playlist_items))
                    t.start()
                return

        if handle and handle > 0:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())

    finally:
        if progress_dialog is not None:
            try:
                progress_dialog.close()
            except Exception:
                pass
        win.clearProperty("player.movie_playlist_active")


def create_series_playlist(
    start_meta: dict,
    addon: xbmcaddon.Addon,
    active_provider: any,
    tmdb_client: any,
    handle: int,
    plugin_instance: any,
    start_from_next: bool = False,
    use_resolve: bool = True,
    max_items: int = None,
    episodes_count: int = None,
    source_list: str = None,
    start_guard=None,
    prepare_start=None,
    on_started=None
) -> None:
    if start_guard is not None and not start_guard():
        return
    # FIX PRE-EMPTIVE AND FILTERS [CONTINUE CANNOT RESET AN EXHAUSTED LIMIT]
    remaining = get_episode_queue_remaining(start_meta) if start_from_next else None
    if remaining == 0:
        return
    from resources.lib import actions
    from resources.lib.utils import store_meta_in_cache

    if str(addon.getSetting("autolist_enable")).lower() == "false":
        return

    win = xbmcgui.Window(10000)
    if win.getProperty("player.series_playlist_active") == "true":
        return
    win.setProperty("player.series_playlist_active", "true")

    try:
        tmdb_id = validate_tmdb_id(start_meta.get("tmdb_id"))
        if not tmdb_id:
            if use_resolve and handle and handle > 0:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return

        try:
            season_num = int(start_meta.get("season", 0))
            episode_num = int(start_meta.get("episode", 0))
        except Exception:
            if use_resolve and handle and handle > 0:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return

        tv_show_title = start_meta.get("tv_show_title")
        show_details = None
        show_props = {}

        if tmdb_id:
            with tmdb_error_handler("načítání show details"):
                show_details = tmdb_client.get_full_details("tv", tmdb_id)
                if show_details:
                    show_props = tmdb_client._build_metadata_props(show_details, "tv")

        if not show_details and tv_show_title:
            try:
                search_data = tmdb_client.search_raw(tv_show_title, media_type="tv")
                if search_data and search_data.get("results"):
                    fallback_id = search_data["results"][0].get("id")
                    if fallback_id:
                        tmdb_id = fallback_id
                        show_details = tmdb_client.get_full_details("tv", tmdb_id)
                        if show_details:
                            show_props = tmdb_client._build_metadata_props(show_details, "tv")
            except Exception:
                pass

        if not show_details:
            show_props = start_meta.copy()
            show_props['cast_full'] = show_props.get('cast_full', [])

        show_cast = show_props.get("cast_full", [])
        if not start_meta.get("poster"):
            start_meta["poster"] = show_props.get("poster")
        if not start_meta.get("fanart"):
            start_meta["fanart"] = show_props.get("fanart")

        try:
            if max_items is None:
                if start_from_next:
                    max_items = get_setting_int_with_bounds(addon, "continue_episodes_count", 3, 1, 20)
                else:
                    max_items = episodes_count or get_setting_int_with_bounds(addon, "autolist_items", 3, 1, 20)
            if max_items < 1:
                max_items = 3
        except Exception:
            max_items = 3

        if remaining is not None:
            max_items = min(max_items, remaining)

        if start_from_next:
            try:
                s_details = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season_num}")
                if s_details and "episodes" in s_details:
                    ep_count = len(s_details["episodes"])
                    if episode_num >= ep_count:
                        season_num += 1
                        episode_num = 1
                        next_s_details = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season_num}")
                        if not next_s_details or not next_s_details.get("episodes") or "status_code" in next_s_details:
                            notify_info("INFO Konec seriálu (další epizoda nenalezena)", category="CONTINUE")
                            if use_resolve and handle and handle > 0:
                                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
                            return
                    else:
                        episode_num += 1
                else:
                    episode_num += 1
            except Exception:
                episode_num += 1

        search_query = f"{tv_show_title} S{season_num:02d}E{episode_num:02d}"

        if start_from_next:
            source_selection_enabled = str(addon.getSetting("continue_source_selection_enable")).lower() == "true"
            method_str = addon.getSetting("continue_source_method")
            priority_setting = "continue_result_priority"
        else:
            source_selection_enabled = str(addon.getSetting("autolist_source_selection_enable_ser")).lower() == "true"
            method_str = addon.getSetting("autolist_source_method_ser")
            priority_setting = "autolist_result_priority_ser"

        providers = plugin_instance.provider_manager.get_providers_to_search()
        sort_priority = str(addon.getSetting("multi_provider_sort"))

        def _get_filtered_sources(query, season=None, episode=None):
            if start_from_next:
                return _search_continue_sources(
                    query,
                    addon,
                    plugin_instance,
                    tmdb_id,
                    season if season is not None else season_num,
                    episode if episode is not None else episode_num
                )
            if source_selection_enabled and method_str == "INTELIGENTNÍ":
                raw_s = actions._search_providers_parallel(query, providers, apply_filters=True, sort_priority=sort_priority)
                return _apply_autolist_filters_ser(raw_s, addon)
            return actions._search_providers_parallel(query, providers, apply_filters=True, sort_priority=sort_priority)

        sources = _get_filtered_sources(search_query, season_num, episode_num)
        if start_guard is not None and not start_guard():
            return
        if not sources:
            if use_resolve and handle and handle > 0:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return

        selected = None
        if source_selection_enabled and method_str == "PODLE POZICE":
            try:
                priority = get_setting_int_with_bounds(addon, priority_setting, 1, 1, 5)
            except Exception:
                priority = 1
            index = min(max(0, priority - 1), len(sources) - 1)
            selected = sources[index]
        else:
            selected = sources[0]

        if start_from_next and str(addon.getSetting('auto_prediction_enable')).lower() == 'true':
            from resources.lib.utils_auto_prediction import capture_reference, select_source
            start_meta = dict(start_meta)
            if str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
                from resources.lib.utils_prediction_handoff import begin_session
                begin_session(start_meta, addon)
            capture_reference(start_meta, {'title': start_meta.get('source_title', '')}, addon)
            selected = select_source(sources, start_meta, addon, selected, target=(season_num, episode_num))
            if selected is None:
                if use_resolve and handle and handle > 0:
                    xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
                return

        ep_props = {}
        try:
            ep_data_raw = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season_num}/episode/{episode_num}", params={"append_to_response": "credits"})
            if ep_data_raw and "status_code" not in ep_data_raw:
                ep_props = tmdb_client._build_metadata_props(ep_data_raw, 'episode')
        except Exception:
            pass

        if not ep_props:
            ep_props = start_meta.copy()
            ep_props['cast_full'] = ep_props.get('cast_full', [])

        final_cast = ep_props.get("cast_full", []) + show_cast
        current_episode_meta_dict = ep_props.copy()
        for key, value in show_props.items():
            if not current_episode_meta_dict.get(key):
                current_episode_meta_dict[key] = value

        current_episode_meta_dict.update({
            'media_type': 'episode',
            'tv_show_title': tv_show_title,
            'title': ep_props.get("title") or f"Epizoda {episode_num}",
            'season': season_num,
            'episode': episode_num,
            'tmdb_id': tmdb_id,
            'source_title': selected.get("title", ""),
            'cast_full': final_cast
        })
        # FIX PRE-EMPTIVE AND FILTERS [CARRY BUDGET THROUGH CONTINUE FALLBACK]
        current_episode_meta_dict['_play_er_queue_remaining'] = max_items - 1
        if start_meta.get('_play_er_prediction_session'):
            current_episode_meta_dict['_play_er_prediction_session'] = start_meta['_play_er_prediction_session']
        if str(addon.getSetting('auto_prediction_enable')).lower() == 'true':
            from resources.lib.utils_auto_prediction import capture_reference, REFERENCE
            if start_from_next and isinstance(start_meta.get(REFERENCE), dict):
                current_episode_meta_dict[REFERENCE] = dict(start_meta[REFERENCE])
            if not start_from_next:
                capture_reference(current_episode_meta_dict, selected, addon)
                if str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
                    from resources.lib.utils_prediction_handoff import begin_session
                    begin_session(current_episode_meta_dict, addon)


        if not current_episode_meta_dict.get('thumb'):
            current_episode_meta_dict['thumb'] = ep_props.get('thumb') or show_props.get('thumb')
        if not current_episode_meta_dict.get('poster'):
            current_episode_meta_dict['poster'] = ep_props.get('poster') or show_props.get('poster')
        if not current_episode_meta_dict.get('fanart'):
            current_episode_meta_dict['fanart'] = ep_props.get('fanart') or show_props.get('fanart')

        final_url, view_identity = actions.resolve_video(
            selected["link"],
            selected.get("provider"),
            json.dumps(current_episode_meta_dict),
            return_url_only=True,
            return_view_identity=True,
            plugin_instance=plugin_instance,
        )

        if start_guard is not None and not start_guard():
            return
        if not final_url:
            if use_resolve and handle and handle > 0:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return

        li = xbmcgui.ListItem(f"S{season_num:02d}E{episode_num:02d} - {current_episode_meta_dict['title']}")
        li.setContentLookup(False)
        tmdb_client.fill_list_item(li, current_episode_meta_dict, "episode")
        li.setProperty("IsPlayable", "true")
        li.setPath(final_url)
        set_view_identity(li, view_identity)
        attach_subtitles(li, selected["link"], provider=selected.get("provider"))

        meta_uuid = store_meta_in_cache(current_episode_meta_dict)

        trakt_id = ""
        try:
            if str(addon.getSetting("enable_trakt_scrobbling")).lower() == "true" and tmdb_id:
                from resources.lib import trakt as trakt_lib
                trakt_id = trakt_lib.get_trakt_episode_id(
                    tmdb_id, season_num, episode_num, plugin_instance.session, addon
                )
        except Exception:
            pass

        li.setProperty('play_er.meta_id', str(meta_uuid))
        li.setProperty('play_er.link', str(selected["link"]))
        li.setProperty('play_er.provider', str(selected.get("provider") or ""))
        li.setProperty('play_er.media_type', 'episode')
        li.setProperty('play_er.trakt_id', str(trakt_id))
        if source_list and not start_from_next:
            li.setProperty('play_er.source_list', str(source_list))

        if use_resolve and handle and handle > 0:
            publish_active_streams(selected["link"], provider=selected.get("provider"))
            publish_fallback(win, final_url, current_episode_meta_dict, meta_uuid, 'episode', trakt_id,
                             source_link=str(selected['link']), provider=selected.get('provider'), view_identity=view_identity)
            xbmcplugin.setResolvedUrl(handle, True, li)
        else:
            pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            if start_guard is not None and not start_guard():
                return
            if prepare_start is not None and not prepare_start():
                return
            if start_guard is not None and not start_guard():
                return
            pl.clear()
            pl.add(final_url, li)
            if start_guard is not None and not start_guard():
                return
            publish_active_streams(selected["link"], provider=selected.get("provider"))
            publish_fallback(win, final_url, current_episode_meta_dict, meta_uuid, 'episode', trakt_id,
                             source_link=str(selected['link']), provider=selected.get('provider'), view_identity=view_identity)
            xbmc.Player().play(pl)
            if on_started is not None:
                on_started()
            try:
                from resources.lib import plugin as plugin_module
                plugin_module.save_playback_history(current_episode_meta_dict, selected.get('link'), skip_refresh=True)
            except Exception:
                pass

        if max_items > 1:
            def _bg_series_loader():
                win_bg = None
                try:
                    xbmc.sleep(8000)
                    win_bg = xbmcgui.Window(10000)
                    win_bg.setProperty("play_er.bg_playlist_active", "true")
                    player = xbmc.Player()
                    allowed_urls = {str(final_url).split('|', 1)[0]}
                    allowed_sources = {(str(meta_uuid), str(selected['link']))} if meta_uuid and selected.get('link') else set()
                    pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
                    c_season = season_num
                    c_ep = episode_num + 1
                    added = 1

                    while added < max_items:
                        if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                            break

                        bg_ep_props = {}
                        try:
                            bg_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{c_season}/episode/{c_ep}", params={"append_to_response": "credits"})
                            if not bg_data or "status_code" in bg_data:
                                season_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{c_season}")
                                if season_data and "episodes" in season_data:
                                    if c_ep > len(season_data["episodes"]):
                                        c_season += 1
                                        c_ep = 1
                                        bg_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{c_season}/episode/{c_ep}", params={"append_to_response": "credits"})
                                        if not bg_data or "status_code" in bg_data:
                                            break
                                    else:
                                        break
                                else:
                                    break

                            if bg_data:
                                bg_ep_props = tmdb_client._build_metadata_props(bg_data, 'episode')
                        except Exception:
                            pass

                        if not bg_ep_props:
                            break
                        if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                            break

                        search_q = f"{tv_show_title} S{c_season:02d}E{c_ep:02d}"
                        srcs = _get_filtered_sources(search_q, c_season, c_ep)
                        if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                            break
                        if not srcs:
                            if str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
                                from resources.lib.utils_auto_prediction import select_source
                                select_source([], current_episode_meta_dict, addon, None, target=(c_season, c_ep))
                            break

                        if source_selection_enabled and method_str == "PODLE POZICE":
                            ep_meta_uuid = ''
                            try:
                                pr = get_setting_int_with_bounds(addon, priority_setting, 1, 1, 5)
                            except Exception:
                                pr = 1
                            ix = min(max(0, pr - 1), len(srcs) - 1)
                            sel = srcs[ix]
                        else:
                            sel = srcs[0]

                        if str(addon.getSetting('auto_prediction_enable')).lower() == 'true':
                            from resources.lib.utils_auto_prediction import select_source
                            sel = select_source(srcs, current_episode_meta_dict, addon, sel, target=(c_season, c_ep))
                            if sel is None:
                                break

                        bg_cast = bg_ep_props.get("cast_full", []) + show_cast
                        ep_meta = current_episode_meta_dict.copy()
                        # Replace all episode fields, including dates, duration and votes.
                        ep_meta.update(bg_ep_props)
                        for key in ("genre", "studio", "mpaa", "poster", "fanart"):
                            if not ep_meta.get(key):
                                ep_meta[key] = show_props.get(key, "")
                        ep_meta["thumb"] = bg_ep_props.get("thumb") or show_props.get("thumb", "")
                        ep_meta.update({
                            "season": c_season,
                            "episode": c_ep,
                            "title": bg_ep_props.get("title") or f"Epizoda {c_ep}",
                            "plot": bg_ep_props.get("plot", ""),
                            "rating": bg_ep_props.get("rating", 0.0),
                            "cast_full": bg_cast,
                            "source_title": sel.get("title", ""),
                            "tmdb_id": tmdb_id
                        })
                        # 'added' includes the playing episode and all earlier additions.
                        ep_meta['_play_er_queue_remaining'] = max_items - added - 1

                        if bg_ep_props.get("thumb"): ep_meta["thumb"] = bg_ep_props.get("thumb")
                        if bg_ep_props.get("poster"): ep_meta["poster"] = bg_ep_props.get("poster")
                        elif show_props.get("poster"): ep_meta["poster"] = show_props.get("poster")
                        if bg_ep_props.get("fanart"): ep_meta["fanart"] = bg_ep_props.get("fanart")
                        elif show_props.get("fanart"): ep_meta["fanart"] = show_props.get("fanart")

                        url, ep_view_identity = actions.resolve_video(sel["link"], sel.get("provider"), json.dumps(ep_meta), return_url_only=True, return_view_identity=True, plugin_instance=plugin_instance)
                        if url:
                            ep_li = xbmcgui.ListItem(f"S{c_season:02d}E{c_ep:02d} - {ep_meta['title']}")
                            ep_li.setContentLookup(False)
                            tmdb_client.fill_list_item(ep_li, ep_meta, "episode")
                            ep_li.setProperty("IsPlayable", "true")
                            ep_li.setPath(url)
                            set_view_identity(ep_li, ep_view_identity)
                            attach_subtitles(ep_li, sel["link"], provider=sel.get("provider"))

                            try:
                                ep_meta_uuid = store_meta_in_cache(ep_meta)
                                ep_li.setProperty('play_er.meta_id', str(ep_meta_uuid))
                                ep_li.setProperty('play_er.link', str(sel["link"]))
                                ep_li.setProperty('play_er.provider', str(sel.get("provider") or ""))
                                ep_li.setProperty('play_er.media_type', 'episode')
                                ep_li.setProperty('play_er.tmdb_id', str(tmdb_id))
                                ep_li.setProperty('play_er.season', str(c_season))
                                ep_li.setProperty('play_er.episode', str(c_ep))
                                ep_li.setProperty('play_er.queue_managed', 'true')

                                ep_trakt_id = ""
                                if str(addon.getSetting("enable_trakt_scrobbling")).lower() == "true" and ep_meta.get("tmdb_id"):
                                    from resources.lib import trakt as trakt_lib
                                    ep_trakt_id = trakt_lib.get_trakt_episode_id(
                                        ep_meta.get("tmdb_id"), c_season, c_ep, plugin_instance.session, addon
                                    )
                                ep_li.setProperty('play_er.trakt_id', str(ep_trakt_id))
                            except Exception:
                                pass

                            if not _playlist_playback_is_current(player, allowed_urls, allowed_sources):
                                break
                            allowed_urls.add(str(url).split('|', 1)[0])
                            if ep_meta_uuid and sel.get('link'):
                                allowed_sources.add((str(ep_meta_uuid), str(sel['link'])))
                            pl.add(url, ep_li)
                            _remember_playlist_item(
                                url, ep_meta,
                                ep_li.getProperty("play_er.meta_id"),
                                ep_li.getProperty("play_er.trakt_id"),
                                sel.get("link"), sel.get("provider"), ep_view_identity
                            )
                            added += 1
                        else:
                            break
                        c_ep += 1

                finally:
                    try:
                        if win_bg is not None:
                            win_bg.clearProperty("play_er.bg_playlist_active")
                    finally:
                        win.clearProperty("play_er.bg_series_playlist_building")

            win.setProperty("play_er.bg_series_playlist_building", "true")
            try:
                threading.Thread(target=_bg_series_loader).start()
            except Exception as e:
                win.clearProperty("play_er.bg_series_playlist_building")
                log(f"AUTOLIST SERIES - Nelze spustit načítání na pozadí: {e}", xbmc.LOGWARNING)

    except Exception as e:
        log(f"AUTOLIST SERIES - Kritická chyba: {e}", xbmc.LOGERROR)
        if use_resolve and handle and handle > 0:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
    finally:
        win.clearProperty("player.series_playlist_active")


# FIX PRE-EMPTIVE AND FILTERS [TMDBHELPER FIRST EPISODE QUEUE]
# FIX PRE-EMPTIVE AND FILTERS [LEGACY TMDBH QUEUE PRESERVED FOR ROLLBACK]
def _queue_following_episodes_from_tmdbh_legacy(meta, addon, plugin_instance):
    """Replace queued alternative streams with filtered next episodes after TMDBH selection."""
    if str(addon.getSetting("autolist_enable")).lower() == "false":
        return
    if not meta or meta.get("media_type") != "episode" or not meta.get("tmdb_id"):
        return

    win = xbmcgui.Window(10000)
    if win.getProperty("play_er.tmdbh_episode_queue_active") == "true":
        return
    win.setProperty("play_er.tmdbh_episode_queue_active", "true")

    def _load_following_episodes():
        try:
            from resources.lib import actions
            from resources.lib.utils import store_meta_in_cache

            tmdb_id = validate_tmdb_id(meta.get("tmdb_id"))
            if not tmdb_id or not plugin_instance.tmdb_client:
                return

            try:
                current_season = int(meta.get("season", 0))
                current_episode = int(meta.get("episode", 0))
                max_items = get_setting_int_with_bounds(addon, "continue_episodes_count", 3, 1, 20)
            except Exception:
                return
            if max_items < 1:
                return

            player = xbmc.Player()
            current_item_confirmed = False
            for _ in range(120):
                if player.isPlayingVideo():
                    try:
                        active_meta = json.loads(win.getProperty("play_er.current_meta") or "{}")
                    except Exception:
                        active_meta = {}
                    if (
                        str(active_meta.get("tmdb_id")) == str(tmdb_id)
                        and str(active_meta.get("season")) == str(current_season)
                        and str(active_meta.get("episode")) == str(current_episode)
                    ):
                        current_item_confirmed = True
                        break
                    return
                xbmc.sleep(500)

            if not current_item_confirmed:
                log("FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: přehrávání aktuální epizody nebylo potvrzeno", xbmc.LOGWARNING)
                return

            playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            position = playlist.getposition()
            size = playlist.size()
            if position < 0 or size <= position:
                log("FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: Kodi nevrátilo platnou pozici playlistu", xbmc.LOGWARNING)
                return

            # FIX PRE-EMPTIVE AND FILTERS - Kodi PlayList.remove() removes by URL;
            # JSON-RPC position removal keeps the active item and removes later stream alternatives.
            for item_position in range(size - 1, position, -1):
                request = json.dumps({
                    "jsonrpc": "2.0",
                    "method": "Playlist.Remove",
                    "params": {"playlistid": 1, "position": item_position},
                    "id": "play_er_episode_queue"
                })
                response = json.loads(xbmc.executeJSONRPC(request) or "{}")
                if response.get("error"):
                    log(f"FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: nelze odstranit alternativní streamy: {response['error']}", xbmc.LOGWARNING)
                    return
            removed_streams = max(0, size - position - 1)

            tmdb_client = plugin_instance.tmdb_client
            show_details = tmdb_client.get_full_details("tv", tmdb_id) or {}
            show_props = tmdb_client._build_metadata_props(show_details, "tv") if show_details else {}
            show_title = meta.get("tv_show_title") or show_props.get("title") or ""
            show_cast = show_props.get("cast_full", [])

            sources_to_add = []
            season_num = current_season
            episode_num = current_episode
            for _ in range(max_items):
                candidate_season = season_num
                candidate_episode = episode_num + 1
                episode_data = tmdb_client._fetch(
                    f"tv/{tmdb_id}/season/{candidate_season}/episode/{candidate_episode}",
                    params={"append_to_response": "credits"}
                )

                if not episode_data or "status_code" in episode_data:
                    season_details = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season_num}")
                    season_count = len(season_details.get("episodes", [])) if season_details else 0
                    if season_count and episode_num >= season_count:
                        candidate_season = season_num + 1
                        candidate_episode = 1
                        episode_data = tmdb_client._fetch(
                            f"tv/{tmdb_id}/season/{candidate_season}/episode/{candidate_episode}",
                            params={"append_to_response": "credits"}
                        )
                    if not episode_data or "status_code" in episode_data:
                        break

                episode_props = tmdb_client._build_metadata_props(episode_data, "episode")
                query = f"{show_title} S{candidate_season:02d}E{candidate_episode:02d}"
                sources = _search_continue_sources(
                    query, addon, plugin_instance, tmdb_id, candidate_season, candidate_episode
                )
                if not sources:
                    break

                selection_enabled = str(addon.getSetting("continue_source_selection_enable")).lower() == "true"
                method = addon.getSetting("continue_source_method")
                if selection_enabled and method == "PODLE POZICE":
                    priority = get_setting_int_with_bounds(addon, "continue_result_priority", 1, 1, 5)
                    selected = sources[min(max(0, priority - 1), len(sources) - 1)]
                else:
                    selected = sources[0]

                episode_meta = dict(meta)
                episode_meta.update(show_props)
                episode_meta.update(episode_props)
                episode_meta.update({
                    "media_type": "episode",
                    "tv_show_title": show_title,
                    "title": episode_props.get("title") or f"Epizoda {candidate_episode}",
                    "season": candidate_season,
                    "episode": candidate_episode,
                    "tmdb_id": tmdb_id,
                    "source_title": selected.get("title", ""),
                    "cast_full": episode_props.get("cast_full", []) + show_cast
                })
                episode_meta.pop("_play_er_tmdbh_source_search", None)
                final_url, view_identity = actions.resolve_video(
                    selected["link"], selected.get("provider"), json.dumps(episode_meta),
                    return_url_only=True, return_view_identity=True, plugin_instance=plugin_instance
                )
                if not final_url:
                    break

                list_item = xbmcgui.ListItem(
                    f"S{candidate_season:02d}E{candidate_episode:02d} - {episode_meta['title']}"
                )
                list_item.setContentLookup(False)
                tmdb_client.fill_list_item(list_item, episode_meta, "episode")
                list_item.setProperty("IsPlayable", "true")
                list_item.setPath(final_url)
                set_view_identity(list_item, view_identity)
                attach_subtitles(list_item, selected["link"], provider=selected.get("provider"))
                list_item.setProperty("play_er.media_type", "episode")
                list_item.setProperty("play_er.tmdb_id", str(tmdb_id))
                list_item.setProperty("play_er.season", str(candidate_season))
                list_item.setProperty("play_er.episode", str(candidate_episode))
                meta_uuid = store_meta_in_cache(episode_meta)
                trakt_id = ""
                try:
                    if addon.getSettingBool("enable_trakt_scrobbling"):
                        from resources.lib import trakt as trakt_lib
                        trakt_id = trakt_lib.get_trakt_episode_id(
                            tmdb_id, candidate_season, candidate_episode,
                            plugin_instance.session, addon
                        )
                except Exception:
                    pass
                list_item.setProperty("play_er.meta_id", str(meta_uuid))
                list_item.setProperty("play_er.link", str(selected["link"]))
                list_item.setProperty("play_er.provider", str(selected.get("provider") or ""))
                list_item.setProperty("play_er.trakt_id", str(trakt_id))
                sources_to_add.append((final_url, list_item))
                season_num, episode_num = candidate_season, candidate_episode

            if not sources_to_add:
                log("FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: nejsou dostupné filtrované další epizody", xbmc.LOGINFO)
                return

            try:
                active_meta = json.loads(win.getProperty("play_er.current_meta") or "{}")
            except Exception:
                active_meta = {}
            if (
                not player.isPlayingVideo()
                or str(active_meta.get("tmdb_id")) != str(tmdb_id)
                or str(active_meta.get("season")) != str(current_season)
                or str(active_meta.get("episode")) != str(current_episode)
                or playlist.getposition() != position
                or playlist.size() != position + 1
            ):
                log("FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: přehrávání nebo playlist se během hledání změnil", xbmc.LOGINFO)
                return

            for final_url, list_item in sources_to_add:
                playlist.add(final_url, list_item)

            log(f"FIX PRE-EMPTIVE AND FILTERS - TMDBH queue: odstraněno {removed_streams} alternativních streamů, přidáno {len(sources_to_add)} následujících epizod", xbmc.LOGINFO)
        except Exception as e:
            log(f"FIX PRE-EMPTIVE AND FILTERS - TMDBH queue chyba: {e}", xbmc.LOGWARNING)
        finally:
            win.clearProperty("play_er.tmdbh_episode_queue_active")

    threading.Thread(target=_load_following_episodes).start()


# FIX PRE-EMPTIVE AND FILTERS [ROLLING TMDBHELPER QUEUE]
def _build_managed_episode_item(meta, addon, plugin_instance, show_props, show_cast, season, episode):
    from resources.lib import actions
    from resources.lib.utils import store_meta_in_cache

    tmdb_client = plugin_instance.tmdb_client
    tmdb_id = validate_tmdb_id(meta.get("tmdb_id"))
    episode_data = tmdb_client._fetch(
        f"tv/{tmdb_id}/season/{season}/episode/{episode}",
        params={"append_to_response": "credits"}
    )
    if not episode_data or "status_code" in episode_data:
        return None

    episode_props = tmdb_client._build_metadata_props(episode_data, "episode")
    show_title = meta.get("tv_show_title") or show_props.get("title") or ""
    query = f"{show_title} S{season:02d}E{episode:02d}"
    sources = _search_continue_sources(
        query, addon, plugin_instance, tmdb_id, season, episode
    )
    if not sources:
        if str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true':
            from resources.lib.utils_auto_prediction import select_source
            select_source([], meta, addon, None, target=(season, episode))
        return None

    selection_enabled = str(addon.getSetting("continue_source_selection_enable")).lower() == "true"
    method = addon.getSetting("continue_source_method")
    if selection_enabled and method == "PODLE POZICE":
        priority = get_setting_int_with_bounds(addon, "continue_result_priority", 1, 1, 5)
        selected = sources[min(max(0, priority - 1), len(sources) - 1)]
    else:
        selected = sources[0]

    if str(addon.getSetting('auto_prediction_enable')).lower() == 'true':
        from resources.lib.utils_auto_prediction import select_source
        selected = select_source(sources, meta, addon, selected, target=(season, episode))
        if selected is None:
            return None

    episode_meta = dict(meta)
    episode_meta.update(show_props)
    episode_meta.update(episode_props)
    # Match CONTINUE's merge: episode detail often omits show-level fields.
    # Empty genre/studio properties otherwise leak into JSON-RPC as strings
    # instead of arrays, causing remote clients such as Yatse to lose details.
    for key, value in show_props.items():
        if not episode_meta.get(key):
            episode_meta[key] = value
    # Keep session artwork as a final fallback if TMDB has no show art either.
    for art_key in ("poster", "fanart", "thumb"):
        episode_meta[art_key] = (episode_props.get(art_key)
                                 or show_props.get(art_key)
                                 or meta.get(art_key))
    episode_meta.update({
        "media_type": "episode",
        "tv_show_title": show_title,
        "title": episode_props.get("title") or f"Epizoda {episode}",
        "season": season,
        "episode": episode,
        "tmdb_id": tmdb_id,
        "source_title": selected.get("title", ""),
        "cast_full": episode_props.get("cast_full", []) + show_cast
    })
    episode_meta.pop("_play_er_tmdbh_source_search", None)

    final_url, view_identity = actions.resolve_video(
        selected["link"], selected.get("provider"), json.dumps(episode_meta),
        return_url_only=True, return_view_identity=True, plugin_instance=plugin_instance
    )
    if not final_url:
        return None

    list_item = xbmcgui.ListItem(f"S{season:02d}E{episode:02d} - {episode_meta['title']}")
    list_item.setContentLookup(False)
    tmdb_client.fill_list_item(list_item, episode_meta, "episode")
    list_item.setProperty("IsPlayable", "true")
    list_item.setPath(final_url)
    set_view_identity(list_item, view_identity)
    attach_subtitles(list_item, selected["link"], provider=selected.get("provider"))
    list_item.setProperty("play_er.media_type", "episode")
    list_item.setProperty("play_er.tmdb_id", str(tmdb_id))
    list_item.setProperty("play_er.season", str(season))
    list_item.setProperty("play_er.episode", str(episode))
    list_item.setProperty("play_er.queue_managed", "true")
    meta_id = store_meta_in_cache(episode_meta)
    list_item.setProperty("play_er.meta_id", str(meta_id))
    list_item.setProperty("play_er.link", str(selected["link"]))
    list_item.setProperty("play_er.provider", str(selected.get("provider") or ""))

    trakt_id = ""
    try:
        if addon.getSettingBool("enable_trakt_scrobbling"):
            from resources.lib import trakt as trakt_lib
            trakt_id = trakt_lib.get_trakt_episode_id(
                tmdb_id, season, episode, plugin_instance.session, addon
            )
    except Exception:
        pass
    list_item.setProperty("play_er.trakt_id", str(trakt_id))
    _remember_playlist_item(final_url, episode_meta, meta_id, trakt_id, selected.get("link"), selected.get("provider"), view_identity)
    return final_url, list_item


def _active_episode_matches(player, win, meta):
    try:
        playing_item = player.getPlayingItem()
        meta_id = playing_item.getProperty("play_er.meta_id")
        if meta_id:
            from resources.lib.utils import get_meta_from_cache
            active_meta = get_meta_from_cache(meta_id)
        else:
            active_meta = json.loads(win.getProperty("play_er.current_meta") or "{}")
        return (
            str(active_meta.get("tmdb_id")) == str(meta.get("tmdb_id"))
            and str(active_meta.get("season")) == str(meta.get("season"))
            and str(active_meta.get("episode")) == str(meta.get("episode"))
        )
    except Exception:
        return False


def queue_following_episodes_from_tmdbh(meta, addon, plugin_instance, seed_only=True, verify_future=False):
    """Seed one episode after TMDBH selection, then refill only missing queue entries."""
    if str(addon.getSetting("autolist_enable")).lower() == "false":
        return
    if not meta or meta.get("media_type") != "episode" or not meta.get("tmdb_id"):
        return
    if get_episode_queue_remaining(meta) == 0:
        return

    win = xbmcgui.Window(10000)
    if win.getProperty("play_er.tmdbh_episode_queue_active") == "true":
        return
    win.setProperty("play_er.tmdbh_episode_queue_active", "true")

    def _load_following_episodes():
        try:
            tmdb_id = validate_tmdb_id(meta.get("tmdb_id"))
            tmdb_client = plugin_instance.tmdb_client
            if not tmdb_id or not tmdb_client:
                return

            try:
                current_season = int(meta.get("season", 0))
                current_episode = int(meta.get("episode", 0))
                configured_count = get_setting_int_with_bounds(addon, "continue_episodes_count", 3, 1, 20)
            except Exception:
                return

            player = xbmc.Player()
            for _ in range(120):
                if player.isPlayingVideo():
                    if not _active_episode_matches(player, win, meta):
                        return
                    break
                xbmc.sleep(500)
            else:
                log("FIX PRE-EMPTIVE AND FILTERS - Queue: aktuální epizoda se nezačala přehrávat", xbmc.LOGWARNING)
                return

            if not seed_only:
                for _ in range(120):
                    if win.getProperty("play_er.bg_series_playlist_building") != "true":
                        break
                    xbmc.sleep(500)

            playlist, position, items = _get_video_playlist_snapshot()
            size = playlist.size()
            if position < 0 or size <= position:
                log("FIX PRE-EMPTIVE AND FILTERS - Queue: Kodi nevrátilo platnou pozici playlistu", xbmc.LOGWARNING)
                return

            future_items = [] if seed_only else _managed_future_episode_items(meta, items, position)
            # If the current ListItem lost its properties, do not risk
            # duplicating or appending behind future items we cannot identify.
            if not seed_only and verify_future and (
                len(items) != size or len(future_items) != size - position - 1
            ):
                log("FIX PRE-EMPTIVE AND FILTERS - Queue: nelze ověřit následující položky", xbmc.LOGINFO)
                return
            # FIX PRE-EMPTIVE AND FILTERS [REFILL ONLY WITHIN THE ORIGINAL LIMIT]
            # Original rolling target recreated the same number after EVERY episode:
            # target_future_count = 1 if seed_only else max(0, configured_count - 1)
            remaining = get_episode_queue_remaining(meta)
            if remaining is None:
                remaining = max(0, configured_count - 1)
            target_future_count = 1 if seed_only else max(0, configured_count - 1)
            target_future_count = min(target_future_count, remaining)
            missing_count = max(0, target_future_count - len(future_items))
            if not missing_count:
                return

            # FIX PRE-EMPTIVE AND FILTERS - nejdřív vyhledáme další epizodu.
            # Alternativní zdroje aktuální epizody odstraníme až po úspěšném hledání.
            removed_streams = 0
            if seed_only:
                expected_size = size
            else:
                expected_size = size

            show_details = tmdb_client.get_full_details("tv", tmdb_id) or {}
            show_props = tmdb_client._build_metadata_props(show_details, "tv") if show_details else {}
            show_cast = show_props.get("cast_full", [])
            base_episode = future_items[-1] if future_items else {
                "season": current_season,
                "episode": current_episode
            }
            season_num = int(base_episode["season"])
            episode_num = int(base_episode["episode"])
            items_to_add = []

            for _ in range(missing_count):
                coordinates = _next_episode_coordinates(tmdb_id, season_num, episode_num, tmdb_client)
                if not coordinates:
                    break
                candidate_season, candidate_episode = coordinates
                candidate_meta = dict(meta)
                candidate_meta['_play_er_queue_remaining'] = remaining - len(future_items) - len(items_to_add) - 1
                item = _build_managed_episode_item(
                    candidate_meta, addon, plugin_instance, show_props, show_cast,
                    candidate_season, candidate_episode
                )
                if not item:
                    break
                items_to_add.append(item)
                season_num, episode_num = candidate_season, candidate_episode

            strict_seed_end = (seed_only and not items_to_add
                               and str(addon.getSetting('auto_prediction_enable')).lower() == 'true'
                               and str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true')
            if not items_to_add and not strict_seed_end:
                log("FIX PRE-EMPTIVE AND FILTERS - Queue: žádné nové filtrované epizody", xbmc.LOGINFO)
                return

            if (
                not player.isPlayingVideo()
                or not _active_episode_matches(player, win, meta)
                or playlist.getposition() != position
                or playlist.size() != expected_size
            ):
                log("FIX PRE-EMPTIVE AND FILTERS - Queue: přehrávání nebo playlist se během hledání změnil", xbmc.LOGINFO)
                return

            if seed_only:
                for item_position in range(size - 1, position, -1):
                    request = json.dumps({
                        "jsonrpc": "2.0",
                        "method": "Playlist.Remove",
                        "params": {"playlistid": 1, "position": item_position},
                        "id": "play_er_episode_queue"
                    })
                    response = json.loads(xbmc.executeJSONRPC(request) or "{}")
                    if response.get("error"):
                        log(f"FIX PRE-EMPTIVE AND FILTERS - Queue: nelze odstranit alternativní streamy: {response['error']}", xbmc.LOGWARNING)
                        return
                removed_streams = max(0, size - position - 1)
                if playlist.getposition() != position or playlist.size() != position + 1:
                    log("FIX PRE-EMPTIVE AND FILTERS - Queue: playlist se změnil při odstranění alternativních streamů", xbmc.LOGINFO)
                    return

            for final_url, list_item in items_to_add:
                playlist.add(final_url, list_item)

            log(
                f"FIX PRE-EMPTIVE AND FILTERS - Queue: odstraněno {removed_streams} alternativních streamů, "
                f"doplněno {len(items_to_add)} epizod; ve frontě nyní {len(future_items) + len(items_to_add)} dalších",
                xbmc.LOGINFO
            )
        except Exception as e:
            log(f"FIX PRE-EMPTIVE AND FILTERS - Queue chyba: {e}", xbmc.LOGWARNING)
        finally:
            win.clearProperty("play_er.tmdbh_episode_queue_active")

    threading.Thread(target=_load_following_episodes).start()


def random_movie_trigger(start_meta, addon, active_provider, tmdb_client, handle, plugin_instance):
    create_movie_playlist(start_meta, addon, active_provider, tmdb_client, handle, plugin_instance)


def list_sources(meta_json, active_provider):
    active_provider.find_and_list_sources(meta_json)
