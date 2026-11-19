import json
import unittest
from unittest.mock import MagicMock, patch

from kodi_test_support import load_module

views = load_module('resources.lib.view_modes')
with patch.dict('sys.modules', {'resources.lib.view_modes': views}):
    ui = load_module('resources.lib.ui_builder', (
        'resources.lib.sf_context_style', 'resources.lib.utils_theme', 'resources.lib.utils',
    ))

URL = 'plugin://plugin.video.play_er/?action=menu&page=2'


class ViewModesTests(unittest.TestCase):
    def setUp(self):
        views.begin_directory(URL, {})
        views.xbmc.reset_mock()
        views.xbmcvfs.reset_mock()
        views.xbmc.getSkinDir.return_value = 'skin.arctic.fuse.3'
        views.xbmc.getCondVisibility.return_value = True
        views.xbmc.getInfoLabel.return_value = URL

    def test_view_is_applied_only_after_directory_completion(self):
        addon = MagicMock()
        addon.getSettingBool.side_effect = lambda key: key == 'enable_view_modes'
        addon.getSettingString.return_value = 'Široký seznam'
        source = views.xbmcvfs.File.return_value
        source.read.return_value = json.dumps({'viewtypes': {'583': '31480', '580': '31120'}})
        ui.xbmc.getSkinDir.return_value = 'skin.arctic.fuse.3'
        ui.xbmc.getCondVisibility.return_value = False
        ui.set_view_mode(1, addon, 'movies', 'movies')
        views.xbmc.executebuiltin.assert_not_called()
        ui.xbmcplugin.endOfDirectory(1)
        self.assertTrue(views.finish_directory())
        views.xbmc.executebuiltin.assert_called_once_with('Container.SetViewMode(583)')
        self.assertFalse(views.finish_directory())
        source.close.assert_called_once()

    def test_installed_skin_controls_ids_including_older_af3(self):
        source = views.xbmcvfs.File.return_value
        for view_id in ('509', '583'):
            source.read.return_value = json.dumps({'viewtypes': {view_id: '31480'}})
            self.assertEqual(views.af3_view_ids()['widelist'], int(view_id))
        source.read.return_value = 'invalid json'
        self.assertEqual(views.af3_view_ids(), {})

    def test_invalid_ids_never_execute(self):
        for value in (None, 0, -1, '１２３', '583),ReloadSkin(', 'nan'):
            self.assertFalse(views.apply_view_mode(value))
        views.xbmc.executebuiltin.assert_not_called()

    def test_same_addon_different_folder_is_not_changed(self):
        views.xbmc.getInfoLabel.return_value = URL.replace('page=2', 'page=3')
        self.assertFalse(views.apply_view_mode(583, plugin_url=URL))
        views.xbmc.executebuiltin.assert_not_called()
        views.xbmc.getInfoLabel.return_value = 'plugin://plugin.video.play_er/?page=2&action=menu'
        self.assertTrue(views.apply_view_mode(583, plugin_url=URL))

    def test_hosted_lists_and_non_video_windows_keep_host_view(self):
        for key in ('widget', 'is_widget', 'widget_id', 'multisearch', 'is_multisearch'):
            views.begin_directory(URL, {key: 'true'})
            views.queue_view_mode(583)
            self.assertFalse(views.finish_directory())
        views.begin_directory(URL, {})
        for kw in ({'widgets': True}, {'multisearch': True}, {'video_list': False}):
            self.assertFalse(views.apply_view_mode(583, **kw))
        views.xbmc.getCondVisibility.return_value = False
        self.assertFalse(views.apply_view_mode(583))
        views.xbmc.executebuiltin.assert_not_called()

    def test_reused_interpreter_does_not_keep_pending_view(self):
        views.queue_view_mode(583)
        views.begin_directory(URL, {})
        self.assertFalse(views.finish_directory())
        views.xbmc.executebuiltin.assert_not_called()

    def test_catalogue_is_opt_in_for_af3_navigation_only(self):
        addon = MagicMock()
        addon.getSetting.return_value = 'false'
        self.assertEqual(views.menu_content(addon, 'files', 'main_menu'), 'files')
        addon.getSetting.return_value = 'true'
        self.assertEqual(views.menu_content(addon, 'files', 'main_menu'), 'movies')
        self.assertEqual(views.menu_content(addon, 'episodes', 'episodes'), 'episodes')
        self.assertEqual(views.menu_content(addon, 'files', 'sources'), 'files')
        views.begin_directory(URL, {'widget': 'true'})
        self.assertEqual(views.menu_content(addon, 'files', 'main_menu'), 'files')
        views.begin_directory(URL, {})
        views.xbmc.getSkinDir.return_value = 'skin.estuary'
        self.assertEqual(views.menu_content(addon, 'files', 'main_menu'), 'files')

    def test_native_configuration_uses_supported_skinvariables_action(self):
        addon = MagicMock()
        views.xbmcgui.Dialog.return_value.select.return_value = 1
        self.assertTrue(views.configure_af3_views(addon))
        addon.setSettingBool.assert_called_once_with('af3_native_views', True)
        views.xbmc.executebuiltin.assert_called_once_with(
            'RunScript(script.skinvariables,action=buildviews,pluginname=plugin.video.play_er,contentid=movies)')
        views.xbmc.reset_mock()
        views.xbmcgui.Dialog.return_value.select.return_value = -1
        self.assertFalse(views.configure_af3_views(addon))
        views.xbmc.executebuiltin.assert_not_called()
        views.xbmc.getSkinDir.return_value = 'skin.estuary'
        self.assertFalse(views.configure_af3_views(addon))
        views.xbmc.executebuiltin.assert_not_called()

    def test_native_or_disabled_modes_still_set_content(self):
        addon = MagicMock()
        ui.xbmc.getSkinDir.return_value = 'skin.arctic.fuse.3'
        for enabled, native in ((True, True), (False, False)):
            addon.getSettingBool.side_effect = lambda key: enabled if key == 'enable_view_modes' else native
            with patch.object(ui, 'queue_view_mode') as queue:
                ui.set_view_mode(1, addon, 'episodes', 'episodes')
            queue.assert_not_called()
            ui.xbmcplugin.setContent.assert_called_with(1, 'episodes')


if __name__ == '__main__':
    unittest.main()
