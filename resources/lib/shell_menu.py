# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: shell_menu.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import json
import datetime
import threading
import subprocess

import xbmc
import xbmcgui
import xbmcvfs


from resources.lib.utils_theme import (
    Colors,
    Icons
)




SCRIPTS_DIR = xbmcvfs.translatePath("special://userdata/PLAY-DATA/SHELL-LAUNCHER")
MENU_FILE_YAML = os.path.join(SCRIPTS_DIR, "MENU.YAML")
MENU_FILE_JSON = os.path.join(SCRIPTS_DIR, "MENU.JSON")
LOG_FILE = xbmcvfs.translatePath("special://userdata/PLAY-DATA/SHELL-LAUNCHER/SHELL.LOG")





class ShellMenu:

    @staticmethod

    def show_shell_menu():

        """
        SCRIPTS :: SHOW MENU
        -- Show combined menu ( menu.yaml/json + auto-detected scripts ).
        -- Fixes duplicates by normalizing paths.
        """

        _ensure_scripts_dir()
        items = _read_menu_from_yaml_or_json()

        for it in items:
            cmd = it.get("cmd")
            if cmd and not os.path.isabs(cmd):
                it["cmd"] = os.path.join(SCRIPTS_DIR, cmd)

        auto_items = _collect_scripts_from_dir()

        known_cmds = {it.get("cmd") for it in items if it.get("cmd")}
        for a in auto_items:
            if a.get("cmd") not in known_cmds:
                items.append(a)

        if not items:
            create_example_scripts()
            items = _read_menu_from_yaml_or_json()
            for it in items:
                cmd = it.get("cmd")
                if cmd and not os.path.isabs(cmd):
                    it["cmd"] = os.path.join(SCRIPTS_DIR, cmd)

            items = _collect_scripts_from_dir()
            known_cmds = {it.get("cmd") for it in items if it.get("cmd")}
            for a in auto_items:
                if a.get("cmd") not in known_cmds:
                    items.append(a)

            if not items:
                if xbmcgui:
                    xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]○  SHELL SCRIPT LAUNCHER  ○[/COLOR][/B]",
                                        f"Adresář skriptů je prázdný: {SCRIPTS_DIR}\nŠablony vytvořeny, zkontroluj práva")
                _kodi_log("Menu je prázdné i po vytvoření šablon", xbmc.LOGWARNING if xbmc else None)
                return

        labels = [f"{it.get('label')} - {it.get('desc','')}" for it in items]

        try:
            if not xbmcgui:
                print("DEBUG: menu items:", labels)
                return
            idx = xbmcgui.Dialog().select(f"[B][COLOR {Colors.ORANGE}]○  SHELL SCRIPT LAUNCHER  ○[/COLOR][/B]", labels)
            if idx == -1: return
            selected = items[idx]
            _handle_menu_item(selected)
        except Exception as e:
            _kodi_log(f"ERROR - show_shell_menu : {e}", xbmc.LOGERROR if xbmc else None)


def _kodi_log(msg: str, level=None):

    """
    SCRIPTS :: KODI LOGGER
    -- Safe logger – funguje i mimo Kodi.
    """

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"SHELL.TO :: {ts} - {msg}"

    if xbmc:
        try:
            xbmc.log(line, level if level else xbmc.LOGINFO)
        except Exception:
            pass

    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_flatpak():
    return os.path.exists("/.flatpak-info")


def _ensure_scripts_dir():

    """
    SCRIPTS :: CREATE DIRECTORY
    -- Create /home/mauix/.var/app/tv.kodi.Kodi/data/userdata/SHELL-LAUNCHER and ensure permissions.
    """

    try:
        os.makedirs(SCRIPTS_DIR, exist_ok=True)

        for name in os.listdir(SCRIPTS_DIR):
            path = os.path.join(SCRIPTS_DIR, name)
            if os.path.isfile(path) and (path.endswith(".sh") or path.endswith(".py")):
                try:
                    os.chmod(path, 0o755)
                except Exception as e:
                    _kodi_log(f"CHMOD selhal pro {name} : {e}", xbmc.LOGERROR)
    except Exception as e:
        _kodi_log(
            f"Nemohu vytvořit scripts dir {SCRIPTS_DIR}: {e}",
            xbmc.LOGERROR if xbmc else None
        )


def _read_menu_from_yaml_or_json():

    """
    SCRIPTS :: READ MNEU
    -- Read menu items from file.
    """

    items = []

    try:
        if os.path.exists(MENU_FILE_YAML):
            try:
                import yaml
                with open(MENU_FILE_YAML, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or []
                    if isinstance(data, list):
                        items = data
            except Exception as e:
                _kodi_log(f"YAML parse failed : {e}", xbmc.LOGWARNING if xbmc else None)
        if not items and os.path.exists(MENU_FILE_JSON):
            with open(MENU_FILE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f) or []
                if isinstance(data, list):
                    items = data
    except Exception as e:
        _kodi_log(f"Error reading menu files : {e}", xbmc.LOGERROR if xbmc else None)
    return items


def _collect_scripts_from_dir():

    """
    SCRIPTS :: COLLECTOR
    -- Collect scripts from directory.
    """

    _ensure_scripts_dir()
    menu = []
    try:
        for entry in sorted(os.listdir(SCRIPTS_DIR)):
            full = os.path.join(SCRIPTS_DIR, entry)
            if os.path.isfile(full):

                ext = os.path.splitext(entry)[1].lower()
                is_exec = os.access(full, os.X_OK)
                if ext in (".sh", ".py") or is_exec:
                    menu.append({
                        "label": entry,
                        "desc": f"Script: {entry}",
                        "cmd": full,
                        "confirm": False,
                        "background": False,
                        "timeout": 120
                    })
    except Exception as e:
        _kodi_log(f"Error scanning scripts dir : {e}", xbmc.LOGERROR if xbmc else None)
    return menu


def open_script_folder():

    """
    SCRIPTS :: CONVENIENCE
    -- Ensure scripts dir exists and create examples, then show notification.
    """

    _ensure_scripts_dir()
    create_example_scripts()
    msg = f"Skripty : {SCRIPTS_DIR}"
    try:
        if xbmcgui:
            from resources.lib.utils_notification import notify_info
            notify_info(msg, category="○ SHELL SCRIPT LAUNCHER ○", time=2500, sound=True)
    except Exception:
        _kodi_log(msg, xbmc.LOGINFO if xbmc else None)


def run_script(path: str | None):

    """
    SCRIPTS :: DIRECTORY
    -- Public entry to run a script by absolute path.
    """

    if not path:
        _kodi_log("ERROR run_script called without path", xbmc.LOGERROR if xbmc else None)
        if xbmcgui:
            xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]○  SHELL SCRIPT LAUNCHER  ○[/COLOR][/B]", "Chyba : nebyla zadána cesta ke skriptu")
        return
    if not os.path.isabs(path):

        path = os.path.join(SCRIPTS_DIR, path)
    if not os.path.exists(path):
        if xbmcgui:
            xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]○  SHELL SCRIPT LAUNCHER  ○[/COLOR][/B]", f"Skript nenalezen : \n{path}")
        _kodi_log(f"ERROR run_script - not found : {path}", xbmc.LOGERROR if xbmc else None)
        return

    _execute_and_show_output(path, background=False, timeout=300)


def _handle_menu_item(item: dict):

    """
    HANDLER :: INTERNAL
    """

    cmd = item.get("cmd")
    label = item.get("label") or os.path.basename(cmd or "")
    confirm = item.get("confirm", False)
    background = item.get("background", False)
    timeout = item.get("timeout", 120)

    if not cmd:
        if xbmcgui:
            xbmcgui.Dialog().ok(f"[B][COLOR {Colors.ORANGE}]○  SHELL SCRIPT LAUNCHER  ○[/COLOR][/B]", "WARNING : Vybraná položka nemá příkaz")
        return

    if not os.path.isabs(cmd):
        cmd = os.path.join(SCRIPTS_DIR, cmd)

    if confirm:
        if xbmcgui and not xbmcgui.Dialog().yesno("POTVRDIT", f"OPRAVDU SPUSTIT?\n\n{label}"):
            return

    ext = os.path.splitext(cmd)[1].lower()
    if ext == ".py":
        run_cmd = cmd if os.access(cmd, os.X_OK) else f"python3 \"{cmd}\""
    else:
        run_cmd = cmd

    if is_flatpak():
        _kodi_log(f"Flatpak detected. Running on host: {run_cmd}")
        run_cmd = f"flatpak-spawn --host {run_cmd}"

    _execute_and_show_output(run_cmd, background=background, timeout=timeout, label=label)


def _execute_and_show_output(cmd, background=False, timeout=120, label=None):

    """
    COMMAND :: EXECUTOR
    -- Background=True -> spawn and return immediately.
    -- Background=False -> run, capture output, show in textviewer at the end.
    -- No busy dialogs, no blocking Kodi GUI.
    """

    _kodi_log(f"Spouštím : {cmd} background={background}", xbmc.LOGINFO if xbmc else None)

    if background:
        try:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _kodi_log(f"Spawned background : {cmd}")
        except Exception as e:
            _kodi_log(f"Background spawn failed : {e}", xbmc.LOGERROR if xbmc else None)
        return

    def _worker():
        out = ""
        code = None
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            out = (proc.stdout or "") + ("\nERR:\n" + proc.stderr if proc.stderr else "")
            code = proc.returncode
            _kodi_log(f"Command finished : exit={code}")
        except subprocess.TimeoutExpired:
            out = f"ERROR : Timeout after {timeout}s"
            code = -1
            _kodi_log(out, xbmc.LOGERROR if xbmc else None)
        except Exception as e:
            out = f"ERROR : {e}"
            code = -2
            _kodi_log(f"Run error : {e}", xbmc.LOGERROR if xbmc else None)

        try:
            safe_out = out or "( žádný výstup )"
            safe_out = safe_out.strip()
            title = f"{label or 'Script'} (exit {code})"
            if xbmcgui:
                xbmcgui.Dialog().textviewer(title, safe_out)
            else:
                print("--- OUTPUT ---")
                print(title)
                print(safe_out)
        except Exception as e:
            _kodi_log(f"Show output failed : {e}", xbmc.LOGERROR if xbmc else None)

    threading.Thread(target=_worker, daemon=True).start()


def create_example_scripts():

    """
    DEFAULT :: SCRIPTS_DIR
    -- debug_addon.sh : quick dump (ls, df, env)
    -- check_settings.py : parse settings.xml in addon dir and report missing/invalid entries
    -- check_router.py : static check for _create_actions_map presence and counts, and try import of mapped modules
    -- check_permissions.sh : print permission bits for addon files
    """

    _ensure_scripts_dir()

    examples = {


        "debug_addon.sh": """#!/bin/sh

echo "#######################################"
echo "# [ FUCKING DEBUG ADDON SCRIPT ] #"
echo "#######################################"

echo "=== DATE ==="
date

echo "=== WHOAMI ==="
whoami 2>/dev/null || echo "unknown"

echo "=== UPTIME ==="
uptime 2>/dev/null || echo "no uptime"

echo "=== DISK ==="
df -h 2>/dev/null || echo "no df"

echo "=== ADDONS ==="
/bin/ls -la "$(dirname "$(readlink -f "$0")")" || ls -la .

echo "== ENV VARS =="
env | sort

""",


        "check_permissions.sh": """#!/bin/sh

SCRIPTS_DIR="{0}"
echo "Scripts dir: $SCRIPTS_DIR"
ls -ld "$SCRIPTS_DIR"
ls -l "$SCRIPTS_DIR"
echo "PERMISSIONS : Checking whether scripts are executable : "
for f in "$SCRIPTS_DIR"/*; do
  [ -e "$f" ] || continue
  printf "%%s - " "$f"
  if [ -x "$f" ]; then
    echo "DONE : Is executable"
  else
    echo "FAILED : NOT executable"
  fi
done
""".format(SCRIPTS_DIR),


        "check_settings.py": r'''#!/usr/bin/env python3

import os
import sys

from xml.etree import ElementTree as ET

def find_settings(addon_id="plugin.video.play_er"):

    possible = [
        os.path.expanduser("~/.kodi/addons/" + addon_id + "/resources"),
        "/usr/share/kodi/addons/" + addon_id + "/resources",
        os.path.expanduser("~/.var/app/tv.kodi.Kodi/data/addons/" + addon_id + "/resources"),
        os.path.join(os.path.dirname(__file__), "..", "..", "resources")
    ]

    for p in possible:
        settings = os.path.join(p, "settings.xml")
        if os.path.exists(settings):
            return settings
    return None

def main():
    settings = find_settings()
    if not settings:
        print("WARNING : File settings.xml not found in standard locations. Provide path as argument")
        return
    print("Using settings.xml:", settings)
    try:
        tree = ET.parse(settings)
        root = tree.getroot()
        entries = root.findall(".//setting")
        print("Found", len(entries), "setting entries.")
        missing = []
        for s in entries:
            sid = s.get("id")
            if sid is None or sid.strip()=="":
                missing.append(s)
        if missing:
            print("ERROR : Found settings elements without id attribute :", len(missing))
        else:
            print("DONE : All setting elements have id attribute")
    except Exception as e:
        print("ERROR : Parsing settings.xml :", e)

if __name__ == '__main__':
    main()
''',


        "check_router.py": r'''#!/usr/bin/env python3

import os
import re
import sys

addon_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
candidates = [
    "resources/lib/plugin.py",
    "plugin.py",
    os.path.join("resources", "lib", "plugin.py")
]

found = None

for c in candidates:
    path = os.path.join(addon_root, c)
    if os.path.exists(path):
        found = path
        break

if not found:
    if os.path.exists(addon_root):
        for root, dirs, files in os.walk(addon_root):
            if "plugin.py" in files and "resources" in root:
                found = os.path.join(root, "plugin.py")
                break

if not found:
    print("plugin.py not found.")
    sys.exit(2)

print("Using plugin file:", found)
text = open(found, "r", encoding="utf-8", errors="ignore").read()
m = re.search(r"def\s+_create_actions_map\s*\(\s*\)\s*:\s*(?:\"\"\".*?\"\"\"\s*)?return\s*{", text, re.S)

if not m:
    print("WARNING : Could not find _create_actions_map definition")
    sys.exit(1)

start = text.find("def _create_actions_map")
start_return = text.find("return", start)
brace = text.find("{", start_return)

if brace==-1:
    print("WARNING : No dict literal returned found after return")
    sys.exit(1)

idx = brace
stack = []
while idx < len(text):
    ch = text[idx]
    if ch == "{":
        stack.append("{")
    elif ch == "}":
        stack.pop()
        if not stack:
            end = idx
            break
    idx += 1
else:
    print("Could not find matching closing brace for actions map")
    sys.exit(1)

map_text = text[brace:end+1]
keys = re.findall(r'["\']([a-zA-Z0-9_\-]+)["\']\s*:', map_text)
unique_keys = sorted(set(keys))
print("Detected actions in map:", len(unique_keys))

for k in unique_keys:
    print(" -", k)

print("! HINT : Run plugin in debug mode and check Kodi log for ModuleNotFound errors !")
'''
    }

    for fn, content in examples.items():
        path = os.path.join(SCRIPTS_DIR, fn)
        try:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                try:
                    os.chmod(path, 0o755)
                except Exception:
                    pass
                _kodi_log(f"Vytvořen example script : {path}")
            else:
                _kodi_log(f"Example script exists : {path}")
        except Exception as e:
            _kodi_log(f"Nelze vytvořit example script {path} : {e}", xbmc.LOGERROR if xbmc else None)

    if not os.path.exists(MENU_FILE_YAML):
        try:
            with open(MENU_FILE_YAML, "w", encoding="utf-8") as f:
                f.write(


"""

- label: "DEBUG ADDON"
  desc: "Spustí debug a vypíše výstup"
  cmd: "debug_addon.sh"
  confirm: true
  background: false
  timeout: 30

- label: "CHECK SETTINGS"
  desc: "Provede kontrolu settings.xml"
  cmd: "check_settings.py"
  confirm: true
  background: false
  timeout: 20

- label: "CHECK ROUTER MAP"
  desc: "Kontroluje _create_actions_map"
  cmd: "check_router.py"
  confirm: true
  background: false
  timeout: 30

- label: "CHECK PERMISSIONS"
  desc: "Kontroluje oprávnění souborů"
  cmd: "check_permissions.sh"
  confirm: true
  background: false
  timeout: 30

""")


            _kodi_log(f"Vytvořen  [ MENU.YAML ] : {MENU_FILE_YAML}")
        except Exception as e:
            _kodi_log(f"Nelze vytvořit  [ MENU.YAML ] : {e}", xbmc.LOGERROR if xbmc else None)