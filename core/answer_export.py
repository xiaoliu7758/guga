# -*- coding: utf-8 -*-
"""长回答导出 —— 文档(.md) / 思维导图(.md 大纲 + .html 交互图)

当智能体回答超过阈值时，由 UI 询问主人是否保存；本模块负责真正的落盘。
纯 Python、无 Qt 依赖，可离线测试。
"""
import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / 'runtime' / 'exports'
DEFAULT_THRESHOLD = 600


def _load_cfg():
    try:
        with open(ROOT / 'ai_config.json', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}


def threshold():
    cfg = _load_cfg()
    try:
        return int(cfg.get('answer_export_threshold', DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


def is_long(text):
    """回答是否达到需要询问保存的阈值。"""
    return len(str(text).strip()) >= threshold()


def derive_title(text, maxlen=24):
    """从回答首行提取一个可作文件名的短标题。"""
    first = str(text).strip().split('\n', 1)[0]
    first = re.sub(r'^[#*>\-\s]+', '', first).strip()
    first = re.sub(r'[\\/:*?"<>|]', '', first)
    first = first.strip() or '未命名'
    return first[:maxlen].strip()


def _unique(path):
    if not path.exists():
        return path
    for i in range(2, 200):
        p = path.with_name(f'{path.stem}({i}){path.suffix}')
        if not p.exists():
            return p
    return path


def save_document(text, out_dir=None):
    """把回答保存为 Markdown 文档，返回文件绝对路径。"""
    out = Path(out_dir) if out_dir else EXPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = _unique(out / (derive_title(text) + '.md'))
    path.write_text(str(text).strip(), encoding='utf-8')
    return str(path)


def _to_outline(text):
    """用模型把长回答整理成 Markdown 思维导图大纲；失败则退化为逐行大纲。"""
    cfg = _load_cfg()
    key = (cfg.get('api_key') or '').strip()
    if key and not key.startswith('YOUR_'):
        try:
            base = (cfg.get('base_url') or '').rstrip('/')
            if base:
                prompt = (
                    '把下面这段回答整理成 Markdown 思维导图大纲：用 # 表示中心主题、'
                    '## 表示一级分支、- 表示叶子要点，保留所有关键信息不遗漏，'
                    '层级清晰，只输出大纲本身，不要任何解释。\n\n' + str(text)
                )
                r = requests.post(
                    base + '/chat/completions',
                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                    json={'model': cfg.get('model', 'qwen-plus'),
                          'messages': [{'role': 'user', 'content': prompt}],
                          'max_tokens': 3000, 'temperature': 0.3},
                    timeout=90)
                if r.status_code == 200:
                    content = (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '')
                    if content and content.strip():
                        return content.strip()
        except Exception:
            pass
    lines = [ln.strip() for ln in str(text).split('\n') if ln.strip()]
    return '# ' + derive_title(text) + '\n' + '\n'.join('- ' + ln for ln in lines)


def save_mindmap(text, out_dir=None):
    """生成思维导图：返回 dict(outline=md 大纲路径, html=交互图路径)。"""
    out = Path(out_dir) if out_dir else EXPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    title = derive_title(text)
    outline = _to_outline(text)
    md_path = _unique(out / (title + '.mindmap.md'))
    md_path.write_text(outline, encoding='utf-8')
    html_path = _unique(out / (title + '.mindmap.html'))
    html_path.write_text(_render_html(title, outline), encoding='utf-8')
    return {'outline': str(md_path), 'html': str(html_path)}


def _render_html(title, outline):
    """把 Markdown 大纲渲染成自包含的可折叠思维导图（无 CDN 依赖）。"""
    items = _outline_to_html_items(outline)
    return '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · 思维导图</title>
<style>
:root{--bg:#0b1220;--card:#111a2c;--line:#2a3a5c;--ink:#e7edff;--muted:#8ea0c2;--accent:#72f6e4}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20%% -10%%,#142444 0,var(--bg) 55%%);color:var(--ink);font:14px/1.7 "Microsoft YaHei",system-ui,sans-serif;padding:32px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:12px;margin:0 0 22px}
.tree{list-style:none;margin:0;padding-left:22px;position:relative}
.tree .tree{padding-left:26px}
.node{position:relative;margin:8px 0}
.node>.head{display:flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:9px 14px;cursor:pointer;transition:.15s}
.node>.head:hover{border-color:var(--accent)}
.node>.head .dot{width:8px;height:8px;border-radius:50%%;background:var(--accent);flex:0 0 auto}
.node.root>.head{background:linear-gradient(120deg,#1d3557,#14304f);font-size:16px;font-weight:600}
.toggle{width:16px;color:var(--muted);font-size:11px;flex:0 0 auto;text-align:center}
.node.collapsed>.tree{display:none}
.node.leaf .toggle{visibility:hidden}
.node .txt{flex:1}
.tree>.node::before{content:"";position:absolute;left:-13px;top:20px;width:13px;height:1px;background:var(--line)}
.tree>.node::after{content:"";position:absolute;left:-13px;top:-6px;bottom:0;width:1px;background:var(--line)}
.tree>.node:last-child::after{height:20px}
.tree>.node::before{top:22px}
</style>
</head>
<body>
<h1>%s</h1>
<p class="sub">咕嘎为你生成 · 点击分支可折叠/展开</p>
%s
<script>
document.querySelectorAll(".node .head").forEach(function(h){
  h.addEventListener("click",function(){h.parentNode.classList.toggle("collapsed");});
});
</script>
</body>
</html>''' % (title, title, items)


def _outline_to_html_items(outline):
    """Markdown 大纲 → 嵌套 <ul class=tree> HTML。"""
    import html

    def esc(s):
        return html.escape(s)

    # 1. 解析成 (level, text) 列表
    nodes = []
    for raw in outline.split('\n'):
        line = raw.rstrip()
        if not line.strip():
            continue
        m = re.match(r'^(#+)\s+(.*)$', line)
        if m:
            nodes.append((max(1, len(m.group(1))), m.group(2).strip()))
            continue
        m = re.match(r'^(\s*)[-*]\s+(.*)$', line)
        if m:
            nodes.append((3 + len(m.group(1)), m.group(2).strip()))
            continue
    if not nodes:
        nodes = [(1, '未命名')]

    # 2. 把最小层级归一到 1
    base = min(l for l, _ in nodes)
    nodes = [(l - base + 1, t) for l, t in nodes]

    # 3. 递归渲染
    def render(idx, level):
        out = []
        while idx < len(nodes):
            l, text = nodes[idx]
            if l < level:
                break
            if l > level:
                # 子节点挂到上一个节点的 children
                child_html, idx = render(idx, l)
                out[-1][2].append(child_html)
                continue
            out.append([text, l, []])
            idx += 1
        html_parts = []
        for text, l, children in out:
            is_root = l == 1
            is_leaf = not children
            cls = 'node root' if is_root else ('node leaf' if is_leaf else 'node')
            inner = (f'<div class="head"><span class="toggle">▾</span><span class="dot"></span>'
                     f'<span class="txt">{esc(text)}</span></div>')
            if children:
                inner += '<ul class="tree">' + ''.join(children) + '</ul>'
            html_parts.append(f'<li class="{cls}">{inner}</li>')
        return '<ul class="tree">' + ''.join(html_parts) + '</ul>', idx

    html_out, _ = render(0, 1)
    return html_out


def summarize_speech(text, max_chars=180):
    """把长回答提炼成适合朗读的「挑重点」精华版（口语化、短小）。

    用 LLM 压缩成 2-4 句重点；失败则退化为按句截断。返回可直接朗读的短文本。
    """
    text = str(text or '').strip()
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    cfg = _load_cfg()
    key = (cfg.get('api_key') or '').strip()
    if key and not key.startswith('YOUR_'):
        try:
            base = (cfg.get('base_url') or '').rstrip('/')
            if base:
                prompt = (
                    '把下面这段长回答提炼成适合语音朗读的重点摘要：'
                    '只保留最核心的结论和要点，用口语化短句，2-4 句，'
                    '总字数不超过 %d 字，不要列表、不要标题、不要解释。'
                    '直接输出摘要正文。\n\n%s' % (max_chars, text)
                )
                r = requests.post(
                    base + '/chat/completions',
                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                    json={'model': cfg.get('model', 'qwen-plus'),
                          'messages': [{'role': 'user', 'content': prompt}],
                          'max_tokens': 300, 'temperature': 0.3},
                    timeout=60)
                if r.status_code == 200:
                    content = (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '')
                    content = str(content).strip()
                    if content:
                        return content
        except Exception:
            pass
    # 降级：按句截断到 max_chars，尽量在句末断开
    sentences = re.split(r'(?<=[。！？!?])', text)
    out = ''
    for s in sentences:
        if len(out) + len(s) > max_chars:
            break
        out += s
    return (out.strip() + '…（完整内容已存文档）') if out.strip() else text[:max_chars] + '…'
