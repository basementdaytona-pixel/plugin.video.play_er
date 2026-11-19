# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: provider_prehrajto.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re
import json
import base64
import math
import requests
import time


from datetime import datetime
from urllib.parse import urljoin


import xbmc
import xbmcgui
import xbmcvfs


from resources.lib.provider_base import BaseProvider
from resources.lib.utils_filter import FilterUtils
from resources.lib.utils_theme import Colors
from resources.lib.utils_logging import log
from resources.lib import cache_manager
from resources.lib.play_mail import PlayMail
from resources.lib.utils_files import SafeVFSFile


from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_warning,
    notify_acc,
    notify_ok
)

from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_bool,
    get_setting_str
)

from resources.lib.utils import (
    convert_size,
    safe_get
)





class PrehrajTo(BaseProvider):

    """
    CLASS :: PREHRAJ.TO
    -- Třída providera Prehraj.to pro REST API v2.
    """

    def __init__(self, addon, handle, session, tmdb_client):
        super(PrehrajTo, self).__init__(addon, handle, session, tmdb_client)

        self.utils_filter = FilterUtils(addon)
        self.headers = {"user-agent": "kodi/play.er"}
        self.base_url = "https://prehraj.to"
        self.api_base = "https://prehrajto.cz/api/v2"
        self._access_token = None
        self._refresh_token = None

        self._fallback_email = 'player.8ceff2ec@deltajohnsons.com'
        self._fallback_password = 'PLAYER123!'
        self._auth_loaded = False

    def _fetch_and_set_premium_days(self, force_notify=False):
        days_left = None
        profile_failed = False
        if self._access_token:
            try:
                parts = self._access_token.split('.')
                if len(parts) == 3:
                    payload = parts[1]
                    payload += '=' * (-len(payload) % 4)
                    data = json.loads(base64.urlsafe_b64decode(payload).decode('utf-8'))

                    for key in ['premiumTo', 'premium_until', 'premiumUntil', 'subscription_end', 'premium_exp']:
                        if key in data and data[key]:
                            val = data[key]
                            if isinstance(val, (int, float)):
                                exp_date = datetime.fromtimestamp(val)
                            else:
                                exp_date = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
                            days_left = max(0, math.ceil((exp_date - datetime.now(exp_date.tzinfo)).total_seconds() / 86400))
                            break
            except Exception as e:
                log(f"PREMIUM - PREHRAJ.TO :: Chyba parsování JWT pro premium : {e}", xbmc.LOGDEBUG)

        if days_left is None:
            try:
                res = self._api_get('profile', require_auth=True)
                if res is not None and res.status_code == 200:
                    j = res.json()

                    def find_premium_days(d):
                        if isinstance(d, dict):
                            if 'premium_days' in d and str(d['premium_days']).isdigit():
                                return int(d['premium_days'])
                            if 'premiumDays' in d and str(d['premiumDays']).isdigit():
                                return int(d['premiumDays'])
                            for date_key in ['valid_to', 'validTo', 'premiumTo', 'premium_until', 'premiumUntil', 'subscription_end']:
                                if date_key in d and d[date_key]:
                                    val = d[date_key]
                                    try:
                                        if isinstance(val, (int, float)):
                                            exp = datetime.fromtimestamp(val)
                                        elif ' ' in str(val):
                                            exp = datetime.strptime(str(val).split('.')[0], "%Y-%m-%d %H:%M:%S")
                                        else:
                                            exp = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
                                        return max(0, math.ceil((exp - datetime.now(exp.tzinfo)).total_seconds() / 86400))
                                    except Exception:
                                        pass
                            for v in d.values():
                                found = find_premium_days(v)
                                if found is not None:
                                    return found
                        elif isinstance(d, list):
                            for item in d:
                                found = find_premium_days(item)
                                if found is not None:
                                    return found
                        return None

                    days_left = find_premium_days(j)
                else:
                    profile_failed = True
                    log(f'PREHRAJTO :: Nelze ověřit premium účet, HTTP {getattr(res, "status_code", "bez odpovědi")}', xbmc.LOGWARNING)
            except Exception as e:
                profile_failed = True
                log(f"PREMIUM - PREHRAJ.TO :: Chyba API profilu pro premium : {e}", xbmc.LOGDEBUG)

        if profile_failed:
            return None

        if days_left is None:
            log('PREHRAJTO :: Platnost premium není v odpovědi profilu uvedena; automatická registrace se nespustí', xbmc.LOGWARNING)
            return None

        main_window = xbmcgui.Window(10000)
        notified_prop = "player.prehrajto.premium.notified"
        if days_left is not None and days_left >= 0:
            safe_days = max(0, days_left)
            main_window.setProperty("player.prehrajto.premium_days", str(safe_days))
            if force_notify or not main_window.getProperty(notified_prop):
                log(f"PREMIUM - PREHRAJ.TO :: AKTIVNÍ [ ZBÝVÁ  {safe_days}  DNÍ ]", xbmc.LOGINFO)
                notify_acc(f'PREHRAJ.TO PREMIUM AKTIVNÍ :: {safe_days} DNÍ', category='PROVIDER')
                main_window.setProperty(notified_prop, "true")
            expiry_prop = "player.prehrajto.premium.expiry_notified"
            if (safe_days <= 2 and get_setting_bool(self.addon, 'notify_premium_expiry', False)
                    and main_window.getProperty(expiry_prop) != str(safe_days)):
                notify_warning(self.addon.getLocalizedString(32811).format(days=safe_days), category='PROVIDER')
                main_window.setProperty(expiry_prop, str(safe_days))
            elif safe_days > 2:
                main_window.clearProperty(expiry_prop)
            return safe_days
        else:
            main_window.setProperty("player.prehrajto.premium_days", "0")
            if force_notify or not main_window.getProperty(notified_prop):
                log("PREMIUM - PREHRAJ.TO :: FREE ACCOUNT!", xbmc.LOGINFO)
                notify_acc('PREHRAJ.TO POZOR :: FREE ÚČET!', category='PROVIDER')
                main_window.setProperty(notified_prop, "true")
            return 0

    def _extract_tokens_from_response(self, j):
        token_block = {}
        if isinstance(j, dict):
            if 'data' in j and isinstance(j['data'], dict):
                token_block = j['data'].get('token') or j['data'].get('tokens') or j['data']
            if not token_block and 'payload' in j and isinstance(j['payload'], dict):
                p_data = j['payload'].get('data') or {}
                if isinstance(p_data, dict):
                    token_block = p_data.get('token') or p_data.get('tokens') or p_data

        if isinstance(token_block, dict):
            access = token_block.get('access') or token_block.get('access_token')
            refresh = token_block.get('refresh') or token_block.get('refresh_token')
            return access, refresh
        return None, None

    def _auth_file(self):
        return xbmcvfs.translatePath("special://profile/addon_data/plugin.video.play_er/PREHRAJTO_COOKIES.JSON")

    def _set_tokens(self, access, refresh):
        self._access_token = access
        self._refresh_token = refresh
        if access:
            self.headers['Authorization'] = f'Bearer {access}'
        else:
            self.headers.pop('Authorization', None)

    def _load_auth_state(self):
        if getattr(self, '_auth_loaded', False):
            return
        self._auth_loaded = True
        canonical = self._auth_file()
        legacy = xbmcvfs.translatePath("special://profile/addon_data/plugin.video.play_er/PREHRAJTO_TOKENS.JSON")
        for path in (canonical, legacy):
            if not xbmcvfs.exists(path):
                continue
            try:
                with SafeVFSFile(path, 'r') as f:
                    state = json.loads(f.read() or '{}')
                if not isinstance(state, dict):
                    raise ValueError('JSON root is not an object')
                token = state.get('token') or state.get('tokens') or state
                if not isinstance(token, dict):
                    raise ValueError('token block is not an object')
                access = token.get('access') or token.get('access_token')
                refresh = token.get('refresh') or token.get('refresh_token')
                if path == canonical:
                    cookies = {k: v for k, v in state.items() if k not in ('token', 'tokens', 'access', 'refresh', 'access_token', 'refresh_token')}
                    if cookies:
                        self.session.cookies.update(cookies)
                if access or refresh:
                    self._set_tokens(access, refresh)
                    if path == legacy:
                        self._save_auth_state()
                    return
            except Exception as exc:
                log(f'PREHRAJTO :: Nelze načíst uložené přihlášení ({os.path.basename(path)}): {type(exc).__name__}', xbmc.LOGWARNING)

    def _save_auth_state(self):
        if not self._access_token:
            return False
        try:
            state = dict(self.session.cookies.get_dict())
            state['token'] = {'access': self._access_token, 'refresh': self._refresh_token}
            with SafeVFSFile(self._auth_file(), 'w') as f:
                f.write(json.dumps(state))
            legacy = xbmcvfs.translatePath("special://profile/addon_data/plugin.video.play_er/PREHRAJTO_TOKENS.JSON")
            if xbmcvfs.exists(legacy):
                xbmcvfs.delete(legacy)
            return True
        except Exception as exc:
            log(f'PREHRAJTO :: Nelze uložit přihlášení: {type(exc).__name__}', xbmc.LOGWARNING)
            return False

    def _token_needs_refresh(self):
        if not self._access_token:
            return True
        try:
            payload = self._access_token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            issued = int(claims['iat'])
            expires = int(claims['exp'])
            ttl_minutes = get_setting_int_with_bounds(self.addon, 'prehrajto_token_ttl', 50, 5, 180)
            # TTL is only an earlier refresh threshold; it cannot extend server validity.
            return time.time() >= min(expires, issued + ttl_minutes * 60) - 60
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            # Unknown token format: let the API response determine validity.
            return False

    def replace_account_credentials(self, email, password):
        """Activate a successfully registered account and retire old auth state."""
        self.addon.setSetting('email', email)
        self.addon.setSetting('password', password)
        for filename in ('PREHRAJTO_COOKIES.JSON', 'PREHRAJTO_TOKENS.JSON'):
            path = xbmcvfs.translatePath(f"special://profile/addon_data/plugin.video.play_er/{filename}")
            if xbmcvfs.exists(path):
                xbmcvfs.delete(path)
        self._set_tokens(None, None)
        self.session.cookies.clear()
        self._auth_loaded = True
        win = xbmcgui.Window(10000)
        win.clearProperty("player.prehrajto.premium.notified")
        win.clearProperty("player.prehrajto.premium.expiry_notified")
        win.clearProperty("player.prehrajto.premium_days")

    def _auto_register_new_account(self):
        win = xbmcgui.Window(10000)
        if win.getProperty("play_er.prehrajto.auto_reg_running") == "true":
            return False

        win.setProperty("play_er.prehrajto.auto_reg_running", "true")
        try:
            log("AUTO-REGISTER :: Spouštím automatickou registraci nového VIP účtu ...", xbmc.LOGINFO)
            notify_info("INFO Platnost VIP končí - vytvářím nový účet ...", category="PREMIUM", time=10000, sound=True)

            mail_bot = PlayMail(self.addon)
            email, password = mail_bot.register_account()

            if email and password:
                self.replace_account_credentials(email, password)

                xbmcgui.Dialog().ok(
                    f"[B][COLOR {Colors.LIMEGREEN}] ○   | PLAY.ER |  ::  ÚČET OBNOVEN   ○ [/COLOR][/B]",
                    f"Vaše předplatné kleslo na hranici expirace.\nAutomaticky byl zaregistrován nový 30-denní VIP účet!\n\n[COLOR {Colors.ORANGE}]NOVÝ E-MAIL : {email}[/COLOR]"
                )
                return True
            else:
                xbmcgui.Dialog().ok(
                    f"[B][COLOR {Colors.RED}] ○   | PLAY.ER |  ::  CHYBA OBNOVY   ○ [/COLOR][/B]",
                    "Automatická obnova účtu prehraj.to selhala!\nZkuste to prosím později nebo manuálně."
                )
                return False
        except Exception as e:
            log(f"AUTO-REGISTER :: ERROR : {e}", xbmc.LOGERROR)
            return False
        finally:
            win.clearProperty("play_er.prehrajto.auto_reg_running")

    def get_premium_cookies(self, force=False):
        self._load_auth_state()

        def _check_and_auto_register():
            auto_register = get_setting_bool(self.addon, 'enable_auto_register', True)
            if not auto_register and not get_setting_bool(self.addon, 'notify_premium_expiry', False):
                return False
            days_left = self._fetch_and_set_premium_days()
            if auto_register and days_left is not None and days_left <= 2:
                log(f"PREMIUM :: ZBÝVÁ {days_left} DNÍ -> SPOUŠTÍM AUTO-REGISTRACI", xbmc.LOGINFO)
                if self._auto_register_new_account():
                    return True
            return False

        if not force and self._access_token:
            if self._token_needs_refresh():
                if not self._refresh_access_token():
                    log('PREHRAJTO :: Obnova tokenu selhala, opakuji přihlášení', xbmc.LOGWARNING)
                    force = True
            if not force and _check_and_auto_register():
                force = True
            if not force:
                return self.session.cookies
        elif not force and self._refresh_token:
            if self._refresh_access_token():
                if not _check_and_auto_register():
                    return self.session.cookies

        email = get_setting_str(self.addon, 'email', '')
        password = get_setting_str(self.addon, 'password', '')

        if not email or not password:
            email = email or self._fallback_email
            password = password or self._fallback_password

        main_window = xbmcgui.Window(10000)

        if not email or not password:
            log('PREHRAJTO :: Chybí email nebo heslo v nastavení', xbmc.LOGWARNING)
            notify_info('PREHRAJ.TO CHYBÍ PŘIHLAŠOVACÍ ÚDAJE', category='PROVIDER')
            main_window.setProperty('player.prehrajto.login.failed', 'true')
            return None

        login_api = f"{self.api_base}/users/login"
        payload = {"email": email, "password": password}
        self._set_tokens(None, None)

        try:
            res = self.session.post(login_api, json=payload, headers={'Content-Type': 'application/json', 'User-Agent': self.headers.get('user-agent'), 'Authorization': None}, timeout=10)
            if getattr(res, 'status_code', None) == 200:
                access, refresh = self._extract_tokens_from_response(res.json())
                if access:
                    self._set_tokens(access, refresh)

                    notify_acc(f'PREHRAJ.TO PŘIHLÁŠEN : {email}', category='PROVIDER')
                    self._fetch_and_set_premium_days(force_notify=True)

                    self._save_auth_state()

                    main_window.clearProperty('player.prehrajto.login.failed')
                    return self.session.cookies
            log(f'PREHRAJTO :: Přihlášení odmítnuto, HTTP {getattr(res, "status_code", "?")}', xbmc.LOGWARNING)

        except requests.exceptions.Timeout:
            log('PREHRAJTO :: Timeout API (LOGIN)', xbmc.LOGWARNING)
            notify_error('PREHRAJ.TO ERROR : VÝPADEK PŘIPOJENÍ', category='PROVIDER')
        except Exception as e:
            log(f'PREHRAJTO :: Chyba parsování login odpovědi : {e}', xbmc.LOGERROR)

        notify_error('PREHRAJ.TO ERROR : CHYBA PŘIHLÁŠENÍ', category='PROVIDER')
        main_window.setProperty('player.prehrajto.login.failed', 'true')
        return None

    def _refresh_access_token(self):
        if not self._refresh_token:
            return False
        refresh_api = f"{self.api_base}/users/refresh-token"
        payload = {'refreshToken': self._refresh_token}
        try:
            res = self.session.post(refresh_api, json=payload, headers={'Content-Type': 'application/json', 'User-Agent': self.headers.get('user-agent'), 'Authorization': None}, timeout=10)
            if getattr(res, 'status_code', None) == 200:
                access, refresh = self._extract_tokens_from_response(res.json())
                if access:
                    self._set_tokens(access, refresh or self._refresh_token)
                    self._save_auth_state()
                    return True
            log(f'PREHRAJTO :: Obnova tokenu odmítnuta, HTTP {getattr(res, "status_code", "?")}', xbmc.LOGWARNING)
        except Exception as e:
            log(f'PREHRAJTO :: REFRESH ERROR : {e}', xbmc.LOGWARNING)
        return False

    def _api_get(self, path, params=None, require_auth=False):
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {'User-Agent': self.headers.get('user-agent')}
        if require_auth and self._access_token:
            headers['Authorization'] = f'Bearer {self._access_token}'
        try:
            res = self.session.get(url, params=params, headers=headers, timeout=10)
            if require_auth and getattr(res, 'status_code', None) == 401:
                renewed = self._refresh_access_token() if self._refresh_token else False
                if not renewed and path.strip('/') != 'profile':
                    self.get_premium_cookies(force=True)
                    renewed = bool(self._access_token)
                if renewed and self._access_token:
                    headers['Authorization'] = f'Bearer {self._access_token}'
                    res = self.session.get(url, params=params, headers=headers, timeout=10)
            return res
        except Exception as e:
            log(f'PREHRAJTO - API GET ERROR {url} : {e}', xbmc.LOGWARNING)
        return None

    def _api_post(self, path, json_payload=None, require_auth=False):
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {'User-Agent': self.headers.get('user-agent'), 'Content-Type': 'application/json'}
        if require_auth and self._access_token:
            headers['Authorization'] = f'Bearer {self._access_token}'
        try:
            res = self.session.post(url, json=json_payload, headers=headers, timeout=10)
            if require_auth and getattr(res, 'status_code', None) == 401:
                renewed = self._refresh_access_token() if self._refresh_token else False
                if not renewed:
                    self.get_premium_cookies(force=True)
                    renewed = bool(self._access_token)
                if renewed and self._access_token:
                    headers['Authorization'] = f'Bearer {self._access_token}'
                    res = self.session.post(url, json=json_payload, headers=headers, timeout=10)
            return res
        except Exception as e:
            log(f'PREHRAJTO - API POST ERROR {url} : {e}', xbmc.LOGWARNING)
        return None

    def api_track_view(self, video_id):
        try:
            self._api_post(f'videos/{video_id}/view', json_payload={}, require_auth=True)
        except Exception:
            pass

    def _video_response_data(self, response):
        """Accept only successful object responses and decode JSON once."""
        if response is None or getattr(response, 'status_code', None) != 200:
            return None
        try:
            data = response.json()
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        if 'data' in data:
            data = data['data']
        elif 'payload' in data:
            payload = data['payload']
            data = payload.get('data') if isinstance(payload, dict) else None
        return data if isinstance(data, dict) else None

    def api_get_video_detail(self, video_id):
        res = self._api_get(f'videos/{video_id}', require_auth=True)
        return self._video_response_data(res)

    def api_get_video_subtitle(self, video_id, detail=...):
        if detail is Ellipsis:
            detail = self.api_get_video_detail(video_id)
        subs = detail.get('subtitles') if detail else None
        return [sub for sub in subs if isinstance(sub, dict)] if isinstance(subs, list) else []

    def suggest(self, phrase, limit=6):
        if not phrase:
            return []
        try:
            self.get_premium_cookies()
            res = self._api_get('videos/suggest', params={'phrase': phrase}, require_auth=True)
            if not res:
                res = self._api_get('videos/suggest', params={'phrase': phrase}, require_auth=False)
            if not res:
                return []
            j = res.json()
            data = (j.get('payload') or {}).get('data') or j.get('data') or []
            phrases = []
            for item in data:
                p = item.get('phrase') if isinstance(item, dict) else item
                if p and isinstance(p, str):
                    phrases.append(p)

            seen = set()
            out = []
            for p in phrases:
                if p not in seen:
                    seen.add(p)
                    out.append(p)
                if len(out) >= limit:
                    break
            return out
        except Exception as e:
            log(f"PREHRAJTO - Suggest error: {e}", xbmc.LOGWARNING)
            return []

    def api_get_download_link(self, video_id, detail=...):
        if detail is Ellipsis:
            detail = self.api_get_video_detail(video_id)
        valid_links = {}

        orig_link = None
        ext = "MKV"
        res = self._api_get(f'videos/{video_id}/download', require_auth=True)
        data = self._video_response_data(res)
        if data:
            orig_link = next((value for key in ('download_link', 'link', 'url')
                              if isinstance((value := data.get(key)), str) and value.strip()), None)
            if orig_link and detail and detail.get('extension'):
                ext = str(detail.get('extension')).upper()

        transcodes = {}
        if detail:
            links_obj = detail.get('links') or {}
            if isinstance(links_obj, dict):
                for k, v in links_obj.items():
                    if v and isinstance(v, str):
                        try:
                            transcodes[int(k)] = v
                        except Exception:
                            transcodes[k] = v
            elif isinstance(links_obj, list) and links_obj:
                for item in links_obj:
                    if not isinstance(item, dict):
                        continue
                    url = next((value for key in ('url', 'link')
                                if isinstance((value := item.get(key)), str) and value.strip()), None)
                    if url:
                        transcodes[0] = url
                        break

        if orig_link:
            valid_links[f'ORIGINAL ({ext})'] = orig_link

        sorted_res = sorted([k for k in transcodes.keys() if isinstance(k, int)], reverse=True)
        for res_val in sorted_res:
            if res_val > 0:
                valid_links[f'{res_val}P'] = transcodes[res_val]
            else:
                valid_links['Základní Stream'] = transcodes[res_val]

        for k, v in transcodes.items():
            if not isinstance(k, int):
                valid_links[f'{k} Stream'] = v

        return valid_links

    def get_video_link(self, video_id):
        self.get_premium_cookies()

        vid_str = str(video_id)
        m = re.search(r"([0-9]{5,12})", vid_str)
        vid = m.group(1) if m else vid_str

        if not vid or not vid.isdigit():
            log("PREHRAJTO - Neplatné ID videa pro získání streamu!", xbmc.LOGERROR)
            notify_error('PREHRAJ.TO CHYBNÉ ID STREAMU', category='PROVIDER')
            return None, []

        self.api_track_view(vid)
        # A failed lookup is also reused for this resolution; no persistent cache.
        detail = self.api_get_video_detail(vid)
        available_links = self.api_get_download_link(vid, detail=detail)

        if available_links:
            xbmcgui.Window(10000).setProperty(f"play_er.qualities.{vid}", json.dumps(available_links))
        else:
            xbmcgui.Window(10000).clearProperty(f"play_er.qualities.{vid}")

        subs = self.api_get_video_subtitle(vid, detail=detail)
        sub_urls = []
        if subs:
            from resources.lib.utils_files import ensure_dir
            # Prefetch must not delete or replace another video's subtitle files.
            sub_dir = xbmcvfs.translatePath(f"special://temp/play_er_subs/{vid}/")
            ensure_dir(sub_dir)

            cz_sk_subs = []
            other_subs = []
            unk_counter = 1

            for sub_index, s in enumerate(subs):
                url = s.get('cdnUrl')
                if not url or s.get('isBroken'):
                    continue

                lang_code = str(s.get('language') or '').lower()
                lang_name = str(s.get('name') or '').upper()

                if not lang_name or lang_name == 'NONE':
                    lang_name = f"UNK_{unk_counter:02d}"
                    unk_counter += 1

                safe_name = "".join(c for c in lang_name if c.isalnum() or c in (" ", "_", "-"))
                if not safe_name:
                    safe_name = f"SUB_{unk_counter:02d}"
                local_file = os.path.join(sub_dir, f"{safe_name}_{sub_index}.vtt")

                try:
                    resp = safe_get(self.session, url, timeout=5)
                    if resp and resp.content:
                        with open(local_file, 'wb') as f:
                            f.write(resp.content)

                    if os.path.exists(local_file):
                        if any(l in lang_code for l in ('cze', 'ces', 'cs', 'slo', 'slv', 'sk')):
                            cz_sk_subs.append(local_file)
                        else:
                            other_subs.append(local_file)
                except Exception as e:
                    log(f"PREHRAJTO - Chyba stahování titulků: {e}", xbmc.LOGWARNING)
                    continue

            sub_urls = cz_sk_subs + other_subs

        xbmcgui.Window(10000).setProperty(f"play_er.subtitles.{vid}", json.dumps(sub_urls))

        if not available_links:
            return None, sub_urls

        stream_mode = self.addon.getSettingString("prehrajto_stream_mode") or "auto"
        pref_quality = self.addon.getSettingString("prehrajto_pref_quality") or "highest"

        try:
            max_bandwidth = float(self.addon.getSetting("max_bandwidth_mbps") or "0")
        except Exception:
            max_bandwidth = 0.0

        selected_url = None
        quality_bitrates = {1080: 3.5, 720: 1.5, 480: 0.8}

        win = xbmcgui.Window(10000)
        saved_choice = win.getProperty("play_er.playlist_quality_choice")
        is_bg_playlist = win.getProperty("play_er.bg_playlist_active") == "true"
        is_playing = xbmc.Player().isPlayingVideo()
        is_tmdbh_autoplay = win.getProperty("play_er.tmdbh_autoplay") == "true"

        if len(available_links) == 1:
            selected_url = list(available_links.values())[0]

        elif stream_mode == "ask":
            if saved_choice and any(saved_choice in k for k in available_links.keys()):
                for k, v in available_links.items():
                    if saved_choice in k:
                        selected_url = v
                        break
            elif is_bg_playlist or is_tmdbh_autoplay or (is_playing and win.getProperty("play_er.series_playlist_active") == "true"):
                stream_mode = "auto"
            else:
                options = list(available_links.keys())
                urls = list(available_links.values())
                from resources.lib.utils import pop_dialog_select
                choice = pop_dialog_select(f"[COLOR {Colors.ORANGE}] ○  VÝBĚR KVALITY STREAMU  ○ [/COLOR]", options)
                if choice == -1:
                    return None, []
                selected_url = urls[choice]
                win.setProperty("play_er.playlist_quality_choice", options[choice])

        if stream_mode != "ask" and not selected_url:
            q_dict = {}
            original_url = None
            original_bitrate = 0.0

            if detail:
                try:
                    s_bytes = float(detail.get('size', 0))
                    duration_s = float(detail.get('length') or detail.get('duration') or 0)
                    if s_bytes > 0 and duration_s > 0:
                        original_bitrate = (s_bytes * 8) / (duration_s * 1024 * 1024)
                except Exception:
                    pass

            for k, v in available_links.items():
                if "ORIGINAL" in k.upper():
                    original_url = v
                else:
                    nums = re.findall(r'\d+', k)
                    if nums:
                        q_dict[int(nums[0])] = v

            if max_bandwidth > 0.0:
                if original_url and original_bitrate > max_bandwidth:
                    original_url = None
                    if pref_quality == "original":
                        pref_quality = "highest"
                to_remove = [q for q, _ in q_dict.items() if quality_bitrates.get(q, 10.0) > max_bandwidth]
                for q in to_remove:
                    del q_dict[q]

            sorted_q = sorted(q_dict.keys(), reverse=True)

            if pref_quality == "original" and original_url:
                selected_url = original_url
            elif sorted_q:
                if pref_quality in ("original", "highest"):
                    selected_url = q_dict[sorted_q[0]]
                elif pref_quality == "lowest":
                    selected_url = q_dict[sorted_q[-1]]
                else:
                    target_q = 1080 if pref_quality == "1080p" else (720 if pref_quality == "720p" else 480)
                    for q in sorted_q:
                        if q <= target_q:
                            selected_url = q_dict[q]
                            break
                    if not selected_url:
                        selected_url = q_dict[sorted_q[-1]]

            if not selected_url:
                if q_dict:
                    selected_url = q_dict[sorted_q[-1]]
                elif original_url:
                    selected_url = original_url
                else:
                    selected_url = list(available_links.values())[0]

        return selected_url, sub_urls

    def _apply_multi_indicator(self, it, title, mark_multi):
        if not mark_multi:
            return title

        has_multi = False
        for k in ('links', 'files', 'qualities', 'resolutions', 'streams'):
            val = it.get(k)
            if isinstance(val, dict):
                valid_links = [v for v in val.values() if v and isinstance(v, str)]
                if len(valid_links) > 1 or (len(valid_links) == 1 and str(it.get('extension', '')).lower() in ('mkv', 'avi')):
                    has_multi = True
                    break
            elif isinstance(val, list) and len(val) > 1:
                has_multi = True
                break

        if not has_multi:
            ext = str(it.get('extension', '')).lower()
            if ext in ('mkv', 'avi'):
                has_multi = True
            else:
                for key, threshold in (('originalHeight', 700), ('size', 1073741825)):
                    try:
                        if int(it.get(key) or 0) >= threshold:
                            has_multi = True
                    except (ValueError, TypeError, OverflowError):
                        continue

        return f"► {title}" if has_multi else title

    def _search_response_items(self, response, endpoint):
        """Decode each response once and normalize the supported list envelopes."""
        if response is None or getattr(response, 'status_code', None) != 200:
            status = getattr(response, 'status_code', None)
            log(f'PREHRAJTO :: Vyhledávání selhalo ({endpoint}), HTTP {status or "bez odpovědi"}', xbmc.LOGWARNING)
            reason = 'PŘIHLÁŠENÍ SELHALO' if status in (401, 403) else 'VYHLEDÁVÁNÍ SELHALO'
            notify_error(f'PREHRAJ.TO ERROR : {reason}', category='PROVIDER')
            return None
        try:
            items = response.json()
            for _ in range(6):
                if isinstance(items, list):
                    return items
                if not isinstance(items, dict):
                    break
                if not items:
                    return []
                key = next((key for key in ('data', 'items', 'results', 'payload')
                            if key in items and items[key] is not None), None)
                if key is None:
                    break
                items = items[key]
        except (ValueError, TypeError):
            pass
        log('PREHRAJTO :: Vyhledávání vrátilo neplatný JSON', xbmc.LOGWARNING)
        notify_error('PREHRAJ.TO ERROR : NEPLATNÁ ODPOVĚĎ VYHLEDÁVÁNÍ', category='PROVIDER')
        return None

    def search_sources(self, query, cookies=None, apply_filters=True):
        """
        PREHRAJTO :: SMART SEARCH AND FILTER RESULTS
        -- Filtruje, chytře vyhledává a automaticky koriguje délku epizod.
        """
        self.get_premium_cookies()

        search_pages = get_setting_int_with_bounds(self.addon, 'search_pages', 2, 1, 10)
        search_ls = get_setting_int_with_bounds(self.addon, 'search_ls', 32, 32, 416)
        mark_multi = get_setting_bool(self.addon, 'prehrajto_mark_multi_streams', True)
        is_filtering_enabled = get_setting_bool(self.addon, 'enable_filtering', True)

        api_sort_idx = get_setting_int_with_bounds(self.addon, 'prehrajto_api_sort', 0, 0, 2)
        api_quality_idx = get_setting_int_with_bounds(self.addon, 'prehrajto_api_quality', 0, 0, 3)

        sort_map = {0: "relevance", 1: "popularity", 2: "relevance"}
        quality_map = {0: "", 1: "4k", 2: "1080p", 3: "720p"}

        api_sort = sort_map.get(api_sort_idx, "relevance")
        api_quality = quality_map.get(api_quality_idx, "")

        smart_query = re.sub(r'[:\-]', ' ', query)
        smart_query = re.sub(r'\s+', ' ', smart_query).strip()

        # Detekce epizody seriálu (např. S01E02 nebo 1x02) - u epizod NESMÍME filtrovat >20 minut!
        is_episode_query = bool(re.search(r'\b[Ss]\d+[Ee]\d+\b|\b\d+x\d+\b', smart_query))

        all_videos = []
        seen_links = set()
        for p in range(1, search_pages + 1):
            limit = 32
            offset = (p - 1) * limit

            params = {
                'phrase': smart_query,
                'limit': limit,
                'offset': offset
            }

            if is_filtering_enabled:
                if not is_episode_query:
                    params['filterLongerThan20min'] = 1
                if api_sort:
                    params['sort'] = api_sort
                if api_quality:
                    params['quality'] = api_quality

            api_resp = self._api_get('videos/search', params=params, require_auth=bool(self._access_token))

            items = self._search_response_items(api_resp, 'videos/search')
            if items is None:
                break
            used_suggest = False
            if not items:
                if p != 1:
                    break
                log(f"PREHRAJTO - Běžné hledání '{smart_query}' vrátilo 0 výsledků. Zkouším suggest fallback.", xbmc.LOGINFO)
                api_resp = self._api_get('videos/suggest', params={'phrase': smart_query}, require_auth=bool(self._access_token))
                items = self._search_response_items(api_resp, 'videos/suggest')
                used_suggest = True
                if not items:
                    break

            previous_count = len(all_videos)
            if items:
                for it in items:
                    if len(all_videos) >= search_ls:
                        break
                    if not isinstance(it, dict):
                        continue
                    title = next((value.strip() for value in (it.get('title'), it.get('name'))
                                  if isinstance(value, str) and value.strip()), 'Neznámý titul')
                    title = self._apply_multi_indicator(it, title, mark_multi)
                    tl = title.lower()

                    link = next((value.strip() for key in ('videoPage', 'pageUrl', 'link', 'url')
                                 if isinstance((value := it.get(key)), str) and value.strip()), None)
                    video_id = it.get('id')
                    if not link and isinstance(video_id, (str, int)) and not isinstance(video_id, bool) and str(video_id).isascii() and str(video_id).isdecimal() and int(video_id) > 0:
                        link = urljoin(self.base_url, f"/videos/{video_id}")
                    if not link or link in seen_links:
                        continue

                    size_str = ''
                    if it.get('size') is not None:
                        try:
                            size_str = convert_size(int(it.get('size')))
                        except Exception:
                            size_str = str(it.get('size'))

                    duration_str = str(it.get('duration') or it.get('length') or '')
                    api_tags = set()
                    ext = str(it.get('extension') or '').lower()

                    h = it.get('originalHeight')
                    if h:
                        try:
                            height = int(h)
                            if height >= 2160: api_tags.add('4K')
                            elif height >= 1080: api_tags.add('1080P')
                            elif height >= 720: api_tags.add('720P')
                        except Exception:
                            pass

                    has_cz_subs_api = False
                    has_cz_audio_api = False
                    has_sk_audio_api = False

                    subs = it.get('subtitles', [])
                    if subs and isinstance(subs, list):
                        for s in subs:
                            lang = str(s.get('language') or '' if isinstance(s, dict)
                                       else s if isinstance(s, str) else '').lower()
                            if any(l in lang for l in ('cze', 'ces', 'cs', 'sk', 'slo', 'slv')):
                                api_tags.add('TIT')
                                has_cz_subs_api = True
                                break

                    audio_tracks = it.get('audio') or it.get('audios') or it.get('languages') or []
                    if isinstance(audio_tracks, list):
                        for a in audio_tracks:
                            lang = str(a.get('language', a) if isinstance(a, dict) else a).lower()
                            if any(l in lang for l in ('cze', 'ces', 'cs')):
                                api_tags.add('DAB')
                                has_cz_audio_api = True
                                break
                            elif any(l in lang for l in ('sk', 'slo', 'slv')):
                                api_tags.add('SK')
                                has_sk_audio_api = True
                                break

                    has_cz_word = re.search(r'\b(cz|sk)\b', tl)
                    is_explicit_dub = re.search(r'\b(dabing|dab|czdab|czdabing|skdab|skdabing)\b', tl)
                    has_sub_keywords = re.search(r'\b(titulky|tit|cztit|cztitulky|sub|subs)\b', tl)

                    if has_sub_keywords and not has_cz_subs_api:
                        api_tags.add('TIT')

                    if not has_cz_audio_api and not has_sk_audio_api:
                        if is_explicit_dub:
                            api_tags.add('DAB')
                        elif has_cz_word:
                            if has_cz_subs_api or has_sub_keywords:
                                api_tags.add('TIT')
                            else:
                                api_tags.add('DAB')

                    likes = 0
                    dislikes = 0
                    thumbs = it.get('thumbs')
                    thumbs = thumbs.get('global') if isinstance(thumbs, dict) else None
                    thumbs = thumbs if isinstance(thumbs, dict) else {}
                    if thumbs:
                        try:
                            likes = int(thumbs.get('up', 0))
                            dislikes = int(thumbs.get('down', 0))
                        except Exception:
                            pass

                    if not ext:
                        match = re.search(r'\.(mp4|avi|mkv|wmv|mov|flv|webm)\b', title, re.IGNORECASE)
                        if match:
                            ext = match.group(1).lower()

                    if link and link not in seen_links:
                        seen_links.add(link)
                        all_videos.append({
                            'title': title,
                            'link': link,
                            'size_str': size_str,
                            'duration_str': duration_str,
                            'id': it.get('id'),
                            'provider': 'prehraj.to',
                            'provider_color': Colors.ORANGE,
                            'tags': list(api_tags),
                            'extension': ext,
                            'likes': likes,
                            'dislikes': dislikes
                        })

                if (len(all_videos) >= search_ls or used_suggest
                        or len(items) < limit or len(all_videos) == previous_count):
                    break
            else:
                break

        return self.normalize_and_filter(all_videos, apply_filters=apply_filters)

    def _get_video_pages(self, endpoint, require_auth=False, extra_params=None):
        """Fetch a bounded list; stop if a server ignores pagination."""
        max_pages = get_setting_int_with_bounds(self.addon, 'max_pages', default=5, min_val=1, max_val=10)
        videos, seen = [], set()
        for page in range(max_pages):
            params = dict(extra_params or {}, limit=32, offset=page * 32)
            response = self._api_get(endpoint, params=params, require_auth=require_auth)
            if response is None or response.status_code != 200:
                if page:
                    raise RuntimeError('PREHRAJ.TO: incomplete paginated response')
                return None
            payload = response.json()
            items = (payload.get('payload') or {}).get('data') or payload.get('data') or payload.get('items') or []
            if isinstance(items, dict):
                items = items.get('items') or items.get('data') or []
            if not isinstance(items, list):
                return None
            added = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = item.get('id') or item.get('videoPage') or item.get('pageUrl') or item.get('link') or item.get('url')
                if key is None or str(key) in seen:
                    continue
                seen.add(str(key))
                videos.append(item)
                added += 1
            if len(items) < 32 or not added:
                break
        return videos

    def get_most_watched(self):
        use_cache = get_setting_bool(self.addon, "enable_most_watched_cache", True)
        max_pages = get_setting_int_with_bounds(self.addon, 'max_pages', default=5, min_val=1, max_val=10)
        mark_multi = get_setting_bool(self.addon, 'prehrajto_mark_multi_streams', True)
        cache_key = f"prehrajto_most_watched_pages_{max_pages}_multi_{int(mark_multi)}"
        if use_cache:
            cached_videos = cache_manager.cache_get("MOST_WATCHED", cache_key)
            if cached_videos:
                return cached_videos

        self.get_premium_cookies()
        videos = []
        try:
            items = None
            for period in (None, 'day', 'week', 'month', 'all'):
                params = {'time-period': period} if period else None
                items = self._get_video_pages('videos/most-watched',
                                              require_auth=bool(self._access_token), extra_params=params)
                if items is not None:
                    break
            if items is None:
                return videos

            for it in items:
                title = it.get('title') or it.get('name') or 'Neznámý titul'
                title = self._apply_multi_indicator(it, title, mark_multi)
                link = it.get('videoPage') or it.get('pageUrl') or it.get('link') or it.get('url')
                if not link and it.get('id'):
                    link = urljoin(self.base_url, f"/videos/{it.get('id')}")

                size_str = ''
                if it.get('size') is not None:
                    try:
                        size_str = convert_size(int(it.get('size')))
                    except Exception:
                        size_str = str(it.get('size'))

                likes = 0
                thumbs = it.get('thumbs', {}).get('global', {})
                if thumbs:
                    try:
                        likes = int(thumbs.get('up', 0))
                    except Exception:
                        pass

                if link:
                    videos.append({
                        'title': title,
                        'link': link,
                        'size_str': size_str,
                        'duration_str': str(it.get('duration') or it.get('length') or ''),
                        'id': it.get('id'),
                        'provider': 'prehraj.to',
                        'provider_color': Colors.ORANGE,
                        'likes': likes,
                        'is_series': it.get('type') == 'series' or 'S0' in title.upper() or 'E0' in title.upper()
                    })
        except Exception:
            pass

        if videos and use_cache:
            cache_manager.cache_set("MOST_WATCHED", cache_key, videos)

        return videos

    def get_user_history(self):
        cookies = self.get_premium_cookies()
        if not cookies and not self._access_token:
            notify_info('PREHRAJ.TO ZOBRAZENÍ VYŽADUJE LOGIN', category='PROVIDER')
            return []
        try:
            mark_multi = get_setting_bool(self.addon, 'prehrajto_mark_multi_streams', True)
            items = self._get_video_pages('profile/videos/watched', require_auth=True)
            if items is not None:

                videos = []
                for it in items:
                    title = it.get('title') or it.get('name') or 'Neznámý titul'
                    title = self._apply_multi_indicator(it, title, mark_multi)
                    link = it.get('videoPage') or it.get('pageUrl') or it.get('link') or it.get('url')
                    if not link and it.get('id'):
                        link = urljoin(self.base_url, f"/videos/{it.get('id')}")

                    size_str = ''
                    if it.get('size') is not None:
                        try:
                            size_str = convert_size(int(it.get('size')))
                        except Exception:
                            size_str = str(it.get('size'))

                    likes = 0
                    thumbs = it.get('thumbs', {}).get('global', {})
                    if thumbs:
                        try:
                            likes = int(thumbs.get('up', 0))
                        except Exception:
                            pass

                    if link:
                        videos.append({
                            'title': title,
                            'link': link,
                            'size_str': size_str,
                            'duration_str': str(it.get('duration') or it.get('length') or ''),
                            'id': it.get('id'),
                            'provider': 'prehraj.to',
                            'provider_color': Colors.ORANGE,
                            'likes': likes
                        })
                return videos
        except Exception:
            pass

        notify_info('PREHRAJ.TO HISTORIE NENÍ DOSTUPNÁ', category='PROVIDER')
        return []
