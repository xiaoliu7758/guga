# -*- coding: utf-8 -*-
"""咕嘎学习行为追踪 —— 采集学习行为信号，用于动态校准学习风格画像。

行为信号（signal）→ 对应风格倾向：
  - skip       跳题/想跳过       → results_first（快进结果型）
  - ask_hint   求助/要提示       → help_seeking（畏难求助型）
  - confirm    反复确认/重答     → thorough（细嚼稳扎型）
  - rush       赶进度/嫌慢       → results_first
  - slow_down  要求慢一点/细讲   → thorough

数据落盘 runtime/learning/behavior.json；纯 Python、无 Qt 依赖。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / 'runtime' / 'learning'
BEHAVIOR_PATH = LEARNING / 'behavior.json'

# 信号 → 风格倾向权重
SIGNAL_TO_TYPE = {
    'skip': 'results_first',
    'ask_hint': 'help_seeking',
    'confirm': 'thorough',
    'rush': 'results_first',
    'slow_down': 'thorough',
}


def _load():
    try:
        with open(BEHAVIOR_PATH, encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'signals' in data:
                return data
    except (OSError, ValueError):
        pass
    return {'signals': []}


def _save(data):
    LEARNING.mkdir(parents=True, exist_ok=True)
    with open(BEHAVIOR_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record(signal, note=''):
    """记录一条行为信号。signal 见 SIGNAL_TO_TYPE。"""
    if signal not in SIGNAL_TO_TYPE:
        raise ValueError('未知行为信号：' + signal)
    data = _load()
    data['signals'].append({
        'signal': signal,
        'note': str(note)[:100],
        'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })
    # 保留最近 200 条
    data['signals'] = data['signals'][-200:]
    _save(data)
    return {'recorded': signal}


def tally(limit=200):
    """统计各风格倾向的累计信号数。"""
    data = _load()
    signals = data['signals'][-limit:]
    counts = {}
    for s in signals:
        t = SIGNAL_TO_TYPE.get(s.get('signal'))
        if t:
            counts[t] = counts.get(t, 0) + 1
    return {'counts': counts, 'total': len(signals)}


def recent_signals(limit=50):
    """返回最近的行为信号列表。"""
    data = _load()
    return data['signals'][-limit:]


def _reset_for_test():
    LEARNING.mkdir(parents=True, exist_ok=True)
    BEHAVIOR_PATH.write_text(json.dumps({'signals': []}, ensure_ascii=False), encoding='utf-8')
