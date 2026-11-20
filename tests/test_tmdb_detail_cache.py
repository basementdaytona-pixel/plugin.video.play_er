"""Full TMDB detail cache recovers from incomplete or failed entries."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import test_atomic_user_data as atomic_support
import test_tmdb_fetch as tmdb_support

tmdb = tmdb_support.tmdb


class TMDBDetailCacheTests(unittest.TestCase):
    def setUp(self):
        self.client = object.__new__(tmdb.TMDB)
        self.client.api_key, self.client.language = 'synthetic-key', 'cs-CZ'
        self.client.base_url, self.client.session = 'https://example.invalid/3', MagicMock()
        self.client.addon = MagicMock()
        self.client.addon.getSetting.return_value = 'OFF'
        self.storage = {}
        self.cache = MagicMock()
        self.cache.cache_get.side_effect = lambda section, key: self.storage.get((section, key))
        self.cache.cache_set.side_effect = lambda section, key, value: self.storage.__setitem__((section, key), value)
        self.key = ('TMDB', self.client._cache_variant('movie_detail_42'))
        self.full = {'id': 42, 'title': 'Updated', 'credits': {'cast': []}}

    @staticmethod
    def response(data):
        result = MagicMock()
        result.json.return_value = data
        return result

    def test_localized_title_uses_valid_language_tags(self):
        for requested, expected in [('cs', 'cs-CZ'), ('sk', 'sk-SK'), ('en', 'en-US'),
                                    ('fr', 'fr'), ('en_GB', 'en-GB'), ('cs-CZ', 'cs-CZ')]:
            with self.subTest(requested=requested), \
                 patch.object(self.client, 'get_full_details', return_value={'title': 'Translated'}) as details:
                self.assertEqual(self.client.get_localized_title('movie', 42, requested), 'Translated')
                details.assert_called_once_with('movie', 42, lang=expected)

    def test_localized_title_reuses_current_czech_detail_cache(self):
        self.storage[self.key] = self.full
        with patch.object(tmdb, 'cache_manager', self.cache), patch.object(tmdb, 'safe_get') as request:
            self.assertEqual(self.client.get_localized_title('movie', 42, 'cs'), 'Updated')
        request.assert_not_called()

    def test_incomplete_entry_is_refreshed_and_then_reused(self):
        self.storage[self.key] = {'id': 42, 'title': 'Old'}
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', return_value=self.response(self.full)) as request:
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['params']['append_to_response'], 'credits,aggregate_credits')
        self.assertEqual(self.storage[self.key], self.full)

    def test_failed_refresh_preserves_incomplete_cached_metadata_and_retries(self):
        old = {'id': 42, 'title': 'Offline title'}
        self.storage[self.key] = old
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', side_effect=[None, self.response(self.full)]) as request:
            self.assertEqual(self.client.get_full_details('movie', 42), old)
            self.assertEqual(self.storage[self.key], old)
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.storage[self.key], self.full)

    def test_server_error_does_not_replace_cached_metadata(self):
        old = {'id': 42, 'title': 'Offline title'}
        self.storage[self.key] = old
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', return_value=self.response({'status_code': 34, 'success': False})):
            self.assertEqual(self.client.get_full_details('movie', 42), old)
        self.assertEqual(self.storage[self.key], old)
        self.cache.cache_set.assert_not_called()

    def test_incomplete_fresh_response_is_returned_but_not_cached(self):
        incomplete = {'id': 42, 'title': 'Partial'}
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', side_effect=[self.response(incomplete), self.response(self.full)]) as request:
            self.assertEqual(self.client.get_full_details('movie', 42), incomplete)
            self.assertNotIn(self.key, self.storage)
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.storage[self.key], self.full)

    def test_bad_cached_shapes_are_refreshed(self):
        for bad in ({}, [], 17, {'status_code': 34, 'success': False, 'credits': {}}, {'success': False, 'credits': {}}):
            with self.subTest(bad=bad):
                self.storage[self.key] = bad
                with patch.object(tmdb, 'cache_manager', self.cache), \
                        patch.object(tmdb, 'safe_get', return_value=self.response(self.full)) as request:
                    self.assertEqual(self.client.get_full_details('movie', 42), self.full)
                request.assert_called_once()

    def test_new_complete_entry_from_another_writer_avoids_network(self):
        calls = []
        def get(section, key):
            calls.append(key)
            return {'id': 42} if len(calls) == 1 else self.full
        self.cache.cache_get.side_effect = get
        with patch.object(tmdb, 'cache_manager', self.cache), patch.object(tmdb, 'safe_get') as request:
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        request.assert_not_called()
        self.cache.cache_set.assert_not_called()

    def test_late_incomplete_response_does_not_overwrite_complete_entry(self):
        self.storage[self.key] = {'id': 42, 'title': 'Old'}
        def fetch(*args, **kwargs):
            # Another caller completes the cache while this HTTP request is in flight.
            self.storage[self.key] = self.full
            return self.response({'id': 42, 'title': 'Incomplete response'})
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', side_effect=fetch) as request:
            self.assertEqual(self.client.get_full_details('movie', 42)['title'], 'Incomplete response')
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        request.assert_called_once()
        self.cache.cache_set.assert_not_called()

    def test_tv_aggregate_credits_are_complete_in_requested_language(self):
        key = ('TMDB', self.client._cache_variant('tv_detail_42_en-US', 'en-US'))
        self.storage[key] = {'id': 42, 'name': 'Old'}
        data = {'id': 42, 'name': 'New', 'aggregate_credits': {'cast': []}}
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', return_value=self.response(data)) as request:
            self.assertEqual(self.client.get_full_details('tv', 42, lang='en-US'), data)
            self.assertEqual(self.client.get_full_details('tv', 42, lang='en-US'), data)
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs['params']['language'], 'en-US')
        self.assertEqual(self.storage[key], data)

    def test_missing_api_key_can_use_complete_cached_details(self):
        self.client.api_key = ''
        self.storage[self.key] = self.full
        with patch.object(tmdb, 'cache_manager', self.cache), patch.object(tmdb, 'safe_get') as request:
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        request.assert_not_called()

    def test_refresh_does_not_change_other_language_or_filter_variants(self):
        cs = self.key
        en = ('TMDB', self.client._cache_variant('movie_detail_42_en-US', 'en-US'))
        self.storage[cs] = {'id': 42, 'title': 'Český'}
        en_details = {'id': 42, 'title': 'English', 'aggregate_credits': {}}
        self.storage[en] = en_details
        with patch.object(tmdb, 'cache_manager', self.cache), \
                patch.object(tmdb, 'safe_get', return_value=self.response(self.full)) as request:
            self.assertEqual(self.client.get_full_details('movie', 42, lang='en-US'), en_details)
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
            self.client.addon.getSetting.return_value = 'HARD'
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.storage[en], en_details)

    def test_real_sqlite_persists_repaired_details(self):
        cache = atomic_support.cache
        with tempfile.TemporaryDirectory() as directory, \
             patch.multiple(cache, CACHE_DB_PATH=str(Path(directory) / 'cache.db'), DB_TYPE='SQLite', SQLITE_INITIALIZED=False), \
             patch.object(tmdb, 'cache_manager', cache), \
             patch.object(tmdb, 'safe_get', return_value=self.response(self.full)) as request:
            cache.clear_ram_cache()
            cache.cache_set(*self.key, {'id': 42, 'title': 'Old'})
            cache.clear_ram_cache()
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
            cache.clear_ram_cache()
            self.assertEqual(self.client.get_full_details('movie', 42), self.full)
            self.assertEqual(cache.cache_get(*self.key), self.full)
            request.assert_called_once()
            cache.clear_ram_cache()


if __name__ == '__main__':
    unittest.main()
