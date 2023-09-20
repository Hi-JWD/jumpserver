# -*- coding: utf-8 -*-
#


_report_templates = {}


def get_report_templates(template_names=None, get_name=False):
    if not template_names:
        return _report_templates

    result = {}
    for class_name, item in _report_templates.items():
        if class_name in template_names:
            item = item.NAME if get_name else item
            result[class_name] = item
    return result


def register_report_template(report_class):
    if issubclass(report_class, BaseReport):
        _report_templates[report_class.__name__] = report_class
    return report_class


class BaseReport:
    NAME = ''

    def __init__(self, file_type, period, *args, **kwargs):
        self.file_type = file_type
        self.time_period = period

    def get_title(self):
        return self.NAME

    @staticmethod
    def get_info_from_counter(counter, default_name='', default_count=0):
        try:
            item, count = counter.most_common(1)[0]
        except:
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
