# -*- coding: utf-8 -*-
"""长回答智能处理编排 —— 自动判断 + 重点提炼/精炼 + 调用工具生成产物。

这是「快速生成文档/思维导图」和「长回答自动判断提炼或精炼」的统一调度层。
纯 Python、无 Qt 依赖，可离线测试；由 agent_chat / 智能体工具调用。

触发条件（classify）：
  - short  : < 300 字   直接原样输出，不做处理
  - medium : 300-599 字 原样输出，可选生成文档
  - long   : 600-1999 字 自动「挑重点提炼」朗读 + 存文档/思维导图
  - huge   : >= 2000 字  自动「精炼全文」+ 存文档/思维导图

处理策略（decide）：
  - 提炼(summarize)：保留核心结论，口语化短句，适合朗读，完整内容存文档
  - 精炼(refine)   ：压缩篇幅但保留结构要点，输出结构化精炼版

产物（generate）：复用 answer_export 的 save_document / save_mindmap，
  并可选调用其他 AI（_to_outline / summarize_speech 内部已走 LLM）。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 精炼阈值：超过 50 字即精炼（用户要求敏感触发）
REFINE_THRESHOLD = 50


def _load_cfg():
    try:
        with open(ROOT / 'ai_config.json', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return {}


def classify(text):
    """按长度给回答分档，返回 dict(bucket, length)。

    - short : <= 50 字   原样输出
    - long  : > 50 字    需要精炼
    """
    n = len(str(text or '').strip())
    bucket = 'short' if n <= REFINE_THRESHOLD else 'long'
    return {'bucket': bucket, 'length': n}


def decide(text):
    """根据长度自动判断处理策略。

    返回 dict：
      - action: 'none' | 'refine'
      - reason: 判断依据
      - bucket: 长度分档
    """
    info = classify(text)
    bucket = info['bucket']
    if bucket == 'short':
        return {'action': 'none', 'bucket': bucket, 'reason': '很短，原样输出'}
    return {'action': 'refine', 'bucket': bucket,
            'reason': '超过 %d 字，精炼后输出，完整内容存文档' % REFINE_THRESHOLD}


def _chat(messages, max_tokens=2000, temperature=0.3, timeout=90):
    """复用聊天 API 调用其他 AI 辅助。失败返回 None。"""
    import requests
    cfg = _load_cfg()
    key = (cfg.get('api_key') or '').strip()
    base = (cfg.get('base_url') or '').rstrip('/')
    if not key or key.startswith('YOUR_') or not base:
        return None
    try:
        r = requests.post(
            base + '/chat/completions',
            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
            json={'model': cfg.get('model', 'qwen-plus'),
                  'messages': messages, 'max_tokens': max_tokens,
                  'temperature': temperature}, timeout=timeout)
        if r.status_code != 200:
            return None
        return (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '').strip() or None
    except Exception:
        return None


def summarize(text, max_chars=180):
    """提炼重点：口语化短句，适合朗读。失败降级为按句截断。"""
    from core.answer_export import summarize_speech
    return summarize_speech(text, max_chars=max_chars)


def refine(text):
    """精炼全文：压缩篇幅但保留结构要点，输出结构化 Markdown。"""
    text = str(text or '').strip()
    if not text:
        return text
    out = _chat([{'role': 'user', 'content':
                  '把下面这段长回答精炼压缩：保留所有关键结论、要点和结构，'
                  '去掉冗余铺垫和重复表述，用简洁的 Markdown（## 小标题 + - 要点）重新组织，'
                  '信息不遗漏但篇幅明显缩短。只输出精炼后的正文。\n\n' + text}],
                max_tokens=2500, temperature=0.3)
    if out and out.strip():
        return out.strip()
    # 降级：原样返回
    return text


def generate(text, title=None, want=('document', 'mindmap'), out_dir=None):
    """调用已有工具生成文档/思维导图，返回产物路径 dict。

    want 可含 'document' / 'mindmap'。失败单项降级不阻断其余。
    """
    from core.answer_export import save_document, save_mindmap, derive_title
    title = (title or derive_title(text)).strip()
    result = {'title': title, 'document': None, 'mindmap': None, 'errors': []}
    try:
        if 'document' in want:
            result['document'] = save_document(text, out_dir=out_dir)
    except Exception as exc:
        result['errors'].append('文档生成失败：' + str(exc))
    try:
        if 'mindmap' in want:
            mm = save_mindmap(text, out_dir=out_dir)
            result['mindmap'] = {'outline': mm.get('outline'), 'html': mm.get('html')}
    except Exception as exc:
        result['errors'].append('思维导图失败：' + str(exc))
    return result


def process(text, title=None, want=('document', 'mindmap'), out_dir=None):
    """统一入口：自动判断策略 + 提炼/精炼 + 生成产物。

    返回 dict：
      - decision: decide() 的结果
      - spoken: 适合朗读/直接输出的文本（提炼或精炼后的版本，或原样）
      - artifacts: generate() 的产物路径
    """
    text = str(text or '').strip()
    decision = decide(text)
    action = decision['action']
    spoken = text
    artifacts = None
    if action == 'refine':
        refined = refine(text)
        spoken = refined or text
        artifacts = generate(text, title=title, want=want, out_dir=out_dir)
    # action == 'none'：很短，原样输出，不生成产物
    return {'decision': decision, 'spoken': spoken, 'artifacts': artifacts}
