"""A quality dialog must resume at the position reached while it was open."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module
from test_movie_playlist import FakeWindow

dialog = load_module('resources.lib.dialog_stream', ('resources.lib.stream_state',))


class StreamDialogPositionTests(unittest.TestCase):
    def run_dialog(self, selected=True, stopped=False):
        window = FakeWindow()
        player = MagicMock()
        state = {'time': 20.0, 'playing': True}
        player.isPlayingVideo.side_effect = lambda: state['playing']
        player.getTime.side_effect = lambda: state['time']
        player.getPlayingItem.return_value.getProperty.return_value = ''
        dashboard = MagicMock()
        dashboard.selected_url = 'https://example.invalid/720' if selected else None
        dashboard.next_action = None

        def choose():
            state.update(time=65.0, playing=not stopped)

        dashboard.doModal.side_effect = choose
        item = MagicMock()
        factory = MagicMock(return_value=dashboard)
        with patch.object(dialog.xbmcgui, 'Window', return_value=window), \
             patch.object(dialog.xbmcgui, 'ListItem', return_value=item), \
             patch.object(dialog.xbmc, 'Player', return_value=player), \
             patch.object(dialog, 'get_streams', return_value={'720P': dashboard.selected_url}), \
             patch.dict(sys.modules, {'resources.lib.dialog_stream_xml': SimpleNamespace(StreamDashboardXML=factory)}):
            dialog.show_stream_menu(SimpleNamespace(handle=1))
        self.assertEqual(window.getProperty('play_er.stream_menu_is_open'), '')
        return player, item

    def test_resume_at_position_after_dialog(self):
        player, item = self.run_dialog()
        player.play.assert_called_once()
        item.setProperty.assert_any_call('StartOffset', '65.0')
        player.seekTime.assert_not_called()

    def test_cancel_does_not_restart_playback(self):
        player, _ = self.run_dialog(selected=False)
        player.play.assert_not_called()

    def test_stopped_playback_is_not_restarted(self):
        player, _ = self.run_dialog(stopped=True)
        player.play.assert_not_called()


if __name__ == '__main__':
    unittest.main()
