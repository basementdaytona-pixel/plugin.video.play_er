"""Subtitle hints must not acquire the local dubbing sort preference."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

filters = load_module('resources.lib.utils_filter', ('resources.lib.utils_theme',))


class DubbingSortTests(unittest.TestCase):
    def setUp(self):
        self.addon = MagicMock()
        self.addon.getSettingBool.side_effect = lambda key: key == 'prioritize_dubbing'
        self.filters = filters.FilterUtils(self.addon)

    def sort(self, *rows):
        for index, row in enumerate(rows):
            row.setdefault('original_index', index)
        utils = SimpleNamespace(convert_size_to_bytes=lambda value: 0)
        with patch.dict(sys.modules, {'resources.lib.utils': utils}):
            return self.filters._sort_videos(list(rows))

    def test_subtitles_do_not_outrank_unknown_audio(self):
        for title in ('Film CZ titulky', 'Film SK sub', 'Film CZTIT',
                      'Film CZ subtitles', 'Film_SK_titulky'):
            with self.subTest(title=title):
                first = {'title': 'Unknown audio'}
                self.assertIs(self.sort(first, {'title': title})[0], first)

    def test_subtitle_metadata_blocks_ambiguous_filename_hint(self):
        first = {'title': 'Unknown audio'}
        self.assertIs(self.sort(first, {'title': 'Film CZ', 'tags': ['TIT']})[0], first)

    def test_explicit_audio_still_outranks_subtitles(self):
        for audio in ({'title': 'Film', 'tags': ['DAB', 'TIT']},
                      {'title': 'Film', 'tags': ['SK', 'TIT']},
                      {'title': 'Film CZ dabing + titulky', 'tags': ['TIT']},
                      {'title': 'Film SKDAB'}, {'title': 'Film_DAB'},
                      {'title': 'Film CZ'}, {'title': 'Film SK'}):
            with self.subTest(audio=audio):
                self.assertIs(self.sort({'title': 'Film CZ titulky'}, audio)[0], audio)

    def test_unrelated_title_substrings_are_not_dubbing(self):
        for title in ('Dabangg', 'Task Force', 'Mask of Zorro'):
            with self.subTest(title=title):
                first = {'title': 'Unknown audio'}
                self.assertIs(self.sort(first, {'title': title})[0], first)

    def test_disabled_preference_preserves_order(self):
        self.addon.getSettingBool.return_value = False
        self.addon.getSettingBool.side_effect = None
        first = {'title': 'Film CZ titulky'}
        self.assertIs(self.sort(first, {'title': 'Film', 'tags': ['DAB']})[0], first)

    def test_likes_keep_existing_priority_over_dubbing(self):
        self.addon.getSettingBool.side_effect = lambda key: key in ('prioritize_dubbing', 'sort_by_likes')
        first = {'title': 'Film CZ titulky', 'likes': 10}
        self.assertIs(self.sort(first, {'title': 'Film', 'tags': ['DAB'], 'likes': 1})[0], first)


if __name__ == '__main__':
    unittest.main()
