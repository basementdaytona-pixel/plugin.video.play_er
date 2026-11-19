"""Play.er credits prompt using the installed AF3 Up Next layout when available.

Own controller; no service.upnext service, source code or assets are required.
The AF3 XML adapter references jurialmunkey's installed OSD layout components.
"""
import math
import threading
import time

import xbmc
import xbmcgui

from resources.lib.utils_logging import log


class SkipCreditsDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.result = None
        self.ready = threading.Event()
        self._result_lock = threading.Lock()
        self.deadline = None
        self._initial_focus_pending = True

    def configure(self, meta, episode, timeout, default_action, is_current):
        self.meta = meta
        self.episode = episode or {}
        self.timeout = max(1, int(timeout))
        self.default_action = 'PRESKOCIT' if default_action == 'PRESKOCIT' else 'POKRACOVAT'
        self.is_current = is_current

    def onInit(self):
        meta, episode = self.meta, self.episode
        art = meta.get('art') or {}
        still = episode.get('still_path')
        thumb = f'https://image.tmdb.org/t/p/w780{still}' if still else ''
        episode_title = episode.get('name') or f"Epizoda {meta.get('episode', '?')}"
        show_title = meta.get('tv_show_title') or meta.get('showtitle') or ''
        episode_number = f"{int(meta.get('season', 0))}x{int(meta.get('episode', 0)):02d}"
        props = {
            'play_er.episode_label': f"[B][COLOR orange]{episode_number}[/COLOR][/B] • {show_title.upper()}\n{episode_title}" if show_title else f"[B][COLOR orange]{episode_number}[/COLOR][/B]\n{episode_title}",
            'title': episode.get('name') or f"Epizoda {meta.get('episode', '?')}",
            'tvshowtitle': meta.get('tv_show_title') or meta.get('showtitle') or '',
            'season': meta.get('season', ''),
            'episode': meta.get('episode', ''),
            'seasonepisode': f"S{int(meta.get('season', 0)):02d}E{int(meta.get('episode', 0)):02d}",
            'plot': episode.get('overview') or '',
            'year': (episode.get('air_date') or '')[:4],
            'thumb': thumb,
            'landscape': thumb or art.get('tvshow.landscape') or meta.get('landscape') or '',
            'fanart': art.get('tvshow.fanart') or meta.get('fanart') or '',
            'poster': art.get('tvshow.poster') or meta.get('poster') or '',
            'remaining': str(self.timeout),
            'play_er.timeout_action': 'Další epizoda' if self.default_action == 'PRESKOCIT' else 'Zavření nabídky',
        }
        for key, value in props.items():
            self.setProperty(key, str(value or ''))
        self.getControl(3012).setLabel('SKIP')
        # Also tolerate AF3 overrides using a visible cancel proxy (4013).
        for control_id in (3013, 4013):
            try:
                self.getControl(control_id).setLabel('CLOSE')
            except RuntimeError:
                pass
        self.getControl(3014).setPercent(100)
        self.setFocusId(3012)
        self.deadline = time.monotonic() + self.timeout
        self.window_id = xbmcgui.getCurrentWindowDialogId()
        self.ready.set()

    def finish(self, result):
        with self._result_lock:
            if self.result is not None:
                return
            self.result = result
        self.close()

    def tick(self, now):
        if self.result is not None:
            return
        if not self.is_current():
            self.finish('POKRACOVAT')
            return
        # onInit runs while AF3 is closing the previous video OSD. Recover
        # missing focus once after the first frames, never steal a valid selection
        # or focus from another dialog opened above this one.
        if (self._initial_focus_pending and self.ready.is_set()
                and now >= self.deadline - self.timeout + 0.2
                and xbmcgui.getCurrentWindowDialogId() == self.window_id):
            try:
                focused = self.getFocusId()
            except RuntimeError:
                focused = -1
            if focused not in (3012, 3013, 3015, 4013):
                self.setFocusId(3012)
            self._initial_focus_pending = False
        remaining = max(0, self.deadline - now)
        self.setProperty('remaining', str(math.ceil(remaining)))
        self.getControl(3014).setPercent(100 * remaining / self.timeout)
        if remaining <= 0:
            self.finish(self.default_action)

    def onClick(self, controlId):
        if controlId == 3012:
            self.finish('PRESKOCIT')
        elif controlId == 3015:
            self.finish('MENU')
        elif controlId in (3013, 4013):
            self.finish('POKRACOVAT')

    def onAction(self, action):
        # AF3's button group also maps Up to Close. Treat dismissal as continue.
        if action.getId() in (3, 9, 10, 13, 92, 110, 284, 513):
            self.finish('POKRACOVAT')


def show_skip_credits(meta, episode, addon, timeout, default_action, is_current):
    """Wait for UI choice without pausing playback; never act on another item."""
    af3 = xbmc.getSkinDir() == 'skin.arctic.fuse.3'
    filename = 'script-play_er-skip-credits-af3.xml' if af3 else 'script-play_er-skip-credits.xml'
    dialog = SkipCreditsDialog(filename, addon.getAddonInfo('path'), 'Default', '1080i')
    dialog.configure(meta, episode, timeout, default_action, is_current)
    monitor = xbmc.Monitor()
    try:
        if not is_current():
            return 'POKRACOVAT'
        dialog.show()
        startup_deadline = time.monotonic() + 5
        while not dialog.ready.is_set():
            if monitor.waitForAbort(0.05) or not is_current() or time.monotonic() >= startup_deadline:
                return 'POKRACOVAT'
        window_id = dialog.window_id
        while dialog.result is None:
            if monitor.abortRequested() or not is_current():
                return 'POKRACOVAT'
            if not xbmc.getCondVisibility(f'Window.IsVisible({window_id})'):
                return 'POKRACOVAT'
            dialog.tick(time.monotonic())
            if monitor.waitForAbort(0.1):
                return 'POKRACOVAT'
        if dialog.result == 'MENU':
            # Open the existing router only after the credits window has closed.
            dialog.close()
            if not monitor.waitForAbort(0.3) and is_current():
                xbmc.executebuiltin('RunPlugin(plugin://plugin.video.play_er/?action=show_stream_menu)')
            return 'POKRACOVAT'
        return dialog.result if is_current() else 'POKRACOVAT'
    except Exception as exc:
        log(f'SKIP CREDITS - Dialog error: {exc}', xbmc.LOGWARNING)
        return 'POKRACOVAT'
    finally:
        dialog.close()
