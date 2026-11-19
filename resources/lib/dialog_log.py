# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_log.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 24.04.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import xbmc
import xbmcgui
import xbmcaddon


from resources.lib.utils_logging import log


from resources.lib.utils_notification import (
    notify_error
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)





def show_addon_log():

    """
    ADDON :: SHOW LOG
    -- Zobrazí filtrovaný debug log addonu v XML okně.
    """

    try:
        addon_instance = xbmcaddon.Addon("plugin.video.play_er")
        addon_path = addon_instance.getAddonInfo('path')

        try:
            from resources.lib.dialog_log_xml import PlayErDialogLogXML
        except ImportError:
            log("LOG VIEWER - Nepodařilo se najít dialog_log_xml.py", xbmc.LOGERROR)
            notify_error(f"ERROR NAČÍTANÍ ROZHRANÍ XML LOG-VIEWER", category="DIALOG", time=3000)
            #  xbmcgui.Dialog().notification("PLAY.ER", "Chyba načítání rozhraní pro LOG", xbmcgui.NOTIFICATION_ERROR)
            return

        # --- Zobrazení okna

        xml_dialog = PlayErDialogLogXML(
            "script-play_er-dialog_log.xml",
            addon_path,
            "Default",
            "1080i"
        )
        xml_dialog.doModal()
        del xml_dialog

    except Exception as e:
        log(f"LOG VIEWER - CHYBA: {e}", xbmc.LOGERROR)
        notify_error(f"ERROR CHYBA LOG-VIEWER", category="DIALOG", time=3000)
