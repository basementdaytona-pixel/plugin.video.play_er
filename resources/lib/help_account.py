# -*- coding: utf-8 -*-

from resources.lib.utils_theme import Colors

HELP_ACCOUNT_TEXT = f"""
[B][COLOR {Colors.ORANGE}]   PLAY.ER  ::  PRŮVODCE NASTAVENÍM API ÚČTŮ      [/COLOR][/B]
[B][COLOR {Colors.ORANGE}]   Verze dokumentace: 3.5  ( Build: 2025-12-13 )  [/COLOR][/B]

Tento dokument slouží jako přiručka pro získání a nastavení vašich vlastních API klíčů pro služby [B]TRAKT.TV[/B] a [B]The Movie Database (TMDB)[/B].

[B]Proč to dělat?[/B]
Mít vlastní API klíče znamená, že nejste závislí na veřejných klíčích, které mohou být přetížené. Získáte stabilnější synchronizaci, rychlejší načítání metadat a plnou kontrolu nad svým účtem.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 1: TRAKT.TV API (CLIENT ID & SECRET)[/COLOR][/B]

TRAKT.TV je "mozkem" vaší historie. Vlastní API aplikace vám zajistí bezproblémový scrobbling (záznam sledování).

[B][COLOR {Colors.ORANGE}]KROK 1: PŘÍPRAVA[/COLOR][/B]
- Otevřete webový prohlížeč na PC nebo mobilu.
- Jděte na [B]https://trakt.tv[/B]
- Přihlaste se ke svému účtu (nebo se zaregistrujte).

[B][COLOR {Colors.ORANGE}]KROK 2: VYTVOŘENÍ APLIKACE[/COLOR][/B]
- Přejděte na adresu: [B]https://trakt.tv/oauth/applications[/B]
- Klikněte na zelené tlačítko [B]NEW APPLICATION[/B].

[B][COLOR {Colors.ORANGE}]KROK 3: VYPLNĚNÍ FORMULÁŘE[/COLOR][/B]
Formulář může vypadat složitě, ale stačí vyplnit jen toto:
- [B]Name:[/B] Zadejte libovolný název (např. "MujKodiPlayer").
- [B]Description:[/B] Libovolný popis (např. "Private use").
- [B]Redirect URI:[/B] [COLOR {Colors.RED}]DŮLEŽITÉ![/COLOR] Zde musíte napsat přesně toto:
  [B][COLOR {Colors.LIMEGREEN}]urn:ietf:wg:oauth:2.0:oob[/COLOR][/B]
  (Bez tohoto nebude fungovat autorizace v Kodi!)
- [B]Permissions:[/B] Zaškrtněte všechna políčka ([B]/checkin[/B], [B]/scrobble[/B], [B]/sync[/B]).

[B][COLOR {Colors.ORANGE}]KROK 4: ZÍSKÁNÍ KLÍČŮ[/COLOR][/B]
- Klikněte na [B]SAVE APP[/B].
- Nyní uvidíte stránku s detaily vaší nové aplikace.
- Najděte sekci "Keys" a zkopírujte si:
  1. [B]Client ID[/B] (Dlouhý řetězec znaků)
  2. [B]Client Secret[/B] (Ještě delší řetězec)

[B][COLOR {Colors.ORANGE}]KROK 5: NASTAVENÍ V KODI[/COLOR][/B]
- Otevřete nastavení doplňku Play.er -> [B]INTEGRACE[/B].
- Vložte zkopírované kódy do polí [B]Trakt Client ID[/B] a [B]Trakt Client Secret[/B].
- Poté klikněte na "Trakt: Autorizovat účet" a postupujte podle pokynů na obrazovce (zadání PIN kódu).

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 2: TMDB API (API KEY & SESSION ID)[/COLOR][/B]

TMDB je "knihovna", odkud bereme obrázky a texty. Vlastní klíč zaručí, že uvidíte limity jen pro sebe a nebudete sdílet "frontu" s ostatními uživateli doplňku.

[B][COLOR {Colors.ORANGE}]KROK 1: PŘÍPRAVA[/COLOR][/B]
- Jděte na [B]https://www.themoviedb.org[/B]
- Přihlaste se.

[B][COLOR {Colors.ORANGE}]KROK 2: ŽÁDOST O API KLÍČ[/COLOR][/B]
- Klikněte na svůj profil (ikona vpravo nahoře) -> [B]Settings[/B].
- V levém menu vyberte [B]API[/B].
- Klikněte na [B]Create[/B] nebo [B]click here[/B] pro vygenerování nového klíče.
- Vyberte možnost [B]Developer[/B].

[B][COLOR {Colors.ORANGE}]KROK 3: VYPLNĚNÍ ŽÁDOSTI[/COLOR][/B]
- TMDB se zeptá na detaily. Vyplňte je pravdivě, ale stručně:
  - [B]Application Name:[/B] "Kodi Personal"
  - [B]Application URL:[/B] "https://kodi.tv"
  - [B]Application Summary:[/B] "For personal use in Kodi media center to fetch metadata."
  - Vyplňte své kontaktní údaje.
- Odešlete formulář. Klíč je obvykle schválen [B]okamžitě[/B].

[B][COLOR {Colors.ORANGE}]KROK 4: ZÍSKÁNÍ "API KEY (v3 auth)"[/COLOR][/B]
- Po schválení uvidíte na stránce API sekci "API Key (v3 auth)".
- Zkopírujte tento klíč.
- Vložte ho v Kodi do nastavení doplňku -> [B]INTEGRACE[/B] -> [B]TMDB API Key[/B].

[B][COLOR {Colors.ORANGE}]KROK 5: GENERACE SESSION ID[/COLOR][/B]
Toto je krok, který propojí doplněk s vaším konkrétním účtem (aby věděl, co máte ve Watchlistu).
- V nastavení doplňku Play.er (v sekci Integrace) klikněte na tlačítko [B]TMDB: Přihlásit se (Získat Session ID)[/B].
- Doplněk vás provede procesem (otevře okno s QR kódem nebo výzvou k návštěvě webu).
- Na webu potvrdíte, že "Kodi Personal" smí přistupovat k vašemu účtu.
- Session ID se poté automaticky uloží.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]SHRNUTÍ[/COLOR][/B]

Máte hotovo! Nyní máte doplněk nastavený na "PROFI" úrovni.
- [B]Trakt API[/B] zajistí, že se historie sledování nikdy neztratí.
- [B]TMDB API[/B] zajistí, že načítání menu a informací o filmech bude bleskové a spolehlivé.


[I]TIP : Pokud se vám nedaří klíče zkopírovat do TV (je to dlouhé psaní), doporučujeme použít aplikaci "Kodi Remote" na telefonu, která umí poslat text do Kodi přes schránku (Paste Text), nebo editovat soubor `settings.xml` přes síť/SSH.[/I]


--- [B][COLOR {Colors.ORANGE}] [ Mau!X ER '2025 ] [/COLOR][/B] ---

"""
