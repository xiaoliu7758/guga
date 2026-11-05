# -*- coding: utf-8 -*-
"""咕嘎学习进度看板 —— 可视化展示学习全貌。

展示：概念掌握度分布、复习卡状态与到期数、学习风格画像、学习产物统计。
纯 PyQt5 实现，浅色风格，无外部图表依赖。
"""
from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QPolygonF
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
                             QFrame, QProgressBar, QScrollArea, QPushButton)

from core.learning_stats import dashboard


def _pct(n, total):
    return int(round(n * 100.0 / total)) if total else 0


class RadarWidget(QWidget):
    """自绘五边形雷达图，展示学习健康度五维。"""

    def __init__(self, values, parent=None):
        super().__init__(parent)
        self.values = values  # [{'axis':..,'value':0-100}, ...]
        self.setMinimumSize(300, 260)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        cx, cy = w / 2, h / 2 + 6
        radius = min(w, h) / 2 - 40

        n = len(self.values)
        import math
        # 背景网格（5 层同心多边形）
        grid_color = QColor('#e4e8ef')
        for level in (1, 2, 3, 4, 5):
            ratio = level / 5.0
            poly = QPolygonF()
            for i in range(n):
                ang = -math.pi / 2 + i * 2 * math.pi / n
                poly.append(QPointF(cx + radius * ratio * math.cos(ang),
                                    cy + radius * ratio * math.sin(ang)))
            pen = QPen(grid_color)
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(poly)

        # 轴线
        axis_pen = QPen(QColor('#d6dae3'))
        axis_pen.setWidth(1)
        p.setPen(axis_pen)
        for i in range(n):
            ang = -math.pi / 2 + i * 2 * math.pi / n
            p.drawLine(QPointF(cx, cy),
                       QPointF(cx + radius * math.cos(ang), cy + radius * math.sin(ang)))

        # 数据多边形
        data_poly = QPolygonF()
        for i, item in enumerate(self.values):
            ratio = max(0, min(100, item.get('value', 0))) / 100.0
            ang = -math.pi / 2 + i * 2 * math.pi / n
            data_poly.append(QPointF(cx + radius * ratio * math.cos(ang),
                                     cy + radius * ratio * math.sin(ang)))
        p.setPen(QPen(QColor('#4a8fd4'), 2))
        p.setBrush(QColor(74, 143, 212, 80))
        p.drawPolygon(data_poly)

        # 顶点标签 + 数值
        label_color = QColor('#33415c')
        p.setPen(label_color)
        font = self.font()
        font.setPointSize(8)
        p.setFont(font)
        for i, item in enumerate(self.values):
            ang = -math.pi / 2 + i * 2 * math.pi / n
            lx = cx + (radius + 16) * math.cos(ang)
            ly = cy + (radius + 16) * math.sin(ang)
            text = '%s %d' % (item.get('axis', ''), item.get('value', 0))
            # 简单居中估算文本宽度
            tw = p.fontMetrics().horizontalAdvance(text)
            p.drawText(QPointF(lx - tw / 2, ly + 4), text)


class LearningDashboard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle('咕嘎 · 学习进度看板')
        self.resize(560, 620)
        self.setMinimumSize(460, 520)
        self.setStyleSheet('''
            QDialog{background:#f7f9fc;}
            QLabel{font:13px "Microsoft YaHei UI";color:#202124;}
            QLabel#title{font-size:16px;font-weight:600;}
            QLabel#sub{color:#7a8294;font:11px "Microsoft YaHei UI";}
            QLabel#hint{color:#7a8294;font:11px "Microsoft YaHei UI";}
            QLabel#big{font-size:28px;font-weight:700;color:#33415c;}
            QFrame#card{background:#ffffff;border:1px solid #e4e8ef;border-radius:10px;}
            QFrame#metric{background:#ffffff;border:1px solid #e4e8ef;border-radius:10px;}
            QProgressBar{border:0;border-radius:5px;background:#eef1f7;text-align:center;
                         font:11px "Microsoft YaHei UI";color:#33415c;}
            QProgressBar::chunk{border-radius:5px;}
            QPushButton{background:#eef2fc;border:0;border-radius:8px;padding:8px 14px;
                        font:12px "Microsoft YaHei UI";color:#33415c;}
            QPushButton:hover{background:#e0e8fb;}
        ''')
        self.refresh()

    def refresh(self):
        data = dashboard()
        # 清空旧内容
        if self.layout() is not None:
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel('学习进度看板')
        title.setObjectName('title')
        outer.addWidget(title)
        sub = QLabel('概念掌握 · 复习卡 · 学习风格 · 学习产物 一屏总览')
        sub.setObjectName('sub')
        outer.addWidget(sub)

        # 雷达图（学习健康度五维）
        radar_card = QFrame()
        radar_card.setObjectName('card')
        radar_lay = QVBoxLayout(radar_card)
        radar_lay.setContentsMargins(14, 10, 14, 10)
        radar_title = QLabel('学习健康度雷达图')
        radar_title.setStyleSheet('font-weight:600;')
        radar_lay.addWidget(radar_title)
        radar_lay.addWidget(RadarWidget(data['radar']))
        outer.addWidget(radar_card)

        # 可滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(14)

        # 1. 概念掌握度
        m = data['mastery']
        lay.addWidget(self._section_title('概念掌握度'))
        lay.addWidget(self._bar_row('已掌握', m['mastered'], m['total'], '#0a7d4f'))
        lay.addWidget(self._bar_row('已了解', m['known'], m['total'], '#4a8fd4'))
        lay.addWidget(self._bar_row('未掌握', m['unknown'], m['total'], '#d98c3a'))

        # 2. 复习卡状态
        s = data['srs']
        lay.addWidget(self._section_title('复习卡（间隔重复）'))
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._metric_card('总卡片', str(s['total'])))
        row.addWidget(self._metric_card('已到期', str(s['due']), accent='#d9534f' if s['due'] else None))
        states = s.get('states', {})
        row.addWidget(self._metric_card('学习中', str(states.get('Learning', 0))))
        row.addWidget(self._metric_card('已复习', str(states.get('Review', 0))))
        lay.addLayout(row)
        if s['due']:
            lay.addWidget(self._hint('有 %d 张卡片到期，跟咕嘎说「复习」即可开始。' % s['due']))

        # 3. 学习风格画像
        p = data['profile']
        lay.addWidget(self._section_title('学习风格画像'))
        if p:
            lay.addWidget(self._kv('主型', p['label'] + ('（混合型）' if p['mixed'] else '')))
            lay.addWidget(self._kv('专注度', '%d%%' % int(p['concentration'] * 100)))
        else:
            lay.addWidget(self._hint('尚未测评。跟咕嘎说「做学习风格测评」即可了解自己的学习偏好。'))

        # 4. 学习产物
        a = data['artifacts']
        lay.addWidget(self._section_title('学习产物（runtime/study/）'))
        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(self._metric_card('思维导图', str(a['mindmaps'])))
        row2.addWidget(self._metric_card('拓展笔记', str(a['expands'])))
        row2.addWidget(self._metric_card('文件总数', str(a['total'])))
        lay.addLayout(row2)

        lay.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 底部：刷新按钮 + 生成时间
        footer = QHBoxLayout()
        footer.addWidget(self._hint('生成于 ' + data['generated_at'].replace('T', ' ')))
        footer.addStretch(1)
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh)
        footer.addWidget(refresh_btn)
        outer.addLayout(footer)

    # ---- 小部件 ----
    def _section_title(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet('font-weight:600;margin-top:6px;')
        return lbl

    def _bar_row(self, label, n, total, color):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(label)
        num = QLabel('%d / %d  (%d%%)' % (n, total, _pct(n, total)))
        num.setObjectName('sub')
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(num)
        lay.addLayout(top)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(_pct(n, total))
        bar.setFixedHeight(14)
        bar.setStyleSheet('QProgressBar::chunk{background:%s;}' % color)
        lay.addWidget(bar)
        return w

    def _metric_card(self, label, value, accent=None):
        card = QFrame()
        card.setObjectName('metric')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        v = QLabel(str(value))
        v.setObjectName('big')
        if accent:
            v.setStyleSheet('font-size:28px;font-weight:700;color:%s;' % accent)
        lay.addWidget(v, alignment=Qt.AlignCenter)
        t = QLabel(label)
        t.setObjectName('sub')
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        return card

    def _kv(self, k, v):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        kk = QLabel(k)
        kk.setObjectName('sub')
        lay.addWidget(kk)
        lay.addStretch(1)
        lay.addWidget(QLabel(v))
        return w

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setObjectName('hint')
        lbl.setWordWrap(True)
        return lbl
