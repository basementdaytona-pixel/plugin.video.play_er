"""Window markers bind a resolved stream to the playback owner without its URL."""
import json
import unittest

from resources.lib.playback_identity import EXPECTED_OWNER, EXPECTED_URL, publish_fallback, stream_key
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


if __name__ == '__main__':
    unittest.main()
