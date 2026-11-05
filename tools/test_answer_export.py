# -*- coding: utf-8 -*-
"""answer_export 离线测试：阈值、标题、文档与思维导图落盘。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.answer_export as ae


class AnswerExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.long = ('这是一段足够长的回答。' * 60)

    def test_is_long_and_threshold(self):
        self.assertFalse(ae.is_long('短回答'))
        self.assertTrue(ae.is_long(self.long))
        self.assertGreaterEqual(ae.threshold(), 1)

    def test_derive_title(self):
        self.assertEqual(ae.derive_title('递归算法详解\n\n内容……'), '递归算法详解')

    def test_save_document(self):
        p = ae.save_document(self.long, self.tmp)
        self.assertTrue(os.path.exists(p))
        self.assertTrue(p.endswith('.md'))

    def test_save_mindmap_fallback(self):
        # 无有效 Key 时走退化大纲；这里直接调 _outline 渲染，不依赖网络
        outline = '# 主题\n## 分支\n- 叶子'
        html = ae._outline_to_html_items(outline)
        self.assertIn('<ul class="tree">', html)
        self.assertIn('分支', html)
        self.assertIn('node root', html)

    def test_outline_parser_levels(self):
        outline = '# 根\n## 一\n### 叶子1\n## 二\n- 叶子2'
        html = ae._outline_to_html_items(outline)
        self.assertEqual(html.count('node root'), 1)
        self.assertGreaterEqual(html.count('node leaf'), 2)


if __name__ == '__main__':
    unittest.main()
