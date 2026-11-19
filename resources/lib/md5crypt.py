# -*- coding: utf-8 -*-

##############################################################################
#
# Module: md5crypt
# Author: Mau!X ER
# Created on: 20.11.2025
# License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################

import hashlib




MAGIC = '$1$'
ITOA64 = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"




def to64 (v, n):
    ret = ''
    while (n - 1 >= 0):
        n = n - 1
        ret = ret + ITOA64[v & 0x3f]
        v = v >> 6
    return ret


def apache_md5_crypt (pw, salt):

    return unix_md5_crypt(pw, salt, '$apr1$')


def unix_md5_crypt(pw, salt, magic=None):
    if magic == None:
        magic = MAGIC

    if salt[:len(magic)] == magic:
        salt = salt[len(magic):]

    salt = salt.split('$', 1)[0]
    salt = salt[:8]

    pw_bytes = pw.encode('utf-8')
    salt_bytes = salt.encode('utf-8')
    magic_bytes = magic.encode('utf-8')

    ctx = pw_bytes + magic_bytes + salt_bytes
    final = hashlib.md5(pw_bytes + salt_bytes + pw_bytes).digest()

    for pl in range(len(pw),0,-16):
        ctx += final[:16 if pl > 16 else pl]

    i = len(pw)
    while i:
        if i & 1:
            ctx += b'\x00'
        else:
            ctx += pw_bytes[0:1]
        i = i >> 1

    final = hashlib.md5(ctx).digest()

    for i in range(1000):
        ctx1 = b''

        if i & 1:
            ctx1 += pw_bytes
        else:
            ctx1 += final

        if i % 3:
            ctx1 += salt_bytes

        if i % 7:
            ctx1 += pw_bytes

        if i & 1:
            ctx1 += final
        else:
            ctx1 += pw_bytes

        final = hashlib.md5(ctx1).digest()

    passwd = ''
    passwd += to64((final[0] << 16) | (final[6] << 8) | final[12], 4)
    passwd += to64((final[1] << 16) | (final[7] << 8) | final[13], 4)
    passwd += to64((final[2] << 16) | (final[8] << 8) | final[14], 4)
    passwd += to64((final[3] << 16) | (final[9] << 8) | final[15], 4)
    passwd += to64((final[4] << 16) | (final[10] << 8) | final[5], 4)
    passwd += to64(final[11], 2)

    return magic + salt + '$' + passwd



md5crypt = unix_md5_crypt

if __name__ == "__main__":
    print (unix_md5_crypt("cat", "hat"))
