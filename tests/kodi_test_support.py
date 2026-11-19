"""Load production modules with only Kodi and unrelated integrations replaced."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, dependencies=()):
    mocks = {key: MagicMock() for key in (
        'xbmc', 'xbmcgui', 'xbmcaddon', 'xbmcplugin', 'xbmcvfs',
        'resources.lib.utils_logging', 'resources.lib.utils_notification',
        *dependencies,
    )}
    mocks['xbmcaddon'].Addon.return_value.getSetting.return_value = ''
    mocks['xbmcvfs'].translatePath.side_effect = lambda path: '/tmp/play-er-test-unused'
    spec = importlib.util.spec_from_file_location(name, ROOT / (name.replace('.', '/') + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**mocks, name: module}):
        spec.loader.exec_module(module)
    return module
