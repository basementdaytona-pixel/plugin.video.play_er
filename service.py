# -*- coding: utf-8 -*-
# FIX PRE-EMPTIVE AND FILTERS [BROADCAST REGISTERED KODI SERVICE]
from resources.lib.sharing_service import SharingListener

if __name__ == '__main__':
    # Run on the service's main thread so Kodi controls its full lifetime.
    SharingListener().run()
