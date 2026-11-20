"""Automatic playback actions must not use a position invalidated by a seek."""
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_monitor_fallback as fallback
from test_skip_credits_handoff import orchestrator as orchestrator_module


class ProgressActionSeekTests(unittest.TestCase):
    def setUp(self):
        self.module, self.window, self.monitor, self.history, self.episode = (
            fallback.MonitorFallbackTests.make_active_episode(self))
        self.orchestrator = orchestrator_module.MonitorOrchestrator()
        self.orchestrator.win = self.window
        self.monitor.orchestrator = self.orchestrator
        self.monitor.play_key = 'episode'
        self.monitor.getTotalTime = lambda: 1000.0
        self.monitor.getTime = lambda: 950.0
        self.monitor.addon.getSettingBool.side_effect = lambda key: key in (
            'enable_skip_credits', 'enable_pre_emptive_scrape')
        self.module.get_setting_int_with_bounds.return_value = 120
        self.module.xbmc.getCondVisibility.return_value = False

    def seek_back(self):
        self.monitor.getTime = lambda: 100.0
        self.monitor.onPlayBackSeek(100000, -850000)

    def test_seek_during_preemptive_cancels_queued_skip_and_allows_later_retry(self):
        def cancelled_preemptive(*args, **kwargs):
            self.seek_back()
            return False
        self.monitor._trigger_pre_emptive_scrape = MagicMock(side_effect=cancelled_preemptive)
        self.monitor._trigger_skip_credits = MagicMock(return_value=True)
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.monitor._trigger_skip_credits.assert_not_called()
        self.assertFalse(self.orchestrator.has_triggered('episode', 'preemptive'))
        self.assertFalse(self.orchestrator.has_triggered('episode', 'skip_credits'))
        self.monitor.getTime = lambda: 950.0
        self.monitor.onPlayBackSeek(950000, 850000)
        self.monitor._trigger_pre_emptive_scrape = MagicMock(return_value=True)
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.monitor._trigger_pre_emptive_scrape.assert_called_once()
        self.monitor._trigger_skip_credits.assert_called_once()

    def test_seek_during_preemptive_metadata_lookup_does_not_dispatch_search(self):
        self.monitor.addon.getSettingBool.side_effect = lambda key: key == 'enable_pre_emptive_scrape'
        def lookup(*args):
            self.seek_back()
            return True, 'ok'
        self.orchestrator.should_trigger_preemptive = MagicMock(side_effect=lookup)
        self.orchestrator.record_preemptive = MagicMock()
        generator = SimpleNamespace(get_preemptive_episode_target=lambda *args: (1, 3))
        self.module.get_url.return_value = 'plugin://plugin.video.play_er/?action=pre_emptive_search'
        self.module.xbmc.executebuiltin.reset_mock()
        with patch.dict(sys.modules, {'resources.lib.generator': generator}):
            self.monitor._update_progress(self.monitor._playback_item_generation)
        self.module.xbmc.executebuiltin.assert_not_called()
        self.orchestrator.record_preemptive.assert_not_called()
        self.assertFalse(self.orchestrator.has_triggered('episode', 'preemptive'))

    def test_seek_during_skip_dialog_invalidates_decision_and_rearms(self):
        self.monitor.addon.getSettingBool.side_effect = lambda key: key == 'enable_skip_credits'
        observations = []
        def dialog(meta, client, addon, is_current):
            self.seek_back()
            observations.append(is_current())
            return ('none', 'playback_changed') if not observations[-1] else ('next', 'incorrect')
        self.orchestrator.handle_skip_credits = MagicMock(side_effect=dialog)
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.assertEqual(observations, [False])
        self.assertFalse(self.orchestrator.has_triggered('episode', 'skip_credits'))
        self.monitor.getTime = lambda: 950.0
        self.monitor.onPlayBackSeek(950000, 850000)
        self.orchestrator.handle_skip_credits = MagicMock(return_value=('next', 'playlist_next'))
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.orchestrator.handle_skip_credits.assert_called_once()
        self.assertTrue(self.orchestrator.has_triggered('episode', 'skip_credits'))

    def test_completed_preemptive_is_kept_when_seek_cancels_later_skip(self):
        def completed_preemptive(*args):
            self.seek_back()
            return True
        self.monitor._trigger_pre_emptive_scrape = MagicMock(side_effect=completed_preemptive)
        self.monitor._trigger_skip_credits = MagicMock()
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.monitor._trigger_skip_credits.assert_not_called()
        self.assertTrue(self.orchestrator.has_triggered('episode', 'preemptive'))
        self.assertFalse(self.orchestrator.has_triggered('episode', 'skip_credits'))

    def test_superseded_owner_does_not_clear_new_owner_triggers(self):
        def replace_owner(*args):
            self.seek_back()
            self.window.setProperty('play_er.monitor_owner', 'new-owner')
            return False
        self.monitor._trigger_pre_emptive_scrape = MagicMock(side_effect=replace_owner)
        self.monitor._trigger_skip_credits = MagicMock()
        with patch.object(self.orchestrator, 'clear_trigger', wraps=self.orchestrator.clear_trigger) as clear:
            self.monitor._update_progress(self.monitor._playback_item_generation)
        clear.assert_not_called()
        self.monitor._trigger_skip_credits.assert_not_called()
        self.assertTrue(self.orchestrator.has_triggered('episode', 'skip_credits'))

    def test_normal_continue_choice_remains_one_shot(self):
        self.monitor.addon.getSettingBool.side_effect = lambda key: key == 'enable_skip_credits'
        self.orchestrator.handle_skip_credits = MagicMock(return_value=('none', 'user_continued'))
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.orchestrator.handle_skip_credits.assert_called_once()
        self.assertTrue(self.orchestrator.has_triggered('episode', 'skip_credits'))

    def test_seek_while_paused_requests_prompt_progress_check_on_resume(self):
        self.monitor.addon.getSettingBool.side_effect = lambda key: key == 'enable_skip_credits'
        def dialog(meta, client, addon, is_current):
            self.module.xbmc.getCondVisibility.return_value = True
            self.seek_back()
            return 'none', 'playback_changed'
        self.orchestrator.handle_skip_credits = MagicMock(side_effect=dialog)
        self.monitor._update_progress(self.monitor._playback_item_generation)
        self.assertFalse(self.orchestrator.has_triggered('episode', 'skip_credits'))
        self.assertIsNone(self.monitor.progress_update_timer)
        self.module.xbmc.getCondVisibility.return_value = False
        self.module.threading.Timer.reset_mock()
        self.monitor.onPlayBackResumed()
        self.assertEqual(self.module.threading.Timer.call_args.args[0], 0.25)

    def test_another_tick_cannot_duplicate_actions_during_cancelled_lookup(self):
        entered, proceed = threading.Event(), threading.Event()
        def lookup(*args):
            entered.set()
            if not proceed.wait(3):
                raise TimeoutError('test did not resume lookup')
            return True, 'ok'
        self.orchestrator.should_trigger_preemptive = MagicMock(side_effect=lookup)
        self.monitor._trigger_skip_credits = MagicMock()
        generator = SimpleNamespace(get_preemptive_episode_target=lambda *args: (1, 3))
        with patch.dict(sys.modules, {'resources.lib.generator': generator}):
            worker = threading.Thread(target=self.monitor._update_progress,
                                      args=(self.monitor._playback_item_generation,))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.monitor.getTime = lambda: 940.0
                self.monitor.onPlayBackSeek(940000, -10000)
                self.monitor._update_progress(self.monitor._playback_item_generation)
            finally:
                proceed.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.orchestrator.should_trigger_preemptive.call_count, 1)
        self.monitor._trigger_skip_credits.assert_not_called()
        self.assertFalse(self.orchestrator.has_triggered('episode', 'preemptive'))
        self.assertFalse(self.orchestrator.has_triggered('episode', 'skip_credits'))


if __name__ == '__main__':
    unittest.main()
