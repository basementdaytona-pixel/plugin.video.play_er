# -*- coding: utf-8 -*-
"""BROADCAST polling, owned by service.py; menu refresh also works independently."""

# FIX PRE-EMPTIVE AND FILTERS [BROADCAST SERVICE LIFETIME AND MANUAL REFRESH]
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.sharing_store import SharingStore, normalize_records
from resources.lib.utils_logging import log
from resources.lib.utils import safe_get


def get_store():
    return SharingStore(xbmcvfs.translatePath('special://masterprofile/DATA--PLAY/SHARING'))


class SharingListener(threading.Thread):
    def __init__(self, addon_id='plugin.video.play_er', poll_interval=60):
        super().__init__(daemon=True)
        self.addon = xbmcaddon.Addon(addon_id)
        self.poll_interval = max(1, int(poll_interval))
        self._stop_event = threading.Event()
        self._force_event = threading.Event()
        self.store = get_store()

    def stop(self):
        self._stop_event.set()
        self._force_event.set()

    def force_check(self):
        return self.perform_fetch(manual=True)

    def perform_fetch(self, manual=False):
        if not self.addon.getSettingBool('enable_community_sharing'):
            return True
        try:
            from resources.lib.telegram import get_device_id
            with self.store.locked():
                try:
                    interval = max(1, int(self.addon.getSetting('community_poll_interval') or '60')) * 60
                    limit = max(1, min(500, int(self.addon.getSetting('community_history_size') or '200')))
                except (TypeError, ValueError):
                    interval, limit = 3600, 200
                if not manual and time.time() - self.store.last_check() < interval:
                    return True
                url = self.addon.getSettingString('community_api_url').strip() or 'https://xbmc.south-fork.uk/SERVER/addon-sharing.php'
                response = safe_get(url, timeout=10, retry=0)
                if response is None or response.status_code != 200:
                    status = getattr(response, 'status_code', 'bez odpovědi')
                    log(f'SHARING SERVICE - Server nedostupný: {status}', xbmc.LOGWARNING)
                    return False
                records = normalize_records(response.json())
                incoming, previous_ts = self.store.merge(records, get_device_id(), limit)
                self.store.mark_checked(time.time())
            # Notify only after a successful save; notification failure must not
            # reset the cursor or prevent receiving the remaining records.
            if previous_ts > 0 or manual:
                self._notify(incoming)
            return True
        except Exception as exc:
            log(f'SHARING SERVICE - Příjem selhal: {type(exc).__name__}: {exc}', xbmc.LOGWARNING)
            return False

    def _notify(self, records):
        from resources.lib.utils_notification import notify_info

        for rec in records:
            try:
                notify_info(f"SDÍLENÍ Přijato: {rec['title']}", category="SHARING", time=15000,
                            sound=self.addon.getSettingBool('community_notify_sound'))
                if self.addon.getSettingBool('telegram_master_device'):
                    from resources.lib.telegram import TelegramManager
                    TelegramManager(self.addon).send_incoming_share_notification(rec)
            except Exception as exc:
                log(f'SHARING SERVICE - Oznámení selhalo: {type(exc).__name__}', xbmc.LOGWARNING)

    def run(self):
        log('SHARING SERVICE - START', xbmc.LOGINFO)
        monitor = xbmc.Monitor()
        try:
            while not self._stop_event.is_set() and not monitor.abortRequested():
                self.perform_fetch()
                for _ in range(self.poll_interval):
                    if self._stop_event.is_set() or monitor.waitForAbort(1):
                        return
                    if self._force_event.is_set():
                        self._force_event.clear()
                        break
        finally:
            log('SHARING SERVICE - STOP', xbmc.LOGINFO)


_sharing_instance = None


def start_listener(addon=None, interval=60):
    """Compatibility entry point; the registered Kodi service owns its lifetime."""
    global _sharing_instance
    if not _sharing_instance or not _sharing_instance.is_alive():
        _sharing_instance = SharingListener(poll_interval=interval)
        _sharing_instance.start()
    return _sharing_instance


def stop_listener():
    global _sharing_instance
    if _sharing_instance:
        _sharing_instance.stop()
        _sharing_instance = None


def force_check():
    # Old code silently did nothing unless this interpreter had started a thread.
    listener = _sharing_instance or SharingListener()
    return listener.perform_fetch(manual=True)
