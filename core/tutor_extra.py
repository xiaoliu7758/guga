# -*- coding: utf-8 -*-
"""咕嘎智能助教增强 —— 学习计划 / 知识点诊断 / 代码判分。

纯 Python、无 Qt 依赖；内容生成走聊天 API（复用 _chat），失败返回 None 由上层降级。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _chat(messages, max_tokens=2500, temperature=0.4, timeout=90):
    import json
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


PLAN_PROMPT = """你是学习规划师。根据学习目标与时长，制定一份可执行的学习计划。
输出 Markdown，包含：
## 总体目标 —— 一句话概括最终要达成的能力
## 阶段划分 —— 按周/月分成 3-6 个阶段，每阶段写明主题与目标
## 每周安排 —— 具体到每周学什么、做什么练习
## 验收标准 —— 如何判断每个阶段达标
要求具体、可执行、不空泛。"""


def learn_plan(goal, duration=''):
    """生成学习计划。返回 Markdown 文本，失败返回 None。"""
    goal = str(goal or '').strip()
    if not goal:
        raise ValueError('请提供学习目标')
    extra = ('，计划时长 ' + str(duration).strip()) if duration and str(duration).strip() else ''
    text = _chat([{'role': 'user', 'content': PLAN_PROMPT + '\n\n目标：' + goal + extra}],
                 max_tokens=3000)
    return text


DIAGNOSE_PROMPT = """你是耐心助教，用苏格拉底式提问帮学生定位知识盲点。
规则：不要直接给答案；每次只问一个具体问题，引导学生自己发现卡在哪一步；
根据学生上一轮回答，逐步追问到根本原因；最后总结他真正没理解的地方。
学生想搞懂的问题如下。请开始第一轮提问（一个问题 + 简短引导）。"""


def diagnose(question):
    """知识点诊断：返回第一轮苏格拉底式提问。"""
    question = str(question or '').strip()
    if not question:
        raise ValueError('请提供想搞懂的问题')
    return _chat([{'role': 'user', 'content': DIAGNOSE_PROMPT + '\n\n问题：' + question}],
                 max_tokens=1500)


def diagnose_followup(question, student_reply):
    """根据学生回答，继续追问。"""
    question = str(question or '').strip()
    reply = str(student_reply or '').strip()
    if not reply:
        raise ValueError('请提供学生回答')
    prompt = ('继续苏格拉底式追问。学生想搞懂的问题：「%s」。学生上一轮回答：「%s」。'
              '根据回答判断他卡在哪里，继续只问一个更聚焦的问题，或判断他已理解则简短确认。'
              % (question, reply))
    return _chat([{'role': 'user', 'content': prompt}], max_tokens=1200)


CODE_REVIEW_PROMPT = """你是代码评审助教。看这段代码，从正确性、bug、性能、可读性四个维度点评。
输出 Markdown：
## 结论 —— 这段代码对不对、能不能跑（一句话）
## 问题 —— 逐条列出 bug 或隐患（如有），标出行号位置
## 优化建议 —— 给出改进方向或示例
## 加分点 —— 写得好的地方
若代码正确也如实说明。"""


def code_review(code):
    """代码判分讲解。"""
    code = str(code or '').strip()
    if not code:
        raise ValueError('请提供代码片段')
    return _chat([{'role': 'user', 'content': CODE_REVIEW_PROMPT + '\n\n```\n' + code[:6000] + '\n```'}],
                 max_tokens=2500)
