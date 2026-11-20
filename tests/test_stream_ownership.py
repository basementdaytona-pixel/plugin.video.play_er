"""Source-specific stream metadata with synthetic colliding provider IDs."""
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module
from test_movie_playlist import FakeWindow
from test_atomic_user_data import actions

stream_state = load_module('resources.lib.stream_state')


class StreamOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.window = FakeWindow()
        self.window.setProperty('play_er.qualities.123456', json.dumps({'1080P': 'https://example.invalid/prehraj'}))
        self.window.setProperty('play_er.subtitles.123456', json.dumps(['/tmp/prehraj.vtt']))
        self.window.setProperty('play_er.current_stream_qualities', json.dumps({'OLD': 'https://example.invalid/old'}))
        patcher = patch.object(stream_state.xbmcgui, 'Window', return_value=self.window)
        patcher.start()
        self.addCleanup(patcher.stop)

    def item(self, provider, link='123456'):
        item = MagicMock()
        props = {'play_er.link': link, 'play_er.provider': provider}
        item.getProperty.side_effect = lambda key: props.get(key, '')
        return item

    def test_numeric_webshare_id_cannot_use_prehraj_assets(self):
        item = self.item('webshare.cz')
        self.assertEqual(stream_state.get_streams(item), {})
        self.assertEqual(stream_state.get_subtitles(item), [])
        stream_state.publish_active_streams(item)
        self.assertEqual(self.window.getProperty('play_er.current_stream_qualities'), '')

    def test_explicit_provider_prevents_attaching_other_provider_subtitles(self):
        item = MagicMock()
        stream_state.attach_subtitles(item, '123456', provider='webshare.cz')
        item.setSubtitles.assert_not_called()
        stream_state.attach_subtitles(item, '123456', provider='prehraj.to')
        item.setSubtitles.assert_called_once_with(['/tmp/prehraj.vtt'])

    def test_prehraj_and_legacy_items_keep_their_assets(self):
        for provider in ('prehraj.to', ''):
            with self.subTest(provider=provider):
                item = self.item(provider)
                self.assertEqual(stream_state.get_streams(item), {'1080P': 'https://example.invalid/prehraj'})
                self.assertEqual(stream_state.get_subtitles(item), ['/tmp/prehraj.vtt'])

    def test_explicit_provider_overrides_missing_item_property(self):
        self.assertEqual(stream_state.get_streams('123456', provider='webshare.cz'), {})
        stream_state.publish_active_streams('123456', provider='webshare.cz')
        self.assertEqual(self.window.getProperty('play_er.current_stream_qualities'), '')

    def test_quality_switch_preserves_provider_and_passes_source_item(self):
        original = self.item('prehraj.to')
        switched = MagicMock()
        player = MagicMock()
        player.isPlayingVideo.return_value = True
        player.getPlayingItem.return_value = original
        player.getTime.return_value = 20
        kodi = MagicMock()
        kodi.Player.return_value = player
        gui = MagicMock()
        gui.Window.return_value = self.window
        gui.ListItem.return_value = switched
        self.window.setProperty('play_er.current_meta', json.dumps({'media_type': 'episode'}))
        plugin = MagicMock()
        modules = {'xbmc': kodi, 'xbmcgui': gui,
                   'resources.lib.utils': SimpleNamespace(pop_dialog_select=lambda *args: 1),
                   'resources.lib.utils_notification': MagicMock()}
        with patch.dict(sys.modules, modules), \
             patch.object(actions, 'get_streams', return_value={'1080P': 'https://example.invalid/a',
                                                              '720P': 'https://example.invalid/b'}), \
             patch.object(actions, 'attach_subtitles') as attach:
            actions.change_stream_quality({}, plugin)
        switched.setProperty.assert_any_call('play_er.provider', 'prehraj.to')
        attach.assert_called_once_with(switched, original)
        player.play.assert_called_once()
        player.seekTime.assert_called_once_with(20)

    def test_quality_selection_does_not_replace_changed_or_stopped_playback(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                player = MagicMock()
                state = {'file': 'https://example.invalid/original', 'playing': True}
                player.isPlayingVideo.side_effect = lambda: state['playing']
                player.getPlayingFile.side_effect = lambda: state['file']

                def choose(*args):
                    state.update(file='https://example.invalid/next', playing=not stopped)
                    return 1

                kodi = MagicMock()
                kodi.Player.return_value = player
                gui = MagicMock()
                gui.Window.return_value = self.window
                modules = {'xbmc': kodi, 'xbmcgui': gui,
                           'resources.lib.utils': SimpleNamespace(pop_dialog_select=choose),
                           'resources.lib.utils_notification': MagicMock()}
                with patch.dict(sys.modules, modules), \
                     patch.object(actions, 'get_streams', return_value={'1080P': 'a', '720P': 'b'}):
                    actions.change_stream_quality({}, MagicMock())
                player.stop.assert_not_called()
                player.play.assert_not_called()
                self.assertEqual(self.window.getProperty('play_er.seamless_switching'), '')


if __name__ == '__main__':
    unittest.main()
