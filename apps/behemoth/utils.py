import json

from typing import Callable, Any

from Crypto.Cipher import AES  # noqa
from Crypto.Util.Padding import pad, unpad # noqa


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
