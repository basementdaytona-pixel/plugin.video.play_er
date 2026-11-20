"""Prehraj stream metadata must retain valid qualities and usable URLs."""
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_provider_responses as provider_support
from kodi_test_support import ROOT
from test_movie_playlist import FakeWindow

prehraj = provider_support.prehraj


class PrehrajStreamLinksTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(prehraj.PrehrajTo)
        self.client.addon = MagicMock()
        self.client.addon.getLocalizedString.return_value = 'ALTERNATIVA'
        self.settings = {'prehrajto_stream_mode': 'auto', 'prehrajto_pref_quality': 'highest'}
        self.client.addon.getSettingString.side_effect = lambda key: self.settings.get(key, '')
        self.client.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.client.get_premium_cookies = MagicMock()
        self.client.api_get_video_subtitle = MagicMock(return_value=[])
        self.response = SimpleNamespace(status_code=200, json=lambda: {'data': {}})
        self.client._api_get = MagicMock(side_effect=lambda *args, **kwargs: self.response)
        self.window = FakeWindow()
        self.player = SimpleNamespace(isPlayingVideo=lambda: False)
        self.window_patch = patch.object(prehraj.xbmcgui, 'Window', return_value=self.window)
        self.player_patch = patch.object(prehraj.xbmc, 'Player', return_value=self.player)
        for p in (self.window_patch, self.player_patch):
            p.start()
            self.addCleanup(p.stop)

    def links(self, detail, download=None):
        self.response = SimpleNamespace(status_code=200, json=lambda: {'data': download or {}})
        return self.client.api_get_download_link('123456', detail=detail)

    def resolve(self, detail, download=None):
        self.client.api_get_video_detail = MagicMock(return_value=detail)
        self.response = SimpleNamespace(status_code=200, json=lambda: {'data': download or {}})
        return self.client.get_video_link('123456')

    def test_standard_application_object_preserves_original_and_quality_order(self):
        detail = {'extension': 'mp4', 'links': {'480': 'https://example.invalid/480',
                  '1080': 'https://example.invalid/1080', '720': 'https://example.invalid/720'}}
        links = self.links(detail, {'download_link': 'https://example.invalid/original'})
        self.assertEqual(list(links), ['ORIGINAL (MP4)', '1080P', '720P', '480P'])
        self.assertEqual(links['1080P'], 'https://example.invalid/1080')
        self.client._api_get.assert_called_once_with('videos/123456/download', require_auth=True)

    def test_blank_links_are_dropped_and_surrounding_whitespace_trimmed(self):
        detail = {'links': {'1080': '   ', '720': '  https://example.invalid/720  ',
                            '480': '', 'broken': None}}
        links = self.links(detail, {'download_link': ' \t '})
        self.assertEqual(links, {'720P': 'https://example.invalid/720'})
        url, subtitles = self.resolve(detail, {'download_link': '   '})
        self.assertEqual((url, subtitles), ('https://example.invalid/720', []))
        self.assertEqual(json.loads(self.window.getProperty('play_er.qualities.123456')), links)

    def test_original_url_is_trimmed_before_playback(self):
        links = self.links({'extension': 'mkv', 'links': {}},
                           {'download_link': '  https://example.invalid/original  '})
        self.assertEqual(links, {'ORIGINAL (MKV)': 'https://example.invalid/original'})

    def test_list_exposes_known_and_unknown_distinct_variants(self):
        detail = {'links': [None, {'url': '  '},
                  {'url': ' https://example.invalid/720 ', 'quality': '720p'},
                  {'link': 'https://example.invalid/1080', 'height': 1080},
                  {'url': 'https://example.invalid/4k', 'resolution': '4K'},
                  {'url': 'https://example.invalid/unknown'},
                  {'url': 'https://example.invalid/other'},
                  {'url': 'https://example.invalid/alternate720', 'quality': '720'},
                  {'url': 'https://example.invalid/720', 'quality': '720p'}]}
        links = self.links(detail)
        self.assertEqual(links['2160P'], 'https://example.invalid/4k')
        self.assertEqual(links['1080P'], 'https://example.invalid/1080')
        self.assertEqual(links['720P'], 'https://example.invalid/720')
        self.assertEqual(links['Základní Stream'], 'https://example.invalid/unknown')
        self.assertEqual(set(links.values()), {'https://example.invalid/4k', 'https://example.invalid/1080',
                         'https://example.invalid/720', 'https://example.invalid/unknown',
                         'https://example.invalid/other', 'https://example.invalid/alternate720'})
        alternatives = [key for key in links if key.startswith('ALTERNATIVA ')]
        self.assertEqual(len(alternatives), 2)
        self.assertTrue(all(not any(c.isdigit() for c in key) for key in alternatives))

    def test_legacy_list_and_string_entries_remain_available(self):
        links = self.links({'links': [{'url': 'https://example.invalid/first'},
                                      'https://example.invalid/second']})
        self.assertEqual(links['Základní Stream'], 'https://example.invalid/first')
        self.assertIn('https://example.invalid/second', links.values())

    def test_duplicate_url_can_supply_missing_quality_metadata(self):
        links = self.links({'links': [{'url': 'https://example.invalid/first'},
                                      {'url': 'https://example.invalid/first', 'quality': '720p'},
                                      {'url': 'https://example.invalid/second', 'quality': '1080p'}]})
        self.assertEqual(links, {'1080P': 'https://example.invalid/second',
                                 '720P': 'https://example.invalid/first'})

    def test_alternative_label_has_translations_and_fallback(self):
        for language in ('en_gb', 'cs_cz'):
            text = (ROOT / 'resources' / 'language' / ('resource.language.' + language) / 'strings.po').read_text()
            self.assertEqual(text.count('msgctxt "#32918"'), 1)
        self.client.addon.getLocalizedString.return_value = ''
        links = self.links({'links': ['https://example.invalid/first', 'https://example.invalid/second']})
        self.assertIn('ALTERNATIVE A Stream', links)

    def test_preferred_quality_selects_matching_list_streams(self):
        detail = {'links': [{'url': 'https://example.invalid/720', 'quality': '720p'},
                            {'url': 'https://example.invalid/1080', 'quality': '1080p'},
                            {'url': 'https://example.invalid/4k', 'quality': '4k'}]}
        for pref, expected in [('highest', '4k'), ('lowest', '720'), ('1080p', '1080'),
                               ('720p', '720'), ('original', 'original')]:
            with self.subTest(pref=pref):
                self.settings['prehrajto_pref_quality'] = pref
                url, subtitles = self.resolve(detail, {'download_link': 'https://example.invalid/original'})
                self.assertEqual((url, subtitles), ('https://example.invalid/' + expected, []))

    def test_bandwidth_filter_still_selects_existing_eligible_quality(self):
        self.settings.update(prehrajto_pref_quality='original', max_bandwidth_mbps='1')
        detail = {'size': 100000000, 'length': 60, 'links': [
            {'url': 'https://example.invalid/1080', 'quality': '1080p'},
            {'url': 'https://example.invalid/720', 'quality': '720p'},
            {'url': 'https://example.invalid/480', 'quality': '480p'}]}
        url, _ = self.resolve(detail, {'download_link': 'https://example.invalid/original'})
        self.assertEqual(url, 'https://example.invalid/480')

    def test_saved_playlist_quality_is_preserved(self):
        self.settings['prehrajto_stream_mode'] = 'ask'
        self.window.setProperty('play_er.playlist_quality_choice', '720P')
        detail = {'links': [{'url': 'https://example.invalid/1080', 'quality': '1080p'},
                            {'url': 'https://example.invalid/720', 'quality': '720p'}]}
        url, _ = self.resolve(detail)
        self.assertEqual(url, 'https://example.invalid/720')

    def test_ask_mode_keeps_alternatives_available_for_manual_choice(self):
        self.settings['prehrajto_stream_mode'] = 'ask'
        detail = {'links': [{'url': 'https://example.invalid/first'}, {'url': 'https://example.invalid/second'}]}
        ui = SimpleNamespace(pop_dialog_select=MagicMock(return_value=1))
        with patch.dict(sys.modules, {'resources.lib.utils': ui}):
            url, _ = self.resolve(detail)
        self.assertEqual(url, 'https://example.invalid/second')
        self.assertEqual(len(ui.pop_dialog_select.call_args.args[1]), 2)

    def test_all_blank_urls_fail_without_publishing_invalid_streams(self):
        self.window.setProperty('play_er.qualities.123456', '{"old":"old"}')
        url, subtitles = self.resolve({'links': {'1080': '  ', '720': None}}, {'download_link': ' '})
        self.assertEqual((url, subtitles), (None, []))
        self.assertEqual(self.window.getProperty('play_er.qualities.123456'), '')


if __name__ == '__main__':
    unittest.main()
