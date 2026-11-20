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
            module.expect_stream(window, monitor.getPlayingFile())
            monitor.onAVStarted()
        self.assertEqual(monitor.current_meta, episode)
        self.assertEqual(window.getProperty('play_er.current_media_type'), 'episode')
        history.assert_called_once_with(episode, 'https://example.invalid/episode', skip_refresh=True)
        return utils

    def test_missing_item_properties_use_current_uuid_and_media_type(self):
        utils = self.exercise_fallback('new-episode-key')
        utils.get_meta_from_cache.assert_called_once_with('new-episode-key')

    def test_foreign_video_after_stop_does_not_reuse_previous_metadata(self):
        module = load_monitor()
        window = FakeWindow()
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'title': 'Episode'}
        window.setProperty('play_er.current_meta', json.dumps(episode))
        window.setProperty('play_er.current_meta_uuid', 'new-episode-key')
        window.setProperty('play_er.current_media_type', 'episode')
        addon = MagicMock()
        addon.getSettingBool.return_value = False
        history = MagicMock()
        monitor = module.KodiPlayerMonitor(session=MagicMock(), addon=addon, save_playback_history_func=history)
        monitor.orchestrator = None
        monitor._start_downgrade_check = MagicMock()
        utils = MagicMock()
        utils.get_meta_from_cache.return_value = episode
        with patch.object(module.xbmcgui, 'Window', return_value=window), \
                patch.object(module, 'get_setting_bool', return_value=False), \
                patch.object(module.threading, 'Timer', return_value=MagicMock()), \
                patch.dict(sys.modules, {'resources.lib.utils': utils}):
            monitor.claim_playback()
            module.expect_stream(window, monitor.getPlayingFile())
            monitor.onAVStarted()
            history.assert_called_once()
            history.reset_mock()
            monitor.onPlayBackStopped()
            monitor.item.getPath.return_value = 'https://other.invalid/unrelated'
            monitor.getPlayingFile = lambda: 'https://other.invalid/unrelated'
            monitor.onAVStarted()
        history.assert_not_called()
        self.assertIsNone(monitor.current_meta)

    def make_active_episode(self):
        module = load_monitor()
        window = FakeWindow()
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2, 'title': 'Episode'}
        window.setProperty('play_er.current_meta', json.dumps(episode))
        window.setProperty('play_er.current_meta_uuid', 'episode-key')
        window.setProperty('play_er.current_media_type', 'episode')
        addon = MagicMock()
        addon.getSettingBool.return_value = False
        history = MagicMock()
        monitor = module.KodiPlayerMonitor(session=MagicMock(), addon=addon, save_playback_history_func=history)
        monitor.orchestrator = None
        monitor._start_downgrade_check = MagicMock()
        utils = MagicMock()
        utils.get_meta_from_cache.return_value = episode
        patchers = [patch.object(module.xbmcgui, 'Window', return_value=window),
                    patch.object(module, 'get_setting_bool', return_value=False),
                    patch.object(module, 'get_streams', return_value={}),
                    patch.object(module.threading, 'Timer', return_value=MagicMock()),
                    patch.dict(sys.modules, {'resources.lib.utils': utils})]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        monitor.claim_playback()
        module.expect_stream(window, monitor.getPlayingFile())
        monitor.onAVStarted()
        history.assert_called_once()
        history.reset_mock()
        return module, window, monitor, history, episode

    def set_playing_url(self, monitor, url):
        monitor.item.getPath.return_value = url
        monitor.getPlayingFile = lambda: url

    def queue_record(self, module, window, monitor, url, meta, owner=None):
        record = {'meta': meta, 'meta_id': 'queued-key', 'trakt_id': '',
                  'media_type': meta['media_type'], 'link': 'queued-source',
                  'owner': monitor._playback_owner if owner is None else owner}
        window.setProperty('play_er.episode_queue_metadata', json.dumps({module.stream_key(url): record}))

    def test_stripped_queue_item_uses_its_provider_for_stream_assets(self):
        module, window, monitor, history, episode = self.make_active_episode()
        next_episode = dict(episode, episode=3)
        url = 'https://example.invalid/next'
        self.queue_record(module, window, monitor, url, next_episode)
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        records[module.stream_key(url)].update(link='123456', provider='webshare.cz')
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        self.set_playing_url(monitor, url)
        with patch.object(module, 'publish_active_streams') as publish:
            monitor.onAVStarted()
        publish.assert_called_once_with('123456', provider='webshare.cz')

    def test_foreign_video_without_stop_releases_monitor_and_keeps_old_progress(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.scrobbling_in_progress = True
        monitor.media_id, monitor.media_type = '77', 'episode'
        monitor.last_known_progress = 0.0
        monitor._queue_scrobble = MagicMock()
        self.set_playing_url(monitor, 'https://other.invalid/unrelated')
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())
        self.assertIsNone(monitor.current_meta)
        self.assertEqual(window.getProperty('play_er.current_meta'), '')
        self.assertEqual(window.getProperty(module.EXPECTED_URL), '')
        self.assertEqual(window.getProperty(module.EXPECTED_OWNER), '')
        monitor._queue_scrobble.assert_called_once_with('stop', '77', 'episode', 0.0, episode)

    def test_paused_backward_seek_then_stop_does_not_mark_episode_watched_without_trakt(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.last_known_progress = 95.0
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(10000, -85000)
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_not_called()

    def test_paused_forward_seek_then_stop_marks_episode_watched_without_trakt(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.last_known_progress = 10.0
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(95000, 85000)
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_called_once_with(episode)

    def test_seek_to_zero_then_stop_does_not_use_an_old_player_time(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.last_known_progress = 95.0
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(0, -95000)
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_not_called()

    def test_pause_samples_progress_without_trakt_before_stop(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.last_known_progress = 20.0
        monitor.getTime = lambda: 95.0
        monitor.onPlayBackPaused()
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_called_once_with(episode)

    def test_pause_does_not_overwrite_seek_target_with_stale_player_time(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.getTime = lambda: 10.0
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(95000, 85000)
        monitor.onPlayBackPaused()
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_called_once_with(episode)

    def test_progress_tick_does_not_replace_backward_seek_with_stale_player_time(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.return_value = False
        monitor.onPlayBackSeek(10000, -85000)
        monitor._update_progress(monitor._playback_item_generation)
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_not_called()

    def test_progress_tick_accepts_clock_after_seek_settles(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.getTime = lambda: 11.0
        module.xbmc.getCondVisibility.return_value = False
        monitor.onPlayBackSeek(10000, -85000)
        monitor._update_progress(monitor._playback_item_generation)
        self.assertEqual(monitor.last_known_progress, 11.0)
        self.assertIsNone(monitor._pending_seek)

    def test_progress_tick_eventually_accepts_clock_if_seek_cannot_settle(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.return_value = False
        with patch.object(module.time, 'monotonic', side_effect=[100.0, 104.0]):
            monitor.onPlayBackSeek(10000, -85000)
            monitor._update_progress(monitor._playback_item_generation)
        self.assertEqual(monitor.last_known_progress, 95.0)
        self.assertIsNone(monitor._pending_seek)

    def test_resuming_after_long_pause_keeps_seek_target_until_clock_settles(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.return_value = True
        with patch.object(module.time, 'monotonic', side_effect=[100.0, 110.0, 111.0]):
            monitor.onPlayBackSeek(10000, -85000)
            monitor.onPlayBackResumed()
            module.xbmc.getCondVisibility.return_value = False
            monitor._update_progress(monitor._playback_item_generation)
        self.assertEqual(monitor.last_known_progress, 10.0)

    def test_buffering_keeps_seek_target_even_after_settle_timeout(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.side_effect = lambda condition: condition == 'Player.Caching'
        with patch.object(module.time, 'monotonic', side_effect=[100.0, 110.0]):
            monitor.onPlayBackSeek(10000, -85000)
            monitor._update_progress(monitor._playback_item_generation)
        self.assertEqual(monitor.last_known_progress, 10.0)
        self.assertIsNotNone(monitor._pending_seek)

    def test_progress_actions_wait_for_seek_to_settle(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.orchestrator = MagicMock()
        monitor.orchestrator.has_triggered.return_value = False
        monitor.play_key = 'episode'
        monitor._trigger_skip_credits = MagicMock()
        monitor._trigger_pre_emptive_scrape = MagicMock()
        monitor.addon.getSettingBool.side_effect = lambda key: key in ('enable_skip_credits', 'enable_pre_emptive_scrape')
        monitor.getTotalTime = lambda: 1000.0
        monitor.getTime = lambda: 100.0
        module.xbmc.getCondVisibility.return_value = False
        module.get_setting_int_with_bounds.return_value = 120
        monitor.onPlayBackSeek(950000, 850000)
        monitor._update_progress(monitor._playback_item_generation)
        monitor.orchestrator.set_triggered.assert_not_called()
        monitor._trigger_skip_credits.assert_not_called()
        monitor._trigger_pre_emptive_scrape.assert_not_called()
        monitor.getTime = lambda: 950.0
        monitor._update_progress(monitor._playback_item_generation)
        monitor._trigger_skip_credits.assert_called_once()
        monitor._trigger_pre_emptive_scrape.assert_called_once()

    def test_cancelled_seek_timer_cannot_start_an_extra_progress_loop(self):
        module, window, monitor, history, episode = self.make_active_episode()
        module.xbmc.getCondVisibility.return_value = False
        monitor.onPlayBackSeek(10000, -85000)
        old_args = module.threading.Timer.call_args.kwargs['args']
        monitor.onPlayBackSeek(50000, 40000)
        module.threading.Timer.reset_mock()
        monitor._update_progress(*old_args)
        module.threading.Timer.assert_not_called()

    def test_pause_invalidates_a_progress_callback_already_in_flight(self):
        module, window, monitor, history, episode = self.make_active_episode()
        module.xbmc.getCondVisibility.return_value = False
        monitor.onPlayBackSeek(10000, -85000)
        old_args = module.threading.Timer.call_args.kwargs['args']
        monitor.onPlayBackPaused()
        module.threading.Timer.reset_mock()
        monitor._update_progress(*old_args)
        module.threading.Timer.assert_not_called()

    def test_current_progress_callback_reschedules_once_after_seek_settles(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.getTime = lambda: 10.0
        module.xbmc.getCondVisibility.return_value = False
        monitor.onPlayBackSeek(10000, -85000)
        old_args = module.threading.Timer.call_args.kwargs['args']
        module.threading.Timer.reset_mock()
        monitor._update_progress(*old_args)
        self.assertEqual(module.threading.Timer.call_count, 1)
        self.assertEqual(module.threading.Timer.call_args.args[0], 15)
        new_args = module.threading.Timer.call_args.kwargs['args']
        module.threading.Timer.reset_mock()
        monitor._update_progress(*old_args)
        module.threading.Timer.assert_not_called()
        monitor.onPlayBackPaused()
        monitor._update_progress(*new_args)
        module.threading.Timer.assert_not_called()

    def test_trakt_seek_to_zero_sends_zero_on_stop(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.scrobbling_in_progress = True
        monitor.media_id, monitor.media_type = '77', 'episode'
        monitor.addon.getSetting.return_value = 'true'
        monitor._queue_scrobble = MagicMock()
        monitor.last_known_progress = 95.0
        monitor.getTime = lambda: 95.0
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(0, -95000)
        monitor.onPlayBackStopped()
        monitor._queue_scrobble.assert_called_once_with('stop', '77', 'episode', 0.0, episode)

    def test_trakt_paused_seek_still_sends_coalesced_pause(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.scrobbling_in_progress = True
        monitor.media_id, monitor.media_type = '77', 'episode'
        monitor.addon.getSetting.return_value = 'true'
        monitor._queue_scrobble = MagicMock()
        monitor.getTime = lambda: 60.0
        module.xbmc.getCondVisibility.return_value = True
        module.threading.Timer.reset_mock()
        monitor.onPlayBackSeek(50000, 40000)
        delay, callback = module.threading.Timer.call_args.args
        self.assertEqual(delay, 1.0)
        self.assertEqual(monitor.last_known_progress, 50.0)
        callback()
        monitor._queue_scrobble.assert_called_once_with(
            'pause', '77', 'episode', 50.0, episode, monitor._playback_item_generation)

    def test_new_item_resets_known_zero_before_stop_fallback(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.mark_watched_func = MagicMock()
        module.xbmc.getCondVisibility.return_value = True
        monitor.onPlayBackSeek(0, -10000)
        url = 'https://example.invalid/next-episode'
        next_episode = dict(episode, episode=3)
        self.queue_record(module, window, monitor, url, next_episode)
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        monitor.getTime = lambda: 95.0
        monitor.onPlayBackStopped()
        monitor.mark_watched_func.assert_called_once_with(next_episode)

    def test_superseded_monitor_does_not_clear_new_owner_metadata(self):
        module, window, monitor, history, episode = self.make_active_episode()
        window.setProperty('play_er.monitor_owner', 'new-owner')
        window.setProperty(module.EXPECTED_OWNER, 'new-owner')
        window.setProperty(module.EXPECTED_URL, 'new-hash')
        window.setProperty('play_er.current_meta', 'new-metadata')
        monitor.release_playback(current_item_changed=True)
        self.assertEqual(window.getProperty('play_er.monitor_owner'), 'new-owner')
        self.assertEqual(window.getProperty(module.EXPECTED_URL), 'new-hash')
        self.assertEqual(window.getProperty('play_er.current_meta'), 'new-metadata')

    def test_temporarily_unavailable_paths_do_not_end_owned_monitor(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.item.getPath.return_value = ''
        def unavailable():
            raise RuntimeError('Kodi has not exposed a path yet')
        monitor.getPlayingFile = unavailable
        monitor.onAVChange()
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, episode)

    def test_foreign_av_change_also_releases_monitor(self):
        module, window, monitor, history, episode = self.make_active_episode()
        self.set_playing_url(monitor, 'https://other.invalid/unrelated')
        monitor.onAVChange()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())

    def test_owned_episode_with_stripped_properties_advances_by_queue_record(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/next-episode'
        next_episode = dict(episode, episode=3, title='Next')
        self.queue_record(module, window, monitor, url, next_episode)
        self.set_playing_url(monitor, url)
        monitor.onAVChange()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, next_episode)
        history.assert_called_once_with(next_episode, 'queued-source', skip_refresh=True)

    def test_propertyless_managed_episode_with_remaining_budget_requests_refill(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/next-episode'
        next_episode = dict(episode, episode=3, _play_er_queue_remaining=1)
        self.queue_record(module, window, monitor, url, next_episode)
        self.set_playing_url(monitor, url)
        module.get_url.return_value = 'plugin://plugin.video.play_er/?action=refill_episode_queue'
        module.xbmc.executebuiltin.reset_mock()
        monitor.onAVStarted()
        module.get_url.assert_called_with(action='refill_episode_queue', meta=json.dumps(next_episode), verify_future='true')
        module.xbmc.executebuiltin.assert_called_once_with(
            'RunPlugin(plugin://plugin.video.play_er/?action=refill_episode_queue)')

    def test_propertyless_episode_with_exhausted_budget_does_not_refill(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/last-episode'
        self.queue_record(module, window, monitor, url, dict(episode, episode=3, _play_er_queue_remaining=0))
        self.set_playing_url(monitor, url)
        module.get_url.reset_mock()
        monitor.onAVStarted()
        module.get_url.assert_not_called()

    def test_explicit_unmanaged_property_does_not_use_queue_fallback(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/unmanaged-episode'
        self.queue_record(module, window, monitor, url, dict(episode, episode=3, _play_er_queue_remaining=1))
        self.set_playing_url(monitor, url)
        monitor.item.getProperty.side_effect = lambda key: 'false' if key == 'play_er.queue_managed' else ''
        module.get_url.reset_mock()
        monitor.onAVStarted()
        module.get_url.assert_not_called()

    def test_explicit_managed_episode_keeps_existing_refill_request(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/managed-episode'
        next_episode = dict(episode, episode=3, _play_er_queue_remaining=1)
        self.queue_record(module, window, monitor, url, next_episode)
        self.set_playing_url(monitor, url)
        monitor.item.getProperty.side_effect = lambda key: 'true' if key == 'play_er.queue_managed' else ''
        module.get_url.reset_mock()
        monitor.onAVStarted()
        module.get_url.assert_called_once_with(action='refill_episode_queue', meta=json.dumps(next_episode))

    def test_owned_movie_with_stripped_properties_uses_its_queue_record(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/next-movie'
        movie = {'tmdb_id': 90, 'media_type': 'movie', 'title': 'Next movie'}
        self.queue_record(module, window, monitor, url, movie)
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        self.assertEqual(monitor.current_meta, movie)
        self.assertEqual(window.getProperty('play_er.current_media_type'), 'movie')
        history.assert_called_once_with(movie, 'queued-source', skip_refresh=True)

    def test_legacy_episode_record_is_accepted_in_current_playlist(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/legacy-next'
        next_episode = dict(episode, episode=3, title='Legacy next')
        self.queue_record(module, window, monitor, url, next_episode)
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        del records[module.stream_key(url)]['owner']
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        module.xbmc.PlayList.return_value.getposition.return_value = 1
        module.xbmc.executeJSONRPC.return_value = json.dumps({'result': {'items': [
            {'file': 'https://example.invalid/episode'}, {'file': url}]}})
        monitor.onPlayBackStopped()
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, next_episode)
        history.assert_called_once_with(next_episode, 'queued-source', skip_refresh=True)

    def test_legacy_episode_waits_for_playlist_position_before_attribution(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/legacy-next'
        next_episode = dict(episode, episode=3, title='Legacy next')
        self.queue_record(module, window, monitor, url, next_episode)
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        del records[module.stream_key(url)]['owner']
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        module.xbmc.PlayList.return_value.getposition.return_value = 0
        module.xbmc.executeJSONRPC.return_value = json.dumps({'result': {'items': [
            {'file': 'https://example.invalid/episode'}, {'file': url}]}})
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertTrue(monitor.owns_playback())
        module.xbmc.PlayList.return_value.getposition.return_value = 1
        monitor.onAVStarted()
        self.assertEqual(monitor.current_meta, next_episode)
        history.assert_called_once()

    def test_legacy_record_from_another_show_is_not_trusted(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://other.invalid/unrelated-legacy'
        self.queue_record(module, window, monitor, url, dict(episode, tmdb_id=99))
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        del records[module.stream_key(url)]['owner']
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())

    def test_explicit_item_metadata_overrides_queue_record_without_cache_key(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/reused-url'
        stale = dict(episode, episode=3, title='Stale queued episode')
        self.queue_record(module, window, monitor, url, stale)
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        records[module.stream_key(url)]['meta_id'] = ''
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        current = dict(episode, episode=4, title='Current item')
        monitor.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'current-key',
                                                            'play_er.media_type': 'episode'}.get(key, '')
        self.set_playing_url(monitor, url)
        utils = MagicMock()
        utils.get_meta_from_cache.return_value = current
        with patch.dict(sys.modules, {'resources.lib.utils': utils}):
            monitor.onAVStarted()
        self.assertEqual(monitor.current_meta, current)
        history.assert_called_once_with(current, url, skip_refresh=True)

    def test_corrupt_owned_queue_record_does_not_inherit_previous_metadata(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/corrupt-queue'
        self.queue_record(module, window, monitor, url, episode)
        records = json.loads(window.getProperty('play_er.episode_queue_metadata'))
        records[module.stream_key(url)]['meta'] = {}
        window.setProperty('play_er.episode_queue_metadata', json.dumps(records))
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())

    def test_queue_record_from_previous_owner_is_not_trusted(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://other.invalid/old-queue'
        self.queue_record(module, window, monitor, url, episode, owner='old-owner')
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())

    def test_seamless_quality_from_known_sources_preserves_monitor(self):
        module, window, monitor, history, episode = self.make_active_episode()
        url = 'https://example.invalid/alternate-quality'
        module.get_streams.return_value = {'720p': url}
        window.setProperty('play_er.seamless_switching', 'true')
        self.set_playing_url(monitor, url)
        monitor.onAVStarted()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, episode)
        self.assertEqual(window.getProperty('play_er.seamless_switching'), '')

    def test_stale_seamless_flag_does_not_claim_foreign_video(self):
        module, window, monitor, history, episode = self.make_active_episode()
        window.setProperty('play_er.seamless_switching', 'true')
        self.set_playing_url(monitor, 'https://other.invalid/unrelated')
        monitor.onAVStarted()
        history.assert_not_called()
        self.assertFalse(monitor.owns_playback())

    def test_foreign_video_while_waiting_for_first_owned_start_is_ignored(self):
        module = load_monitor()
        window = FakeWindow()
        addon = MagicMock()
        addon.getSettingBool.return_value = False
        history = MagicMock()
        monitor = module.KodiPlayerMonitor(session=MagicMock(), addon=addon, save_playback_history_func=history)
        monitor.orchestrator = None
        monitor._start_downgrade_check = MagicMock()
        utils = MagicMock()
        episode = {'tmdb_id': 42, 'media_type': 'episode', 'season': 1, 'episode': 2}
        utils.get_meta_from_cache.return_value = episode
        with patch.object(module.xbmcgui, 'Window', return_value=window), \
                patch.object(module, 'get_setting_bool', return_value=False), \
                patch.object(module.threading, 'Timer', return_value=MagicMock()), \
                patch.dict(sys.modules, {'resources.lib.utils': utils}):
            monitor.claim_playback()
            window.setProperty('play_er.current_meta_uuid', 'episode-key')
            self.set_playing_url(monitor, 'https://other.invalid/unrelated')
            monitor.onAVStarted()
            history.assert_not_called()
            self.assertTrue(monitor.owns_playback())
            self.set_playing_url(monitor, 'https://example.invalid/episode')
            module.expect_stream(window, monitor.getPlayingFile())
            monitor.onAVStarted()
            history.assert_called_once()
            self.assertEqual(monitor.current_meta, episode)

    def test_item_properties_remain_valid_without_window_marker(self):
        module, window, monitor, history, episode = self.make_active_episode()
        window.clearProperty(module.EXPECTED_URL)
        window.clearProperty(module.EXPECTED_OWNER)
        monitor.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'episode-key',
                                                            'play_er.media_type': 'episode'}.get(key, '')
        self.set_playing_url(monitor, 'https://cdn.example.invalid/new-url')
        monitor.onAVStarted()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, episode)

    def test_own_plugin_path_is_recognized_with_stripped_properties(self):
        module, window, monitor, history, episode = self.make_active_episode()
        window.clearProperty(module.EXPECTED_URL)
        window.clearProperty(module.EXPECTED_OWNER)
        monitor.item.getPath.return_value = 'plugin://plugin.video.play_er/?action=play'
        monitor.getPlayingFile = lambda: 'https://cdn.example.invalid/redirected-stream'
        monitor.onAVStarted()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, episode)

    def test_invalid_url_does_not_break_owned_item_detection(self):
        module, window, monitor, history, episode = self.make_active_episode()
        monitor.item.getPath.return_value = 'http://[invalid'
        monitor.item.getProperty.side_effect = lambda key: {'play_er.meta_id': 'episode-key'}.get(key, '')
        monitor.getPlayingFile = lambda: 'http://[invalid'
        monitor.onAVStarted()
        self.assertTrue(monitor.owns_playback())
        self.assertEqual(monitor.current_meta, episode)

    def test_empty_cache_key_uses_published_metadata(self):
        utils = self.exercise_fallback('')
        utils.get_meta_from_cache.assert_not_called()


if __name__ == '__main__':
    unittest.main()
