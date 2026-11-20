"""Automatic quality changes must identify the currently playing stream."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_monitor_fallback as support
from test_movie_playlist import FakeWindow


class DowngradeMatchingTests(unittest.TestCase):
    def setUp(self):
        self.module = support.load_monitor()
        self.window = FakeWindow()
        self.addon = MagicMock()
        self.addon.getSettingBool.side_effect = lambda key: key == 'enable_auto_downgrade'
        self.addon.getSetting.return_value = '5'
        self.playlist = MagicMock()
        self.playlist.getposition.return_value = 0
        self.module.xbmc.PlayList.return_value = self.playlist
        self.module.xbmc.getCondVisibility.return_value = True
        self.window_patch = patch.object(self.module.xbmcgui, 'Window', return_value=self.window)
        self.window_patch.start()
        self.addCleanup(self.window_patch.stop)
        self.monitor = self.module.KodiPlayerMonitor(session=MagicMock(), addon=self.addon)
        self.monitor.claim_playback()
        self.monitor.current_meta = {'title': 'Synthetic episode', 'media_type': 'episode'}
        self.monitor.item.getProperty.side_effect = lambda key: '123456' if key == 'play_er.link' else ''
        self.monitor.getTime = lambda: 25.0
        self.monitor._schedule_downgrade_check = MagicMock()
        self.current = ''
        self.monitor.getPlayingFile = lambda: self.current
        self.module.xbmc.executebuiltin.reset_mock()

    def check(self, current, streams):
        self.current = current
        self.module.get_streams.return_value = streams
        self.monitor.is_buffering_since = time.time() - 10
        self.monitor._run_downgrade_check()

    def assert_switch(self, url):
        self.assertEqual(self.playlist.add.call_count, 1)
        self.assertEqual(self.playlist.add.call_args.kwargs['url'].split('|')[0], url)
        self.module.xbmc.executebuiltin.assert_called_once_with('PlayerControl(Next)')
        self.module.attach_subtitles.assert_called_once()

    def test_quality_is_distinguished_by_query_even_on_same_path(self):
        high = 'https://cdn.example.invalid/video?quality=1080&token=synthetic'
        low = 'https://cdn.example.invalid/video?quality=720&token=synthetic'
        self.check(high + '|User-Agent=synthetic', {'1080P': high, '720P': low})
        self.assert_switch(low)

    def test_different_paths_are_not_matched_by_prefix(self):
        high = 'https://cdn.example.invalid/video'
        low = 'https://cdn.example.invalid/video/720'
        self.check(high, {'1080P': high, '720P': low})
        self.assert_switch(low)

    def test_rotated_token_with_one_matching_path_keeps_legacy_fallback(self):
        self.check('https://cdn.example.invalid/1080?token=new',
                   {'1080P': 'https://cdn.example.invalid/1080?token=old',
                    '720P': 'https://cdn.example.invalid/720?token=old'})
        self.assert_switch('https://cdn.example.invalid/720?token=old')

    def test_unknown_redirect_still_uses_lowest_of_multiple_streams(self):
        self.check('https://redirect.example.invalid/video',
                   {'1080P': 'https://cdn.example.invalid/1080', '720P': 'https://cdn.example.invalid/720'})
        self.assert_switch('https://cdn.example.invalid/720')

    def test_ambiguous_queryless_match_is_not_switched(self):
        self.check('https://cdn.example.invalid/video?token=rotated',
                   {'1080P': 'https://cdn.example.invalid/video?quality=1080',
                    '720P': 'https://cdn.example.invalid/video?quality=720'})
        self.playlist.add.assert_not_called()
        self.monitor._schedule_downgrade_check.assert_called_once()

    def test_lowest_stream_is_not_upgraded(self):
        high = 'https://cdn.example.invalid/video?quality=1080'
        low = 'https://cdn.example.invalid/video?quality=720'
        self.check(low, {'1080P': high, '720P': low})
        self.playlist.add.assert_not_called()
        self.monitor._schedule_downgrade_check.assert_called_once()

    def test_equal_quality_alternative_is_skipped(self):
        self.check('https://cdn.example.invalid/720-a',
                   {'720P': 'https://cdn.example.invalid/720-a',
                    '720P alternate': 'https://cdn.example.invalid/720-b',
                    '480P': 'https://cdn.example.invalid/480'})
        self.assert_switch('https://cdn.example.invalid/480')

    def test_4k_is_higher_than_full_hd_and_never_an_upgrade(self):
        streams = {'4k Stream': 'https://cdn.example.invalid/4k',
                   '1080P': 'https://cdn.example.invalid/1080',
                   '720P': 'https://cdn.example.invalid/720'}
        self.check(streams['4k Stream'], streams)
        self.assert_switch(streams['1080P'])
        self.playlist.add.reset_mock()
        self.module.xbmc.executebuiltin.reset_mock()
        self.monitor._schedule_downgrade_check.reset_mock()
        self.check(streams['720P'], streams)
        self.playlist.add.assert_not_called()
        self.monitor._schedule_downgrade_check.assert_called_once()

    def test_8k_downgrades_to_4k(self):
        streams = {'8K Stream': 'https://cdn.example.invalid/8k',
                   '4K Stream': 'https://cdn.example.invalid/4k',
                   '1080P': 'https://cdn.example.invalid/1080'}
        self.check(streams['8K Stream'], streams)
        self.assert_switch(streams['4K Stream'])

    def test_duplicate_url_at_multiple_qualities_uses_next_lower(self):
        shared = 'https://cdn.example.invalid/shared'
        self.check(shared, {'1080P': shared, '720P': shared, '480P': 'https://cdn.example.invalid/480'})
        self.assert_switch('https://cdn.example.invalid/480')

    def test_missing_path_and_single_stream_do_not_trigger_switch(self):
        for current, streams in [('', {'1080P': 'https://cdn.example.invalid/1080',
                                      '720P': 'https://cdn.example.invalid/720'}),
                                 ('https://redirect.example.invalid/video',
                                  {'720P': 'https://cdn.example.invalid/720'})]:
            with self.subTest(current=current):
                self.playlist.add.reset_mock()
                self.monitor._schedule_downgrade_check.reset_mock()
                self.check(current, streams)
                self.playlist.add.assert_not_called()
                self.monitor._schedule_downgrade_check.assert_called_once()

    def test_owner_change_before_switch_does_not_mutate_playlist(self):
        self.current = 'https://cdn.example.invalid/1080'
        def streams(item):
            self.window.setProperty('play_er.monitor_owner', 'new-owner')
            return {'1080P': self.current, '720P': 'https://cdn.example.invalid/720'}
        self.module.get_streams.side_effect = streams
        self.monitor.is_buffering_since = time.time() - 10
        self.monitor._run_downgrade_check()
        self.playlist.add.assert_not_called()
        self.module.xbmc.executebuiltin.assert_not_called()

    def test_manual_quality_change_before_switch_cancels_stale_decision(self):
        high = 'https://cdn.example.invalid/1080'
        low = 'https://cdn.example.invalid/720'
        self.module.attach_subtitles.side_effect = lambda *args: setattr(self, 'current', low)
        self.check(high, {'1080P': high, '720P': low})
        self.playlist.add.assert_not_called()
        self.module.xbmc.executebuiltin.assert_not_called()
        self.module.notify_info.assert_not_called()
        self.monitor._schedule_downgrade_check.assert_called_once()


if __name__ == '__main__':
    unittest.main()
