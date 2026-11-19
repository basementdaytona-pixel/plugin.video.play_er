# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_settings.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import xbmcaddon




class SafeAddonWrapper:

    """
    CLASS :: SAFE ADDON WRAPPER
    -- Bezpečný wrapper pro xbmcaddon.Addon chránící před pády v Kodi 22 Piers.
    """

    def __init__(self, original_addon=None):
        self._addon = original_addon or xbmcaddon.Addon(id="plugin.video.play_er")

    def getSetting(self, id):
        try:
            return self._addon.getSetting(id)
        except Exception:
            return ""

    def getSettingBool(self, id):
        try:
            val = self._addon.getSetting(id)
            return str(val).strip().lower() in ("true", "1", "yes", "on")
        except Exception:
            return False

    def getSettingString(self, id):
        try:
            return str(self._addon.getSetting(id) or "")
        except Exception:
            return ""

    def getSettingInt(self, id):
        try:
            val = self._addon.getSetting(id)
            return int(val)
        except Exception:
            return 0

    def getSettingNumber(self, id):
        try:
            val = self._addon.getSetting(id)
            return float(val)
        except Exception:
            return 0.0

    def setSetting(self, id, val):
        try:
            return self._addon.setSetting(id, str(val))
        except Exception:
            return False

    def setSettingBool(self, id, val):
        try:
            return self._addon.setSettingBool(id, bool(val))
        except Exception:
            return self._addon.setSetting(id, "true" if val else "false")

    def setSettingInt(self, id, val):
        try:
            return self._addon.setSettingInt(id, int(val))
        except Exception:
            return self._addon.setSetting(id, str(val))

    def setSettingString(self, id, val):
        try:
            return self._addon.setSettingString(id, str(val))
        except Exception:
            return self._addon.setSetting(id, str(val))

    def __getattr__(self, name):
        return getattr(self._addon, name)


def get_setting_int(addon, setting_id, default=0):
    try:
        val = addon.getSetting(setting_id)
        return int(val) if val not in (None, "") else default
    except (ValueError, TypeError):
        return default


def get_setting_float_with_bounds(addon, setting_id, default=0.0, min_val=None, max_val=None):
    try:
        val = addon.getSetting(setting_id)
        value = float(val) if val not in (None, "") else float(default)
        if min_val is not None:
            value = max(value, min_val)
        if max_val is not None:
            value = min(value, max_val)
        return value
    except (ValueError, TypeError):
        return float(default)


def get_setting_bool(addon, setting_id, default=False):
    try:
        value = addon.getSetting(setting_id)
        if value is None or value == "":
            return default
        return str(value).strip().lower() in ("true", "1", "yes", "y", "on")
    except Exception:
        return default


def get_setting_int_with_bounds(addon, setting_id, default=0, min_val=None, max_val=None):
    value = get_setting_float_with_bounds(addon, setting_id, default, min_val, max_val)
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_setting_str(addon, setting_id, default=""):
    try:
        value = addon.getSetting(setting_id)
        return str(value) if value is not None and value != "" else default
    except Exception:
        return default


def get_tmdb_language(addon):
    """Resolve the shared language preference to a TMDB language tag."""
    language = get_setting_str(addon, "tmdb_language", "cs_CZ")
    if language == "auto":
        import xbmc

        code = xbmc.getLanguage(xbmc.ISO_639_1) or "en"
        language = {"cs": "cs-CZ", "sk": "sk-SK", "en": "en-US",
                    "de": "de-DE", "fr": "fr-FR", "pl": "pl-PL",
                    "es": "es-ES", "it": "it-IT"}.get(code, f"{code}-{code.upper()}")
    return language.replace("_", "-")
