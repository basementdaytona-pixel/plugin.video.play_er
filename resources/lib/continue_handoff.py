"""Guard the idle interval between Skip Credits and automatic Continue."""
import threading

import xbmc
import xbmcgui


TOKEN = 'plugin.video.play_er.continue_token'
ACK = 'plugin.video.play_er.continue_ack'


class ContinueHandoffGuard(xbmc.Player):
    """Cancel a pending handoff if any new playback starts in the meantime."""

    def __init__(self, token):
        super().__init__()
        self.token = token
        self.window = xbmcgui.Window(10000)
        self.interrupted = threading.Event()
        self.owner = None
        self.started = False

    def mark_started(self):
        self.started = True

    def bind_owner(self, owner):
        self.owner = owner or None

    def _cancel_on_start(self):
        self.interrupted.set()
        self.clear_token()

    def onPlayBackStarted(self):
        self._cancel_on_start()

    def onAVStarted(self):
        self._cancel_on_start()

    def valid(self):
        try:
            return (not self.interrupted.is_set()
                    and self.window.getProperty(TOKEN) == self.token
                    and (self.owner is None or self.window.getProperty('play_er.monitor_owner') == self.owner)
                    and not self.isPlaying())
        except Exception:
            return False

    def acknowledge(self):
        if not self.valid():
            return False
        self.window.setProperty(ACK, self.token)
        return self.valid()

    def clear_token(self):
        try:
            if self.window.getProperty(TOKEN) == self.token:
                self.window.clearProperty(TOKEN)
        except Exception:
            pass

    def clear(self):
        self.clear_token()
        try:
            if self.window.getProperty(ACK) == self.token:
                self.window.clearProperty(ACK)
        except Exception:
            pass
