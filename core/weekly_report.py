# -*- coding: utf-8 -*-
"""咕嘎个人学习周报 —— 聚合近一周学习数据，用咕嘎风格语气总结进度与建议。

数据来源：
  - 理解模型 concepts（总数/掌握度，含创建时间不直接记录 → 用掌握度分布）
  - 错题本 mistakes（近一周新增/攻克）
  - 复习卡 srs（到期/状态）
  - 学习产物 study/（近一周新增文件）

纯 Python、无 Qt 依赖；文案生成走聊天 API，失败降级为纯数据罗列。
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / 'runtime' / 'learning'
STUDY = ROOT / 'runtime' / 'study'


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _chat(messages, max_tokens=2000, temperature=0.5, timeout=90):
    try:
        with open(ROOT / 'ai_config.json', encoding='utf-8-sig') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    key = (cfg.get('api_key') or '').strip()
    base = (cfg.get('base_url') or '').rstrip('/')
    if not key or key.startswith('YOUR_') or not base:
        return None
    try:
        import requests
        r = requests.post(base + '/chat/completions',
                          headers={'Authorization': 'Bearer ' + key,
                                   'Content-Type': 'application/json'},
                          json={'model': cfg.get('model', 'deepseek-v4.1-flash'),
                                'messages': messages, 'max_tokens': max_tokens,
                                'temperature': temperature}, timeout=timeout)
        if r.status_code != 200:
            return None
        return (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '').strip() or None
    except Exception:
        return None


def collect(weeks=1):
    """采集近 N 周学习数据，返回结构化 dict。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(weeks=weeks)

    # 理解模型
    model = _load(LEARNING / 'understanding_model.json', {'concepts': {}})
    concepts = model.get('concepts', {})
    mastery = {'mastered': 0, 'known': 0, 'unknown': 0}
    for v in concepts.values():
        m = v.get('mastery', 'unknown')
        mastery[m] = mastery.get(m, 0) + 1

    # 错题本
    mistakes = _load(LEARNING / 'mistakes.json', {'items': []})
    items = mistakes.get('items', [])
    recent_mistakes = 0
    solved = 0
    for it in items:
        try:
            created = datetime.fromisoformat(str(it.get('created_at', '')))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if created >= since:
            recent_mistakes += 1
        if it.get('solved'):
            solved += 1

    # 复习卡
    srs = _load(LEARNING / 'srs.json', {'cards': {}})
    cards = srs.get('cards', {})
    due = 0
    for cd in cards.values():
        try:
            due_str = cd.get('due') if isinstance(cd, dict) else getattr(cd, 'due', None)
            if due_str:
                due_dt = datetime.fromisoformat(str(due_str))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt <= now:
                    due += 1
        except Exception:
            continue

    # 学习产物（近一周新增）
    new_artifacts = 0
    if STUDY.exists():
        for f in STUDY.iterdir():
            if f.is_file() and f.suffix in ('.md', '.html', '.json'):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                    if mtime >= since:
                        new_artifacts += 1
                except Exception:
                    continue

    return {
        'period': '%d 周' % weeks,
        'concepts_total': len(concepts),
        'mastery': mastery,
        'recent_mistakes': recent_mistakes,
        'mistakes_total': len(items),
        'solved': solved,
        'cards_total': len(cards),
        'cards_due': due,
        'new_artifacts': new_artifacts,
    }


REPORT_PROMPT = """你是咕嘎，一只温柔的小企鹅助教。根据下面的学习周报数据，写一份简短温暖的学习周报。
要求：
- 用「本鹅」自称，称呼用户「饲养员」
- 语气鼓励、温暖，不毒舌；适当穿插「咕嘎~」
- 结构：
  1. 一句话总体评价
  2. 本周亮点（学了什么、掌握情况）
  3. 待加强的地方（错题、待复习）
  4. 下周建议（1-2 条具体行动）
- 简洁，200 字以内，用中文

数据：
"""


def generate(weeks=1):
    """生成学习周报文本。返回 Markdown 字符串（含数据摘要 + AI 文案）。"""
    data = collect(weeks)
    ai_text = _chat([{'role': 'user', 'content': REPORT_PROMPT + json.dumps(data, ensure_ascii=False)}])
    lines = ['# 学习周报（近 %s）' % data['period'], '']
    if ai_text:
        lines.append(ai_text.strip())
    else:
        lines.append('本鹅帮你总结了一下这周的学习情况：')
        lines.append('- 已收录概念 %d 个（已掌握 %d / 已了解 %d / 未掌握 %d）'
                     % (data['concepts_total'], data['mastery']['mastered'],
                        data['mastery']['known'], data['mastery']['unknown']))
        lines.append('- 本周新增错题 %d 道，已攻克 %d 道' % (data['recent_mistakes'], data['solved']))
        lines.append('- 复习卡共 %d 张，其中 %d 张待复习' % (data['cards_total'], data['cards_due']))
        lines.append('- 本周新生成学习产物 %d 个' % data['new_artifacts'])
    lines.append('')
    lines.append('---')
    lines.append('数据快照：' + json.dumps(data, ensure_ascii=False))
    return '\n'.join(lines)
