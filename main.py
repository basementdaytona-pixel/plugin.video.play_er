# -*- coding: utf-8 -*-

import os
import sys
import traceback
import threading
import importlib
import gc

import xbmc
import xbmcvfs
import xbmcaddon

ERROR_DIR = xbmcvfs.translatePath("special://userdata/DATA--PLAY/ERRORS/")
ERROR_FILE = os.path.join(ERROR_DIR, "STARTUP-ERROR.LOG")

ADDON_ID = "plugin.video.play_er"
addon = xbmcaddon.Addon(id=ADDON_ID)

# ─────────────────────────────────────────────────────────────
# BACKGROUND SHARING LISTENER
# ─────────────────────────────────────────────────────────────

# FIX PRE-EMPTIVE AND FILTERS [BROADCAST MOVED TO KODI SERVICE]
# Original startup kept for reference; service.py now owns the listener.
# def start_background_service():
#     try:
#         from resources.lib import sharing_service
#
#         xbmc.log(
#             "| PLAY.ER | :: SERVICE - LISTENER :: MODULE FILE = " +
#             sharing_service.__file__,
#             xbmc.LOGINFO
#         )
#
#         importlib.reload(sharing_service)
#
#         listener = sharing_service.start_listener(addon, 60)
#
#         if listener:
#             xbmc.log(
#                 "| PLAY.ER | :: SERVICE - LISTENER :: START  [ OK ]",
#                 xbmc.LOGINFO
#             )
#         else:
#             xbmc.log(
#                 "| PLAY.ER | :: SERVICE - LISTENER :: START  [ FAILED ]",
#                 xbmc.LOGERROR
#             )
#
#     except Exception as e:
#         xbmc.log(
#             f"| PLAY.ER | :: SERVICE - LISTENER :: ERROR : {e}\n{traceback.format_exc()}",
#             xbmc.LOGERROR
#         )
#
#
# def run_service_once():
#     try:
#         if xbmc.getInfoLabel("Window(Home).Property(play_er_listener)") == "running":
#             return
#
#         xbmc.executebuiltin(
#             "SetProperty(play_er_listener,running,Home)"
#         )
#
#         thread = threading.Thread(
#             target=start_background_service,
#             daemon=True
#         )
#         thread.start()
#
#     except Exception:
#         pass
#
# ─────────────────────────────────────────────────────────────
# MAIN IMPORT
# ─────────────────────────────────────────────────────────────

try:
    from resources.lib import plugin

except Exception as e:
    xbmc.log(
        f"| PLAY.ER | :: MAIN PROCESS :: CRITICAL ERROR : {e}\n{traceback.format_exc()}",
        xbmc.LOGERROR
    )

    xbmc.executebuiltin(
        'Notification([B][COLOR red][ PLAY.ER : MAIN ][/COLOR][/B],'
        ' |► START-UP FATAL ERROR !,5000,)'
    )

    try:
        xbmcvfs.mkdirs(ERROR_DIR)
        fh = xbmcvfs.File(ERROR_FILE, "w")
        fh.write(traceback.format_exc())
        fh.close()
    except Exception:
        pass

    sys.exit(1)

# ─────────────────────────────────────────────────────────────
# START
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # run_service_once()  # Started by the xbmc.service extension.
    params_str = sys.argv[2][1:] if len(sys.argv) > 2 else ""

    try:
        plugin.router(params_str)

    except Exception as e:
        xbmc.log(
            f"| PLAY.ER | :: MAIN PROCESS :: ROUTER FATAL ERROR : {e}\n{traceback.format_exc()}",
            xbmc.LOGERROR
        )

        xbmc.executebuiltin(
            'Notification([B][COLOR red][ PLAY.ER : MAIN ][/COLOR][/B],'
            ' |► ROUTER FATAL ERROR !,5000,)'
        )

    finally:
        try:
            plugin.shutdown_runtime()
        except Exception as e:
            xbmc.log(f"| PLAY.ER | :: RUNTIME SHUTDOWN ERROR : {e}", xbmc.LOGWARNING)
        gc.collect()
