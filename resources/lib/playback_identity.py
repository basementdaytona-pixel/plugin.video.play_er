"""Identify PLAY.ER streams without putting signed URLs in window properties."""
import hashlib
import json

EXPECTED_URL = 'play_er.expected_stream_hash'
EXPECTED_OWNER = 'play_er.expected_stream_owner'
MONITOR_OWNER = 'play_er.monitor_owner'


def stream_key(url):
    if not isinstance(url, str) or not url:
        return ''
    return hashlib.sha256(url.split('|', 1)[0].encode('utf-8')).hexdigest()


def expect_stream(window, url):
    key = stream_key(url)
    if not key:
        return
    window.setProperty(EXPECTED_URL, key)
    window.setProperty(EXPECTED_OWNER, window.getProperty(MONITOR_OWNER))


def publish_fallback(window, url, meta, meta_id, media_type, trakt_id):
    window.setProperty('play_er.current_meta', json.dumps(meta))
    window.setProperty('play_er.current_meta_uuid', str(meta_id or ''))
    window.setProperty('play_er.current_media_type', str(media_type or ''))
    window.setProperty('play_er.current_trakt_id', str(trakt_id or ''))
    expect_stream(window, url)
