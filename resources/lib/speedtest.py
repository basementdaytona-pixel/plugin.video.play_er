# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: speedtest.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import time
import requests

import xbmcgui


from resources.lib.utils_logging import log
from resources.lib.utils import safe_get


from resources.lib.utils_notification import (
    notify_info,
    notify_error
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)




DOWNLOAD_URL = "https://prg.download.datapacket.com/100mb.bin"





def diagnose_speed(addon):

    notify_info("SPEEDTEST Stahuji 100 MB", category="SYSTEM", time=10000, sound=True)

    try:
        start = time.time()
        r = safe_get(DOWNLOAD_URL, stream=True, timeout=120)
        if not r:
            notify_error("ERROR Chyba při testu rychlosti: network error", category="SYSTEM")
            return
        downloaded = 0
        for chunk in r.iter_content(chunk_size=1024 * 64):
            if chunk:
                downloaded += len(chunk)
        duration = time.time() - start
        bits_downloaded = downloaded * 8
        mbps_download = (
            (bits_downloaded / (1024 * 1024)) / duration if duration > 0 else 0
        )
        notify_info(f"SPEEDTEST Rychlost: {mbps_download:.2f} Mbps", category="SYSTEM", time=20000, sound=True)

    except Exception as e:

        notify_error(f"ERROR Chyba při testu rychlosti: {e}", category="SYSTEM")