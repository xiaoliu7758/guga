# -*- coding: utf-8 -*-
"""离线验证 study_tools 的纯逻辑部分（不依赖联网/API）。"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import study_tools as st


def test_parse_knowledge_json():
    raw = '好的，以下是结果：\n{"title":"装饰器","topics":[{"name":"闭包","summary":"函数捕获外层变量","detail":"","tags":["python"]}]}'
    data = st._parse_knowledge_json(raw)
    assert data['title'] == '装饰器', data
    assert data['topics'][0]['name'] == '闭包'
    print('✓ 知识点 JSON 解析')


def test_parse_knowledge_json_fallback():
    raw = '这不是 JSON'
    data = st._parse_knowledge_json(raw, '第一行\n第二行')
    assert data['topics'], data
    print('✓ 知识点解析降级')


def test_outline_from_knowledge():
    k = {'title': '异步', 'topics': [
        {'name': '协程', 'summary': 'async def', 'detail': '事件循环调度', 'tags': []}
    ]}
    outline = st._outline_from_knowledge(k)
    assert outline.startswith('# 异步'), outline
    assert '## 协程' in outline
    print('✓ 知识点转大纲')


def test_render_html():
    html = st._render_html('测试', '# 主题\n## 分支\n- 叶子')
    assert '<title>测试 · 思维导图</title>' in html
    assert 'collapsed' in html
    print('✓ 思维导图 HTML 渲染')


def test_mindmap_fallback_no_network():
    # 文本路径降级：无 api_key 时也应能生成大纲与 html
    result = st.mindmap(text='第一行标题\n第二行要点\n第三行要点')
    assert result and result['html'], result
    assert Path(result['html']).exists()
    assert Path(result['outline']).exists()
    print('✓ 思维导图落盘（文本降级路径）')


def test_unique():
    p = st._unique(st.DATA_DIR / 'x.md')
    assert p.name == 'x.md'
    print('✓ 文件名去重')


def test_save_cards():
    cards = [{'front': '什么是闭包', 'back': '捕获外层变量的函数', 'concept': '闭包'}]
    path = st._save_cards(cards)
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    assert data[-1]['concept'] == '闭包'
    print('✓ 复习卡落盘')


if __name__ == '__main__':
    test_parse_knowledge_json()
    test_parse_knowledge_json_fallback()
    test_outline_from_knowledge()
    test_render_html()
    test_mindmap_fallback_no_network()
    test_unique()
    test_save_cards()
    print('\n全部通过 ✅')
