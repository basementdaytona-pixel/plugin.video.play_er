"""Playback monitor consumes Kodi's window fallback if ListItem fields are absent."""
import importlib.util
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

from kodi_test_support import ROOT
from test_movie_playlist import FakeWindow


class FakeKodiPlayer:
    def __init__(self):
        self.item = MagicMock()
        self.item.getProperty.return_value = ''
        self.item.getPath.return_value = 'https://example.invalid/episode'

    def getPlayingItem(self):
        return self.item

    def getPlayingFile(self):
        return 'https://example.invalid/episode|User-Agent=synthetic'

    def isPlayingVideo(self):
        return True

    def isPlaying(self):
        return True

    def getTime(self):
        return 10

    def getTotalTime(self):
        return 100


def load_monitor():
    names = ('xbmc', 'xbmcgui', 'xbmcaddon', 'xbmcplugin', 'xbmcvfs',
             'resources.lib.sf_context_style', 'resources.lib.monitor_orchestrator',
             'resources.lib.utils_logging', 'resources.lib.stream_state',
             'resources.lib.utils_files', 'resources.lib.utils_notification',
             'resources.lib.utils_settings', 'resources.lib.utils_theme', 'resources.lib.utils')
    mocks = {name: MagicMock() for name in names}
    mocks['xbmc'].Player = FakeKodiPlayer
    mocks['xbmcaddon'].Addon.return_value.getSetting.return_value = ''
    mocks['xbmcvfs'].translatePath.return_value = '/tmp/play-er-test-unused'
    spec = importlib.util.spec_from_file_location('play_er_monitor_fallback_test', ROOT / 'resources/lib/trakt.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, mocks):
        spec.loader.exec_module(module)
    return module


class MonitorFallbackTests(unittest.TestCase):
    def exercise_fallback(self, meta_key):
        module = load_monitor()
        window = FakeWindow()
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'title': 'Episode'}
        window.setProperty('play_er.current_meta', json.dumps(episode))
        window.setProperty('play_er.current_meta_uuid', meta_key)
        window.setProperty('play_er.current_media_type', 'episode')
        window.setProperty('play_er.current_trakt_id', '')
        addon = MagicMock()
        addon.getSettingBool.return_value = False
        history = MagicMock()
        monitor = module.KodiPlayerMonitor(session=MagicMock(), addon=addon, save_playback_history_func=history)
        monitor.orchestrator = None
        monitor._start_downgrade_check = MagicMock()
        utils = MagicMock()
        utils.get_meta_from_cache.side_effect = lambda key: {'new-episode-key': episode}[key]
        with patch.object(module.xbmcgui, 'Window', return_value=window), \
                patch.object(module, 'get_setting_bool', return_value=False), \
                patch.object(module.threading, 'Timer', return_value=MagicMock()), \
                patch.dict(sys.modules, {'resources.lib.utils': utils}):
            monitor.claim_playback()
            monitor.onAVStarted()
        self.assertEqual(monitor.current_meta, episode)
        self.assertEqual(window.getProperty('play_er.current_media_type'), 'episode')
        history.assert_called_once_with(episode, 'https://example.invalid/episode', skip_refresh=True)
        return utils

    def test_missing_item_properties_use_current_uuid_and_media_type(self):
        utils = self.exercise_fallback('new-episode-key')
        utils.get_meta_from_cache.assert_called_once_with('new-episode-key')

    def test_empty_cache_key_uses_published_metadata(self):
        utils = self.exercise_fallback('')
        utils.get_meta_from_cache.assert_not_called()


if __name__ == '__main__':
    unittest.main()
