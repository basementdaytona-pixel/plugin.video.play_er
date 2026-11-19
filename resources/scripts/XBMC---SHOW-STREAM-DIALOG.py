#!/usr/bin/env python3

import subprocess




# ======= SETUP ======= #

IP = "192.168.200.100"
PORT = "8077"
USER = "KODI"
PASS = "114698730"

# ======= SETUP ======= #





URL = f"http://{IP}:{PORT}/jsonrpc"





DATA = """
{
  "jsonrpc": "2.0",
  "method": "Addons.ExecuteAddon",
  "params": {
    "addonid": "plugin.video.play_er",
    "params": {
      "action": "show_stream_menu"
    }
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
