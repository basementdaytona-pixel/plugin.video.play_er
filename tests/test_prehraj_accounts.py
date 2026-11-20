"""Prehraj.to authentication ownership with isolated synthetic accounts."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
import test_provider_responses as support

prehraj = support.prehraj


class PrehrajAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = {'email': 'first@example.invalid', 'password': 'first-pass',
                         'enable_auto_register': 'false', 'notify_premium_expiry': 'false'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.setSetting.side_effect = lambda key, value: self.settings.__setitem__(key, value)
        self.vfs = MagicMock()
        self.vfs.translatePath.side_effect = lambda path: str(self.root / Path(path).name)
        self.vfs.exists.side_effect = lambda path: Path(path).exists()
        self.vfs.delete.side_effect = lambda path: Path(path).unlink()
        for p in (patch.object(prehraj, 'xbmcvfs', self.vfs),
                  patch.object(prehraj, 'SafeVFSFile', side_effect=lambda path, mode: open(path, mode, encoding='utf-8')),
                  patch.object(prehraj.PrehrajTo, '_fetch_and_set_premium_days', return_value=30)):
            p.start()
            self.addCleanup(p.stop)
        self.write_auth()

    def write_auth(self, filename='PREHRAJTO_COOKIES.JSON', **state):
        if not state:
            state = {'token': {'access': 'first-token', 'refresh': 'first-refresh'}, 'account_cookie': 'first-cookie'}
        (self.root / filename).write_text(json.dumps(state), encoding='utf-8')

    def provider(self, session=None):
        if session is None:
            session = MagicMock()
            session.cookies = requests.cookies.RequestsCookieJar()
            session.post.return_value = SimpleNamespace(status_code=200, json=lambda: {'data': {'access': 'second-token', 'refresh': 'second-refresh'}})
        return prehraj.PrehrajTo(self.addon, 1, session, None)

    def test_legacy_token_and_cookies_are_kept_without_login(self):
        client = self.provider()
        self.assertIs(client.get_premium_cookies(), client.session.cookies)
        self.assertEqual(client._access_token, 'first-token')
        self.assertEqual(client.session.cookies.get('account_cookie'), 'first-cookie')
        client.session.post.assert_not_called()

    def test_different_account_after_recreation_requires_new_login(self):
        self.provider().get_premium_cookies()
        self.settings.update(email='second@example.invalid', password='second-pass')
        client = self.provider()
        client.get_premium_cookies()
        self.assertEqual(client._access_token, 'second-token')
        self.assertEqual(client.session.post.call_args.kwargs['json'],
                         {'email': 'second@example.invalid', 'password': 'second-pass'})
        self.assertIsNone(client.session.cookies.get('account_cookie'))

    def test_password_change_on_existing_client_requires_login_and_preserves_other_cookies(self):
        client = self.provider()
        client.session.cookies.set('other', 'keep', domain='other.invalid', path='/')
        client.get_premium_cookies()
        self.settings['password'] = 'changed-pass'
        client.get_premium_cookies()
        self.assertEqual(client._access_token, 'second-token')
        self.assertEqual(client.session.cookies.get('other', domain='other.invalid'), 'keep')
        self.assertIsNone(client.session.cookies.get('account_cookie'))
        self.assertEqual(client.session.post.call_args.kwargs['json']['password'], 'changed-pass')

    def test_recreated_client_clears_old_cookies_from_shared_session(self):
        first = self.provider()
        first.session.cookies.set('other', 'keep', domain='other.invalid', path='/')
        first.session.cookies.set('account_cookie', 'original')
        first.get_premium_cookies()
        self.provider(first.session).get_premium_cookies()
        self.settings.update(email='second@example.invalid', password='second-pass')
        second = self.provider(first.session)
        second.get_premium_cookies()
        self.assertEqual(second._access_token, 'second-token')
        self.assertEqual(second.session.cookies.get('account_cookie'), 'original')
        self.assertEqual(second.session.cookies.get('other', domain='other.invalid'), 'keep')

    def test_failed_login_never_returns_previous_account_token(self):
        self.provider().get_premium_cookies()
        self.settings['email'] = 'second@example.invalid'
        client = self.provider()
        client.session.post.return_value = SimpleNamespace(status_code=401)
        self.assertIsNone(client.get_premium_cookies())
        self.assertIsNone(client._access_token)

    def test_legacy_token_file_migrates_and_remains_usable(self):
        (self.root / 'PREHRAJTO_COOKIES.JSON').unlink()
        self.write_auth('PREHRAJTO_TOKENS.JSON', access='first-token', refresh='first-refresh')
        client = self.provider()
        client.get_premium_cookies()
        self.assertEqual(client._access_token, 'first-token')
        self.assertTrue((self.root / 'PREHRAJTO_COOKIES.JSON').exists())
        self.assertFalse((self.root / 'PREHRAJTO_TOKENS.JSON').exists())
        client.session.post.assert_not_called()

    def test_credentials_changed_during_login_do_not_save_stale_token(self):
        (self.root / 'PREHRAJTO_COOKIES.JSON').unlink()
        client = self.provider()
        def reply(*args, **kwargs):
            self.settings['email'] = 'second@example.invalid'
            return SimpleNamespace(status_code=200, json=lambda: {'data': {'access': 'stale-token'}})
        client.session.post.side_effect = reply
        self.assertIsNone(client.get_premium_cookies())
        self.assertIsNone(client._access_token)
        self.assertFalse((self.root / 'PREHRAJTO_COOKIES.JSON').exists())

    def test_refresh_saves_new_token_for_same_account(self):
        client = self.provider()
        client.get_premium_cookies()
        self.assertTrue(client._refresh_access_token())
        recreated = self.provider()
        recreated.get_premium_cookies()
        self.assertEqual(recreated._access_token, 'second-token')
        recreated.session.post.assert_not_called()

    def test_refresh_rejects_response_after_credentials_change(self):
        client = self.provider()
        client.get_premium_cookies()
        def reply(*args, **kwargs):
            self.settings['password'] = 'changed-pass'
            return SimpleNamespace(status_code=200, json=lambda: {'data': {'access': 'stale-token'}})
        client.session.post.side_effect = reply
        self.assertFalse(client._refresh_access_token())
        self.assertIsNone(client._access_token)
        self.assertEqual(json.loads((self.root / 'PREHRAJTO_COOKIES.JSON').read_text())['token']['access'], 'first-token')

    def test_corrupt_binding_requires_fresh_login(self):
        self.provider().get_premium_cookies()
        (self.root / 'PREHRAJTO_AUTH_BINDING.JSON').write_text('{bad')
        client = self.provider()
        client.get_premium_cookies()
        self.assertEqual(client._access_token, 'second-token')
        client.session.post.assert_called_once()

    def test_binding_has_no_raw_credentials_or_token(self):
        self.provider().get_premium_cookies()
        binding = (self.root / 'PREHRAJTO_AUTH_BINDING.JSON').read_text()
        for value in ('first@example.invalid', 'first-pass', 'first-token'):
            self.assertNotIn(value, binding)

    def test_unwritable_binding_still_tracks_changes_in_current_instance(self):
        original_open = prehraj.SafeVFSFile.side_effect
        def open_with_unwritable_binding(path, mode):
            if path.endswith('PREHRAJTO_AUTH_BINDING.JSON'):
                raise OSError('synthetic failure')
            return original_open(path, mode)
        with patch.object(prehraj, 'SafeVFSFile', side_effect=open_with_unwritable_binding):
            client = self.provider()
            client.get_premium_cookies()
            self.settings['password'] = 'changed-pass'
            client.get_premium_cookies()
            self.assertEqual(client._access_token, 'second-token')

    def test_fallback_credentials_keep_existing_token(self):
        self.settings.update(email='', password='')
        client = self.provider()
        client.get_premium_cookies()
        recreated = self.provider()
        recreated.get_premium_cookies()
        self.assertEqual(recreated._access_token, 'first-token')
        recreated.session.post.assert_not_called()

    def test_credential_change_during_premium_check_discards_old_token(self):
        self.settings['notify_premium_expiry'] = 'true'
        client = self.provider()
        def premium(*args, **kwargs):
            self.settings['password'] = 'changed-pass'
            return 30
        with patch.object(client, '_fetch_and_set_premium_days', side_effect=premium):
            self.assertIsNone(client.get_premium_cookies())
        self.assertIsNone(client._access_token)

    def test_expired_old_account_does_not_register_after_account_change(self):
        self.settings['enable_auto_register'] = 'true'
        client = self.provider()
        def premium(*args, **kwargs):
            self.settings.update(email='second@example.invalid', password='second-pass')
            return 1
        with patch.object(client, '_fetch_and_set_premium_days', side_effect=premium), \
             patch.object(client, '_auto_register_new_account') as register:
            self.assertIsNone(client.get_premium_cookies())
        register.assert_not_called()
        self.assertIsNone(client._access_token)

    def test_registration_does_not_replace_manually_changed_account(self):
        client = self.provider()
        client.get_premium_cookies()
        def registration():
            self.settings.update(email='manual@example.invalid', password='manual-pass')
            return 'generated@example.invalid', 'generated-pass'
        with patch.object(prehraj, 'PlayMail') as mail:
            mail.return_value.register_account.side_effect = registration
            self.assertFalse(client._auto_register_new_account())
        self.assertEqual(self.settings['email'], 'manual@example.invalid')
        self.assertEqual(self.settings['password'], 'manual-pass')
        self.assertIsNone(client._access_token)

    def test_changed_account_during_registration_aborts_current_login(self):
        self.settings['enable_auto_register'] = 'true'
        client = self.provider()
        def registration():
            self.settings.update(email='manual@example.invalid', password='manual-pass')
            return 'generated@example.invalid', 'generated-pass'
        with patch.object(client, '_fetch_and_set_premium_days', return_value=1), \
             patch.object(prehraj, 'PlayMail') as mail:
            mail.return_value.register_account.side_effect = registration
            self.assertIsNone(client.get_premium_cookies())
        self.assertEqual(self.settings['email'], 'manual@example.invalid')
        self.assertIsNone(client._access_token)
        client.session.post.assert_not_called()

    def test_failed_registration_keeps_current_account(self):
        self.settings['enable_auto_register'] = 'true'
        client = self.provider()
        with patch.object(client, '_fetch_and_set_premium_days', return_value=1), \
             patch.object(prehraj, 'PlayMail') as mail:
            mail.return_value.register_account.return_value = (None, None)
            self.assertIs(client.get_premium_cookies(), client.session.cookies)
        self.assertEqual(self.settings['email'], 'first@example.invalid')
        self.assertEqual(client._access_token, 'first-token')
        client.session.post.assert_not_called()

    def test_automatic_account_replacement_preserves_other_provider_cookies(self):
        client = self.provider()
        client.session.cookies.set('other', 'keep', domain='other.invalid', path='/')
        client.session.cookies.set('provider', 'remove', domain='prehrajto.cz', path='/')
        client.get_premium_cookies()
        client.replace_account_credentials('new@example.invalid', 'new-pass')
        self.assertEqual(client.session.cookies.get('other', domain='other.invalid'), 'keep')
        self.assertIsNone(client.session.cookies.get('provider', domain='prehrajto.cz'))
        self.assertIsNone(client.session.cookies.get('account_cookie'))
        self.assertIsNone(client._access_token)


if __name__ == '__main__':
    unittest.main()
