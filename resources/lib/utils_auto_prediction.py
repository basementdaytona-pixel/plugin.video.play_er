"""Optional release affinity for already-filtered automatic episode choices.

No network requests, candidate removal or media metadata rewriting.
Kodi output helpers are imported lazily and cannot interrupt source selection.
The reference is a small private JSON-safe value carried by the existing queue.
"""
import math
import re
import unicodedata
from difflib import SequenceMatcher

REFERENCE = '_play_er_auto_prediction'
_EPISODE = re.compile(r'\bs\d{1,3}[ ._-]*e\d{1,4}\b|\b\d{1,3}x\d{1,4}\b', re.I)
_TECH = re.compile(r'\b(?:\d{3,4}p|[248]k|web[ ._-]*dl|webrip|bluray|bdrip|hdtv|hevc|[hx][ ._-]?26[45])\b', re.I)


def _enabled(addon):
    return str(addon.getSetting('auto_prediction_enable')).lower() == 'true'


def _number(addon, key, default, low, high):
    try:
        value = float(addon.getSetting(key))
        return max(low, min(high, value)) if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _release_name(title):
    title = re.sub(r'\[(?:/?(?:B|I|LIGHT)|/?COLOR[^\]]*)\]', '', str(title or ''), flags=re.I)
    title = ''.join(c for c in unicodedata.normalize('NFKD', title.casefold()) if not unicodedata.combining(c))
    title = title.replace('_', ' ')
    episode = _EPISODE.search(title)
    if not episode:
        return ''  # Generic show/episode titles are not a release fingerprint.
    tail = title[episode.end():]
    tech = _TECH.search(tail)
    if tech:
        tail = tail[tech.start():]  # Episode-specific title is not release identity.
    tail = re.sub(r'\.(?:mkv|mp4|avi|m4v|ts)\s*$', '', tail)
    name = ' '.join(re.findall(r'[a-z0-9]+', tail))[:256]
    if name:
        return name
    # A release can keep all uploader/language/quality information BEFORE SxxEyy.
    prefix = title[:episode.start()]
    evidence = (re.findall(r'\[([^\]]+)\]', prefix) + _TECH.findall(prefix)
                + re.findall(r'\b(?:cz|cs|sk|dab|dabing|dub|eng|en|multi)\b', prefix))
    return ' '.join(re.findall(r'[a-z0-9]+', ' '.join(evidence)))[:256]


def _raw_filename(title):
    """Keep uploader/language/format details from the whole original filename."""
    title = re.sub(r'\[(?:/?(?:B|I|LIGHT)|/?COLOR[^\]]*)\]', '', str(title or ''), flags=re.I)
    title = ''.join(c for c in unicodedata.normalize('NFKD', title.casefold()) if not unicodedata.combining(c))
    title = _EPISODE.sub(' ', title.replace('_', ' '))
    title = re.sub(r'\.(?:mkv|mp4|avi|m4v|ts)\s*$', '', title)
    return ' '.join(re.findall(r'[a-z0-9]+', title))[:256]


def _size(source):
    value = str(source.get('size_str') or '').replace(',', '.').strip()
    match = re.fullmatch(r'([\d.]+)\s*(B|[KMGT]i?B)', value, re.I)
    if not match:
        return None
    try:
        unit = match[2].upper()
        power = 'BKMGT'.index(unit[0]) if unit != 'B' else 0
        result = float(match[1]) * (1024 if 'I' in unit else 1000) ** power
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, OverflowError):
        return None


def capture_reference(meta, source, addon):
    """Seed once from a selected source; never learn a fallback's different release."""
    if not _enabled(addon) or meta.get('media_type') != 'episode' or not meta.get('tmdb_id'):
        return
    old = meta.get(REFERENCE)
    if isinstance(old, dict) and old.get('show') == str(meta['tmdb_id']):
        return
    name = _release_name(source.get('title'))
    if name:
        meta[REFERENCE] = {'show': str(meta['tmdb_id']), 'name': name, 'raw_name': _raw_filename(source.get('title')), 'size': _size(source)}


def _report_selection(meta, addon, selected, target, status, similarity=None):
    """Report one automatic decision, independently of playback and output failures."""
    try:
        season, episode = target if target is not None else (meta.get('season'), meta.get('episode'))
        episode_label = f'S{int(season):02d}E{int(episode):02d}'
    except (TypeError, ValueError):
        episode_label = '?'
    title = str((selected or {}).get('title') or '')
    message = f'PREDICTION - {episode_label} - {status} - filename={title!r}'
    if similarity is not None:
        message += f' - similarity={similarity:.1%}'
    try:
        import xbmc
        from resources.lib.utils_logging import log
        log(message, xbmc.LOGINFO)
    except Exception:
        pass
    try:
        if str(addon.getSetting('auto_prediction_notifications')).lower() == 'false':
            return
        from resources.lib.utils_notification import notify_info
        labels = {
            'MATCH': (32712, 'SELECTED BY SIMILARITY'),
            'NO_MATCH': (32713, 'NO RELIABLE MATCH - STANDARD SELECTION'),
            'NO_REFERENCE': (32714, 'NO REFERENCE - STANDARD SELECTION'),
            'NO_SOURCES': (32715, 'NO SOURCES FOR PREDICTION'),
            'STOP_NO_MATCH': (32719, 'NO RELIABLE MATCH - END OF PLAYLIST'),
            'STOP_NO_REFERENCE': (32720, 'NO REFERENCE - END OF PLAYLIST'),
            'STOP_NO_SOURCES': (32721, 'NO SOURCES - END OF PLAYLIST'),
        }
        label_id, default = labels[status]
        get_label = getattr(addon, 'getLocalizedString', lambda _: '')
        label = get_label(label_id) or default
        filename = title or get_label(32716) or 'NO FILE SELECTED'
        notify_info(f'{episode_label} - {label} : {filename}', category='PREDICTION', time=8000)
    except Exception:
        pass


def select_source(sources, meta, addon, fallback, target=None):
    """Prefer a matching release; optional strict mode rejects unverified successors."""
    if not _enabled(addon) or meta.get('media_type') != 'episode':
        return fallback
    strict = str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true'
    fallback = None if strict else fallback
    def report(selected, status, similarity=None):
        _report_selection(meta, addon, selected, target, status, similarity)
        if strict and str(addon.getSetting('auto_prediction_manual_on_stop')).lower() == 'true':
            try:
                from resources.lib.utils_prediction_handoff import remember_rejection, forget_rejection
                if status.startswith('STOP_'):
                    remember_rejection(meta, addon, target)
                elif status == 'MATCH':
                    forget_rejection(meta, target)
            except Exception:
                pass
    if not sources:
        report(fallback, 'STOP_NO_SOURCES' if strict else 'NO_SOURCES')
        return fallback
    reference = meta.get(REFERENCE)
    if not isinstance(reference, dict) or reference.get('show') != str(meta.get('tmdb_id')):
        report(fallback, 'STOP_NO_REFERENCE' if strict else 'NO_REFERENCE')
        return fallback
    name = reference.get('name')
    if not isinstance(name, str) or not name:
        report(fallback, 'STOP_NO_REFERENCE' if strict else 'NO_REFERENCE')
        return fallback
    threshold = _number(addon, 'auto_prediction_min_similarity', 65, 0, 100) / 100
    tolerance = _number(addon, 'auto_prediction_size_tolerance', 40, 0, 100) / 100
    compare_size = str(addon.getSetting('auto_prediction_compare_size')).lower() != 'false'
    ref_size = reference.get('size')
    if not isinstance(ref_size, (int, float)) or not math.isfinite(ref_size) or ref_size <= 0:
        ref_size = None
    best, best_score = fallback, -1
    best_similarity = None
    ref_tokens = set(name.split())
    for source in sources:
        if target is not None:
            match = _EPISODE.search(str(source.get('title') or '').replace('_', ' '))
            coordinates = tuple(map(int, re.findall(r'\d+', match.group()))) if match else None
            if coordinates != target:
                continue
        candidate = _release_name(source.get('title'))
        if not candidate:
            continue
        tokens = set(candidate.split())
        similarity = .6 * len(tokens & ref_tokens) / len(tokens | ref_tokens) + .4 * SequenceMatcher(None, name, candidate).ratio()
        raw_name = reference.get('raw_name')
        if isinstance(raw_name, str) and raw_name:
            raw_candidate = _raw_filename(source.get('title'))
            raw_tokens, first_tokens = set(raw_candidate.split()), set(raw_name.split())
            raw_similarity = (.6 * len(raw_tokens & first_tokens) / len(raw_tokens | first_tokens)
                              + .4 * SequenceMatcher(None, raw_name, raw_candidate).ratio())
            similarity = .7 * raw_similarity + .3 * similarity
        if similarity < threshold:
            continue
        size = _size(source) if compare_size else None
        deviation = abs(size - ref_size) / ref_size if size and ref_size else None
        if deviation is not None and deviation > tolerance:
            continue
        score = similarity + (.05 * (1 - min(1, deviation)) if deviation is not None else 0)
        if score > best_score:  # Equal scores retain existing filtered/provider order.
            best, best_score = source, score
            best_similarity = similarity
    status = 'MATCH' if best_similarity is not None else ('STOP_NO_MATCH' if strict else 'NO_MATCH')
    report(best, status, best_similarity)
    return best
