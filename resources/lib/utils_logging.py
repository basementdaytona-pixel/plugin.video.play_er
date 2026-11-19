# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_logging.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import xbmc
import xbmcaddon
from resources.lib.utils_settings import get_setting_int_with_bounds


try:
    addon = xbmcaddon.Addon("plugin.video.play_er")
except Exception:
    addon = xbmcaddon.Addon()






def log(message, level=xbmc.LOGDEBUG):

    """
    LOGGING :: GLOBAL
    -- Ovládá funkci logování na základě úrovně logu v nastavení.
    """

    try:
        level_index = get_setting_int_with_bounds(addon, "logging_level", 0)
    except Exception:
        level_index = 0


    level_map = {
        0: xbmc.LOGDEBUG,
        1: xbmc.LOGINFO,
        2: xbmc.LOGWARNING,
        3: xbmc.LOGERROR,
        4: None,
    }

    min_log_level = level_map.get(level_index, xbmc.LOGDEBUG)

    if min_log_level is None:
        return
    if level >= min_log_level:
        xbmc.log(f"| PLAY.ER | :: {message}", level=level)