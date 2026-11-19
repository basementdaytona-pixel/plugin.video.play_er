# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_notification.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re

import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon


from resources.lib.utils_logging import log


from resources.lib.utils_theme import (
    Colors,
    Icons
)




try:
    addon = xbmcaddon.Addon("plugin.video.play_er")
except Exception:
    addon = xbmcaddon.Addon()





def _get_icon_path(filename, default="DefaultIconInfo.png"):
    try:
        addon_path = addon.getAddonInfo('path')
        path = os.path.join(addon_path, "resources", "icons", filename)
        translated = xbmcvfs.translatePath(path)
        if xbmcvfs.exists(translated):
            return translated
    except Exception:
        pass

    return xbmcvfs.translatePath(f"special://xbmc/media/Icons/{default}")






def _format_message(text):

    """
    NOTIFICATION :: FORMAT
    -- První slovo COLOR limegreen
    -- Zbytek textu v hranatých závorkách[]
    """

    parts = text.split(" ", 1)
    if len(parts) == 2:
        prefix, rest = parts
        return f"[B][COLOR orange]► [/COLOR][COLOR limegreen]{prefix}[/COLOR][/B]  [ {rest} ]"

    return f"[B][COLOR orange]► [/COLOR][COLOR limegreen]{text}[/COLOR][/B]"


def _build_title(category):
    base = f"[B][COLOR {Colors.ORANGE}]| PLAY.ER"

    if category:
        base += f" : {category.upper()}"

    base += " |[/COLOR][/B]"
    return base


def _log_notify(level, category, message):
    log(f"[NOTIFY][{level.upper()}][{category}] {message}")


def _should_skip(setting_key, force):
    return addon.getSettingBool(setting_key) and not force


def _base_notify(message, category, time, icon_file, setting_key, sound, level, force=False, native_icon=None):

    if _should_skip(setting_key, force):
        return

    _log_notify(level, category, message)

    formatted_msg = _format_message(message)
    title = _build_title(category)
    icon = native_icon if native_icon is not None else _get_icon_path(icon_file)

    xbmcgui.Dialog().notification(title, formatted_msg, icon, time, sound)


def notify_ok(message, category="", time=5000, sound=False):
    _base_notify(
        message,
        category,
        time,
        "NOTIFY-OK.webp",
        "disable_notify_ok",
        sound,
        level="ok"
    )


def notify_info(message, category="", time=5000, sound=False):
    _base_notify(
        message,
        category,
        time,
        "NOTIFY-INFO.webp",
        "disable_notify_info",
        sound,
        level="info"
    )


def notify_warning(message, category="", time=5000, sound=True):
    """Warnings follow the information switch and keep Kodi's warning icon."""
    _base_notify(
        message,
        category,
        time,
        None,
        "disable_notify_info",
        sound,
        level="warning",
        native_icon=xbmcgui.NOTIFICATION_WARNING
    )


def notify_error(message, category="", time=5000, sound=True):
    _base_notify(
        message,
        category,
        time,
        "NOTIFY-ERROR.webp",
        "disable_notify_error",
        sound,
        level="error"
    )


def notify_acc(message, category="", time=5000, sound=False):
    _base_notify(
        message,
        category,
        time,
        "NOTIFY-ACC.webp",
        "disable_notify_acc",
        sound,
        level="ok"
    )


def notify_episode(message, category="", time=5000, sound=False):
    _base_notify(
        message,
        category,
        time,
        "NOTIFY-INFO.webp",
        "disable_episode_notify",
        sound,
        level="ok"
    )