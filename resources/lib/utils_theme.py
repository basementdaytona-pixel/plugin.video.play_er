# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: utils_theme.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import os

import xbmc
import xbmcvfs
import xbmcaddon





_addon = xbmcaddon.Addon(id="plugin.video.play_er")
_addon_path = xbmcvfs.translatePath(_addon.getAddonInfo('path'))
_icon_base = os.path.join(_addon_path, "resources", "icons")


def apply_dialog_theme(window, fallback_background="FF000000"):
    """Use AF3 dialog colour roles, including its light-dialog palette."""
    af3 = xbmc.getSkinDir() == 'skin.arctic.fuse.3'
    for role, colour, fallback in (
        ('Background', 'dialog_bg_100', fallback_background),
        ('Text', 'dialog_fg_100', 'FFFFFFFF'),
        ('Muted', 'dialog_fg_70', 'FFCCCCCC'),
        ('Focus', 'dialog_fg_12', 'C0E91E63'),
    ):
        window.setProperty('play_er.' + role, colour if af3 else fallback)





class Colors:
    DARKORANGE = "darkorange"
    LIMEGREEN = "limegreen"
    YELLOW = "yellow"
    ORCHID = "orchid"
    ORANGE = "orange"
    BLUE = "blue"
    GRAY = "gray"
    GREY = "grey"
    RED = "red"





class Icons:
    @staticmethod
    def get_icon(name):
        return os.path.join(_icon_base, name)





    # --- HLAVNÍ IKONY


    PLAYMAIN      = get_icon("MAIN--PLAYMAIN.webp")
    SEARCH        = get_icon("MAIN--SEARCHING.webp")
    SETTINGS      = get_icon("MAIN--SETTINGS.webp")
    SEPARATOR     = get_icon("MAIN--SEPARATOR.webp")
    NEXT_PAGE     = get_icon("MAIN--NEXT-PAGE.webp")
    PREHRAJ_TO    = get_icon("MAIN--PREHRAJ-TO.webp")


    # --- POSKYTOVATELÉ


    TMDB_MAIN     = get_icon("MAIN--TMDB.webp")
    TRAKT         = get_icon("MAIN--TRAKT.webp")
    CSFD          = get_icon("MAIN--CSFD.webp")
    TMDB          = get_icon("TMDB.webp")


    # --- KATEGORIE


    MOVIE_MAIN    = get_icon("MAIN--MOVIE.webp")
    TV_SHOW       = get_icon("MAIN--TV-SHOW.webp")
    TVSHOW        = get_icon("TVSHOW.webp")
    MOVIE         = get_icon("MOVIE.webp")


    # --- FUNKCE


    SHELL         = get_icon("MAIN--LAUNCHER.webp")
    RANDOM        = get_icon("MAIN--RANDOM.webp")
    PLAYER        = get_icon("MAIN--PLAYER.webp")
    HISTORY       = get_icon("MAIN--HISTORY.webp")
    MANAGER       = get_icon("MAIN--MANAGER.webp")
    LIBRARY       = get_icon("MAIN--LIBRARY.webp")
    STREMIO       = get_icon("MAIN--STREMIO.webp")
    PLAYBACK      = get_icon("MAIN--PLAYBACK.png")
    CONTINUE      = get_icon("MAIN--CONTINUE.webp")
    EPISODES      = get_icon("MAIN--EPISODES.webp")
    WANT_SEE      = get_icon("MAIN--WANT-SEE.webp")
    WATCH_IT      = get_icon("MAIN--WATCH-IT.webp")
    REGISTER      = get_icon("MAIN--REGISTER.webp")
    TELEGRAM      = get_icon("MAIN--TELEGRAM.webp")
    SEARCHING     = get_icon("MAIN--SEARCHING.webp")
    SPEEDTEST     = get_icon("MAIN--SPEEDTEST.webp")
    PROVIDERS     = get_icon("MAIN--PROVIDERS.webp")
    TMDB_LISTS    = get_icon("MAIN--TMDB-LISTS.webp")
    INTELLIGENCE  = get_icon("MAIN--INTELLIGENCE.webp")


    # --- UPDATED


    WATCHING      = get_icon("MAIN--WATCHING.webp")
    BROADCAST     = get_icon("MAIN--BROADCAST.webp")
    RANDOMIZED    = get_icon("MAIN--RANDOMIZE.webp")
    SEARCH_TAG    = get_icon("MAIN--SEARCHTAG.webp")

    PLAY_BACK     = get_icon("MAIN--PLAY-BACK.webp")
    PLAY_MOVIE    = get_icon("MAIN--PLAY-MOVIE.webp")
    PLAY_SERIES   = get_icon("MAIN--PLAY-SERIES.webp")

    WATCH_LATER   = get_icon("MAIN--WATCH-LATER.webp")
    WATCH_MOVIE   = get_icon("MAIN--WATCH-MOVIE.webp")
    WATCH_SERIES  = get_icon("MAIN--WATCH-SERIES.webp")

    AI_MOOD       = get_icon("MAIN--AI-MOOD.webp")
    AI_TODAY      = get_icon("MAIN--AI-TODAY.webp")
    AI_WHISP      = get_icon("MAIN--AI-WHISP.webp")
    AI_SCRIPT     = get_icon("MAIN--AI-SCRIPT.webp")

    TMDB_MOVIE    = get_icon("MAIN--TMDB-MOVIE.webp")
    TMDB_SHOW     = get_icon("MAIN--TMDB-SHOW.webp")

    TRAKT_TV      = get_icon("MAIN--TRAKT-TV.webp")
    CSFD_TOPS     = get_icon("MAIN--CSFD-TOPS.webp")
    CSFD_LISTS    = get_icon("MAIN--CSFD-LISTS.webp")
    TMDB_EXTRA    = get_icon("MAIN--TMDB-EXTRA.webp")
    TMDB_USERS    = get_icon("MAIN--TMDB-USERS.webp")

    STRM_RANKS    = get_icon("MAIN--STRM-RANKINGS.webp")
    STRM_CHARTS   = get_icon("MAIN--STRM-CHARTS.webp")
    STRM_CSFD     = get_icon("MAIN--STRM-CSFD.webp")
    STRM_IMDB     = get_icon("MAIN--STRM-IMDB.webp")
    STRM_SEARCH   = get_icon("MAIN--STRM-SEARCHING.webp")
    STRM_STUDIO   = get_icon("MAIN--STRM-STUDIOS.webp")
    STRM_DUBBING  = get_icon("MAIN--STRM-DUBBING.webp")
    STRM_SERVICE  = get_icon("MAIN--STRM-SERVICES.webp")

    # DUB_MOVIES    = get_icon("MAIN--DUB-MOVIES.webp")
    # DUB_SHOWS     = get_icon("MAIN--DUB-SHOWS.webp")
    # VOD_MOVIES    = get_icon("MAIN--VOD-MOVIES.webp")
    # VOD_SHOWS     = get_icon("MAIN--VOD-SHOWS.webp")


    # --- DOPLŇKOVÉ


    TOP           = get_icon("TOP.png")
    PLAY          = get_icon("PLAY.webp")
    YEAR          = get_icon("YEAR.webp")
    CAST          = get_icon("CAST.webp")
    NEWS          = get_icon("NEWS.webp")
    WATCH         = get_icon("WATCH.webp")
    VIDEO         = get_icon("VIDEO.png")
    ACTOR         = get_icon("ACTOR.webp")
    GENRE         = get_icon("GENTRE.webp")
    FOLDER        = get_icon("FOLDER.png")
    RATING        = get_icon("RATING.webp")
    KEYWORD       = get_icon("KEYWORD.png")
    NETWORK       = get_icon("NETWORK.png")
    DISCOVER      = get_icon("DISCOVER.webp")
    PROVIDER      = get_icon("PROVIDER.png")
    TRAKT_RED     = get_icon("TRAKT-RED.webp")
    PLAYER_ICON   = get_icon("PLAYER-ICON.webp")
    SEARCH_MOVIE  = get_icon("SEARCH-MOVIE.webp")
    SEARCH_TVSHOW = get_icon("SEARCH-TVSHOW.webp")


    # --- ALIASY  ( pro zpětnou kompatibilitu v plugin.py )


    FAVOURITES    = RATING
    TRAKT_WHITE   = TRAKT
    GENTRE        = GENRE   # Aby plugin.py nespadl, pokud hledá Icons.GENTRE




    # --- NOVÉ IKONY
    #
    # CATALOGS      = get_icon("MAIN--CATALOGS.webp")
    # DUBBING       = get_icon("MAIN--DUBBING.webp")
    # GENERATOR     = get_icon("MAIN--GENERATOR.webp")
    # 
    # SETTINGS      = get_icon("MAIN--ICON.webp")
    # SEPARATOR     = get_icon("MAIN--LOGO.webp")
    # WATCH_LATER   = get_icon("WATCH-LATER.webp")
