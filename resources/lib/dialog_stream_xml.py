# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_stream_xml.py
# Author: Mau!X ER
# Created on: 22.05.2026
# Last edit on: 24.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import xbmc
import xbmcgui
import xbmcaddon

from resources.lib.utils_logging import log

from resources.lib.utils_theme import apply_dialog_theme



ACTION_PREVIOUS_MENU = [9, 92, 110, 284, 513]



class StreamDashboardXML(xbmcgui.WindowXMLDialog):
    PREDICTION_SETTINGS = {
        4101: ('auto_prediction_enable', 'PREDIKCE HLEDANÉHO VÝRAZU'),
        4102: ('auto_prediction_stop_on_no_match', 'NESHODA UKONČÍ PLAYLIST'),
        4103: ('auto_prediction_manual_on_stop', 'RUČNÍ VÝBĚR PO UKONČENÍ'),
    }


    def __new__(cls, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        return super(StreamDashboardXML, cls).__new__(cls, xmlFilename, scriptPath, defaultSkin, defaultRes)

    def __init__(self, xmlFilename, scriptPath, defaultSkin='Default', defaultRes='1080i', **kwargs):
        super().__init__()
        self.addon = xbmcaddon.Addon(id="plugin.video.play_er")
        self.streams = kwargs.get('streams', {})
        self.selected_url = None
        self.next_action = None
        self.slider_updating = False
        self._slider_positions = {}
        
        # --- Ochrana listu před GC uvolněním v paměti

        self.list_items = []
        
        # --- Ochrana proti vícenásobnému spuštění z Kodi jádra

        self._init_done = False
        log("DIALOG_XML - Inicializace třídy dokončena", xbmc.LOGDEBUG)



    def onInit(self):
        apply_dialog_theme(self)
        if not self._init_done:
            log("DIALOG_XML - onInit SPUŠTĚN  ( PRVNÍ BĚH )", xbmc.LOGINFO)
            self.populate_streams()
            self.update_setting_labels()
            
            try:
                current_trigger = self._get_slider_int("skip_credits_trigger", 120)
                current_trigger = min(600, current_trigger) if current_trigger >= 10 else 120
                percent_trigger = ((current_trigger - 10) / 590.0) * 100
                self._set_slider_percent(4004, percent_trigger)
                self._set_skip_credits_label(current_trigger)

                current_bw = self._get_slider_int("max_bandwidth_mbps", 0)
                current_bw = max(0, min(1000, current_bw))
                percent_bw = (current_bw / 1000.0) * 100
                self._set_slider_percent(3005, percent_bw)
                bw_label = "NEOMEZENO" if current_bw == 0 else f"{current_bw} MBPS"
                self.getControl(3004).setLabel(f"MAX BANDWIDTH : [COLOR limegreen]{bw_label}[/COLOR]")

                current_tol = self._get_slider_int("downgrade_tolerance", 5)
                current_tol = min(15, current_tol) if current_tol >= 2 else 5
                percent_tol = ((current_tol - 2) / 13.0) * 100
                self._set_slider_percent(3008, percent_tol)
                self.getControl(3007).setLabel(f"TOLERANCE ZASEKÁVÁNÍ : [COLOR limegreen]{current_tol} SEKUND[/COLOR]")
            except Exception as e:
                log(f"DIALOG_XML - Chyba při nastavení slideru : {e}", xbmc.LOGWARNING)
            self._init_continue_slider()
            self._init_done = True
        else:
            log("DIALOG_XML - onInit SPUŠTĚN OPAKOVANĚ  ( IGNOROVÁNO )", xbmc.LOGDEBUG)



    def _set_skip_credits_label(self, value):
        self.getControl(4003).setLabel(
            f"PŘESKOČIT TITULKY : [COLOR limegreen]{value}[/COLOR] PŘED KONCEM"
        )

    def _get_slider_int(self, key, default):
        try:
            return int(self.addon.getSetting(key))
        except (ValueError, TypeError, RuntimeError):
            return default

    def _set_slider_percent(self, control_id, percent):
        self.getControl(control_id).setPercent(percent)
        self._slider_positions[control_id] = percent

    def _get_continue_count(self):
        try:
            value = int(self.addon.getSetting("continue_episodes_count"))
        except (ValueError, TypeError):
            value = 3
        return max(1, min(10, value))

    def _init_continue_slider(self):
        value = self._get_continue_count()
        self._set_slider_percent(3010, (value - 1) * 100.0 / 9)
        self.getControl(3009).setLabel(f"POČET NÁSLEDUJÍCÍCH EPIZOD : [COLOR limegreen]{value}[/COLOR]")

    def populate_streams(self):
        log(f"DIALOG_XML - Začínám plnit seznam streamů. Počet: {len(self.streams)}", xbmc.LOGDEBUG)
        try:
            list_control = self.getControl(1000)

            list_control.reset()
            self.list_items = []
            
            # --- TADY ZAČÍNÁ NOVÝ KÓD PRO BARVY A TEXTY

            for name in self.streams.keys():
                if name.upper() == "ORIGINAL (MKV)":
                    display_name = "[COLOR orange]  ► [/COLOR][B]  ORIGINAL  (MKV)[/B]"
                else:
                    display_name = f"[COLOR orange]  ► [/COLOR][B]  STREAM  :  {name.upper()}[/B]"
                    
                li = xbmcgui.ListItem(f"{display_name}")
                
                # --- Uložíme originální klíč do paměti, aby přehrávač našel správný soubor!

                li.setProperty('stream_key', name)
                
                self.list_items.append(li)

            # --- KONEC NOVÉHO KÓDU ---
                
            if self.list_items:
                list_control.addItems(self.list_items)
                log("DIALOG_XML - Položky úspěšně přidány do listu", xbmc.LOGDEBUG)
                
                # FIX PRE-EMPTIVE AND FILTERS [FOCUS ON THE GUI CALLBACK THREAD]
                self.setFocusId(1000)
            else:
                self.setFocusId(3001)

        except Exception as e:
            log(f"DIALOG_XML - Kritická chyba v populate_streams: {e}", xbmc.LOGERROR)


    def update_setting_labels(self):
        try:
            mode = self.addon.getSetting("prehrajto_stream_mode").upper()
            self.getControl(3001).setLabel(f"REŽIM VÝBĚRU ZDROJE : [COLOR limegreen]{mode}[/COLOR]")
            qual = self.addon.getSetting("prehrajto_pref_quality").upper()
            self.getControl(3002).setLabel(f"PREFEROVANÁ KVALITA : [COLOR limegreen]{qual}[/COLOR]")
            
            likes = "ON" if self.addon.getSettingBool("sort_by_likes") else "OFF"
            color_likes = "limegreen" if likes == "ON" else "red"
            self.getControl(3003).setLabel(f"ŘADIT DLE POČTU LIKE : [COLOR {color_likes}]{likes}[/COLOR]")
            
            auto_down = "ON" if self.addon.getSettingBool("enable_auto_downgrade") else "OFF"
            color_auto_down = "limegreen" if auto_down == "ON" else "red"
            self.getControl(3006).setLabel(f"AUTO DOWN-STREAM : [COLOR {color_auto_down}]{auto_down}[/COLOR]")

            skip = "ON" if self.addon.getSettingBool("enable_skip_credits") else "OFF"
            color_skip = "limegreen" if skip == "ON" else "red"
            self.getControl(4001).setLabel(f"SKIP CREDITS : [COLOR {color_skip}]{skip}[/COLOR]")
            
            pl = "ON" if self.addon.getSettingBool("skip_credits_auto_when_playlist") else "OFF"
            color_pl = "limegreen" if pl == "ON" else "red"
            self.getControl(4002).setLabel(f"LIST SKIP : [COLOR {color_pl}]{pl}[/COLOR]")
            
            ac = self.addon.getSettingInt("skip_credits_autoclose")
            self.getControl(4005).setLabel(f"AUTOMATICKÉ ZAVŘENÍ OKNA : [COLOR limegreen]{ac} SEKUND[/COLOR]")

            for control_id, (key, label) in self.PREDICTION_SETTINGS.items():
                enabled = self.addon.getSettingBool(key)
                color, state = ('limegreen', 'ON') if enabled else ('red', 'OFF')
                self.getControl(control_id).setLabel(f"{label} : [COLOR {color}]{state}[/COLOR]")

            
        except Exception as e:
            log(f"DIALOG_XML - Chyba při aktualizaci labelů nastavení : {e}", xbmc.LOGWARNING)


    def onClick(self, controlId):
        log(f"DIALOG_XML - Uživatel kliknul na controlId : {controlId}", xbmc.LOGDEBUG)
        if controlId in self.PREDICTION_SETTINGS:
            key, _ = self.PREDICTION_SETTINGS[controlId]
            self.addon.setSettingBool(key, not self.addon.getSettingBool(key))
            self.update_setting_labels()
            return
        if controlId in (4004, 3005, 3008, 3010):
            self._save_slider(controlId)
            return
        
        if controlId == 1000:
            selected_item = self.getControl(1000).getSelectedItem()
            if selected_item:

                # --- Načteme skrytý klíč z vlastnosti položky!

                stream_key = selected_item.getProperty('stream_key')
                
                self.selected_url = self.streams.get(stream_key)
                log(f"DIALOG_XML - VYBRÁN STREAM : {stream_key}", xbmc.LOGINFO)
                self.close()

        elif controlId == 3001:
            current = self.addon.getSetting("prehrajto_stream_mode")
            new_val = "auto" if current == "ask" else "ask"
            self.addon.setSetting("prehrajto_stream_mode", new_val)
            self.update_setting_labels()

        elif controlId == 3002:
            opts = ["original", "highest", "1080p", "720p", "480p", "lowest"]
            current = self.addon.getSetting("prehrajto_pref_quality")
            try:
                idx = opts.index(current)
                new_val = opts[(idx + 1) % len(opts)]
            except:
                new_val = opts[0]
            self.addon.setSetting("prehrajto_pref_quality", new_val)
            self.update_setting_labels()

        elif controlId == 3003:
            current = self.addon.getSettingBool("sort_by_likes")
            self.addon.setSettingBool("sort_by_likes", not current)
            self.update_setting_labels()
        elif controlId == 3006:
            current = self.addon.getSettingBool("enable_auto_downgrade")
            self.addon.setSettingBool("enable_auto_downgrade", not current)
            self.update_setting_labels()
        elif controlId == 4001:
            current = self.addon.getSettingBool("enable_skip_credits")
            self.addon.setSettingBool("enable_skip_credits", not current)
            self.update_setting_labels()
        elif controlId == 4002:
            current = self.addon.getSettingBool("skip_credits_auto_when_playlist")
            self.addon.setSettingBool("skip_credits_auto_when_playlist", not current)
            self.update_setting_labels()

        elif controlId == 4005:
            opts = [5, 10, 15, 20, 30, 45, 60]
            current = self.addon.getSettingInt("skip_credits_autoclose")
            try:
                idx = opts.index(current)
                new_val = opts[(idx + 1) % len(opts)]
            except:
                new_val = opts[0]
            self.addon.setSettingInt("skip_credits_autoclose", new_val)
            self.update_setting_labels()

        elif controlId == 5001:
            self.next_action = "settings"
            self.close()
        elif controlId == 5002:
            self.next_action = "menu"
            self.close()

    # FIX PRE-EMPTIVE AND FILTERS [BOUNDED SLIDERS AND SAFE BACK ACTION]
    def _save_slider(self, control_id):
        specs = {
            3010: ('continue_episodes_count', 1, 10, 1, 3009, 'POČET NÁSLEDUJÍCÍCH EPIZOD ', ''),
            4004: ('skip_credits_trigger', 10, 600, 5, 4003, 'PŘESKOČIT', 'SEKUND PŘED KONCEM'),
            3005: ('max_bandwidth_mbps', 0, 1000, 1, 3004, 'MAX BANDWIDTH', 'MBPS'),
            3008: ('downgrade_tolerance', 2, 15, 1, 3007, 'TOLERANCE ZASEKÁVÁNÍ', 'SEKUND'),
        }
        if control_id not in specs or not self._init_done:
            return
        key, minimum, maximum, step, label_id, label, unit = specs[control_id]
        percent = max(0, min(100, self.getControl(control_id).getPercent()))
        previous = self._slider_positions.get(control_id)
        if previous is not None and abs(percent - previous) < 0.001:
            return
        value = minimum + round((maximum - minimum) * percent / 100 / step) * step
        value = int(max(minimum, min(maximum, value)))
        if key == 'continue_episodes_count':
            if self.addon.getSetting(key) != str(value):
                self.addon.setSetting(key, str(value))
        elif self._get_slider_int(key, None) != value:
            self.addon.setSettingInt(key, value)
        self._slider_positions[control_id] = percent
        if control_id == 4004:
            self._set_skip_credits_label(value)
            return
        text = 'NEOMEZENO' if key == 'max_bandwidth_mbps' and value == 0 else f'{value} {unit}'.strip()
        self.getControl(label_id).setLabel(f'{label}: [COLOR limegreen]{text}[/COLOR]')

    def onAction(self, action):
        if action.getId() in ACTION_PREVIOUS_MENU:
            self.close()
            return
        try:
            self._save_slider(self.getFocusId())
        except (RuntimeError, TypeError):
            pass
