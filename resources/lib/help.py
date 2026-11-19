# -*- coding: utf-8 -*-

from resources.lib.utils_theme import Colors

HELP_TEXT = f"""
[B][COLOR {Colors.ORANGE}]   PLAY.ER  ::  ULTIMÁTNÍ PRŮVODCE & DOKUMENTACE  [/COLOR][/B]
[B][COLOR {Colors.ORANGE}]   Verze dokumentace: 3.5  ( Build: 2025-12-13 )  [/COLOR][/B]

Vítejte v oficiální dokumentaci projektu [B]PLAY.ER[/B].
Tento manuál je koncipován tak, aby vás provedl od úplných základů až po expertní nastavení automatizace a síťových notifikací.

[B][COLOR {Colors.LIMEGREEN}]OBSAH MANUÁLU:[/COLOR][/B]
[B]01.[/B] Architektura a Filozofie (Metadata-First)
[B]02.[/B] Průvodce hlavním menu (Položka po položce)
[B]03.[/B] Zdroje videa a Provideři (Webshare, Prehraj.to)
[B]04.[/B] Vyhledávání, Přehrávání a Filtry (Regex logika)
[B]05.[/B] Funkce AUTOLIST (Nekonečné přehrávání)
[B]06.[/B] Ekosystém a Integrace (Trakt.tv, TMDB, ČSFD)
[B]07.[/B] Osobní knihovna (Nové epizody, Historie, Watch Later)
[B]08.[/B] Notifikační centrum (Kodi & Telegram Bot)
[B]09.[/B] Správa systému (Cache, Zálohování, View Modes)
[B]10.[/B] Technická příloha (Parser a zpracování názvů)
[B]11.[/B] FLATPAK SANDBOX PERMISSIONS COMMANDS

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 1: ARCHITEKTURA "METADATA-FIRST"[/COLOR][/B]

Většina doplňků funguje jako "vyhledávač" – napíšete text a doplněk hledá soubory. [B]PLAY.ER funguje jinak.[/B] Je to multimediální knihovník.

[B]Princip fungování:[/B]
1.  [B]Identifikace:[/B] Jakmile na něco kliknete, doplněk se nejprve spojí s globální databází [B]TMDB[/B]. Získá přesný název, rok, originální název, číslo epizody, žánry a grafiku.
2.  [B]Validace:[/B] Teprve když ví, co přesně hledá, začne prohledávat cloudová úložiště.
3.  [B]Párování:[/B] Nalezené soubory porovnává s metadaty.

[B]Proč tento složitější postup?[/B]
* [B]Krása:[/B] Díky tomu vidíte v Kodi (a skinech jako Arctic Horizon 2 či Estuary Mod) krásné plakáty, fanarty a popisy děje, nikoliv jen seznamy souborů.
* [B]Přesnost:[/B] Minimalizuje se riziko, že si pustíte "Matrix" a spustí se "Matrix Dokument".
* [B]Scrobbling:[/B] Služby jako Trakt.tv potřebují přesná ID (IMDb/TMDB), aby věděly, co sledujete.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 2: PRŮVODCE HLAVNÍM MENU[/COLOR][/B]

Hlavní menu je dynamické – mění se podle toho, co máte nastaveno a co právě sledujete.

[B]1. HLEDÁNÍ[/B]
- Vstupní brána do databáze. Vyhledává filmy i seriály naráz.
- [B]Kontextové menu:[/B] Vyvoláním kontextového menu na této položce zobrazíte [B]Historii hledání[/B].

[B]2. PLAYBACK (Historie)[/B]
- Interní historie doplňku (nezávislá na Trakt.tv).
- Pamatuje si přesně, na jaký soubor jste klikli.
- Slouží pro funkce jako "Znovu přehrát" nebo pro vyloučení již viděného z Autolistů.

[B]3. POKRAČUJ (Continue Watching)[/B]
- [B]Inteligentní tlačítko:[/B] Doplněk se podívá, jaký seriál jste viděli naposledy (např. S01E04) a okamžitě vám nabídne přehrání [B]S01E05[/B].
- Pokud není co sledovat, tato položka zmizí.

[B]4. NOVÉ EPIZODY (Dynamická sekce)[/B]
- Zobrazí se POUZE tehdy, pokud vyšla nová epizoda seriálu, který máte ve Watchlistu.
- Ukazuje číslo (počítadlo) nových dílů.
- [B]Autocleaning:[/B] Jakmile epizodu zhlédnete, automaticky se ze seznamu odstraní.

[B]5. CHCI VIDĚT (Watch Later)[/B]
- Vaše rychlá "odkladiště" obsahu.
- Funguje lokálně. Ideální, když si chcete večer něco pustit, ale nechcete to hledat znova.

[B]6. FILMY & SERIÁLY (Kategorie)[/B]
- Rozsáhlé stromy kategorií z TMDB.
- [B]Discover:[/B] Objevování obsahu podle filtrů.
- [B]Trendy:[/B] Co se právě sleduje ve světě.
- [B]Žánry, Roky, Studia, Televizní stanice.[/B]

[B]7. TMDB USER & TRAKT.TV[/B]
- Osobní sekce pro vaše cloudové účty. Synchronizují vaše seznamy (Watchlist, Favorites, Collections).

[B]8. ČSFD TOPS[/B]
- Lokální specialita. Stahuje data z Česko-Slovenské filmové databáze.
- Tipy dne, Žebříčky, Novinky v kinech.

[B]9. MANAGER[/B]
- Nástroj pro manuální správu seriálů. Umožňuje označovat série jako zhlédnuté/nezhlédnuté.

[B]10. SPEEDTEST & DIAGNOSTIKA[/B]
- Integrovaný nástroj pro měření rychlosti stahování přímo ze serverů (Webshare/Prehraj.to).
- Důležité pro ověření, zda zvládnete přehrát 4K HDR stream.

[B]11. LAUNCHER[/B]
- Pokročilá funkce pro spouštění linuxových shell skriptů přímo z Kodi (pro experty).

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 3: ZDROJE VIDEA (PROVIDEŘI)[/COLOR][/B]

Aby doplněk mohl přehrávat, potřebuje zdroj dat. Play.er podporuje duální režim.

[B][COLOR orange]A) WEBSHARE.CZ[/COLOR][/B]
- Populární české úložiště s obrovskou databází dabovaného obsahu.
- Vyžaduje VIP účet.

[B][COLOR {Colors.ORANGE}]B) PREHRAJ.TO[/COLOR][/B]
- Alternativní zdroj, často obsahuje raritnější kousky nebo jiné verze kvality.
- Vyžaduje Premium účet.

[B][COLOR {Colors.ORANGE}]FUNKCE: MULTI-SEARCH[/COLOR][/B]
Tuto funkci naleznete v menu `PROVIDERS` nebo v Nastavení.
- [B]VYPNUTO:[/B] Doplněk se ptá pouze jednoho serveru (toho, který je nastaven jako aktivní). Je to rychlejší.
- [B]ZAPNUTO:[/B] Doplněk se dotáže [B]obou serverů současně[/B].
    - Výsledky se sloučí do jednoho seznamu.
    - Položky jsou barevně odlišeny (např. Webshare zeleně, Prehrajto oranžově).
    - Ideální pro maximalizaci počtu nalezených zdrojů.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 4: FILTRACE A VÝBĚR STREAMŮ[/COLOR][/B]

Toto je "mozek" doplňku. V `NASTAVENÍ -> EXPRESSION` můžete definovat, co chcete a nechcete vidět.
Filtry fungují na bázi klíčových slov (tzv. RegEx match).

[B]1. GLOBÁLNÍ FILTRY (Použijí se vždy)[/B]

* [B]INCLUDE (Priorita/Vynucení):[/B]
    - Zdroje obsahující tato slova budou posunuty na úplný začátek seznamu.
    - [I]Typické nastavení:[/I] `CZ DABING 1080p`
    - [I]Výsledek:[/I] Pokud existuje FullHD verze s dabingem, bude vždy první. Pokud ne, zobrazí se ostatní.

* [B]EXCLUDE (Blokace/Ignorace):[/B]
    - Zdroje obsahující tato slova budou nemilosrdně smazány ze seznamu.
    - [I]Typické nastavení:[/I] `CAM TS TELESYNC 3D` (Odstraní nekvalitní nahrávky z kina).
    - [I]Pro pomalý internet:[/I] Přidejte `4K 2160p HDR`, abyste neviděli soubory, které neutáhnete.

[B]2. VIETCONG FILTR (TMDB Language Filter)[/B]
- Speciální přepínač v nastavení.
- Pokud je zapnutý, doplněk automaticky ignoruje ve výpisech filmů a seriálů asijskou produkci, která nemá českou/anglickou lokalizaci, aby neplevelila seznamy.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 5: FUNKCE AUTOLIST (NEKONEČNÉ PŘEHRÁVÁNÍ)[/COLOR][/B]

Unikátní vlastnost doplňku PLAY.ER, která mění Kodi v televizní stanici.

[B][COLOR {Colors.ORANGE}]AUTOLIST PRO FILMY[/COLOR][/B]
- [B]Scénář:[/B] Dokoukali jste film a nechce se vám hledat další.
- [B]Řešení:[/B] Vyvoláte kontextové menu na filmu a dáte "Přehrát jako Autolist".
- [B]Logika:[/B]
    1. Doplněk zjistí žánr a téma filmu.
    2. Stáhne seznam "Doporučených filmů" z TMDB.
    3. [B]Vyloučí filmy, které jste už viděli[/B] (podle historie).
    4. Sestaví playlist a začne přehrávat jeden za druhým.
    5. Stream vybírá automaticky (metoda výběru: Smart nebo First Available).

[B][COLOR {Colors.ORANGE}]AUTOLIST PRO SERIÁLY (Binge Watching)[/COLOR][/B]
- [B]Scénář:[/B] Sledujete seriál a nechce se vám po každém dílu sahat na ovladač.
- [B]Řešení:[/B] Klikněte na epizodu (např. S01E01) a zvolte Autolist.
- [B]Logika:[/B]
    1. Doplněk okamžitě vygeneruje playlist pro zbytek série (E02, E03, E04...).
    2. Automaticky vybírá nejlepší zdroj pro každou epizodu.

[B]Nastavení výběru zdroje pro Autolist:[/B]
V `NASTAVENÍ -> AUTOLISTS` můžete určit, jak se má vybírat "ten pravý" soubor, když u toho nejste.
- [B]PRVNÍ DOSTUPNÝ:[/B] Rychlé, bere první nalezený odkaz.
- [B]INTELIGENTNÍ:[/B] Použije speciální sadu filtrů (Autolist Include/Exclude). Zde můžete být přísnější (např. vyžadovat jen 1080p), aby automatické přehrávání mělo garantovanou kvalitu.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 6: EKOSYSTÉM A INTEGRACE[/COLOR][/B]

Play.er není ostrov, umí komunikovat s okolním světem.

[B][COLOR {Colors.ORANGE}]TRAKT.TV (Mozek vaší historie)[/COLOR][/B]
- Doporučujeme každému uživateli.
- [B]Synchronizace:[/B] Pokud označíte film jako zhlédnutý na mobilu, v Kodi se "odfajfkuje".
- [B]Scrobbling:[/B] Play.er posílá informace o tom, co sledujete, v reálném čase.
- [B]Listy:[/B] Vaše osobní seznamy (Watchlist, Collection) jsou dostupné v menu `TRAKT.TV`.

[B][COLOR {Colors.ORANGE}]TMDB (Databázový gigant)[/COLOR][/B]
- Pokud máte účet na TheMovieDB.org, můžete ho propojit v menu `TMDB USER`.
- Umožňuje spravovat Watchlisty a Oblíbené přímo na webu TMDB a vidět je v Kodi.
- [B]Hodnocení:[/B] Po zhlédnutí filmu se vás doplněk může zeptat na hodnocení, které odešle zpět do TMDB.

[B][COLOR {Colors.ORANGE}]ČSFD (Lokální expert)[/COLOR][/B]
- Doplněk využívá ČSFD jako zdroj pro sekci "Tipy" a "Žebříčky".
- Není vyžadován účet, data jsou parsována veřejně.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 7: OSOBNÍ KNIHOVNA[/COLOR][/B]

Kromě cloudových služeb má Play.er svou vlastní paměť uloženou lokálně ve vašem zařízení (nebo na SQL serveru, pokud tak máte nastaveno Kodi).

[B]1. NOVÉ EPIZODY (The Monitor)[/B]
- Toto je jedna z nejužitečnějších funkcí.
- Doplněk na pozadí (při startu) kontroluje váš [B]TMDB Watchlist[/B] (seriály).
- Porovnává data vysílání s aktuálním datem.
- Pokud zjistí, že včera nebo dnes vyšla epizoda, kterou jste ještě neviděli, přidá ji do speciálního menu [B]NOVÉ EPIZODY[/B].
- [B]Chování:[/B] Kliknete -> Přehrajete -> [B]Položka zmizí[/B]. Seznam je tak vždy čistý.
- [B]Nastavení:[/B] Časový rozsah kontroly (např. hledat epizody 7 dní zpětně) lze nastavit v menu.

[B]2. KNIHOVNA (Library Integration)[/B]
- Chcete mít filmy z doplňku přímo v hlavní knihovně Kodi (mezi vašimi lokálními soubory)?
- Použijte funkci "Přidat do knihovny" v kontextovém menu.
- Doplněk vytvoří malý `.strm` soubor, který se tváří jako video, ale ve skutečnosti je to odkaz na Play.er.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 8: NOTIFIKAČNÍ CENTRUM[/COLOR][/B]

Play.er vás umí informovat o dění několika způsoby.

[B]1. KODI NOTIFIKACE (Bubliny)[/B]
- [B]Global:[/B] Informace o přihlášení, chybách.
- [B]Autolist:[/B] Informace o tom, jaký stream se právě vybral ("Přehrávám: Matrix 1080p").
- [B]Nové epizody:[/B] Po startu Kodi vyskočí informace "Nalezena nová epizoda: Rod draka S02E01".

[B]2. TELEGRAM BOT (Notifikace na mobil)[/B]
Pro opravdové nadšence. Doplněk umí poslat zprávu na váš telefon přes Telegram.

[B]Jak to nastavit?[/B]
1.  Nainstalujte si aplikaci Telegram.
2.  Najděte uživatele [B]@BotFather[/B].
3.  Pošlete mu příkaz `/newbot` a postupujte podle instrukcí (pojmenujte bota).
4.  BotFather vám dá [B]HTTP API TOKEN[/B] (dlouhý řetězec znaků). Zkopírujte ho.
5.  Najděte uživatele [B]@userinfobot[/B] (nebo jiného ID bota).
6.  Napište mu jakoukoliv zprávu. Odpoví vám vaším [B]Chat ID[/B] (číslo).
7.  V Kodi jděte do `NASTAVENÍ -> INTEGRACE`.
8.  Zadejte [B]Token[/B] a [B]Chat ID[/B].
9.  Zapněte přepínač "Povolit Telegram notifikace".

[B]Co to umí?[/B]
- Odeslat zprávu, když vyjde nová epizoda (včetně plakátu).
- Odeslat zálohu nastavení doplňku (ZIP soubor) přímo do chatu.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 9: SPRÁVA SYSTÉMU[/COLOR][/B]

[B]1. CACHE MANAGER[/B]
Play.er intenzivně cachuje (ukládá si) výsledky z TMDB a Traktu, aby byl rychlý.
- Pokud se vám zdá, že data jsou zastaralá, použijte v kontextovém menu hlavního menu funkci [B]VYČISTIT CACHE[/B].

[B]2. VIEW MODES (Režimy zobrazení)[/B]
Každý skin v Kodi používá jiná čísla pro zobrazení (Seznam, Plakát, Zeď).
- V `NASTAVENÍ -> VZHLED` můžete vynutit konkrétní pohled pro konkrétní sekci.
- [B]Play.er má inteligentní detekci skinů:[/B] Pozná, zda používáte Estuary, Arctic Horizon 2 nebo Arctic Fuse a podle toho automaticky přizpůsobuje ID pohledů, aby fungovaly funkce jako "Posun" (Shift) nebo "Zeď" (Wall).

[B]3. ZÁLOHOVÁNÍ[/B]
- V kontextovém menu Nastavení naleznete funkci [B]ZÁLOHA TELEGRAM[/B].
- Tato funkce zabalí vaše nastavení, historii a cache do ZIP souboru a odešle ji vašemu Telegram botovi. Ideální pro přenos nastavení na jiné zařízení.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 10: TECHNICKÁ PŘÍLOHA (PARSER)[/COLOR][/B]

Jak doplněk pozná, že soubor `The.Matrix.1999.Remastered.1080p.x264.DTS-WIKI.mkv` je film Matrix?

[B]Proces zpracování:[/B]
1.  [B]Sanitace:[/B] Název se převede na velká písmena, tečky se nahradí mezerami.
2.  [B]Extrakce roku:[/B] Algoritmus najde `1999` a vyjme ho.
3.  [B]Identifikace tagů:[/B] Algoritmus porovná slova se slovníkem.
    - `1080P` -> Rozlišení.
    - `X264` -> Kodek.
    - `DTS`, `WIKI`, `REMASTERED` -> Balast (zahodit nebo skrýt).
4.  [B]Rekonstrukce:[/B] Zbytek slov (`THE MATRIX`) tvoří název.
5.  [B]Prezentace:[/B] Výsledek se zformátuje pro uživatele:
    [B]THE MATRIX (1999) [COLOR {Colors.ORANGE}][ 1080P | H264 ][/COLOR][/B]

Díky tomuto je seznam výsledků vždy čistý a jednotný, bez ohledu na to, jak bordelářsky byl soubor na serveru pojmenován.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]


-- ROZLIŠENÍ

2160P   =  2160P, 4K, UHD, UHDRDV
1080P   =  1080P, FHD, FULLHD
720P    =  720P, HD, HDTV
KINO    =  KINO, KINORIP, CAMRIP

-- KODEKY

H265    =  H265, HEVC, X265
H264    =  H264, X264, AVC

-- JAZYKY

DAB     =  DAB, CZDAB, CZ-DABING, DABING, CZ-DAB, CZ, CZE, CS
SK      =  SK
EN      =  EN, ENG
TIT-CZ  =  TIT, TITULKY, CZTIT, CZ TITULKY, CZ-TIT, SUB, CZSUB


Když do nastavení filtru INCLUDE zadáš  "1080P DAB"
Doplněk interně "rozbalí slovník" a bude hledat jakýkoliv soubor, který obsahuje :

( 1080P nebo FHD nebo FULLHD )
  ZÁROVEŇ TAKÉ
( DAB nebo CZDAB nebo DABING nebo CZ ... )

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]


[I]Manuál sestaven pro komunitu uživatelů PLAY.ER.
Doufáme, že vám tento dokument pomohl pochopit plný potenciál tohoto nástroje.[/I]


[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B]11. FLATPAK SANDBOX PERMISSIONS[/B]


- FLATPAK  ::  TEST
    flatpak run --command=bash tv.kodi.Kodi
    ls -la /run/host/usr/local/bin
    deno qjs

- FLATPAK  ::  SYSTEM BUS
    org.freedesktop.UDisks2
    org.freedesktop.UPower
    org.freedesktop.login1
    org.freedesktop.Avahi

- FLATPAK  ::  SESSION BUS
    org.freedesktop.ScreenSaver

- FLATPAK  ::  FILES DENO
    ~/.deno

- FLATPAK  ::  ENVIRONMENT
    YTDLP_JS_RUNTIME=/home/mauix/.deno/bin/deno

- FLATPAK  ::  PERMISSIONS SCREENSAVER & DENO
    flatpak override --user --talk-name=org.freedesktop.Flatpak tv.kodi.Kodi
    flatpak override --user --env=YTDLP_JS_RUNTIME=/home/mauix/.deno/bin/deno tv.kodi.Kodi


[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]


--- [B][COLOR {Colors.ORANGE}] [ Mau!X ER '2025 ] [/COLOR][/B] ---

"""
