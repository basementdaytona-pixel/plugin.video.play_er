# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: FULLSCREEN---MUTE.py
# Author: Mau!X ER
# Created on: 09.05.2026
# Last edit on: 09.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import subprocess





# ============= SETUP ============= #

IP = "192.168.200.100"
PORT = "8077"
USER = "KODI"
PASS = "114698730"

URL = f"http://{IP}:{PORT}/jsonrpc"

# ================================= #





DATA = """
{
  "jsonrpc": "2.0",
  "method": "Input.ExecuteAction",
  "params": {
    "action": "fullscreen"
  },
  "id": 1
}
"""


subprocess.run([
    "curl",
    "-s",
    "-u", f"{USER}:{PASS}",
    "-X", "POST",
    "-H", "Content-Type: application/json",
    "-d", DATA,
    URL
])
