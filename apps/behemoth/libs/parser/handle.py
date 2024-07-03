import ctypes
import os
import platform

from typing import List

from django.conf import settings


if platform.system() == "Darwin":
    so_dir = 'parse_darwin.so'
else:
    so_dir = 'parse_linux.so'

lib = ctypes.CDLL(os.path.join(settings.APPS_DIR, 'behemoth', 'libs', 'parser', so_dir))
lib.Parse.argtypes = [ctypes.c_char_p] # noqa
lib.Parse.restype = ctypes.c_char_p


def parse_sql(sql: str) -> List[str]:
    try:
        result = lib.Parse(sql.encode('utf-8'))
    except BaseException: # noqa
        result = ''
    return result.decode('utf-8').split('\n')
