"""Subtitle downloads must not expose partial or damaged files to Kodi."""
import json
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_provider_responses as provider_support
from kodi_test_support import ROOT

prehraj = provider_support.prehraj


def make_provider():
    client = object.__new__(prehraj.PrehrajTo)
    client.addon = MagicMock()
    client.addon.getSettingString.return_value = 'auto'
    client.addon.getSetting.return_value = ''
    client.session = MagicMock()
    client.get_premium_cookies = MagicMock()
    client.api_get_video_detail = MagicMock(return_value={})
    client.api_get_download_link = MagicMock(return_value={'720P': 'https://example.invalid/video'})
    client.api_get_video_subtitle = MagicMock(return_value=[
        {'name': 'Czech', 'language': 'cz', 'cdnUrl': 'https://example.invalid/cz'}])
    return client


def setup_directory(directory):
    return patch.object(prehraj.xbmcvfs, 'translatePath',
                        side_effect=lambda path: str(Path(directory) / path.rstrip('/').split('/')[-1]))


def directory_tools():
    return patch.dict(sys.modules, {'resources.lib.utils_files':
                      SimpleNamespace(ensure_dir=lambda path: os.makedirs(path, exist_ok=True))})


class PrehrajSubtitleFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.client = make_provider()
        self.patchers = [setup_directory(self.directory), directory_tools(),
                         patch.object(prehraj.xbmcgui, 'Window', return_value=MagicMock())]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.folder = self.directory / '123456'
        self.folder.mkdir()
        self.path = self.folder / 'CZECH_0.vtt'
        self.old = b'Previous complete subtitle'
        self.new = b'Updated complete subtitle'
        self.path.write_bytes(self.old)

    def test_old_file_stays_intact_until_new_file_is_ready(self):
        real_replace = os.replace
        def publish(source, destination):
            self.assertEqual(Path(destination), self.path)
            self.assertEqual(self.path.read_bytes(), self.old)
            self.assertEqual(Path(source).read_bytes(), self.new)
            return real_replace(source, destination)
        with patch.object(prehraj, 'safe_get', return_value=SimpleNamespace(content=self.new)), \
             patch.object(prehraj.os, 'replace', side_effect=publish) as replace:
            url, paths = self.client.get_video_link('123456')
        replace.assert_called_once()
        self.assertEqual(url, 'https://example.invalid/video')
        self.assertEqual(paths, [str(self.path)])
        self.assertEqual(self.path.read_bytes(), self.new)
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_replace_failure_preserves_existing_file_and_cleans_staging_file(self):
        with patch.object(prehraj, 'safe_get', return_value=SimpleNamespace(content=self.new)), \
             patch.object(prehraj.os, 'replace', side_effect=OSError('synthetic replacement failure')):
            _, paths = self.client.get_video_link('123456')
        self.assertEqual(paths, [])
        self.assertEqual(self.path.read_bytes(), self.old)
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_failed_download_reuses_existing_subtitle(self):
        with patch.object(prehraj, 'safe_get', return_value=None):
            _, paths = self.client.get_video_link('123456')
        self.assertEqual(paths, [str(self.path)])
        self.assertEqual(self.path.read_bytes(), self.old)

    def test_simultaneous_resolutions_publish_only_complete_files(self):
        barrier = threading.Barrier(2)
        payloads = [b'First complete subtitle', b'Second complete subtitle']
        lock = threading.Lock()
        def download(*args, **kwargs):
            with lock:
                content = payloads.pop()
            barrier.wait(timeout=5)
            return SimpleNamespace(content=content)
        with patch.object(prehraj, 'safe_get', side_effect=download), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.client.get_video_link, '123456') for _ in range(2)]
            results = [future.result(timeout=8) for future in futures]
        self.assertTrue(all(paths == [str(self.path)] for _, paths in results))
        self.assertIn(self.path.read_bytes(), (b'First complete subtitle', b'Second complete subtitle'))
        self.assertEqual(list(self.folder.iterdir()), [self.path])

    def test_other_video_files_are_not_changed(self):
        other = self.directory / '654321'
        other.mkdir()
        previous = other / 'CZECH_0.vtt'
        previous.write_bytes(b'Other video')
        with patch.object(prehraj, 'safe_get', return_value=SimpleNamespace(content=self.new)):
            self.client.get_video_link('123456')
        self.assertEqual(previous.read_bytes(), b'Other video')

    @unittest.skipUnless(os.name == 'posix' and hasattr(signal, 'SIGXFSZ')
                         and importlib.util.find_spec('resource') is not None,
                         'POSIX file size limit required')
    def test_short_write_does_not_damage_existing_subtitle(self):
        script = r'''
import json, resource, signal, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from test_prehraj_subtitle_files import prehraj, make_provider, setup_directory, directory_tools
root=Path(sys.argv[1]); client=make_provider(); folder=root/'123456'; folder.mkdir()
path=folder/'CZECH_0.vtt'; original=b'Previous complete subtitle'; path.write_bytes(original)
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (5, 5))
with setup_directory(root), directory_tools(), patch.object(prehraj.xbmcgui,'Window',return_value=MagicMock()), patch.object(prehraj,'safe_get',return_value=SimpleNamespace(content=b'A longer updated subtitle')):
    _, paths=client.get_video_link('123456')
print(json.dumps({'intact':path.read_bytes()==original,'paths':paths,'files':sorted(p.name for p in folder.iterdir())}))
'''
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT / 'tests'))
        with tempfile.TemporaryDirectory() as directory:
            child = subprocess.run([sys.executable, '-c', script, directory], cwd=ROOT,
                                   env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr)
        outcome = json.loads(child.stdout)
        self.assertTrue(outcome['intact'])
        self.assertEqual(outcome['paths'], [])
        self.assertEqual(outcome['files'], ['CZECH_0.vtt'])


if __name__ == '__main__':
    unittest.main()
