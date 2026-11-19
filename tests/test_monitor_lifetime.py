"""A foreign stream must not keep an unstarted playback monitor alive."""
import unittest
from unittest.mock import MagicMock, patch

from test_atomic_user_data import plugin


class MonitorLifetimeTests(unittest.TestCase):
    def test_foreign_video_does_not_extend_startup_deadline(self):
        player = MagicMock()
        player.owns_playback.return_value = True
        player.isPlayingVideo.return_value = True
        player._playback_confirmed = False
        stop = MagicMock()
        stop.abortRequested.return_value = False
        with patch.object(plugin.xbmc, 'Monitor', return_value=stop), \
                patch.object(plugin.time, 'monotonic', side_effect=[0.0, 61.0]):
            plugin._wait_for_playback_monitor(player)
        stop.waitForAbort.assert_not_called()
        player.release_playback.assert_called_once()

    def test_confirmed_video_keeps_monitor_until_abort(self):
        player = MagicMock()
        player.owns_playback.return_value = True
        player.isPlayingVideo.return_value = True
        player._playback_confirmed = True
        stop = MagicMock()
        stop.abortRequested.return_value = False
        stop.waitForAbort.return_value = True
        with patch.object(plugin.xbmc, 'Monitor', return_value=stop), \
                patch.object(plugin.time, 'monotonic', side_effect=[0.0, 61.0]):
            plugin._wait_for_playback_monitor(player)
        stop.waitForAbort.assert_called_once_with(0.25)
        player.release_playback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
