"""Prehraj duration filtering uses the Android client's query contract."""
import json
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import requests
import test_provider_responses as provider_support
from kodi_test_support import ROOT
from resources.lib.preemptive_scope import source_scope

prehraj = provider_support.prehraj


class PrehrajSearchDurationTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'search_pages': '2', 'search_ls': '64', 'enable_filtering': 'true'}
        self.addon = MagicMock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.provider = object.__new__(prehraj.PrehrajTo)
        self.provider.addon = self.addon
        self.provider.base_url = 'https://example.invalid'
        self.provider._access_token = None
        self.provider.get_premium_cookies = MagicMock()
        self.provider.normalize_and_filter = MagicMock(side_effect=lambda rows, **kwargs: rows)
        self.provider._api_get = MagicMock(return_value=SimpleNamespace(status_code=200, json=lambda: [
            {'id': 1, 'title': 'Video'}]))

    def params(self, query):
        self.provider.search_sources(query, apply_filters=False)
        return self.provider._api_get.call_args_list[-1].kwargs['params']

    def test_default_does_not_exclude_short_videos(self):
        params = self.params('Film 2025')
        self.assertNotIn('longer-than-20min', params)
        self.assertNotIn('filterLongerThan20min', params)

    def test_opt_in_sends_actual_api_boolean_even_without_expression_filters(self):
        self.settings.update(prehrajto_long_videos='true', enable_filtering='false')
        params = self.params('Film 2025')
        request = requests.Request('GET', 'https://example.invalid/videos/search', params=params).prepare()
        self.assertEqual(parse_qs(urlsplit(request.url).query)['longer-than-20min'], ['true'])
        self.assertNotIn('filterLongerThan20min', params)

    def test_episode_queries_never_apply_duration_filter(self):
        self.settings['prehrajto_long_videos'] = 'true'
        for query in ('Show S01E02', 'Show s1e2', 'Show 1x02', 'Show 1X02'):
            with self.subTest(query=query):
                self.assertNotIn('longer-than-20min', self.params(query))

    def test_opt_in_applies_to_all_requested_pages(self):
        self.settings['prehrajto_long_videos'] = 'true'
        first_page = [{'id': i, 'title': 'Video'} for i in range(1, 33)]
        responses = [first_page, [{'id': 33, 'title': 'Video'}]]
        self.provider._api_get.side_effect = [SimpleNamespace(status_code=200, json=lambda rows=rows: rows)
                                               for rows in responses]
        rows = self.provider.search_sources('Film 2025', apply_filters=False)
        self.assertEqual(len(rows), 33)
        calls = [call.kwargs['params'] for call in self.provider._api_get.call_args_list]
        self.assertEqual([p['offset'] for p in calls], [0, 32])
        self.assertEqual([p.get('longer-than-20min') for p in calls], ['true', 'true'])

    def test_filter_changes_provider_cache_identity(self):
        manager = SimpleNamespace(_active_provider_name='prehraj.to')
        self.addon.getSettingBool.return_value = False
        baseline = source_scope(self.addon, manager)
        self.settings['prehrajto_long_videos'] = 'true'
        self.assertNotEqual(baseline, source_scope(self.addon, manager))

    def test_suggest_fallback_is_only_used_for_unfiltered_queries(self):
        self.provider._api_get.return_value = SimpleNamespace(status_code=200, json=lambda: [])
        self.settings['prehrajto_long_videos'] = 'true'
        self.provider.search_sources('Film', apply_filters=False)
        self.assertEqual([c.args[0] for c in self.provider._api_get.call_args_list], ['videos/search'])
        self.provider._api_get.reset_mock()
        self.provider.search_sources('Show S01E02', apply_filters=False)
        self.assertEqual([c.args[0] for c in self.provider._api_get.call_args_list],
                         ['videos/search', 'videos/suggest'])

    def test_new_setting_has_native_default_and_both_translations(self):
        root = ET.parse(ROOT / 'resources/settings.xml')
        setting = root.find(".//setting[@id='prehrajto_long_videos']")
        self.assertEqual(setting.get('type'), 'boolean')
        self.assertEqual(setting.findtext('default'), 'false')
        for language in ('en_gb', 'cs_cz'):
            text = (ROOT / 'resources' / 'language' / ('resource.language.' + language) / 'strings.po').read_text()
            for ident in ('32908', '32909'):
                self.assertEqual(text.count(f'msgctxt "#{ident}"'), 1)

    def test_actual_http_request_and_filtered_results(self):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                params = parse_qs(urlsplit(self.path).query)
                seen.append((urlsplit(self.path).path, params))
                rows = [{'id': 1, 'title': 'Short', 'duration': 600},
                        {'id': 2, 'title': 'Long', 'duration': 3600}]
                if params.get('longer-than-20min') == ['true']:
                    rows = [row for row in rows if row['duration'] > 1200]
                payload = json.dumps(rows).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

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
            self.assertEqual([r['id'] for r in self.provider.search_sources('Film')], [1, 2])
            self.settings['prehrajto_long_videos'] = 'true'
            self.assertEqual([r['id'] for r in self.provider.search_sources('Film')], [2])
            self.assertEqual([r['id'] for r in self.provider.search_sources('Show S01E02')], [1, 2])
        finally:
            self.provider.session.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertTrue(all(path == '/api/v2/videos/search' for path, _ in seen))
        self.assertEqual(seen[1][1].get('longer-than-20min'), ['true'])
        self.assertNotIn('longer-than-20min', seen[0][1])
        self.assertNotIn('longer-than-20min', seen[2][1])


if __name__ == '__main__':
    unittest.main()
