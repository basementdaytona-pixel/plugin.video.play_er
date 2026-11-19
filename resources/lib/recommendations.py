"""Catalog recommendation selection, independent of Kodi menu construction."""

from resources.lib.utils_settings import get_setting_int_with_bounds, get_setting_float_with_bounds
from resources.lib import cache_manager
from resources.lib.utils_logging import log
import xbmc


def catalog_type(media_type):
    return "tv" if media_type in ("tv", "tvshow", "show", "episode", "season") else "movie"


def similar_items(tmdb_client, addon, tmdb_id, media_type):
    """Honor the configured TMDB sources, rating floor and result count."""
    source = get_setting_int_with_bounds(addon, "tmdb_similar_source", 1, 0, 2)
    limit = get_setting_int_with_bounds(addon, "tmdb_find_similar_limit", 20, 5, 50)
    minimum = get_setting_float_with_bounds(addon, "tmdb_similar_min_rating", 6.0, 0.0, 10.0)
    endpoints = ("recommendations", "similar") if source == 0 else ("recommendations",) if source == 1 else ("similar",)
    items, seen = [], set()
    for endpoint in endpoints:
        page, total_pages = 1, 1
        while page <= total_pages and len(items) < limit:
            result = tmdb_client._fetch(f"{media_type}/{tmdb_id}/{endpoint}", params={"page": page}) or {}
            for item in result.get("results", []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                item_id = str(item["id"])
                try:
                    rating = float(item.get("vote_average") or 0)
                except (TypeError, ValueError):
                    continue
                if item_id in seen or rating < minimum:
                    continue
                seen.add(item_id)
                items.append(item)
                if len(items) == limit:
                    break
            total_pages = min(int(result.get("total_pages") or 1), 10)
            page += 1
    return items


def seed_metadata(items, media_type):
    """Accept nested playback history and flat Watch Later records."""
    seeds, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = item.get("meta", item)
        if not isinstance(meta, dict) or not meta.get("tmdb_id"):
            continue
        kind = meta.get("media_type")
        if kind not in ("movie", "tv", "tvshow", "show", "episode", "season") or catalog_type(kind) != media_type:
            continue
        key = str(meta["tmdb_id"])
        if key not in seen:
            seen.add(key)
            seeds.append(meta)
    return seeds


def recommendations_from_seeds(tmdb_client, seeds, media_type, seed_limit=5, result_limit=None, excluded_ids=()):
    results, seen = [], set(excluded_ids)
    for seed in seeds[:seed_limit]:
        try:
            items = tmdb_client.get_recommendations_raw(media_type, seed["tmdb_id"]) or []
            for item in items:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                key = str(item["id"])
                if key not in seen:
                    seen.add(key)
                    results.append(dict(item, tmdb_id=item["id"], media_type=media_type))
                    if result_limit is not None and len(results) >= result_limit:
                        return results
        except Exception as exc:
            log(f"RECOMMENDATIONS - Nelze načíst doporučení: {exc}", xbmc.LOGWARNING)
    return results


def _recommendations_for_source(plugin, source, media_type, quick=False):
    source_items = cache_manager.user_data_get(source) or []
    seeds = seed_metadata(source_items, media_type)
    options = {"seed_limit": 1 if quick else 5, "result_limit": 1 if quick else None}
    # These settings explicitly govern PLAYBACK history, not Watch Later.
    if source == "playback_history":
        prefix = "watch_movies" if media_type == "movie" else "watch_series"
        if not quick:
            options["seed_limit"] = get_setting_int_with_bounds(plugin.addon, prefix + "_seed_limit", 5, 1, 10)
            options["result_limit"] = get_setting_int_with_bounds(plugin.addon, prefix + "_max_recommendations", 30, 5, 50)
        if plugin.addon.getSettingBool(prefix + "_skip_watched"):
            options["excluded_ids"] = {str(meta["tmdb_id"]) for meta in seeds}
    return recommendations_from_seeds(plugin.tmdb_client, seeds, media_type, **options)


def list_seed_recommendations(plugin, source, media_type, action):
    results = _recommendations_for_source(plugin, source, media_type)
    plugin.tmdb_client.list_items({"results": results, "total_pages": 1}, media_type, 1, action)


def quick_play_seed_recommendation(plugin, source, media_type):
    from resources.lib import actions

    results = _recommendations_for_source(plugin, source, media_type, quick=True)
    if not results:
        return
    tmdb_id = results[0]["id"]
    if media_type == "tv":
        details = plugin.tmdb_client.get_full_details("tv", tmdb_id)
        props = plugin.tmdb_client._build_metadata_props(details, "tv") if details else {}
        query = f"{props.get('title', '')} S01E01" if props.get('title') else ""
    else:
        props = plugin.tmdb_client.get_movie_details_raw(tmdb_id) or {}
        query = props.get("title", "")
    if query:
        actions.search(query, plugin, resolve_first=True)
