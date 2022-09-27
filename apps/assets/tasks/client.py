import paramiko
import socket
import time

from paramiko.ssh_exception import AuthenticationException, SSHException
from django.utils.translation import ugettext as _

from common.utils import get_logger


logger = get_logger(__file__)


class CustomSSHClient:
    def __init__(self):
        self.client = None
        self.init()

    def init(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def connect(self, **connect_params):
        dark_msg = ''
        try:
            self.client.connect(**connect_params)
        except AuthenticationException as err:
            dark_msg = err
        except SSHException as err:
            dark_msg = err
        except Exception as err:
            dark_msg = err
        return dark_msg

    def exec_commands(self, commands, charset='utf8'):
        if self.client is None:
            return
        channel = self.client.invoke_shell()
        # 读取首次登陆终端返回的消息
        channel.recv(4096)
        # 终端登陆有延迟，等终端有返回后再执行命令
        time.sleep(40)
        result = ''
        for command in commands:
            try:
                channel.send(command + '\n')
            except socket.error as e:
                result += _('Command execution is interrupted, network problems or command errors. '
                            'See the backend log output for details')
                logger.warning('自定义改密平台执行改密失败，原因: %s', str(e))
                break
            time.sleep(3)
            result += channel.recv(1024).decode(encoding=charset)
        channel.close()
        self.client.close()
        return result

    @staticmethod
    def is_login_success(err):
        return isinstance(err, AuthenticationException)

    def close(self):
        self.client.close()
