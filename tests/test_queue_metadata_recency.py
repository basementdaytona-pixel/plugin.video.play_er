"""Recently refreshed per-URL metadata survives bounded queue cache eviction."""
import hashlib
import json
import unittest
from unittest.mock import patch

from test_movie_playlist import FakeWindow, generator


class QueueMetadataRecencyTests(unittest.TestCase):
    def setUp(self):
        self.window = FakeWindow()
        self.window.setProperty('play_er.monitor_owner', 'synthetic-owner')
        patcher = patch.object(generator.xbmcgui, 'Window', return_value=self.window)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def key(number):
        return hashlib.sha256(('https://example.invalid/' + str(number)).encode()).hexdigest()

    def remember(self, number, title='Original', suffix=''):
        generator._remember_playlist_item('https://example.invalid/' + str(number) + suffix,
                                         {'title': title, 'media_type': 'episode'},
                                         'meta', 'trakt', str(number), 'prehraj.to', ('view', 'binding'))

    def records(self):
        return json.loads(self.window.getProperty('play_er.episode_queue_metadata'))

    def test_refreshed_record_survives_next_eviction(self):
        for number in range(25):
            self.remember(number)
        self.remember(0, 'Updated')
        self.remember(25)
        records = self.records()
        self.assertEqual(len(records), 25)
        self.assertIn(self.key(0), records)
        self.assertNotIn(self.key(1), records)
        self.assertEqual(records[self.key(0)]['meta']['title'], 'Updated')
        self.assertEqual(records[self.key(0)]['owner'], 'synthetic-owner')

    def test_refresh_replaces_same_url_without_duplicate_or_payload_loss(self):
        self.remember(0, suffix='|Header=old')
        self.remember(0, 'Updated', '|Header=new')
        records = self.records()
        self.assertEqual(len(records), 1)
        record = records[self.key(0)]
        self.assertEqual(record['meta']['title'], 'Updated')
        self.assertEqual(record['provider'], 'prehraj.to')
        self.assertEqual((record['view_id'], record['view_binding']), ('view', 'binding'))

    def test_malformed_or_wrong_shape_cache_recovers(self):
        for raw in ('broken', '[]', 'null'):
            with self.subTest(raw=raw):
                self.window.setProperty('play_er.episode_queue_metadata', raw)
                self.remember(0)
                self.assertEqual(list(self.records()), [self.key(0)])
