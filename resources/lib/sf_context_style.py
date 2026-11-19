"""Menu labels only. Standalone, dependency-free except lazy Kodi translations.

Distributed into each addon's own import path; never changes action commands.
"""
import re

_TAGS = re.compile(r'\[/?(?:COLOR(?:\s+[^\]]+)?|B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE)\]', re.I)
_REFERENCE = re.compile(r'\$(ADDON|LOCALIZE)\[([^\]]+)\]')
_ICONS = '•▷✓✗☆♡☰⤓↻↵↑↓↗↔⚙ℹ★♥▶'
_DECORATION = _ICONS + '►◄◁○⬓| '


def preferences():
    return {'dot_color': 'orange', 'uppercase': True, 'aliases': True, 'normalize_remotes': True, 'template': '[COLOR {dot_color}]• [/COLOR]{label}'}


def _localized(text):
    def resolve(match):
        try:
            if match[1] == 'ADDON':
                import xbmcaddon
                addon_id, number = match[2].rsplit(' ', 1)
                return xbmcaddon.Addon(addon_id).getLocalizedString(int(number)) or match[0]
            import xbmc
            return xbmc.getLocalizedString(int(match[2])) or match[0]
        except (ImportError, AttributeError, ValueError, RuntimeError):
            return match[0]
    return _REFERENCE.sub(resolve, text)


def label(text, command='', icon=None, options=None):
    """Return one yellow-dot label; placeholders and actions remain untouched."""
    if command == 'stay':
        return text  # PLAY.ER's non-selectable section separators.
    plain = _TAGS.sub('', _localized(str(text or ''))).strip()
    if not plain:
        return ''
    options = preferences() if options is None else options
    # REMOTES permits custom addon templates; remove its known arrow delimiter.
    legacy = '|►' in plain
    if legacy and options['normalize_remotes']:
        plain = re.sub(r'\s*\|►\s*', ' : ', plain)
        plain = re.sub(r'^\|\s*(.*?)\s*\|\s*:\s*', r'\1 : ', plain).rstrip()
        if plain.endswith(' :'):
            plain = plain[:-2].rstrip()
    # Remove edge ornaments, not arbitrary square-bracket data such as [S01].
    decoration = _DECORATION if options['normalize_remotes'] or not legacy else _DECORATION.replace('|', '')
    plain = plain.strip(decoration)
    if re.fullmatch(r'\[\s+.*\s+\]', plain, re.S):
        plain = plain[1:-1].strip().strip(decoration)
    if options['uppercase']:
        plain = '[UPPERCASE]' + plain + '[/UPPERCASE]'
    return options.get('template', '[COLOR {dot_color}]• [/COLOR]{label}').format(
        dot_color=options['dot_color'], label=plain)


def items(menu):
    """Copy (label, command) entries in their original order."""
    return [(label(entry[0], entry[1]), *entry[1:]) for entry in menu]


def labels(choices):
    """Preserve choice indices in the explicitly selected action dialogs."""
    return [label(text) for text in choices]
