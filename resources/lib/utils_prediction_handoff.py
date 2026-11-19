"""Session-scoped manual source recovery after a strict prediction rejection."""
import json
from uuid import uuid4
from urllib.parse import parse_qs, urlencode, urlsplit

SESSION = '_play_er_prediction_session'
PENDING = 'play_er.prediction_pending'
OPENING = 'play_er.prediction_opening'


def _enabled(addon):
    return all(str(addon.getSetting(key)).lower() == 'true' for key in (
        'auto_prediction_enable', 'auto_prediction_stop_on_no_match',
        'auto_prediction_manual_on_stop'))


def begin_session(meta, addon, fresh=False):
    if (meta.get('media_type') != 'episode'
            or str(addon.getSetting('auto_prediction_enable')).lower() != 'true'
            or str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() != 'true'):
        return
    if fresh or not meta.get(SESSION):
        meta[SESSION] = uuid4().hex
    if fresh:
        try:
            import xbmcgui
            win = xbmcgui.Window(10000)
            win.clearProperty(PENDING)
            win.clearProperty(OPENING)
        except Exception:
            pass


def remember_rejection(meta, addon, target):
    if not _enabled(addon) or not meta.get(SESSION) or target is None:
        return
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        active = json.loads(win.getProperty('play_er.current_meta') or '{}')
        if active.get(SESSION) != meta[SESSION]:
            return  # An old background builder must not affect a newer session.
        request = {'session': meta[SESSION], 'show': str(meta.get('tmdb_id')),
                   'target': list(target)}
        old = json.loads(win.getProperty(PENDING) or '{}')
        if old.get('session') == request['session'] and tuple(old['target']) < tuple(target):
            return
        win.setProperty(PENDING, json.dumps(request))
    except Exception:
        pass


def cancel_handoff(meta):
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        for key in (PENDING, OPENING):
            request = json.loads(win.getProperty(key) or '{}')
            if meta.get(SESSION) and request.get('session') == meta[SESSION]:
                win.clearProperty(key)
    except Exception:
        pass


def forget_rejection(meta, target):
    """A verified retry must not leave an obsolete manual-recovery target."""
    try:
        import xbmcgui
        win = xbmcgui.Window(10000)
        request = json.loads(win.getProperty(PENDING) or '{}')
        if (meta.get(SESSION) and request.get('session') == meta[SESSION]
                and tuple(request.get('target', [])) == tuple(target or [])):
            win.clearProperty(PENDING)
    except Exception:
        pass


def schedule_manual_selection(meta, addon, tmdb_client):
    """Called only after natural Ended; never from Stop, error or a skip dialog."""
    if not _enabled(addon) or not meta.get(SESSION):
        return False
    try:
        import xbmc
        import xbmcgui
        import threading
        from resources.lib.generator import _next_episode_coordinates, is_next_episode_queued
        win = xbmcgui.Window(10000)
        request = json.loads(win.getProperty(PENDING) or '{}')
        if request.get('session') != meta[SESSION] or request.get('show') != str(meta.get('tmdb_id')):
            return False
        expected = _next_episode_coordinates(meta['tmdb_id'], meta['season'], meta['episode'], tmdb_client)
        if expected is None or tuple(request.get('target', [])) != tuple(expected):
            return False
        if is_next_episode_queued(meta, tmdb_client):
            return False
        token = json.dumps(request)
        if win.getProperty(OPENING):
            return False
        # Keep PENDING visible throughout the worker lifetime. A Stop/new
        # session can then cancel it even during timeout cleanup; never recreate
        # a request after removing its cancellation marker.
        win.setProperty(OPENING, token)

        def open_results():
            monitor = xbmc.Monitor()
            restore_request = True
            season, episode = request['target']
            target_label = f"S{int(season):02d}E{int(episode):02d}"
            query = {'action': 'tmdbh_bridge', 'mode': 'search', 'media_type': 'episode',
                     'tmdb_id': request['show'], 'season': season, 'episode': episode}
            url = 'plugin://plugin.video.play_er/?' + urlencode(query)

            def report(state, level=xbmc.LOGINFO):
                xbmc.log(f"[PLAY.ER] PREDICTION MANUAL - {target_label} - {state}", level)

            try:
                attempts, retry_at = 0, 0
                # Unlike the initial TMDBH player, recovery must never force
                # activation through a modal or outlive its playback session.
                for step in range(150):
                    if monitor.waitForAbort(0.1):
                        restore_request = False
                        return
                    if win.getProperty(OPENING) != token:
                        return
                    active = json.loads(win.getProperty('play_er.current_meta') or '{}')
                    if (xbmc.Player().isPlaying() or active.get(SESSION) != meta[SESSION]
                            or not _enabled(addon)):
                        restore_request = False
                        report('CANCELLED')
                        return
                    if (xbmc.getCondVisibility('System.HasActiveModalDialog')
                            or xbmc.getCondVisibility('System.HasVisibleModalDialog')):
                        continue
                    folder = urlsplit(xbmc.getInfoLabel('Container.FolderPath'))
                    params = parse_qs(folder.query)
                    if (xbmc.getCondVisibility('Window.IsActive(Videos)')
                            and not xbmc.getCondVisibility('Container.IsUpdating')
                            and folder.scheme == 'plugin'
                            and folder.netloc == 'plugin.video.play_er'
                            and all(params.get(key) == [str(value)]
                                    for key, value in query.items())):
                        restore_request = False
                        report('OPENED')
                        return
                    if (attempts < 3 and step >= retry_at
                            and not xbmc.getCondVisibility('Container.IsUpdating')):
                        attempts += 1
                        retry_at = step + 20
                        report(f'OPENING attempt={attempts}')
                        # Do not block this worker in the GUI thread: it must
                        # continue observing Stop/new-playback cancellation.
                        xbmc.executebuiltin(f'ActivateWindow(Videos,{url},return)')
                report('TIMEOUT - results not confirmed; request retained', xbmc.LOGWARNING)
            except Exception as exc:
                # Do not log exception values: provider URLs can contain secrets.
                report(f'ERROR {type(exc).__name__} - request retained', xbmc.LOGWARNING)
            finally:
                if win.getProperty(OPENING) == token:
                    if not restore_request or monitor.abortRequested():
                        # Remove only our own request; a new session may already
                        # have published another one in the shared window.
                        if win.getProperty(PENDING) == token:
                            win.clearProperty(PENDING)
                    win.clearProperty(OPENING)

        threading.Thread(target=open_results).start()
        return True
    except Exception:
        return False
