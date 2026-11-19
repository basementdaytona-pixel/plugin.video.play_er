# -*- coding: utf-8 -*-

from resources.lib.utils_theme import Colors

HELP_FILTER_TEXT = f"""
[B][COLOR {Colors.ORANGE}]   PLAY.ER  ::  PRŮVODCE FILTROVÁNÍM A NASTAVENÍM   [/COLOR][/B]
[B][COLOR {Colors.ORANGE}]   Verze dokumentace: 1.0  ( Build: 2025-12-14 )    [/COLOR][/B]

Tento dokument popisuje pokročilé možnosti filtrování obsahu, řazení výsledků a nastavení priorit providerů.

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 1: SYSTÉM FILTROVÁNÍ  ( INCLUDE / EXCLUDE )[/COLOR][/B]

Filtry v doplňku PLAY.ER fungují na principu klíčových slov. Můžete je nastavit globálně (pro všechna vyhledávání) nebo specificky pro Autolisty a Knihovnu.

[B]1. INCLUDE  ( Vynucení / Priorita )[/B]
- Pokud zadáte klíčová slova do pole INCLUDE, výsledky obsahující tato slova budou [B]prioritizovány[/B] (posunuty na začátek seznamu).
- Čím více shod, tím výše bude výsledek.
- [I]Příklad:[/I] `1080P DAB` (Upřednostní FullHD s dabingem).

[B]2. EXCLUDE  ( Vyloučení )[/B]
- Výsledky obsahující slova z pole EXCLUDE budou [B]zcela skryty[/B].
- [I]Příklad:[/I] `CAM TS` (Skryje nekvalitní nahrávky z kina).

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 2: SMART TAGS  ( CHYTRÉ ZKRATKY )[/COLOR][/B]

Aby nebylo nutné vypisovat všechny varianty (např. `1080p`, `FHD`, `FullHD`), doplněk obsahuje slovník synonym. Stačí napsat jeden "Smart Tag" a doplněk automaticky zahrne všechny jeho varianty.

[B]TABULKA SMART TAGS:[/B]

[B]ROZLIŠENÍ:[/B]
• [B]4K[/B]     = 2160P, 4K, UHD, UHDRDV
• [B]1080P[/B]  = 1080P, FHD, FULLHD
• [B]720P[/B]   = 720P, HD, HDTV
• [B]KINO[/B]   = KINO, KINORIP, CAMRIP
• [B]TS[/B]     = TS

[B]KODEKY:[/B]
• [B]H265[/B]   = H265, HEVC, X265
• [B]H264[/B]   = H264, X264, AVC

[B]JAZYKY:[/B]
• [B]DAB[/B]    = DAB, CZDAB, CZ-DABING, DABING, CZ-DAB, CZ, CZE, CS
• [B]SUB[/B]    = TIT, TITULKY, CZTIT, CZ TITULKY, CZ-TIT, SUB, CZSUB
• [B]MULTI[/B]  = CZ + EN


[I]Příklad použití:[/I]
Do filtru INCLUDE stačí napsat `1080P DAB`.
Doplněk to pochopí jako: (1080P nebo FHD nebo FULLHD) A ZÁROVEŇ (DAB nebo CZDAB nebo CZ...).

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 3: ŘAZENÍ A PRIORITY[/COLOR][/B]

[B]1. MULTI-SEARCH PREFERENCE[/B]
Pokud máte zapnutý Multi-Search (hledání na Webshare i Prehraj.to současně), můžete v nastavení určit, který provider má přednost.
- [B]PREHRAJ.TO:[/B] Výsledky z Prehraj.to budou nahoře.
- [B]WEBSHARE.CZ:[/B] Výsledky z Webshare budou nahoře.
I.[/I]

[B]2. ŘAZENÍ PODLE VELIKOSTI[/B]
V nastavení filtrů lze zapnout "SORTING : VELIKOST".
- Seřadí výsledky od nejmenšího souboru po největší.
- Vhodné pro pomalejší připojení.
- Aplikuje se PŘED prioritizací podle kvality (takže nejprve seřadí podle velikosti, a pak v rámci podobné velikosti upřednostní INCLUDE tagy).

[COLOR {Colors.ORANGE}]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 4: AUTOLIST A KNIHOVNA[/COLOR][/B]

Pro automatické přehrávání (Autolist) a přehrávání z knihovny můžete nastavit [B]nezávislé filtry[/B].

- To umožňuje mít globální vyhledávání "volné" (vidět vše), ale pro automatické přehrávání seriálů vyžadovat přísnou kvalitu (např. EXCLUDE `CAM`, INCLUDE `720P`).
- Nastavení naleznete v sekci [B]EXPRESSION -> AUTOLIST / KNIHOVNA[/B].


--- [B][COLOR {Colors.ORANGE}] [ Mau!X ER '2025 ] [/COLOR][/B] ---

"""
