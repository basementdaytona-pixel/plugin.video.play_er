#!/usr/bin/env python3


"""
  Yatse Kodi Starter: samostatný instalátor, aktualizace a odinstalace.

  -- Nespouštět přes sudo.  Instalátor obsahuje vlastní kód UDP služby, takže
     k instalaci stačí jediný soubor. Druhý soubor je k dispozici pro kontrolu.

  VOLBY : --install, --status, --test, --uninstall, --yes, --purge-logs.
  Bez voleb nabídne přehledné menu.


  WAYLAND WAKE-UP MONITORS FROM SSH :

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export WAYLAND_DISPLAY="$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -type s -name 'wayland-*' -printf '%f\n' | head -n1)"
export QT_QPA_PLATFORM=wayland
export XDG_SESSION_TYPE=wayland

kscreen-doctor --dpms on

"""

import argparse
import base64
import configparser
import ipaddress
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys


# Vygenerováno z kompletního souboru YATSE---LINUX-UDP-STARTER.py.

PAYLOAD = 'IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwoiIiJZYXRzZSBVRFAgd2FrZSAtPiBLb2RpIChLREUgV2F5bGFuZC9YMTEsIEZsYXRwYWsvbmF0aXZlKS4KClJ1biBhcyBhbiB1bnByaXZpbGVnZWQgdXNlci4gIERldGVjdCBhIFJFQUwgS29kaSBleGVjdXRhYmxlLCBuZXZlciBhcmJpdHJhcnkKY29tbWFuZC1saW5lIGFyZ3VtZW50czogYW4gb3BlbiBLb2RpIGZpbGUgaW4gS1dyaXRlIG11c3Qgbm90IGJsb2NrIGxhdW5jaC4KIiIiCgppbXBvcnQgYXJncGFyc2UKaW1wb3J0IGNvbmZpZ3BhcnNlcgppbXBvcnQgaXBhZGRyZXNzCmltcG9ydCBvcwpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKaW1wb3J0IHJlCmltcG9ydCBzaGxleAppbXBvcnQgc29ja2V0CmltcG9ydCBzdGF0CmltcG9ydCBzdWJwcm9jZXNzCmltcG9ydCBzeXMKaW1wb3J0IHRpbWUKCkNPTkZJRyA9IFBhdGguaG9tZSgpIC8gJy5jb25maWcveWF0c2Uta29kaS1zdGFydGVyLmNvbmYnClNUQVRFID0gUGF0aC5ob21lKCkgLyAnLmxvY2FsL3N0YXRlL3lhdHNlLWtvZGktc3RhcnRlcicKREVGQVVMVFMgPSB7CiAgICAnYmluZCc6ICcwLjAuMC4wJywKICAgICdwb3J0JzogJzU2MDAnLAogICAgJ2FsbG93ZWRfaXBzJzogJycsCiAgICAndG9rZW4nOiAnWWF0c2VTdGFydC1YYm1jJywKICAgICdzZXNzaW9uJzogJ2F1dG8nLAogICAgJ3dheWxhbmRfZGlzcGxheSc6ICd3YXlsYW5kLTAnLAogICAgJ3hfZGlzcGxheSc6ICc6MCcsCiAgICAnd2FrZV9kaXNwbGF5JzogJ3llcycsCiAgICAnZW5hYmxlX21vbml0b3InOiAnbm8nLAogICAgJ21vbml0b3InOiAnJywKICAgICdsYXVuY2hfZGVsYXknOiAnMS41JywKICAgICdtaW5fbGF1bmNoX2ludGVydmFsJzogJzgnLAogICAgJ3ZlcmlmeV9zZWNvbmRzJzogJzEyJywKICAgICdrb2RpX2NvbW1hbmQnOiAnZmxhdHBhayBydW4gdHYua29kaS5Lb2RpJywKfQoKCmRlZiBsb2cobWVzc2FnZSk6CiAgICBwcmludChmJ3t0aW1lLnN0cmZ0aW1lKCIlRiAlVCIpfSB7bWVzc2FnZX0nLCBmbHVzaD1UcnVlKQoKCmRlZiBydW4oYXJndiwgZW52LCB0aW1lb3V0PTYpOgogICAgdHJ5OgogICAgICAgIHJlc3VsdCA9IHN1YnByb2Nlc3MucnVuKGFyZ3YsIGVudj1lbnYsIHRleHQ9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzdGRvdXQ9c3VicHJvY2Vzcy5QSVBFLCBzdGRlcnI9c3VicHJvY2Vzcy5QSVBFLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRpbWVvdXQ9dGltZW91dCwgY2hlY2s9RmFsc2UpCiAgICBleGNlcHQgKE9TRXJyb3IsIHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQpIGFzIGV4YzoKICAgICAgICBsb2coZidWQVJPVsOBTsONOiB7YXJndlswXX0gc2UgbmVwb2RhxZlpbG8gcHJvdsOpc3Q6IHtleGN9JykKICAgICAgICByZXR1cm4gTm9uZQogICAgaWYgcmVzdWx0LnJldHVybmNvZGU6CiAgICAgICAgbWVzc2FnZSA9IChyZXN1bHQuc3RkZXJyIG9yIHJlc3VsdC5zdGRvdXQpLnN0cmlwKCkKICAgICAgICBsb2coZidWQVJPVsOBTsONOiB7YXJndlswXX0gc2tvbsSNaWwge3Jlc3VsdC5yZXR1cm5jb2RlfToge21lc3NhZ2VbOjkwMF19JykKICAgIHJldHVybiByZXN1bHQKCgpkZWYga29kaV9waWQocHJvY19yb290PVBhdGgoJy9wcm9jJykpOgogICAgIiIiQ2hlY2sgKmV4ZWN1dGFibGUgbmFtZSosIG5vdCBmdWxsIGFyZ3YgKGZpeGVzIEtXcml0ZSBmYWxzZSBwb3NpdGl2ZXMpLgoKICAgIEJvdGggRmxhdHBhayBLb2RpIGFuZCBuYXRpdmUgS29kaSBub3JtYWxseSBleGVjdXRlIGEgYmluYXJ5IG5hbWVkIGtvZGkuYmluLgogICAgQW4gZXhlY3V0YWJsZSBuYW1lZCBrb2RpIGlzIGFsc28gYWNjZXB0ZWQuIFpvbWJpZXMgZG8gbm90IGNvdW50LgogICAgIiIiCiAgICB0cnk6CiAgICAgICAgcGF0aHMgPSBwcm9jX3Jvb3QuaXRlcmRpcigpCiAgICAgICAgZm9yIHBhdGggaW4gcGF0aHM6CiAgICAgICAgICAgIGlmIG5vdCBwYXRoLm5hbWUuaXNkZWNpbWFsKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBwYXRoLnN0YXQoKS5zdF91aWQgIT0gb3MuZ2V0dWlkKCk6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgIGNvbW0gPSAocGF0aCAvICdjb21tJykucmVhZF90ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGV4ZSA9IG9zLnBhdGguYmFzZW5hbWUob3MucmVhZGxpbmsocGF0aCAvICdleGUnKSkucmVtb3Zlc3VmZml4KCcgKGRlbGV0ZWQpJykKICAgICAgICAgICAgICAgIGV4Y2VwdCBPU0Vycm9yOgogICAgICAgICAgICAgICAgICAgIGV4ZSA9ICcnCiAgICAgICAgICAgICAgICBpZiBjb21tIG5vdCBpbiAoJ2tvZGknLCAna29kaS5iaW4nKSBhbmQgZXhlIG5vdCBpbiAoJ2tvZGknLCAna29kaS5iaW4nKToKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgc3RhdHVzID0gKHBhdGggLyAnc3RhdHVzJykucmVhZF90ZXh0KCkKICAgICAgICAgICAgICAgIGlmIHJlLnNlYXJjaChyJ15TdGF0ZTpccytbWlhdXGInLCBzdGF0dXMsIHJlLk0pOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICByZXR1cm4gaW50KHBhdGgubmFtZSkKICAgICAgICAgICAgZXhjZXB0IChPU0Vycm9yLCBVbmljb2RlRXJyb3IpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgIGV4Y2VwdCBPU0Vycm9yIGFzIGV4YzoKICAgICAgICBsb2coZidDSFlCQToga29udHJvbGEgcHJvY2Vzxa8gL3Byb2Mgc2VsaGFsYToge2V4Y30nKQogICAgcmV0dXJuIE5vbmUKCgpkZWYgd2F5bGFuZF9zb2NrZXQocnVudGltZSwgcHJlZmVycmVkKToKICAgIHJvb3QgPSBQYXRoKHJ1bnRpbWUpCiAgICBjYW5kaWRhdGVzID0gKFtyb290IC8gcHJlZmVycmVkXSBpZiBwcmVmZXJyZWQgZWxzZSBbXSkgKyBzb3J0ZWQocm9vdC5nbG9iKCd3YXlsYW5kLSonKSkKICAgIGZvciBwYXRoIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgaWYgJy8nIGluIHBhdGgubmFtZSBvciBwYXRoLm5hbWUuc3RhcnRzd2l0aCgnLicpIG9yIHBhdGgubmFtZS5lbmRzd2l0aCgnLmxvY2snKToKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIHN0YXQuU19JU1NPQ0socGF0aC5zdGF0KCkuc3RfbW9kZSk6CiAgICAgICAgICAgICAgICByZXR1cm4gcGF0aC5uYW1lCiAgICAgICAgZXhjZXB0IE9TRXJyb3I6CiAgICAgICAgICAgIHBhc3MKICAgIHJldHVybiBOb25lCgoKZGVmIGdyYXBoaWNhbF9lbnZpcm9ubWVudChjKToKICAgIGVudiA9IG9zLmVudmlyb24uY29weSgpCiAgICBydW50aW1lID0gZicvcnVuL3VzZXIve29zLmdldHVpZCgpfScKICAgIGVudlsnWERHX1JVTlRJTUVfRElSJ10gPSBydW50aW1lCiAgICBlbnZbJ0RCVVNfU0VTU0lPTl9CVVNfQUREUkVTUyddID0gZid1bml4OnBhdGg9e3J1bnRpbWV9L2J1cycKICAgIGVudi5zZXRkZWZhdWx0KCdYREdfQ1VSUkVOVF9ERVNLVE9QJywgJ0tERScpCiAgICBwcmVmZXJyZWQgPSBjLmdldCgnd2F5bGFuZF9kaXNwbGF5JywgJ3dheWxhbmQtMCcpLnN0cmlwKCkKICAgIGRpc3BsYXkgPSB3YXlsYW5kX3NvY2tldChydW50aW1lLCBwcmVmZXJyZWQpCiAgICBzZXNzaW9uID0gY1snc2Vzc2lvbiddLnN0cmlwKCkubG93ZXIoKQogICAgaWYgc2Vzc2lvbiA9PSAnYXV0byc6CiAgICAgICAgc2Vzc2lvbiA9ICd3YXlsYW5kJyBpZiBkaXNwbGF5IGVsc2UgJ3gxMScKICAgIGlmIHNlc3Npb24gbm90IGluICgneDExJywgJ3dheWxhbmQnKToKICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCdzZXNzaW9uIG11c8OtIGLDvXQgYXV0by93YXlsYW5kL3gxMScpCiAgICBlbnZbJ1hER19TRVNTSU9OX1RZUEUnXSA9IHNlc3Npb24KICAgIGlmIHNlc3Npb24gPT0gJ3dheWxhbmQnOgogICAgICAgIGlmIGRpc3BsYXkgaXMgTm9uZToKICAgICAgICAgICAgbG9nKGYnQ0hZQkE6IHYge3J1bnRpbWV9IG5lZXhpc3R1amUgV2F5bGFuZCBzb2NrZXQ7IHDFmWlobGFzIHNlIGRvIEtERScpCiAgICAgICAgICAgIHJldHVybiBOb25lLCBzZXNzaW9uCiAgICAgICAgZW52WydXQVlMQU5EX0RJU1BMQVknXSA9IGRpc3BsYXkKICAgICAgICBlbnZbJ1FUX1FQQV9QTEFURk9STSddID0gJ3dheWxhbmQ7eGNiJwogICAgICAgIGVudi5zZXRkZWZhdWx0KCdESVNQTEFZJywgYy5nZXQoJ3hfZGlzcGxheScsICc6MCcpLnN0cmlwKCkgb3IgJzowJykKICAgIGVsc2U6CiAgICAgICAgZW52LnBvcCgnV0FZTEFORF9ESVNQTEFZJywgTm9uZSkKICAgICAgICBlbnZbJ0RJU1BMQVknXSA9IGMuZ2V0KCd4X2Rpc3BsYXknLCAnOjAnKS5zdHJpcCgpIG9yICc6MCcKICAgICAgICBlbnZbJ1FUX1FQQV9QTEFURk9STSddID0gJ3hjYicKICAgICAgICBpZiBub3QgUGF0aCgnL3RtcC8uWDExLXVuaXgvWCcgKyBlbnZbJ0RJU1BMQVknXS5sc3RyaXAoJzonKS5zcGxpdCgnLicpWzBdKS5leGlzdHMoKToKICAgICAgICAgICAgbG9nKGYnVkFST1bDgU7DjTogWDExIHNvY2tldCBwcm8gRElTUExBWT17ZW52WyJESVNQTEFZIl19IG5lbmFsZXplbicpCiAgICByZXR1cm4gZW52LCBzZXNzaW9uCgoKZGVmIHJvdGF0ZV9sb2coKToKICAgIFNUQVRFLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHBhdGggPSBTVEFURSAvICdrb2RpLWxhdW5jaC5sb2cnCiAgICBpZiBwYXRoLmV4aXN0cygpIGFuZCBwYXRoLnN0YXQoKS5zdF9zaXplID4gNCAqIDEwMjQgKiAxMDI0OgogICAgICAgIG9sZGVyID0gU1RBVEUgLyAna29kaS1sYXVuY2gubG9nLm9sZCcKICAgICAgICBvbGRlci51bmxpbmsobWlzc2luZ19vaz1UcnVlKQogICAgICAgIHBhdGgucmVwbGFjZShvbGRlcikKICAgIHJldHVybiBwYXRoCgoKZGVmIGdldF9jb25maWcoKToKICAgIHBhcnNlciA9IGNvbmZpZ3BhcnNlci5Db25maWdQYXJzZXIoaW50ZXJwb2xhdGlvbj1Ob25lKQogICAgcGFyc2VyWydzdGFydGVyJ10gPSBERUZBVUxUUy5jb3B5KCkKICAgIHBhcnNlci5yZWFkKENPTkZJRywgZW5jb2Rpbmc9J3V0Zi04JykKICAgIGMgPSBwYXJzZXJbJ3N0YXJ0ZXInXQogICAgcG9ydCA9IGMuZ2V0aW50KCdwb3J0JykKICAgIGlmIG5vdCAxIDw9IHBvcnQgPD0gNjU1MzU6CiAgICAgICAgcmFpc2UgVmFsdWVFcnJvcignUG9ydCBuZW7DrSB2IHJvenNhaHUgMeKAkzY1NTM1JykKICAgIHJldHVybiBjCgoKZGVmIGFsbG93ZWRfc2VuZGVyKGlwLCBlbnRyaWVzKToKICAgIGlmIG5vdCBlbnRyaWVzOgogICAgICAgIHJldHVybiBUcnVlCiAgICBzZW5kZXIgPSBpcGFkZHJlc3MuaXBfYWRkcmVzcyhpcCkKICAgIHJldHVybiBhbnkoc2VuZGVyIGluIGlwYWRkcmVzcy5pcF9uZXR3b3JrKGl0ZW0sIHN0cmljdD1GYWxzZSkgZm9yIGl0ZW0gaW4gZW50cmllcykKCgpkZWYgbGF1bmNoX2tvZGkoY29tbWFuZCwgZW52LCB2ZXJpZnlfc2Vjb25kcyk6CiAgICBsb2dmaWxlID0gcm90YXRlX2xvZygpCiAgICBsb2coZidTcG91xaF0w61tOiB7c2hsZXguam9pbihjb21tYW5kKX0nKQogICAgdHJ5OgogICAgICAgIHdpdGggbG9nZmlsZS5vcGVuKCdhYicpIGFzIGZpbGU6CiAgICAgICAgICAgIGZpbGUud3JpdGUoZidcbj09PT09IHt0aW1lLnN0cmZ0aW1lKCIlRiAlVCIpfSB8IHtzaGxleC5qb2luKGNvbW1hbmQpfSA9PT09PVxuJy5lbmNvZGUoKSkKICAgICAgICAgICAgZmlsZS5mbHVzaCgpCiAgICAgICAgICAgIHByb2MgPSBzdWJwcm9jZXNzLlBvcGVuKGNvbW1hbmQsIGN3ZD1zdHIoUGF0aC5ob21lKCkpLCBlbnY9ZW52LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzdGRpbj1zdWJwcm9jZXNzLkRFVk5VTEwsIHN0ZG91dD1maWxlLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzdGRlcnI9c3VicHJvY2Vzcy5TVERPVVQsIHN0YXJ0X25ld19zZXNzaW9uPVRydWUpCiAgICBleGNlcHQgKE9TRXJyb3IsIFZhbHVlRXJyb3IpIGFzIGV4YzoKICAgICAgICBsb2coZidDSFlCQTogc3B1xaF0xJtuw60gS29kaSBzZWxoYWxvOiB7ZXhjfScpCiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICBsb2coZidQxZnDrWtheiBvZGVzbMOhbiAoUElEIHNwb3XFoXTEm8SNZSB7cHJvYy5waWR9KTsgdsO9c3R1cDoge2xvZ2ZpbGV9JykKICAgIGRlYWRsaW5lID0gdGltZS5tb25vdG9uaWMoKSArIHZlcmlmeV9zZWNvbmRzCiAgICB3aGlsZSB0aW1lLm1vbm90b25pYygpIDwgZGVhZGxpbmU6CiAgICAgICAgcGlkID0ga29kaV9waWQoKQogICAgICAgIGlmIHBpZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgbG9nKGYnUE9UVlJaRU5POiBLb2RpIGLEm8W+w60gKFBJRCB7cGlkfSknKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGNvZGUgPSBwcm9jLnBvbGwoKQogICAgICAgICMgRmxhdHBhayBsYXVuY2hlciBtYXkgdGVybWluYXRlIG5vcm1hbGx5IGV2ZW4gaWYgaXRzIGNoaWxkIGlzIHN0YXJ0aW5nLgogICAgICAgIGlmIGNvZGUgaXMgbm90IE5vbmUgYW5kIGNvZGUgIT0gMDoKICAgICAgICAgICAgbG9nKGYnQ0hZQkE6IEZsYXRwYWsvc3BvdcWhdMSbxI0gc2tvbsSNaWwgcyBrw7NkZW0ge2NvZGV9OyB2aXoge2xvZ2ZpbGV9JykKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgdGltZS5zbGVlcCgwLjUpCiAgICBwaWQgPSBrb2RpX3BpZCgpCiAgICBpZiBwaWQ6CiAgICAgICAgbG9nKGYnUE9UVlJaRU5POiBLb2RpIGLEm8W+w60gKFBJRCB7cGlkfSknKQogICAgICAgIHJldHVybiBUcnVlCiAgICBsb2coZidORVBPVFZSWkVOTzogcHJvY2VzIEtvZGkgc2UgZG8ge3ZlcmlmeV9zZWNvbmRzOmd9IHMgbmVvYmpldmlsOyAnCiAgICAgICAgZid2w71zdHVwIHNwb3XFoXTEm8SNZToge2xvZ2ZpbGV9IChuw6F2cmF0b3bDvSBrw7NkOiB7cHJvYy5wb2xsKCl9KScpCiAgICByZXR1cm4gRmFsc2UKCgpkZWYgaGFuZGxlX3N0YXJ0KGMsIGNvbW1hbmQpOgogICAgZW52LCBzZXNzaW9uID0gZ3JhcGhpY2FsX2Vudmlyb25tZW50KGMpCiAgICBpZiBlbnYgaXMgTm9uZToKICAgICAgICByZXR1cm4gRmFsc2UKICAgICMgV2FrZSB1cCBkaXNwbGF5IGV2ZW4gd2hlbiBLb2RpIGlzIGFscmVhZHkgcnVubmluZy4KICAgIGlmIGMuZ2V0Ym9vbGVhbignd2FrZV9kaXNwbGF5Jyk6CiAgICAgICAgaWYgc2Vzc2lvbiA9PSAnd2F5bGFuZCc6CiAgICAgICAgICAgIHJ1bihbJ2tzY3JlZW4tZG9jdG9yJywgJy0tZHBtcycsICdvbiddLCBlbnYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgcnVuKFsneHNldCcsICctZGlzcGxheScsIGVudlsnRElTUExBWSddLCAnZHBtcycsICdmb3JjZScsICdvbiddLCBlbnYpCiAgICBtb25pdG9yID0gY1snbW9uaXRvciddLnN0cmlwKCkKICAgIGlmIG1vbml0b3IgYW5kIGMuZ2V0Ym9vbGVhbignZW5hYmxlX21vbml0b3InKSBhbmQgc2Vzc2lvbiA9PSAnd2F5bGFuZCc6CiAgICAgICAgaWYgcmUuZnVsbG1hdGNoKHInW0EtWmEtejAtOV8uLV0rJywgbW9uaXRvcik6CiAgICAgICAgICAgIHJ1bihbJ2tzY3JlZW4tZG9jdG9yJywgZidvdXRwdXQue21vbml0b3J9LmVuYWJsZSddLCBlbnYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgbG9nKCdWQVJPVsOBTsONOiBuZXBsYXRuw70gbW9uaXRvciB2IGtvbmZpZ3VyYWNpJykKICAgIHBpZCA9IGtvZGlfcGlkKCkKICAgIGlmIHBpZCBpcyBub3QgTm9uZToKICAgICAgICBsb2coZidLb2RpIGppxb4gc2t1dGXEjW7EmyBixJvFvsOtIChQSUQge3BpZH0pOyBkcnVow70gcHJvY2VzIG5lc3BvdcWhdMOtbScpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGRlbGF5ID0gbWF4KDAuMCwgbWluKDE1LjAsIGMuZ2V0ZmxvYXQoJ2xhdW5jaF9kZWxheScpKSkKICAgIGlmIGRlbGF5OgogICAgICAgIHRpbWUuc2xlZXAoZGVsYXkpCiAgICBpZiBrb2RpX3BpZCgpIGlzIG5vdCBOb25lOgogICAgICAgIGxvZygnS29kaSBtZXppdMOtbSBuYWLEm2hsbzsgZHJ1aG91IGluc3RhbmNpIG5lc3BvdcWhdMOtbScpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIHJldHVybiBsYXVuY2hfa29kaShjb21tYW5kLCBlbnYsIG1heCgxLjAsIG1pbig0NS4wLCBjLmdldGZsb2F0KCd2ZXJpZnlfc2Vjb25kcycpKSkpCgoKZGVmIG1haW4oKToKICAgIHBhcnNlciA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKGRlc2NyaXB0aW9uPSdZYXRzZSBVRFAgLT4gS0RFIEtvZGkgc3RhcnRlcicpCiAgICBwYXJzZXIuYWRkX2FyZ3VtZW50KCctLWNoZWNrJywgYWN0aW9uPSdzdG9yZV90cnVlJywgaGVscD0nZGlhZ25vc3Rpa2EgYmV6IHNwdcWhdMSbbsOtIEtvZGknKQogICAgcGFyc2VyLmFkZF9hcmd1bWVudCgnLS10ZXN0LXN0YXJ0JywgYWN0aW9uPSdzdG9yZV90cnVlJywgaGVscD0nbcOtc3Ruw60gdGVzdCBzdGFydHUgYmV6IHRlbGVmb251JykKICAgIGFyZ3MgPSBwYXJzZXIucGFyc2VfYXJncygpCiAgICBjID0gZ2V0X2NvbmZpZygpCiAgICBjb21tYW5kID0gc2hsZXguc3BsaXQoY1sna29kaV9jb21tYW5kJ10pCiAgICBpZiBub3QgY29tbWFuZDoKICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCdQcsOhemRuw70ga29kaV9jb21tYW5kJykKICAgIGlmIGFyZ3MuY2hlY2s6CiAgICAgICAgZW52LCBzZXNzaW9uID0gZ3JhcGhpY2FsX2Vudmlyb25tZW50KGMpCiAgICAgICAgbG9nKGYnS29uZmlndXJhY2U6IHtDT05GSUd9OyByZWxhY2U6IHtzZXNzaW9ufScpCiAgICAgICAgbG9nKGYnV0FZTEFORF9ESVNQTEFZPXtlbnYuZ2V0KCJXQVlMQU5EX0RJU1BMQVkiKSBpZiBlbnYgZWxzZSAibmVkb3N0dXBuw70ifTsgJwogICAgICAgICAgICBmJ0RJU1BMQVk9e2Vudi5nZXQoIkRJU1BMQVkiKSBpZiBlbnYgZWxzZSAibmVkb3N0dXBuw70ifScpCiAgICAgICAgbG9nKGYnS29kaSBwcm9jZXM6IHtrb2RpX3BpZCgpIG9yICJuZWLEm8W+w60ifTsgcMWZw61rYXo6IHtzaGxleC5qb2luKGNvbW1hbmQpfScpCiAgICAgICAgcmV0dXJuIDAKICAgIGlmIGFyZ3MudGVzdF9zdGFydDoKICAgICAgICBsb2coJ1JVxIxOw40gVEVTVCAoYmV6IFVEUCBhIFlhdHNlKScpCiAgICAgICAgcmV0dXJuIDAgaWYgaGFuZGxlX3N0YXJ0KGMsIGNvbW1hbmQpIGVsc2UgMQoKICAgIGFsbG93ZWQgPSBbcy5zdHJpcCgpIGZvciBzIGluIGNbJ2FsbG93ZWRfaXBzJ10uc3BsaXQoJywnKSBpZiBzLnN0cmlwKCldCiAgICBmb3IgaXRlbSBpbiBhbGxvd2VkOgogICAgICAgIGlwYWRkcmVzcy5pcF9uZXR3b3JrKGl0ZW0sIHN0cmljdD1GYWxzZSkKICAgIGlmIG5vdCBhbGxvd2VkOgogICAgICAgIGxvZygnVkFST1bDgU7DjTogYWxsb3dlZF9pcHMgamUgcHLDoXpkbsOpLCBLb2RpIG3Fr8W+ZSBzcG91xaF0xJt0IGNlbMOhIGRvc3R1cG7DoSBzw63FpScpCiAgICBjb29sZG93biA9IG1heCgwLjAsIG1pbigxMjAuMCwgYy5nZXRmbG9hdCgnbWluX2xhdW5jaF9pbnRlcnZhbCcpKSkKICAgIGxhc3RfYXR0ZW1wdCA9IGZsb2F0KCctaW5mJykKICAgIHdpdGggc29ja2V0LnNvY2tldChzb2NrZXQuQUZfSU5FVCwgc29ja2V0LlNPQ0tfREdSQU0pIGFzIHNvY2s6CiAgICAgICAgc29jay5iaW5kKChjWydiaW5kJ10sIGMuZ2V0aW50KCdwb3J0JykpKQogICAgICAgIGxvZyhmJ05hc2xvdWNow6FtIFVEUCB7Y1siYmluZCJdfTp7Y1sicG9ydCJdfTsgemRyb2pvdsOpIElQOiAnCiAgICAgICAgICAgIGYneyIsICIuam9pbihhbGxvd2VkKSBpZiBhbGxvd2VkIGVsc2UgInbFoWVjaG55In0nKQogICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgIGRhdGEsIHNlbmRlciA9IHNvY2sucmVjdmZyb20oMjA0OCkKICAgICAgICAgICAgaXAgPSBzZW5kZXJbMF0KICAgICAgICAgICAgaWYgbm90IGFsbG93ZWRfc2VuZGVyKGlwLCBhbGxvd2VkKToKICAgICAgICAgICAgICAgIGxvZyhmJ09kbcOtdG51dMOhIElQOiB7aXB9JykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNbJ3Rva2VuJ10uZW5jb2RlKCd1dGYtOCcpIG5vdCBpbiBkYXRhOgogICAgICAgICAgICAgICAgY29udGludWUgICMgSWdub3JlIHRoZSBvcmRpbmFyeSAxMDItYnl0ZSBXb0wgbWFnaWMgcGFja2V0cy4KICAgICAgICAgICAgbG9nKGYnWWF0c2UgcG/FvmFkYXZlayBvZCB7aXB9JykKICAgICAgICAgICAgaWYgdGltZS5tb25vdG9uaWMoKSAtIGxhc3RfYXR0ZW1wdCA8IGNvb2xkb3duOgogICAgICAgICAgICAgICAgbG9nKGYnT3Bha292YW7DvSBwb8W+YWRhdmVrIGlnbm9yb3bDoW4gKGludGVydmFsIHtjb29sZG93bjpnfSBzKScpCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBsYXN0X2F0dGVtcHQgPSB0aW1lLm1vbm90b25pYygpCiAgICAgICAgICAgIGhhbmRsZV9zdGFydChjLCBjb21tYW5kKQoKCmlmIF9fbmFtZV9fID09ICdfX21haW5fXyc6CiAgICB0cnk6CiAgICAgICAgc3lzLmV4aXQobWFpbigpKQogICAgZXhjZXB0IEtleWJvYXJkSW50ZXJydXB0OgogICAgICAgIHBhc3MKICAgIGV4Y2VwdCAoT1NFcnJvciwgVmFsdWVFcnJvciwgY29uZmlncGFyc2VyLkVycm9yKSBhcyBlcnJvcjoKICAgICAgICBsb2coZidDSFlCQToge2Vycm9yfScpCiAgICAgICAgc3lzLmV4aXQoMSkK'

HOME = Path.home()
BIN = HOME / '.local/bin/yatse-kodi-starter.py'
CFG = HOME / '.config/yatse-kodi-starter.conf'
UNIT = HOME / '.config/systemd/user/yatse-kodi-starter.service'
STATE = HOME / '.local/state/yatse-kodi-starter'
SERVICE = 'yatse-kodi-starter.service'

UNIT_TEXT = '''[Unit]
Description=Yatse Kodi UDP Starter (KDE Wayland/X11)
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/bin/yatse-kodi-starter.py
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
'''


def cmd(*args):
    try:
        return subprocess.run(args, text=True, capture_output=True, check=False)
    except OSError as exc:
        print(f'CHYBA: {args[0]}: {exc}')
        return None


def check_cmd(*args):
    result = cmd(*args)
    if result is None or result.returncode:
        detail = (result.stderr or result.stdout).strip() if result else 'příkaz nelze spustit'
        raise RuntimeError(f'{shlex.join(args)}: {detail}')
    return result


def ask(label, default=''):
    answer = input(f'{label} [{default}]: ').strip()
    return answer if answer else default


def choice(label, options, default):
    while True:
        result = ask(f'{label} ({"/".join(options)})', default).lower()
        if result in options:
            return result
        print('Neplatná volba.')


def yesno(label, default=True):
    return choice(label, ['ano', 'ne'], 'ano' if default else 'ne') == 'ano'


def check_user():
    if os.geteuid() == 0:
        raise RuntimeError('Nespouštěj pomocí sudo! Patří do systemd --user.')


def check_systemd():
    check_user()
    bus = Path(f'/run/user/{os.getuid()}/bus')
    if not bus.exists():
        raise RuntimeError(f'Chybí {bus}; spusť instalátor jako přihlášený uživatel KDE.')
    check_cmd('systemctl', '--user', 'show-environment')


def read_old():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CFG, encoding='utf-8')
    return cfg


def previous(old, key, fallback):
    return old.get('starter', key, fallback=fallback)


def find_display():
    path = Path(f'/run/user/{os.getuid()}')
    found = os.environ.get('WAYLAND_DISPLAY', '')
    if found and '/' not in found:
        return found
    for sock in sorted(path.glob('wayland-*')):
        try:
            if stat.S_ISSOCK(sock.stat().st_mode):
                return sock.name
        except OSError:
            pass
    return 'wayland-0'


def monitors():
    if not shutil.which('kscreen-doctor'):
        return []
    result = cmd('kscreen-doctor', '-o')
    if not result or result.returncode:
        return []
    return re.findall(r'^Output:\s*\d+\s+([\w.\-]+)', result.stdout, re.M)


def install():
    check_systemd()
    old = read_old()
    print('\n=== YATSE / KODI STARTER : INSTALACE NEBO AKTUALIZACE ===')
    print('KDE Wayland/X11 | Kodi Flatpak nebo nativní | UDP WoL port 5600\n')

    session = choice('Grafická relace', ['auto', 'wayland', 'x11'],
                     previous(old, 'session', 'auto'))
    found = monitors()
    if found:
        print('Monitory KDE:', ', '.join(found))
    monitor = ask('Monitor (pomlčka - = vypnout nastavení monitoru)',
                  previous(old, 'monitor', ''))
    if monitor == '-':
        monitor = ''
    if monitor and not re.fullmatch(r'[A-Za-z0-9_.-]+', monitor):
        raise ValueError('Neplatný název monitoru')
    wake = yesno('Probudit displej při požadavku Yatse?',
                 previous(old, 'wake_display', 'yes') == 'yes')
    enable = yesno('Povolovat vypnutý monitor přes kscreen-doctor?',
                   previous(old, 'enable_monitor', 'no') == 'yes')

    old_command = previous(old, 'kodi_command', 'flatpak run tv.kodi.Kodi')
    kind_default = 'flatpak' if old_command == 'flatpak run tv.kodi.Kodi' else (
        'native' if old_command == 'kodi' else 'custom')
    kind = choice('Instalace Kodi', ['flatpak', 'native', 'custom'], kind_default)
    command = {'flatpak': 'flatpak run tv.kodi.Kodi', 'native': 'kodi'}.get(kind)
    if kind == 'custom':
        command = ask('Příkaz spuštění Kodi', old_command)
    if not shlex.split(command):
        raise ValueError('Prázdný kodi_command')

    port = ask('UDP port Yatse (nezaměňovat s Kodi webserverem 8077)',
               previous(old, 'port', '5600'))
    if not port.isdecimal() or not 1024 <= int(port) <= 65535:
        raise ValueError('UDP port musí být v rozsahu 1024–65535')
    # Zde Enter musí znamenat opravdu žádné omezení IP, nikoli starou hodnotu.
    previous_ips = previous(old, 'allowed_ips', '').strip()
    if previous_ips:
        print(f'Dříve povolené IP: {previous_ips}')
    ips = input('Povolené IP telefonu (čárkou; Enter = všechny IP): ').strip()
    for item in (x.strip() for x in ips.split(',') if x.strip()):
        ipaddress.ip_network(item, strict=False)
    if not ips:
        print('VAROVÁNÍ: UDP start Kodi bude dostupný z celé dosažitelné sítě!')

    delay = ask('Prodleva před spuštěním v sekundách',
                previous(old, 'launch_delay', '1.5'))
    if not 0 <= float(delay) <= 15:
        raise ValueError('Prodleva musí být 0–15 s')

    config = configparser.ConfigParser(interpolation=None)
    config['starter'] = {
        'port': port,
        'bind': previous(old, 'bind', '0.0.0.0'),
        'allowed_ips': ips,
        'token': 'YatseStart-Xbmc',
        'session': session,
        'wayland_display': previous(old, 'wayland_display', find_display()),
        'x_display': previous(old, 'x_display', os.environ.get('DISPLAY', ':0')),
        'monitor': monitor,
        'wake_display': 'yes' if wake else 'no',
        'enable_monitor': 'yes' if enable else 'no',
        'launch_delay': delay,
        'min_launch_interval': previous(old, 'min_launch_interval', '8'),
        'verify_seconds': previous(old, 'verify_seconds', '12'),
        'kodi_command': command,
    }

    print('\nInstalace pro:', HOME)
    print('Příkaz Kodi:', command)
    print('Povolené IP:', ips or 'všechny')
    if not yesno('Zapsat soubory a RESTARTOVAT službu?', True):
        print('Instalace zrušena.')
        return

    for target in (BIN, CFG, UNIT):
        target.parent.mkdir(parents=True, exist_ok=True)
    # Old running service is not touched until the replacement is fully written.
    BIN.write_bytes(base64.b64decode(PAYLOAD))
    BIN.chmod(0o755)
    with CFG.open('w', encoding='utf-8') as file:
        config.write(file)
    CFG.chmod(0o600)
    UNIT.write_text(UNIT_TEXT, encoding='utf-8')
    envkeys = ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE',
               'XDG_CURRENT_DESKTOP', 'XDG_RUNTIME_DIR',
               'DBUS_SESSION_BUS_ADDRESS', 'XAUTHORITY')
    present = [key for key in envkeys if key in os.environ]
    if present:
        result = cmd('systemctl', '--user', 'import-environment', *present)
        if result and result.returncode:
            print('VAROVÁNÍ: import grafického prostředí selhal:', result.stderr.strip())
    check_cmd('systemctl', '--user', 'daemon-reload')
    check_cmd('systemctl', '--user', 'enable', SERVICE)
    # CRITICAL: enable --now does NOT restart an already running old service.
    check_cmd('systemctl', '--user', 'restart', SERVICE)
    print('\nHOTOVO: nainstalováno a STARÁ SLUŽBA BYLA RESTARTOVÁNA.')
    print('Test: python3', Path(__file__).name, '--test')
    print('Stav: systemctl --user status', SERVICE)
    print('Logy: sudo journalctl _SYSTEMD_USER_UNIT=' + SERVICE + ' -n 50 --no-pager')
    print('Odinstalace: python3', Path(__file__).name, '--uninstall')
    print('POZOR: odpojený/spící PC neprobudí tento skript, jen klasický Wake-on-LAN.')
    if monitor:
        print('Umístění okna Kodi na monitor nastav v pravidlech KWin.')


def status():
    check_user()
    print('\n=== INSTALACE / STAV ===')
    for item in (BIN, CFG, UNIT):
        print(('OK  ' if item.is_file() else 'CHYBÍ'), item)
    result = cmd('systemctl', '--user', 'status', SERVICE, '--no-pager')
    if result:
        print(result.stdout or result.stderr)
    if BIN.is_file():
        diag = cmd(sys.executable, str(BIN), '--check')
        if diag:
            print(diag.stdout or diag.stderr)


def test():
    check_user()
    if not BIN.is_file():
        raise RuntimeError('Služba ještě není nainstalována')
    print('Ruční start bez telefonu (Yatse není potřeba):\n')
    result = cmd(sys.executable, str(BIN), '--test-start')
    if result:
        print(result.stdout, end='')
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode:
            print('NEÚSPĚCH: zkontroluj:', STATE / 'kodi-launch.log')
            sys.exit(result.returncode)


def uninstall(assume_yes=False, purge_logs=False):
    check_systemd()
    print('\n=== ODINSTALACE YATSE KODI STARTER ===')
    print('Odstraním službu, její spouštěč a konfiguraci. Kodi ani Flatpak nesmažu.')
    if not assume_yes and not yesno('Opravdu odinstalovat?', False):
        print('Zrušeno.')
        return
    check_cmd('systemctl', '--user', 'disable', '--now', SERVICE)
    for path in (UNIT, BIN, CFG):
        if path.exists():
            path.unlink()
            print('Smazáno:', path)
    check_cmd('systemctl', '--user', 'daemon-reload')
    if STATE.exists() and (purge_logs or assume_yes or yesno('Smazat také diagnostické logy?', True)):
        shutil.rmtree(STATE)
        print('Smazáno:', STATE)
    print('HOTOVO. Kodi zůstalo nainstalované a nedotčené.')


def menu():
    print('\n=== YATSE / KODI STARTER ===')
    print('1) Instalovat nebo aktualizovat')
    print('2) Zobrazit stav / diagnostiku')
    print('3) Otestovat spuštění Kodi')
    print('4) Odinstalovat včetně služby')
    print('0) Konec')
    answer = input('Vyber [1]: ').strip() or '1'
    return {'1': install, '2': status, '3': test,
            '4': uninstall, '0': lambda: None}.get(answer, lambda: print('Neplatná volba.'))()


def main():
    parser = argparse.ArgumentParser(description='Yatse Kodi Starter pro KDE Linux')
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--install', action='store_true', help='instalovat nebo aktualizovat')
    actions.add_argument('--status', action='store_true', help='zobrazit stav služby')
    actions.add_argument('--test', action='store_true', help='ručně otestovat Kodi')
    actions.add_argument('--uninstall', action='store_true', help='odinstalovat včetně služby')
    parser.add_argument('-y', '--yes', action='store_true', help='potvrdit odinstalaci bez dotazu')
    parser.add_argument('--purge-logs', action='store_true', help='smazat i diagnostické logy')
    args = parser.parse_args()
    if args.install:
        install()
    elif args.status:
        status()
    elif args.test:
        test()
    elif args.uninstall:
        uninstall(assume_yes=args.yes, purge_logs=args.purge_logs)
    else:
        menu()


if __name__ == '__main__':
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print('\nZrušeno.')
    except (OSError, ValueError, RuntimeError, configparser.Error) as exc:
        sys.exit(f'CHYBA: {exc}')
