# -*- coding: utf-8 -*-
#
import copy
import math
import os

from django.conf import settings

from reportlab.platypus import Table, SimpleDocTemplate, Paragraph, TableStyle, PageBreak
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.graphics.samples.excelcolors import *

from common.utils.timezone import local_now_display
from settings.utils import get_login_title
from reports import const as c


SONG_FONT = 'song'
FONT_PATH = os.path.join(settings.APPS_DIR, 'reports', 'tools', 'font', 'FeiHuaSongTi-2.ttf')
pdfmetrics.registerFont(TTFont(SONG_FONT, FONT_PATH))
CLASSIC_GREEN = HexColor('#328E76')


class PDFDocument(object):
    def __init__(self, filepath, data, **kwargs):
        self.content = []
        self.data = data
        self.font_name = SONG_FONT
        self.font_size = 8
        self.left_margin = 12 * mm
        self.right_margin = 12 * mm
        self._doc = SimpleDocTemplate(
            filepath, pagesize=A4, topMargin=8 * mm,
            leftMargin=self.left_margin, rightMargin=self.right_margin
        )
        self._generate_style(kwargs)

    def _generate_style(self, kwargs):
        styles = getSampleStyleSheet()
        self.title_style = ParagraphStyle(
            'title', parent=styles['Title'], fontName=self.font_name,
            spaceAfter=20
        )
        self.h3_style = ParagraphStyle(
            'h3', parent=styles['Heading3'], fontName=self.font_name,
            textColor=CLASSIC_GREEN
        )
        self.h4_style = ParagraphStyle(
            'h4', parent=styles['Heading4'], fontName=self.font_name,
        )
        self.text_style = ParagraphStyle(
            'body', parent=styles['BodyText'], fontName=self.font_name,
            fontSize=self.font_size, spaceAfter=6,
            firstLineIndent=self.font_size * 2
        )
        self.table_text_style = ParagraphStyle(
            'body', parent=styles['BodyText'], fontName=self.font_name,
            fontSize=self.font_size
        )
        self.ul_style = ParagraphStyle(
            'ul', parent=styles['BodyText'], fontName=self.font_name, fontSize=self.font_size,
            bulletFontSize=self.font_size, bulletIndent=self.font_size * 2
        )
        self.table_style = TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ('BOX', (0, 0), (-1, -1), 0.50, colors.black),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),  # 内部网格线
            ('BACKGROUND', (0, 0), (-1, 0), '#D6DCE4'),  # 表头背景颜色
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),  # 表头文本颜色
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),  # 表头底部边距
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),  # 数据行的文本颜色
            ('FONTNAME', (0, 0), (-1, -1), self.font_name),  # 数据行的字体
            ('FONTSIZE', (0, 0), (-1, -1), self.font_size),  # 数据行的字体大小
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # 所有单元格的垂直对齐方式为居中
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ])
        if t_style := kwargs.get('table_style'):
            self.table_style += t_style

    def _draw_chart(self, data, chart_type):
        if not data:
            return
        if chart_type == c.BAR:
            self._draw_bar(data)
        elif chart_type == c.LINE_PLOT:
            self._draw_line_plot(data)
        elif chart_type == c.PIE:
            self._draw_pie(data)

    def _draw_table(self, data, ident=None):
        if ident is None:
            ident = self.font_size * 2

        class IndentedTable(Table):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            def drawOn(self, c, x, y, _sW=0):
                super().drawOn(c, x + ident, y, _sW)

        table_style = copy.copy(self.table_style)
        # 只有标题的情况下，给做个空表格
        if len(data) == 1:
            table_style.add('SPAN', (0, 1), (-1, 1))
            data.append(['无内容'])

        result = []
        for d in data:
            result.append([Paragraph(str(i), self.table_text_style) for i in d])

        table = IndentedTable(
            result, style=table_style, hAlign='LEFT', cornerRadii=[2] * 4,
            colWidths=(A4[0] - self.right_margin - 20 * mm) // len(result[0]),
        )
        self.content.append(table)

    def _draw_text(self, data):
        self.content.append(Paragraph(data, self.text_style))

    def _draw_list(self, data):
        self.content.append(Paragraph(f"<para><bullet>&bullet;</bullet>{data}</para>", self.ul_style))

    @staticmethod
    def __reverse_matrix(matrix, threshold=5, alias=True):
        serial_as_label = True if len(matrix) > threshold else False
        row, col, comments = [], [], []
        for serial, i in enumerate(matrix, 1):
            if serial_as_label:
                label_name = str(serial)
                alias_name = serial if alias else i[1]
                comments.append(f'{i[0]}({alias_name})')
            else:
                label_name = i[0]
                if len(label_name) > threshold:
                    label_name = f'{label_name[:3]}..{label_name[-3:]}'
            row.append(label_name)
            col.append(i[1])
        return row, col, comments

    def _draw_bar(self, data):
        # 创建柱状图
        labels, data, comments = self.__reverse_matrix(data)
        drawing = Drawing()
        bar = VerticalBarChart()
        max_data = max(data)
        step = math.ceil(max_data // len(data) / 10) * 10
        bar.setProperties({
            'x': self.left_margin, 'y': 8 * mm,
            'width': A4[0] - self.right_margin - 30 * mm, 'height': 160,
            'data': [data], 'categoryAxis.categoryNames': labels,
            'categoryAxis.labels.fontName': 'song',
            'valueAxis.valueMin': 0, 'valueAxis.valueStep': step,
            'valueAxis.valueMax': max_data + step,
            'barLabels.nudge': 10, 'barLabels.fillColor': CLASSIC_GREEN,
            'barLabelArray': [[str(d) for d in data]],
            'barLabelFormat': 'values'
        })
        bar.bars[0].fillColor = CLASSIC_GREEN
        drawing.add(bar)
        self.content.append(drawing)
        if comments:
            comment_str = ' '.join(comments)
            self.content.append(Paragraph(comment_str, self.text_style))

    def _draw_line_plot(self, data):
        # 创建柱状图
        labels, data, comments = self.__reverse_matrix(data)
        drawing = Drawing()
        line_plot = HorizontalLineChart()
        max_data = max(data)
        step = math.ceil(max_data // len(data) / 10) * 10
        line_plot.setProperties({
            'x': self.left_margin, 'y': 8 * mm,
            'width': A4[0] - self.right_margin - 30 * mm, 'height': 160,
            'data': [data], 'categoryAxis.categoryNames': labels,
            'categoryAxis.labels.fontName': 'song',
            'valueAxis.valueMin': 0, 'valueAxis.valueStep': step,
            'valueAxis.valueMax': max_data + step,
            'lineLabelNudge': 12, 'lineLabels.fillColor': CLASSIC_GREEN,
            'lineLabelArray': [[str(d) for d in data]],
            'lineLabelFormat': 'values',
        })
        line_plot.lines[0].strokeColor = CLASSIC_GREEN
        line_plot.lines[0].strokeWidth = 2
        drawing.add(line_plot)
        self.content.append(drawing)
        if comments:
            comment_str = ' '.join(comments)
            self.content.append(Paragraph(comment_str, self.text_style))

    @staticmethod
    def get_color_comment(comments):
        custom_colors = [
            color01, color02, color03, color04, color05, color06,
            color07, color08, color09, color10, color01Light, color02Light,
            color03Light, color04Light, color05Light, color06Light, color07Light
        ]
        return list(zip(custom_colors[:len(comments)], comments))

    def _draw_pie(self, data):
        labels, data, comments = self.__reverse_matrix(data, alias=False)
        drawing, pie, legend = Drawing(), Pie(), Legend()
        data_colors = self.get_color_comment(comments)
        legend.setProperties({
            'x': 200, 'y': 150, 'dy': 8, 'dx': 8, 'alignment': 'right',
            'colorNamePairs': data_colors, 'fontName': 'song',
            'columnMaximum': 5
        })
        pie.setProperties({
            'x': self.left_margin, 'y': 8 * mm, 'data': data,
            'width': 150, 'height': 150,
        })
        for index, item in enumerate(data_colors):
            pie.slices[index].fillColor = item[0]
        drawing.add(legend)
        drawing.add(pie)
        self.content.append(drawing)

    def first_page(self, c, doc):
        c.saveState()
        # 设置填充色
        c.setFillColor(CLASSIC_GREEN)
        # 设置字体大小
        c.setFont(self.font_name, 30)
        # 绘制居中标题文本
        c.drawCentredString(A4[0] / 2, A4[1] / 2, get_login_title())
        # 绘制时间
        c.setFont(self.font_name, 15)
        c.drawCentredString(A4[0] / 2, A4[1] / 2 - 30, local_now_display())
        c.restoreState()

    def later_pages(self, c, doc):
        c.saveState()
        # 设置页头
        c.setFillColor(CLASSIC_GREEN)
        c.rect(0, A4[1] - 8 * mm, A4[0], 8 * mm, stroke=0, fill=1)
        c.setFont(self.font_name, 10)
        c.setFillColor(colors.white)
        c.drawCentredString(A4[0] / 2, A4[1] - 5 * mm, get_login_title())
        # 设置页尾
        c.setFillColor(CLASSIC_GREEN)
        c.rect(0, 0, A4[0], 8 * mm, stroke=0, fill=1)
        c.setFont(self.font_name, 9)
        c.setFillColor(colors.white)
        c.drawCentredString(A4[0] - 30, 2.5 * mm, f'{doc.page - 1}')
        c.drawCentredString(30 * mm, 2.5 * mm, f'杭州飞致云信息科技有限责任公司')
        c.restoreState()

    def rander_content(self):
        for report in self.data:
            self.content.append(PageBreak())
            first_title, summary, first_data = report['title'], report['summary'], report['data']
            self.content.append(Paragraph(first_title, self.title_style))
            self.content.append(Paragraph(summary, self.text_style))
            for seria, sec_data in enumerate(first_data, 1):
                sec_title, sec_data = sec_data['title'], sec_data['data']
                self.content.append(Paragraph(f'{seria}.{sec_title}', self.h3_style))
                for data in sec_data:
                    _type, _data = data['type'], data['data']
                    if _type == c.TEXT:
                        self._draw_text(_data)
                    elif _type == c.UNSIGNED_LIST:
                        self._draw_list(_data)
                    elif _type == c.TABLE:
                        self._draw_table(_data, ident=self.font_size * 2)
                    elif _type[:11] == c.TABLE_CHART:
                        self._draw_chart(_data[1:], _type[12:])
                        self._draw_table(_data)

    def save(self):
        self.rander_content()
        self._doc.build(
            self.content, onFirstPage=self.first_page, onLaterPages=self.later_pages
        )
