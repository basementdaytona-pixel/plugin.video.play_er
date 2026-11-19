# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: metrics_manager.py
# Author: Mau!X ER
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import time
import json

import xbmc
import xbmcvfs

# --- AUTO-INJECTED KODI 22 VFS PATCH ---
class SafeVFSFile:
    def __init__(self, *args, **kwargs):
        import xbmcvfs
        self.file_obj = xbmcvfs.File(*args, **kwargs)
    def __enter__(self):
        return self.file_obj
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file_obj.close()
        return False
# ---------------------------------------

import xbmcaddon


try:
    ADDON = xbmcaddon.Addon("plugin.video.play_er")
except Exception:
    ADDON = xbmcaddon.Addon()








class MetricsManager:

    def __init__(self):
        self._counters = {}
        self._gauges = {}
        self._meta = {}



    def inc(self, name, amount=1, tags=None):
        self._counters[name] = self._counters.get(name, 0) + amount

    def gauge(self, name, value, tags=None):
        self._gauges[name] = value

    def set_meta(self, key, value):
        self._meta[key] = value

    def snapshot(self):
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "addon_version": ADDON.getAddonInfo('version'),
            "metrics": {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
            },
            "meta": dict(self._meta)
        }

    def export(self, path):
        try:
            snap = self.snapshot()
            # Use xbmcvfs.translatePath for filesystem paths
            export_path = xbmcvfs.translatePath(path)
            # ensure directory exists
            dirpath = export_path.rsplit('/', 1)[0]
            if not xbmcvfs.exists(dirpath):
                xbmcvfs.mkdirs(dirpath)
            with SafeVFSFile(export_path, 'w') as f:
                f.write(json.dumps(snap, ensure_ascii=False, indent=2))
            return export_path
        except Exception as e:
            try:
                from resources.lib.utils_logging import log
                log(f"METRICS EXPORT FAILED: {e}", xbmc.LOGERROR)
            except Exception:
                xbmc.log(f"METRICS EXPORT FAILED: {e}", xbmc.LOGERROR)
            return None


# module-level singleton
METRICS = MetricsManager()
