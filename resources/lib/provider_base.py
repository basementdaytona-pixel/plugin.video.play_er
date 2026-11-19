# -*- coding: utf-8 -*-

##############################################################################
#
# Addon: plugin.video.play_er
# Module: provider_base.py
# Author: Mau!X ER
# Created on: 20.11.2025
# Last edit on: 21.03.2026
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

from abc import (
    abstractmethod,
    ABC
)





class BaseProvider(ABC):

    """
    ABC :: PROVIDER CLASS
    -- Abstraktní základní třída pro všechny providery.
    -- Definuje společné rozhraní, které musí každý provider implementovat.
    -- Tím je zajištěna konzistence a snadná rozšiřitelnost o nové providery.
    """


    def __init__(self, addon, handle, session, tmdb_client):

        self.addon = addon
        self._handle = handle
        self.session = session
        self.tmdb_client = tmdb_client
        # základní identifikace provideru (lze přepsat v potomcích)
        try:
            self.provider_name = getattr(self, 'provider_name', self.__class__.__name__.lower())
        except Exception:
            self.provider_name = self.__class__.__name__.lower()
        self.provider_color = None


    @abstractmethod
    def search_sources(self, query, cookies=None, apply_filters=True):

        """
        ABC :: SEARCH
        -- Vyhledá zdroje na základě dotazu.
        -- :param query: Vyhledávací řetězec.
        -- :param cookies: Cookies pro autentizaci (pokud jsou potřeba).
        -- :param apply_filters: Zda aplikovat globální filtry.
        -- :return: Seznam slovníků s nalezenými videi.
        """
        pass

    @abstractmethod
    def get_video_link(self, link_or_id):

        """
        ABC :: VIDEO GET
        -- Získá přímý odkaz na video a případně na titulky.
        -- :param link_or_id: URL nebo ID souboru.
        -- :return: Tuple (stream_url, subtitle_url).
        """

        pass

    def get_premium_cookies(self):

        """
        ABC :: COOKIES
        -- Vrátí cookies pro premium účet. Pokud provider cookies nepoužívá,
        -- může vrátit None.
        """

        return None

    def normalize_and_filter(self, items, apply_filters=True):
        """
        Normalizuje položky výsledků provideru: zajistí klíče `provider`, `tags`, `extension` a
        přidá `provider_color` (pokud není nastaveno). Poté aplikuje globální filtry pokud je
        `apply_filters` True.
        """
        from resources.lib.utils_filter import FilterUtils
        from resources.lib.utils_theme import Colors

        normalized = []
        for it in items:
            if not isinstance(it, dict):
                normalized.append(it)
                continue
            if 'provider' not in it or not it.get('provider'):
                it['provider'] = getattr(self, 'provider_name', self.__class__.__name__.lower())
            if 'tags' not in it or it.get('tags') is None:
                it['tags'] = []
            if 'extension' not in it or it.get('extension') is None:
                it['extension'] = ''
            if 'provider_color' not in it or not it.get('provider_color'):
                prov = str(it.get('provider', '')).lower()
                it['provider_color'] = Colors.LIMEGREEN if 'webshare' in prov else Colors.ORANGE
            normalized.append(it)

        if apply_filters:
            try:
                return FilterUtils(self.addon).apply_filters(
                    normalized,
                    enable_setting_id="enable_filtering",
                    include_setting_ids=["filter_global"],
                    exclude_setting_ids=["exclude_global"]
                )
            except Exception:
                return normalized

        return normalized