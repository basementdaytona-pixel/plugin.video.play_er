# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_menu_xml.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 24.04.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import xbmc
import xbmcgui

from resources.lib.utils_theme import apply_dialog_theme



ACTION_PREVIOUS_MENU =[9, 92, 110, 284, 513]



class PlayErDialogMenuXML(xbmcgui.WindowXMLDialog):

    def __new__(cls, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        return super(PlayErDialogMenuXML, cls).__new__(cls, xmlFilename, scriptPath, defaultSkin, defaultRes)

    def __init__(self, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        super().__init__()
        self.actions = kwargs.get('actions',[])
        self.dialog_title = kwargs.get('dialog_title', '')
        self.meta_dict = kwargs.get('meta_dict') or {}
        self.poster = kwargs.get('poster', '')

        self.selected_choice = -1
        self.initial_selection = kwargs.get('selected_index', 0)
        self.list_control = None


    def onInit(self):
        apply_dialog_theme(self)

        # --- Vyčištění tagů pro čistý nadpis

        clean_title = self.dialog_title.replace('[B]', '').replace('[/B]', '')
        self.setProperty('DialogTitle', clean_title)
        self.setProperty('MediaPoster', self.poster if self.poster else 'DefaultVideo.png')
        self.setProperty('MediaPlot', self.meta_dict.get('plot', 'Žádný popis není k dispozici'))

        self.populate_list()


    def populate_list(self):
        self.list_control = self.getControl(1000)
        self.list_control.reset()

        # --- BULK ADD OPTIMALIZACE

        list_items =[]
        for action in self.actions:
            li = xbmcgui.ListItem(_sf_cm_label(action.get('label', ''), action.get('plugin_url') or action.get('action', '')))

            if action.get('action') == 'stay':
                li.setProperty('IsHeader', 'true')
            else:
                li.setProperty('IsHeader', 'false')

            list_items.append(li)

        # --- Přidání všeho najednou

        self.list_control.addItems(list_items)
        if list_items:
            index = self.initial_selection if isinstance(self.initial_selection, int) else 0
            self.list_control.selectItem(max(0, min(index, len(list_items) - 1)))

        # --- OCHRANA PROTI "asked to focus, but it can't" ERRORU V KODI

        try:
            self.setFocusId(1000)
        except Exception:
            pass


    def onClick(self, controlId):
        if controlId == 1000:
            selected_item = self.list_control.getSelectedItem()
            if selected_item:
                if selected_item.getProperty('IsHeader') == 'true':
                    return

                self.selected_choice = self.list_control.getSelectedPosition()
                self.close()


    def onAction(self, action):
        if action.getId() in ACTION_PREVIOUS_MENU:
            self.selected_choice = -1
            self.close()
