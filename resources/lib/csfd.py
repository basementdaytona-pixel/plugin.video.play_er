# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: csfd.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import re
import random
import requests

import xbmc

from bs4 import BeautifulSoup

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)


from resources.lib.utils import safe_get, get_threadpool
from resources.lib import cache_manager


from resources.lib.utils_logging import (
    log
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)





CSFD_TIPS_URL = "https://www.csfd.cz/televize/"
BASE_URL = "https://www.csfd.cz/"
CSFD_ID_REGEX = r"/film/(\d+)-"
TIMEOUT = 30






class CSFD:

    """
    CLASS :: CSFD
    -- Class module CSFD database.
    """


    def __init__(self, addon_obj, tmdb_client):
        self.addon = addon_obj
        self.tmdb_client = tmdb_client
        self.base_url = BASE_URL

        log("CSFD - Vytvářím standardní 'requests.Session'", level=xbmc.LOGDEBUG)
        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": "CSFD-Mobile-App/3.4.5 (Android 13; Build/1002)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "cs-CZ,cs;q=0.9",
            "Connection": "keep-alive"
        })


        self.cache_dir = ""


    def get_daily_tips(self, progress_callback=None):

        """
        CSFD :: CSFD TIPS
        -- Získá detaily pro položky dnešní tipy ČSFD.
        -- Optimalizováno: Window Cache -> SSD Cache -> Web Scraping.
        """

        log("CSFD - Starting get_daily_tips", level=xbmc.LOGDEBUG)
        cache_key = "daily_tips"


        w_data = cache_manager.window_cache_get(cache_key)
        if w_data:
            log("CSFD - WIDGET CACHE HIT: Vracím tipy z paměti okna", level=xbmc.LOGDEBUG)
            return w_data


        cached_data = cache_manager.cache_get("CSFD", cache_key)
        if cached_data:
            log("CSFD - SSD CACHE HIT: Vracím tipy z disku", level=xbmc.LOGDEBUG)
            cache_manager.window_cache_set(cache_key, cached_data)
            return cached_data


        url = CSFD_TIPS_URL

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "cs-CZ,cs;q=0.8,en-US;q=0.5,en;q=0.3",
            "Referer": self.base_url,
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        try:
            response = safe_get(self.session, url, headers=headers, timeout=TIMEOUT)
            if not response:
                log("CSFD - Failed to get daily tips (network error)", level=xbmc.LOGERROR)
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            tips_section = None

            selectors = [
                ("section", {"id": "tv-tip"}),
                ("div", {"class": "box box-tv-tip"}),
                ("div", {"class": "tv-tips-container"}),
                ("div", {"class": "tv-tip-box"}),
                ("section", {"class": "tv-tips"}),
                ("div", {"class": "box-content tv-tips"}),
                ("div", {"class": lambda x: x and ("tip" in x.lower() or "tv" in x.lower())}),
                ("section", {"class": lambda x: x and ("tip" in x.lower() or "tv" in x.lower())}),
            ]

            for tag, attrs in selectors:
                tips_section = soup.find(tag, attrs)
                if tips_section:
                    log(f"CSFD - Found tips section with selector : {tag} {attrs}", level=xbmc.LOGDEBUG)
                    break
            if not tips_section:
                log("CSFD - No TV tips section found", level=xbmc.LOGWARNING)
                return []

            article_selectors = [
                ("article", {"class": "article"}),
                ("div", {"class": "tip-item"}),
                ("li", {"class": "tv-tip-item"}),
                ("div", {"class": "film-item"}),
                ("div", {"class": lambda x: x and ("item" in x.lower() or "tip" in x.lower())}),
                ("li", {"class": lambda x: x and ("item" in x.lower() or "tip" in x.lower())}),
            ]

            articles = []
            for tag, attrs in article_selectors:
                articles = tips_section.find_all(tag, attrs)
                if articles:
                    log(f"CSFD - Found {len(articles)} articles with selector : {tag} {attrs}", level=xbmc.LOGDEBUG)
                    break
            if not articles:
                log("CSFD - No articles found in TV tips section", level=xbmc.LOGWARNING)
                return []

            tip_ids = []
            for article in articles:
                title_elem = article.find("a", class_="film-title-name")
                if not title_elem:
                    continue
                href = title_elem.get("href", "")
                full_id = re.search(CSFD_ID_REGEX, href)
                if not full_id:
                    continue
                full_id = full_id.group(1)
                tip_type = "movie"
                time_channel_elem = article.find("span", class_="tv-tip-time")
                time_val = None
                channel = None
                if time_channel_elem:
                    time_text = time_channel_elem.text.strip()
                    time_match = re.search(r"(\d{1,2}:\d{2})", time_text)
                    if time_match:
                        time_val = time_match.group(1)
                    channel_elem = time_channel_elem.find("img") or time_channel_elem.find(
                        "span", class_=lambda x: x and "channel" in x.lower()
                    )
                    if channel_elem and "alt" in channel_elem.attrs:
                        channel = channel_elem["alt"].strip()
                    elif channel_elem:
                        channel = channel_elem.text.strip()
                tip_ids.append({"id": full_id, "type": tip_type, "time": time_val, "channel": channel})

            tips = []


            max_workers = get_threadpool(2)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:

                future_to_id = {executor.submit(self.get_detail, tip["id"]): tip for tip in tip_ids}
                total = len(future_to_id)
                done = 0
                for future in as_completed(future_to_id):
                    tip = future_to_id[future]
                    try:
                        details = future.result()
                        if details and details.get("title"):
                            details.update({"id": tip["id"], "time": tip["time"], "channel": tip["channel"], "type": tip["type"]})
                            tips.append(details)
                    except Exception as e:
                        log(f"CSFD - Failed to get details for {tip['id']} : {str(e)}", level=xbmc.LOGERROR)
                    done += 1
                    if progress_callback and total > 0:
                        progress_callback(int(done / total * 100), tip.get("id", "???"))

            log(f"CSFD - Returning {len(tips)} tips", level=xbmc.LOGDEBUG)


            if tips:
                cache_manager.cache_set("CSFD", cache_key, tips)
                cache_manager.window_cache_set(cache_key, tips)

            return tips

        except Exception as e:
            log(f"CSFD - Error fetching daily tips : {str(e)}", level=xbmc.LOGERROR)
            return []


    def get_detail(self, full_id):

        """
        CSFD :: DETAIL
        -- Získá detaily pro položky žebříčku z ČSFD.
        -- Kombinuje scraping ČSFD (priorita pro texty/hodnocení) a TMDB API (pro ID, grafiku a herce).
        """

        cache_key = f"csfd_detail_{full_id}"
        cached = cache_manager.cache_get("CSFD", cache_key)
        if cached:
            return cached

        url = f"{self.base_url}film/{full_id}-/prehled/"
        try:
            r = safe_get(self.session, url, timeout=TIMEOUT)
            if not r:
                return {}
            soup = BeautifulSoup(r.text, "html.parser")


            csfd_title = soup.find("h1").text.strip() if soup.find("h1") else "Neznámý titul"
            year = None
            origin = soup.find("div", class_="origin")
            if origin:
                m = re.search(r"\b(\d{4})\b", origin.text)
                year = m.group(1) if m else None

            rating = soup.find("div", class_="film-rating-average")
            rating = rating.text.strip() if rating else None

            genres_div = soup.find("div", class_="genres")
            genres = [a.text.strip() for a in genres_div.find_all("a")] if genres_div else []

            plot_elem = soup.find("div", class_="plot-full")
            plot = plot_elem.get_text(separator=" ").strip() if plot_elem else ""


            tmdb_props = {}
            if self.tmdb_client:
                try:
                    log(f"CSFD - Hledám TMDB metadata pro '{csfd_title}' ({year})", level=xbmc.LOGDEBUG)


                    results = self.tmdb_client.search_raw(csfd_title, year=year)
                    if results and results.get("results"):
                        tmdb_item = results["results"][0]
                        media_type = tmdb_item.get("media_type", "movie")


                        tmdb_props = self.tmdb_client._build_metadata_props(tmdb_item, media_type)

                        log(f"CSFD - TMDB shoda nalezena: ID {tmdb_props.get('tmdb_id')}", level=xbmc.LOGDEBUG)
                except Exception as e:
                    log(f"CSFD - TMDB selhalo: {e}", level=xbmc.LOGWARNING)


            details = {
                "id": full_id,
                "title": csfd_title,
                "original_title": tmdb_props.get("original_title", csfd_title),
                "year": year or tmdb_props.get("year"),
                "rating": rating,
                "tmdb_rating": tmdb_props.get("rating"),
                "genres": genres,
                "plot": plot or tmdb_props.get("plot", ""),


                "poster": tmdb_props.get("poster"),
                "fanart": tmdb_props.get("fanart"),
                "tmdb_id": tmdb_props.get("tmdb_id"),
                "media_type": tmdb_props.get("media_type", "movie"),


                "cast_full": tmdb_props.get("cast_full", []),
                "studio": tmdb_props.get("studio", ""),
                "mpaa": tmdb_props.get("mpaa", ""),
                "duration": tmdb_props.get("duration", "")
            }


            if not details["poster"]:
                img = soup.find("img", class_="film-poster")
                if img and img.get("src"):
                    src = img["src"]
                    details["poster"] = src if src.startswith("http") else f"{self.base_url}{src}"
                    if not details["fanart"]: details["fanart"] = details["poster"]

            if not details["poster"]:
                details["poster"] = Icons.CSFD

            if not details["fanart"]:
                details["fanart"] = details["poster"]

            cache_manager.cache_set("CSFD", cache_key, details)
            return details

        except Exception as e:
            log(f"CSFD - get_detail error {full_id}: {e}", xbmc.LOGERROR)
            return {}


    def get_chart(self, chart_path, page=1, progress_callback=None):

        """
        CSFD :: CHART
        -- Získá položky žebříčku z ČSFD.
        """

        from_param = (page - 1) * 100

        if from_param > 0:
            url = f"{self.base_url}zebricky/{chart_path}/?from={from_param}"
        else:
            url = f"{self.base_url}zebricky/{chart_path}/"
        log(f"CSFD - Stahuji URL žebříčku : {url}", level=xbmc.LOGDEBUG)

        try:
            response = safe_get(self.session, url, timeout=TIMEOUT)
            if not response:
                log("CSFD - Chyba při stahování žebříčku (network error)", level=xbmc.LOGERROR)
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("article", class_="article")

            items_to_resolve = []

            for article in articles:
                try:
                    title_elem = article.find("a", class_="film-title-name")
                    if not title_elem: continue

                    href = title_elem.get("href")
                    match = re.search(CSFD_ID_REGEX, href)
                    if not match: continue
                    csfd_id = match.group(1)

                    title = title_elem.text.strip()

                    year_elem = article.find("span", class_="info")
                    year = ""
                    if year_elem:
                        m_year = re.search(r"\((\d{4})\)", year_elem.text)
                        if m_year: year = m_year.group(1)

                    rating_elem = article.find("div", class_="film-rating-average")
                    rating = rating_elem.text.strip() if rating_elem else ""

                    item_data = {
                        "id": csfd_id,
                        "title": title,
                        "year": year,
                        "rating": rating
                    }
                    items_to_resolve.append(item_data)

                except Exception as e:
                    continue

            final_items = []

            max_workers = get_threadpool(4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {executor.submit(self.get_detail, item["id"]): item for item in items_to_resolve}

                total = len(items_to_resolve)
                done = 0

                for future in as_completed(future_to_item):
                    item_basic = future_to_item[future]
                    try:
                        details = future.result()
                        if details:
                            if not details.get("rating") and item_basic.get("rating"):
                                details["rating"] = item_basic["rating"]
                            final_items.append(details)
                    except Exception:
                        pass

                    done += 1
                    if progress_callback and total > 0:
                        progress_callback(10 + int(done/total * 90), item_basic["title"])

            ordered_items = []
            lookup = {i["id"]: i for i in final_items}
            for orig in items_to_resolve:
                if orig["id"] in lookup:
                    ordered_items.append(lookup[orig["id"]])

            return ordered_items

        except Exception as e:
            log(f"CSFD - Kritická chyba v get_chart : {e}", xbmc.LOGERROR)
            return []


    def get_lists(self, chart_list, page=1, progress_callback=None):

        """
        CSFD :: LISTS
        -- Získá položky seznamů z ČSFD  ( STRUKTURA 2025+ ).
        """

        if page < 1:
            page = 1


        category = None
        detail_id = None

        m = re.match(r'^(filmy|serialy)/\?detail=(\d+)$', str(chart_list))
        if m:
            category = m.group(1)
            detail_id = m.group(2)
        else:

            detail_id = str(chart_list).strip()
            try:
                num = int(detail_id)
                category = 'filmy' if num <= 71 else 'serialy'
            except Exception:

                category = 'filmy'

        base = f"{self.base_url}seznamy/{category}/"
        if page == 1:
            url = f"{base}?detail={detail_id}"
        else:
            url = f"{base}?page={page}&detail={detail_id}"

        log(f"CSFD - Stahuji URL seznamu: {url}", level=xbmc.LOGDEBUG)

        try:
            response = safe_get(self.session, url, timeout=TIMEOUT)
            if not response:
                log("CSFD - Chyba při stahování seznamu (network error)", level=xbmc.LOGERROR)
                return []

            soup = BeautifulSoup(response.text, "html.parser")


            links = soup.find_all("a", href=re.compile(r"^/film/\d+.*?/prehled/$"))

            items_to_resolve = []
            seen_ids = set()
            for a in links:
                try:
                    href = a["href"]
                    match = re.search(r"/film/(\d+)", href)
                    if not match:
                        continue
                    csfd_id = match.group(1)


                    if csfd_id in seen_ids:
                        continue
                    seen_ids.add(csfd_id)

                    full_text = a.get_text(strip=True)


                    year_match = re.search(r"(\d{4})$", full_text)
                    year = year_match.group(1) if year_match else ""

                    title = re.sub(r"\s*\d{4}$", "", full_text).strip()


                    rating = ""

                    items_to_resolve.append({
                        "id": csfd_id,
                        "title": title,
                        "year": year,
                        "rating": rating
                    })
                except Exception:
                    continue

            if not items_to_resolve:
                log("CSFD - Žádné položky nenalezeny v seznamu", level=xbmc.LOGWARNING)

            final_items = []

            max_workers = get_threadpool(4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_item = {executor.submit(self.get_detail, item["id"]): item for item in items_to_resolve}

                total = len(items_to_resolve)
                done = 0

                for future in as_completed(future_to_item):
                    item_basic = future_to_item[future]
                    try:
                        details = future.result()
                        if details:
                            if not details.get("rating") and item_basic.get("rating"):
                                details["rating"] = item_basic["rating"]
                            final_items.append(details)
                    except Exception:
                        pass

                    done += 1
                    if progress_callback and total > 0:
                        progress_callback(10 + int(done/total * 90), item_basic["title"])


            ordered_items = []
            lookup = {i["id"]: i for i in final_items}
            for orig in items_to_resolve:
                if orig["id"] in lookup:
                    ordered_items.append(lookup[orig["id"]])

            return ordered_items

        except Exception as e:
            log(f"CSFD - Kritická chyba v get_lists: {e}", xbmc.LOGERROR)
            return []