import json

from typing import Any

from Crypto.Cipher import AES  # noqa
from Crypto.Util.Padding import pad, unpad # noqa
from termcolor import COLORS

from common.utils.timezone import local_now_display


# 加密函数
def encrypt(plaintext, key):
    cipher = AES.new(key, AES.MODE_CBC)
    ciphertext = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return cipher.iv + ciphertext


def decrypt(ciphertext, key):
    iv = ciphertext[:AES.block_size]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext[AES.block_size:]), AES.block_size)
    return plaintext.decode()


def encrypt_json_file(filepath: str, secret: str) -> str:
    with open(filepath) as raw_file:
        content = raw_file.read()

    encrypt_filepath = '%s.jm' % filepath
    with open(encrypt_filepath, 'wb') as encrypted_file:
        encrypted_data: Any = encrypt(content, secret.encode())
        encrypted_file.write(encrypted_data)
    return encrypt_filepath


def decrypt_json_file(file_path: str, secret: str) -> None:
    with open(file_path, 'rb') as encrypted_file:
        encrypted_data = encrypted_file.read()

    decrypted_data = decrypt(encrypted_data, secret)
    data = json.loads(decrypted_data)
    return data


class ColoredPrinter(object):
    _red = 'light_red'
    _green = 'light_green'
    _cyan = 'cyan'
    _light_cyan = 'light_cyan'
    _yellow = 'light_yellow'
    _grey = 'light_grey'
    _white = 'white'
    _light_blue = 'light_blue'

    @staticmethod
    def polish(text, color, has_time=True):
        fmt = u"\033[%sm%s\033[0m"
        color_code = u'0;%s' % COLORS[color]
        content = u"\n".join([fmt % (color_code, t) for t in text.split(u'\n')])
        if has_time:
            content = f'{local_now_display()}: {content}'
        return f'{content}\n'

    def title(self, msg, level=20):
        msg = f'{"-" * level} {msg} {"-" * level}'
        return self.polish(has_time=False, text=msg, color=self._light_blue)

    def field(self, field, msg):
        msg = f'\033[1m{field}\033[0m: {msg}'
        return self.polish(has_time=False, text=msg, color=self._white)

    def red(self, text):
        return self.polish(text=text, color=self._red)

    def green(self, text):
        return self.polish(text=text, color=self._green)

    def cyan(self, text):
        return self.polish(text=text, color=self._cyan)

    def light_cyan(self, text):
        return self.polish(text=text, color=self._light_cyan)

    def yellow(self, text):
        return self.polish(text=text, color=self._yellow)

    def info(self, text):
        return self.polish(text=text, color=self._grey)

    def line(self, output='=', length=60):
        text = '{}{}'.format('\n', output * length)
        return self.polish(text=text, color=self._white, has_time=False)


colored_printer = ColoredPrinter()
