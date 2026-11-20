"""Prehraj API preferences are independent of local expression filters."""
import json
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import requests
import test_episode_playback as episode_support
import test_provider_responses as provider_support
from kodi_test_support import ROOT
from resources.lib.preemptive_scope import source_scope

prehraj = provider_support.prehraj
actions = episode_support.actions


class PrehrajSearchPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'search_pages': '1', 'search_ls': '32', 'enable_filtering': 'false'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.addon.getSettingBool.return_value = False
        self.provider = object.__new__(prehraj.PrehrajTo)
        self.provider.addon = self.addon
        self.provider.base_url = 'https://example.invalid'
        self.provider._access_token = None
        self.provider.get_premium_cookies = MagicMock()
        self.provider.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)
        self.provider._api_get = MagicMock(return_value=SimpleNamespace(status_code=200,
                    json=lambda: [{'id': 1, 'title': 'Video'}]))

    def query(self, apply_filters=False):
        self.provider._api_get.reset_mock()
        self.provider.search_sources('Show S01E02', apply_filters=apply_filters)
        return self.provider._api_get.call_args.kwargs['params']

    def test_defaults_preserve_previous_server_request(self):
        self.assertNotIn('sort', self.query())
        self.assertNotIn('quality', self.query())
        self.settings['enable_filtering'] = 'true'
        self.assertEqual(self.query()['sort'], 'relevance')

    def test_selected_sort_is_sent_without_expression_filters(self):
        for value, expected in [('1', 'popularity'), ('2', 'relevance')]:
            with self.subTest(value=value):
                self.settings['prehrajto_api_sort'] = value
                self.assertEqual(self.query()['sort'], expected)

    def test_all_quality_choices_are_sent_without_expression_filters(self):
        for value, expected in [('1', '4k'), ('2', '1080p'), ('3', '720p'),
                                ('4', '1440p'), ('5', '480p'), ('6', '360p'),
                                ('7', '240p'), ('8', '8k'), ('9', '8k_more')]:
            for apply_filters in (False, True):
                with self.subTest(value=value, apply_filters=apply_filters):
                    self.settings['prehrajto_api_quality'] = value
                    self.assertEqual(self.query(apply_filters)['quality'], expected)

    def test_quality_limit_never_falls_back_to_unfiltered_suggestions(self):
        self.settings['prehrajto_api_quality'] = '1'
        self.provider._api_get.return_value = SimpleNamespace(status_code=200, json=lambda: [])
        for filtering in ('false', 'true'):
            self.settings['enable_filtering'] = filtering
            self.provider._api_get.reset_mock()
            self.assertEqual(self.provider.search_sources('Film'), [])
            self.assertEqual([c.args[0] for c in self.provider._api_get.call_args_list], ['videos/search'])
        self.settings['prehrajto_api_quality'] = '0'
        self.provider._api_get.reset_mock()
        self.provider.search_sources('Film')
        self.assertEqual([c.args[0] for c in self.provider._api_get.call_args_list],
                         ['videos/search', 'videos/suggest'])

    def test_tmdbhelper_search_worker_keeps_server_preferences(self):
        self.settings.update(prehrajto_api_sort='1', prehrajto_api_quality='2')
        with patch.object(actions, 'get_threadpool', return_value=2):
            rows = actions._search_providers_parallel('Show S01E02', [self.provider], apply_filters=False)
        self.assertEqual(len(rows), 1)
        params = self.provider._api_get.call_args.kwargs['params']
        self.assertEqual((params['sort'], params['quality']), ('popularity', '1080p'))

    def test_old_preemptive_cache_scope_is_invalidated(self):
        self.settings = {'enable_filtering': 'false', 'prehrajto_api_sort': '1', 'prehrajto_api_quality': '1'}
        manager = SimpleNamespace(_active_provider_name='prehraj.to')
        old_scope = '9a497c518e4384be80a7c840f85c43103c0436b1948743cb00742024afa6d953'
        self.assertNotEqual(source_scope(self.addon, manager), old_scope)

    def test_setting_values_and_translation_ids_are_complete(self):
        root = ET.parse(ROOT / 'resources/settings.xml')
        quality = root.find(".//setting[@id='prehrajto_api_quality']")
        options = quality.findall('./constraints/options/option')
        self.assertEqual({o.text for o in options}, {str(i) for i in range(10)})
        for language in ('en_gb', 'cs_cz'):
            text = (ROOT / 'resources' / 'language' / ('resource.language.' + language) / 'strings.po').read_text()
            for ident in ('32910', '32911', '32912', '32913', '32914', '32915', '32916', '32917'):
                self.assertEqual(text.count(f'msgctxt "#{ident}"'), 1)

    def test_actual_http_request_honors_selected_quality(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlsplit(self.path).query)
                seen.append(params)
                rows = [{'id': 1, 'title': '4K'}, {'id': 2, 'title': '720P'}]
                if params.get('quality') == ['4k']:
                    rows = rows[:1]
                data = json.dumps(rows).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.provider.api_base = 'http://127.0.0.1:%d/api/v2/' % server.server_port
            self.provider.headers = {'user-agent': 'synthetic-test'}
            self.provider.session = requests.Session()
            self.provider._api_get = prehraj.PrehrajTo._api_get.__get__(self.provider)
            self.assertEqual(len(self.provider.search_sources('Film')), 2)
            self.settings.update(prehrajto_api_quality='1', prehrajto_api_sort='1')
            self.assertEqual([r['id'] for r in self.provider.search_sources('Film')], [1])
        finally:
            self.provider.session.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(seen[-1].get('quality'), ['4k'])
        self.assertEqual(seen[-1].get('sort'), ['popularity'])


if __name__ == '__main__':
    unittest.main()
