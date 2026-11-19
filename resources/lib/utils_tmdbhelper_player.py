# -*- coding: utf-8 -*-

########################################################################################
#
# Addon: plugin.video.play_er
# Module: utils_tmdbhelper_player.py
# Author: Mau!X ER
# Created on: 11.11.2026
# Last edit on: 11.11.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
# Description: Helper for TMDBHelper player actions waiting for modal dialog dismissal
#
########################################################################################

import sys
import urllib.parse

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib.utils_tmdbhelper import normalise_episode_numbers, normalise_tmdb_id
from resources.lib.utils_logging import log
from resources.lib.utils_notification import notify_info, notify_warning, notify_error
from resources.lib.utils_settings import get_setting_bool, get_setting_int_with_bounds






def notify(addon, message, level=xbmcgui.NOTIFICATION_INFO, time_ms=3500):

    """
    NOTIFICATION  ::  KODI UI
    -- Zobrazí nativní toast notifikaci přímo v rozhraní Kodi.
    """

    # Keep the entry point used by the player bridge; notification settings belong
    # to PLAY.ER, including when no addon instance was passed by the caller.
    notifier = notify_error if level == xbmcgui.NOTIFICATION_ERROR else (
        notify_warning if level == xbmcgui.NOTIFICATION_WARNING else notify_info
    )
    notifier(str(message), category="TMDB-HELP", time=time_ms, sound=True)






def wait_modal_and_activate(params, plugin_instance=None):

    """
    MODAL DIALOG  ::  WATCHDOG
    -- Wait for active modal dialogs to close based on settings, then activate videos window.
    """

    if plugin_instance:
        addon = plugin_instance.addon
    else:
        try:
            addon = xbmcaddon.Addon("plugin.video.play_er")
        except Exception:
            addon = xbmcaddon.Addon()

    tmdb_id = params.get("tmdb_id")
    media_type = params.get("media_type", "episode")
    season = params.get("season")
    episode = params.get("episode")
    mode = params.get("mode", "search")

    try:
        tmdb_id = normalise_tmdb_id(tmdb_id)
        if media_type not in ("movie", "episode", "tv", "show"):
            raise ValueError("Nepodporovaný typ média")
        if mode not in ("search", "play", "smart_play"):
            raise ValueError("Nepodporovaný režim přehrávače")
    except ValueError as exc:
        log(f"[ TMDBH - PLAYER ] INVALID : {exc}", xbmc.LOGWARNING)
        notify(addon, f"ERROR : {exc}", xbmcgui.NOTIFICATION_ERROR, 3000)
        return

    query = {
        "action": "tmdbh_bridge",
        "tmdb_id": str(tmdb_id),
        "media_type": media_type,
        "mode": mode,
    }
    if media_type == "episode":
        try:
            query["season"], query["episode"] = normalise_episode_numbers(season, episode)
        except ValueError as exc:
            notify(addon, f"ERROR : {exc}", xbmcgui.NOTIFICATION_ERROR, 3000)
            return

    url = "plugin://plugin.video.play_er/?" + urllib.parse.urlencode(query)



    # ---  Načtení parametrů ze settings.xml  ------------------------------------------------------------------------- #

    enabled = get_setting_bool(addon, "tmdbh_modal_wait_enable", default=True)
    timeout_sec = get_setting_int_with_bounds(addon, "tmdbh_modal_wait_timeout", default=5, min_val=1, max_val=15)
    interval_ms = get_setting_int_with_bounds(addon, "tmdbh_modal_wait_interval", default=50, min_val=25, max_val=500)
    fallback_open = get_setting_bool(addon, "tmdbh_modal_wait_fallback_open", default=True)

    # ----------------------------------------------------------------------------------------------------------------- #


    if not enabled:
        xbmc.executebuiltin(f"ActivateWindow(Videos,{url},return)")
        log(f"[ TMDBH - PLAYER ] DISABLED : Modal wait disabled, activating : {url}", xbmc.LOGINFO)
        return

    step_sec = interval_ms / 1000.0
    max_steps = max(1, int((timeout_sec * 1000) / interval_ms))
    monitor = xbmc.Monitor()

    for _ in range(max_steps):
        if monitor.abortRequested():
            return
        if not xbmc.getCondVisibility("System.HasActiveModalDialog"):
            xbmc.executebuiltin(f"ActivateWindow(Videos,{url},return)")
            log(f"[ TMDBH - PLAYER ] ACTIVATE : {url}", xbmc.LOGINFO)
            break
        if monitor.waitForAbort(step_sec):
            return
    else:
        log(f"[ TMDBH - PLAYER ] TIMEOUT : Modální dialog stále aktivní po {timeout_sec}s", xbmc.LOGWARNING)

        if fallback_open:
            notify(
                addon,
                f"TIMEOUT ({timeout_sec}s) vypršel > okno otevírám vynuceně ...",
                xbmcgui.NOTIFICATION_WARNING,
                3000,
            )
            xbmc.executebuiltin(f"ActivateWindow(Videos,{url},return)")
        else:
            notify(
                addon,
                f"TIMEOUT ({timeout_sec}s) vypršel > dialog nezmizel ...",
                xbmcgui.NOTIFICATION_ERROR,
                4000,
            )






if __name__ == "__main__":

    # ---  Podpora přímého volání přes RunScript  --------------------------------------------------------------------- #

    if len(sys.argv) >= 4:
        p = {
            "tmdb_id": sys.argv[1],
            "media_type": "episode",
            "season": sys.argv[2],
            "episode": sys.argv[3],
            "mode": "search",
        }
    elif len(sys.argv) >= 2:
        p = {"tmdb_id": sys.argv[1], "media_type": "movie", "mode": "search"}
    else:
        p = {}
    wait_modal_and_activate(p)
