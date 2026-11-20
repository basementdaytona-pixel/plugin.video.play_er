"""Window markers bind a resolved stream to the playback owner without its URL."""
import json
import unittest

from resources.lib.playback_identity import (EXPECTED_OWNER, EXPECTED_URL, EXPECTED_SOURCE, EXPECTED_PROVIDER,
                                              EXPECTED_VIEW_ID, EXPECTED_VIEW_BINDING, VIEW_ID, VIEW_BINDING,
                                              publish_fallback, set_view_identity, stream_key)
from test_movie_playlist import FakeWindow


class PlaybackIdentityTests(unittest.TestCase):
    def test_marker_hashes_url_and_preserves_query_identity(self):
        window = FakeWindow()
        window.setProperty('play_er.monitor_owner', 'owner-1')
        url = 'https://example.invalid/video?token=synthetic-secret|User-Agent=Kodi'
        meta = {'tmdb_id': 42, 'media_type': 'episode', 'episode': 2}
        publish_fallback(window, url, meta, 'meta-id', 'episode', 'trakt-id')
        self.assertEqual(window.getProperty(EXPECTED_OWNER), 'owner-1')
        self.assertEqual(window.getProperty(EXPECTED_URL), stream_key(url))
        self.assertEqual(stream_key(url), stream_key(url.split('|', 1)[0]))
        self.assertNotEqual(stream_key(url), stream_key('https://example.invalid/video?token=other'))
        self.assertNotIn('synthetic-secret', str(window.properties))
        self.assertEqual(json.loads(window.getProperty('play_er.current_meta')), meta)

    def test_fallback_view_identity_is_replaced_for_each_source(self):
        window = FakeWindow()
        window.setProperty('play_er.monitor_owner', 'owner-1')
        url = 'https://example.invalid/video?token=synthetic-secret'
        publish_fallback(window, url, {}, '', 'movie', '', source_link='123456',
                         provider='prehraj.to', view_identity=('123456', 'binding'))
        self.assertEqual(window.getProperty(EXPECTED_SOURCE), stream_key('123456'))
        self.assertEqual(window.getProperty(EXPECTED_PROVIDER), 'prehraj.to')
        self.assertEqual(window.getProperty(EXPECTED_VIEW_ID), '123456')
        self.assertEqual(window.getProperty(EXPECTED_VIEW_BINDING), 'binding')
        self.assertNotIn('synthetic-secret', str(window.properties))
        publish_fallback(window, 'https://example.invalid/other', {}, '', 'movie', '')
        self.assertEqual(window.getProperty(EXPECTED_VIEW_ID), '')
        self.assertEqual(window.getProperty(EXPECTED_VIEW_BINDING), '')

    def test_list_item_carries_only_the_view_id_and_binding(self):
        item = FakeWindow()
        set_view_identity(item, ('123456', 'binding'))
        self.assertEqual(item.getProperty(VIEW_ID), '123456')
        self.assertEqual(item.getProperty(VIEW_BINDING), 'binding')


if __name__ == '__main__':
    unittest.main()
