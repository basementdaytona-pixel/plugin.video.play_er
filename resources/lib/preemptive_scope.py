"""Identify the provider configuration used for a preemptive search."""
import hashlib
import hmac
import json


def source_scope(addon, provider_manager):
    multi = addon.getSettingBool('enable_multi_provider')
    active = getattr(provider_manager, '_active_provider_name', None)
    if not isinstance(active, str) or not active:
        active = addon.getSetting('active_provider') or 'prehraj.to'
    active = active.lower()
    if active not in ('prehraj.to', 'webshare.cz'):
        active = 'prehraj.to'
    providers = ('prehraj.to', 'webshare.cz') if multi else (active,)
    settings = {'providers': providers, 'enable_filtering': addon.getSetting('enable_filtering')}
    if 'prehraj.to' in providers:
        for key in ('email', 'search_pages', 'search_ls', 'prehrajto_api_sort',
                    'prehrajto_api_quality', 'prehrajto_mark_multi_streams',
                    'prehrajto_long_videos'):
            settings[key] = addon.getSetting(key)
    if 'webshare.cz' in providers:
        for key in ('webshare_username', 'webshare_search_limit', 'webshare_category', 'webshare_sort'):
            settings[key] = addon.getSetting(key)
        token = addon.getSetting('webshare_token')
        if token:
            password = addon.getSetting('webshare_password') or ''
            settings['webshare_auth'] = hmac.new(token.encode('utf-8'), password.encode('utf-8'), hashlib.sha256).hexdigest()
    encoded = json.dumps(settings, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()
