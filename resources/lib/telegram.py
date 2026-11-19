# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: telegram.py
# Author: Mau!X ER
# Revised: ChatGPT
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re
import html
import uuid
import json
import socket
import requests

import xbmc
import xbmcvfs

# --- AUTO-INJECTED KODI 22 VFS PATCH ---
class SafeVFSFile:
    def __init__(self, *args, **kwargs):
        import xbmcvfs
        self.file_obj = xbmcvfs.File(*args, **kwargs)
    def __enter__(self):
        return self.file_obj
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.file_obj.close()
        return False
# ---------------------------------------



from resources.lib.utils_logging import log


from resources.lib.utils_theme import (
    Colors,
    Icons
)
from resources.lib.utils import safe_post



REQUEST_TIMEOUT = (5, 15)




def get_device_id():
    device_name = xbmc.getInfoLabel("System.FriendlyName")

    if device_name and device_name not in (
        "System.FriendlyName",
        "Kodi",
        "localhost"
    ):
        return device_name

    path = xbmcvfs.translatePath(
        "special://userdata/addon_data/plugin.video.play_er/DEVICE.ID"
    )

    try:
        if xbmcvfs.exists(path):
            with SafeVFSFile(path, "r") as f:
                val = f.read().strip()
                if val:
                    return val

        new_id = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"

        with SafeVFSFile(path, "w") as f:
            f.write(new_id)

        return new_id

    except Exception:
        return "Kodi-Device"




class TelegramManager:

    """
    CLASS :: TELEGRAM MANAGER
    -- Třída pro správu Telegram notifikací a odesílání zpráv, fotek a dokumentů.
    """


    def __init__(self, addon, log_func=None):
        self.addon = addon
        self.log = log_func or log


    def _token(self):
        return self.addon.getSettingString(
            "telegram_bot_token"
        ).strip()


    def _chat_id(self):
        return self.addon.getSettingString(
            "telegram_chat_id"
        ).strip()


    def _enabled(self):
        return self.addon.getSettingBool(
            "enable_telegram_notifications"
        )


    def _telegram_url(self, method):
        return f"https://api.telegram.org/bot{self._token()}/{method}"


    def _escape(self, value):
        if value is None:
            return ""
        return html.escape(str(value), quote=False)


    def _post(self, method, data=None, files=None, timeout=REQUEST_TIMEOUT, retry=2):
        url = self._telegram_url(method)

        r = safe_post(url, data=data, files=files, timeout=timeout, retry=retry)
        if r is None:
            raise Exception("Telegram POST failed")
        if not r.ok:
            try:
                result = r.json()
            except Exception:
                result = {}
            description = result.get("description") or getattr(r, "reason", "HTTP error")
            error_code = result.get("error_code")
            code_text = f" ({error_code})" if error_code else ""
            raise RuntimeError(
                f"Telegram {method} odmítl požadavek: HTTP {r.status_code}{code_text}: {description}"
            )
        return r


    def _check_ready(self):
        return (
            self._enabled() and
            self._token() and
            self._chat_id()
        )


    def _read_binary(self, path):
        local_path = xbmcvfs.translatePath(path)
        if local_path and os.path.isfile(local_path):
            with open(local_path, "rb") as f:
                data = f.read()
        else:
            with SafeVFSFile(path, "rb") as f:
                data = f.readBytes()

        if not data:
            raise ValueError(f"Soubor je prázdný nebo jej nelze přečíst: {os.path.basename(path)}")
        return data

    # ------------------------------------------------------------------
    #  BASIC SEND
    # ------------------------------------------------------------------

    def send_message(self, message, photo_url=None):
        if not self._check_ready():
            return False

        try:
            if photo_url:
                payload = {
                    "chat_id": self._chat_id(),
                    "photo": photo_url,
                    "caption": message,
                    "parse_mode": "HTML"
                }
                self._post("sendPhoto", data=payload)

            else:
                payload = {
                    "chat_id": self._chat_id(),
                    "text": message,
                    "parse_mode": "HTML"
                }
                self._post("sendMessage", data=payload)

            self.log(
                "UTILS : TELEGRAM - Zpráva úspěšně odeslána",
                xbmc.LOGINFO
            )
            return True

        except Exception as e:
            self.log(
                f"UTILS : TELEGRAM - Chyba při odesílání : {e}",
                xbmc.LOGERROR
            )
            return False

    # ------------------------------------------------------------------
    # BACKUP FILE
    # ------------------------------------------------------------------

    def send_backup(
        self,
        file_path,
        caption="Záloha souboru",
        thumb_path=None
    ):
        if not self._check_ready():
            return False

        if not file_path or not xbmcvfs.exists(file_path):
            return False

        files = {}

        try:
            files["document"] = (
                os.path.basename(file_path),
                self._read_binary(file_path)
            )

            if thumb_path and xbmcvfs.exists(thumb_path):
                files["thumb"] = (
                    os.path.basename(thumb_path),
                    self._read_binary(thumb_path)
                )

            payload = {
                "chat_id": self._chat_id(),
                "caption": caption,
                "parse_mode": "HTML"
            }

            response = self._post(
                "sendDocument",
                data=payload,
                files=files,
                timeout=(10, 180),
                retry=0
            )
            result = response.json()
            if not result.get("ok"):
                raise RuntimeError(result.get("description") or "Telegram upload failed")

            return True

        except Exception as e:
            self.log(
                f"UTILS : TELEGRAM - Výjimka při odesílání zálohy : {e}",
                xbmc.LOGERROR
            )
            return False

    # ------------------------------------------------------------------
    # XML SETTINGS READ
    # ------------------------------------------------------------------

    def _get_val(self, path, setting_id):
        import xml.etree.ElementTree as ET

        try:
            if not xbmcvfs.exists(path):
                return "Nenalezeno"

            with SafeVFSFile(path, "r") as f:
                xml_text = f.read()

            root = ET.fromstring(xml_text)

            for node in root.findall("setting"):
                if node.get("id") == setting_id:
                    return node.text if node.text else "---"

        except Exception:
            pass

        return "N/A"

    # ------------------------------------------------------------------
    # ACCOUNT REPORT
    # ------------------------------------------------------------------

    def send_account_report(self, photo_path=None):
        if not self._check_ready():
            return False

        p_xml = xbmcvfs.translatePath(
            "special://userdata/addon_data/plugin.video.play_er/settings.xml"
        )

        def val(key):
            return self._escape(self._get_val(p_xml, key))


        msg = (
            "<code>-----------------------------------</code>\n"
            "<b>💎  JUDENRAMPE  ::  ACCOUNT REPORTER  </b>\n"
            "<code>-----------------------------------</code>\n\n"
            f"<b>DATABASE   : </b> <code>{val('db_name')}</code>\n"
            f"<b>USERNAME  : </b> <code>{val('db_user')}</code>\n"
            f"<b>PASSWORD  : </b> <code>{val('db_pass')}</code>\n"
            f"<b>IP ADDR  : </b> <code>{val('db_host')}</code>\n"
            f"<b>IP PORT  : </b> <code>{val('db_port')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b>🎬 ACCOUNT  ::  WEBSHARE.CZ           </b>\n\n"
            f"<b>USER : </b> <code>{val('webshare_username')}</code>\n"
            f"<b>PASS : </b> <code>{val('webshare_password')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b>🎬 ACCOUNT  ::  PREHRAJ.TO            </b>\n\n"
            f"<b>USER : </b> <code>{val('email')}</code>\n"
            f"<b>PASS : </b> <code>{val('password')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b>🎬 ACCOUNT  ::  TELEGRAM.ORG            </b>\n\n"
            f"<b>CHAT ID  : </b>\n<code>{val('telegram_chat_id')}</code>\n\n"
            f"<b>BOT TOKEN  : </b>\n<code>{val('telegram_bot_token')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b>🎬 ACCOUNT  ::  TRAKT.TV                </b>\n\n"
            f"<b>CLIENT ID  : </b>\n<code>{val('trakt_client_id')}</code>\n\n"
            f"<b>CLIENT SECRET  : </b>\n<code>{val('trakt_client_secret')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b>🔑 API-KEYS  ::  PLAY.ER               </b>\n\n"
            f"<b>TMDB API  : </b>\n<code>{val('api_key')}</code>\n\n"
            f"<b>GEMINI API  : </b>\n<code>{val('gemini_api_key')}</code>\n\n"
            f"<b>OPENROUTER API  : </b>\n<code>{val('openrouter_api_key')}</code>\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<b> SENT FROM YOUR    [ FUCKING ]    PLAY.ER</b>"
        )

        try:
            if photo_path and xbmcvfs.exists(photo_path):
                payload = {
                    "chat_id": self._chat_id(),
                    "caption": msg,
                    "parse_mode": "HTML"
                }

                files = {
                    "photo": (
                        "ACCOUNT.png",
                        self._read_binary(photo_path)
                    )
                }

                self._post(
                    "sendPhoto",
                    data=payload,
                    files=files
                )

            else:
                self.send_message(msg)

            return True

        except Exception as e:
            self.log(
                f"TELEGRAM REPORT ERROR : {e}",
                xbmc.LOGERROR
            )
            return False

    # ------------------------------------------------------------------
    # TMDB AUTH
    # ------------------------------------------------------------------

    def send_tmdb_auth_url(self, auth_url, photo_path=None):
        if not self._check_ready():
            return False

        msg = (
            "<code>-----------------------------------</code>\n"
            "<b>🎬  JUDENRAMPE  ::  AUTHENTICATION    </b>\n"
            "<code>-----------------------------------</code>\n\n"
            "<b>🔗 AUTHENTICATION URL  :              </b>\n\n"
            f"<code>{self._escape(auth_url)}</code>\n\n"

            "<b>📋 LOGIN INSTRUKCE  :                 </b>\n\n"
            "1. Otevři odkaz v prohlížeči.\n"
            "2. Přihlas se ke svému TMDB účtu.\n"
            "3. Potvrď přístup aplikaci.\n"
            "4. Vrať se do Kodi.\n\n"

            "<code>-----------------------------------</code>\n\n"
            "<i> SENT FROM YOUR    [ FUCKING ]    PLAY.ER</i>"
        )

        try:
            if photo_path and xbmcvfs.exists(photo_path):
                payload = {
                    "chat_id": self._chat_id(),
                    "caption": msg,
                    "parse_mode": "HTML"
                }

                files = {
                    "photo": (
                        "TMDB-AUTH.png",
                        self._read_binary(photo_path)
                    )
                }

                self._post(
                    "sendPhoto",
                    data=payload,
                    files=files
                )
            else:
                self.send_message(msg)

            return True

        except Exception as e:
            self.log(
                f"TELEGRAM TMDB AUTH ERROR : {e}",
                xbmc.LOGERROR
            )
            return False

    # ------------------------------------------------------------------
    # SHARE NOTIFICATION
    # ------------------------------------------------------------------

    def send_incoming_share_notification(self, item):
        title = item.get("title", "Neznámé")
        year = item.get("year", "")
        sender = item.get("sender_id", "Neznámý uživatel")
        plot = item.get("plot", "")
        poster = item.get("poster")

        plot = re.sub(
            r'\[/?(?:color|b|i|uppercase|lowercase|light).*?\]',
            '',
            plot,
            flags=re.IGNORECASE
        )

        title = self._escape(title)
        sender = self._escape(sender)
        plot = self._escape(plot)

        if len(plot) > 750:
            plot = plot[:747] + "..."

        msg = (
            "<code>----------------------------------</code>\n"
            "<b>🎬  JUDENRAMPE  :  INCOMMING SHARE   </b>\n"
            "<code>----------------------------------</code>\n\n"
            f"👤  <b>SDÍLEL UŽIVATEL  == </b> <code>{sender}</code>\n\n"
            f"<b>{title}   ({year})</b>\n\n"
            f"{plot}\n\n"
            "<code>----------------------------------</code>\n\n"
            "<i> SENT FROM YOUR    [ FUCKING ]    PLAY.ER</i>"
        )

        return self.send_message(
            msg,
            photo_url=poster
        )
