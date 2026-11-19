import importlib.util
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import ROOT


def load(name, mocks):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name.replace('.', '/') + '.py'))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(module)
    return module


class SettingsLifecycleTests(unittest.TestCase):
    def test_idle_settings_change_closes_pool_then_refreshes(self):
        kodi = MagicMock()
        kodi.Monitor = object
        kodi.Player.return_value.isPlaying.return_value = False
        monitor_module = load('resources.lib.settings_monitor', {'xbmc': kodi})
        plugin, cache = MagicMock(), MagicMock()
        events = []
        plugin.reinitialize_clients.side_effect = lambda: events.append('clients')
        cache.close_mysql_pool.side_effect = lambda: events.append('close')
        cache.safe_refresh.side_effect = lambda: events.append('refresh')
        import resources.lib
        with patch.dict(sys.modules, {'resources.lib.plugin': plugin, 'resources.lib.cache_manager': cache}), \
                patch.object(resources.lib, 'cache_manager', cache, create=True):
            monitor_module.SettingsMonitor().onSettingsChanged()
        self.assertEqual(events, ['clients', 'close', 'refresh'])

    def test_playing_settings_change_keeps_pool_and_container(self):
        kodi = MagicMock()
        kodi.Monitor = object
        kodi.Player.return_value.isPlaying.return_value = True
        module = load('resources.lib.settings_monitor', {'xbmc': kodi})
        plugin, cache = MagicMock(), MagicMock()
        import resources.lib
        with patch.dict(sys.modules, {'resources.lib.plugin': plugin, 'resources.lib.cache_manager': cache}), \
                patch.object(resources.lib, 'cache_manager', cache, create=True):
            module.SettingsMonitor().onSettingsChanged()
        plugin.reinitialize_clients.assert_called_once()
        cache.close_mysql_pool.assert_not_called()
        cache.safe_refresh.assert_not_called()

    def test_interpreter_cleanup_closes_pool_before_releasing_addon(self):
        module = load('resources.lib.runtime_cleanup', {})
        cache = SimpleNamespace(ADDON=object(), WINDOW=object(), close_mysql_pool=MagicMock())
        def close():
            self.assertIsNotNone(cache.ADDON)
        cache.close_mysql_pool.side_effect = close
        fake_modules = {'resources.lib.' + key: SimpleNamespace() for key in module._MODULE_ROOTS}
        fake_modules['resources.lib.cache_manager'] = cache
        with patch.dict(sys.modules, fake_modules), patch.object(module.gc, 'collect'):
            module.release_interpreter_objects()
        cache.close_mysql_pool.assert_called_once()
        self.assertIsNone(cache.ADDON)
        self.assertIsNone(cache.WINDOW)
