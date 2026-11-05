# -*- coding: utf-8 -*-
"""咕嘎学习辅导模块 —— 学习风格画像 + Agent Harness 五阶段学习框架。

参考：Eero Alvar《Agent Harness for Learning Things》提出的五阶段学习法：
  目标设定(goal) → 理解(understand) → 优化前提(prerequisites) → 教学(teach) → 练习(practice)，
配合「个人理解模型」（记录已知/未知/误解），以及一套「置信度选择题」学习风格测评。

设计要点：
  - 纯 Python、无 Qt 依赖，可离线测试；由 AppRuntime 在主线程调用。
  - 状态落盘到 runtime/learning/，不写日志、不存凭据。
  - 学习风格是「启发式偏好画像」而非心理测评，评分用置信度加权(certainty-based marking 的简化)。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'runtime' / 'learning'
PROFILE_PATH = DATA_DIR / 'profile.json'
ANSWERS_PATH = DATA_DIR / 'pending_answers.json'
MODEL_PATH = DATA_DIR / 'understanding_model.json'
SESSION_PATH = DATA_DIR / 'session.json'

# 三种学习风格（启发式分类，非临床心理量表）
TYPES = {
    'results_first': {
        'label': '快进结果型',
        'blurb': '先结论后推导、少铺垫，配跳步验证题，直接给结果反馈。',
        'teaching': '先给结论和重点，短讲解 + 跳步验证题，少铺垫多结果。',
        'pacing': '快节奏，允许跳步，尽快推进。',
        'hint': '少给提示，必要时直接给结果。',
        'tone': '直接、夸结果、别啰嗦。',
    },
    'thorough': {
        'label': '细嚼稳扎型',
        'blurb': '分层拆解、每步确认，配每小节点一道确认题，不催进度。',
        'teaching': '分层拆解讲解，每讲一小步就出一道确认题。',
        'pacing': '稳扎稳打，宁可慢也要扎实。',
        'hint': '主动给推导步骤，逐步引导。',
        'tone': '夸扎实、肯定细节。',
    },
    'help_seeking': {
        'label': '畏难求助型',
        'blurb': '阶梯式提示、低压力小步题，先半遮答案再补原理，多鼓励降焦虑。',
        'teaching': '阶梯式提示，先给半遮答案再补原理，低压力小步题。',
        'pacing': '小步推进，避免一次给太多造成压力。',
        'hint': '先给半遮答案 + 提示，再补原理。',
        'tone': '鼓励、降焦虑、多肯定。',
    },
}

# 置信度权重：让答案更科学（certainty-based marking 的简化）
CONFIDENCE_WEIGHT = {'不确定': 0.5, '确定': 1.0, '很确定': 1.5}
CONFIDENCE_LEVELS = list(CONFIDENCE_WEIGHT.keys())

# 5 道场景题，每题 3 个选项，每个选项唯一映射到一个学习风格
QUESTIONS = [
    {
        'id': 'q1',
        'text': '遇到一个全新的知识点，你最想要的打开方式是？',
        'options': [
            {'key': 'A', 'text': '直接说结论和重点，别啰嗦', 'type': 'results_first'},
            {'key': 'B', 'text': '从基础到细节，一步步讲清楚', 'type': 'thorough'},
            {'key': 'C', 'text': '先给我一个具体例子，我照着理解', 'type': 'help_seeking'},
        ],
    },
    {
        'id': 'q2',
        'text': '学到一半卡壳了，你的第一反应是？',
        'options': [
            {'key': 'A', 'text': '先跳过，把后面的看完再说', 'type': 'results_first'},
            {'key': 'B', 'text': '停下来，把这个点死磕懂再往下', 'type': 'thorough'},
            {'key': 'C', 'text': '立刻想找提示，或者直接问人', 'type': 'help_seeking'},
        ],
    },
    {
        'id': 'q3',
        'text': '做练习的时候，你更希望是？',
        'options': [
            {'key': 'A', 'text': '题少一点、能跳步，快速验证', 'type': 'results_first'},
            {'key': 'B', 'text': '每学一小步就有一道确认题', 'type': 'thorough'},
            {'key': 'C', 'text': '题目难度低一点、别给我压力', 'type': 'help_seeking'},
        ],
    },
    {
        'id': 'q4',
        'text': '你更喜欢的节奏是？',
        'options': [
            {'key': 'A', 'text': '越快越好，赶进度优先', 'type': 'results_first'},
            {'key': 'B', 'text': '稳一点，宁可慢也要扎实', 'type': 'thorough'},
            {'key': 'C', 'text': '看心情，太赶我会焦虑', 'type': 'help_seeking'},
        ],
    },
    {
        'id': 'q5',
        'text': '卡在一道难题上时，你更愿意？',
        'options': [
            {'key': 'A', 'text': '能跳过就跳过，别耽误时间', 'type': 'results_first'},
            {'key': 'B', 'text': '自己先硬想几把，实在不行再查', 'type': 'thorough'},
            {'key': 'C', 'text': '直接搜答案或问人，不硬耗', 'type': 'help_seeking'},
        ],
    },
]

# Agent Harness 五阶段
STAGES = ['goal', 'understand', 'prerequisites', 'teach', 'practice']
STAGE_LABEL = {
    'goal': '目标设定',
    'understand': '理解现状',
    'prerequisites': '优化前提',
    'teach': '教学',
    'practice': '练习',
}


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def questions():
    """返回测评题目（不含内部 type 映射，供智能体逐题呈现）。"""
    return [
        {'id': q['id'], 'text': q['text'],
         'options': [{'key': o['key'], 'text': o['text']} for o in q['options']],
         'confidence': CONFIDENCE_LEVELS}
        for q in QUESTIONS
    ]


def record(qid, option, confidence):
    """记录一道题的回答。qid=q1..q5，option=A/B/C，confidence=不确定/确定/很确定。"""
    q = next((q for q in QUESTIONS if q['id'] == qid), None)
    if q is None:
        raise ValueError('题目编号无效，应为 q1..q5')
    opt = next((o for o in q['options'] if o['key'] == option), None)
    if opt is None:
        raise ValueError('选项无效，应为 A/B/C')
    if confidence not in CONFIDENCE_WEIGHT:
        raise ValueError('置信度应为：' + '/'.join(CONFIDENCE_LEVELS))
    answers = _load(ANSWERS_PATH, [])
    # 同题重答则覆盖
    answers = [a for a in answers if a.get('qid') != qid]
    answers.append({'qid': qid, 'option': option, 'confidence': confidence,
                    'type': opt['type'], 'weight': CONFIDENCE_WEIGHT[confidence]})
    _save(ANSWERS_PATH, answers)
    return {'recorded': qid, 'answered': len(answers), 'total': len(QUESTIONS)}


def assess():
    """按置信度加权计算学习风格画像（主型 + 次型），并落盘。"""
    answers = _load(ANSWERS_PATH, [])
    if len(answers) < len(QUESTIONS):
        return {'ok': False, 'done': len(answers), 'total': len(QUESTIONS),
                'error': '题目未答完，先让用户继续作答'}
    scores = {t: 0.0 for t in TYPES}
    consistency = {}
    for a in answers:
        scores[a['type']] += a['weight']
        consistency.setdefault(a['qid'], a['type'])
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    primary, secondary = ranked[0], ranked[1]
    margin = primary[1] - secondary[1]
    # 高置信度下的自相矛盾检测：同一题只能一个类型，这里看的是多题是否集中在单一类型
    max_possible = sum(a['weight'] for a in answers)
    concentration = primary[1] / max_possible if max_possible else 0
    mixed = concentration < 0.5 or margin < 0.5
    profile = {
        'types': TYPES,
        'scores': {t: round(v, 2) for t, v in scores.items()},
        'primary': primary[0],
        'secondary': secondary[0],
        'mixed': mixed,
        'concentration': round(concentration, 2),
        'style': TYPES[primary[0]],
    }
    _save(PROFILE_PATH, profile)
    _save(ANSWERS_PATH, [])
    return {'ok': True, 'profile': profile,
            'summary': profile['style']['label'] + ('（混合型，可结合次型策略）' if mixed else ''),
            'advice': profile['style']['teaching']}


def get_profile():
    return _load(PROFILE_PATH, None)


def plan(goal):
    """根据画像 + 目标，生成五阶段学习计划骨架（具体讲解由智能体填充）。"""
    profile = get_profile() or {}
    style = (profile.get('style') or TYPES['thorough'])
    steps = [
        {'stage': 'goal', 'label': STAGE_LABEL['goal'],
         'task': f'明确目标「{goal}」：要学到什么程度、为什么学、验收标准是什么。'},
        {'stage': 'understand', 'label': STAGE_LABEL['understand'],
         'task': '先探测用户当前已知什么、哪些概念没接触过、有没有错误前提，建立个人理解模型。'},
        {'stage': 'prerequisites', 'label': STAGE_LABEL['prerequisites'],
         'task': '补齐缺口：先讲清必要的前置概念，纠正已知的错误前提。'},
        {'stage': 'teach', 'label': STAGE_LABEL['teach'],
         'task': '正式教学：' + style['teaching'] + '，边讲边确认理解，不囫囵吞枣。'},
        {'stage': 'practice', 'label': STAGE_LABEL['practice'],
         'task': '练习巩固：按「' + style['pacing'] + '」出题，' + style['hint'] + '，根据对错更新理解模型。'},
    ]
    return {'goal': goal, 'style': style['label'], 'tone': style['tone'],
            'stages': steps}


def set_stage(stage):
    if stage not in STAGES:
        raise ValueError('阶段应为：' + '/'.join(STAGES))
    _save(SESSION_PATH, {'stage': stage})
    return {'stage': stage, 'label': STAGE_LABEL[stage]}


def current_stage():
    return (_load(SESSION_PATH, {}) or {}).get('stage', 'goal')


def update_model(concept, mastery='known', note=''):
    """更新个人理解模型：概念名 + 掌握度(unknown/known/mastered) + 备注（误解等）。"""
    if mastery not in ('unknown', 'known', 'mastered'):
        raise ValueError('掌握度应为 unknown/known/mastered')
    if not concept or not str(concept).strip():
        raise ValueError('概念名不能为空')
    model = _load(MODEL_PATH, {'concepts': {}})
    concept = str(concept).strip()
    entry = model['concepts'].setdefault(concept, {'mastery': 'unknown', 'notes': []})
    entry['mastery'] = mastery
    if note:
        entry['notes'].append(str(note))
        entry['notes'] = entry['notes'][-20:]  # 最近20条
    _save(MODEL_PATH, model)
    return {'concept': concept, **entry}


def model_status():
    model = _load(MODEL_PATH, {'concepts': {}})
    concepts = model.get('concepts', {})
    return {
        'total': len(concepts),
        'mastered': [c for c, v in concepts.items() if v.get('mastery') == 'mastered'],
        'known': [c for c, v in concepts.items() if v.get('mastery') == 'known'],
        'unknown': [c for c, v in concepts.items() if v.get('mastery') == 'unknown'],
        'with_notes': {c: v.get('notes', []) for c, v in concepts.items() if v.get('notes')},
    }


# ---- 间隔重复（FSRS，来自 open-spaced-repetition，Anki 同源算法）----
SRS_PATH = DATA_DIR / 'srs.json'
RATING_MAP = {'again': 'Again', 'hard': 'Hard', 'good': 'Good', 'easy': 'Easy'}


def _srs_state():
    return _load(SRS_PATH, {'cards': {}})


def _save_srs(state):
    _save(SRS_PATH, state)


def due_reviews(limit=50):
    """返回到期需要复习的概念列表（按 due 升序）。"""
    from datetime import datetime, timezone
    try:
        from fsrs import Card
    except ImportError:
        return {'error': '未安装 fsrs，先 pip install fsrs'}
    state = _srs_state()
    now = datetime.now(timezone.utc)
    due = []
    for concept, cd in state.get('cards', {}).items():
        try:
            card = Card.from_dict(cd)
            if card.due <= now:
                due.append((concept, card.due.isoformat()))
        except Exception:
            continue
    due.sort(key=lambda kv: kv[1])
    return {'due': [c for c, _ in due[:limit]], 'total_due': len(due)}


def review(concept, rating='good'):
    """按 FSRS 复习一个概念，返回下次复习时间与记忆状态。"""
    from datetime import datetime, timezone
    if rating not in RATING_MAP:
        raise ValueError('评分应为 again/hard/good/easy')
    if not concept or not str(concept).strip():
        raise ValueError('概念名不能为空')
    try:
        from fsrs import Scheduler, Card, Rating
    except ImportError:
        raise ValueError('未安装 fsrs，先 pip install fsrs')
    concept = str(concept).strip()
    state = _srs_state()
    cd = state.get('cards', {}).get(concept)
    card = Card.from_dict(cd) if cd else Card()
    scheduler = Scheduler()
    new_card, _log = scheduler.review_card(card, getattr(Rating, RATING_MAP[rating]))
    state.setdefault('cards', {})[concept] = new_card.to_dict()
    _save_srs(state)
    return {'concept': concept, 'rating': rating, 'state': new_card.state,
            'due': new_card.due.isoformat()}

