"""Identify PLAY.ER streams without putting signed URLs in window properties."""
import hashlib
import json

EXPECTED_URL = 'play_er.expected_stream_hash'
EXPECTED_OWNER = 'play_er.expected_stream_owner'
MONITOR_OWNER = 'play_er.monitor_owner'
EXPECTED_SOURCE = 'play_er.expected_source_hash'
EXPECTED_PROVIDER = 'play_er.expected_source_provider'
EXPECTED_VIEW_ID = 'play_er.expected_view_id'
EXPECTED_VIEW_BINDING = 'play_er.expected_view_binding'
VIEW_ID = 'play_er.view_video_id'
VIEW_BINDING = 'play_er.view_binding'


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


def set_view_identity(item, identity):
    if identity:
        item.setProperty(VIEW_ID, identity[0])
        item.setProperty(VIEW_BINDING, identity[1])


def publish_fallback(window, url, meta, meta_id, media_type, trakt_id, source_link='', provider='', view_identity=None):
    window.setProperty('play_er.current_meta', json.dumps(meta))
    window.setProperty('play_er.current_meta_uuid', str(meta_id or ''))
    window.setProperty('play_er.current_media_type', str(media_type or ''))
    window.setProperty('play_er.current_trakt_id', str(trakt_id or ''))
    window.setProperty(EXPECTED_SOURCE, stream_key(source_link))
    window.setProperty(EXPECTED_PROVIDER, str(provider or ''))
    window.setProperty(EXPECTED_VIEW_ID, view_identity[0] if view_identity else '')
    window.setProperty(EXPECTED_VIEW_BINDING, view_identity[1] if view_identity else '')
    expect_stream(window, url)
