# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: play_mail.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 20.05.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os
import re
import csv
import time
import requests

import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon


from datetime import datetime


from resources.lib.utils_logging import log


from resources.lib.utils_notification import (
    notify_error,
    notify_info,
    notify_ok
)







class PlayMail:

    """
    CLASS :: PLAY MAIL
    -- Automatická registrace, verifikace e-mailu a login účtu PREHRAJ.TO
    """

    def __init__(self, addon=None):
        self.addon = addon or xbmcaddon.Addon()
        self.addon_name = self.addon.getAddonInfo("id")
        self.profile_path = xbmcvfs.translatePath(
            f"special://profile/addon_data/{self.addon_name}/"
        )

        if not xbmcvfs.exists(self.profile_path):
            xbmcvfs.mkdirs(self.profile_path)

        self.guerrilla_api = "https://api.guerrillamail.com/ajax.php"
        self.reg_url = "https://prehraj.to/registrace"
        self.reg_action = "https://prehraj.to/registrace?frm=registration-registrationForm"

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.9",
        })

        self.email = None
        self.password = "PLAYER123!"
        self.guerrilla_sid_token = None






    def _setup_temp_email(self):
        log("[ PLAY.MAIL ] Připravuji dočasný email přes GuerrillaMail API ...")
        try:
            resp = self.session.get(f"{self.guerrilla_api}?f=get_email_address", timeout=15)
            if resp.status_code != 200:
                log(f"[ PLAY.MAIL ] Chyba připojení k mail API : {resp.status_code}", xbmc.LOGERROR)
                return False

            data = resp.json()
            self.email = data.get("email_addr")
            self.guerrilla_sid_token = data.get("sid_token")

            if not self.email or not self.guerrilla_sid_token:
                log("[ PLAY.MAIL ] API nevrátilo email nebo sid_token.", xbmc.LOGERROR)
                return False

            log(f"[ PLAY.MAIL ] E-mail vygenerován : {self.email}")
            return True

        except Exception as e:
            log(f"[ PLAY.MAIL ] Neočekávaná chyba při přípravě emailu : {e}", xbmc.LOGERROR)
            return False



    def _register_prehrajto(self):
        log("[ PLAY.MAIL ] Registrace účtu na prehraj.to ...")

        try:
            self.session.get(self.reg_url, timeout=10)
        except:
            pass

        payload = {
            "email": self.email,
            "password": self.password,
            "check_password": self.password,
            "accept_terms": "on",
            "_do": "registration-registrationForm-submit",
        }

        self.session.headers.update({
            "Referer": self.reg_url,
            "Origin": "https://prehraj.to"
        })

        try:
            reg_resp = self.session.post(
                self.reg_action,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15
            )

            if reg_resp.status_code == 200:
                log("[ PLAY.MAIL ] Registrační požadavek (formulář) úspěšně odeslán.")
                return True
            else:
                log(f"[ PLAY.MAIL ] Registrace selhala, návratový kód : {reg_resp.status_code}", xbmc.LOGWARNING)
                return False

        except Exception as e:
            log(f"[ PLAY.MAIL ] Chyba při odesílání registrace : {e}", xbmc.LOGERROR)
            return False



    def _wait_for_verification_email(self):
        log("[ PLAY.MAIL ] Čekám na verifikační e-mail od prehraj.to ...")

        seq = 0

        for attempt in range(1, 16):
            log(f"[ PLAY.MAIL ] Kontrola doručené pošty {attempt}/15 ...")

            try:
                resp = self.session.get(
                    f"{self.guerrilla_api}?f=check_email&seq={seq}&sid_token={self.guerrilla_sid_token}",
                    timeout=15
                )

                if resp.status_code == 200:
                    messages = resp.json().get("list", [])
                    for msg in messages:
                        subject = str(msg.get("mail_subject", "")).lower()
                        sender = str(msg.get("mail_from", "")).lower()
                        mail_id = msg.get("mail_id")

                        if "welcome" in subject or "guerrillamail" in sender or "temp mail" in subject:
                            continue

                        if "prehraj" in sender:
                            log(f"[ PLAY.MAIL ] E-mail dorazil od {msg.get('mail_from')}. Stahuji obsah ...")

                            msg_resp = self.session.get(
                                f"{self.guerrilla_api}?f=fetch_email&email_id={mail_id}&sid_token={self.guerrilla_sid_token}",
                                timeout=15
                            )

                            if msg_resp.status_code == 200:
                                content = msg_resp.json().get("mail_body", "")
                                match = re.search(r'(https://prehrajto\.cz/overeni-emailu/[^\s"\'<>]+)', content)
                                if not match:
                                    match = re.search(r'(https://(prehrajto\.cz|prehraj\.to)[^\s"\'<>]+)', content)

                                if match:
                                    link = match.group(1)
                                    log(f"[ PLAY.MAIL ] Nalezen aktivační odkaz: {link}")
                                    return link
                                else:
                                    log("[ PLAY.MAIL ] Aktivační odkaz nenalezen v obsahu zprávy!", xbmc.LOGERROR)
                                    return None

                    if messages:
                        seq = max([int(m.get("mail_id", seq)) for m in messages])
            except Exception as e:
                log(f"[ PLAY.MAIL ] Chyba při dotazování mail API : {e}", xbmc.LOGWARNING)

            xbmc.sleep(5000) # Kodi sleep

        log("[ PLAY.MAIL ] Čas vypršel, žádný e-mail nedorazil.", xbmc.LOGERROR)
        return None



    def _verify_email(self, activation_link):
        log("[ PLAY.MAIL ] Otevírám aktivační odkaz pro dokončení registrace ...")

        headers = {
            "Referer": "https://www.guerrillamail.com/",
            "Upgrade-Insecure-Requests": "1"
        }

        try:
            ver_resp = self.session.get(activation_link, headers=headers, timeout=15, allow_redirects=True)

            if ver_resp.status_code == 200:
                log("[ PLAY.MAIL ] Aktivační odkaz úspěšně navštíven  ( HTTP 200 ) . Účet by měl být aktivován.")

                csv_path = os.path.join(self.profile_path, "PLAY.MAIL--REGISTRATIONS.csv")
                with open(csv_path, "a", newline="", encoding="utf-8") as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow([
                        datetime.now().isoformat(),
                        self.email,
                        self.password,
                        "VERIFIED"
                    ])

                xbmc.sleep(3000)
                return True
            else:
                log(f"[ PLAY.MAIL ] Návštěva odkazu skončila chybou HTTP {ver_resp.status_code}", xbmc.LOGWARNING)
                return False

        except Exception as e:
            log(f"[ PLAY.MAIL ] Sítová chyba při návštěvě aktivačního odkazu : {e}", xbmc.LOGERROR)
            return False



    def register_account(self):

        """
        REGISTER :: ACCOUNT
        -- Spustí kompletní rutinu (generování mailu -> formulář -> vyčkání na link -> aktivace).
        -- Vrací (email, heslo) v případě úspěchu, jinak (None, None).
        """

        try:
            notify_info("PREHRAJ.TO Generuji dočasný účet ...", category="ACCOUNT", time=3000)

            if not self._setup_temp_email():
                notify_error("PREHRAJ.TO Nepodařilo se vytvořit e-mail.", category="ACCOUNT")
                return None, None

            if not self._register_prehrajto():
                notify_error("PREHRAJ.TO Registrace ( formulář ) selhala.", category="ACCOUNT")
                return None, None

            notify_info("PREHRAJ.TO Čekám na verifikační e-mail ...", category="ACCOUNT", time=10000)

            activation_link = self._wait_for_verification_email()
            if not activation_link:
                notify_error("PREHRAJ.TO Verifikační e-mail nedorazil.", category="ACCOUNT")
                return None, None

            notify_info("PREHRAJ.TO Ověřuji nově vytvořený účet ...", category="ACCOUNT", time=4000)

            if not self._verify_email(activation_link):
                notify_error("PREHRAJ.TO Selhalo ověření přes aktivační odkaz.", category="ACCOUNT")
                return None, None

            notify_ok(f"PREHRAJ.TO ÚČET VYTVOŘEN : {self.email}", category="ACCOUNT", time=5000)
            log(f"[ PLAY.MAIL ] Kompletní procedura úspěšná. Účet {self.email} je připraven na 30 dní!")

            return self.email, self.password

        except Exception as e:
            log(f"[ PLAY.MAIL ] KRITICKÁ CHYBA : {e}", xbmc.LOGERROR)
            notify_error(f"PREHRAJ.TO Kritická chyba : {e}", category="ACCOUNT")
            return None, None
