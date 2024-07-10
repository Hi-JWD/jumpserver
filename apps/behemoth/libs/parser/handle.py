import ctypes
import os
import platform

from typing import List

from django.conf import settings

from common.utils import get_logger


if platform.system() == "Darwin":
    so_dir = 'parse_darwin.so'
else:
    so_dir = 'parse_linux.so'


logger = get_logger(__file__)

lib = ctypes.CDLL(os.path.join(settings.APPS_DIR, 'behemoth', 'libs', 'parser', so_dir))
lib.Parse.argtypes = [ctypes.c_char_p] # noqa
lib.Parse.restype = ctypes.c_char_p


def parse_sql(sql: str) -> List[str]:
    try:
        result = lib.Parse(sql.encode('utf-8'))
        result.decode('utf-8').split('\n')
    except Exception as e: # noqa
        logger.error('Parse sql error: %s' % e)
        result = ''
    return result
