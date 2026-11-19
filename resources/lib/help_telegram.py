# -*- coding: utf-8 -*-

from resources.lib.utils_theme import Colors

TELEGRAM_HELP_TEXT = f"""
[B][COLOR {Colors.ORANGE}]   PLAY.ER  ::  PRŮVODCE NASTAVENÍM TELEGRAM BOTA   [/COLOR][/B]
[B][COLOR {Colors.ORANGE}]   Verze dokumentace: 1.1  ( Build: 2026-03-20 )    [/COLOR][/B]


Tento návod vás provede vytvořením vlastního Telegram bota pro zasílání oznámení :

1. Notifikace o nových epizodách seriálů
2. Report hesel a API klíčů k zadaným ůčtům
3. Zálohování libovolného obsahu  ( složky, nastavení ... )


[COLOR {Colors.ORANGE}]============================================================================[/COLOR]

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 1 : JAK ZÍSKAT TELEGRAM BOT TOKEN[/COLOR][/B]

[B]Postup vytvoření bota :[/B]

1. Otevřete aplikaci Telegram a do vyhledávání napište  [B]@BotFather[/B]
2. Spusťte ho tlačítkem  [B]START[/B]
3. Napište příkaz : [B]/newbot[/B]
4. BotFather se vás zeptá na jméno bota  ([I]XBMC PLAYER ROBOT[/I])
5. Zvolte "username" , které musí končit slovem [B]bot[/B]  ([I]xbmc_player_bot[/I])
6. Bot vytvoří účet, vypíše vám text : [I]"Done! Congratulations on your new bot ..."[/I]

[B]V tomto textu najdete svůj BOT TOKEN :[/B]
[COLOR {Colors.ORANGE}]HTTP API: 123456789:ABCDefghIJKLmnopQRSTuvwxYZ[/COLOR]
( Tento dlouhý řetězec znaků zkopírujte do nastavení doplňku )

[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 2 : AKTIVACE BOTA[/COLOR][/B]

Aby vám bot mohl posílat zprávy, musíte s ním nejprve navázat kontakt.

1. Klikněte na odkaz, který vám poslal BotFather  ([I]t.me/xbmc_player_bot[/I])
2. V okně chatu s vaším botem klikněte na tlačítko  [B]START[/B]
3. Bez tohoto kroku bot nemá oprávnění vám psát!


[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 3 : JAK ZÍSKAT VAŠE CHAT ID[/COLOR][/B]

Chat ID je vaše unikátní číselná adresa v Telegramu. Díky ní bot ví, komu má zprávu doručit.

[B]Postup zjištění ID :[/B]

1. Do vyhledávání v Telegramu napište  [B]@userinfobot[/B]
2. Spusťte ho tlačítkem  [B]START[/B].
3. Bot vám okamžitě odpoví zprávou, kde uvidíte :
   • • [B]ID : [/B] [COLOR {Colors.ORANGE}]123456789[/COLOR]
   • • [B]FIRST NAME : [/B] Vaše jméno ...

[B]Toto číslo (ID) zkopírujte do nastavení doplňku pod položku CHAT ID[/B]


[B][COLOR {Colors.LIMEGREEN}]KAPITOLA 4 : FINÁLNÍ NASTAVENÍ V PLAY.ER[/COLOR][/B]

Nyní máte oba potřebné údaje. Vložte je do příslušných polí v doplňku :

- [B]TELEGRAM TOKEN    :[/B]  ( Vložit řetězec - z Kapitoly 1 )
- [B]TELEGRAM CHAT ID  :[/B]  ( Vložit číslo - z Kapitoly 3 )


[I]TIP : Po uložení nastavení můžete v sekci "Nástroje" vyzkoušet "Odeslat testovací zprávu". Pokud se zpráva objeví ve vašem Telegramu, vše je nastaveno správně.[/I]


--- [B][COLOR {Colors.ORANGE}] [ Mau!X ER '2026 ] [/COLOR][/B] ---

"""