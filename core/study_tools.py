# -*- coding: utf-8 -*-
"""咕嘎学习工具箱 —— 截图/文本 → 学习产物的主动能力链。

围绕「截取屏幕内容」这件事，提供一组可直接落盘的学习能力：
  - extract_knowledge()  截图/文本 → 提炼知识点清单（JSON）
  - mindmap()            内容 → 思维导图（.md 大纲 + .html 交互图）
  - expand_knowledge()   知识点 → 关联概念 / 进阶延伸 / 学习笔记
  - quiz()               内容 → 练习题（选择/简答）
  - flashcards()         内容 → 复习卡片，可写入 FSRS 间隔重复库

设计要点：
  - 纯 Python、无 Qt 依赖，可在命令行离线测试。
  - 视觉识别复用 core.vision 的截图/读图能力；文本理解复用聊天 API。
  - 落盘到 runtime/study/，不写日志、不存凭据。
  - 所有「理解类」函数都带降级：模型不可用时回退到纯文本解析，保证不崩溃。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'runtime' / 'study'
DATA_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# 配置与底层调用
# --------------------------------------------------------------------------

def _load_cfg():
    try:
        with open(ROOT / 'ai_config.json', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}


def _chat(messages, max_tokens=3000, temperature=0.3, timeout=90):
    """调用聊天 API 做文本理解，返回正文；不可用/失败返回 None。"""
    cfg = _load_cfg()
    key = (cfg.get('api_key') or '').strip()
    if not key or key.startswith('YOUR_'):
        return None
    base = (cfg.get('base_url') or '').rstrip('/')
    if not base:
        return None
    try:
        import requests
        r = requests.post(
            base + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key,
                     'Content-Type': 'application/json'},
            json={'model': cfg.get('model', 'deepseek-v4.1-flash'),
                  'messages': messages,
                  'max_tokens': max_tokens, 'temperature': temperature},
            timeout=timeout)
        if r.status_code != 200:
            return None
        content = (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '')
        return content.strip() or None
    except Exception:
        return None


def _vision(image_b64, prompt):
    """复用 core.vision 的视觉调用；失败返回 None。"""
    try:
        from core import vision
        return vision._call_vision(image_b64, prompt)
    except Exception:
        return None


# --------------------------------------------------------------------------
# 截图输入：把截图转成可分析的图像与文本
# --------------------------------------------------------------------------

def capture_screenshot(max_side=1280):
    """截取当前屏幕，返回 (image_b64_data_uri, 保存路径)。"""
    try:
        from core import vision
        b64 = vision.screenshot_to_b64(max_side=max_side)
        return b64, None
    except Exception as exc:
        return None, str(exc)


def image_from_bytes(png_bytes):
    """把 PNG 字节转成 data URI。"""
    import base64
    return 'data:image/png;base64,' + base64.b64encode(png_bytes).decode()


def image_from_path(path, max_side=1280):
    """把图片文件转成 data URI。"""
    try:
        from core import vision
        return vision.image_path_to_b64(str(path), max_side=max_side)
    except Exception:
        return None


# --------------------------------------------------------------------------
# 知识点提取
# --------------------------------------------------------------------------

EXTRACT_PROMPT = """你是一位学习助教。请根据下面提供的{source}，提炼其中的核心知识点，用于学习。
要求：
1. 提炼 3-8 个关键知识点，每个给一个简短标题和一句话解释。
2. 尽量覆盖主题、定义、原理、易错点。
3. 只输出 JSON，格式严格如下，不要输出任何解释或 Markdown 代码块标记：
{{"title":"主题","topics":[{{"name":"知识点名","summary":"一句话解释","detail":"1-2句补充","tags":["标签"]}}]}}"""


def extract_knowledge(text=None, image_b64=None):
    """从文本或截图提炼知识点。返回 dict 或 None。

    优先走视觉识别（有图），否则走文本理解；两者都失败返回 None。
    """
    source = '截图' if image_b64 else '文本内容'
    result = None
    if image_b64:
        result = _vision(image_b64, EXTRACT_PROMPT.format(source=source))
    elif text and str(text).strip():
        result = _chat([
            {'role': 'user', 'content': EXTRACT_PROMPT.format(source=source) + '\n\n内容：\n' + str(text)[:6000]}
        ])
    if not result:
        return None
    return _parse_knowledge_json(result, text)


def _parse_knowledge_json(raw, fallback_text=''):
    """解析模型返回的 JSON；失败则从文本退化解析。"""
    try:
        m = re.search(r'\{.*\}', raw, re.S)
        data = json.loads(m.group(0) if m else raw)
        if isinstance(data, dict) and 'topics' in data:
            return data
    except Exception:
        pass
    # 降级：用文本行模拟知识点
    lines = [ln.strip() for ln in str(fallback_text).split('\n') if ln.strip()][:8]
    topics = [{'name': ln[:40], 'summary': ln, 'detail': '', 'tags': []} for ln in lines]
    return {'title': '截图内容', 'topics': topics}


# --------------------------------------------------------------------------
# 思维导图
# --------------------------------------------------------------------------

MINDMAP_PROMPT = """把下面这段学习内容整理成 Markdown 思维导图大纲：
- 用 # 表示中心主题（一个）
- 用 ## 表示一级分支（主要知识板块）
- 用 - 表示叶子要点
- 保留所有关键信息不遗漏，层级清晰
- 只输出大纲本身，不要任何解释或代码块标记

内容：
"""


def _outline_from_text(text):
    outline = _chat([{'role': 'user', 'content': MINDMAP_PROMPT + str(text)[:6000]}])
    if outline:
        return outline.strip()
    # 降级：按行生成大纲
    lines = [ln.strip() for ln in str(text).split('\n') if ln.strip()]
    title = (lines[0][:40] if lines else '未命名')
    return '# ' + title + '\n' + '\n'.join('- ' + ln for ln in lines[:30])


def _outline_from_knowledge(knowledge):
    title = knowledge.get('title', '学习主题')
    topics = knowledge.get('topics', [])
    lines = ['# ' + title]
    for t in topics:
        lines.append('## ' + t.get('name', ''))
        if t.get('summary'):
            lines.append('- ' + t['summary'])
        if t.get('detail'):
            lines.append('- ' + t['detail'])
    return '\n'.join(lines)


def _render_html(title, outline):
    """复用 answer_export 的思维导图 HTML 渲染器。"""
    from core.answer_export import _render_html
    return _render_html(title, outline)


def _unique(path):
    if not path.exists():
        return path
    for i in range(2, 200):
        p = path.with_name(f'{path.stem}({i}){path.suffix}')
        if not p.exists():
            return p
    return path


def mindmap(text=None, image_b64=None, title=None, knowledge=None):
    """基于文本/截图生成思维导图，返回 dict(outline, html, title)。

    knowledge 为已提取的知识点 dict，可复用避免重复调用视觉/文本理解。
    """
    if knowledge is None:
        if image_b64:
            knowledge = extract_knowledge(image_b64=image_b64)
    outline = None
    if knowledge:
        outline = _outline_from_knowledge(knowledge)
        title = title or knowledge.get('title', '学习主题')
    elif text and str(text).strip():
        outline = _outline_from_text(str(text))
    if not outline:
        return None
    title = (title or _derive_title(outline))[:40] or '未命名'
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    md_path = _unique(DATA_DIR / (title + '.mindmap.md'))
    md_path.write_text(outline, encoding='utf-8')
    html_path = _unique(DATA_DIR / (title + '.mindmap.html'))
    html_path.write_text(_render_html(title, outline), encoding='utf-8')
    return {'title': title, 'outline': str(md_path), 'html': str(html_path),
            'knowledge': knowledge}


def _derive_title(outline):
    for ln in outline.split('\n'):
        m = re.match(r'^#+\s+(.+)$', ln.strip())
        if m:
            return re.sub(r'[\\/:*?"<>|]', '', m.group(1)).strip()
    return '未命名'


# --------------------------------------------------------------------------
# 知识点拓展
# --------------------------------------------------------------------------

EXPAND_PROMPT = """你是学习助教。围绕下面这个知识点，做拓展讲解，帮助学习者建立知识网络。
请分四个部分输出（用 Markdown 标题）：
## 关联概念 —— 与它相关的前置/并列概念（3-5 个，各一句话点明关系）
## 进阶延伸 —— 更深入的方向（2-3 个，指出可以继续学什么）
## 常见误区 —— 学习者容易踩的坑（2-3 个）
## 一句话记忆 —— 帮助记住核心的一句话

知识点：
"""


def expand_knowledge(topic_name, topic_detail=''):
    """围绕单个知识点生成拓展讲解。返回 Markdown 文本，失败返回 None。"""
    body = topic_name + ('\n' + topic_detail if topic_detail else '')
    text = _chat([{'role': 'user', 'content': EXPAND_PROMPT + body[:3000]}],
                 max_tokens=2000)
    return text


def expand_from_screen(text=None, image_b64=None, save=True, knowledge=None):
    """从截图/文本提炼知识点，并对第一个知识点做拓展。返回 dict。"""
    if knowledge is None:
        knowledge = extract_knowledge(text=text, image_b64=image_b64)
    if not knowledge or not knowledge.get('topics'):
        return None
    topics = knowledge['topics']
    first = topics[0]
    expansion = expand_knowledge(first.get('name', ''), first.get('summary', ''))
    result = {'title': knowledge.get('title'), 'topics': topics,
              'focus': first, 'expansion': expansion}
    if save and expansion:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = _unique(DATA_DIR / (re.sub(r'[\\/:*?"<>|]', '', first.get('name', '拓展'))[:30] + '.expand.md'))
        md = '# ' + first.get('name', '知识点') + '\n\n' + (expansion or '')
        path.write_text(md, encoding='utf-8')
        result['path'] = str(path)
    return result


# --------------------------------------------------------------------------
# 出题自测
# --------------------------------------------------------------------------

QUIZ_PROMPT = """你是学习助教。根据下面的学习内容出 3 道自测题，用于巩固理解。
输出 JSON 数组，不要输出解释或代码块标记。每道题格式：
{{"type":"choice|short","question":"题干","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"正确答案","explanation":"解析"}}
其中 choice 题型必填 options（4 项），short 题型 options 为空数组。answer 写清正确选项字母（如 "B"）或简答要点。

内容：
"""


def quiz(text=None, image_b64=None, knowledge=None):
    """根据内容出题。返回 [题目] 列表，失败返回 None。"""
    if knowledge is None:
        knowledge = extract_knowledge(text=text, image_b64=image_b64)
    if knowledge:
        # 用提炼出的知识点作为题目素材，更聚焦
        src = json.dumps(knowledge, ensure_ascii=False)
    elif text:
        src = str(text)
    else:
        return None
    raw = _chat([{'role': 'user', 'content': QUIZ_PROMPT + src[:5000]}], max_tokens=2000)
    if not raw:
        return None
    try:
        m = re.search(r'\[.*\]', raw, re.S)
        data = json.loads(m.group(0) if m else raw)
        if isinstance(data, list):
            return _apply_difficulty(data)
    except Exception:
        pass
    return None


def _apply_difficulty(questions):
    """按自适应难度档位调整题目数量/提示（不改题目本身，仅附难度元信息）。"""
    try:
        from core.personalize import adaptive_difficulty
        diff = adaptive_difficulty()
    except Exception:
        diff = {'level': 'normal'}
    level = diff.get('level', 'normal')
    # 简单档：减少题目压力（保留前 2 题）；困难档：保持原样（模型已出 3 题）
    if level == 'easy' and len(questions) > 2:
        questions = questions[:2]
    for q in questions:
        q['_difficulty'] = level
        q['_hint_strategy'] = diff.get('hint_strategy', '')
    return questions


# --------------------------------------------------------------------------
# 复习卡片（FSRS 间隔重复）
# --------------------------------------------------------------------------

FLASHCARD_PROMPT = """你是学习助教。根据下面的学习内容，生成 5 张复习卡片（问答式）。
输出 JSON 数组，不要输出解释或代码块标记。每张卡片格式：
{{"front":"问题（正面）","back":"答案（背面）","concept":"关联概念名"}}

内容：
"""


def flashcards(text=None, image_b64=None, knowledge=None):
    """生成复习卡片列表。返回 [卡片] 列表，失败返回 None。"""
    if knowledge is None:
        knowledge = extract_knowledge(text=text, image_b64=image_b64)
    if knowledge:
        src = json.dumps(knowledge, ensure_ascii=False)
    elif text:
        src = str(text)
    else:
        return None
    raw = _chat([{'role': 'user', 'content': FLASHCARD_PROMPT + src[:5000]}], max_tokens=2000)
    if not raw:
        return None
    try:
        m = re.search(r'\[.*\]', raw, re.S)
        data = json.loads(m.group(0) if m else raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def _save_cards(cards):
    """把卡片写入本地复习卡库 runtime/study/cards.json。"""
    path = DATA_DIR / 'cards.json'
    existing = []
    try:
        existing = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        existing = []
    existing.extend(cards)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def _save_quiz(questions, title=None):
    """把自测题落盘成独立 JSON 文件（题目全文留在文件里，不塞回对话）。"""
    if not questions:
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]', '', str(title or '自测题'))[:30] or '自测题'
    path = _unique(DATA_DIR / (safe + '.quiz.json'))
    payload = {'title': title or '自测题', 'count': len(questions), 'questions': questions}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def import_cards_to_srs(cards):
    """把生成的卡片加入 FSRS 复习库（写为 unknown 掌握度的理解模型概念）。"""
    imported = 0
    for c in cards:
        concept = (c.get('concept') or c.get('front') or '').strip()
        if not concept:
            continue
        try:
            from core.learning_tutor import update_model
            note = '复习卡: ' + (c.get('front', '') or '')[:80]
            update_model(concept, mastery='unknown', note=note)
            imported += 1
        except Exception:
            continue
    return imported


# --------------------------------------------------------------------------
# 一次性「截图 → 学习包」入口
# --------------------------------------------------------------------------

def study_package(text=None, image_b64=None, title=None, want=('mindmap', 'expand', 'quiz', 'cards')):
    """一键从截图/文本生成一个学习包。

    返回 dict，键为已成功生成的部分；各部分独立降级，互不影响。

    性能优化：只提取一次知识点（避免重复走视觉/文本理解），
    并把 expand / quiz / cards 三个互不依赖的生成请求并行执行，
    把原先 6-7 次串行请求压缩到「1 次提取 + 1 轮并行」，显著缩短耗时。
    """
    from concurrent.futures import ThreadPoolExecutor
    result = {'ok': True}
    want = tuple(want)

    # 1) 只提取一次知识点（截图时尤其昂贵，避免 4-5 次重复视觉调用）
    knowledge = None
    if any(w in want for w in ('mindmap', 'expand', 'quiz', 'cards')):
        if image_b64 or (text and str(text).strip()):
            knowledge = extract_knowledge(text=text, image_b64=image_b64)

    # 2) 思维导图：复用 knowledge，纯本地生成大纲（无额外请求）
    if 'mindmap' in want:
        mm = mindmap(text=text, image_b64=image_b64, title=title, knowledge=knowledge)
        if mm:
            result['mindmap'] = mm

    # 3) expand / quiz / cards：互不依赖，并行生成
    tasks = {}
    if 'expand' in want:
        tasks['expand'] = ('expand',)
    if 'quiz' in want:
        tasks['quiz'] = ('quiz',)
    if 'cards' in want:
        tasks['cards'] = ('cards',)

    def _expand():
        exp = expand_from_screen(text=text, image_b64=image_b64, save=True, knowledge=knowledge)
        if exp:
            return {'title': exp['title'], 'focus': exp['focus'],
                    'expansion': exp['expansion'], 'path': exp.get('path')}
        return None

    def _quiz():
        qz = quiz(text=text, image_b64=image_b64, knowledge=knowledge)
        if qz:
            qpath = _save_quiz(qz, title=title)
            return {'questions': qz, 'path': qpath}
        return None

    def _cards():
        cards = flashcards(text=text, image_b64=image_b64, knowledge=knowledge)
        if cards:
            path = _save_cards(cards)
            imported = import_cards_to_srs(cards)
            return {'cards': cards, 'path': path, 'imported_srs': imported}
        return None

    fn_map = {'expand': _expand, 'quiz': _quiz, 'cards': _cards}
    if tasks:
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            futures = {k: pool.submit(fn_map[k]) for k in tasks}
            for k, fut in futures.items():
                try:
                    val = fut.result(timeout=180)
                except Exception:
                    val = None
                if val:
                    result[k] = val

    if len(result) == 1:  # 只有 ok=True，说明全都失败
        result['ok'] = False
        result['error'] = '未能从该内容生成学习产物，请确认截图清晰或文本非空、聊天 API 已配置'
    return result


# --------------------------------------------------------------------------
# 外部资源输入：网址 / 本地文本 / PDF → 学习产物
# --------------------------------------------------------------------------

def content_from_url(url, max_chars=8000):
    """抓取网页正文文本（用 requests + 简易 HTML 去标签），返回文本或 None。"""
    url = str(url or '').strip()
    if not url.startswith(('http://', 'https://')):
        raise ValueError('请提供 http/https 网址')
    try:
        import requests
        r = requests.get(url, timeout=20, headers={'User-Agent': 'GugaDesktopPet/1.0'})
        r.raise_for_status()
        html_text = r.text
    except Exception as exc:
        return None
    # 简易去标签 + 去脚本/样式
    import re as _re
    html_text = _re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html_text, flags=_re.S | _re.I)
    text = _re.sub(r'<[^>]+>', ' ', html_text)
    text = _re.sub(r'&nbsp;|&#160;', ' ', text)
    text = _re.sub(r'\s+', ' ', text).strip()
    if not text:
        return None
    return text[:max_chars]


def content_from_file(path, max_chars=8000):
    """读取本地文本文件（.txt/.md/.py 等）或 PDF，返回文本或 None。"""
    path = Path(str(path))
    if not path.exists():
        raise ValueError('文件不存在：' + str(path))
    suffix = path.suffix.lower()
    try:
        if suffix == '.pdf':
            text = _pdf_to_text(path)
        else:
            data = path.read_bytes()
            for enc in ('utf-8', 'gbk', 'utf-8-sig', 'latin-1'):
                try:
                    text = data.decode(enc)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                return None
    except Exception:
        return None
    text = (text or '').strip()
    return text[:max_chars] if text else None


def _pdf_to_text(path):
    """提取 PDF 文本；优先 pdfplumber，其次 PyPDF2，都不可用返回 None。"""
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or '')
        return '\n'.join(parts)
    except Exception:
        pass
    try:
        from PyPDF2 import PdfReader
        parts = []
        reader = PdfReader(str(path))
        for page in reader.pages:
            parts.append(page.extract_text() or '')
        return '\n'.join(parts)
    except Exception:
        return None


def study_from_source(url=None, file_path=None, text=None, title=None,
                      want=('mindmap', 'cards')):
    """从网址/本地文件/文本生成学习产物。返回与 study_package 同构的 dict。"""
    content = None
    if url:
        content = content_from_url(url)
        if not content:
            return {'ok': False, 'error': '网页内容抓取失败，请确认网址可访问'}
    elif file_path:
        content = content_from_file(file_path)
        if not content:
            return {'ok': False, 'error': '文件读取失败或无法提取文本（PDF 需安装 pdfplumber 或 PyPDF2）'}
    else:
        content = str(text or '').strip()
    if not content:
        return {'ok': False, 'error': '没有可分析的内容'}
    return study_package(text=content, title=title, want=want)


# --------------------------------------------------------------------------
# 主题成文：给定一个知识点/主题 → 结构化文档 + 思维导图
# --------------------------------------------------------------------------

TOPIC_DOC_PROMPT = """你是学习助教。围绕下面这个主题/知识点，写一份结构清晰、便于复习的学习文档。
要求（用 Markdown 组织）：
## 核心概念 —— 用 1-2 句话讲清这个主题是什么
## 要点拆解 —— 拆成 3-6 个关键要点，每个用 - 列表 + 一句话说明
## 示例或类比 —— 给 1-2 个具体例子或生活化类比，帮助理解
## 快速复习总结 —— 用 2-3 句话或几个关键词，方便快速回忆
说明：语言简洁、易读、便于后续编辑；详细程度根据主题复杂程度自动调整，不要过度冗长。
只输出文档正文，不要任何额外解释。

主题：
"""


def topic_document(topic, detail='auto', save=True, title=None, want=('document', 'mindmap')):
    """从主题名生成结构化学习文档 + 可选思维导图。

    参数：
      - topic: 主题/知识点名称（必填）
      - detail: 'auto'（默认，按主题复杂程度自动）| 'brief' 简洁 | 'full' 详细
      - save: 是否落盘
      - want: 要生成的产物，可含 'document' / 'mindmap'

    返回 dict：
      - ok, title, document(路径), document_text(正文), mindmap(路径 dict)
    失败降级：LLM 不可用时返回 None。
    """
    topic = str(topic or '').strip()
    if not topic:
        return {'ok': False, 'error': '请提供主题/知识点名称'}
    # 详细程度指令
    detail_hint = {
        'auto': '详细程度根据主题复杂程度自动调整，默认简洁易读',
        'brief': '尽量简洁，抓核心，点到为止',
        'full': '尽量详细，覆盖背景、原理、细节、易错点',
    }.get(detail, 'auto')
    prompt = TOPIC_DOC_PROMPT.replace(
        '详细程度根据主题复杂程度自动调整，不要过度冗长。', detail_hint + '。') + topic
    doc_text = _chat([{'role': 'user', 'content': prompt}], max_tokens=3000, temperature=0.4)
    if not doc_text:
        return {'ok': False, 'error': '文档生成失败：聊天 API 未配置或调用失败'}
    result = {'ok': True, 'title': title or topic[:40], 'document_text': doc_text}
    if save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r'[\\/:*?"<>|]', '', title or topic)[:40] or '主题'
        if 'document' in want:
            doc_path = _unique(DATA_DIR / (safe_title + '.md'))
            doc_path.write_text('# ' + (title or topic) + '\n\n' + doc_text, encoding='utf-8')
            result['document'] = str(doc_path)
        if 'mindmap' in want:
            mm = mindmap(text=doc_text, title=title or topic)
            if mm:
                result['mindmap'] = {'outline': mm.get('outline'), 'html': mm.get('html')}
    return result

