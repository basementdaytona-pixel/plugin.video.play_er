"""Protect Skip Credits' Continue handoff when playback changes."""
import importlib.util
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import ROOT, load_module
from test_movie_playlist import FakeWindow, generator as real_generator

orchestrator = load_module('resources.lib.monitor_orchestrator', (
    'resources.lib.utils_theme', 'resources.lib.utils',
))


class SkipCreditsHandoffTests(unittest.TestCase):
    def setUp(self):
        self.window = FakeWindow()
        self.owner = orchestrator.MonitorOrchestrator()
        self.owner.win = self.window
        self.owner.allow_skip_via_episode_playlist = MagicMock(return_value=False)
        self.owner.get_play_key = MagicMock(return_value='episode')
        self.owner.set_state = MagicMock()
        self.owner.perform_next = MagicMock()
        self.addon = MagicMock()
        self.addon.getSetting.return_value = 'false'
        self.tmdb = MagicMock()
        self.tmdb._fetch.return_value = {'name': 'Next'}
        self.meta = {'media_type': 'episode', 'tmdb_id': 42, 'season': 1, 'episode': 1}
        self.player = MagicMock()
        self.player.isPlaying.return_value = False
        self.show_dialog = MagicMock(return_value='PRESKOCIT')
        class KodiPlayer:
            def isPlaying(inner):
                return self.player.isPlaying()
        kodi = SimpleNamespace(Player=KodiPlayer)
        gui = SimpleNamespace(Window=lambda window_id: self.window)
        spec = importlib.util.spec_from_file_location(
            'resources.lib.continue_handoff', ROOT / 'resources/lib/continue_handoff.py')
        self.handoff = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'xbmc': kodi, 'xbmcgui': gui}):
            spec.loader.exec_module(self.handoff)
        real_guard = self.handoff.ContinueHandoffGuard
        self.guards = []
        def make_guard(token):
            guard = real_guard(token)
            self.guards.append(guard)
            return guard
        self.handoff.ContinueHandoffGuard = make_guard
        self.generator = SimpleNamespace(
            get_episode_queue_remaining=lambda meta: None,
            _next_episode_coordinates=lambda *args: (1, 2),
            is_next_episode_queued=lambda *args: False,
        )
        patches = [
            patch.dict(sys.modules, {
                'resources.lib.generator': self.generator,
                'resources.lib.continue_handoff': self.handoff,
                'resources.lib.dialog_skip_credits': SimpleNamespace(show_skip_credits=self.show_dialog),
            }),
            patch.object(orchestrator.xbmc, 'Player', return_value=self.player),
            patch.object(orchestrator.xbmc, 'executebuiltin'),
            patch.object(orchestrator.xbmc, 'sleep'),
            patch.object(orchestrator, 'get_setting_int_with_bounds', return_value=15),
            patch.object(orchestrator, 'get_setting_str', return_value='PRESKOCIT'),
            patch.object(orchestrator, 'get_url', return_value='plugin://plugin.video.play_er/?action=continue_watching_main'),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        orchestrator.xbmc.Monitor.return_value.waitForAbort.return_value = False
        def dispatch(command):
            if command.startswith('RunPlugin('):
                self.window.setProperty(self.handoff.ACK, self.window.getProperty(self.handoff.TOKEN))
        orchestrator.xbmc.executebuiltin.side_effect = dispatch

    def run_handoff(self, is_current=lambda: True):
        return self.owner.handle_skip_credits(self.meta, self.tmdb, self.addon, is_current=is_current)

    def test_successful_fallback_stops_then_launches_continue(self):
        self.assertEqual(self.run_handoff(), ('runplugin', 'skip_action'))
        commands = [c.args[0] for c in orchestrator.xbmc.executebuiltin.call_args_list]
        self.assertEqual(commands[0], 'PlayerControl(Stop)')
        self.assertTrue(commands[1].startswith('RunPlugin('))
        request = orchestrator.get_url.call_args.kwargs
        self.assertEqual(request['automatic'], 'true')
        self.assertEqual(request['action'], 'continue_watching_main')
        self.assertEqual(len(request['handoff_token']), 32)
        self.assertEqual(request['handoff_owner'], '')

    def test_new_playback_during_stop_does_not_launch_continue(self):
        def switch(delay):
            self.player.isPlaying.return_value = True
            self.guards[-1].onAVStarted()
        orchestrator.xbmc.sleep.side_effect = switch
        self.run_handoff()
        commands = [c.args[0] for c in orchestrator.xbmc.executebuiltin.call_args_list]
        self.assertEqual(commands, ['PlayerControl(Stop)'])

    def test_short_replacement_that_stops_before_check_still_cancels(self):
        def switch(delay):
            self.guards[-1].onPlayBackStarted()
            self.player.isPlaying.return_value = False
        orchestrator.xbmc.sleep.side_effect = switch
        self.run_handoff()
        self.assertEqual([c.args[0] for c in orchestrator.xbmc.executebuiltin.call_args_list],
                         ['PlayerControl(Stop)'])

    def test_guard_only_clears_its_own_token_and_ack(self):
        self.window.setProperty(self.handoff.TOKEN, 'new')
        self.window.setProperty(self.handoff.ACK, 'new')
        guard = self.handoff.ContinueHandoffGuard('old')
        guard.onAVStarted()
        guard.clear()
        self.assertEqual(self.window.getProperty(self.handoff.TOKEN), 'new')
        self.assertEqual(self.window.getProperty(self.handoff.ACK), 'new')

    def test_acknowledgement_requires_idle_matching_handoff(self):
        self.window.setProperty(self.handoff.TOKEN, 'token')
        guard = self.handoff.ContinueHandoffGuard('token')
        self.player.isPlaying.return_value = True
        self.assertFalse(guard.acknowledge())
        self.assertEqual(self.window.getProperty(self.handoff.ACK), '')
        self.player.isPlaying.return_value = False
        self.assertTrue(guard.acknowledge())
        self.assertEqual(self.window.getProperty(self.handoff.ACK), 'token')
        guard.onAVStarted()
        self.assertFalse(guard.valid())

    def test_new_manual_playback_owner_cancels_idle_handoff(self):
        self.window.setProperty('play_er.monitor_owner', 'first')
        def change_owner(delay):
            self.window.setProperty('play_er.monitor_owner', 'second')
        orchestrator.xbmc.sleep.side_effect = change_owner
        self.run_handoff(is_current=lambda: self.window.getProperty('play_er.monitor_owner') == 'first')
        self.assertEqual([c.args[0] for c in orchestrator.xbmc.executebuiltin.call_args_list],
                         ['PlayerControl(Stop)'])

    def test_new_playback_owner_invalidates_guard_even_before_playback_starts(self):
        self.window.setProperty(self.handoff.TOKEN, 'token')
        self.window.setProperty('play_er.monitor_owner', 'first')
        guard = self.handoff.ContinueHandoffGuard('token')
        guard.bind_owner('first')
        self.assertTrue(guard.valid())
        self.window.setProperty('play_er.monitor_owner', 'second')
        self.assertFalse(guard.valid())

    def test_failed_stop_does_not_launch_continue(self):
        def execute(command):
            if command == 'PlayerControl(Stop)':
                raise RuntimeError('stop failed')
        orchestrator.xbmc.executebuiltin.side_effect = execute
        self.run_handoff()
        commands = [c.args[0] for c in orchestrator.xbmc.executebuiltin.call_args_list]
        self.assertEqual(commands, ['PlayerControl(Stop)'])

    def test_exhausted_budget_and_last_episode_are_not_skipped(self):
        self.generator.get_episode_queue_remaining = lambda meta: 0
        self.assertEqual(self.run_handoff(), ('none', 'episode_limit'))
        self.generator.get_episode_queue_remaining = lambda meta: None
        self.generator._next_episode_coordinates = lambda *args: None
        self.assertEqual(self.run_handoff(), ('none', 'last_episode'))
        orchestrator.xbmc.executebuiltin.assert_not_called()
        self.show_dialog.assert_not_called()

    def test_numbered_season_keeps_skip_and_preemptive_on_same_season(self):
        self.meta['episode'] = 3
        self.owner.allow_preemptive = MagicMock(return_value=True)
        rows = [{'episode_number': 1}, {'episode_number': 3}, {'episode_number': 4}]
        self.tmdb._fetch.side_effect = lambda path: {'episodes': rows} if path.endswith('/season/1') else None
        with patch.dict(sys.modules, {'resources.lib.generator': real_generator}):
            self.assertEqual(self.owner.should_trigger_preemptive(self.meta, self.tmdb, self.addon), (True, 'ok'))
            self.tmdb._fetch.assert_called_once()
            self.tmdb._fetch.reset_mock()
            self.assertEqual(self.run_handoff(), ('runplugin', 'skip_action'))

    def test_strict_prediction_refuses_unverified_fallback(self):
        self.addon.getSetting.side_effect = lambda key: 'true' if key in (
            'auto_prediction_enable', 'auto_prediction_stop_on_no_match') else 'false'
        self.assertEqual(self.run_handoff(), ('none', 'prediction_end'))
        orchestrator.xbmc.executebuiltin.assert_not_called()
        self.show_dialog.assert_not_called()

    def test_dialog_continue_leaves_episode_playing(self):
        self.show_dialog.return_value = 'POKRACOVAT'
        self.assertEqual(self.run_handoff(), ('none', 'user_continued'))
        orchestrator.xbmc.executebuiltin.assert_not_called()

    def test_changed_playback_after_dialog_is_not_stopped(self):
        current = iter((True, False))
        self.assertEqual(self.run_handoff(is_current=lambda: next(current)), ('none', 'playback_changed'))
        orchestrator.xbmc.executebuiltin.assert_not_called()

    def test_position_change_during_next_episode_lookup_stops_before_dialog(self):
        current = {'value': True}
        def lookup(*args):
            current['value'] = False
            return 1, 2
        self.generator._next_episode_coordinates = lookup
        self.assertEqual(self.run_handoff(is_current=lambda: current['value']),
                         ('none', 'playback_changed'))
        self.show_dialog.assert_not_called()
        self.owner.perform_next.assert_not_called()
        orchestrator.xbmc.executebuiltin.assert_not_called()

    def test_slow_stop_waits_for_original_playback(self):
        self.player.isPlaying.return_value = True
        sleeps = []
        def stop_later(delay):
            sleeps.append(delay)
            if len(sleeps) == 3:
                self.player.isPlaying.return_value = False
        orchestrator.xbmc.sleep.side_effect = stop_later
        self.assertEqual(self.run_handoff(), ('runplugin', 'skip_action'))
        self.assertEqual(sleeps, [500, 100, 100])

    def test_handoff_timeout_invalidates_late_receiver(self):
        orchestrator.xbmc.executebuiltin.side_effect = None
        self.assertEqual(self.run_handoff(), ('none', 'handoff_timeout'))
        self.assertEqual(self.window.getProperty(self.handoff.TOKEN), '')
        self.assertEqual(self.window.getProperty(self.handoff.ACK), '')

    def test_aborted_handoff_clears_its_token(self):
        orchestrator.xbmc.executebuiltin.side_effect = None
        orchestrator.xbmc.Monitor.return_value.waitForAbort.return_value = True
        self.assertEqual(self.run_handoff(), ('none', 'playback_changed'))
        self.assertEqual(self.window.getProperty(self.handoff.TOKEN), '')

    def test_dispatch_error_clears_its_token(self):
        def execute(command):
            if command.startswith('RunPlugin('):
                raise RuntimeError('dispatch failed')
        orchestrator.xbmc.executebuiltin.side_effect = execute
        self.assertEqual(self.run_handoff(), ('error', 'handoff_failed'))
        self.assertEqual(self.window.getProperty(self.handoff.TOKEN), '')

    def test_verified_queued_episode_advances_without_stopping(self):
        self.owner.allow_skip_via_episode_playlist.return_value = True
        self.assertEqual(self.run_handoff(), ('next', 'playlist_next'))
        self.owner.perform_next.assert_called_once()
        orchestrator.xbmc.executebuiltin.assert_not_called()
        self.show_dialog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
