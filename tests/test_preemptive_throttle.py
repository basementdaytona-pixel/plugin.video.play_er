"""The configured preemptive interval applies to a show across its seasons."""
import sys
import unittest
from unittest.mock import patch

from kodi_test_support import load_module
from test_movie_playlist import FakeWindow, generator

orchestrator = load_module('resources.lib.monitor_orchestrator', (
    'resources.lib.utils_theme', 'resources.lib.utils',
))


class PreemptiveThrottleTests(unittest.TestCase):
    def setUp(self):
        self.owner = orchestrator.MonitorOrchestrator()
        self.owner.win = FakeWindow()
        self.owner._inc_metric = lambda *args: None

    def test_same_show_is_throttled_across_seasons_but_other_show_is_not(self):
        with patch.object(orchestrator.time, 'time', return_value=1000):
            self.owner.record_preemptive(42, 1)
        with patch.object(orchestrator.time, 'time', return_value=1200):
            self.assertFalse(self.owner.allow_preemptive('42', 2, 600))
            self.assertTrue(self.owner.allow_preemptive(43, 1, 600))

    def test_future_timestamp_does_not_block_after_clock_moves_back(self):
        with patch.object(orchestrator.time, 'time', return_value=1000):
            self.owner.record_preemptive(42, 1)
        with patch.object(orchestrator.time, 'time', return_value=900):
            self.assertTrue(self.owner.allow_preemptive(42, 1, 600))

    def test_configured_interval_and_missing_window_keep_existing_behavior(self):
        with patch.object(orchestrator.time, 'time', return_value=1000):
            self.owner.record_preemptive(42, 1)
        with patch.object(orchestrator.time, 'time', return_value=1599):
            self.assertFalse(self.owner.allow_preemptive(42, 1, 600))
        with patch.object(orchestrator.time, 'time', return_value=1600):
            self.assertTrue(self.owner.allow_preemptive(42, 1, 600))
        self.owner.win = None
        self.assertTrue(self.owner.allow_preemptive(42, 1, 600))

    def test_should_trigger_honors_show_interval_after_season_rollover(self):
        with patch.object(orchestrator.time, 'time', return_value=1000):
            self.owner.record_preemptive(42, 1)
        meta = {'media_type': 'episode', 'tmdb_id': 42, 'season': 2, 'episode': 1}
        with patch.dict(sys.modules, {'resources.lib.generator': generator}), \
             patch.object(orchestrator.time, 'time', return_value=1100):
            self.assertEqual(self.owner.should_trigger_preemptive(meta, None, None, 600), (False, 'throttled'))


if __name__ == '__main__':
    unittest.main()
