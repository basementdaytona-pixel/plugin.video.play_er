# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_metrics_xml.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import time

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.metrics_manager import METRICS
from resources.lib.utils_theme import Colors, apply_dialog_theme
from resources.lib.utils_files import SafeVFSFile
from resources.lib.utils_logging import log


from resources.lib.utils_notification import (
    notify_error,
    notify_info
)




ACTION_PREVIOUS_MENU = [9, 92, 110, 284, 513]




class PlayErDialogMetricsXML(xbmcgui.WindowXMLDialog):

    def __new__(cls, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        return super(PlayErDialogMetricsXML, cls).__new__(cls, xmlFilename, scriptPath, defaultSkin, defaultRes)

    def __init__(self, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        super().__init__()
        self.metrics_data = kwargs.get('metrics_data', [])
        self.addon = kwargs.get('addon')
        self.orchestrator = kwargs.get('orchestrator')
        self.raw_metrics = kwargs.get('raw_metrics', {})
        self.list_ctrl = None

    def onInit(self):
        apply_dialog_theme(self)
        self.list_ctrl = self.getControl(1000)
        self.populate()

    def populate(self):
        self.list_ctrl.reset()
        list_items = []
        for item in self.metrics_data:
            li = xbmcgui.ListItem(item['label'])
            li.setProperty('Value', str(item['value']))
            if item.get('is_header'):
                li.setProperty('IsHeader', 'true')
            list_items.append(li)

        self.list_ctrl.addItems(list_items)
        xbmc.sleep(100)
        try:
            self.setFocusId(1000)
        except Exception:
            pass

    def onClick(self, controlId):
        if controlId == 2001:
            self.close()
        elif controlId == 2002:
            self.toggle_metrics()
        elif controlId == 2003:
            self.export_metrics()

    def toggle_metrics(self):
        try:
            current_state = self.addon.getSettingBool('metrics_enabled')
            new_state = not current_state

            self.addon.setSettingBool('metrics_enabled', new_state)

            if self.orchestrator:
                self.orchestrator.set_metrics_enabled(new_state)

            state_text = "ZAPNUTO" if new_state else "VYPNUTO"
            notify_info(f"INFO SBĚR METRIK : {state_text}", category="METRICS", time=3000)

            self.close()
            xbmc.executebuiltin('RunPlugin(plugin://plugin.video.play_er/?action=show_metrics)')
        except Exception as e:
            xbmc.log(f"METRICS TOGGLE ERROR : {e}", xbmc.LOGERROR)

    def export_metrics(self):
        try:
            dlg = xbmcgui.Dialog()
            choice = dlg.yesnocustom(
                heading=f"[COLOR {Colors.ORANGE}] ○  EXPORTOVAT DATA  ○ [/COLOR]",
                message="Vyberte formát pro export diagnostických dat :",
                customlabel="[ JSON ]",
                yeslabel="[ TEXT ]",
                nolabel="[ ZRUŠIT ]"
            )

            if choice == 0:
                return

            if choice == 2:
                ts = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
                path = f'special://userdata/DATA--PLAY/DEBUG/ORCHESTRATOR-METRICS-SNAPSHOT---{ts}.JSON'
                exported = METRICS.export(path)
                if exported:
                    notify_info(f"INFO EXPORT BYL ÚSPĚŠNÝ : {exported}", category="METRICS", time=3000)
                else:
                    notify_error("INFO EXPORT JSON DAT SELHAL", category="METRICS", time=3000)
            elif choice == 1:
                if self.orchestrator and self.raw_metrics:
                    export_dir = xbmcvfs.translatePath('special://userdata/DATA--PLAY/DEBUG/')
                    if not xbmcvfs.exists(export_dir):
                        xbmcvfs.mkdirs(export_dir)
                    export_path = xbmcvfs.translatePath('special://userdata/DATA--PLAY/DEBUG/ORCHESTRATOR-METRICS.TXT')
                    with SafeVFSFile(export_path, 'w') as f:
                        for k in sorted(self.raw_metrics.keys()):
                            f.write(f"{k}: {self.raw_metrics.get(k, 0)}\n")
                    notify_info(f"INFO EXPORT BYL ÚSPĚŠNÝ : {export_path}", category="METRICS", time=3000)
                else:
                    notify_error("INFO EXPORT TXT SELHAL - ŽÁDNÁ DATA", category="METRICS", time=3000)
        except Exception as e:
            xbmc.log(f"METRICS EXPORT ERROR: {e}", xbmc.LOGERROR)

    def onAction(self, action):
        if action.getId() in ACTION_PREVIOUS_MENU:
            self.close()
