# -*- coding: utf-8 -*-
"""咕嘎学习统计 —— 聚合学习数据，供进度看板展示。

数据来源（均在 runtime/learning/ 与 runtime/study/）：
  - understanding_model.json : 概念掌握度 unknown/known/mastered
  - srs.json                : FSRS 复习卡（state、due）
  - profile.json            : 学习风格画像
  - study/                  : 生成的学习产物（导图/拓展/卡）

纯 Python、无 Qt 依赖，可离线测试。
"""
import json
from datetime import datetime, timezone
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


# ---- 概念掌握度 ----
def mastery_stats():
    model = _load(LEARNING / 'understanding_model.json', {'concepts': {}})
    concepts = model.get('concepts', {})
    mastered = sum(1 for v in concepts.values() if v.get('mastery') == 'mastered')
    known = sum(1 for v in concepts.values() if v.get('mastery') == 'known')
    unknown = sum(1 for v in concepts.values() if v.get('mastery') == 'unknown')
    total = len(concepts)
    return {'total': total, 'mastered': mastered, 'known': known, 'unknown': unknown}


# ---- FSRS 复习卡状态 ----
def srs_stats():
    state = _load(LEARNING / 'srs.json', {'cards': {}})
    cards = state.get('cards', {})
    now = datetime.now(timezone.utc)
    due = 0
    state_count = {}
    for concept, cd in cards.items():
        try:
            st = cd.get('state') if isinstance(cd, dict) else getattr(cd, 'state', 'New')
            state_count[st] = state_count.get(st, 0) + 1
            # 判断是否到期
            due_str = cd.get('due') if isinstance(cd, dict) else getattr(cd, 'due', None)
            if due_str:
                due_dt = datetime.fromisoformat(str(due_str))
                if due_dt.tzinfo is None:
                    due_dt = due_dt.replace(tzinfo=timezone.utc)
                if due_dt <= now:
                    due += 1
        except Exception:
            continue
    return {'total': len(cards), 'due': due, 'states': state_count}


# ---- 学习风格画像 ----
def profile_summary():
    profile = _load(LEARNING / 'profile.json', None)
    if not profile:
        return None
    return {
        'primary': profile.get('primary'),
        'label': (profile.get('style') or {}).get('label', ''),
        'mixed': profile.get('mixed', False),
        'concentration': profile.get('concentration', 0),
    }


# ---- 学习产物 ----
def study_artifacts():
    if not STUDY.exists():
        return {'mindmaps': 0, 'expands': 0, 'cards_file': 0, 'total': 0}
    files = list(STUDY.iterdir())
    mindmaps = sum(1 for f in files if f.suffix == '.html' and '.mindmap' in f.stem)
    expands = sum(1 for f in files if f.suffix == '.md' and f.stem.endswith('.expand'))
    cards_file = 1 if (STUDY / 'cards.json').exists() else 0
    return {'mindmaps': mindmaps, 'expands': expands, 'cards_file': cards_file,
            'total': len([f for f in files if f.suffix in ('.md', '.html', '.json')])}


# ---- 聚合看板数据 ----
def dashboard():
    """返回看板所需的完整统计。"""
    return {
        'mastery': mastery_stats(),
        'srs': srs_stats(),
        'profile': profile_summary(),
        'artifacts': study_artifacts(),
        'radar': radar(),
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    }


# ---- 掌握度雷达图（学习健康度五维）----
def radar():
    """学习健康度五维得分（0-100），供雷达图绘制。

    维度：
      - 掌握度：已掌握概念占全部概念的比例
      - 复习进度：复习卡中已复习(Review)占比（有卡时）
      - 错题掌握：错题已攻克占比（有错题时；无错题记满分）
      - 学习广度：概念总数（按经验映射，≥10 记满分）
      - 学习活跃度：生成的学习产物数量（按经验映射，≥10 记满分）
    """
    m = mastery_stats()
    s = srs_stats()
    # 掌握度
    mastery = _pct(m['mastered'], m['total']) if m['total'] else 0
    # 复习进度
    states = s.get('states', {})
    learned = states.get('Review', 0) + states.get('Relearning', 0)
    review = _pct(learned, s['total']) if s['total'] else 0
    # 错题掌握
    from core import mistake_book
    mb = mistake_book.stats()
    mistake = _pct(mb['solved'], mb['total']) if mb['total'] else 100
    # 学习广度（概念数）
    breadth = min(100, m['total'] * 10)
    # 学习活跃度（产物数）
    art = study_artifacts()
    activity = min(100, art['total'] * 10)
    return [
        {'axis': '掌握度', 'value': mastery},
        {'axis': '复习进度', 'value': review},
        {'axis': '错题掌握', 'value': mistake},
        {'axis': '学习广度', 'value': breadth},
        {'axis': '学习活跃度', 'value': activity},
    ]


def _pct(n, total):
    return int(round(n * 100.0 / total)) if total else 0
