# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: gemini.py
# Author: Mau!X ER
# Created on: 24.04.2026
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from resources.lib.sf_context_style import items as _sf_cm_items, labels as _sf_cm_labels, label as _sf_cm_label
import re
import os
import copy
import hashlib
import xbmcvfs
from resources.lib.ai_state import AIState
import sys
import json
import time
import datetime
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import xbmc
import xbmcgui
import xbmcaddon
import xbmcplugin


from resources.lib.monitor_orchestrator import get_orchestrator
from resources.lib.utils_theme import Colors
from resources.lib.utils_logging import log
from resources.lib import cache_manager


from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)

from resources.lib.utils import (
    get_threadpool,
    safe_post
)





def _store(plugin_instance):
    return AIState(xbmcvfs.translatePath('special://masterprofile/DATA--PLAY/INTELLIGENCE'))

def _text(ident):
    return xbmcaddon.Addon().getLocalizedString(ident)


def _reason_words(plugin_instance):
    try:
        return max(10, min(80, int(plugin_instance.addon.getSetting('ai_reason_words') or 24)))
    except (TypeError, ValueError):
        return 24


def _format_reason(plugin_instance, text):
    words = str(text or '').split()
    limit = _reason_words(plugin_instance)
    return ' '.join(words[:limit]) + ('…' if len(words) > limit else '')


def _candidate_count(plugin_instance):
    count = _limit(plugin_instance)
    return min(60, count + max(3, (count + 1) // 2))


def _output_budget(plugin_instance, count=None):
    return min(16384, 1024 + (count or _limit(plugin_instance)) * (80 + 3 * _reason_words(plugin_instance)))


def _recommendation_schema(count):
    return {'type':'OBJECT', 'required':['recommendations'], 'properties':{
        'recommendations': {'type':'ARRAY', 'minItems':count, 'maxItems':count,
            'items': {'type':'OBJECT', 'required':['title','original_title','year','type','reason'],
                'properties': {'title':{'type':'STRING'}, 'original_title':{'type':'STRING'},
                    'year':{'type':'INTEGER'}, 'type':{'type':'STRING','enum':['Movie','Show']},
                    'reason':{'type':'STRING'}}}}}}


def _limit(plugin_instance):
    try:
        return max(1, min(40, int(plugin_instance.addon.getSettingString('gemini_limit') or 10)))
    except (TypeError, ValueError):
        return 10

def _request_key(plugin_instance, prompt, kind='recommendations'):
    keys = ('ai_provider', 'gemini_model', 'openrouter_model', 'gemini_temperature',
            'gemini_limit', 'ai_reason_words', 'ai_custom_instructions',
            'gemini_context_source_1', 'gemini_context_source_2', 'tmdb_language')
    preferences = {key: plugin_instance.addon.getSetting(key) for key in keys}
    # Hash the effective model for both providers. Neutral defaults preserve
    # existing caches; inactive presets and equivalent custom aliases do not
    # cause unnecessary new requests.
    gemini_id = plugin_instance.addon.getSettingString('gemini_model_id').strip()
    if gemini_id.startswith('models/'):
        gemini_id = gemini_id[len('models/'):].strip()
    if gemini_id:
        preferences['gemini_model'] = gemini_id
    if not preferences['openrouter_model'].strip():
        preset = plugin_instance.addon.getSettingString('openrouter_model_preset').strip()
        preferences['openrouter_model'] = preset if preset and preset != 'custom' else 'google/gemma-4-31b-it:free'
    values = [kind, prompt] + [preferences[key] for key in keys]
    # The preset path migrates retired 1.5/2.0 IDs; an explicit override must
    # actually try that ID rather than reuse a migrated preset's cached result.
    if gemini_id.startswith(('gemini-1.5-', 'gemini-2.0-')):
        values.extend(('explicit_gemini_model_id', gemini_id))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def _prepare_result(plugin_instance, item):
    kind = item.get('media_type', 'movie')
    data = dict(item)
    # Full TMDB detail already contains genre names: never fetch the genre API
    # when preparing an AI result or rendering a migrated daily selection.
    genres = {g['id']: g['name'] for g in data.get('genres', [])
              if isinstance(g, dict) and g.get('id') is not None and g.get('name')}
    props = plugin_instance.tmdb_client._build_metadata_props(data, kind, genre_names=genres)
    return {'id': data['id'], 'title': props.get('title', ''), 'media_type': kind,
            'gemini_reason': _format_reason(plugin_instance, data.get('gemini_reason')), '_ai_props': props}

def _queue_daily(plugin_instance, force=False):
    state = _store(plugin_instance)
    token = state.request(force=force)
    if token:
        try:
            url = 'plugin://plugin.video.play_er/?' + urllib.parse.urlencode({'action':'ai_daily_generate', 'token':token, 'force':str(bool(force)).lower()})
            xbmc.executebuiltin('RunPlugin(' + url + ')')
        except Exception:
            state.fail(token)
            raise
    return token

def _refresh_ai_widgets(plugin_instance):
    xbmcgui.Window(10000).setProperty('play_er.ai_daily_revision', str(time.time()))
    if 'action=ai_daily_mix' in xbmc.getInfoLabel('Container.FolderPath'):
        xbmc.executebuiltin('Container.Refresh')
    # AF3 dynamic containers listen for library completion. Scan only our empty
    # directory, never the user's library; no clean, skin reload or focus change.
    empty = 'special://masterprofile/DATA--PLAY/INTELLIGENCE/refresh'
    empty = xbmcvfs.translatePath(empty).rstrip('/\\') + '/'
    os.makedirs(empty, exist_ok=True)
    xbmc.executebuiltin('UpdateLibrary(video,"' + empty.replace('"', '') + '")')

def refresh_daily_mix(plugin_instance):
    token = _queue_daily(plugin_instance, force=True)
    notify_info(_text(32654) if token else _text(32655), category='AI')
    if plugin_instance.handle >= 0:
        xbmcplugin.endOfDirectory(plugin_instance.handle, cacheToDisc=False)

def generate_daily_mix(plugin_instance, params):
    store = _store(plugin_instance)
    token = params.get('token', '')
    with store.guard('daily-worker', blocking=False) as acquired:
        if not acquired or not store.claim(token): return
        try:
            state = store.read()
            settings = {'key':_request_key(plugin_instance, ''), 'limit':_limit(plugin_instance),
                        'reason_words':_reason_words(plugin_instance),
                        'prompt_hash':hashlib.sha256(plugin_instance.addon.getSettingString('ai_custom_instructions').encode()).hexdigest()}
            # Legacy USER_DATA may be in a remote MySQL database. Migration
            # belongs to this background worker, never the widget render path.
            if not state.get('results'):
                try:
                    legacy = cache_manager.user_data_get('ai_daily_mix_results')
                    if isinstance(legacy, list) and legacy:
                        prepared = [_prepare_result(plugin_instance, item) for item in legacy
                                    if isinstance(item, dict) and item.get('id')]
                        legacy_date = cache_manager.user_data_get('ai_daily_mix_date') or ''
                        store.seed(prepared, legacy_date)
                        state = store.read()
                        from resources.lib.utils_ai_context import select_daily_results
                        current = select_daily_results(prepared, _limit(plugin_instance))
                        if (legacy_date == datetime.date.today().isoformat() and current
                                and str(params.get('force', '')).lower() != 'true'):
                            if store.complete(token, current, settings=settings):
                                try:
                                    _refresh_ai_widgets(plugin_instance)
                                except Exception as exc:
                                    log(f'AI-TODAY: Výběr uložen, obnovení widgetu selhalo: {type(exc).__name__}', xbmc.LOGWARNING)
                            return
                except Exception as exc:
                    log(f'AI-TODAY: Starší cache není dostupná: {type(exc).__name__}', xbmc.LOGWARNING)
            cutoff = (datetime.date.today() - datetime.timedelta(days=21)).isoformat()
            history = [r for r in state.get('history', []) if r.get('date', '') > cutoff]
            # Migrate the current selection into the exclusion list for manual refresh.
            exclusions = {(r.get('media_type'), str(r.get('id'))) for r in history + state.get('results', [])} | _known_context_ids()
            previous = ', '.join(dict.fromkeys(str(r.get('title', '')) for r in state.get('results', []) + history))[:2500]
            themes = ('atmosféra a silné postavy', 'méně známé kvalitní objevy', 'jiné období a prostředí',
                      'napětí a promyšlený příběh', 'pestrý večerní výběr', 'výrazní tvůrci', 'nečekané příbuzné tituly')
            revision = state.get('revision', 1)
            theme = themes[(datetime.date.today().toordinal() + revision) % len(themes)]
            prompt_text = (f'Datum {datetime.date.today().isoformat()}, varianta {revision}. Zaměření dne: {theme}. '
                'Připrav pestrý, ale cílený výběr filmů a seriálů podle vkusu v kontextu. '
                'Mezi kandidáty vždy zahrň filmy i seriály, aby denní výběr pro počet alespoň dvě položky obsahoval oba typy. '
                'Kombinuj ověřené tituly s méně známými objevy; střídej tvůrce a období. '
                'Neopakuj uvedené dřívější tipy, z jedné franšízy nejvýše jeden titul. '
                f'Důvod nejvýše {_reason_words(plugin_instance)} slov, konkrétní vazba na vkus. Dostupnost dabingu ani streamu nevymýšlej. '
                f'Předchozí doporučení: {previous}')
            candidates = _candidate_count(plugin_instance)
            prompt = _get_ai_prompt(plugin_instance, prompt_text, candidates, _get_user_context(), exact_count=True)
            stats = {}
            results = _process_ai_json_and_display(plugin_instance, prompt, None, is_widget=True,
                render=False, excluded_ids=exclusions, cache_response=False, candidate_limit=candidates, stats=stats, mixed=True)
            if results and store.complete(token, results, settings=settings, stats=stats):
                try:
                    _refresh_ai_widgets(plugin_instance)
                except Exception as exc:
                    log(f'AI-TODAY: Výběr uložen, obnovení widgetu selhalo: {type(exc).__name__}', xbmc.LOGWARNING)
            else:
                store.fail(token)
        except Exception as exc:
            store.fail(token)
            log(f'AI-TODAY: Obnova selhala, předchozí cache zachována: {type(exc).__name__}', xbmc.LOGWARNING)

def _remember_navigation(plugin_instance, results):
    xbmcgui.Window(10000).setProperty(_get_window_cache_key(), json.dumps({
        'time':time.time(), 'config':_request_key(plugin_instance, ''), 'items':results}))


def _restore_navigation(plugin_instance, is_widget=False):
    if not _is_refresh() or is_widget: return False
    try:
        entry = json.loads(xbmcgui.Window(10000).getProperty(_get_window_cache_key()) or '{}')
        if (isinstance(entry, dict) and entry.get('items') and time.time() - entry.get('time', 0) < 86400
                and entry.get('config') == _request_key(plugin_instance, '')):
            _render_tmdb_results(plugin_instance, entry['items'])
            xbmcplugin.endOfDirectory(plugin_instance.handle, cacheToDisc=False)
            return True
    except Exception:
        pass
    return False

def _is_refresh():
    try:
        current_path = (sys.argv[0] + sys.argv[2]).rstrip('/')
        folder_path = xbmc.getInfoLabel('Container.FolderPath').rstrip('/')
        return urllib.parse.unquote(current_path) == urllib.parse.unquote(folder_path) and current_path != ""
    except Exception:
        return False


def _render_tmdb_results(plugin_instance, tmdb_results, is_widget=False, daily=False):
    xbmcplugin.setContent(plugin_instance.handle, 'movies')
    for item_data in tmdb_results:
        mtype = item_data.get('media_type', 'movie')
        prepared = item_data if isinstance(item_data.get('_ai_props'), dict) else _prepare_result(plugin_instance, item_data)
        props = copy.deepcopy(prepared['_ai_props'])
        reason = _format_reason(plugin_instance, prepared.get('gemini_reason', ''))
        if reason:
            props['plot'] = f"[B][COLOR {Colors.LIMEGREEN}]► {_text(32652)}[/COLOR][/B] {reason}\n\n{props.get('plot', '')}"
        li = xbmcgui.ListItem(label=f"{props.get('title', '')} ({props.get('year', '')})")
        plugin_instance.tmdb_client._populate_list_item(li, props, mtype, context_type='search_results',
            is_ai_daily=daily)
    if not is_widget:
        from resources.lib.ui_builder import set_view_mode
        set_view_mode(plugin_instance.handle, plugin_instance.addon, 'movies', 'search_results')


def _get_window_cache_key():
    import hashlib
    raw_url = sys.argv[2] if len(sys.argv) > 2 else "default"
    return f"gemini_res_{hashlib.md5(raw_url.encode('utf-8')).hexdigest()}"


def _known_context_ids():
    addon = xbmcaddon.Addon()
    selected = {addon.getSetting('gemini_context_source_1'), addon.getSetting('gemini_context_source_2')}
    keys = {'internal_history':'playback_history', 'internal_wl':'watch_later',
            'trakt_watchlist':'trakt_watchlist_items', 'trakt_favorites':'trakt_favorites_items'}
    identities = set()
    for source in selected:
        if source in ('trakt_watched', 'trakt_in_progress', 'trakt_ratings'):
            from resources.lib import utils_ai_context
            for item in utils_ai_context.get_source_items(addon, source):
                if item.get('tmdb_id'):
                    identities.add((item['media_type'], str(item['tmdb_id'])))
            continue
        if source not in keys: continue
        for entry in cache_manager.user_data_get(keys[source]) or []:
            if not isinstance(entry, dict): continue
            meta = entry.get('meta') or entry
            kind = meta.get('media_type', meta.get('type', 'movie'))
            kind = 'tv' if kind in ('tv', 'show', 'episode', 'series') else 'movie'
            ident = meta.get('tmdb_id')
            if ident: identities.add((kind, str(ident)))
    return identities


def _get_user_context():
    addon = xbmcaddon.Addon()
    source_1 = addon.getSetting("gemini_context_source_1") or "none"
    source_2 = addon.getSetting("gemini_context_source_2") or "none"

    selected_sources = {source_1, source_2} - {"none"}
    if not selected_sources:
        return ""

    context_lines = []
    for source in sorted(selected_sources):
        if source == "internal_history":
            try:
                history = cache_manager.user_data_get("playback_history") or []
                hist_titles = []
                for item in history:
                    meta = item.get("meta") or {}
                    title = (meta.get("tv_show_title") or meta.get("title")) if meta.get("media_type") == "episode" else meta.get("title")
                    if title and title not in hist_titles:
                        hist_titles.append(title)
                    if len(hist_titles) >= 15: break
                if hist_titles:
                    context_lines.append(f"Nedávno sledované tituly v přehrávači : {', '.join(hist_titles)}")
            except Exception as e:
                log(f"AI CONTEXT - Chyba INTERNÍ HISTORIE : {e}", xbmc.LOGWARNING)

        elif source == "internal_wl":
            try:
                watch_later = cache_manager.user_data_get("watch_later") or []
                wl_titles = []
                for item in watch_later[:20]:
                    title = item.get("title")
                    if title and title not in wl_titles:
                        wl_titles.append(title)
                if wl_titles:
                    context_lines.append(f"V interním seznamu 'Chci vidět' : {', '.join(wl_titles)}")
            except Exception as e:
                log(f"AI CONTEXT - Chyba WATCHLISTU : {e}", xbmc.LOGWARNING)

        elif source == "trakt_watchlist":
            try:
                trakt_wl = cache_manager.user_data_get("trakt_watchlist_items") or []
                t_titles = [i.get('title') for i in trakt_wl if i.get('title')][:20]
                if t_titles:
                    context_lines.append(f"Na TRAKT.TV ve watchlistu má uživatel : {', '.join(t_titles)}")
            except Exception as e:
                log(f"AI CONTEXT - Chyba TRAKT WATCHLIST : {e}", xbmc.LOGWARNING)

        elif source == "trakt_favorites":
            try:
                trakt_favs = cache_manager.user_data_get("trakt_favorites_items") or []
                f_titles = [i.get('title') for i in trakt_favs if i.get('title')][:20]
                if f_titles:
                    context_lines.append(f"Na TRAKT.TV v oblíbených má uživatel : {', '.join(f_titles)}")
            except Exception as e:
                log(f"AI CONTEXT - Chyba TRAKT FAVORITES : {e}", xbmc.LOGWARNING)

        elif source in ('trakt_watched', 'trakt_in_progress', 'trakt_ratings'):
            from resources.lib import utils_ai_context
            items = utils_ai_context.get_source_items(addon, source)
            line = utils_ai_context.format_context(source, items)
            if line:
                context_lines.append(line)

        elif source == "tmdb_watchlist":
            try:
                from resources.lib import tmdb_account
                tmdb_titles = []
                wl_movies = tmdb_account.tmdb_get_watchlist('movie')
                if wl_movies and 'results' in wl_movies:
                    tmdb_titles.extend([m.get('title') for m in wl_movies['results'][:10] if m.get('title')])
                wl_shows = tmdb_account.tmdb_get_watchlist('tv')
                if wl_shows and 'results' in wl_shows:
                    tmdb_titles.extend([s.get('name') for s in wl_shows['results'][:10] if s.get('name')])
                if tmdb_titles:
                    context_lines.append(f"Na TMDB ve Watchlistu : {', '.join(tmdb_titles)}")
            except Exception as e:
                log(f"AI CONTEXT - Chyba TMDB WATCHLIST : {e}", xbmc.LOGWARNING)

    return "\n".join(context_lines)


def _get_ai_prompt(plugin_instance, prompt_text, limit, user_context="", exact_count=False):
    custom_instructions = plugin_instance.addon.getSettingString('ai_custom_instructions').strip()
    custom_block = f"USER CUSTOM INSTRUCTIONS & PREFERENCES:\n{custom_instructions}\n\n" if custom_instructions else ""
    context_block = f"USER CONTEXT (Movies/Shows they already know or plan to watch):\n{user_context}\n\nUse this context ONLY to understand the user's taste. DO NOT recommend titles that are already in the context list. Recommend fresh items that fit the vibe.\n\n" if user_context else ""

    count_instruction = (f'You MUST return exactly {limit} distinct candidate titles. This includes a reserve for local TMDB matching; supply the full candidate count.'
                         if exact_count else f'You MUST NOT return more than {limit} items.')
    return f"""You are an expert movie/TV recommendations engine and search assistant.
You always respond with ONE JSON object, nothing else. Do not use markdown wrappers if possible.

JSON OUTPUT SHAPE:
{{
  "recommendations": [
    {{
      "title": "Czech Title or Localized Name",
      "original_title": "Original English/Native Name",
      "year": 2000,
      "type": "Movie" or "Show",
      "reason": "Konkrétní důvod česky, nejvýše {_reason_words(plugin_instance)} slov"
    }}
  ]
}}

{custom_block}{context_block}LIMITS:
- {count_instruction}
- Reason length: aim for {round(_reason_words(plugin_instance) * 0.8)}–{_reason_words(plugin_instance)} words, at most {_reason_words(plugin_instance)} words. This numeric setting controls length even if style instructions mention another length; keep all other custom preferences.
PROMPT (the original user text to answer in Czech):
{prompt_text}

Produce ONE JSON object exactly in the shape above. Do NOT include any explanation, comments, or markdown formatting outside the JSON object."""


def _call_gemini(plugin_instance, prompt, temperature, json_mode=True, candidate_limit=None):
    api_key = plugin_instance.addon.getSettingString('gemini_api_key').strip()
    if not api_key:
        log("GEMINI API : Přeskočeno, chybí API klíč v nastavení.", xbmc.LOGINFO)
        return None

    if _store(plugin_instance).is_cooling('GEMINI'): return None
    from resources.lib.utils_ai_models import gemini_model_selection
    configured_model, is_custom_model = gemini_model_selection(plugin_instance.addon)
    if not is_custom_model and configured_model.startswith(("gemini-1.5-", "gemini-2.0-")):
        log(f"GEMINI API : Uložený model {configured_model} již není dostupný, používám gemini-3.5-flash-lite.", xbmc.LOGINFO)
        configured_model = "gemini-3.5-flash-lite"
    models_to_try = [configured_model]
    for fallback in ["gemini-3.5-flash-lite", "gemini-3.8-flash"]:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json" if json_mode else "text/plain",
            "maxOutputTokens": _output_budget(plugin_instance, candidate_limit) if json_mode else 1024
        }
    }

    if json_mode and candidate_limit:
        payload['generationConfig']['responseSchema'] = _recommendation_schema(candidate_limit)

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        try:
            resp = plugin_instance.session.post(url, json=payload, headers=headers, timeout=40)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    usage = data.get('usageMetadata', {})
                    log(f"AI TOKENS: input={usage.get('promptTokenCount', 0)}, output={usage.get('candidatesTokenCount', 0)}, thinking={usage.get('thoughtsTokenCount', 0)}", xbmc.LOGINFO)
                    parts = data['candidates'][0]['content']['parts']
                    return ''.join(p.get('text', '') for p in parts if isinstance(p, dict) and not p.get('thought'))
                except Exception as e:
                    log(f"GEMINI PARSE ERROR ({model_name}): {e}", xbmc.LOGERROR)
                    return None
            elif resp.status_code == 404:
                log(f"GEMINI API 404 pro model {model_name}, zkouším fallback...", xbmc.LOGWARNING)
                continue
            elif resp.status_code == 429:
                try: delay = int(resp.headers.get('Retry-After', '900'))
                except (TypeError, ValueError): delay = 900
                _store(plugin_instance).cooldown('GEMINI', delay)
                notify_info("GEMINI : Vyčerpány free limity / tokeny!", category="AI")
                return None
            else:
                log(f"GEMINI API FAIL ({model_name}): HTTP {resp.status_code}", xbmc.LOGWARNING)
                return None
        except Exception as e:
            log(f"GEMINI CONNECTION ERROR ({model_name}): {type(e).__name__}", xbmc.LOGWARNING)
            return None

    return None


def _call_openrouter(plugin_instance, prompt, temperature, json_mode=True, candidate_limit=None):
    api_key = plugin_instance.addon.getSettingString('openrouter_api_key').strip()
    if not api_key:
        log("OPENROUTER API : Přeskočeno, chybí API klíč v nastavení.", xbmc.LOGINFO)
        return None

    if _store(plugin_instance).is_cooling('OPENROUTER'): return None
    from resources.lib.utils_ai_models import openrouter_model
    model = openrouter_model(plugin_instance.addon)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/play_er",
        "X-Title": "Kodi Play.er"
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _output_budget(plugin_instance, candidate_limit) if json_mode else 1024
    }
    if json_mode: payload['response_format'] = {'type':'json_object'}
    if temperature != 0.7:
        payload["temperature"] = temperature

    try:
        resp = plugin_instance.session.post(url, json=payload, headers=headers, timeout=40)
        if resp.status_code == 200:
            try:
                return resp.json()['choices'][0]['message']['content']
            except Exception as e:
                log(f"OPENROUTER PARSE ERROR : {e}", xbmc.LOGERROR)
                return None
        else:
            log(f"OPENROUTER API FAIL : HTTP {resp.status_code}", xbmc.LOGWARNING)
            if resp.status_code == 429:
                _store(plugin_instance).cooldown('OPENROUTER')
                notify_info("OPENROUTER : Vyčerpány free limity / kredity!", category="AI")
            return None
    except Exception as e:
        log(f"OPENROUTER CONNECTION ERROR : {e}", xbmc.LOGERROR)
        return None


def _call_ai_api(plugin_instance, prompt, json_mode=True, candidate_limit=None):
    provider = plugin_instance.addon.getSettingString('ai_provider') or "GEMINI"
    temperature = plugin_instance.addon.getSettingInt('gemini_temperature') / 10.0

    orch = get_orchestrator()
    if orch:
        orch.inc_metric("ai_requests_total")

    text_response = None
    if provider == "OPENROUTER":
        text_response = _call_openrouter(plugin_instance, prompt, temperature, json_mode=json_mode, candidate_limit=candidate_limit)
        if not text_response:
            log("AI CALLER - OpenRouter selhal, spouštím Fallback -> GEMINI", xbmc.LOGINFO)
            if orch:
                orch.inc_metric("ai_fallback_triggered")
            text_response = _call_gemini(plugin_instance, prompt, temperature, json_mode=json_mode, candidate_limit=candidate_limit)
    else:
        text_response = _call_gemini(plugin_instance, prompt, temperature, json_mode=json_mode, candidate_limit=candidate_limit)
        if not text_response:
            log("AI CALLER - Gemini selhalo, spouštím Fallback -> OPENROUTER", xbmc.LOGINFO)
            if orch:
                orch.inc_metric("ai_fallback_triggered")
            text_response = _call_openrouter(plugin_instance, prompt, temperature, json_mode=json_mode, candidate_limit=candidate_limit)

    if not text_response:
        if orch:
            orch.inc_metric("ai_errors_total")
        notify_error("ERROR AI selhalo u obou API.", category="AI")

    return text_response


def _process_ai_json_and_display(plugin_instance, final_prompt, progress_dialog, cache_key_override=None,
                               is_widget=False, render=True, excluded_ids=(), cache_response=True, candidate_limit=None, stats=None, mixed=False, force_refresh=False):
    store = _store(plugin_instance)
    key = _request_key(plugin_instance, final_prompt)
    with store.guard('generate-' + key, blocking=False) as acquired:
        if not acquired: return None
        try:
            cached = store.get(key) if cache_response and not force_refresh else None
            if cached:
                _remember_navigation(plugin_instance, cached)
                if render: _render_tmdb_results(plugin_instance, cached, is_widget=is_widget)
                return cached
            text_response = _call_ai_api(plugin_instance, final_prompt, candidate_limit=candidate_limit)
            if not text_response: return None
            text_response = text_response.replace('```json', '').replace('```', '')
            start, end = text_response.find('{'), text_response.rfind('}')
            if start < 0 or end <= start: return None
            payload = json.loads(re.sub(r',\s*([\]}])', r'\1', text_response[start:end+1]))
            recs = payload.get('recommendations', []) if isinstance(payload, dict) else []
            if not isinstance(recs, list): return None
            limit = _limit(plugin_instance)
            valid = []
            requested_candidates = candidate_limit or min(60, limit * 2)
            for rec in recs[:requested_candidates]:
                if not isinstance(rec, dict) or not isinstance(rec.get('title'), str) or not rec['title'].strip(): continue
                mode = str(rec.get('type', '')).lower().strip()
                if mode not in ('movie', 'film', 'show', 'tv', 'series', 'seriál', 'serial'): continue
                valid.append(rec)
            if not valid: return None
            if progress_dialog: progress_dialog.update(50, 'Překládám výsledky…')
            def resolve(rec):
                try:
                    kind = 'movie' if str(rec['type']).lower().strip() in ('movie', 'film') else 'tv'
                    title, original, year = rec['title'], rec.get('original_title'), rec.get('year')
                    if year is not None:
                        year = int(year)
                        if not 1880 <= year <= datetime.date.today().year + 2: return None
                    response = None
                    queries = list(dict.fromkeys((t, y) for t, y in ((title, year), (original, year), (title, None), (original, None)) if isinstance(t, str) and t))
                    for name, requested_year in queries:
                        response = plugin_instance.tmdb_client.search_raw(name, year=requested_year, media_type=kind)
                        if response and response.get('results'): break
                    if not response or not response.get('results'): return None
                    match = response['results'][0]
                    if not match.get('id') or (kind, str(match['id'])) in excluded_ids: return None
                    full = plugin_instance.tmdb_client.get_full_details(kind, match['id']) or match
                    full = dict(full, media_type=kind, gemini_reason=rec.get('reason', ''))
                    return _prepare_result(plugin_instance, full)
                except Exception:
                    return None
            seen = set(excluded_ids); results = []; matched = 0; duplicates = 0
            with ThreadPoolExecutor(max_workers=get_threadpool(len(valid))) as executor:
                for result in executor.map(resolve, valid):
                    if not result: continue
                    matched += 1
                    identity = (result['media_type'], str(result['id']))
                    if identity not in seen and len(results) < (requested_candidates if mixed else limit):
                        seen.add(identity); results.append(result)
                    elif identity in seen:
                        duplicates += 1
            if mixed:
                from resources.lib.utils_ai_context import select_daily_results
                results = select_daily_results(results, limit)
                if not results:
                    log('AI-TODAY: Chybí použitelná směs filmů a seriálů; předchozí výběr zachován', xbmc.LOGWARNING)
            counts = {'requested':limit, 'candidates':candidate_limit or limit, 'returned':len(recs),
                      'valid':len(valid), 'matched':matched, 'duplicates':duplicates, 'displayed':len(results)}
            if stats is not None: stats.update(counts)
            log('AI RESULTS: ' + ', '.join(f'{k}={v}' for k,v in counts.items()), xbmc.LOGINFO)
            if not results: return None
            if cache_response: store.put(key, results)
            # Short-lived navigation restore, invalidated by changed preferences.
            _remember_navigation(plugin_instance, results)
            if cache_key_override: cache_manager.user_data_set(cache_key_override, results)
            if render: _render_tmdb_results(plugin_instance, results, is_widget=is_widget)
            return results
        except Exception as exc:
            log(f'AI: Odpověď nebyla použitelná: {type(exc).__name__}', xbmc.LOGWARNING)
            return None


def search_gemini(plugin_instance):
    if _restore_navigation(plugin_instance, is_widget=False): return

    limit = _limit(plugin_instance)
    kb = xbmc.Keyboard("", f"[COLOR {Colors.ORANGE}] ○   ZADEJTE LIBOVOLNÝ TEXT   ○ [/COLOR]")
    kb.doModal()
    if not kb.isConfirmed() or not kb.getText().strip():
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
        return

    prompt_text = kb.getText().strip()
    progress = xbmcgui.DialogProgress()
    progress.create(f"[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  ::  AI HLEDÁNÍ   ○ [/COLOR][/B]", "Zpracovávám dotaz...")

    try:
        user_context = _get_user_context()
        final_prompt = _get_ai_prompt(plugin_instance, prompt_text, limit, user_context)
        _process_ai_json_and_display(plugin_instance, final_prompt, progress)
    finally:
        progress.close()
        xbmcplugin.endOfDirectory(plugin_instance.handle)


def ai_recommend_for_me(plugin_instance, is_widget=False, force_refresh=False):
    if _restore_navigation(plugin_instance, is_widget=is_widget): return

    limit = _limit(plugin_instance)
    progress = None
    if not is_widget:
        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  ::  AI DOPORUČENÍ   ○ [/COLOR][/B]", "Analyzuji historii...")

    try:
        user_context = _get_user_context()
        if not user_context and not is_widget:
            notify_info("INFO Nedostatek historie pro personalizaci.", category="AI")
            return

        prompt_text = "Na základě mého uživatelského kontextu mi doporuč přesně vybraný počet titulů (namíchej filmy a seriály), které by mě mohly nadchnout. Jako reason uveď, proč by se mi to mohlo líbit vzhledem k mé historii."
        final_prompt = _get_ai_prompt(plugin_instance, prompt_text, limit, user_context)
        _process_ai_json_and_display(plugin_instance, final_prompt, progress, is_widget=is_widget,
                                     force_refresh=force_refresh)
    finally:
        if progress:
            progress.close()
        xbmcplugin.endOfDirectory(plugin_instance.handle)


def ai_daily_mix(plugin_instance, is_widget=False):
    try:
        store = _store(plugin_instance)
        state = store.read()
        _queue_daily(plugin_instance)
        from resources.lib.utils_ai_context import select_daily_results
        cached_results = state.get('results') or []
        # Preserve a valid movie/TV mixture even after lowering the item count.
        # Older single-kind caches remain visible until background refresh.
        results = select_daily_results(cached_results, _limit(plugin_instance)) or cached_results[:_limit(plugin_instance)]
        if not is_widget and state.get('settings', {}).get('key') not in (None, _request_key(plugin_instance, '')):
            notify_info(_text(32658), category='AI')
        if results:
            _render_tmdb_results(plugin_instance, results, is_widget=is_widget, daily=True)
        else:
            message = _text(32657) if state.get('error') else _text(32656)
            item = xbmcgui.ListItem(label=message)
            item.setProperty('IsPlayable', 'false')
            item.addContextMenuItems(_sf_cm_items(plugin_instance.tmdb_client._build_context_menu(
                None, 'movie', '', context_type='ai_daily_empty', is_ai_daily=True)))
            xbmcplugin.addDirectoryItem(plugin_instance.handle,
                'plugin://plugin.video.play_er/?action=ai_daily_refresh', item, False)
    except Exception as exc:
        log(f'AI-TODAY: Cache není dostupná: {type(exc).__name__}', xbmc.LOGWARNING)
    finally:
        xbmcplugin.endOfDirectory(plugin_instance.handle, cacheToDisc=False)


def ai_mood_matcher(plugin_instance):
    if _restore_navigation(plugin_instance, is_widget=False): return

    moods = [
        ("  SCI-FI STORY", "Chci epické nebo atmosférické Sci-Fi, odehrávající se ve vesmíru nebo v kyberpunkové budoucnosti."),
        ("  TEMNÝ KRIMI VIBE", "Chci temnou, ponurou detektivku nebo krimi thriller (ideálně severský nebo ve stylu Fincher/True Detective)."),
        ("  MINDFUCK / MIND-BENDING", "Chci něco, co mi úplně odrovná mozek. Thriller, sci-fi nebo mysteriózní film s obřím plot-twistem na konci."),
        ("  CHCI SE ZASMÁT", "Chci skvělou čistou komedii, u které se nahlas zasměju. Žádná deprese."),
        ("  ČISTÝ ADRENALIN", "Chci drsný a rychlý akčňák nebo thriller, kde se pořád něco děje a nedá mi to vydechnout."),
        ("  PRO CELOU RODINU", "Chci skvělý animák nebo dobrodružný film, na který se dá koukat s rodinou nebo dětmi, ale zabaví i dospělé.")
    ]

    labels = [m[0] for m in moods]
    dialog = xbmcgui.Dialog()
    choice = dialog.select(f"[COLOR {Colors.ORANGE}]  ○   JAKOU MÁTE NÁLADU   ○  [/COLOR]", labels)

    if choice < 0:
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=False)
        return

    selected_mood_prompt = moods[choice][1]
    limit = _limit(plugin_instance)
    progress = xbmcgui.DialogProgress()
    progress.create(f"[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  ::  AI VÝBĚR NÁLADY   ○ [/COLOR][/B]", "Zpracovávám výběr...")

    try:
        user_context = _get_user_context()
        prompt_text = f"Uživatel má aktuálně tuto náladu/požadavek: '{selected_mood_prompt}'. Najdi pro něj ty nejlepší možné tituly, které tuto náladu naprosto přesně splňují, ale vezmi v potaz i jeho historii. Jako 'reason' napiš, proč to přesně sedí do jeho aktuální nálady."
        final_prompt = _get_ai_prompt(plugin_instance, prompt_text, limit, user_context)
        _process_ai_json_and_display(plugin_instance, final_prompt, progress)
    finally:
        progress.close()
        xbmcplugin.endOfDirectory(plugin_instance.handle)


def ai_similar(plugin_instance, params, is_widget=False):
    if _restore_navigation(plugin_instance, is_widget=is_widget): return

    title = params.get('title', '')
    year = params.get('year', '')
    media_type = params.get('media_type', 'movie')
    tmdb_id = params.get('tmdb_id', '')
    limit = _limit(plugin_instance)

    if tmdb_id and plugin_instance.tmdb_client:
        try:
            mtype = 'tv' if media_type in ('tv', 'show', 'episode') else 'movie'
            details = plugin_instance.tmdb_client.get_full_details(mtype, tmdb_id)
            if details:
                props = plugin_instance.tmdb_client._build_metadata_props(details, mtype)
                title = props.get('original_title') or props.get('title') or title
                year = props.get('year') or year
        except Exception as e:
            log(f"AI SIMILAR - TMDB FETCH ERROR : {e}", xbmc.LOGWARNING)

    if not title:
        notify_error("ERROR Chybí název titulu.", category="AI")
        return

    progress = None
    if not is_widget:
        progress = xbmcgui.DialogProgress()
        progress.create(f"[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  ::  AI PODOBNÉ   ○ [/COLOR][/B]", "Hledám podobné tituly...")

    media_name = "film" if media_type == "movie" else "seriál"
    prompt_text = f"Najdi {limit} velmi podobných titulů k {media_name} '{title}' ({year}). Zaměř se na podobnou atmosféru, tempo, styl vyprávění, prostředí a témata, ne jen na stejný žánr. Jako reason stručně vysvětli hlavní podobnost s '{title}'."

    try:
        final_prompt = _get_ai_prompt(plugin_instance, prompt_text, limit, "")
        _process_ai_json_and_display(plugin_instance, final_prompt, progress, is_widget=is_widget)
    finally:
        if progress:
            progress.close()
        xbmcplugin.endOfDirectory(plugin_instance.handle)


def gemini_trivia(plugin_instance, params):
    title = params.get('title', '')
    year = params.get('year', '')
    media_type = params.get('media_type', 'movie')
    tmdb_id = params.get('tmdb_id', '')

    if tmdb_id and plugin_instance.tmdb_client:
        try:
            mtype = 'tv' if media_type in ('tv', 'show', 'episode') else 'movie'
            details = plugin_instance.tmdb_client.get_full_details(mtype, tmdb_id)
            if details:
                props = plugin_instance.tmdb_client._build_metadata_props(details, mtype)
                title = props.get('original_title') or props.get('title') or title
                year = props.get('year') or year
        except Exception as e:
            log(f"AI TRIVIA - TMDB FETCH ERROR : {e}", xbmc.LOGWARNING)

    if not title:
        notify_error("ERROR Chybí název titulu.", category="AI")
        return

    progress = xbmcgui.DialogProgress()
    progress.create(
        f"[B][COLOR {Colors.ORANGE}] ○   PLAY.ER  ::  AI ZAJÍMAVOSTI   ○ [/COLOR][/B]",
        "Získávám zajímavosti o natáčení..."
    )

    media_name = "film" if media_type == "movie" else "seriál"
    prompt = (
        f"Napiš 3 velmi zajímavé a málo známé fakty z natáčení "
        f"(behind the scenes) pro {media_name} '{title}' ({year}). "
        f"Odpověz v češtině, bez spoilerů. "
        f"Použij poutavý styl a odrážky pro každý fakt."
    )

    custom_instructions = plugin_instance.addon.getSettingString('ai_custom_instructions').strip()
    if custom_instructions:
        prompt += f"\n\nDodatečné instrukce uživatele:\n{custom_instructions}"

    try:
        store = _store(plugin_instance)
        key = _request_key(plugin_instance, prompt, kind='trivia')
        with store.guard('generate-' + key, blocking=False) as acquired:
            text_response = store.get(key)
            if not text_response and acquired:
                text_response = _call_ai_api(plugin_instance, prompt, json_mode=False)
                if text_response: store.put(key, text_response, ttl=604800)
        if text_response:
            dialog = xbmcgui.Dialog()
            dialog.textviewer(f"[B][COLOR {Colors.ORANGE}]AI ZAJÍMAVOSTI : {title}[/COLOR][/B]", text_response)
        else:
            notify_info("INFO Prázdná odpověď od AI.", category="AI")
    except Exception as e:
        log(f"AI TRIVIA ERROR : {e}", xbmc.LOGERROR)
        notify_error("ERROR Chyba při získávání zajímavostí.", category="AI")
    finally:
        progress.close()
        xbmcplugin.endOfDirectory(plugin_instance.handle, succeeded=True, updateListing=False, cacheToDisc=False)
