# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_stream.py
# Author: Mau!X ER
# Created on: 22.05.2025
# Last edit on: 23.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import json
import time

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin


from urllib.parse import quote


from resources.lib.utils_logging import log
from resources.lib.stream_state import get_streams, attach_subtitles

from resources.lib.utils_notification import (
    notify_error,
    notify_info
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)







def show_stream_menu(plugin_instance):
    win = xbmcgui.Window(10000)

    # 1. ZABRÁNĚNÍ VYPNUTÍ MONITORU

    xbmc.executebuiltin("WakeIdle")

    # 2. ABSOLUTNÍ OCHRANA PROTI PÁDU KODI (Dvojité spuštění)

    is_open = win.getProperty("play_er.stream_menu_is_open")
    if is_open == "true":
        log("DIALOG STREAM - Blokováno: Dialog již běží (Ochrana proti pádu)", xbmc.LOGWARNING)
        try: xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, updateListing=False, cacheToDisc=False)
        except: pass
        return

    last_closed = win.getProperty("play_er.stream_menu_last_closed")
    current_time_ts = time.time()
    
    # Kodi potřebuje zhruba 1 vteřinu na dokončení animace a uvolnění paměti starého okna

    if last_closed and (current_time_ts - float(last_closed)) < 1.0:
        log("DIALOG STREAM - Blokováno: Ochrana proti pádu (Kodi GUI Animace starého okna ještě běží)", xbmc.LOGWARNING)
        try: xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, updateListing=False, cacheToDisc=False)
        except: pass
        return

    # Uzamkneme paměť pro tuto session okna

    win.setProperty("play_er.stream_menu_is_open", "true")
    next_action = None

    try:
        xbmc.executebuiltin("Dialog.Close(busydialog)")

        player = xbmc.Player()
        if not player.isPlayingVideo():
            notify_info("INFO PŘEHRÁVAČ AKTUÁLNĚ NEBĚŽÍ", category="SYSTEM")
            return

        # 3. EXTRAKCE DAT Z AKTUÁLNĚ HRAJÍCÍ POLOŽKY

        playing_item = player.getPlayingItem()
        playing_file = player.getPlayingFile()
        current_meta_id = playing_item.getProperty("play_er.meta_id")

        streams = get_streams(playing_item)
        if not streams:
            notify_error("ERROR KVALITY STREAMU NEJSOU K DISPOZICI", category="SYSTEM")
            return

        addon_instance = xbmcaddon.Addon(id="plugin.video.play_er")
        
        try:
            from resources.lib.dialog_stream_xml import StreamDashboardXML
        except ImportError:
            log("DIALOG STREAM - Nepodařilo se naimportovat StreamDashboardXML", xbmc.LOGERROR)
            return

        # 4. OTEVŘENÍ OKNA
        xml_dialog = StreamDashboardXML(
            "script-play_er-dialog_stream.xml",
            addon_instance.getAddonInfo('path'),
            "Default",
            "1080i",
            streams=streams
        )
        
        log("DIALOG STREAM - OTEVÍRÁM OKNO  ( doModal )", xbmc.LOGINFO)
        xml_dialog.doModal()

        selected_url = xml_dialog.selected_url
        next_action = xml_dialog.next_action

        # --- Počkání na ukončení animace okna před zásahem do paměti a GUI

        xbmc.sleep(300)
        del xml_dialog

        if not selected_url:
            log("DIALOG STREAM - Výběr zrušen uživatelem", xbmc.LOGINFO)
            return

        # Playback continues while the modal is open; resume at its current time.
        try:
            if not player.isPlayingVideo() or player.getPlayingFile() != playing_file:
                return
        except RuntimeError:
            return
        try:
            current_play_time = player.getTime()
        except Exception:
            current_play_time = 0.0


        # ============== PŘÍPRAVA METADAT ==============


        meta = {}
        if current_meta_id:
            from resources.lib.utils import get_meta_from_cache
            meta = get_meta_from_cache(current_meta_id)
            if isinstance(meta, str):
                try: meta = json.loads(meta)
                except: meta = {}

        notify_info("INFO ON-THE-FLY PŘEPÍNÁNÍ STREAMU ...", category="STREAM", time=2500)

        # --- FLAG : Informujeme Trakt monitor, že se nejedná o konec, ale o Seamless Switch!

        win.setProperty("play_er.seamless_switching", "true")

        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"
        referer = "https://prehraj.to/"
        accept = "video/mp4,video/*,*/*"
        clean_url = selected_url.split('|')[0]
        final_url = "{0}|User-Agent={1}&Referer={2}&Accept={3}".format(clean_url, quote(ua), quote(referer), quote(accept))

        li = xbmcgui.ListItem(path=final_url)
        li.setContentLookup(False)
        li.setProperty('StartOffset', str(current_play_time))
        
        if meta:
            try:
                plugin_instance.tmdb_client.fill_list_item(li, meta, meta.get('media_type', 'movie'))
                li.setProperty('play_er.media_type', meta.get('media_type', 'movie'))
            except Exception as e: 
                log(f"STREAM SWITCH - Chyba metadat : {e}", xbmc.LOGWARNING)

        # Playback identity and subtitles remain valid when metadata expires.
        for key in ('play_er.link', 'play_er.provider', 'play_er.view_video_id', 'play_er.view_binding',
                    'play_er.meta_id', 'play_er.media_type', 'play_er.source_list', 'play_er.trakt_id'):
            value = playing_item.getProperty(key)
            if value:
                li.setProperty(key, value)
        try:
            attach_subtitles(li, playing_item)
        except Exception as e:
            log(f"STREAM SWITCH - Chyba titulků : {e}", xbmc.LOGWARNING)


        # ============== HYBRIDNÍ PŘEPÍNAČ (ANTI-CRASH) ==============


        switch_count = int(win.getProperty("play_er.switch_count") or "0")
        switch_count += 1
        win.setProperty("play_er.switch_count", str(switch_count))

        playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
        pos = playlist.getposition()

        if switch_count == 1:

            # --- První přepnutí = původní BLESKOVÝ REŽIM  ( nejrychlejší start )

            log("DIALOG STREAM - Bleskový režim player.play (Switch 1)", xbmc.LOGINFO)
            player.play(final_url, listitem=li)
        else:

            # --- Druhé a další přepnutí = Posunutí skrze Playlist s PlayerControl(Next)

            log(f"DIALOG STREAM - Plynulý posun v playlistu (Switch {switch_count}, Pozice: {pos})", xbmc.LOGINFO)
            if pos >= 0:
                playlist.add(url=final_url, listitem=li, index=pos + 1)
                xbmc.executebuiltin("PlayerControl(Next)")
            else:

                # --- Ochranný fallback, kdyby se pozice ztratila

                playlist.add(url=final_url, listitem=li)
                player.play(playlist, windowed=False, startpos=max(0, playlist.size() - 1))

        # --- Fallback pojistka vrácení času pro případ prodlevy bufferingu

        for _ in range(50):
            if player.isPlayingVideo():
                if player.getTime() < 5.0 and current_play_time > 10.0:
                    player.seekTime(current_play_time)
                break
            xbmc.sleep(100)

    finally:

        # 5. ABSOLUTNÍ ODBLOKOVÁNÍ PAMĚTI PŘI UKONČENÍ

        win.clearProperty("play_er.stream_menu_is_open")
        win.setProperty("play_er.stream_menu_last_closed", str(time.time()))
        
        # OPRAVA: succeeded=False zabrání Kodi navigovat do prázdné složky

        try:
            xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False, updateListing=False, cacheToDisc=False)
        except Exception:
            pass

        # Akce z tlačítek skinu se spouští až po zavření a odblokování dialogu.
        try:
            if next_action == "settings":
                xbmc.executebuiltin("Addon.OpenSettings(plugin.video.play_er)")
            elif next_action == "menu":
                from resources.lib import plugin as plugin_module
                plugin_module._display_player_menu({})
        except Exception as e:
            log(f"DIALOG STREAM - Nepodařilo se spustit akci '{next_action}': {e}", xbmc.LOGERROR)

        # POJISTKA: Natvrdo přepne zobrazení Kodi zpět na přehrávač (pokud běží video)

        try:
            if not next_action and xbmc.Player().isPlayingVideo():
                xbmc.executebuiltin("ActivateWindow(fullscreenvideo)")
        except Exception:
            pass
