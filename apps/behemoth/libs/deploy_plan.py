import os

from django.conf import settings
from django.utils.module_loading import import_string

from common.utils import get_logger


logger = get_logger(__file__)


custom_remote_pull_method = None
REMOTE_PULL_CUSTOM_FILE_PATH = os.path.join(settings.PROJECT_DIR, 'data', 'deploy', 'main.py')
try:
    custom_remote_pull_method_path = 'data.deploy.main.handle_remote_pull'
    custom_remote_pull_method = import_string(custom_remote_pull_method_path)
except Exception as e:
    logger.warning('Import custom remote_pull method failed: {}, Maybe not enabled'.format(e))
