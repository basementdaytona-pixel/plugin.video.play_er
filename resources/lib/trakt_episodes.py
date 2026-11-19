# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: trakt_episodes.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 25.04.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import threading

import xbmc
import xbmcaddon


from datetime import datetime


from resources.lib.utils_logging import log
from resources.lib import cache_manager
from resources.lib import trakt


from resources.lib.utils_notification import (
    notify_episode
)




ADDON = xbmcaddon.Addon("plugin.video.play_er")
BASE_URL = "https://api.trakt.tv"




def get_next_episodes(days=30, force_refresh=False):

    """
    Získá seznam epizod ze zvyků (my/shows) přes centrální Trakt modul, 
    který řeší 401 Unauthorized a automaticky obnovuje tokeny.
    """

    cached = cache_manager.cache_get("TRAKT", 'trakt_next_episodes')
    if cached and not force_refresh:
        return cached

    start = datetime.now().strftime("%Y-%m-%d")
    url = f"{BASE_URL}/calendars/my/shows/{start}/{int(days)}?extended=full,images"

    results =[]
    try:
        # OPRAVA: Využití centrální funkce namísto izolovaného requests.get
        r = trakt.handle_trakt_401(url, addon=ADDON, session=None)
        
        if not r or r.status_code != 200:
            log(f"TRAKT NEXT - API ERROR {r.status_code if r else 'None'} :: {url}", level=xbmc.LOGERROR)
            return[]

        data = r.json()
        for item in data:
            ep = item.get('episode')
            show = item.get('show')
            results.append({
                'show': show or {},
                'next_episode': ep,
                'last_episode': None,
                'progress': {},
                'aired': 0,
                'completed': 0,
            })

    except Exception as e:
        log(f"TRAKT NEXT - ERROR : {e}", level=xbmc.LOGERROR)
        return cached or[]

    try:
        cache_manager.cache_set("TRAKT", 'trakt_next_episodes', results)
    except Exception:
        pass

    return results



def check_new_episodes():
    # Keep the last calendar snapshot available after the short menu-cache TTL
    # expires, then fetch a fresh calendar before comparing episode IDs.
    previous = cache_manager.cache_get(
        "TRAKT", 'trakt_next_episodes', max_age=31 * 86400
    ) or []
    current = get_next_episodes(force_refresh=True)

    if not current:
        return previous

    new_eps = []
    prev_ids = set()
    for ep in previous:
        ne = ep.get("next_episode")
        if ne and isinstance(ne, dict):
            ids = ne.get("ids") or {}
            tid = ids.get("trakt")
            if tid:
                prev_ids.add(tid)

    for ep in current:
        ne = ep.get("next_episode")
        if ne and isinstance(ne, dict):
            ids = ne.get("ids") or {}
            tid = ids.get("trakt")
            if tid and tid not in prev_ids:
                new_eps.append(ep)

    for ep_data in new_eps:
        show = ep_data.get('show') or {}
        next_ep = ep_data.get('next_episode') or {}

        try:
            notify_episode(f'NOVÁ EPIZODA : {show.get("title","?")} S{next_ep.get("season",0):02d}E{next_ep.get("number",0):02d}', category="TRAKT")
        except Exception:
            pass

    return current
