"""Release plugin-owned Kodi references at interpreter exit, not route exit.

Kodi can reuse imported modules for the next invocation. Their clients and window
handles must stay usable until the interpreter actually shuts down. Releasing
these roots in atexit lets native destructors run before Python module teardown.
"""

import atexit
import gc
import sys


# Explicit ownership: no traversal of other addons or destruction of window
# properties (the properties belong to Kodi and are shared between invocations).
_MODULE_ROOTS = {
    "plugin": (
        "plugin_instance", "provider_manager", "series_manager", "csfd_instance",
        "tmdb_client", "telegram_manager", "GLOBAL_TRAKT_MONITOR",
        "settings_monitor", "addon", "main_window",
    ),
    "cache_manager": ("ADDON", "WINDOW"),
    "tmdb_account": ("ADDON",),
    "trakt": ("_addon", "_GLOBAL_PLAYER_MONITOR"),
    "trakt_episodes": ("ADDON",),
    "utils_logging": ("addon",),
    "utils_notification": ("addon",),
    "utils_theme": ("_addon",),
    "utils_custom": ("ADDON",),
    "metrics_manager": ("ADDON",),
    "dialog_metrics": ("ADDON",),
    "monitor_orchestrator": ("_ORCHESTRATOR",),
}
_registered = False


def release_interpreter_objects():
    """Drop loaded modules' owning references; safe after a partial import too.

    This is terminal cleanup only. Callback/timer shutdown remains the job of
    plugin.shutdown_runtime(), which main.py calls after each route. Do not call
    this function there: a subsequent invocation may reuse the same modules.
    """
    for name, roots in _MODULE_ROOTS.items():
        module = sys.modules.get("resources.lib." + name)
        if module is None:
            continue
        namespace = vars(module)
        for root in roots:
            if root in namespace:
                namespace[root] = None
    # Collect client cycles only after every module alias has been released.
    gc.collect()


def register_cleanup():
    """Register once even when Kodi executes main.py repeatedly."""
    global _registered
    if not _registered:
        atexit.register(release_interpreter_objects)
        _registered = True
