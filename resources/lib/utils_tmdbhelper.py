# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_tmdbhelper.py
# Author: Mau!X ER
# Created on: 24.10.2026
# Last edit on: 24.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import json

from datetime import datetime





TMDBHELPER_DATA = "special://profile/addon_data/plugin.video.themoviedb.helper"

PLAYER_FILES = (
    "[TMDBH]--SOURCES-PREDICTION.json",
    "[TMDBH]--SOURCES-SCRIPT.json",
    "[TMDBH]--SOURCES-TMDB.json",
    "[TMDBH]--SEARCH-TEXT.json",
    "[TMDBH]--AUTO-PLAY.json",
    "[TMDBH]--AUTO-NEXT.json",
)


def normalise_tmdb_id(value):
    """TMDB IDs are positive ASCII integers, never paths or placeholders."""
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or int(text) < 1:
        raise ValueError("Chybí platné TMDB ID")
    return str(int(text))


def normalise_episode_numbers(season, episode):
    """Validate TMDBHelper coordinates; season zero contains specials."""
    values = []
    for value, minimum in ((season, 0), (episode, 1)):
        text = str(value).strip()
        if not text.isdecimal() or int(text) < minimum:
            raise ValueError("Chybí platné číslo série nebo epizody")
        values.append(str(int(text)))
    return tuple(values)




class TMDBHelperSetup:

    """
    TMDB-HELPER :: FUNCTIONS
    -- Functions for setup TMDBHelper addon settings.xml
    """


    def __init__(self, source_addon, target_addon, vfs):
        self.source = source_addon
        self.target = target_addon
        self.vfs = vfs


    def _path(self, *parts):
        return os.path.join(self.vfs.translatePath(TMDBHELPER_DATA), *parts)

    def _read_text(self, path):
        file_obj = self.vfs.File(path, "r")
        try:
            return file_obj.read()
        finally:
            file_obj.close()

    def _write_text(self, path, content):
        file_obj = self.vfs.File(path, "w")
        try:
            file_obj.write(content)
        finally:
            file_obj.close()

    def _backup(self, overwritten_players=()):
        settings = self._path("settings.xml")
        if not self.vfs.exists(settings):
            raise RuntimeError("Nastavení TMDBHelper nebylo nalezeno; změny nebyly provedeny")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_dir = self._path("play_er_backups", stamp)
        if not self.vfs.mkdirs(backup_dir) and not self.vfs.exists(backup_dir):
            raise RuntimeError("Nelze vytvořit složku zálohy TMDBHelper")
        backup_file = os.path.join(backup_dir, "settings.xml")
        if not self.vfs.copy(settings, backup_file) or not self.vfs.exists(backup_file):
            raise RuntimeError("Záloha nastavení TMDBHelper selhala; změny nebyly provedeny")
        if overwritten_players:
            player_backup = os.path.join(backup_dir, "players")
            if not self.vfs.mkdirs(player_backup) and not self.vfs.exists(player_backup):
                raise RuntimeError("Nelze vytvořit složku zálohy playerů")
            for filename in overwritten_players:
                original = self._path("players", filename)
                saved = os.path.join(player_backup, filename)
                # Kodi CFile::Copy treats a literal pipe in local filenames as
                # URL options when creating the parent directory. It leaves an
                # extra |NAME.json directory next to the copied player. Copy
                # these JSON texts via File I/O and verify the complete backup.
                content = self._read_text(original)
                self._write_text(saved, content)
                if not self.vfs.exists(saved) or self._read_text(saved) != content:
                    raise RuntimeError("Záloha playerů TMDBHelper selhala; změny nebyly provedeny")
        return backup_dir


    @staticmethod
    def _normalise(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _apply_settings(self, updates):
        changed = {key: value for key, value in updates.items()
                   if self.target.getSetting(key) != self._normalise(value)}
        if not changed:
            return 0
        before = {key: self.target.getSetting(key) for key in changed}
        self._backup()
        try:
            for key, value in changed.items():
                if isinstance(value, bool):
                    self.target.setSettingBool(key, value)
                else:
                    self.target.setSettingString(key, str(value))
                if self.target.getSetting(key) != self._normalise(value):
                    raise RuntimeError(f"Nastavení {key} nebylo uloženo")
        except Exception:
            for key, previous in before.items():
                try:
                    if isinstance(changed[key], bool):
                        self.target.setSettingBool(key, previous.lower() == "true")
                    else:
                        self.target.setSettingString(key, previous)
                except Exception:
                    pass
            raise
        return len(changed)


    def configure_database(self):
        base = (self.source.getSetting("library_path") or "").strip().rstrip("/\\")
        if not base:
            raise ValueError("Nejprve nastavte složku knihovny PLAY.ER")
        return self._apply_settings({
            "movies_library": f"{base}/Movies/",
            "tvshows_library": f"{base}/TV Shows/",
        })

    def configure_tmdbhelper(self):
        filename = "[TMDBH]--SOURCES-PREDICTION.json"
        player_path = self._path("players", filename)
        if not self.vfs.exists(player_path):
            raise RuntimeError("Nejprve použijte TMDBHELP : INSTALOVAT PLAYERY")
        player = json.loads(self._read_text(player_path))
        if not isinstance(player, dict) or player.get("plugin") != "plugin.video.play_er":
            raise ValueError("Výchozí player TMDBHelper není platný PLAY.ER player")
        for method in ("search_movie", "search_episode"):
            if not isinstance(player.get(method), str) or not player[method].strip():
                raise ValueError(f"Výchozí player TMDBHelper neobsahuje {method}")
        return self._apply_settings({
            "only_resolve_strm": True,
            "default_player_movies": filename + " search_movie",
            "default_player_episodes": filename + " search_episode",
        })

    def configure_search(self):
        return self._apply_settings({
            "dummy_duration": "0.1",
            "dummy_delay": "0.1",
            "only_resolve_strm": True,
        })

    def configure_api_keys(self):
        gemini = (self.source.getSetting("gemini_api_key") or "").strip()
        if not gemini:
            raise ValueError("Gemini API klíč v PLAY.ER není vyplněn")
        return self._apply_settings({"gemini_apikey": gemini})

    def install_players(self):
        addon_path = self.vfs.translatePath(self.source.getAddonInfo("path"))
        source_dir = os.path.join(addon_path, "resources", "custom", "players")
        target_dir = self._path("players")
        changed = {}
        overwritten = []
        for filename in PLAYER_FILES:
            src = os.path.join(source_dir, filename)
            if not self.vfs.exists(src):
                raise RuntimeError(f"Player {filename} nebyl nalezen")
            content = self._read_text(src)
            data = json.loads(content)
            if not isinstance(data, dict) or data.get("plugin") != "plugin.video.play_er":
                raise ValueError(f"Player {filename} má neplatný obsah")
            dst = os.path.join(target_dir, filename)
            if self.vfs.exists(dst) and self._read_text(dst) == content:
                continue
            changed[dst] = content
            if self.vfs.exists(dst):
                overwritten.append(filename)
        if not changed:
            return 0
        backup_dir = self._backup(overwritten)
        if not self.vfs.exists(target_dir) and not self.vfs.mkdirs(target_dir):
            raise RuntimeError("Nelze vytvořit složku playerů TMDBHelper")
        written = []
        try:
            for dst, content in changed.items():
                written.append(dst)
                self._write_text(dst, content)
                if self._read_text(dst) != content:
                    raise RuntimeError(f"Player {os.path.basename(dst)} nebyl uložen")
        except Exception:
            for dst in written:
                filename = os.path.basename(dst)
                saved = os.path.join(backup_dir, "players", filename)
                try:
                    if self.vfs.exists(saved):
                        self._write_text(dst, self._read_text(saved))
                    else:
                        self.vfs.delete(dst)
                except Exception:
                    pass
            raise
        return len(changed)





def run_tmdbhelper_setup(task, source_addon):

    """
    TMDB-HELPER :: SETUP
    -- Entry point for the TMDBHELP settings buttons in PLAY.ER
    """


    import xbmc
    from resources.lib.utils_notification import notify_info, notify_error
    import xbmcvfs
    import xbmcaddon


    actions = {
        "configure": ("TMDBHELPER", "configure_tmdbhelper"),
        "database": ("KNIHOVNA", "configure_database"),
        "search": ("VYHLEDÁVÁNÍ", "configure_search"),
        "api_keys": ("API KLÍČE", "configure_api_keys"),
        "players": ("PLAYERY", "install_players"),
    }

    if task not in actions:
        xbmc.log("PLAY.ER :: Neznámá akce nastavení TMDBHelper", xbmc.LOGWARNING)
        return False
    label, method = actions[task]
    try:
        target = xbmcaddon.Addon(id="plugin.video.themoviedb.helper")
        setup = TMDBHelperSetup(source_addon, target, xbmcvfs)
        count = getattr(setup, method)()
        message = f"{label}: {count} ZMĚNĚNO" if count else f"{label}: JIŽ NASTAVENO"
        notify_info(message, category="TMDB-HELP", time=5000, sound=True)
        return True
    except Exception as exc:
        xbmc.log(f"PLAY.ER :: TMDBHelper {task} selhalo: {type(exc).__name__}: {exc}", xbmc.LOGERROR)
        notify_error(str(exc), category="TMDB-HELP", time=7000, sound=True)
        return False
