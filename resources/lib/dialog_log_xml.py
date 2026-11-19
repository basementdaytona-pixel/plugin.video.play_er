# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_log_xml.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 24.04.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.utils_logging import log

from resources.lib.utils_notification import (
    notify_error,
    notify_info
)

from resources.lib.utils_theme import (
    Colors,
    apply_dialog_theme,
    Icons
)



ACTION_PREVIOUS_MENU =[9, 92, 110, 284, 513]



class PlayErDialogLogXML(xbmcgui.WindowXMLDialog):

    """
    CLASS :: XML LOG
    """

    def __new__(cls, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        return super(PlayErDialogLogXML, cls).__new__(cls, xmlFilename, scriptPath, defaultSkin, defaultRes)

    def __init__(self, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        super().__init__()
        self.raw_lines =[]

    def onInit(self):
        apply_dialog_theme(self)
        self.list_ctrl = self.getControl(1000)
        self.load_and_filter_log()


    def load_and_filter_log(self):

        """
        FILTER :: LOG
        -- Načte Kodi log, vyfiltruje addon a obarví řádky.
        """

        self.list_ctrl.reset()
        self.raw_lines =[]

        # --- Korektní cesta pro Kodi 19+

        log_path = xbmcvfs.translatePath('special://logpath/kodi.log')

        if not xbmcvfs.exists(log_path):
            li = xbmcgui.ListItem("[COLOR red]Log soubor nebyl nalezen na obvyklém místě[/COLOR]")
            self.list_ctrl.addItem(li)
            return

        try:
            # --- Čtení s chráněným encodingem proti pádům
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if 'plugin.video.play_er' in line or 'PLAY.ER' in line:
                        self.raw_lines.append(line.strip())

            # --- Omezení pro UI na 1000 řádků z důvodu plynulosti GUI
            recent_lines = self.raw_lines[-1000:]

            if not recent_lines:
                self.list_ctrl.addItem(xbmcgui.ListItem("[COLOR gray]Nebyly nalezeny žádné záznamy doplňku[/COLOR]"))
                return

            # --- BULK ADD OPTIMALIZACE PRO EXTRÉMNÍ RYCHLOST VYKRESLENÍ

            list_items =[]
            for line in recent_lines:
                if 'ERROR' in line or 'error' in line.lower() or 'EXCEPTION' in line:
                    color = "red"
                elif 'WARNING' in line or 'warning' in line.lower():
                    color = "orange"
                elif 'DEBUG' in line:
                    color = "dimgrey"
                else:
                    color = None

                list_items.append(xbmcgui.ListItem(f"[COLOR {color}]{line}[/COLOR]" if color else line))

            self.list_ctrl.addItems(list_items)

            # --- Focus na nejnovější  ( poslední )  řádek

            self.list_ctrl.selectItem(self.list_ctrl.size() - 1)

            # --- OCHRANA PROTI "asked to focus, but it can't" ERRORU V KODI

            xbmc.sleep(100)
            try:
                self.setFocusId(1000)
            except Exception:
                pass

        except Exception as e:
            self.list_ctrl.addItem(xbmcgui.ListItem(f"[COLOR red]Chyba při čtení logu : {e}[/COLOR]"))


    def onClick(self, controlId):
        if controlId == 2001:
            self.close()
        elif controlId == 2002:
            self.load_and_filter_log()
            notify_info(f"INFO LOG BYL OBNOVEN", category="LOGGING", time=3000)
        elif controlId == 2003:
            self.export_log()


    def export_log(self):

        """
        EXPORT :: TXT LOG
        -- Vyexportuje vyfiltrovaný addon log do samostatného TXT souboru.
        """

        if not self.raw_lines:
            notify_info(f"INFO NENÍ CO EXPORTOVAT!", category="LOGGING", time=3000)
            return

        try:
            export_dir = xbmcvfs.translatePath('special://userdata/PLAY-DATA/DEBUG/')
            if not xbmcvfs.exists(export_dir):
                xbmcvfs.mkdirs(export_dir)

            export_path = os.path.join(export_dir, 'FILTERED-LOG.TXT')

            with open(export_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(self.raw_lines))

            notify_info(f"INFO LOG BYL ULOŽEN : {export_path}", category="LOGGING", time=3000)
        except Exception as e:
            xbmc.log(f"CHYBA EXPORTU LOGU : {e}", xbmc.LOGERROR)
            notify_error(f"ERROR CHYBA PŘI EXPORTU", category="LOGGING", time=3000)


    def onAction(self, action):
        if action.getId() in ACTION_PREVIOUS_MENU:
            self.close()
