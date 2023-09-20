import os

from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage

from common.utils.timezone import local_now_date_display
from .tasks.report.common import get_report_templates
from .tools.pdf import PDFDocument


class ReportFileHandler(object):
    def __init__(self, execution):
        self.execution = execution
        self.file_type = execution.report.file_type
        self.rel_path, self.abs_path = self._get_filepath()

    def _get_filepath(self):
        part_path = os.path.join('reports', local_now_date_display(), self.file_type)
        report_dir = os.path.join(default_storage.location, part_path)
        os.makedirs(report_dir, exist_ok=True, mode=0o755)
        filename = f'{str(self.execution.id)}.{self.file_type}'
        rel_path = os.path.join(part_path, filename)
        abs_path = os.path.join(default_storage.location, rel_path)
        return rel_path, abs_path

    def _save_with_pdf(self, data):
        pdf_document = PDFDocument(self.abs_path, data)
        pdf_document.save()
        return self.rel_path

    def _get_report_class(self):
        valid = []
        templates = get_report_templates()
        for class_name, item in templates.items():
            if class_name in self.execution.report.category:
                valid.append(item)
        return valid

    def _save(self, data):
        save_func = getattr(self, f'_save_with_{self.file_type}')
        return save_func(data)

    def run(self):
        """
        1、根据execution的报表分类获取报表的类
        2、根据报表的类获取文件类型的数据
        3、生成每个分类报表的片段文件
        4、整合各个分片文件到一个整体文件中
        """
        if not self.execution.report.is_active:
            raise ValueError(_('Report not activated'))

        data = []
        for report_class in self._get_report_class():
            instance = report_class(
                file_type=self.file_type, period=self.execution.report.period
            )
            instance_data = instance.generate_data()
            if not instance_data:
                continue

            data.append({
                'title': instance.get_title(),
                'summary': instance.get_summary(),
                'data': instance_data
            })
        return self._save(data)
