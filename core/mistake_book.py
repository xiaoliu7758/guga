# -*- coding: utf-8 -*-
"""咕嘎错题本 + 薄弱点推荐。

- 错题本：自测答错的题归档，记录题目/正确答案/用户答案/错误原因/来源概念，
  支持标注错因、标记已攻克、重测。
- 薄弱点推荐：结合理解模型(unknown 概念)与错题来源概念，推荐下一步该学什么。

纯 Python、无 Qt 依赖，可离线测试；数据落盘 runtime/learning/mistakes.json。
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / 'runtime' / 'learning'
MISTAKES_PATH = LEARNING / 'mistakes.json'

CAUSES = ('概念不清', '粗心', '记不牢', '没思路', '其他')


def _load():
    try:
        with open(MISTAKES_PATH, encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'items' in data:
                return data
    except (OSError, ValueError):
        pass
    return {'items': []}


def _save(data):
    LEARNING.mkdir(parents=True, exist_ok=True)
    with open(MISTAKES_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def add(question, answer='', user_answer='', concept='', source='', cause=''):
    """记录一道错题。返回错题条目。"""
    q = str(question).strip()
    if not q:
        raise ValueError('题目不能为空')
    if cause and cause not in CAUSES:
        raise ValueError('错因应为：' + '/'.join(CAUSES))
    data = _load()
    item = {
        'id': uuid.uuid4().hex[:12],
        'question': q,
        'answer': str(answer).strip(),
        'user_answer': str(user_answer).strip(),
        'concept': str(concept).strip(),
        'source': str(source).strip(),
        'cause': cause or '其他',
        'wrong_count': 1,
        'solved': False,
        'created_at': _now(),
        'last_wrong_at': _now(),
    }
    data['items'].append(item)
    _save(data)
    return item


def record_answer(question, answer='', user_answer='', concept='', source='', correct=False, cause=''):
    """记录一次作答。答错则入错题本（重复答错累加 wrong_count），答对且该题在错题本里则标记已攻克。"""
    if correct:
        data = _load()
        for it in data['items']:
            if it.get('question') == str(question).strip() and not it.get('solved'):
                it['solved'] = True
                it['solved_at'] = _now()
        _save(data)
        return {'recorded': False, 'solved': True}
    # 答错：若已存在同题未攻克，累加；否则新增
    data = _load()
    for it in data['items']:
        if it.get('question') == str(question).strip() and not it.get('solved'):
            it['wrong_count'] += 1
            it['last_wrong_at'] = _now()
            if cause:
                it['cause'] = cause
            _save(data)
            return {'recorded': True, 'id': it['id'], 'wrong_count': it['wrong_count']}
    item = add(question, answer, user_answer, concept, source, cause)
    return {'recorded': True, 'id': item['id'], 'wrong_count': 1}


def list_mistakes(only_unsolved=True, limit=100):
    """列出错题。only_unsolved=True 只返回未攻克的。"""
    data = _load()
    items = data['items']
    if only_unsolved:
        items = [it for it in items if not it.get('solved')]
    return items[:limit]


def mark_solved(mistake_id):
    """手动标记某题已攻克。"""
    data = _load()
    for it in data['items']:
        if it.get('id') == mistake_id:
            it['solved'] = True
            it['solved_at'] = _now()
            _save(data)
            return it
    raise ValueError('错题不存在')


def mark_cause(mistake_id, cause):
    """标注/修改错因。"""
    if cause not in CAUSES:
        raise ValueError('错因应为：' + '/'.join(CAUSES))
    data = _load()
    for it in data['items']:
        if it.get('id') == mistake_id:
            it['cause'] = cause
            _save(data)
            return it
    raise ValueError('错题不存在')


def stats():
    """错题本统计。"""
    data = _load()
    items = data['items']
    unsolved = [it for it in items if not it.get('solved')]
    solved = [it for it in items if it.get('solved')]
    cause_dist = {}
    for it in items:
        cause_dist[it.get('cause', '其他')] = cause_dist.get(it.get('cause', '其他'), 0) + 1
    return {'total': len(items), 'unsolved': len(unsolved),
            'solved': len(solved), 'cause_dist': cause_dist}


def recommend(limit=5):
    """薄弱点推荐：错题来源概念（未攻克、出现次数多者优先）+ 理解模型 unknown 概念。"""
    data = _load()
    unsolved = [it for it in data['items'] if not it.get('solved')]
    # 按概念聚合，按错题次数降序
    concept_weight = {}
    for it in unsolved:
        c = it.get('concept', '') or it.get('question', '')[:20]
        if c:
            concept_weight[c] = concept_weight.get(c, 0) + it.get('wrong_count', 1)
    weak = sorted(concept_weight.items(), key=lambda kv: -kv[1])
    recommendations = [{'concept': c, 'wrong_count': w, 'reason': '错题高频'}
                       for c, w in weak[:limit]]
    # 补充理解模型中未掌握的概念
    try:
        from core.learning_tutor import model_status
        unknowns = model_status().get('unknown', [])
        existing = {r['concept'] for r in recommendations}
        for c in unknowns:
            if c not in existing and len(recommendations) < limit:
                recommendations.append({'concept': c, 'wrong_count': 0, 'reason': '理解模型标记未掌握'})
    except Exception:
        pass
    return recommendations


def _reset_for_test():
    LEARNING.mkdir(parents=True, exist_ok=True)
    MISTAKES_PATH.write_text(json.dumps({'items': []}, ensure_ascii=False), encoding='utf-8')
