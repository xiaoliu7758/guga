# -*- coding: utf-8 -*-
"""咕嘎学习工具箱对话框 —— 截图/文本 → 学习包（导图 / 拓展 / 自测 / 复习卡）。

接收一张截图（data URI）或一段文本，后台调用 core.study_tools 生成学习产物，
用标签页展示；导图可一键用浏览器打开，其余产物提供落盘路径。
"""
import base64
import html
import json
import threading

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextBrowser,
                             QTabWidget, QWidget, QPushButton, QMessageBox)


def _image_data_uri_to_b64(image_url):
    """data URI → 裸 base64（供视觉 API 使用），保留原 URI 字段。"""
    if not image_url or not str(image_url).startswith('data:image'):
        return image_url
    return image_url.split(',', 1)[1]


class StudyDialog(QDialog):
    """截图/文本学习包结果窗口。"""
    _done = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle('咕嘎 · 学习工具箱')
        self.resize(680, 560)
        self.setMinimumSize(480, 420)
        self._busy = False
        self.setStyleSheet('''
            QDialog{background:#f7f9fc;}
            QLabel#hint{color:#7a8294;font:11px "Microsoft YaHei UI";}
            QTextBrowser{border:1px solid #e4e8ef;border-radius:9px;padding:10px;
                         font:13px "Microsoft YaHei UI";background:#ffffff;color:#202124;}
            QPushButton{background:#eef2fc;border:0;border-radius:8px;padding:8px 14px;
                        font:12px "Microsoft YaHei UI";color:#33415c;}
            QPushButton:hover{background:#e0e8fb;}
            QTabWidget::pane{border:1px solid #e4e8ef;border-radius:8px;background:#ffffff;}
            QTabBar::tab{background:#eef1f7;padding:8px 16px;border-radius:6px 6px 0 0;
                         margin-right:3px;color:#5b6472;font:12px "Microsoft YaHei UI";}
            QTabBar::tab:selected{background:#ffffff;color:#33415c;font-weight:600;}
        ''')
        lay = QVBoxLayout(self)
        self.hint = QLabel('正在分析截图并生成学习内容…')
        self.hint.setObjectName('hint')
        lay.addWidget(self.hint)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

    # ---- 入口 ----
    def run_image(self, image_url, focus_image_url=None, want=('mindmap', 'expand', 'quiz', 'cards')):
        """从截图生成学习包。image_url 为 data URI。"""
        self._start('正在分析截图，提取知识点并生成学习内容…')
        def work():
            try:
                from core import study_tools as st
                b64 = _image_data_uri_to_b64(image_url)
                uri = ('data:image/png;base64,' + b64) if b64 and not b64.startswith('data:') else b64
                pkg = st.study_package(image_b64=uri, want=want)
                self._done.emit({'ok': pkg.get('ok', False), 'pkg': pkg})
            except Exception as exc:
                self._done.emit({'ok': False, 'error': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def run_text(self, text, want=('mindmap', 'expand', 'quiz', 'cards')):
        """从文本生成学习包。"""
        self._start('正在分析文本，提取知识点并生成学习内容…')
        def work():
            try:
                from core import study_tools as st
                pkg = st.study_package(text=text, want=want)
                self._done.emit({'ok': pkg.get('ok', False), 'pkg': pkg})
            except Exception as exc:
                self._done.emit({'ok': False, 'error': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def _start(self, msg):
        self._busy = True
        self.hint.setText(msg)
        self.tabs.clear()
        self._done.result.connect(self._on_result)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_result(self, payload):
        self._busy = False
        if not payload.get('ok'):
            self.hint.setText('生成失败：' + payload.get('error', '未知错误'))
            QMessageBox.warning(self, '学习工具箱', payload.get('error', '未能生成学习内容'))
            return
        self.hint.setText('学习内容已生成 · 可切换到各标签页查看')
        self._render(payload['pkg'])

    # ---- 渲染 ----
    def _render(self, pkg):
        self.tabs.clear()
        if 'mindmap' in pkg:
            self.tabs.addTab(self._mindmap_tab(pkg['mindmap']), '思维导图')
        if 'expand' in pkg:
            self.tabs.addTab(self._expand_tab(pkg['expand']), '知识点拓展')
        if 'quiz' in pkg:
            self.tabs.addTab(self._quiz_tab(pkg['quiz']), '自测题')
        if 'cards' in pkg:
            self.tabs.addTab(self._cards_tab(pkg['cards']), '复习卡')

    def _browser(self):
        b = QTextBrowser()
        b.setOpenExternalLinks(True)
        return b

    def _mindmap_tab(self, mm):
        w = QWidget()
        lay = QVBoxLayout(w)
        b = self._browser()
        title = html.escape(mm.get('title', '思维导图'))
        html_path = mm.get('html', '')
        outline = mm.get('outline', '')
        b.setHtml(
            f'<h2>{title}</h2>'
            f'<p style="color:#7a8294">思维导图已生成，可在浏览器中打开交互式导图（可折叠/展开分支）。</p>'
            f'<p><a href="file:///{html.escape(html_path)}">在浏览器打开交互导图</a> · '
            f'<a href="file:///{html.escape(outline)}">查看 Markdown 大纲</a></p>'
            f'<pre style="white-space:pre-wrap">{html.escape(self._read(outline))}</pre>')
        lay.addWidget(b)
        return w

    def _expand_tab(self, exp):
        w = QWidget()
        lay = QVBoxLayout(w)
        b = self._browser()
        focus = html.escape(exp.get('focus', {}).get('name', '知识点'))
        expansion = exp.get('expansion') or ''
        path = exp.get('path', '')
        link = f'<p><a href="file:///{html.escape(path)}">打开拓展笔记 Markdown</a></p>' if path else ''
        b.setHtml(f'<h2>知识点拓展 · {focus}</h2>{link}<div style="white-space:pre-wrap">{self._md_to_html(expansion)}</div>')
        lay.addWidget(b)
        return w

    def _quiz_tab(self, quiz):
        w = QWidget()
        lay = QVBoxLayout(w)
        b = self._browser()
        parts = ['<h2>自测题</h2>']
        for i, q in enumerate(quiz, 1):
            qtype = q.get('type', 'choice')
            parts.append(f'<h3>{i}. {html.escape(q.get("question", ""))}</h3>')
            if qtype == 'choice':
                for opt in q.get('options', []):
                    parts.append(f'<p style="margin-left:16px">{html.escape(opt)}</p>')
            parts.append(f'<p style="color:#0a7d4f">答案：{html.escape(q.get("answer", ""))}</p>')
            if q.get('explanation'):
                parts.append(f'<p style="color:#7a8294">解析：{html.escape(q["explanation"])}</p>')
        b.setHtml(''.join(parts))
        lay.addWidget(b)
        return w

    def _cards_tab(self, cards_data):
        w = QWidget()
        lay = QVBoxLayout(w)
        b = self._browser()
        cards = cards_data.get('cards', [])
        imported = cards_data.get('imported_srs', 0)
        path = cards_data.get('path', '')
        parts = [f'<h2>复习卡（{len(cards)} 张）</h2>']
        if imported:
            parts.append(f'<p style="color:#0a7d4f">已导入 {imported} 个概念到间隔重复复习库（FSRS）。</p>')
        if path:
            parts.append(f'<p><a href="file:///{html.escape(path)}">打开复习卡 JSON</a></p>')
        for i, c in enumerate(cards, 1):
            parts.append(f'<h3>{i}. {html.escape(c.get("front", ""))}</h3>')
            parts.append(f'<p style="color:#0a7d4f">答：{html.escape(c.get("back", ""))}</p>')
        b.setHtml(''.join(parts))
        lay.addWidget(b)
        return w

    # ---- 工具 ----
    @staticmethod
    def _read(path):
        try:
            with open(path, encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ''

    @staticmethod
    def _md_to_html(md):
        return html.escape(md or '').replace('\n', '<br>')
