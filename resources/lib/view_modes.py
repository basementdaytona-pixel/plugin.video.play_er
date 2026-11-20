# -*- coding: utf-8 -*-
"""Directory view selection and Arctic Fuse 3's native view configuration."""
import json
from urllib.parse import parse_qsl, urlsplit

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.utils_logging import log
from resources.lib.utils_notification import notify_info
from resources.lib.utils_settings import get_setting_bool


_request_url = ''
_request_params = {}
_pending_view = None


def begin_directory(url, params):
    """Reset invocation state, including when Kodi reuses the interpreter."""
    global _request_url, _request_params, _pending_view
    _request_url, _request_params, _pending_view = url, dict(params), None


def _is_hosted():
    return any(str(_request_params.get(key, '')).lower() not in ('', 'false', '0', 'no')
               for key in ('widget', 'is_widget', 'widget_id', 'multisearch', 'is_multisearch'))


def _folder_identity(url):
    parts = urlsplit(url)
    return parts.scheme, parts.netloc, parts.path.rstrip('/'), sorted(parse_qsl(parts.query, keep_blank_values=True))


def apply_view_mode(view_id, *, video_list=True, widgets=False, multisearch=False, plugin_url=''):
    """Apply after endOfDirectory, only to the directory that requested it."""
    text = str(view_id or '').strip()
    if not text.isascii() or not text.isdecimal() or int(text) <= 0:
        return False
    if widgets or multisearch or not video_list or _is_hosted():
        return False
    if not xbmc.getCondVisibility('Window.IsActive(videos)'):
        return False
    if plugin_url and _folder_identity(xbmc.getInfoLabel('Container.FolderPath')) != _folder_identity(plugin_url):
        return False
    xbmc.executebuiltin('Container.SetViewMode({})'.format(int(text)))
    return True


def queue_view_mode(view_id):
    global _pending_view
    _pending_view = view_id


def finish_directory():
    global _pending_view
    target, _pending_view = _pending_view, None
    if target is not None:
        return apply_view_mode(target, plugin_url=_request_url)
    return False


def menu_content(addon, content_type, view_type_key):
    """Opt in to AF3 movie catalogue layouts for navigation folders."""
    if (content_type == 'files' and view_type_key in (
            'main_menu', 'movies_submenu', 'tvshows_submenu', 'search_history')
            and xbmc.getSkinDir() == 'skin.arctic.fuse.3'
            and not _is_hosted()
            and xbmc.getCondVisibility('Window.IsActive(videos)')
            and get_setting_bool(addon, 'af3_catalogue_menus', False)):
        return 'movies'
    return content_type


def af3_view_ids():
    """Resolve semantic choices from the installed skin, across AF3 versions."""
    labels = {
        'list': '31120', 'poster': '31635', 'infowall': '31581',
        'widelist': '31480', 'shift': '31040', 'wall': '31554',
        'iconwall': '31556', 'banner': '31112', 'fanart': '31555', 'gallery': '31111',
    }
    try:
        source = xbmcvfs.File('special://skin/shortcuts/skinviewtypes.json')
        try:
            config = json.loads(source.read())
        finally:
            source.close()
        views = config['viewtypes']
        return {key: int(view_id) for key, label in labels.items()
                for view_id, localize in views.items()
                if str(localize) == label and str(view_id).isascii() and str(view_id).isdecimal()}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        log(f'VIEW MODE - AF3 view configuration unavailable: {exc}', xbmc.LOGWARNING)
        return {}


def configure_af3_views(addon):
    """Let skinvariables persist PLAY.ER's per-content view assignments."""
    if (xbmc.getSkinDir() != 'skin.arctic.fuse.3'
            or not xbmc.getCondVisibility('System.HasAddon(script.skinvariables)')):
        notify_info(addon.getLocalizedString(32907), category='VIEW MODE')
        return False
    contents = ('files', 'movies', 'tvshows', 'seasons', 'episodes', 'videos', 'actors')
    labels = [xbmc.getLocalizedString(label) for label in (744, 342, 20343, 20373, 20360, 3, 344)]
    selected = xbmcgui.Dialog().select(addon.getLocalizedString(32901), labels)
    if selected < 0 or selected >= len(contents):
        return False
    # Native assignments control skin visibility. Addon overrides must yield
    # to them or Container.SetViewMode may select a view excluded by the skin.
    addon.setSettingBool('af3_native_views', True)
    xbmc.executebuiltin('RunScript(script.skinvariables,action=buildviews,pluginname=plugin.video.play_er,contentid={})'.format(contents[selected]))
    return True
