"""Keep the Kodi callback type independent of plugin runtime globals."""

import time

import xbmc


class SettingsMonitor(xbmc.Monitor):
    def __init__(self):
        super().__init__()
        self._last_check = 0

    def onSettingsChanged(self):
        if time.time() - self._last_check < 2.0:
            return
        self._last_check = time.time()

        # Import only while handling the callback. A retained native callback
        # type must not keep plugin.py's global Addon/Window objects alive.
        from resources.lib.plugin import reinitialize_clients
        from resources.lib import cache_manager

        reinitialize_clients()
        if not xbmc.Player().isPlaying():
            # Recreate connections after database credentials or pool settings change.
            cache_manager.close_mysql_pool()
            cache_manager.safe_refresh()
