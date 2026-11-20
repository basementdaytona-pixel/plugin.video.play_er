"""Keep source order consistent with the current provider preference."""


def order_sources(sources, preference):
    preferred = 'webshare' if preference == 'WEBSHARE.CZ' else 'prehraj'
    return sorted(sources, key=lambda item: 0 if preferred in str(item.get('provider', '')).lower() else 1)
