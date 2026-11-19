# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: monitor_orchestrator.py
# Author: Mau!X ER
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import time
import json
import uuid

import xbmc
import xbmcgui


from resources.lib.utils_logging import log
from resources.lib.utils_theme import Colors
from resources.lib.utils import get_url


from resources.lib.utils_settings import (
    get_setting_int_with_bounds,
    get_setting_str
)


def _safe_exec(cmd):
    try:
        xbmc.executebuiltin(cmd)
    except Exception as e:
        log(f"ORCHESTRATOR - EXEC ERROR : {e}", xbmc.LOGWARNING)








class MonitorOrchestrator:

    """
    CLASS :: MONITOR ORCHESTRATOR
    -- Centrální, lehký orchestrátor pro koordinaci jednorázových triggerů napříč instancemi.
    """

    def __init__(self):
        try:
            self.win = xbmcgui.Window(10000)
        except Exception:
            self.win = None

        try:
            import xbmcaddon
            addon = xbmcaddon.Addon()
            try:
                val = addon.getSettingBool('metrics_enabled')
                if self.win:
                    self.win.setProperty("plugin.video.play_er.metrics_enabled", '1' if val else '0')
            except Exception:
                pass
        except Exception:
            pass



    def allow_preemptive(self, tmdb_id, season, throttle_seconds=600):
        try:
            if not self.win or not tmdb_id:
                return True
            key = f"plugin.video.play_er.preemptive_last:{tmdb_id}:{season}"
            last = self.win.getProperty(key)
            if last:
                try:
                    last_ts = int(last)
                    if int(time.time()) - last_ts < int(throttle_seconds):
                        try:
                            self._inc_metric('preemptive_throttle_hits')
                        except Exception:
                            pass
                        return False
                except Exception:
                    pass
        except Exception:
            pass
        return True


    def record_preemptive(self, tmdb_id, season):
        try:
            if not self.win or not tmdb_id:
                return
            key = f"plugin.video.play_er.preemptive_last:{tmdb_id}:{season}"
            self.win.setProperty(key, str(int(time.time())))
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( record_preemptive )  ERROR : {e}", xbmc.LOGWARNING)
        try:
            self._inc_metric('preemptive_count')
        except Exception:
            pass


    def allow_skip_via_playlist(self, addon):
        try:
            pl = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
            pos = pl.getposition()
            sz = pl.size()
            try:
                auto_when_playlist = addon.getSettingBool("skip_credits_auto_when_playlist")
            except Exception:
                auto_when_playlist = False

            if sz > 0 and pos >= 0 and pos < (sz - 1) and auto_when_playlist:
                try:
                    self.win.setProperty("player.last_trigger_action", "continue_trigger_main")
                except Exception:
                    pass
                return True
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( allow_skip_via_playlist )  ERROR : {e}", xbmc.LOGWARNING)
        return False


    # FIX PRE-EMPTIVE AND FILTERS [SAFE QUEUED EPISODE CHECK]
    def allow_skip_via_episode_playlist(self, addon, meta, tmdb_client, require_auto_setting=False):
        try:
            if require_auto_setting and not addon.getSettingBool("skip_credits_auto_when_playlist"):
                return False
            from resources.lib.generator import is_next_episode_queued
            return is_next_episode_queued(meta, tmdb_client)
        except Exception as e:
            log(f"FIX PRE-EMPTIVE AND FILTERS - Ověření epizody ve frontě selhalo: {e}", xbmc.LOGDEBUG)
            return False


    def perform_next(self):
        _safe_exec("PlayerControl(Next)")
        try:
            self._inc_metric('skipcredits_next_count')
        except Exception:
            pass


    def _metric_prop_key(self, name):
        return f"plugin.video.play_er.metrics:{name}"


    def inc_metric(self, name, amount=1):

        """
        AI :: PUBLIC ALIAS
        -- Veřejný alias pro inkrementaci metrik  ( používá např. AI Modul )
        """

        return self._inc_metric(name, amount)


    def _inc_metric(self, name, amount=1):
        try:
            try:
                if self.win:
                    en = self.win.getProperty("plugin.video.play_er.metrics_enabled")
                    if en == '0':
                        return
            except Exception:
                pass
            if not self.win:
                return
            key = self._metric_prop_key(name)
            cur = self.win.getProperty(key) or '0'
            try:
                curv = int(cur)
            except Exception:
                curv = 0
            curv += int(amount)
            self.win.setProperty(key, str(curv))
            try:
                idx_key = "plugin.video.play_er.metrics_list"
                idx_raw = self.win.getProperty(idx_key) or '[]'
                try:
                    idx = json.loads(idx_raw)
                    if not isinstance(idx, list):
                        idx =[]
                except Exception:
                    idx =[]
                if name not in idx:
                    idx.append(name)
                    try:
                        self.win.setProperty(idx_key, json.dumps(idx))
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( inc_metric )  ERROR : {e}", xbmc.LOGWARNING)


    def reset_metric(self, name):
        try:
            if not self.win:
                return
            key = self._metric_prop_key(name)
            self.win.setProperty(key, '0')
            try:
                idx_key = "plugin.video.play_er.metrics_list"
                idx_raw = self.win.getProperty(idx_key) or '[]'
                idx = json.loads(idx_raw)
                if name in idx:
                    idx.remove(name)
                    self.win.setProperty(idx_key, json.dumps(idx))
            except Exception:
                pass
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( reset_metric )  ERROR : {e}", xbmc.LOGWARNING)


    def reset_all_metrics(self):
        try:
            if not self.win:
                return
            idx_key = "plugin.video.play_er.metrics_list"
            idx_raw = self.win.getProperty(idx_key) or '[]'
            try:
                idx = json.loads(idx_raw)
                if not isinstance(idx, list):
                    idx = []
            except Exception:
                idx =[]
            for name in list(idx):
                try:
                    self.reset_metric(name)
                except Exception:
                    pass
            try:
                self.win.clearProperty(idx_key)
            except Exception:
                pass
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( reset_all_metrics ) ERROR : {e}", xbmc.LOGWARNING)


    def set_metrics_enabled(self, enabled=True):
        try:
            if not self.win:
                return
            val = '1' if enabled else '0'
            self.win.setProperty("plugin.video.play_er.metrics_enabled", val)
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( set_metrics_enabled )  ERROR : {e}", xbmc.LOGWARNING)


    def is_metrics_enabled(self):
        try:
            if not self.win:
                return True
            v = self.win.getProperty("plugin.video.play_er.metrics_enabled")
            if v == '0':
                return False
            return True
        except Exception:
            return True


    def get_metric(self, name):
        try:
            if not self.win:
                return 0
            key = self._metric_prop_key(name)
            cur = self.win.getProperty(key) or '0'
            try:
                return int(cur)
            except Exception:
                return 0
        except Exception:
            return 0


    def list_all_metrics(self):

        """
        METRICS :: LIST ALL
        -- Formátuje a vrací metriky pro dialogové okno.
        """

        try:
            if not self.win:
                return {}
            idx_key = "plugin.video.play_er.metrics_list"
            idx_raw = self.win.getProperty(idx_key) or '[]'
            try:
                idx = json.loads(idx_raw)
                if not isinstance(idx, list):
                    idx =[]
            except Exception:
                idx =[]

            known_metrics =[
                "preemptive_count",
                "preemptive_throttle_hits",
                "skipcredits_count",
                "skipcredits_next_count",
                "ai_requests_total",
                "ai_provider_gemini",
                "ai_provider_openrouter",
                "ai_fallback_triggered",
                "ai_errors_total",
                "ai_json_errors"
            ]
            for k in known_metrics:
                if k not in idx:
                    idx.append(k)

            friendly_names = {
                "preemptive_count":         "Pre-Emptive Scrapes  :  Úspěšné",
                "preemptive_throttle_hits": "Pre-Emptive Scrapes  :  Zrušené",
                "skipcredits_count":        "Skip Credits Dialog  :  Zobrazeno",
                "skipcredits_next_count":   "Skip Credits Action  :  Auto-Next",
                "ai_requests_total":        "AI Engine  :  Celkový počet dotazů",
                "ai_provider_gemini":       "AI Engine  :  Odbaveno přes Gemini",
                "ai_provider_openrouter":   "AI Engine  :  Odbaveno přez OpenRouter",
                "ai_fallback_triggered":    "AI Engine  :  Aktivován Auto-Fallback",
                "ai_errors_total":          "AI Engine  :  Kritická selhání  ( Limity / Síť )",
                "ai_json_errors":           "AI Engine  :  Chyby parsování  ( JSON )"
            }

            res = {}
            for name in idx:
                if name.startswith("db_mysql_") or name.startswith("db_sqlite_") or name.startswith("cache_ram_") or name.startswith("cache_db_"):
                    continue

                friendly_name = friendly_names.get(name, name.replace('_', ' ').title())
                padded_name = f"{friendly_name:<38}"

                try:
                    res[padded_name] = self.get_metric(name)
                except Exception:
                    res[padded_name] = 0
            return res
        except Exception:
            return {}


    def should_trigger_preemptive(self, meta, tmdb_client, addon, throttle_seconds=None):
        try:
            if not meta or meta.get("media_type") != "episode":
                return False, "not_episode"

            from resources.lib.generator import get_episode_queue_remaining, _next_episode_coordinates
            if get_episode_queue_remaining(meta) == 0:
                return False, "episode_limit"

            tmdb_id = meta.get("tmdb_id")
            try:
                if throttle_seconds is None:
                    throttle_seconds = get_setting_int_with_bounds(addon, "pre_emptive_throttle", 600)
            except Exception:
                throttle_seconds = 600

            season = int(meta.get("season", 1))
            episode = int(meta.get("episode", 0))

            if not tmdb_id:
                return False, "no_tmdb_id"

            try:
                if not self.allow_preemptive(tmdb_id, season, throttle_seconds):
                    return False, "throttled"
            except Exception:
                pass

            if tmdb_client:
                try:
                    season_info = tmdb_client._fetch(f"tv/{tmdb_id}/season/{season}")
                    if not season_info or not season_info.get("episodes"):
                        return False, "no_episodes"
                    episode_count = len(season_info["episodes"])
                    if episode_count and episode >= episode_count:
                        if _next_episode_coordinates(tmdb_id, season, episode, tmdb_client) is None:
                            return False, "last_episode"
                except Exception as e:
                    log(f"ORCHESTRATOR - FUNCTION  ( should_trigger_preemptive )  TMDB ERROR : {e}", xbmc.LOGWARNING)
                    return False, "tmdb_error"

            return True, "ok"
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( should_trigger_preemptive )  ERROR : {e}", xbmc.LOGWARNING)
            return False, "error"


    def handle_skip_credits(self, meta, tmdb_client, addon, is_current=None):
        try:
            is_current = is_current or (lambda: True)
            if not is_current():
                return "none", "playback_changed"
            if not meta or meta.get("media_type") != "episode":
                return "none", "not_episode"
            # FIX PRE-EMPTIVE AND FILTERS [LAST ALLOWED EPISODE ENDS NATURALLY]
            from resources.lib.generator import get_episode_queue_remaining
            if get_episode_queue_remaining(meta) == 0:
                return "none", "episode_limit"

            current_episode = int(meta.get("episode", 0))
            current_season = int(meta.get("season", 1))
            tmdb_id = meta.get("tmdb_id")

            # FIX PRE-EMPTIVE AND FILTERS [SKIP CREDITS SEASON ROLLOVER]
            # Use the same season-aware episode coordinates as the managed queue.
            try:
                from resources.lib.generator import _next_episode_coordinates
                next_coordinates = _next_episode_coordinates(
                    tmdb_id, current_season, current_episode, tmdb_client
                ) if tmdb_id and tmdb_client else (current_season, current_episode + 1)
                if not next_coordinates:
                    return "none", "last_episode"
            except Exception as e:
                log(f"ORCHESTRATOR - SKIP CREDITS TMDB ERROR : {e}", xbmc.LOGWARNING)
                return "none", "tmdb_error"

            # Strict prediction must never stop this episode to try an unverified
            # Continue fallback. Only a prepared sequential successor can be used.
            if (str(addon.getSetting('auto_prediction_enable')).lower() == 'true'
                    and str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true'):
                from resources.lib.generator import is_next_episode_queued
                if not is_next_episode_queued(meta, tmdb_client):
                    return "none", "prediction_end"

            next_ep_meta = dict(meta)
            next_ep_meta["season"], next_ep_meta["episode"] = next_coordinates

            try:
                if self.allow_skip_via_episode_playlist(addon, meta, tmdb_client, require_auto_setting=True):
                    log("FIX PRE-EMPTIVE AND FILTERS - SKIP CREDITS: automaticky přecházím na ověřenou další epizodu playlistu", xbmc.LOGINFO)
                    if not is_current():
                        return "none", "playback_changed"
                    self.perform_next()
                    try:
                        self._inc_metric('skipcredits_count')
                    except Exception:
                        pass
                    return "next", "playlist_next"
            except Exception:
                pass

            ep_data = {}
            try:
                if tmdb_client and tmdb_id:
                    try:
                        ep_data = tmdb_client._fetch(f"tv/{tmdb_id}/season/{int(next_ep_meta.get('season',1))}/episode/{int(next_ep_meta.get('episode',0))}")
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                play_key = self.get_play_key(meta)
                if play_key:
                    self.set_state(play_key, 'TRIGGERED')

                from resources.lib.dialog_skip_credits import show_skip_credits

                autoclose_sec = get_setting_int_with_bounds(addon, "skip_credits_autoclose", 15, 5, 60)
                default_action = get_setting_str(addon, "skip_credits_default", "PRESKOCIT").strip().upper()
                action_to_take = show_skip_credits(
                    next_ep_meta, ep_data, addon, autoclose_sec, default_action, is_current
                )
                if not is_current():
                    return "none", "playback_changed"

                if action_to_take == "PRESKOCIT":
                    log("SKIP CREDITS - AKCE : PŘESKOČIT", xbmc.LOGINFO)
                    if self.win:
                        self.win.setProperty("player.last_trigger_action", "continue_trigger_main")
                    # FIX PRE-EMPTIVE AND FILTERS [REUSE NEXT EPISODE]
                    # Reuse only a queued item verified as the sequential episode of this show.
                    if self.allow_skip_via_episode_playlist(addon, meta, tmdb_client):
                        log("FIX PRE-EMPTIVE AND FILTERS - SKIP CREDITS: používám již připravenou další epizodu", xbmc.LOGINFO)
                        if not is_current():
                            return "none", "playback_changed"
                        self.perform_next()
                        try:
                            self._inc_metric('skipcredits_count')
                        except Exception:
                            pass
                        return "next", "managed_episode_playlist"
                    # Recheck after the dialog: the prepared item may have
                    # disappeared while the user was deciding.
                    if (str(addon.getSetting('auto_prediction_enable')).lower() == 'true'
                            and str(addon.getSetting('auto_prediction_stop_on_no_match')).lower() == 'true'):
                        return "none", "prediction_end"
                    # Observe playback throughout the handoff, including the
                    # gap before the new plugin invocation attaches its guard.
                    from resources.lib.continue_handoff import ContinueHandoffGuard, TOKEN, ACK
                    if not self.win or not is_current():
                        return "none", "playback_changed"
                    token = uuid.uuid4().hex
                    self.win.setProperty(TOKEN, token)
                    guard = None
                    handed_off = False
                    try:
                        guard = ContinueHandoffGuard(token)
                        owner = self.win.getProperty('play_er.monitor_owner')
                        guard.bind_owner(owner)
                        if not is_current() or guard.interrupted.is_set():
                            return "none", "playback_changed"
                        xbmc.executebuiltin("PlayerControl(Stop)")
                        xbmc.sleep(500)
                        # A slow stop may still be finishing. Wait briefly only
                        # while it is the same item; never stop a replacement.
                        for _ in range(25):
                            if guard.valid():
                                break
                            if guard.interrupted.is_set() or not is_current():
                                return "none", "playback_changed"
                            xbmc.sleep(100)
                        else:
                            return "none", "stop_timeout"
                        url = get_url(action="continue_watching_main", meta=json.dumps(meta),
                                      automatic="true", handoff_token=token, handoff_owner=owner)
                        if not guard.valid():
                            return "none", "playback_changed"
                        xbmc.executebuiltin(f"RunPlugin({url})")
                        monitor = xbmc.Monitor()
                        for _ in range(300):
                            if self.win.getProperty(ACK) == token:
                                self.win.clearProperty(ACK)
                                handed_off = True
                                return "runplugin", "skip_action"
                            if not guard.valid() or monitor.waitForAbort(0.1):
                                return "none", "playback_changed"
                        return "none", "handoff_timeout"
                    except Exception as e:
                        log(f"ORCHESTRATOR - SKIP CREDITS HANDOFF ERROR : {type(e).__name__}", xbmc.LOGWARNING)
                        return "error", "handoff_failed"
                    finally:
                        if not handed_off:
                            if guard:
                                guard.clear()
                            elif self.win.getProperty(TOKEN) == token:
                                self.win.clearProperty(TOKEN)
                else:
                    log("SKIP CREDITS - AKCE : POKRAČOVAT", xbmc.LOGINFO)
                    return "none", "user_continued"

            except Exception as e:
                log(f"ORCHESTRATOR - SKIP CREDITS DIALOG ERROR : {e}", xbmc.LOGERROR)
                return "error", str(e)

        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( handle_skip_credits )  ERROR : {e}", xbmc.LOGERROR)
            return "error", str(e)


    def set_continue_token(self, token):
        try:
            if not self.win: return
            self.win.setProperty("plugin.video.play_er.continue_token", token)
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( set_continue_token )  ERROR : {e}", xbmc.LOGDEBUG)


    def clear_monitor_initialized(self):
        try:
            if not self.win: return
            self.win.clearProperty("plugin.video.play_er.monitor_initialized")
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( clear_monitor_initialized )  ERROR : {e}", xbmc.LOGDEBUG)


    def get_play_key(self, meta):
        try:
            if not meta: return None
            tmdb = meta.get('tmdb_id')
            season = meta.get('season')
            episode = meta.get('episode')
            # CONTINUE queue records can inherit the previous episode's cache ID.
            # One-shot playback triggers must identify the episode, not its cache.
            if (meta.get('media_type') == 'episode' and tmdb
                    and season not in (None, '') and episode not in (None, '')):
                return f"tmdb:{tmdb}:s{season}:e{episode}"
            mid = meta.get('meta_id') or None
            if mid: return str(mid)
            if tmdb: return f"tmdb:{tmdb}:s{season}:e{episode}"
            return None
        except Exception:
            return None


    def _trigger_prop_key(self, play_key, trigger_name):
        return f"plugin.video.play_er.trigger:{play_key}:{trigger_name}"


    def has_triggered(self, play_key, trigger_name):
        try:
            if not self.win or not play_key: return False
            return self.win.getProperty(self._trigger_prop_key(play_key, trigger_name)) == '1'
        except Exception:
            return False


    def set_triggered(self, play_key, trigger_name):
        try:
            if not self.win or not play_key: return
            self.win.setProperty(self._trigger_prop_key(play_key, trigger_name), '1')
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( set_triggered )  ERROR : {e}", xbmc.LOGWARNING)


    def clear_triggers(self, play_key):
        try:
            if not self.win or not play_key: return
            for t in ['preemptive', 'skip_credits']:
                try: self.win.clearProperty(self._trigger_prop_key(play_key, t))
                except Exception: pass
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( clear_triggers )  ERROR : {e}", xbmc.LOGWARNING)


    def _state_prop_key(self, play_key):
        return f"plugin.video.play_er.state:{play_key}"


    def set_state(self, play_key, state):
        try:
            if not self.win or not play_key: return
            self.win.setProperty(self._state_prop_key(play_key), f"{state}:{int(time.time())}")
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( set_state )  ERROR : {e}", xbmc.LOGWARNING)


    def get_state(self, play_key):
        try:
            if not self.win or not play_key: return None
            val = self.win.getProperty(self._state_prop_key(play_key))
            if not val: return None
            return val.split(":", 1)[0]
        except Exception:
            return None


    def clear_state(self, play_key):
        try:
            if not self.win or not play_key: return
            self.win.clearProperty(self._state_prop_key(play_key))
        except Exception as e:
            log(f"ORCHESTRATOR - FUNCTION  ( clear_state )  ERROR : {e}", xbmc.LOGWARNING)



_ORCHESTRATOR = None



def get_orchestrator():
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = MonitorOrchestrator()
    return _ORCHESTRATOR
