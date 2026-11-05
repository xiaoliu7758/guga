# -*- coding: utf-8 -*-
"""咕嘎个性化讲解 —— 把学习风格画像真正注入到讲解里，并做自适应难度。

- style_instruction()：根据学习风格画像生成一段可注入 system prompt 的讲解风格指令。
- adaptive_difficulty()：根据近期答对率，返回出题难度档位与提示策略。

纯 Python、无 Qt 依赖，可离线测试。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 三种学习风格的讲解指令模板（与 learning_tutor.TYPES 对应）
STYLE_INSTRUCTIONS = {
    'results_first': (
        '【讲解风格：快进结果型】先直接给结论和重点，再简短补充推导；少铺垫、别啰嗦；'
        '配跳步验证题，允许用户跳步；必要时直接给结果。'
    ),
    'thorough': (
        '【讲解风格：细嚼稳扎型】分层拆解，每讲一小步就出一小问确认理解；'
        '主动给推导步骤，逐步引导；稳扎稳打，不催进度。'
    ),
    'help_seeking': (
        '【讲解风格：畏难求助型】阶梯式提示，先给半遮答案再补原理；'
        '用低压力小步题推进，避免一次给太多；多鼓励、降焦虑、多肯定。'
    ),
}


def get_profile():
    """读取学习风格画像；未测评返回 None。"""
    try:
        from core.learning_tutor import get_profile as _gp
        return _gp()
    except Exception:
        return None


def style_instruction():
    """返回一段可注入的讲解风格指令；未测评返回空串。"""
    profile = get_profile()
    if not profile:
        return ''
    primary = profile.get('primary')
    style = profile.get('style') or {}
    mixed = profile.get('mixed')
    base = STYLE_INSTRUCTIONS.get(primary, '')
    parts = [base]
    if mixed:
        secondary = profile.get('secondary')
        secondary_style = (profile.get('types') or {}).get(secondary, {})
        if secondary_style and secondary_style.get('teaching'):
            parts.append('（混合型，可结合次型策略：%s）' % secondary_style['teaching'])
    tone = style.get('tone')
    if tone:
        parts.append('鼓励语气：%s' % tone)
    return '\n'.join(p for p in parts if p)


def _recent_accuracy(limit=20):
    """从错题本推断近期答对率；无数据返回 None（表示不干预难度）。"""
    try:
        from core.mistake_book import _load
        data = _load()
        items = data.get('items', [])
        if not items:
            return None
        # 近 limit 条：答对(solved=True 且后续没再错) 视为对，否则算错
        recent = items[-limit:]
        correct = sum(1 for it in recent if it.get('solved'))
        total = len(recent)
        return correct / total
    except Exception:
        return None


def adaptive_difficulty():
    """根据近期答对率返回出题难度档位。

    返回 dict：
      - level: 'easy' | 'normal' | 'hard'
      - hint_strategy: '先给半遮答案' | '先独立思考' | '直接给结果'
      - accuracy: 近期答对率（0-1，无数据为 None）
    """
    acc = _recent_accuracy()
    if acc is None:
        return {'level': 'normal', 'hint_strategy': '先独立思考',
                'accuracy': None, 'reason': '尚无做题记录，默认中等难度'}
    if acc < 0.5:
        return {'level': 'easy', 'hint_strategy': '先给半遮答案再补原理',
                'accuracy': round(acc, 2), 'reason': '近期答对率偏低，降低难度并多提示'}
    if acc >= 0.8:
        return {'level': 'hard', 'hint_strategy': '少给提示，鼓励独立完成',
                'accuracy': round(acc, 2), 'reason': '近期答对率高，提升难度'}
    return {'level': 'normal', 'hint_strategy': '先独立思考',
            'accuracy': round(acc, 2), 'reason': '近期答对率适中，保持难度'}


def quiz_instruction():
    """出题时注入的风格+难度指令，供 study_tools.quiz 或助教出题使用。"""
    style = style_instruction()
    diff = adaptive_difficulty()
    parts = []
    if style:
        parts.append(style)
    parts.append('【出题难度：%s】%s。提示策略：%s。' % (
        diff['level'], diff['reason'], diff['hint_strategy']))
    return '\n'.join(parts)


# --------------------------------------------------------------------------
# 画像动态更新：根据学习行为信号持续校准学习风格
# --------------------------------------------------------------------------

def update_profile_from_behavior(min_signals=5):
    """根据累计行为信号微调学习风格画像。

    策略：把行为信号累计按风格倾向叠加到现有画像分数上（行为权重 0.4），
    重新排序主型/次型。信号不足 min_signals 时不调整（避免噪声）。

    返回 {'updated': bool, 'profile': ...} ；无画像或信号不足返回 {'updated': False}。
    """
    profile = get_profile()
    if not profile:
        return {'updated': False, 'reason': '尚未完成学习风格测评'}
    try:
        from core.behavior_tracker import tally
        t = tally()
        counts = t.get('counts', {})
        if t.get('total', 0) < min_signals:
            return {'updated': False, 'reason': '行为信号不足 %d 条' % min_signals,
                    'signals': t.get('total', 0)}
    except Exception:
        return {'updated': False, 'reason': '行为追踪不可用'}

    scores = dict(profile.get('scores', {}))
    behavior_weight = 0.4
    for typ, cnt in counts.items():
        if typ in scores:
            scores[typ] = scores.get(typ, 0.0) + cnt * behavior_weight

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked:
        return {'updated': False, 'reason': '无有效分数'}
    primary, secondary = ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]
    profile['scores'] = {k: round(v, 2) for k, v in scores.items()}
    profile['primary'] = primary[0]
    profile['secondary'] = secondary[0]
    profile['style'] = profile['types'][primary[0]]
    profile['mixed'] = primary[1] < 0.5 or (primary[1] - secondary[1]) < 0.5
    try:
        from core.learning_tutor import PROFILE_PATH, _save
        _save(PROFILE_PATH, profile)
    except Exception:
        pass
    return {'updated': True, 'profile': profile,
            'primary': primary[0], 'behavior_signals': counts}
