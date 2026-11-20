"""Per-source stream assets shared by playback, playlists and quality dialogs."""

import json
import re

import xbmc
import xbmcgui


def _source_link(item_or_link):
    if isinstance(item_or_link, str):
        return item_or_link
    if item_or_link is None:
        try:
            item_or_link = xbmc.Player().getPlayingItem()
        except (AttributeError, RuntimeError):
            return ""
    return item_or_link.getProperty("play_er.link") or ""


def source_video_id(item_or_link):
    link = _source_link(item_or_link)
    if link.isdigit():
        return link
    match = re.search(r"([0-9]{5,12})", link)
    return match.group(1) if match else ""


def _uses_prehraj_assets(item_or_link, provider):
    if provider is None and not isinstance(item_or_link, str):
        if item_or_link is None:
            try:
                item_or_link = xbmc.Player().getPlayingItem()
            except (AttributeError, RuntimeError):
                item_or_link = None
        if item_or_link is not None:
            provider = item_or_link.getProperty('play_er.provider')
    # Older queue items did not record a provider; preserve their behavior.
    return not isinstance(provider, str) or not provider.strip() or provider.strip().lower() == 'prehraj.to'


def _read_property(key, expected_type):
    try:
        value = json.loads(xbmcgui.Window(10000).getProperty(key) or "null")
        return value if isinstance(value, expected_type) else expected_type()
    except (TypeError, ValueError):
        return expected_type()


def get_streams(item=None, provider=None):
    if not _uses_prehraj_assets(item, provider):
        return {}
    link = _source_link(item)
    video_id = source_video_id(link)
    if video_id:
        streams = _read_property(f"play_er.qualities.{video_id}", dict)
    elif link:
        return {}
    else:
        streams = _read_property("play_er.current_stream_qualities", dict)
    return {name: url for name, url in streams.items() if isinstance(name, str) and isinstance(url, str) and url}


def get_subtitles(item_or_link=None, provider=None):
    if not _uses_prehraj_assets(item_or_link, provider):
        return []
    video_id = source_video_id(item_or_link)
    if not video_id:
        return []
    paths = _read_property(f"play_er.subtitles.{video_id}", list)
    return [path for path in paths if isinstance(path, str) and path]


def publish_active_streams(item_or_link, provider=None):
    """Only playback activation publishes the legacy current-stream fallback."""
    streams = get_streams(item_or_link, provider=provider)
    window = xbmcgui.Window(10000)
    if streams:
        window.setProperty("play_er.current_stream_qualities", json.dumps(streams))
    else:
        window.clearProperty("play_er.current_stream_qualities")


def attach_subtitles(list_item, source_link, provider=None):
    paths = get_subtitles(source_link, provider=provider)
    if paths:
        list_item.setSubtitles(paths)
