"""One-shot playback triggers must follow the monitor that owns the item."""
import unittest

import test_monitor_fallback as fallback
from test_skip_credits_handoff import orchestrator as orchestrator_module


class TriggerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.module, self.window, self.monitor, self.history, self.episode = (
            fallback.MonitorFallbackTests.make_active_episode(self))
        self.orchestrator = orchestrator_module.MonitorOrchestrator()
        self.orchestrator.win = self.window
        self.monitor.orchestrator = self.orchestrator
        self.key = self.orchestrator.get_play_key(self.episode)
        self.monitor.play_key = self.key
        self.orchestrator.set_triggered(self.key, 'skip_credits')
        self.orchestrator.set_triggered(self.key, 'preemptive')

    def test_release_clears_owned_triggers_without_stop_callback(self):
        self.monitor.release_playback(current_item_changed=True)
        self.assertFalse(self.orchestrator.has_triggered(self.key, 'skip_credits'))
        self.assertFalse(self.orchestrator.has_triggered(self.key, 'preemptive'))
        self.assertIsNone(self.monitor.play_key)

    def test_superseded_release_does_not_clear_new_owner_triggers(self):
        self.window.setProperty('play_er.monitor_owner', 'new-owner')
        self.monitor.release_playback(current_item_changed=True)
        self.assertTrue(self.orchestrator.has_triggered(self.key, 'skip_credits'))
        self.assertTrue(self.orchestrator.has_triggered(self.key, 'preemptive'))

    def test_direct_next_episode_releases_only_previous_episode_triggers(self):
        url = 'https://example.invalid/next-episode'
        next_episode = dict(self.episode, episode=3)
        next_key = self.orchestrator.get_play_key(next_episode)
        self.orchestrator.set_triggered(next_key, 'skip_credits')
        fallback.MonitorFallbackTests.queue_record(self, self.module, self.window, self.monitor, url, next_episode)
        fallback.MonitorFallbackTests.set_playing_url(self, self.monitor, url)
        self.monitor.onAVStarted()
        self.assertFalse(self.orchestrator.has_triggered(self.key, 'skip_credits'))
        self.assertFalse(self.orchestrator.has_triggered(self.key, 'preemptive'))
        self.assertTrue(self.orchestrator.has_triggered(next_key, 'skip_credits'))
        self.assertEqual(self.monitor.play_key, next_key)

    def test_repeated_callback_for_same_episode_preserves_one_shot_state(self):
        self.monitor.onAVStarted()
        self.assertTrue(self.orchestrator.has_triggered(self.key, 'skip_credits'))
        self.assertTrue(self.orchestrator.has_triggered(self.key, 'preemptive'))


if __name__ == '__main__':
    unittest.main()
