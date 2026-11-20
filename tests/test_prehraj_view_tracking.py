"""Only started, verified Prehraj sources should be reported as views."""
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_provider_responses as support
import test_prehraj_accounts as account_support
from test_atomic_user_data import actions
from test_movie_playlist import FakeWindow

prehraj = support.prehraj


class ViewResolutionTests(unittest.TestCase):
    def test_preparing_a_video_does_not_report_a_view(self):
        client = object.__new__(prehraj.PrehrajTo)
        client.addon = MagicMock()
        client.addon.getSettingString.return_value = 'auto'
        client.addon.getSetting.return_value = ''
        client.get_premium_cookies = MagicMock()
        client.api_track_view = MagicMock()
        client.api_get_video_detail = MagicMock(return_value={})
        client.api_get_download_link = MagicMock(return_value={'720P': 'https://example.invalid/video'})
        client.api_get_video_subtitle = MagicMock(return_value=[])
        with patch.object(prehraj.xbmcgui, 'Window', return_value=MagicMock()):
            url, _ = client.get_video_link('https://prehraj.to/videos/123456')
        self.assertEqual(url, 'https://example.invalid/video')
        client.api_track_view.assert_not_called()

    def test_report_uses_app_declared_endpoint(self):
        client = object.__new__(prehraj.PrehrajTo)
        client._api_post = MagicMock()
        client.api_track_view('123456')
        client._api_post.assert_called_once_with('videos/123456/add-view', require_auth=True)


class ViewAccountTests(unittest.TestCase):
    def setUp(self):
        self.env = account_support.PrehrajAccountTests(methodName='runTest')
        self.env.setUp()
        self.addCleanup(self.env.doCleanups)
        self.client = self.env.provider()
        self.client.get_premium_cookies()
        self.url = 'https://example.invalid/video?token=synthetic-stream'
        self.identity = self.client.view_tracking_identity('https://prehraj.to/videos/123456', self.url)
        self.client.session.post.reset_mock()

    def test_bound_view_posts_to_matching_account(self):
        video_id, binding = self.identity
        self.client.api_track_view(video_id, self.url, binding)
        call = self.client.session.post.call_args
        self.assertTrue(call.args[0].endswith('/videos/123456/add-view'))
        self.assertIsNone(call.kwargs['json'])
        self.assertEqual(call.kwargs['headers']['Authorization'], 'Bearer first-token')

    def test_changed_account_or_video_never_receives_old_view(self):
        video_id, binding = self.identity
        self.client.api_track_view('123457', self.url, binding)
        self.client.api_track_view(video_id, self.url + '-different', binding)
        self.env.settings['password'] = 'changed-pass'
        self.client.api_track_view(video_id, self.url, binding)
        self.client.session.post.assert_not_called()

    def test_token_rotated_before_playback_skips_unverifiable_view(self):
        video_id, binding = self.identity
        self.client._set_tokens('other-token', 'other-refresh')
        self.client.api_track_view(video_id, self.url, binding)
        self.client.session.post.assert_not_called()

    def test_url_only_resolver_returns_private_binding_without_reporting_view(self):
        self.client.get_video_link = MagicMock(return_value=(self.url, []))
        instance = MagicMock()
        instance.provider_manager.get_provider.return_value = self.client
        window = FakeWindow()
        window.setProperty('play_er.monitor_owner', 'owner')
        with patch.object(actions.xbmcgui, 'Window', return_value=window):
            result, identity = actions.resolve_video('https://prehraj.to/videos/123456', 'prehraj.to',
                                                     {'media_type': 'movie', 'title': 'Synthetic'},
                                                     return_url_only=True, return_view_identity=True,
                                                     plugin_instance=instance)
        self.assertTrue(result.startswith(self.url))
        self.client.session.post.assert_not_called()
        self.assertEqual(identity[0], '123456')
        for secret in (self.url, 'first@example.invalid', 'first-pass', 'first-token'):
            self.assertNotIn(secret, str(identity))
        self.assertNotIn('expected_view', str(window.properties))

    def test_account_change_during_unauthorized_response_never_retries_under_new_account(self):
        video_id, binding = self.identity
        def unauthorized(*args, **kwargs):
            self.env.settings['email'] = 'second@example.invalid'
            return SimpleNamespace(status_code=401)
        self.client.session.post.side_effect = unauthorized
        self.client.api_track_view(video_id, self.url, binding)
        self.client.session.post.assert_called_once()
        self.assertIsNone(self.client._access_token)

    def test_unauthorized_view_refreshes_and_retries_for_same_account(self):
        video_id, binding = self.identity
        self.client.session.post.side_effect = [
            SimpleNamespace(status_code=401),
            SimpleNamespace(status_code=200, json=lambda: {'data': {'access': 'new-token', 'refresh': 'new-refresh'}}),
            SimpleNamespace(status_code=200),
        ]
        self.client.api_track_view(video_id, self.url, binding)
        urls = [call.args[0] for call in self.client.session.post.call_args_list]
        self.assertTrue(urls[0].endswith('/videos/123456/add-view'))
        self.assertTrue(urls[1].endswith('/users/refresh-token'))
        self.assertEqual(urls[0], urls[2])
        self.assertEqual(self.client.session.post.call_args.kwargs['headers']['Authorization'], 'Bearer new-token')

    def test_slow_view_request_does_not_block_other_auth_checks(self):
        entered, release = threading.Event(), threading.Event()
        def post(*args, **kwargs):
            entered.set()
            release.wait(3)
            return SimpleNamespace(status_code=204)
        self.client.session.post.side_effect = post
        video_id, binding = self.identity
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                reporting = executor.submit(self.client.api_track_view, video_id, self.url, binding)
                self.assertTrue(entered.wait(1))
                checked = executor.submit(self.client.get_premium_cookies)
                self.assertIs(checked.result(timeout=1), self.client.session.cookies)
                release.set()
                self.assertTrue(reporting.result(timeout=1))
        finally:
            release.set()


if __name__ == '__main__':
    unittest.main()
