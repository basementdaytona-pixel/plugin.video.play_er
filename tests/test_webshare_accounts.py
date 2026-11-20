"""Webshare token ownership using synthetic accounts and an isolated profile."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_provider_responses as support
webshare = support.webshare
real_login = webshare.Webshare._login


class WebshareAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = {'webshare_username': 'first', 'webshare_password': 'first-pass', 'webshare_token': 'first-token'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.setSetting.side_effect = lambda key, value: self.settings.__setitem__(key, value)
        self.vfs = MagicMock()
        self.vfs.translatePath.side_effect = lambda path: str(Path(self.tmp.name) / Path(path).name)
        self.vfs.exists.side_effect = lambda path: Path(path).exists()
        self.vfs.mkdirs.return_value = True
        self.login_calls = []
        def login(provider):
            self.login_calls.append(provider.username)
            provider._auth_token = provider.username + '-new-token'
            saver = getattr(provider, '_save_token_binding', None)
            if saver:
                saver(provider._auth_token)
            provider.addon.setSetting('webshare_token', provider._auth_token)
            return True
        for p in (patch.object(webshare, 'xbmcvfs', self.vfs, create=True),
                  patch.object(webshare, 'SafeVFSFile', side_effect=lambda path, mode: open(path, mode, encoding='utf-8'), create=True),
                  patch.object(webshare.Webshare, '_login', autospec=True, side_effect=login)):
            p.start()
            self.addCleanup(p.stop)

    def create_provider(self):
        return webshare.Webshare(self.addon, 1, MagicMock(), None)

    def test_legacy_and_manually_replaced_tokens_remain_usable(self):
        first = self.create_provider()
        self.assertEqual(first._get_auth_token(), 'first-token')
        self.settings['webshare_token'] = 'manual-token'
        second = self.create_provider()
        self.assertEqual(second._get_auth_token(), 'manual-token')
        self.assertEqual(self.login_calls, [])

    def test_changed_account_does_not_reuse_old_token_after_recreation(self):
        self.create_provider()
        self.settings.update(webshare_username='second', webshare_password='second-pass')
        second = self.create_provider()
        self.assertEqual(second._get_auth_token(), 'second-new-token')
        self.assertEqual(self.login_calls, ['second'])

    def test_password_change_reauthenticates_existing_provider(self):
        provider = self.create_provider()
        self.settings['webshare_password'] = 'changed-pass'
        self.assertEqual(provider._get_auth_token(), 'first-new-token')
        self.assertEqual(self.login_calls, ['first'])

    def test_binding_does_not_store_raw_credentials_or_token(self):
        self.create_provider()
        content = (Path(self.tmp.name) / 'WEBSHARE_TOKEN_BINDING.JSON').read_text()
        for value in ('first', 'first-pass', 'first-token'):
            self.assertNotIn(value, content)

    def test_manually_changed_token_is_used_by_existing_provider(self):
        provider = self.create_provider()
        self.settings['webshare_token'] = 'manual-token'
        self.assertEqual(provider._get_auth_token(), 'manual-token')
        self.assertEqual(self.login_calls, [])

    def test_corrupt_binding_does_not_reuse_unverified_token(self):
        self.create_provider()
        (Path(self.tmp.name) / 'WEBSHARE_TOKEN_BINDING.JSON').write_text('{invalid')
        provider = self.create_provider()
        self.assertEqual(provider._get_auth_token(), 'first-new-token')
        self.assertEqual(self.login_calls, ['first'])

    def test_failed_login_does_not_reuse_old_account_token(self):
        self.create_provider()
        self.settings.update(webshare_username='second', webshare_password='second-pass')
        with patch.object(webshare.Webshare, '_login', return_value=False):
            provider = self.create_provider()
            self.assertIsNone(provider._get_auth_token())
        self.assertEqual(self.settings['webshare_token'], 'first-token')

    def test_unwritable_binding_still_detects_changes_in_existing_provider(self):
        with patch.object(webshare, 'SafeVFSFile', side_effect=OSError('synthetic write failure')):
            provider = self.create_provider()
            self.assertEqual(provider._get_auth_token(), 'first-token')
            self.settings['webshare_password'] = 'changed-pass'
            self.assertEqual(provider._get_auth_token(), 'first-new-token')
        self.assertEqual(self.login_calls, ['first'])

    def test_failed_vfs_write_is_reported_without_raw_credentials(self):
        handle = MagicMock()
        handle.write.return_value = False
        context = MagicMock()
        context.__enter__.return_value = handle
        with patch.object(webshare, 'SafeVFSFile', return_value=context), patch.object(webshare, 'log') as log:
            provider = self.create_provider()
            self.assertFalse(provider._save_token_binding('first-token'))
        self.assertNotIn('first-pass', str(log.call_args_list))
        self.assertNotIn('first-token', str(log.call_args_list))

    def test_removing_credentials_does_not_return_cached_token(self):
        provider = self.create_provider()
        self.settings['webshare_password'] = ''
        self.assertIsNone(provider._get_auth_token())
        self.assertEqual(self.login_calls, [])

    def test_login_does_not_overwrite_credentials_or_token_changed_during_request(self):
        for field, new_value in [('webshare_username', 'second'), ('webshare_token', 'manual-token')]:
            with self.subTest(field=field):
                self.settings.update(webshare_username='first', webshare_password='first-pass', webshare_token='first-token')
                provider = self.create_provider()
                salt = SimpleNamespace(status_code=200, content=b'<response><status>OK</status><salt>synthetic</salt></response>')
                login = SimpleNamespace(status_code=200, content=b'<response><status>OK</status><token>stale-new-token</token></response>')
                def request(*args, **kwargs):
                    if args[1].endswith('/login/'):
                        self.settings[field] = new_value
                        return login
                    return salt
                with patch.object(webshare, 'safe_post', side_effect=request), \
                     patch.object(webshare, 'md5crypt', return_value='synthetic-hash'):
                    self.assertFalse(real_login(provider))
                self.assertEqual(self.settings[field], new_value)
                self.assertNotEqual(self.settings['webshare_token'], 'stale-new-token')


if __name__ == '__main__':
    unittest.main()
