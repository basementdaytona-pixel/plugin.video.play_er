# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_filter.py
# Author: Mau!X ER
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import re
import unicodedata


from resources.lib.utils_theme import Colors





TAG_MAP = {
    '2160P': ('res', '4K'), '2160': ('res', '4K'), '4K': ('res', '4K'), 'UHD': ('res', '4K'),
    '1080P': ('res', '1080P'), '1080': ('res', '1080P'), 'FHD': ('res', '1080P'), 'FULLHD': ('res', '1080P'),
    '720P': ('res', '720P'), '720': ('res', '720P'), 'HD': ('res', '720P'),
    'KINO': ('source', 'CAM'), 'CAMRIP': ('source', 'CAM'), 'TS': ('source', 'TS'),
    'H265': ('codec', 'H265'), 'HEVC': ('codec', 'H265'), 'X265': ('codec', 'H265'),
    'DAB': ('lang', 'DAB'), 'DABING': ('lang', 'DAB'), 'CZDAB': ('lang', 'DAB'),
    'SK': ('lang', 'SK'), 'SKDAB': ('lang', 'SK'), 'SLOVENSKY': ('lang', 'SK'),
    'TIT': ('sub', 'TIT'), 'TITULKY': ('sub', 'TIT'), 'CZTIT': ('sub', 'TIT'), 'CZ': ('sub', 'CZ'),
    'SUB': ('sub', 'TIT')
}





JUNK_WORDS = {
    'ATMOS', 'DOLBY', 'TRUEHD', 'DDP', 'DDP5', 'DDP7', 'DD', 'AC3', 'AAC', 'DTS', 'DIGITALNE', 'AAC5',
    'MKV', 'MP4', 'AVI', 'WEBM', 'WEB-DL', 'WEBDL', 'WEBRIP', 'BLURAY', 'DVDRIP', 'BRRIP', 'BDRIP',
    'HDR', 'DV', 'PROPER', 'REPACK', 'EXTENDED', 'DIRECTORS', 'CUT', 'ŠPIČKOVA', 'KVALITA', 'TOPKVALITAHD',
    'TOP', 'TOPKVALITA', 'NOVINKA', 'ULTRA', 'WEB', 'DL', 'FULL', 'REMUX', 'HDR10', 'HDR10PLUS', 'DOLBYVISION',
    'DVHDR', 'HLG', 'MULTI', 'DUAL', 'SUBS', 'UNRATED', 'UNCUT', 'LIMITED', 'INTERNAL', 'NETFLIX', 'AMZN',
    'DSNP', 'HULU', 'NF', 'HBO', 'NOVINKY', '6CH', 'KATASTROFICKÝ', 'DOBRODRUŽNÝ', 'ROMANTICKÝ', 'DRAMA',
    'HOROR', 'HORROR', 'KOMEDIE', 'THRILLER', 'AKČNÍ', 'KRIMI', 'SCIFI', 'SCI-FI', 'SCI', 'FI', 'ANIMOVANÝ',
    'DOKUMENT', 'DOKUMENTÁRNÍ', 'RAF', 'ARMA', 'LAZARUS', 'RAFIKKY', 'MOUKIN', 'KOFOLA', 'BYDEJV', 'ARAFAT',
    'MARCELCU', 'SFC007', 'CHMELI', 'PM', 'FASTMOVIE', 'GHDC', 'NOXX', 'NEXSUS', 'RADEEK', 'SIKLER', 'BST',
    'RENNITO', 'OOR', 'PEFTO', 'BY', 'KAMER', 'KABI', 'PLS', 'LIKE', 'SD', 'HDRIP', 'BDRIP',
    'EN', 'RU', 'FR', 'PL', 'DE', 'ES', 'IT', 'ČESKÝ', 'SUPERKVALITA', 'ENG'
}





class FilterUtils:
    def __init__(self, addon):
        self.addon = addon
        self.canonical_map = {}
        for tag, (cat, canonical) in TAG_MAP.items():
            if canonical:
                if canonical not in self.canonical_map:
                    self.canonical_map[canonical] = []
                self.canonical_map[canonical].append(tag)

    def apply_filters(self, videos, enable_setting_id, include_setting_ids, exclude_setting_ids, invert_enable_logic=False):
        try:
            is_enabled = self.addon.getSettingBool(enable_setting_id)
        except Exception:
            is_enabled = str(self.addon.getSetting(enable_setting_id)).lower() in ('true', '1')

        try:
            ascending = self.addon.getSettingBool("sort_by_size_asc")
        except Exception:
            ascending = False

        for idx, v in enumerate(videos):
            if 'original_index' not in v:
                v['original_index'] = idx

        if (invert_enable_logic and is_enabled) or (not invert_enable_logic and not is_enabled):
            return self._sort_videos(videos, keywords=[], ascending=ascending)

        exclude_keywords_raw = [
            k.strip() for setting_id in exclude_setting_ids
            for k in str(self.addon.getSetting(setting_id) or "").split()
            if k.strip()
        ]
        exclude_keywords_expanded = self._expand_keywords(exclude_keywords_raw)

        if exclude_keywords_expanded:
            exclude_pattern = re.compile(r'\b(?:' + '|'.join(map(re.escape, exclude_keywords_expanded)) + r')\b', re.IGNORECASE)
            filtered = []
            for video in videos:
                search_string = video['title'] + " " + " ".join(video.get('tags', [])) + " " + video.get('extension', '')
                if not exclude_pattern.search(search_string):
                    filtered.append(video)
            videos = filtered

        include_keywords_raw = [
            k.strip() for setting_id in include_setting_ids
            for k in str(self.addon.getSetting(setting_id) or "").split()
            if k.strip()
        ]
        include_keywords_expanded = self._expand_keywords(include_keywords_raw)

        return self._sort_videos(videos, keywords=include_keywords_expanded, ascending=ascending)

    def _expand_keywords(self, keywords):
        expanded = set()
        for k in keywords:
            # Keep the literal keyword as well as aliases (e.g. CAM and CAMRIP).
            expanded.add(k)
            k_upper = k.upper()
            if k_upper in self.canonical_map:
                expanded.update(self.canonical_map[k_upper])
        return list(expanded)

    def _sort_videos(self, videos, keywords=None, ascending=False):
        from resources.lib.utils import convert_size_to_bytes

        patterns = []
        if keywords:
            patterns = [re.compile(r'\b' + re.escape(k) + r'\b', re.IGNORECASE) for k in keywords]

        try:
            prioritize_dubbing = self.addon.getSettingBool("prioritize_dubbing")
        except Exception:
            prioritize_dubbing = True

        try:
            sort_by_likes = self.addon.getSettingBool("sort_by_likes")
        except Exception:
            sort_by_likes = True

        def sort_key(video):
            matches = 0
            if patterns:
                search_string = video['title'] + " " + " ".join(video.get('tags', [])) + " " + video.get('extension', '')
                matches = sum(1 for p in patterns if p.search(search_string))

            likes_val = video.get('likes', 0)
            dislikes_val = video.get('dislikes', 0)
            score_val = (likes_val - (dislikes_val * 2)) if sort_by_likes else 0

            is_dubbed = 0
            if prioritize_dubbing:
                tags = video.get('tags', [])
                title_up = video.get('title', '').upper()
                if 'DAB' in tags or 'SK' in tags or 'DAB' in title_up or 'SK ' in title_up or 'CZ ' in title_up:
                    is_dubbed = 1

            size_str = video.get('size_str', '0')
            size = convert_size_to_bytes(size_str)
            size_val = size if size > 0 else float('inf')
            orig_idx = video.get('original_index', 999)

            if ascending:
                return (-matches, -score_val, -is_dubbed, size_val, orig_idx)
            else:
                return (-matches, -score_val, -is_dubbed, orig_idx, -size_val)

        return sorted(videos, key=sort_key)


def encode(string):
    if not string:
        return ""
    line = unicodedata.normalize("NFKD", string)
    return "".join([c for c in line if not unicodedata.combining(c)])


def clean_title_for_tmdb(title):
    s = title.replace("_", " ").replace(".", " ").replace("+", " ").replace("…", "")
    s = encode(s)
    season, episode, ep_end = None, None, None
    ep_match = re.search(r"\b[Ss](\d{1,2})[Ee](\d{1,2})(?:[Ee-][Ee]?(\d{1,2}))?\b|\b(\d{1,2})x(\d{1,2})\b", s, re.IGNORECASE)
    if ep_match:
        if ep_match.group(1):
            season, episode = int(ep_match.group(1)), int(ep_match.group(2))
            ep_end = int(ep_match.group(3)) if ep_match.group(3) else None
        else:
            season, episode = int(ep_match.group(4)), int(ep_match.group(5))
        s = s.replace(ep_match.group(0), "")
    possible_years = re.findall(r"\b(19[5-9]\d|20[0-2]\d)\b", s)
    year = possible_years[-1] if possible_years else None
    if year:
        s = s.replace(year, "")

    junk_pattern = r"[\(\[\{].*?[\)\]\}]|\b(?:" + "|".join([re.escape(k) for k in list(TAG_MAP.keys()) + list(JUNK_WORDS)]) + r")\b"
    s = re.sub(junk_pattern, "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip(" -._")
    return s, year, season, episode, ep_end


def clean_display_title(title, explicit_tags=None, extension=None, likes=0):
    if explicit_tags is None:
        explicit_tags = []
    if not title:
        return title, False, [], None

    s = title.upper()
    s = re.sub(r'\[/?COLOR.*?\]', ' ', s)
    s = re.sub(r'\[/?B\]|\[/?I\]', ' ', s)
    s = s.replace("…", "").replace(".MKV", "").replace(".AVI", "").replace(".MP4", "").replace(".MOV", "")
    s = re.sub(r'[\[\]\|\(\)\._\+\-\…\@]', ' ', s)
    s = re.sub(r'\bH\s?26\d\b', lambda m: m.group(0).replace(" ", ""), s)
    s = re.sub(r'\b\d[ .]\d\b', ' ', s)

    year_match = re.search(r'\b(19[5-9]\d|20[0-2]\d)\b', s)
    year = year_match.group(0) if year_match else None
    if year:
        s = s.replace(year, " ", 1)

    series_match = re.search(r'\b[S](\d{1,2})\s?[E](\d{1,2})\b|\b(\d{1,2})X(\d{1,2})\b', s)
    is_series = bool(series_match)
    series_str = ""
    if is_series:
        if series_match.group(1):
            series_str = f"S{int(series_match.group(1)):02d}E{int(series_match.group(2)):02d}"
        else:
            series_str = f"S{int(series_match.group(3)):02d}E{int(series_match.group(4)):02d}"
        s = s.replace(series_match.group(0), " ", 1)

    words = s.split()
    title_parts = []
    collected_tags = {category: set() for category, _ in TAG_MAP.values()}

    for word in words:
        if word in ['COLOR', 'LIMEGREEN', 'ORANGE', 'WHITE', 'YELLOW']:
            continue
        word = word.lstrip('!')

        if word in TAG_MAP:
            tag_type, tag_value = TAG_MAP[word]
            collected_tags[tag_type].add(tag_value)
        elif word in JUNK_WORDS:
            continue
        else:
            if len(word) >= 1 or word.isdigit():
                title_parts.append(word)

    # Zvýšeno na 20 slov, aby nedocházelo k usekávání reálných víceslovných názvů filmů
    clean_name = " ".join(title_parts[:20])
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()
    final_display_name = clean_name.upper()

    if year:
        final_display_name = f"{final_display_name} ({year})"

    if is_series:
        final_display_name = f"{final_display_name} [COLOR {Colors.ORANGE}] • [/COLOR][COLOR {Colors.LIMEGREEN}]{series_str}[/COLOR]"

    formatted_tags = []
    if likes > 0:
        formatted_tags.append(f"[COLOR {Colors.LIMEGREEN}]{likes}[/COLOR]")

    if extension:
        ext_clean = extension.replace('.', '').upper()
        if ext_clean:
            formatted_tags.append(f"[COLOR {Colors.YELLOW}]{ext_clean}[/COLOR]")

    tags_to_show = []
    if 'DAB' in explicit_tags or 'DAB' in collected_tags['lang']:
        tags_to_show.append('DAB')
    elif 'SK' in explicit_tags or 'SK' in collected_tags['lang']:
        tags_to_show.append('SK')

    if 'TIT' in explicit_tags or 'TIT' in collected_tags['sub']:
        tags_to_show.append('TIT')

    res_priority = ['4K', '1080P', '720P', '2K']
    res_found = False
    for r in res_priority:
        if r in explicit_tags:
            tags_to_show.append(r)
            res_found = True
            break
    if not res_found:
        for r in res_priority:
            if r in collected_tags['res']:
                tags_to_show.append(r)
                break

    if 'H265' in explicit_tags or 'H265' in collected_tags['codec']:
        tags_to_show.append('H265')

    formatted_tags.extend(tags_to_show)

    if formatted_tags:
        suffix = " | ".join(formatted_tags)
        final_title = f"{final_display_name}[COLOR {Colors.ORANGE}]   [ {suffix} ][/COLOR]"
    else:
        final_title = final_display_name

    all_tags_list = list(collected_tags['res']) + list(collected_tags['lang']) + list(collected_tags['sub']) + explicit_tags
    return final_title, is_series, all_tags_list, year
