# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_custom.py
# Author: Mau!X ER
# Created on: 24.04.2026
# Last edit on: 16.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re
import shutil


import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon


from resources.lib.utils_logging import log
from resources.lib.utils_notification import notify_ok
from resources.lib.utils_settings import get_setting_bool






ADDON = xbmcaddon.Addon(id='plugin.video.play_er')
SETTING_MAINTENANCE_TRIGGER = 'enable_auto_repair'


FOLDERS_TO_MANAGE =[
    'skin.arctic.fuse.3',
    'script.skinvariables',
    'plugin.video.themoviedb.helper',
    'plugin.video.play_er'
]






# ==========================================================
#  POMOCNÉ FUNKCE  ( PATCH FIXER  )
# ==========================================================
#
#
#
# def emergency_fix_corrupted_paths():
#
#     """
#     NOUZOVÁ OPRAVA: Projde živá data i zálohu a odstraní duplicitní 'special:special://'
#     """
#
#     paths_to_scan =[]
#
#     # Přidáme do skenu všechny živé addon_data složky
#     for folder in FOLDERS_TO_MANAGE:
#         paths_to_scan.append(xbmcvfs.translatePath(f'special://userdata/addon_data/{folder}'))
#
#     # Přidáme do skenu i složku se zálohou (pokud sis ji už stihl dojebat taky)
#     paths_to_scan.append(xbmcvfs.translatePath('special://home/addons/plugin.video.play_er/resources/custom/restore_skin'))
#
#     fixed_files = 0
#
#     for base_dir in paths_to_scan:
#         if not os.path.exists(base_dir):
#             continue
#
#         for root, dirs, files in os.walk(base_dir):
#             for file in files:
#                 if file.endswith(('.xml', '.json')):
#                     filepath = os.path.join(root, file)
#                     try:
#                         with open(filepath, 'r', encoding='utf-8') as f:
#                             content = f.read()
#
#                         # Pokud najdeme poškozený řetězec
#                         if 'special:special://' in content:
#                             # Využijeme Regex, aby to opravilo i kdyby tam bylo special:special:special://
#                             new_content = re.sub(r'(special:)+special://', r'special://', content)
#
#                             with open(filepath, 'w', encoding='utf-8') as f:
#                                 f.write(new_content)
#
#                             fixed_files += 1
#                             log(f"SYSTEM :: UTILS - NOUZOVA OPRAVA CESTY V: {file}", xbmc.LOGINFO)
#                     except Exception as e:
#                         pass
#
#     if fixed_files > 0:
#         log(f"SYSTEM :: UTILS - USPESNE OPRAVENO {fixed_files} DOJEBANYCH SOUBORU!", xbmc.LOGINFO)



# ==========================================================
#  POMOCNÉ FUNKCE  ( KOPÍROVÁNÍ )
# ==========================================================



def _copy_file_if_missing(src_file, dst_file, label):

    """
    COPY :: COPY MISSING FILE ONLY
    -- Kopíruje konkrétní soubor pouze pokud chybí.
    """

    try:
        if not os.path.exists(src_file):
            return False
        if not os.path.exists(dst_file):
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            log(f"SYSTEM :: UTILS - {label} COPIED : {os.path.basename(src_file)}", xbmc.LOGINFO)
            return True
        return False
    except Exception as e:
        log(f"SYSTEM :: UTILS - {label} FILE ERROR : {e}", xbmc.LOGERROR)
        return False



def _copy_dir_missing_only(src, dst, label):

    """
    COPY :: MISSING ONLY DIR
    -- Prochází složku a kopíruje pouze chybějící soubory.
    """

    copied_any = False
    try:
        if not os.path.exists(src):
            return False
        os.makedirs(dst, exist_ok=True)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isfile(s) and not os.path.exists(d):
                try:
                    shutil.copy2(s, d)
                    copied_any = True
                except Exception:
                    pass
    except Exception as e:
        log(f"SYSTEM :: UTILS - {label} DIR ERROR : {e}", xbmc.LOGERROR)
    return copied_any



# ==========================================================
#  OBNOVA ZÁLOHY A ÚPRAVA CEST   SPECIAL://  ( RESTORE )
# ==========================================================



def _process_and_copy_file(src_file, dst_file, label, force_overwrite=False):

    """
    RESTORE :: FILE PROCESS & COPY
    -- Obnovuje soubory ze zálohy a inteligentně PŘEPISUJE cesty na  [  special://  ]
    """

    try:
        if os.path.exists(dst_file):
            if force_overwrite:
                os.remove(dst_file)
            else:
                return False

        os.makedirs(os.path.dirname(dst_file), exist_ok=True)

        # --- Kontrola, zda jde o textový soubor (xml, json) pro úpravu cest

        if src_file.endswith(('.xml', '.json')):
            with open(src_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # OPRAVENÝ REGEX:
            # --- Negativní lookbehind (?<![:/]) zaručí, že přeskočíme cokoliv, co už
            #     v sobě má protokol (např. special://). Zabrání to vzniku special:special://.
            #     Bere absolutní Linux (/home/...) i Windows (C:\...) cesty a mění je.

            content = re.sub(
                r'(?<![:/])(?:/[^<>"\']*?|[a-zA-Z]:\\[^<>"\']*?)[/\\](addons|userdata)(?=[/\\"\']|$)',
                r'special://home/\1',
                content
            )

            # --- Volitelná oprava vícenásobných lomítek  ( častý problém TMDB )

            content = content.replace('//resources', '/resources')
            content = content.replace('//players', '/players')

            with open(dst_file, 'w', encoding='utf-8') as f:
                f.write(content)

            log(f"SYSTEM :: UTILS - {label} PARSED & RESTORED: {os.path.basename(src_file)}", xbmc.LOGINFO)
            return True
        else:

            # --- Obrázky a další binární soubory pouze překopíruje

            shutil.copy2(src_file, dst_file)
            return True

    except Exception as e:
        log(f"SYSTEM :: UTILS - {label} FILE ERROR : {e}", xbmc.LOGERROR)
        return False



def install_skin_backup(force_overwrite=False):

    """
    SKIN :: BACKUP
    -- Rekurzivně obnoví nastavení addonů z uložené zálohy.
    """

    repaired = False
    base = xbmcvfs.translatePath('special://home/addons/plugin.video.play_er')
    restore_base = os.path.join(base, 'resources/custom/restore_skin')

    if not os.path.exists(restore_base):
        return False

    for addon_id in FOLDERS_TO_MANAGE:
        src_addon_dir = os.path.join(restore_base, addon_id)
        dst_addon_dir = xbmcvfs.translatePath(f'special://userdata/addon_data/{addon_id}')

        if os.path.exists(src_addon_dir):
            for root, dirs, files in os.walk(src_addon_dir):
                rel_path = os.path.relpath(root, src_addon_dir)
                if rel_path == '.':
                    dst_root = dst_addon_dir
                else:
                    dst_root = os.path.join(dst_addon_dir, rel_path)

                for file in files:
                    src_file = os.path.join(root, file)
                    dst_file = os.path.join(dst_root, file)

                    if _process_and_copy_file(src_file, dst_file, f"RESTORE {addon_id.upper()}", force_overwrite=force_overwrite):
                        repaired = True

    return repaired


# ==========================================================
#  VYTVOŘENÍ NOVÉ ZÁLOHY  ( BACKUP )
# ==========================================================


def create_skin_backup():

    """
    SKIN :: BACKUP CREATE
    -- Zálohuje aktuální nastavení addonů přímo do addonu pro budoucí obnovu.
    """

    success_count = 0
    base_dest = xbmcvfs.translatePath('special://home/addons/plugin.video.play_er/resources/custom/restore_skin')

    os.makedirs(base_dest, exist_ok=True)

    for folder in FOLDERS_TO_MANAGE:
        src_dir = xbmcvfs.translatePath(f'special://userdata/addon_data/{folder}')
        dst_dir = os.path.join(base_dest, folder)

        if os.path.exists(src_dir):
            try:
                # Smazání staré zálohy, pokud už existuje
                if os.path.exists(dst_dir):
                    shutil.rmtree(dst_dir)

                # Ignorujeme cache soubory, aby záloha nenabobtnala
                shutil.copytree(
                    src_dir,
                    dst_dir,
                    ignore=shutil.ignore_patterns('__pycache__', '*.log', '*.db-journal', 'Thumbnails')
                )
                log(f"SYSTEM :: UTILS - BACKUP SUCCESS : {folder}", xbmc.LOGINFO)
                success_count += 1
            except Exception as e:
                log(f"SYSTEM :: UTILS - BACKUP ERROR '{folder}': {e}", xbmc.LOGERROR)
        else:
            log(f"SYSTEM :: UTILS - BACKUP SKIPPED (Not found) : {folder}", xbmc.LOGINFO)

    return success_count > 0



# ==========================================================
#  LOKÁLNÍ JEDNORÁZOVÉ OPRAVY A JAZYKY
# ==========================================================



def install_tmdb_helper_cz():
    base = xbmcvfs.translatePath('special://home/addons/plugin.video.play_er')
    src = os.path.join(base, 'resources/custom/tmdb_helper/resource.language.cs_cz')
    dst = xbmcvfs.translatePath('special://home/addons/plugin.video.themoviedb.helper/resources/language/resource.language.cs_cz')
    return _copy_dir_missing_only(src, dst, "TMDB HELPER CZ")

def install_arctic_fuse_cz():
    base = xbmcvfs.translatePath('special://home/addons/plugin.video.play_er')
    src = os.path.join(base, 'resources/custom/arctic_fuse/resource.language.cs_cz')
    dst = xbmcvfs.translatePath('special://home/addons/skin.arctic.fuse.3/language/resource.language.cs_cz')
    return _copy_dir_missing_only(src, dst, "ARCTIC FUSE 3 CZ")

def install_tmdb_players():
    base = xbmcvfs.translatePath('special://home/addons/plugin.video.play_er')
    src = os.path.join(base, 'resources/custom/players')
    dst = xbmcvfs.translatePath('special://userdata/addon_data/plugin.video.themoviedb.helper/players')
    return _copy_dir_missing_only(src, dst, "TMDB PLAYERS")



# ==========================================================
#  MAIN SYSTEM ENGINE (SPOUŠTĚNO PO STARTU)
# ==========================================================



def apply_custom_localizations():

    """
    APPLY :: CUSTOM LOCALIZATIONS
    -- Kontroluje a doplňuje chybějící soubory překladu pro TMDB Helper a Arctic Fuse 3.
    """

    try:

        # --- Zjištění, zda uživatel vyvolal v nastavení požadavek na Nástroj Údržby

        trigger_maintenance = ADDON.getSettingBool(SETTING_MAINTENANCE_TRIGGER)

        if trigger_maintenance:
            log("SYSTEM :: UTILS - MAINTENANCE TOOL TRIGGERED", xbmc.LOGINFO)

            dialog = xbmcgui.Dialog()

            # --- DIALOG - yesnocustom vrací : 2 pro CustomButton, 1 pro YesButton, 0 pro NoButton

            choice = dialog.yesnocustom(
                heading="[ FUCKING ]   KODI 22 PIERS  TOOLBOX",
                message="Vyberte požadovanou akci : \n\nNástroj slouží ke kompletnímu zálohování a obnově nastavení pluginů a vzhledu Arctic Fuse 3. \n\nInstaluje také CZ lokalizace addonů skinu ...",
                customlabel="ZÁLOHOVAT",
                yeslabel="OBNOVIT",
                nolabel="ZRUŠIT"
            )

            # --- AKCE : ZÁLOHOVAT DATABÁZI A NASTAVENÍ  ( CHOICE 2 )

            if choice == 2:
                if create_skin_backup():
                    dialog.ok(
                        "ZÁLOHA DOKONČENA",
                        "Kompletní nastavení bylo zabaleno a připraveno do složky addonu \n\n[B][  resources/custom/restore_skin  ][/B]."
                    )
                else:
                    dialog.ok("CHYBA ZÁLOHY", "Během zálohy došlo k chybě. Více informací v kodi.log")

            # --- AKCE : TVRDÁ OBNOVA ZE ZÁLOHY  ( CHOICE 1 )

            elif choice == 1:
                if install_skin_backup(force_overwrite=True):

                    # --- OPRAVENO: Nyní má dialog pouze 2 argumenty (Nadpis, Zpráva) a odřádkování přes \n

                    dialog.ok(
                        "OBNOVA DOKONČENA",
                        "Úspěšně nahrazeno ze zálohy ...\nAby se vše správně projevilo \n\n[B]MUSÍTE RESTARTOVAT KODI[/B]."
                    )
                else:
                    dialog.ok("CHYBA OBNOVY", "Nepodařilo se obnovit zálohu, zkontrolujte, zda záloha existuje.")

            # --- OKAMŽITÉ VYPNUTÍ PŘEPÍNAČE V NASTAVENÍ - aby proces neproběhl po dalším restartu znovu

            ADDON.setSettingBool(SETTING_MAINTENANCE_TRIGGER, False)

        else:

            # --- Normální tichý start - kontrola a doplnění chybějících souborů překladu a playerů

            repaired = False
            if get_setting_bool(ADDON, "startup_install_tmdb_cz", True) and install_tmdb_helper_cz(): repaired = True
            if get_setting_bool(ADDON, "startup_install_af3_cz", True) and install_arctic_fuse_cz(): repaired = True
            if get_setting_bool(ADDON, "startup_install_tmdb_players", True) and install_tmdb_players(): repaired = True

            if repaired:
                notify_ok(
                    "SYSTEM LOKALIZACE A MODULY OBNOVENY",
                    category="UTILS",
                    time=3000
                )

    except Exception as e:
        log(f"SYSTEM :: UTILS - PATCH/MAINTENANCE ERROR : {e}", xbmc.LOGERROR)




# def apply_custom_localizations():
# 
#     """
#     RESTORE :: CUSTOM LOCALIZATIONS
#     -- Kontroluje a doplňuje chybějící soubory překladu pro TMDB Helper a Arctic Fuse 3.
#     """
# 
#     try:
# 
#         # ---- NOUZOVÝ ČISTIČ  ( ODKOMENTOVAT FUNKCI NAHOŘE )  
#         #
#         # emergency_fix_corrupted_paths()
#         #
#         # --------------------------------------------------------------
# 
# 
#         # --- Zjištění, zda uživatel vyvolal v nastavení požadavek na Nástroj Údržby
# 
#         trigger_maintenance = ADDON.getSettingBool(SETTING_MAINTENANCE_TRIGGER)
# 
# 
#         if trigger_maintenance:
#             log("SYSTEM :: UTILS - MAINTENANCE TOOL TRIGGERED", xbmc.LOGINFO)
# 
#             dialog = xbmcgui.Dialog()
#             choice = dialog.yesnocustom(
#                 heading="[ FUCKING ]   KODI 22 PIERS  TOOLBOX",
#                 message="Nástroj slouží ke kompletnímu zálohování a obnově nastavení pluginů a vzhledu Arctic Fuse 3 a jeho součástí. Instaluje CZ lokalizace skinu Arctic Fuse 3 a TMDB Helper",
#                 customlabel="ZÁLOHOVAT",
#                 yeslabel="OBNOVIT",
#                 nolabel="ZRUŠIT"
#             )
# 
#             # --- AKCE : ZÁLOHOVAT DATABÁZI A NASTAVENÍ  ( CHOICE 2 )
# 
#             if choice == 2:
#                 if create_skin_backup():
#                     dialog.ok(
#                         "ZÁLOHA DOKONČENA",
#                         "Kompletní nastavení bylo zabaleno a připraveno do složky addonu [B]  [ resources/custom/restore_skin ][/B]"
#                     )
#                 else:
#                     dialog.ok("CHYBA ZÁLOHY", "Během zálohy došlo k chybě. Více informací v kodi.log")
# 
#             # --- AKCE : TVRDÁ OBNOVA ZE ZÁLOHY  ( CHOICE 1 )
# 
#             elif choice == 1:
#                 if install_skin_backup(force_overwrite=True):
#                     dialog.ok(
#                         "OBNOVA DOKONČENA",
#                         "Úspěšně nahrazeno ze zálohy.",
#                         "Aby se vše správně projevilo, [B] MUSÍTE RESTARTOVAT KODI [/B]."
#                     )
#                 else:
#                     dialog.ok("CHYBA OBNOVY", "Nepodařilo se obnovit zálohu, zkontrolujte, zda záloha existuje.")
# 
#             # --- OKAMŽITÉ VYPNUTÍ PŘEPÍNAČE V NASTAVENÍ - aby proces neproběhl po dalším restartu znovu
# 
#             ADDON.setSettingBool(SETTING_MAINTENANCE_TRIGGER, False)
# 
#         else:
#             # Normální tichý start - kontrola a doplnění chybějících souborů překladu (nikoliv tvrdý restore)
#             repaired = False
#             if install_tmdb_helper_cz(): repaired = True
#             if install_arctic_fuse_cz(): repaired = True
#             if install_tmdb_players(): repaired = True
# 
#             if repaired:
#                 notify_ok(
#                     "SYSTEM LOKALIZACE A MODULY OBNOVENY",
#                     category="UTILS",
#                     time=3000
#                 )
# 
#     except Exception as e:
#         log(f"SYSTEM :: UTILS - PATCH/MAINTENANCE ERROR : {e}", xbmc.LOGERROR)