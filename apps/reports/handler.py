import os

from datetime import timedelta

from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage
from django.utils.dateparse import parse_datetime

from common.utils.timezone import local_now_date_display, local_now, as_current_tz
from .tasks.report.common import get_report_templates
from .tools.pdf import PDFDocument


class ReportFileHandler(object):
    def __init__(self, execution):
        self.execution = execution
        self.statistical_cycle = execution.report.statistical_cycle
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

    def _compute_statistical_cycle(self):
        if period := self.statistical_cycle.get('period'):
            end = local_now()
            start = end - timedelta(days=int(period))
        else:
            start = as_current_tz(parse_datetime(self.statistical_cycle.get('dateStart')))
            end = as_current_tz(parse_datetime(self.statistical_cycle.get('dateEnd')))
        return start, end

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
        date_start, date_end = self._compute_statistical_cycle()
        for report_class in self._get_report_class():
            instance = report_class(
                file_type=self.file_type, date_start=date_start, date_end=date_end
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
