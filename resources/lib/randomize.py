# -*- coding: utf-8 -*-
"""RANDOMIZE selection only; playback remains owned by the normal play route."""

import random
import re
from datetime import date


# FIX PRE-EMPTIVE AND FILTERS [ISOLATED RANDOMIZE SELECTION]
def history_keys(history):
    keys = set()
    for entry in history or []:
        meta = entry.get('meta', {}) if isinstance(entry, dict) else {}
        if not isinstance(meta, dict):
            continue
        kind = meta.get('media_type')
        kind = 'tv' if kind in ('tv', 'episode') else kind
        if kind in ('tv', 'movie') and meta.get('tmdb_id'):
            keys.add((kind, str(meta['tmdb_id'])))
    return keys


def quality(title):
    words = set(re.findall(r'\w+', title.upper()))
    for height, tags in ((4320, {'8K', '4320P'}), (2160, {'4K', '2160P', '2160', 'UHD'}),
                         (1440, {'1440P', '2K'}), (1080, {'1080P', '1080', 'FHD', 'FULLHD'}),
                         (720, {'720P', '720', 'HD'})):
        if words & tags:
            return height
    return 0


def filter_sources(sources, require_dubbing, require_quality, strategy):
    filtered = []
    for source in sources:
        if not source.get('link'):
            continue
        title = str(source.get('title') or '')
        words = set(re.findall(r'\w+', title.upper()))
        # CZ alone can also describe subtitles; do not treat it as verified dubbing.
        dubbed = bool(words & {'DAB', 'DABING', 'DABBING', 'CZDAB'})
        if require_dubbing and not dubbed:
            continue
        if require_quality and quality(title) < 1080:
            continue
        filtered.append(source)
    if strategy == 'random':
        random.shuffle(filtered)
    elif strategy == 'quality':
        filtered.sort(key=lambda source: quality(str(source.get('title') or '')), reverse=True)
    return filtered


def candidate_metadata(client, candidate):
    kind, ident = candidate['media_type'], candidate['id']
    details = client.get_full_details(kind, ident)
    if not details:
        return None
    props = client._build_metadata_props(details, kind)
    props.update(tmdb_id=ident, media_type=kind)
    if kind == 'movie':
        if details.get('release_date', '') > date.today().isoformat():
            return None
        return props
    for season in sorted(details.get('seasons') or [], key=lambda s: s.get('season_number', 0)):
        number = season.get('season_number', 0)
        if number <= 0:
            continue
        data = client._fetch(f'tv/{ident}/season/{number}') or {}
        for episode in sorted(data.get('episodes') or [], key=lambda ep: ep.get('episode_number', 0)):
            air_date = episode.get('air_date') or ''
            if not air_date or air_date > date.today().isoformat() or episode.get('episode_number', 0) <= 0:
                continue
            ep_props = client._build_metadata_props(episode, 'episode')
            meta = dict(props)
            meta.update({key: value for key, value in ep_props.items() if value})
            meta.update(tmdb_id=ident, media_type='episode', tv_show_title=props.get('title', ''),
                        season=number, episode=episode['episode_number'], premiered=air_date,
                        year=air_date[:4])
            # The episode ID must never replace the show's TMDB identity for scrobbling.
            for key in ('poster', 'fanart', 'cast_full'):
                meta[key] = ep_props.get(key) or props.get(key)
            return meta
    return None


def _integer(addon, key, default, maximum):
    try:
        return max(1, min(maximum, int(addon.getSetting(key) or default)))
    except (TypeError, ValueError):
        return default


def choose(plugin, history, search, resolve, cancelled=lambda: False, progress=lambda text: None):
    addon, client = plugin.addon, plugin.tmdb_client
    if addon.getSetting('random_enabled') == 'false' or cancelled():
        return None
    seed = addon.getSetting('random_seed_type')
    kind = seed if seed in ('movie', 'tv') else 'all'
    window = 'day' if addon.getSetting('random_trending_window') == 'day' else 'week'
    pages = _integer(addon, 'random_trending_pages', 5, 20)
    attempts = _integer(addon, 'random_max_attempts', 3, 10)
    excluded = history_keys(history) if addon.getSetting('random_exclude_seen') == 'true' else set()
    candidates, seen = [], set()
    for page in range(1, pages + 1):
        if cancelled():
            return None
        progress(f'Načítám trendy: {page}/{pages}')
        data = client._fetch(f'trending/{kind}/{window}', params={'page': page}) or {}
        for item in data.get('results') or []:
            item_kind = item.get('media_type', kind)
            key = (item_kind, str(item.get('id') or ''))
            if item_kind not in ('movie', 'tv') or not item.get('id') or key in excluded or key in seen:
                continue
            seen.add(key)
            candidates.append(dict(item, media_type=item_kind))
        if page >= data.get('total_pages', pages):
            break
    random.shuffle(candidates)
    for index, candidate in enumerate(candidates[:attempts], 1):
        if cancelled():
            return None
        meta = candidate_metadata(client, candidate)
        if not meta or not meta.get('title'):
            continue
        title = meta.get('tv_show_title') if meta['media_type'] == 'episode' else meta['title']
        query = (f"{title} S{meta['season']:02d}E{meta['episode']:02d}" if meta['media_type'] == 'episode'
                 else f"{title} {meta.get('year', '')}".strip())
        progress(f'Hledám {index}/{attempts}: {query}')
        sources = filter_sources(search(query), addon.getSetting('random_require_dabing') == 'true',
                                 addon.getSetting('random_require_quality') == 'true',
                                 addon.getSetting('random_source_strategy'))
        for source in sources:
            if cancelled():
                return None
            selected_meta = dict(meta, source_title=source.get('title', title))
            if resolve(source, selected_meta):
                return source, selected_meta
    return None


def run(plugin):
    """Launch a normal plugin play URL, never resolve a non-playable menu handle."""
    import xbmc
    import xbmcgui
    from resources.lib import actions, cache_manager
    from resources.lib.utils import get_url, store_meta_in_cache
    from resources.lib.utils_logging import log
    from resources.lib.utils_notification import notify_info, notify_error

    if plugin.addon.getSetting('random_enabled') == 'false':
        notify_info('RANDOMIZE je vypnuté v nastavení.')
        return
    providers = plugin.provider_manager.get_providers_to_search()
    if not providers or not plugin.tmdb_client:
        notify_error('RANDOMIZE: není dostupný poskytovatel nebo TMDB.')
        return
    dialog = xbmcgui.DialogProgress()
    dialog.create('PLAY.ER — RANDOMIZE', 'Vybírám náhodný titul…')
    monitor = xbmc.Monitor()
    cancelled = lambda: dialog.iscanceled() or monitor.abortRequested()
    result = None
    was_cancelled = False
    try:
        def search(query):
            return actions._search_providers_parallel(
                query, providers, apply_filters=True,
                sort_priority=plugin.addon.getSetting('multi_provider_sort'))

        def resolve(source, meta):
            return actions.resolve_video(source['link'], source.get('provider'), meta,
                                         return_url_only=True, plugin_instance=plugin)

        result = choose(plugin, cache_manager.user_data_get('playback_history') or [], search, resolve,
                        cancelled=cancelled, progress=lambda text: dialog.update(0, text))
        was_cancelled = cancelled()
    except Exception as exc:
        log(f'RANDOMIZE - Chyba výběru: {type(exc).__name__}', xbmc.LOGERROR)
        notify_error('RANDOMIZE: výběr se nezdařil. Podrobnosti jsou v kodi.log.')
        return
    finally:
        dialog.close()
    if was_cancelled:
        return
    if not result:
        notify_info('RANDOMIZE: v nastaveném počtu pokusů nebyl nalezen vhodný zdroj.')
        return
    source, meta = result
    # Reuse the proven source-selection playback path, including finite episode queue.
    if meta['media_type'] == 'episode':
        meta['_play_er_tmdbh_source_search'] = True
    url = get_url(action='play', link=source['link'], provider=source.get('provider', ''),
                  meta=store_meta_in_cache(meta), live_metadata='true')
    item = xbmcgui.ListItem(label=meta['title'], path=url)
    item.setProperty('IsPlayable', 'true')
    item.setContentLookup(False)
    plugin.tmdb_client.fill_list_item(item, meta, meta['media_type'])
    xbmc.Player().play(url, item)
