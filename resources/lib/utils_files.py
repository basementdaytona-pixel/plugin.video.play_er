# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_files.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 16.10.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import traceback

import xbmc
import xbmcvfs


from resources.lib.utils_logging import log





class SafeVFSFile:

    """
    CLASS :: SAFE VFS FILE
    -- Bezpečný kontextový správce pro xbmcvfs.File chránící prostředky.
    """

    def __init__(self, path, mode="r"):
        self.path = path
        self.mode = mode
        self.file_obj = xbmcvfs.File(path, mode)

    def __enter__(self):
        return self.file_obj

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.file_obj.close()
        except Exception:
            pass
        return False


def ensure_dir(path):
    if not path:
        log("FILES - WARNING : Attempted to ensure_dir with empty path", xbmc.LOGWARNING)
        return False
    if xbmcvfs.exists(path):
        return True

    vfs_success = False
    os_success = False
    vfs_error = None
    os_error = None

    try:
        if xbmcvfs.mkdirs(path):
            log(f"FILES - Created missing folder via VFS : {path}", xbmc.LOGDEBUG)
            vfs_success = True
        else:
            vfs_error = RuntimeError(f"VFS mkdirs returned false for {path}")
    except Exception as e_vfs:
        vfs_error = e_vfs

    if not vfs_success:
        try:
            local_path = xbmcvfs.translatePath(path)
            if local_path:
                os.makedirs(local_path, exist_ok=True)
                if os.path.exists(local_path):
                    log(f"FILES - Created missing folder via OS : {local_path}", xbmc.LOGDEBUG)
                    os_success = True
                else:
                    os_error = RuntimeError("os.makedirs succeeded but path still doesn't exist")
            else:
                os_error = ValueError("Translated path is empty")
        except Exception as e_os:
            os_error = e_os

    if not vfs_success and not os_success:
        log(f"FILES - FAILED to create folder : {path} -> VFS Error: {vfs_error} / OS Error: {os_error}\n{traceback.format_exc()}", xbmc.LOGERROR)
        return False
    return True


def ensure_file(path):
    if not path:
        log("FILES - WARNING : Attempted to ensure_file with empty path", xbmc.LOGWARNING)
        return False
    if xbmcvfs.exists(path):
        return True

    parent_dir = os.path.dirname(path)
    if not parent_dir or not ensure_dir(parent_dir):
        log(f"FILES - Cannot create file because parent directory failed : {parent_dir}", xbmc.LOGERROR)
        return False

    try:
        with SafeVFSFile(path, "w") as handle:
            pass
        log(f"FILES - Created missing file via VFS : {path}", xbmc.LOGDEBUG)
        return True
    except Exception as e_vfs:
        log(f"FILES - VFS FAILED to create file : {path} -> {e_vfs}", xbmc.LOGWARNING)
        try:
            local_path = xbmcvfs.translatePath(path)
            if local_path:
                with open(local_path, "a"):
                    pass
                log(f"FILES - Created missing file via OS : {local_path}", xbmc.LOGDEBUG)
                return True
        except Exception as e_os:
            log(f"FILES - FAILED to create file : {path} -> {e_os}\n{traceback.format_exc()}", xbmc.LOGERROR)
    return False
