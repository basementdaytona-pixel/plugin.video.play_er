# HELP AND INSTALL  ::  PLAY.ER – TMDBHELPER



#######################################################################################################################################
# Filmy po výběru streamu pokračují dalšími streamy = VYPNI v nastavení přehrávače Kodi automatické přehrávání dalších položek fronty!
#
# --- TMDBHELPER PLAYER CODEX SETUP :
#
#     MOVIE    :   TMDBH - SOURCES SCRIPT
#     EPISODE  :   TMDBH - SOURCES PREDICTION
#
#######################################################################################################################################



## Instalace

V nastavení PLAY.ER otevřete sekci **TMDB-HELP** a zvolte **INSTALOVAT PLAYERY**. Addon zkopíruje soubory z této složky do `userdata/addon_data/plugin.video.themoviedb.helper/players/` a před přepsáním existujících souborů je zazálohuje. Soubory v této složce samy o sobě nejsou aktivní. Pokud jsou v cílové složce jiné PLAY.ER playery, v nabídce se zobrazí vedle nových; pro přehlednost používejte jen zamýšlené varianty.


## Význam souborů

| Soubor | Režim TMDBHelper    | Účel |
| --- | --- | --- |
| `TMDBH---SOURCES|TMDB.json`  | `search_movie`, `search_episode` | Výběr zdroje pro konkrétní TMDB film nebo epizodu; doporučená výchozí volba. |
| `TMDBH---AUTO|PLAY.json`     | `play_movie`, `play_episode`     | Automatické přehrání prvního výsledku, který prošel filtry addonu. |
| `TMDBH---SEARCH|TEXT.json`   | `search_movie`, `search_episode` | Textová záloha, například když není k dispozici TMDB ID; název se kóduje pro URL. |


## Mapování vyhledávacích tras

- `tmdbh_bridge&tmdb_id=…&media_type=movie|episode&mode=search`: načte metadata TMDB, sestaví dotaz pro film nebo `SxxExx` pro epizodu a otevře `find_and_list_sources_multi`. Respektuje aktivního providera, více providerů, upřednostnění českého názvu, serverové filtry, lokální filtrování výsledků i nastavení zobrazení výsledků.
- Stejná trasa s `mode=play`: vyhledá zdroje se stejnými filtry a první přehraje přes Kodi `setResolvedUrl`. Tato varianta nevyžaduje ruční výběr souboru.
- `tmdbh_bridge&mode=text_search&q=…`: otevře přímý seznam souborů. Film hledá jako `název (rok)`, epizodu jako `název seriálu SxxExx` podle hodnot TMDBHelper. V této trase je vypnuto lokální `apply_filters`, ale provider dál uplatňuje své nastavení `enable_filtering` a parametry API. Záloha proto může vrátit širší seznam než hledání podle TMDB ID.
- `provider_prehrajto.py` hledá v API `videos/search` a při úspěšné prázdné odpovědi zkusí `videos/suggest`; tyto endpointy se volají uvnitř providera, nikoli přímo ze souboru playeru. `videos/most-watched` nevyhledává konkrétní film či epizodu a není vhodnou player trasou. Podobně `search_tmdb` otevírá katalog TMDB a `series_search` dělá obecný průzkum seriálu, nikoli přesné přehrání epizody.

Playery neobsahují `play_show` ani `search_show`, protože instalovaný TMDBHelper 6.18.1 vystavuje v konfiguraci playerů pouze metody pro film a epizodu. Neobsahují ani `{language}` nebo `{quality}` – nejsou to dostupné hodnoty jeho player mapování. Vynucené `lang`/`quality` v současném mostu jsou jen preference: pokud odpovídající zdroj nenajde, zvolí první výsledek.


## Zdroje

- [Oficiální dokumentace TMDBHelper: Player Function](https://github.com/jurialmunkey/plugin.video.themoviedb.helper/wiki/Player-Function)
- Místní implementace: `resources/lib/actions.py` (`tmdbh_bridge`, `find_and_list_sources_multi`), `resources/lib/provider_prehrajto.py` (`search_sources`) a instalovaný TMDBHelper 6.18.1 (`resources/tmdbhelper/lib/player/`).



Struktura JSON a routy byly ověřeny staticky. Přehrání filmu a epizody je potřeba ještě otestovat přímo v Kodi, protože TMDB API, provider a UI běží pouze tam.
