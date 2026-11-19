# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: dialog_metrics.py
# Author: Mau!X ER
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import sys
import time

import xbmc
import xbmcgui
import xbmcaddon


from resources.lib.monitor_orchestrator import get_orchestrator
from resources.lib.metrics_manager import METRICS
from resources.lib.utils_logging import log
from resources.lib.utils import safe_get
from resources.lib import cache_manager


from resources.lib.utils_notification import (
    notify_error
)

from resources.lib.utils_theme import (
    Colors,
    Icons
)





try:
    ADDON = xbmcaddon.Addon("plugin.video.play_er")
except Exception:
    ADDON = xbmcaddon.Addon()






def get_security_info():

    """
    BANLIST :: GET INFO
    -- Získá stav serveru a banlistu.
    """

    status_url = "https://xbmc.south-fork.uk/SERVER/addon-security.run"
    public_ip = "IP UNKNOWN"

    try:
        resp = safe_get("https://api.ipify.org?format=json", timeout=3)
        if resp: public_ip = resp.json().get("ip")
    except: pass

    allowed = "N/A"
    is_banned = False
    try:
        resp = safe_get(status_url, timeout=5)
        if resp:
            lines = resp.text.splitlines()
            ip_ban_list =[]
            server_allowed = True
            for line in lines:
                if "=" in line:
                    key, value = line.split("=", 1)
                    key, value = key.strip(), value.strip()
                    if key == "allowed":
                        server_allowed = (value.lower() == "true")
                    elif key == "ip_ban":
                        ip_ban_list.append(value)

            allowed = "POVOLENO" if server_allowed else "ZAKÁZÁNO"
            if public_ip in ip_ban_list:
                is_banned = True
    except: pass
    return public_ip, allowed, is_banned



def show_system_metrics():

    """
    DIALOG :: SYSTEM METRICS
    -- Zobrazí sjednocený XML dialog pro diagnostiku systému a metrik.
    """

    try:
        # Příprava dat pro XML okno (seznam dictů)
        data =[]

        addon_ver = ADDON.getAddonInfo('version')
        kodi_ver = xbmc.getInfoLabel('System.BuildVersion').split(" ")[0]
        python_ver = sys.version.split()[0]
        free_mem = xbmc.getInfoLabel('System.FreeMemory')
        uptime = xbmc.getInfoLabel('System.Uptime')
        cpu_temp = xbmc.getInfoLabel('System.CpuTemperature')
        ip_address = xbmc.getInfoLabel('Network.IPAddress')

        pub_ip, glob_status, is_banned = get_security_info()
        status_color = Colors.LIMEGREEN if glob_status == "POVOLENO" else Colors.RED
        ban_text = f"[COLOR {Colors.RED}]BAN IP ADRESY![/COLOR]" if is_banned else f"[COLOR {Colors.LIMEGREEN}]IP ALLOWED[/COLOR]"

        db_count, db_size, db_status = cache_manager.get_db_stats()
        db_status_color = Colors.LIMEGREEN if db_status == "CONNECTED" else Colors.RED

        stats = cache_manager.IN_MEMORY_CACHE_STATS
        hits = stats.get('hits', 0)
        misses = stats.get('misses', 0)
        total_lookups = hits + misses
        hit_ratio = (hits / total_lookups * 100) if total_lookups else 0
        eff_col = Colors.LIMEGREEN if hit_ratio > 70 else Colors.YELLOW if hit_ratio > 30 else Colors.RED

        # 1. DB CACHE
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ CACHING DATABÁZE  [ {cache_manager.DB_TYPE} ][/COLOR][/B]", 'value': '', 'is_header': True})
        data.append({'label': '► Stav připojení', 'value': f"[B][COLOR {db_status_color}]{db_status}[/COLOR][/B]"})
        data.append({'label': '► Počet záznamů', 'value': f"[B]{db_count}[/B]"})
        data.append({'label': '► Velikost DB', 'value': f"[B][COLOR {Colors.YELLOW}]{db_size:>8.2f} MB[/COLOR][/B]"})

        if cache_manager.DB_TYPE == "MySQL (MariaDB)":
            try:
                data.append({'label': '► IP adresa serveru', 'value': f"[B]{ADDON.getSetting('db_host')}[/B]"})
                pool = getattr(cache_manager, 'DB_POOL', None)
                pool_size = None
                pool_info = 'NEDOSTUPNÝ'
                if pool:
                    pool_size = getattr(pool, 'pool_size', None) or getattr(pool, '_pool_size', None) or getattr(pool, 'cnx_count', None)
                    pool_info = f"{pool_size}" if pool_size else 'available'
                mysql_checkouts = getattr(cache_manager, 'MYSQL_CHECKOUT_COUNT', 'N/A')

                data.append({'label': '► MySQL Pool Limit', 'value': f"[B]{pool_info}[/B]"})
                data.append({'label': '► MySQL Aktivní vlákna', 'value': f"[B]{mysql_checkouts}[/B]"})
            except: pass

        # 2. RAM CACHE
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ IN-MEMORY CACHE  [ MEMORY -- RAM ][/COLOR][/B]", 'value': '', 'is_header': True})
        data.append({'label': '► Limit položek', 'value': f"[B]{cache_manager.RAM_SIZE}[/B]"})
        data.append({'label': '► Aktuálně použito', 'value': f"[B]{len(cache_manager.CACHE_RAM)}[/B]"})
        data.append({'label': '► Úspěšnost hledání v paměti', 'value': f"[B][COLOR {eff_col}]{hit_ratio:>6.1f} %[/COLOR][/B]"})
        data.append({'label': '► Zásahy vs Minutí  ( HITS / MISS )', 'value': f"[B][COLOR {Colors.LIMEGREEN}]{hits}[/COLOR]  /  [COLOR {Colors.RED}]{misses}[/COLOR][/B]"})

        # --- Runtime Check

        warnings =[]
        free_mem_val, load_avg, uptime_seconds, cores, proc_cpu = 0, 0.0, 0, 1, None
        try:
            fm = xbmc.getInfoLabel('System.FreeMemory')
            if fm:
                import re
                digits = re.sub(r'[^0-9]', '', fm)
                if digits: free_mem_val = int(digits)
            with open('/proc/loadavg', 'r') as f: load_avg = float(f.read().split()[0])
            with open('/proc/uptime', 'r') as f: uptime_seconds = int(float(f.read().split()[0]))
            import os
            cores = os.cpu_count() or 1
        except: pass

        if free_mem_val and free_mem_val < 50 * 1024: warnings.append('Nízká volná paměť RAM')
        if load_avg and load_avg > max(1.0, cores * 0.9): warnings.append('Vysoké zatížení CPU')

        # 3. RUNTIME INFO
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ SYSTÉMOVÉ RUNTIME  [ RUNTIME INFO ][/COLOR][/B]", 'value': '', 'is_header': True})
        data.append({'label': '► Free memory  ( MB )', 'value': f"[B]{free_mem_val}[/B]"})
        # data.append({'label': '► Load avg (1m)', 'value': f"[B]{load_avg:<8.2f}[/B]"})
        data.append({'label': '► Load avegange  ( 1 minute )', 'value': f"[B]{load_avg}[/B]"})
        data.append({'label': '► Uptime systému  ( seconds )', 'value': f"[B]{uptime_seconds}[/B]"})
        data.append({'label': '► CPU jádra', 'value': f"[B]{cores}[/B]"})

        # if warnings:
            # data.append({'label': '[B][COLOR red]► UPOZORNĚNÍ[/COLOR][/B]', 'value': f"[B][COLOR red]{', '.join(warnings)}[/COLOR][/B]"})

        # --- Orchestrator

        orch = None
        try: orch = get_orchestrator()
        except: pass
        is_metrics_enabled = True
        if orch: is_metrics_enabled = orch.is_metrics_enabled()

        if is_metrics_enabled:
            try:
                METRICS.gauge('cache.db.type', cache_manager.DB_TYPE)
                METRICS.gauge('cache.db.count', db_count)
                METRICS.gauge('cache.hits', hits)
                METRICS.gauge('cache.misses', misses)
            except: pass

        # 4. NETWORK & SECURITY
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ BEZPEČNOST A NETWORKING  [ STATUS ADDON ][/COLOR][/B]", 'value': '', 'is_header': True})
        data.append({'label': '► Lokální IP', 'value': f"[B]{ip_address}[/B]"})
        data.append({'label': '► Veřejná IP', 'value': f"[B]{pub_ip}[/B]"})
        data.append({'label': '► Detekce IP ban', 'value': f"[B]{ban_text}[/B]"})
        data.append({'label': '► Stav doplňku', 'value': f"[B][COLOR {status_color}]{glob_status}[/COLOR][/B]"})

        # 5. KODI INFO
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ INFORMACE O KODI SYSTÉMU  [ XBMC INFO ][/COLOR][/B]", 'value': '', 'is_header': True})
        data.append({'label': '► Kodi verze', 'value': f"[B]{kodi_ver}[/B]"})
        data.append({'label': '► Python verze', 'value': f"[B]{python_ver}[/B]"})
        data.append({'label': '► Formátovaná volná paměť', 'value': f"[B][COLOR {Colors.LIMEGREEN}]{free_mem}[/COLOR][/B]"})
        data.append({'label': '► Teplota CPU', 'value': f"[B]{cpu_temp}[/B]"})
        data.append({'label': '► Čas od startu', 'value': f"[B]{uptime}[/B]"})

        # 6. ORCHESTRATOR
        data.append({'label': f"[B][COLOR {Colors.ORANGE}]○ ORCHESTRATOR MONITOR  [ SYSTEM METRICS ][/COLOR][/B]", 'value': '', 'is_header': True})

        metrics = {}
        if not orch:
            data.append({'label': '► Orchestrator', 'value': '[B][COLOR red]NENÍ DOSTUPNÝ[/COLOR][/B]'})
        else:
            state_color = "limegreen" if is_metrics_enabled else "red"
            state_text = "ANO" if is_metrics_enabled else "NE"
            data.append({'label': '► Sběr metrik povolen', 'value': f"[B][COLOR {state_color}]{state_text}[/COLOR][/B]"})

            metrics = orch.list_all_metrics()
            if not metrics:
                data.append({'label': '► Stav záznamu', 'value': '[B][COLOR gray]Zatím žádné metriky neuloženy[/COLOR][/B]'})
            else:
                for mk in sorted(metrics.keys()):
                    val = metrics.get(mk)
                    data.append({'label': f'► {mk.strip()}', 'value': f"[B][COLOR {Colors.YELLOW}]{val}[/COLOR][/B]"})
                    if is_metrics_enabled:
                        try:
                            if isinstance(val, (int, float)): METRICS.gauge(f"orch.{mk}", val)
                            else: METRICS.set_meta(f"orch.{mk}", str(val))
                        except: pass

        # --- Spuštění nového XML Ovladače

        addon_path = ADDON.getAddonInfo('path')

        try:
            from resources.lib.dialog_metrics_xml import PlayErDialogMetricsXML
        except ImportError:
            log("METRICS - Nepodařilo se najít dialog_metrics_xml.py", xbmc.LOGERROR)
            notify_error(f"ERROR NAČÍTANÍ ROZHRANÍ XML UI METRIKY", category="DIALOG", time=3000)
            #  xbmcgui.Dialog().notification("PLAY.ER", "Chyba při načítání XML UI pro Metriky", xbmcgui.NOTIFICATION_ERROR)
            return

        xml_dialog = PlayErDialogMetricsXML(
            "script-play_er-dialog_metrics.xml",
            addon_path,
            "Default",
            "1080i",
            metrics_data=data,
            addon=ADDON,
            orchestrator=orch,
            raw_metrics=metrics
        )
        xml_dialog.doModal()
        del xml_dialog

    except Exception as e:
        log(f"METRICS - DIALOG ERROR : {e}", xbmc.LOGERROR)
        notify_error(f"ERROR CHYBA ZOBRAZENÍ DIAGNOSTIKY", category="DIALOG", time=3000)
        #  xbmcgui.Dialog().notification("PLAY.ER", "Chyba zobrazení diagnostiky", xbmcgui.NOTIFICATION_ERROR, 3000)
