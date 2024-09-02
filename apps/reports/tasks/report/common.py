# -*- coding: utf-8 -*-
#


_report_templates = {}


def get_report_templates(template_class_names=None, get_name=False):
    if template_class_names is None:
        return _report_templates

    result = {}
    for class_name, item in _report_templates.items():
        if class_name in template_class_names:
            item = str(item.NAME) if get_name else item
            result[class_name] = item
    return result


def register_report_template(report_class):
    if issubclass(report_class, BaseReport):
        _report_templates[report_class.__name__] = report_class
    return report_class


class BaseReport:
    NAME = ''

    def __init__(self, file_type, date_start, date_end, *args, **kwargs):
        self.file_type = file_type
        self.date_start = date_start
        self.date_end = date_end
        self.date_start_display = self.date_start.strftime('%Y-%m-%d %H:%M:%S')
        self.date_end_display = self.date_end.strftime('%Y-%m-%d %H:%M:%S')

    def get_title(self):
        return self.NAME

    @staticmethod
    def get_info_from_counter(counter, default_name='', default_count=0):
        try:
            item, count = counter.most_common(1)[0]
        except: # noqa
            item, count = default_name, default_count
        return item, count

    @staticmethod
    def get_summary():
        return ''

    @staticmethod
    def get_common_data():
        return []

    def generate_data(self):
        default_func = self.get_common_data
        get_data_func = getattr(
            self, f'get_{self.file_type}_data', default_func
        )
        return get_data_func()
