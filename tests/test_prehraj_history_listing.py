"""History listing preserves original labels when title cleanup is disabled or fails."""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import test_episode_playback as support

actions = support.actions


class PrehrajHistoryListingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {'title': 'First original', 'link': 'first', 'provider': 'prehraj.to', 'likes': 2},
            {'title': 'Second original', 'link': 'second', 'provider': 'prehraj.to', 'likes': 3},
        ]
        provider = SimpleNamespace(get_user_history=lambda: self.rows)
        self.addon = MagicMock()
        self.instance = SimpleNamespace(handle=7, addon=self.addon, tmdb_client=None,
                                        provider_manager=SimpleNamespace(_get_provider_instance=lambda name: provider))
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.list_items = stack.enter_context(patch.object(actions.xbmcgui, 'ListItem'))
        self.end = stack.enter_context(patch.object(actions.xbmcplugin, 'endOfDirectory'))
        self.add = stack.enter_context(patch.object(actions.xbmcplugin, 'addDirectoryItem'))
        self.content = stack.enter_context(patch.object(actions.xbmcplugin, 'setContent'))
        self.view = stack.enter_context(patch.object(actions, 'set_view_mode'))
        self.clean = stack.enter_context(patch.object(actions, 'clean_display_title'))
        stack.enter_context(patch.object(actions, '_get_context_menu', return_value=[]))
        stack.enter_context(patch.object(actions, '_sf_cm_items', return_value=[]))
        stack.enter_context(patch.object(actions, 'get_url', side_effect=lambda **kw: kw['link']))

    def test_disabled_filter_uses_each_original_title(self):
        self.addon.getSettingBool.return_value = False
        actions.prehrajto_history(self.instance)
        self.assertEqual([call.kwargs['label'] for call in self.list_items.call_args_list],
                         ['First original', 'Second original'])
        self.clean.assert_not_called()
        self.assertEqual([call.args[1] for call in self.add.call_args_list], ['first', 'second'])
        self.content.assert_called_with(7, 'videos')
        self.end.assert_called_once_with(7, succeeded=True, cacheToDisc=False)

    def test_filter_failure_uses_current_title_not_previous_result(self):
        self.addon.getSettingBool.side_effect = lambda key: key == 'filter_display_title_history'
        self.clean.side_effect = [('Clean first', False, [], None), ValueError('invalid title')]
        actions.prehrajto_history(self.instance, is_widget=True)
        self.assertEqual([call.kwargs['label'] for call in self.list_items.call_args_list],
                         ['Clean first', 'Second original'])
        self.assertEqual(self.add.call_count, 2)
        self.view.assert_not_called()
        self.end.assert_called_once_with(7, succeeded=True, cacheToDisc=False)

    def test_filter_failure_on_first_title_does_not_stop_listing(self):
        self.addon.getSettingBool.side_effect = lambda key: key == 'filter_display_title_history'
        self.clean.side_effect = [ValueError('invalid title'), ('Clean second', False, [], None)]
        actions.prehrajto_history(self.instance)
        self.assertEqual([call.kwargs['label'] for call in self.list_items.call_args_list],
                         ['First original', 'Clean second'])
        self.end.assert_called_once_with(7, succeeded=True, cacheToDisc=False)

    def test_disabled_filter_preserves_size_and_duration(self):
        self.rows[0].update(size_str='1 GB', duration_str='01:10')
        self.addon.getSettingBool.side_effect = lambda key: key in ('show_size', 'show_duration_time')
        actions.prehrajto_history(self.instance)
        label = self.list_items.call_args_list[0].kwargs['label']
        self.assertIn('[1 GB]', label)
        self.assertIn('[01:10]', label)
        self.assertTrue(label.endswith('First original'))


if __name__ == '__main__':
    unittest.main()
