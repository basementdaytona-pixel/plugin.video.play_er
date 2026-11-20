# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: series_manager.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import re
import time

import xbmc

from resources.lib.utils_filter import FilterUtils
from resources.lib.utils_logging import log
from resources.lib import cache_manager


from resources.lib.utils_settings import (
    get_setting_float_with_bounds
)





EPISODE_PATTERNS = [
    r"(?:s|serie|série)\s?(\d{1,2})\s?(?:e|x|ep|epizoda|díl)\s?(\d{1,3})",
    r"(\d+)x(\d+)",
    r"(\d+)\.\s*série\s*(\d+)\.\s*(?:díl|epizoda|ep)",
    r"[Ee]pisode\s*(\d+)",
    r"[Ee]p\s*(\d+)",
    r"[Ee](\d+)",
    r"(\d+)\.\s*díl",
    r"(\d+)\.\s*epizoda",
    r"\s(\d+)\.\s",
]





class SeriesManager:

    """
    CLASS :: SERIES MANAGER (SQL BACKEND)
    -- Správa seriálů s využitím centrální SQL cache (cache_manager).
    """

    def __init__(self, addon, profile, tmdb_client=None):
        self.addon = addon
        self.tmdb_client = tmdb_client
        self.filter_utils = FilterUtils(addon)
        self.manager_search_delay = get_setting_float_with_bounds(addon, "manager_search_delay", 0.0, 0.0, 10.0)

    def search_series(self, series_name, providers=None):
        if not providers:
            log("TV-MANAGER - Varování : Nebyli předáni žádní provideři", level=xbmc.LOGWARNING)
            return None

        search_delay = self.manager_search_delay
        series_name_upper = series_name.upper()
        series_data = {
            "name": series_name_upper,
            "last_updated": xbmc.getInfoLabel("System.Date"),
            "seasons": {},
            "tmdb_id": None
        }

        if self.tmdb_client:
            try:
                search_res = self.tmdb_client.search_raw(series_name, media_type="tv")
                if search_res and search_res.get("results"):
                    top_hit = search_res["results"][0]
                    series_data["tmdb_id"] = top_hit.get("id")
            except Exception:
                pass

        search_queries = [series_name, f"{series_name} season", f"{series_name} s01", f"{series_name} epizoda"]
        found_episodes = {}
        seen_filenames = set()

        for provider in providers:
            provider_name = provider.__class__.__name__
            cookies = None
            if getattr(provider, 'search_handles_auth', False) is not True and hasattr(provider, 'get_premium_cookies'):
                cookies = provider.get_premium_cookies()

            for query in search_queries:
                if search_delay > 0:
                    time.sleep(search_delay)
                try:
                    raw_results = provider.search_sources(query, cookies=cookies, apply_filters=False)

                    filtered_results = self.filter_utils.apply_filters(
                        raw_results,
                        enable_setting_id="enable_filtering",
                        include_setting_ids=["filter_global"],
                        exclude_setting_ids=["exclude_global"]
                    )

                    for item in filtered_results:
                        unique_id = f"{item['title']}_{item.get('size_str', '0')}"
                        if unique_id in seen_filenames:
                            continue
                        seen_filenames.add(unique_id)

                        season_num, episode_num = self._detect_episode_info(item["title"], series_name)

                        if season_num is not None and episode_num is not None:
                            key = f"{season_num}_{episode_num}"
                            quality = self._detect_quality(item["title"])
                            quality_score = self._get_quality_score(quality)

                            include_keywords = []
                            val = self.addon.getSetting("filter_global")
                            if val:
                                include_keywords.extend([k.strip().lower() for k in val.split() if k.strip()])

                            matches = sum(1 for k in include_keywords if k in item["title"].lower())
                            final_score = quality_score + (matches * 20)

                            stream_info = {
                                "name": item["title"],
                                "ident": item["link"],
                                "size": item.get("size_str", "0.00 GB"),
                                "provider": provider_name,
                                "quality": quality,
                                "quality_score": final_score
                            }
                            if key not in found_episodes:
                                found_episodes[key] = []
                            found_episodes[key].append(stream_info)
                except Exception:
                    pass

        for key, streams in found_episodes.items():
            season_num, episode_num = map(int, key.split('_'))
            season_str, episode_str = str(season_num), str(episode_num)

            streams.sort(key=lambda x: x["quality_score"], reverse=True)
            best_stream = streams[0]

            if season_str not in series_data["seasons"]:
                series_data["seasons"][season_str] = {}
            series_data["seasons"][season_str][episode_str] = {
                "name": best_stream["name"],
                "ident": best_stream["ident"],
                "size": best_stream["size"],
                "quality": best_stream["quality"],
                "provider": best_stream["provider"],
                "added_timestamp": time.time(),
                "streams": streams
            }

        self._save_series_data(series_name, series_data)
        return series_data

    def update_active_stream(self, series_name, season_num, episode_num, stream_index):
        series_data = self.load_series_data(series_name)
        s_str, e_str = str(season_num), str(episode_num)
        if (not series_data or s_str not in series_data["seasons"] or e_str not in series_data["seasons"][s_str]):
            return False

        ep_data = series_data["seasons"][s_str][e_str]
        streams = ep_data.get("streams", [])
        if stream_index < 0 or stream_index >= len(streams):
            return False

        sel = streams[stream_index]
        ep_data.update({
            "name": sel["name"],
            "ident": sel["ident"],
            "size": sel["size"],
            "quality": sel["quality"],
            "provider": sel["provider"]
        })
        self._save_series_data(series_name, series_data)
        return True

    def _get_quality_score(self, quality):
        scores = {"4k": 10, "2160p": 10, "1080p": 8, "720p": 6, "480p": 4, "sd": 2, "unknown": 1}
        return scores.get(quality, 1)

    def _detect_quality(self, filename):
        fn = filename.lower()
        if any(x in fn for x in ["2160p", "4k", "uhd"]):
            return "4k"
        if "1080p" in fn or "full hd" in fn:
            return "1080p"
        elif "720p" in fn or "hd" in fn:
            return "720p"
        elif "480p" in fn or "sd" in fn:
            return "480p"
        return "unknown"

    def _detect_episode_info(self, filename, series_name):
        clean_name = filename.lower()
        for pattern in EPISODE_PATTERNS:
            match = re.search(pattern, clean_name)
            if match and match.lastindex == 2:
                return int(match.group(1)), int(match.group(2))

        series_pattern = re.escape(series_name.lower()).replace(r"\ ", r"[\s\.\-_]+")
        name_removed = re.sub(series_pattern, "", clean_name).strip()
        simple_ep_match = re.search(r"(?:^|[\s\.\-_])(\d{1,3})(?:[\s\.\-_]|$|díl|ep)", name_removed)
        if simple_ep_match:
            ep_num = int(simple_ep_match.group(1))
            if ep_num < 100:
                season_match = re.search(r"(?:season|série|s)(\d+)", clean_name)
                return int(season_match.group(1)) if season_match else 1, ep_num
        return None, None

    def _save_series_data(self, series_name, series_data):
        safe_name = self._safe_filename(series_name)
        cache_manager.cache_set("SERIES_DB", safe_name, series_data)

    def load_series_data(self, series_name):
        safe_name = self._safe_filename(series_name)
        return cache_manager.cache_get("SERIES_DB", safe_name, max_age=cache_manager.TTL_USER_DATA)

    def get_all_series(self):
        all_series_data = cache_manager.get_all_from_section("SERIES_DB")
        series_list = []
        for data in all_series_data:
            if isinstance(data, dict) and "name" in data:
                safe_name = self._safe_filename(data["name"])
                series_list.append({
                    "name": data["name"],
                    "safe_name": safe_name,
                    "tmdb_id": data.get("tmdb_id")
                })
        series_list.sort(key=lambda x: x["name"])
        return series_list

    def _safe_filename(self, name):
        return re.sub(r"[^\w\-_\. ]", "", name).strip().lower().replace(" ", "_")

    def delete_episode(self, series_name, season_num, episode_num):
        series_data = self.load_series_data(series_name)
        if not series_data:
            return False
        s, e = str(season_num), str(episode_num)
        if s in series_data["seasons"] and e in series_data["seasons"][s]:
            del series_data["seasons"][s][e]
            if not series_data["seasons"][s]:
                del series_data["seasons"][s]
            if not series_data["seasons"]:
                self.delete_series(series_name)
            else:
                self._save_series_data(series_name, series_data)
            return True
        return False

    def delete_season(self, series_name, season_num):
        series_data = self.load_series_data(series_name)
        if not series_data:
            return False
        s = str(season_num)
        if s in series_data["seasons"]:
            del series_data["seasons"][s]
            if not series_data["seasons"]:
                self.delete_series(series_name)
            else:
                self._save_series_data(series_name, series_data)
            return True
        return False

    def delete_series(self, series_name):
        safe = self._safe_filename(series_name)
        try:
            cache_manager.cache_set("SERIES_DB", safe, {})
            cache_manager.cache_set("WATCHED_DB", safe, {})
            return True
        except Exception:
            return False

    def mark_episode_watched(self, series_name, season_num, episode_num):
        w_data = self._load_watched_data(series_name)
        if not w_data or not isinstance(w_data, dict):
            w_data = {"series_name": series_name.upper(), "watched": {}}
        if "watched" not in w_data:
            w_data["watched"] = {}

        s, e = str(season_num), str(episode_num)
        if s not in w_data["watched"]:
            w_data["watched"][s] = {}
        w_data["watched"][s][e] = {"watched_timestamp": time.time(), "watched": True}
        self._save_watched_data(series_name, w_data)
        return True

    def is_episode_watched(self, series_name, season_num, episode_num):
        w_data = self._load_watched_data(series_name)
        if not w_data or not isinstance(w_data, dict):
            return False
        if "watched" not in w_data:
            return False
        s, e = str(season_num), str(episode_num)
        try:
            return bool(s in w_data["watched"] and e in w_data["watched"][s] and w_data["watched"][s][e].get("watched", False))
        except Exception:
            return False

    def _save_watched_data(self, series_name, data):
        safe = self._safe_filename(series_name)
        cache_manager.cache_set("WATCHED_DB", safe, data)

    def _load_watched_data(self, series_name):
        safe = self._safe_filename(series_name)
        return cache_manager.cache_get("WATCHED_DB", safe, max_age=cache_manager.TTL_USER_DATA)

    def mark_episode_unwatched(self, series_name, season_num, episode_num):
        w_data = self._load_watched_data(series_name)
        if not w_data:
            return True
        s, e = str(season_num), str(episode_num)
        if s in w_data["watched"] and e in w_data["watched"][s]:
            del w_data["watched"][s][e]
            if not w_data["watched"][s]:
                del w_data["watched"][s]
            self._save_watched_data(series_name, w_data)
        return True
