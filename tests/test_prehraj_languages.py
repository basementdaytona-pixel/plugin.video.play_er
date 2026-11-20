"""Czech and Slovak audio/subtitle tags use verified language codes."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_provider_responses as provider_support
from kodi_test_support import load_module
from resources.lib.preemptive_scope import source_scope

prehraj = provider_support.prehraj
filters = load_module('resources.lib.utils_filter', ('resources.lib.utils_theme',))


class PrehrajLanguageTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'search_pages': '1', 'search_ls': '32', 'enable_filtering': 'false'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.provider = object.__new__(prehraj.PrehrajTo)
        self.provider.addon = self.addon
        self.provider.base_url = 'https://example.invalid'
        self.provider._access_token = None
        self.provider.get_premium_cookies = MagicMock()
        self.provider.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)

    def search(self, raw):
        self.provider._api_get = MagicMock(return_value=SimpleNamespace(status_code=200, json=lambda: raw))
        return self.provider.search_sources('Example S01E01', apply_filters=False)

    def test_verified_czech_and_slovak_codes_and_region_variants(self):
        codes = [('cz', 'DAB'), ('cs', 'DAB'), ('ces', 'DAB'), ('cze', 'DAB'), ('cs-CZ', 'DAB'),
                 ('sk', 'SK'), ('slo', 'SK'), ('slk', 'SK'), ('sk_SK', 'SK')]
        rows = self.search([{'id': i+1, 'title': 'Video', 'audio': [{'language': code}]}
                            for i, (code, _) in enumerate(codes)])
        self.assertEqual(len(rows), len(codes))
        for row, (code, tag) in zip(rows, codes):
            with self.subTest(language=code):
                self.assertIn(tag, row['tags'])

    def test_named_languages_and_malformed_entries(self):
        rows = self.search([{'id': 1, 'title': 'First', 'audio': [None, {}, {'language': 'ČEŠTINA'}]},
                            {'id': 2, 'title': 'Second', 'audio': [{'language': 'Slovenský'}]},
                            {'id': 3, 'title': 'Third', 'subtitles': [None, {'language': 42}]}])
        self.assertEqual([set(row['tags']) for row in rows], [{'DAB'}, {'SK'}, set()])

    def test_multi_audio_collects_both_languages_in_either_order(self):
        rows = self.search([{'id': 1, 'title': 'First', 'audio': ['sk', 'cz']},
                            {'id': 2, 'title': 'Second', 'audio': ['cz', 'sk']}])
        self.assertEqual([set(row['tags']) for row in rows], [{'DAB', 'SK'}, {'DAB', 'SK'}])

    def test_slovenian_and_unrelated_strings_are_not_misclassified(self):
        for field in ('audio', 'subtitles'):
            raw = [{'id': i+1, 'title': 'Video', field: [{'language': code}]}
                   for i, code in enumerate(('slv', 'sl', 'slovenian', 'es-CS', 'musk', 'unknown'))]
            rows = self.search(raw)
            for row, code in zip(rows, ('slv', 'sl', 'slovenian', 'es-CS', 'musk', 'unknown')):
                with self.subTest(field=field, language=code):
                    self.assertTrue(set(row['tags']).isdisjoint({'DAB', 'SK', 'TIT'}))

    def test_czech_and_slovak_subtitle_tags_keep_title_fallback(self):
        rows = self.search([{'id': 1, 'title': 'Video', 'subtitles': [{'language': 'cz'}]},
                            {'id': 2, 'title': 'Video', 'subtitles': ['slk']},
                            {'id': 3, 'title': 'Video CZ titulky', 'subtitles': []},
                            {'id': 4, 'title': 'Video CZ', 'audio': []}])
        self.assertEqual([set(row['tags']) for row in rows], [{'TIT'}, {'TIT'}, {'TIT'}, {'DAB'}])

    def test_corrected_tags_are_used_by_existing_expression_filter(self):
        rows = self.search([{'id': 1, 'title': 'First', 'audio': ['sk', 'cz']},
                            {'id': 2, 'title': 'Second', 'audio': ['slv']}])
        self.addon.getSettingBool.side_effect = lambda key: key == 'enable_filtering'
        self.settings['exclude_global'] = 'DAB'
        utils = SimpleNamespace(convert_size_to_bytes=lambda value: 0)
        with patch.dict(sys.modules, {'resources.lib.utils': utils}):
            filtered = filters.FilterUtils(self.addon).apply_filters(
                rows, enable_setting_id='enable_filtering', include_setting_ids=[],
                exclude_setting_ids=['exclude_global'])
        self.assertEqual([r['title'] for r in filtered], ['Second'])

    def test_old_preemptive_tags_are_not_reused(self):
        self.settings = {'enable_filtering': 'false', 'prehrajto_api_sort': '1', 'prehrajto_api_quality': '1'}
        self.addon.getSettingBool.return_value = False
        before = '6dba9ec312a5635e40e4a5a77df823d6d15e74f93c8cf9181d26146d93b299a4'
        self.assertNotEqual(source_scope(self.addon, SimpleNamespace(_active_provider_name='prehraj.to')), before)

    def test_playback_prioritizes_czech_slovak_subtitles_without_losing_others(self):
        client = self.provider
        client.addon.getSettingString.return_value = 'auto'
        client.api_get_video_detail = MagicMock(return_value={})
        client.api_get_download_link = MagicMock(return_value={'720P': 'https://example.invalid/video'})
        client.api_get_video_subtitle = MagicMock(return_value=[
            {'name': 'English', 'language': 'en', 'cdnUrl': 'https://example.invalid/en'},
            {'name': 'Slovenian', 'language': 'slv', 'cdnUrl': 'https://example.invalid/sl'},
            {'name': 'Slovak', 'language': 'slk', 'cdnUrl': 'https://example.invalid/sk'},
            {'name': 'Czech', 'language': 'cz', 'cdnUrl': 'https://example.invalid/cz'},
        ])
        client.session = MagicMock()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(prehraj.xbmcvfs, 'translatePath', return_value=directory), \
             patch.object(prehraj.xbmcgui, 'Window', return_value=MagicMock()), \
             patch.object(prehraj, 'safe_get', return_value=SimpleNamespace(content=b'WEBVTT\n')), \
             patch.dict(sys.modules, {'resources.lib.utils_files': SimpleNamespace(ensure_dir=lambda path: os.makedirs(path, exist_ok=True))}):
            url, subtitles = client.get_video_link('123456')
            self.assertEqual(url, 'https://example.invalid/video')
            self.assertEqual([os.path.basename(path) for path in subtitles],
                             ['SLOVAK_2.vtt', 'CZECH_3.vtt', 'ENGLISH_0.vtt', 'SLOVENIAN_1.vtt'])
            self.assertTrue(all(os.path.exists(path) for path in subtitles))


if __name__ == '__main__':
    unittest.main()
