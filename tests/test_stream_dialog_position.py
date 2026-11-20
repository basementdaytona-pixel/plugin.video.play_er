"""A quality dialog must resume at the position reached while it was open."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module
from test_movie_playlist import FakeWindow

dialog = load_module('resources.lib.dialog_stream', ('resources.lib.stream_state',))


class StreamDialogPositionTests(unittest.TestCase):
    def run_dialog(self, selected=True, stopped=False, advanced=False, meta=None, fill_error=False):
        window = FakeWindow()
        player = MagicMock()
        state = {'time': 20.0, 'playing': True, 'file': 'https://example.invalid/original'}
        player.isPlayingVideo.side_effect = lambda: state['playing']
        player.getPlayingFile.side_effect = lambda: state['file']
        player.getTime.side_effect = lambda: state['time']
        self.source_props = {'play_er.link': '123456', 'play_er.provider': 'prehraj.to',
                             'play_er.meta_id': 'cached', 'play_er.media_type': 'episode',
                             'play_er.source_list': 'sources', 'play_er.trakt_id': '456',
                             'play_er.view_video_id': '123456', 'play_er.view_binding': 'synthetic'}
        player.getPlayingItem.return_value.getProperty.side_effect = lambda key: self.source_props.get(key, '')
        dashboard = MagicMock()
        dashboard.selected_url = 'https://example.invalid/720' if selected else None
        dashboard.next_action = None

        def choose():
            state.update(time=65.0, playing=not stopped)
            if advanced:
                state['file'] = 'https://example.invalid/next-episode'

        dashboard.doModal.side_effect = choose
        item = MagicMock()
        factory = MagicMock(return_value=dashboard)
        plugin = MagicMock(handle=1)
        if fill_error:
            plugin.tmdb_client.fill_list_item.side_effect = RuntimeError('synthetic failure')
        with patch.object(dialog.xbmcgui, 'Window', return_value=window), \
             patch.object(dialog.xbmcgui, 'ListItem', return_value=item), \
             patch.object(dialog.xbmc, 'Player', return_value=player), \
             patch.object(dialog, 'get_streams', return_value={'720P': dashboard.selected_url}), \
             patch.object(dialog, 'attach_subtitles') as attach, \
             patch.dict(sys.modules, {'resources.lib.dialog_stream_xml': SimpleNamespace(StreamDashboardXML=factory),
                                      'resources.lib.utils': SimpleNamespace(get_meta_from_cache=lambda key: meta)}):
            dialog.show_stream_menu(plugin)
        self.attach = attach
        self.original_item = player.getPlayingItem.return_value
        self.assertEqual(window.getProperty('play_er.stream_menu_is_open'), '')
        return player, item

    def test_resume_at_position_after_dialog(self):
        player, item = self.run_dialog()
        player.play.assert_called_once()
        item.setProperty.assert_any_call('StartOffset', '65.0')
        player.seekTime.assert_not_called()

    def test_source_assets_survive_missing_or_failed_metadata(self):
        for meta, fill_error in [(None, False), ({'media_type': 'episode'}, False),
                                 ({'media_type': 'episode'}, True)]:
            with self.subTest(meta=meta, fill_error=fill_error):
                player, item = self.run_dialog(meta=meta, fill_error=fill_error)
                player.play.assert_called_once()
                for key, value in self.source_props.items():
                    item.setProperty.assert_any_call(key, value)
                self.attach.assert_called_once_with(item, self.original_item)

    def test_next_episode_is_not_replaced(self):
        player, _ = self.run_dialog(advanced=True)
        player.play.assert_not_called()

    def test_cancel_does_not_restart_playback(self):
        player, _ = self.run_dialog(selected=False)
        player.play.assert_not_called()

    def test_stopped_playback_is_not_restarted(self):
        player, _ = self.run_dialog(stopped=True)
        player.play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
