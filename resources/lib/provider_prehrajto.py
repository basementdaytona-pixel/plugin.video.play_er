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
import hashlib
import hmac
import math
import requests
import tempfile
import threading
import time


from datetime import datetime
from urllib.parse import urljoin


import xbmc
import xbmcgui
import xbmcvfs


from resources.lib.provider_base import BaseProvider
from resources.lib.search_results import SearchResults
from resources.lib.stream_quality import stream_quality
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





def _page_fingerprint(items):
    """Identify a repeated page without depending on ordering or mutable metadata."""
    try:
        rows = []
        for item in items:
            identity = []
            if isinstance(item, dict):
                for key in ('id', 'videoPage', 'pageUrl', 'link', 'url'):
                    value = item.get(key)
                    if isinstance(value, str):
                        value = value.strip()
                    if value and isinstance(value, (str, int)) and not isinstance(value, bool):
                        identity.append((key, value))
            rows.append(json.dumps(['identified', identity] if identity else ['raw', item],
                                   sort_keys=True, ensure_ascii=True, separators=(',', ':')))
        rows.sort()
        return hashlib.sha256('\n'.join(rows).encode('ascii')).digest()
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        # Paging is still bounded when an unexpected response cannot be fingerprinted.
        return None


def _local_language(value):
    """Identify Czech/Slovak codes without matching unrelated languages."""
    if not isinstance(value, str):
        return None
    language = value.strip().casefold().replace('_', '-').split('-', 1)[0]
    if language in ('cz', 'cs', 'cze', 'ces', 'czech', 'cesky', 'česky', 'čeština'):
        return 'cz'
    if language in ('sk', 'slo', 'slk', 'slovak', 'slovensky', 'slovenský', 'slovenčina', 'slovencina'):
        return 'sk'
    return None


def _stream_height(value):
    """Recognize unambiguous list-form quality labels."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 100 <= value <= 9999 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and 100 <= value <= 9999 else None
    if not isinstance(value, str):
        return None
    label = value.strip().lower()
    if label in ('4k', '8k'):
        return {'4k': 2160, '8k': 4320}[label]
    match = re.fullmatch(r'(\d{3,4})p?', label)
    return int(match.group(1)) if match and int(match.group(1)) >= 100 else None


def _alternate_stream_name(index, prefix):
    """Keep unknown alternatives selectable without implying a resolution."""
    label = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(ord('A') + remainder) + label
    return f'{prefix} {label}'


def _write_subtitle_atomically(path, content):
    """Publish a complete file without truncating the subtitle used by Kodi."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=os.path.dirname(path),
                                         prefix='.play_er_sub_', suffix='.tmp', delete=False) as output:
            temporary = output.name
            if output.write(content) != len(content):
                raise OSError('Incomplete subtitle write')
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                log('PREHRAJTO - Nelze odstranit dočasný soubor titulků.', xbmc.LOGWARNING)


class PrehrajTo(BaseProvider):

    """
    CLASS :: PREHRAJ.TO
    -- Třída providera Prehraj.to pro REST API v2.
    """

    search_handles_auth = True

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
        self._auth_credentials = None
        loaded_cookies = getattr(session, '_play_er_prehraj_loaded_cookies', None)
        self._loaded_cookies = loaded_cookies if isinstance(loaded_cookies, dict) else {}
        session._play_er_prehraj_loaded_cookies = self._loaded_cookies
        self._auth_lock = threading.RLock()

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

    def _credentials(self):
        return (get_setting_str(self.addon, 'email', '') or self._fallback_email,
                get_setting_str(self.addon, 'password', '') or self._fallback_password)

    def _binding_file(self):
        return xbmcvfs.translatePath("special://profile/addon_data/plugin.video.play_er/PREHRAJTO_AUTH_BINDING.JSON")

    def _binding_for(self, token, credentials):
        identity = json.dumps(credentials, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return {'token_hash': hashlib.sha256(token.encode('utf-8')).hexdigest(),
                'credentials': hmac.new(token.encode('utf-8'), identity, hashlib.sha256).hexdigest()}

    def _save_binding(self, token, credentials):
        binding = self._binding_for(token, credentials)
        try:
            with SafeVFSFile(self._binding_file(), 'w') as handle:
                if handle.write(json.dumps(binding)) is False:
                    raise OSError('binding write failed')
        except Exception as exc:
            log(f'PREHRAJTO :: Nelze uložit vazbu účtu: {type(exc).__name__}', xbmc.LOGWARNING)

    def _accept_binding(self, token, credentials):
        current = self._binding_for(token, credentials)
        try:
            path = self._binding_file()
            if not xbmcvfs.exists(path):
                # Existing installations can continue using their saved token.
                self._save_binding(token, credentials)
                return True
            with SafeVFSFile(path, 'r') as handle:
                previous = json.loads(handle.read() or '{}')
            if not isinstance(previous, dict) or not all(isinstance(previous.get(k), str) for k in ('token_hash', 'credentials')):
                return False
            valid = (hmac.compare_digest(previous['token_hash'], current['token_hash']) and
                     hmac.compare_digest(previous['credentials'], current['credentials']))
            return valid
        except Exception as exc:
            log(f'PREHRAJTO :: Nelze ověřit vazbu účtu: {type(exc).__name__}', xbmc.LOGWARNING)
            return False

    def _clear_account_cookies(self):
        jar = self.session.cookies
        for name, (loaded, previous) in self._loaded_cookies.items():
            if jar.get(name, domain='', path='/') == loaded:
                jar.clear('', '/', name)
                if previous is not None:
                    jar.set(name, previous)
        self._loaded_cookies.clear()
        for cookie in list(jar):
            domain = cookie.domain.lstrip('.').lower()
            if domain in ('prehraj.to', 'prehrajto.cz') or domain.endswith(('.prehraj.to', '.prehrajto.cz')):
                jar.clear(cookie.domain, cookie.path, cookie.name)

    def _sync_credentials(self):
        with self._auth_lock:
            credentials = self._credentials()
            if self._auth_credentials is not None and self._auth_credentials != credentials:
                self._set_tokens(None, None)
                self._clear_account_cookies()
                self._auth_loaded = True
                win = xbmcgui.Window(10000)
                for prop in ('player.prehrajto.premium.notified', 'player.prehrajto.premium.expiry_notified', 'player.prehrajto.premium_days'):
                    win.clearProperty(prop)
                self._auth_credentials = credentials
                return True
            self._auth_credentials = credentials
            return False

    def _set_tokens(self, access, refresh):
        self._access_token = access
        self._refresh_token = refresh
        if access:
            self.headers['Authorization'] = f'Bearer {access}'
        else:
            self.headers.pop('Authorization', None)

    def _load_auth_state(self):
        self._sync_credentials()
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
                if (access or refresh) and not self._accept_binding(access or refresh, self._auth_credentials):
                    self._clear_account_cookies()
                    return
                if path == canonical:
                    cookies = {k: v for k, v in state.items() if k not in ('token', 'tokens', 'access', 'refresh', 'access_token', 'refresh_token')}
                    if cookies:
                        for name, value in cookies.items():
                            prior = self.session.cookies.get(name, domain='', path='/')
                            old = self._loaded_cookies.get(name)
                            self._loaded_cookies[name] = (value, old[1] if old and old[0] == prior else prior)
                        self.session.cookies.update(cookies)
                if access or refresh:
                    self._set_tokens(access, refresh)
                    if path == legacy:
                        self._save_auth_state()
                    return
            except Exception as exc:
                log(f'PREHRAJTO :: Nelze načíst uložené přihlášení ({os.path.basename(path)}): {type(exc).__name__}', xbmc.LOGWARNING)

    def _save_auth_state(self):
        if self._auth_credentials != self._credentials():
            self._sync_credentials()
            return False
        if not self._access_token:
            return False
        try:
            state = dict(self.session.cookies.get_dict())
            state['token'] = {'access': self._access_token, 'refresh': self._refresh_token}
            with SafeVFSFile(self._auth_file(), 'w') as f:
                if f.write(json.dumps(state)) is False:
                    raise OSError('auth write failed')
            self._save_binding(self._access_token, self._auth_credentials)
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
        for filename in ('PREHRAJTO_COOKIES.JSON', 'PREHRAJTO_TOKENS.JSON', 'PREHRAJTO_AUTH_BINDING.JSON'):
            path = xbmcvfs.translatePath(f"special://profile/addon_data/plugin.video.play_er/{filename}")
            if xbmcvfs.exists(path):
                xbmcvfs.delete(path)
        self._set_tokens(None, None)
        self._clear_account_cookies()
        self._auth_credentials = self._credentials()
        self._auth_loaded = True
        win = xbmcgui.Window(10000)
        win.clearProperty("player.prehrajto.premium.notified")
        win.clearProperty("player.prehrajto.premium.expiry_notified")
        win.clearProperty("player.prehrajto.premium_days")

    def _auto_register_new_account(self):
        credentials = self._credentials()
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
                if self._credentials() != credentials:
                    self._sync_credentials()
                    log('AUTO-REGISTER :: Účet se během registrace změnil; nové údaje nebudou použity.', xbmc.LOGWARNING)
                    return False
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
        with self._auth_lock:
            return self._get_premium_cookies(force)

    def _get_premium_cookies(self, force=False):
        self._load_auth_state()

        def _check_and_auto_register():
            auto_register = get_setting_bool(self.addon, 'enable_auto_register', True)
            if not auto_register and not get_setting_bool(self.addon, 'notify_premium_expiry', False):
                return False
            credentials = self._credentials()
            days_left = self._fetch_and_set_premium_days()
            if self._credentials() != credentials:
                self._sync_credentials()
                return None
            if auto_register and days_left is not None and days_left <= 2:
                log(f"PREMIUM :: ZBÝVÁ {days_left} DNÍ -> SPOUŠTÍM AUTO-REGISTRACI", xbmc.LOGINFO)
                if self._auto_register_new_account():
                    return True
                if self._credentials() != credentials:
                    self._sync_credentials()
                    return None
            return False

        if not force and self._access_token:
            if self._token_needs_refresh():
                if not self._refresh_access_token():
                    log('PREHRAJTO :: Obnova tokenu selhala, opakuji přihlášení', xbmc.LOGWARNING)
                    force = True
            if not force:
                renewal = _check_and_auto_register()
                if renewal is None:
                    return None
                if renewal:
                    force = True
            if not force:
                if self._sync_credentials():
                    return None
                return self.session.cookies
        elif not force and self._refresh_token:
            if self._refresh_access_token():
                renewal = _check_and_auto_register()
                if renewal is None:
                    return None
                if not renewal:
                    if self._sync_credentials():
                        return None
                    return self.session.cookies

        email, password = self._credentials()

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
                    if self._credentials() != (email, password):
                        self._sync_credentials()
                        return None
                    self._set_tokens(access, refresh)

                    notify_acc(f'PREHRAJ.TO PŘIHLÁŠEN : {email}', category='PROVIDER')
                    self._fetch_and_set_premium_days(force_notify=True)

                    if self._credentials() != (email, password):
                        self._sync_credentials()
                        return None

                    self._save_auth_state()

                    if self._sync_credentials():
                        return None

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
        with self._auth_lock:
            return self._refresh_access_token_locked()

    def _refresh_access_token_locked(self):
        if self._sync_credentials():
            return False
        if not self._refresh_token:
            return False
        credentials = self._credentials()
        old_refresh = self._refresh_token
        refresh_api = f"{self.api_base}/users/refresh-token"
        payload = {'refreshToken': self._refresh_token}
        try:
            res = self.session.post(refresh_api, json=payload, headers={'Content-Type': 'application/json', 'User-Agent': self.headers.get('user-agent'), 'Authorization': None}, timeout=10)
            if getattr(res, 'status_code', None) == 200:
                access, refresh = self._extract_tokens_from_response(res.json())
                if access:
                    if self._credentials() != credentials or self._refresh_token != old_refresh:
                        self._sync_credentials()
                        return False
                    self._set_tokens(access, refresh or self._refresh_token)
                    self._save_auth_state()
                    return bool(self._access_token)
            log(f'PREHRAJTO :: Obnova tokenu odmítnuta, HTTP {getattr(res, "status_code", "?")}', xbmc.LOGWARNING)
        except Exception as e:
            log(f'PREHRAJTO :: REFRESH ERROR : {e}', xbmc.LOGWARNING)
        return False

    def _api_get(self, path, params=None, require_auth=False):
        credentials = None
        if require_auth and hasattr(self, '_auth_credentials'):
            with self._auth_lock:
                if self._sync_credentials():
                    return None
                credentials = self._auth_credentials

        def same_account():
            if credentials is None:
                return True
            with self._auth_lock:
                if self._credentials() != credentials or self._auth_credentials != credentials:
                    self._sync_credentials()
                    return False
                return True

        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {'User-Agent': self.headers.get('user-agent')}
        if require_auth and self._access_token:
            headers['Authorization'] = f'Bearer {self._access_token}'
        try:
            res = self.session.get(url, params=params, headers=headers, timeout=10)
            if not same_account():
                return None
            if require_auth and getattr(res, 'status_code', None) == 401:
                renewed = self._refresh_access_token() if self._refresh_token else False
                if not same_account():
                    return None
                if not renewed and path.strip('/') != 'profile':
                    self.get_premium_cookies(force=True)
                    if not same_account():
                        return None
                    renewed = bool(self._access_token)
                if renewed and self._access_token:
                    headers['Authorization'] = f'Bearer {self._access_token}'
                    res = self.session.get(url, params=params, headers=headers, timeout=10)
                    if not same_account():
                        return None
            return res
        except Exception as e:
            log(f'PREHRAJTO - API GET ERROR {url} : {e}', xbmc.LOGWARNING)
        return None

    def _api_post(self, path, json_payload=None, require_auth=False, expected_credentials=None, expected_token=None):
        if expected_credentials is not None:
            with self._auth_lock:
                if self._credentials() != expected_credentials or self._auth_credentials != expected_credentials:
                    self._sync_credentials()
                    return None
            token = expected_token
        else:
            if require_auth and hasattr(self, '_auth_credentials') and self._sync_credentials():
                return None
            token = self._access_token
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {'User-Agent': self.headers.get('user-agent'), 'Content-Type': 'application/json'}
        if require_auth and token:
            headers['Authorization'] = f'Bearer {token}'

        def retry_token():
            if expected_credentials is not None and (self._credentials() != expected_credentials or self._auth_credentials != expected_credentials):
                self._sync_credentials()
                return None
            if expected_credentials is not None and self._access_token and self._access_token != expected_token:
                return self._access_token
            renewed = self._refresh_access_token() if self._refresh_token else False
            if not renewed:
                if expected_credentials is not None and (self._credentials() != expected_credentials or self._auth_credentials != expected_credentials):
                    self._sync_credentials()
                    return None
                self.get_premium_cookies(force=True)
                renewed = bool(self._access_token)
            if expected_credentials is not None and (self._credentials() != expected_credentials or self._auth_credentials != expected_credentials):
                self._sync_credentials()
                return None
            return self._access_token if renewed else None

        try:
            res = self.session.post(url, json=json_payload, headers=headers, timeout=10)
            if require_auth and getattr(res, 'status_code', None) == 401:
                if expected_credentials is None:
                    renewed_token = retry_token()
                else:
                    with self._auth_lock:
                        renewed_token = retry_token()
                if renewed_token:
                    headers['Authorization'] = f'Bearer {renewed_token}'
                    res = self.session.post(url, json=json_payload, headers=headers, timeout=10)
            return res
        except Exception as e:
            log(f'PREHRAJTO - API POST ERROR {url} : {e}', xbmc.LOGWARNING)
        return None

    @staticmethod
    def _video_id(video_id):
        value = str(video_id)
        match = re.search(r'([0-9]{5,12})', value)
        value = match.group(1) if match else value
        return value if value and value.isdigit() else ''

    def view_tracking_identity(self, video_id, stream_url):
        """Bind a pending view to this account, source and resolved stream."""
        from resources.lib.playback_identity import stream_key
        with self._auth_lock:
            video_id = self._video_id(video_id)
            url_key = stream_key(stream_url)
            credentials = self._credentials()
            if not video_id or not url_key or not self._access_token or self._auth_credentials != credentials:
                return None
            message = json.dumps([credentials, video_id, url_key], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            binding = hmac.new(self._access_token.encode('utf-8'), message, hashlib.sha256).hexdigest()
            return video_id, binding

    def api_track_view(self, video_id, stream_url=None, binding=None):
        try:
            if binding is None:
                return self._api_post(f'videos/{video_id}/add-view', require_auth=True)
            with self._auth_lock:
                self._load_auth_state()
                current = self.view_tracking_identity(video_id, stream_url)
                if not current or not isinstance(binding, str) or not hmac.compare_digest(current[1], binding):
                    return False
                credentials, token = self._auth_credentials, self._access_token
            response = self._api_post(f'videos/{current[0]}/add-view', require_auth=True,
                                      expected_credentials=credentials, expected_token=token)
            status = getattr(response, 'status_code', None)
            if not isinstance(status, int) or not 200 <= status < 300:
                log(f'PREHRAJTO :: Záznam zhlédnutí selhal, HTTP {status or "bez odpovědi"}', xbmc.LOGWARNING)
            return True
        except Exception:
            return False

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
            orig_link = next((value.strip() for key in ('download_link', 'link', 'url')
                              if isinstance((value := data.get(key)), str) and value.strip()), None)
            if orig_link and detail and detail.get('extension'):
                ext = str(detail.get('extension')).upper()

        transcodes = {}
        if detail:
            links_obj = detail.get('links') or {}
            if isinstance(links_obj, dict):
                for k, v in links_obj.items():
                    if isinstance(v, str) and v.strip():
                        v = v.strip()
                        try:
                            transcodes[int(k)] = v
                        except Exception:
                            transcodes[k] = v
            elif isinstance(links_obj, list) and links_obj:
                seen_urls = {}
                alternate_index = 0
                alternate_label = None
                for item in links_obj:
                    if isinstance(item, dict):
                        url = next((value.strip() for key in ('url', 'link')
                                    if isinstance((value := item.get(key)), str) and value.strip()), None)
                        height = next((height for key in ('height', 'resolution', 'quality')
                                       if (height := _stream_height(item.get(key))) is not None), None)
                    else:
                        url = item.strip() if isinstance(item, str) else None
                        height = None
                    if not url:
                        continue
                    if url in seen_urls:
                        previous = seen_urls[url]
                        if ((previous == 0 or isinstance(previous, str))
                                and height is not None and height not in transcodes):
                            del transcodes[previous]
                            transcodes[height] = url
                            seen_urls[url] = height
                        continue
                    if height is not None and height not in transcodes:
                        key = height
                    elif height is None and 0 not in transcodes:
                        key = 0
                    else:
                        if alternate_label is None:
                            try:
                                alternate_label = self.addon.getLocalizedString(32918)
                            except Exception:
                                alternate_label = ''
                            if not isinstance(alternate_label, str) or not alternate_label.strip():
                                alternate_label = 'ALTERNATIVE'
                            else:
                                alternate_label = alternate_label.strip()
                        alternate_index += 1
                        key = _alternate_stream_name(alternate_index, alternate_label)
                    transcodes[key] = url
                    seen_urls[url] = key

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
        credentials = getattr(self, '_auth_credentials', None)

        def same_account():
            if credentials is None:
                return True
            with self._auth_lock:
                if self._credentials() != credentials or self._auth_credentials != credentials:
                    self._sync_credentials()
                    return False
                return True

        vid = self._video_id(video_id)

        if not vid:
            log("PREHRAJTO - Neplatné ID videa pro získání streamu!", xbmc.LOGERROR)
            notify_error('PREHRAJ.TO CHYBNÉ ID STREAMU', category='PROVIDER')
            return None, []

        # A failed lookup is also reused for this resolution; no persistent cache.
        detail = self.api_get_video_detail(vid)
        if not same_account():
            return None, []
        available_links = self.api_get_download_link(vid, detail=detail)
        if not same_account():
            return None, []

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

                language = _local_language(s.get('language'))
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
                        _write_subtitle_atomically(local_file, resp.content)

                    if os.path.exists(local_file):
                        if language:
                            cz_sk_subs.append(local_file)
                        else:
                            other_subs.append(local_file)
                except Exception as e:
                    log(f"PREHRAJTO - Chyba stahování titulků: {e}", xbmc.LOGWARNING)
                    continue

            sub_urls = cz_sk_subs + other_subs

        def publish_stream_assets():
            if not same_account():
                return False
            window = xbmcgui.Window(10000)
            if available_links:
                window.setProperty(f"play_er.qualities.{vid}", json.dumps(available_links))
            else:
                window.clearProperty(f"play_er.qualities.{vid}")
            window.setProperty(f"play_er.subtitles.{vid}", json.dumps(sub_urls))
            return True

        if not available_links:
            if not publish_stream_assets():
                return None, []
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
                if not same_account():
                    return None, []
                if choice == -1:
                    publish_stream_assets()
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
                    quality = stream_quality(k)
                    if quality is not None:
                        q_dict[quality] = v

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

        if not publish_stream_assets():
            return None, []
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
        long_videos_only = get_setting_bool(self.addon, 'prehrajto_long_videos', False)

        api_sort_idx = get_setting_int_with_bounds(self.addon, 'prehrajto_api_sort', 0, 0, 2)
        api_quality_idx = get_setting_int_with_bounds(self.addon, 'prehrajto_api_quality', 0, 0, 9)

        sort_map = {0: "relevance", 1: "popularity", 2: "relevance"}
        quality_map = {0: "", 1: "4k", 2: "1080p", 3: "720p", 4: "1440p",
                       5: "480p", 6: "360p", 7: "240p", 8: "8k", 9: "8k_more"}

        api_sort = sort_map.get(api_sort_idx, "relevance")
        api_quality = quality_map.get(api_quality_idx, "")

        smart_query = re.sub(r'[:\-]', ' ', query)
        smart_query = re.sub(r'\s+', ' ', smart_query).strip()

        # Short episodes must remain available even when the duration filter is enabled.
        is_episode_query = bool(re.search(r'\bs\d+e\d+\b|\b\d+x\d+\b', smart_query, re.IGNORECASE))
        filter_duration = long_videos_only and not is_episode_query

        all_videos = []
        seen_links = set()
        seen_pages = set()
        complete = True
        for p in range(1, search_pages + 1):
            limit = 32
            offset = (p - 1) * limit

            params = {
                'phrase': smart_query,
                'limit': limit,
                'offset': offset
            }

            if filter_duration:
                params['longer-than-20min'] = 'true'
            # Explicit server preferences are separate from local expression
            # filters. Preserve the historical default request when unset.
            if is_filtering_enabled or api_sort_idx:
                params['sort'] = api_sort
            if api_quality:
                params['quality'] = api_quality

            api_resp = self._api_get('videos/search', params=params, require_auth=bool(self._access_token))

            items = self._search_response_items(api_resp, 'videos/search')
            if items is None:
                complete = False
                break
            used_suggest = False
            if not items:
                if p != 1 or filter_duration or api_quality:
                    break
                log(f"PREHRAJTO - Běžné hledání '{smart_query}' vrátilo 0 výsledků. Zkouším suggest fallback.", xbmc.LOGINFO)
                api_resp = self._api_get('videos/suggest', params={'phrase': smart_query}, require_auth=bool(self._access_token))
                items = self._search_response_items(api_resp, 'videos/suggest')
                used_suggest = True
                if items is None:
                    complete = False
                if not items:
                    break

            if not used_suggest and len(items) >= limit:
                fingerprint = _page_fingerprint(items)
                if fingerprint is not None:
                    if fingerprint in seen_pages:
                        break
                    seen_pages.add(fingerprint)
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

                    has_cz_sk_subs_api = False
                    has_cz_audio_api = False
                    has_sk_audio_api = False

                    subs = it.get('subtitles', [])
                    if subs and isinstance(subs, list):
                        for s in subs:
                            lang = _local_language(s.get('language') if isinstance(s, dict) else s)
                            if lang:
                                api_tags.add('TIT')
                                has_cz_sk_subs_api = True
                                break

                    audio_tracks = it.get('audio') or it.get('audios') or it.get('languages') or []
                    if isinstance(audio_tracks, list):
                        for a in audio_tracks:
                            lang = _local_language(a.get('language') if isinstance(a, dict) else a)
                            if lang == 'cz':
                                api_tags.add('DAB')
                                has_cz_audio_api = True
                            elif lang == 'sk':
                                api_tags.add('SK')
                                has_sk_audio_api = True
                            if has_cz_audio_api and has_sk_audio_api:
                                break

                    has_cz_word = re.search(r'\b(cz|sk)\b', tl)
                    is_explicit_dub = re.search(r'\b(dabing|dab|czdab|czdabing|skdab|skdabing)\b', tl)
                    has_sub_keywords = re.search(r'\b(titulky|tit|cztit|cztitulky|sub|subs)\b', tl)

                    if has_sub_keywords and not has_cz_sk_subs_api:
                        api_tags.add('TIT')

                    if not has_cz_audio_api and not has_sk_audio_api:
                        if is_explicit_dub:
                            api_tags.add('DAB')
                        elif has_cz_word:
                            if has_cz_sk_subs_api or has_sub_keywords:
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

                if len(all_videos) >= search_ls or used_suggest or len(items) < limit:
                    break
            else:
                break

        return SearchResults(self.normalize_and_filter(all_videos, apply_filters=apply_filters), complete)

    def _get_video_pages(self, endpoint, require_auth=False, extra_params=None):
        """Fetch a bounded list; stop if a server ignores pagination."""
        max_pages = get_setting_int_with_bounds(self.addon, 'max_pages', default=5, min_val=1, max_val=10)
        videos, seen, seen_pages = [], set(), set()
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
            if len(items) >= 32:
                fingerprint = _page_fingerprint(items)
                if fingerprint is not None:
                    if fingerprint in seen_pages:
                        break
                    seen_pages.add(fingerprint)
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = item.get('id') or item.get('videoPage') or item.get('pageUrl') or item.get('link') or item.get('url')
                if key is None or str(key) in seen:
                    continue
                seen.add(str(key))
                videos.append(item)
            if len(items) < 32:
                break
        return videos

    def _catalog_video(self, item, mark_multi, include_series=False):
        """Normalize one history/ranking item without discarding later results."""
        if not isinstance(item, dict):
            return None
        title = next((value for value in (item.get('title'), item.get('name'))
                      if isinstance(value, str) and value.strip()), 'Neznámý titul')
        title = self._apply_multi_indicator(item, title, mark_multi)
        link = next((value.strip() for key in ('videoPage', 'pageUrl', 'link', 'url')
                     if isinstance((value := item.get(key)), str) and value.strip()), None)
        ident = item.get('id')
        if not link and isinstance(ident, (str, int)) and not isinstance(ident, bool) and str(ident).strip() and ident != 0:
            link = urljoin(self.base_url, f"/videos/{str(ident).strip()}")
        if not link:
            return None
        size = item.get('size')
        size_str = ''
        if size is not None:
            try:
                size_str = convert_size(int(size))
            except (TypeError, ValueError, OverflowError):
                size_str = str(size)
        thumbs = item.get('thumbs')
        thumbs = thumbs.get('global') if isinstance(thumbs, dict) else None
        try:
            likes = int(thumbs.get('up', 0)) if isinstance(thumbs, dict) else 0
        except (TypeError, ValueError, OverflowError):
            likes = 0
        video = {
            'title': title, 'link': link, 'size_str': size_str,
            'duration_str': str(item.get('duration') or item.get('length') or ''),
            'id': ident, 'provider': 'prehraj.to', 'provider_color': Colors.ORANGE,
            'likes': likes,
        }
        if include_series:
            video['is_series'] = item.get('type') == 'series' or 'S0' in title.upper() or 'E0' in title.upper()
        return video

    def get_most_watched(self):
        use_cache = get_setting_bool(self.addon, "enable_most_watched_cache", True)
        max_pages = get_setting_int_with_bounds(self.addon, 'max_pages', default=5, min_val=1, max_val=10)
        mark_multi = get_setting_bool(self.addon, 'prehrajto_mark_multi_streams', True)
        cache_key = f"prehrajto_most_watched_v2_pages_{max_pages}_multi_{int(mark_multi)}"
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
                video = self._catalog_video(it, mark_multi, include_series=True)
                if video:
                    videos.append(video)
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
                    video = self._catalog_video(it, mark_multi)
                    if video:
                        videos.append(video)
                return videos
        except Exception:
            pass

        notify_info('PREHRAJ.TO HISTORIE NENÍ DOSTUPNÁ', category='PROVIDER')
        return []
