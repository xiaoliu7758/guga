# -*- coding: utf-8 -*-
"""咕嘎桌宠网络自检 — 一条命令查清所有外联链路

检查项:
  1. 聊天 API        ai_config.json: base_url / model / api_key
  2. 视觉 API        vision_base_url / vision_model / vision_api_key
  3. 实时语音        realtime_voice（只建 WebSocket 握手，不收音、不消耗音频额度）
  4. 千问 TTS 兜底   tts.qwen_*
  5. edge-tts        微软合成服务（国内常被重置，失败不代表桌宠无法播报，会走千问兜底）

用法:
  python tools/net_selfcheck.py
退出码 0 表示核心链路(1-4)全部可用。
"""
import json
import os
import sys
from urllib.parse import urlsplit

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG_PATH = os.path.join(ROOT, 'ai_config.json')

OK, BAD, SKIP = '[ OK ]', '[FAIL]', '[SKIP]'


def load_cfg():
    with open(CFG_PATH, encoding='utf-8-sig') as f:
        return json.load(f)


def _mask(key):
    key = str(key or '')
    return (key[:10] + '...' + key[-4:]) if len(key) > 20 else (key or '(空)')


def check_chat(cfg):
    base = str(cfg.get('base_url') or '').rstrip('/')
    model = cfg.get('model') or ''
    key = str(cfg.get('api_key') or '')
    if not base or base.startswith('https://YOUR') or key.startswith('YOUR_'):
        return BAD, '未配置 base_url / api_key'
    try:
        r = requests.post(base + '/chat/completions',
                          headers={'Authorization': 'Bearer ' + key},
                          json={'model': model,
                                'messages': [{'role': 'user', 'content': '只回两个字：收到'}],
                                'max_tokens': 16},
                          timeout=30)
        if r.status_code != 200:
            return BAD, f'HTTP {r.status_code}: {r.text[:120]}'
        text = (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '')
        if not text:
            return BAD, '返回空内容'
        return OK, f'{model} @ {urlsplit(base).hostname} → {text.strip()[:20]}'
    except Exception as e:
        return BAD, f'{type(e).__name__}: {str(e)[:100]}'


def check_vision(cfg):
    key = str(cfg.get('vision_api_key') or cfg.get('zhipu_api_key') or '')
    model = cfg.get('vision_model') or ''
    base = str(cfg.get('vision_base_url') or 'https://open.bigmodel.cn/api/paas/v4').rstrip('/')
    if not key or key.startswith('YOUR_'):
        return BAD, '未配置 vision_api_key'
    try:
        import base64
        import io

        from PIL import Image
        img = Image.new('RGB', (64, 64), 'red')
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        b64 = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
        r = requests.post(base + '/chat/completions',
                          headers={'Authorization': 'Bearer ' + key},
                          json={'model': model, 'max_tokens': 32, 'messages': [{
                              'role': 'user',
                              'content': [{'type': 'image_url', 'image_url': {'url': b64}},
                                          {'type': 'text', 'text': '一个字说明主色'}]}]},
                          timeout=45)
        if r.status_code != 200:
            return BAD, f'HTTP {r.status_code}: {r.text[:120]}'
        text = (r.json().get('choices') or [{}])[0].get('message', {}).get('content', '')
        return OK, f'{model} → {str(text).strip()[:20]}'
    except Exception as e:
        return BAD, f'{type(e).__name__}: {str(e)[:100]}'


def check_realtime(cfg):
    sys.path.insert(0, ROOT)
    try:
        from core.realtime_voice import connection_url, load_settings
        rv = load_settings()
        url = connection_url(rv)
        import websocket
        ws = websocket.create_connection(
            url, header=['Authorization: Bearer ' + rv['api_key'].strip()], timeout=15,
            http_no_proxy=['*'])
        try:
            event = json.loads(ws.recv())
        finally:
            ws.close()
        kind = event.get('type')
        if kind == 'session.created':
            return OK, f"{rv['provider']} / {rv['model']} 握手成功"
        if kind == 'error':
            return BAD, f"鉴权或参数错误: {str(event.get('error'))[:120]}"
        return BAD, f'意外事件 {kind}'
    except Exception as e:
        return BAD, f'{type(e).__name__}: {str(e)[:100]}'


def check_qwen_tts(cfg):
    tts = cfg.get('tts') or {}
    if not tts.get('qwen_enabled', True):
        return SKIP, 'tts.qwen_enabled = false'
    key = str(tts.get('qwen_api_key') or cfg.get('api_key') or '')
    if not key or key.startswith('YOUR_'):
        return BAD, '未配置 tts.qwen_api_key'
    try:
        r = requests.post('https://dashscope.aliyuncs.com/api/v1/services/aigc/'
                          'multimodal-generation/generation',
                          headers={'Authorization': 'Bearer ' + key},
                          json={'model': tts.get('qwen_model', 'qwen3-tts-flash'),
                                'input': {'text': '自检', 'voice': tts.get('qwen_voice', 'Cherry')}},
                          timeout=45)
        if r.status_code != 200:
            return BAD, f'HTTP {r.status_code}: {r.text[:120]}'
        url = ((r.json().get('output') or {}).get('audio') or {}).get('url')
        if not url:
            return BAD, '未返回音频地址'
        audio = requests.get(url, timeout=45)
        if audio.status_code != 200 or len(audio.content) < 1000:
            return BAD, f'音频下载失败 {audio.status_code}'
        return OK, f"{tts.get('qwen_model', 'qwen3-tts-flash')} → {len(audio.content) // 1024} KB"
    except Exception as e:
        return BAD, f'{type(e).__name__}: {str(e)[:100]}'


def check_edge_tts():
    try:
        import asyncio

        import edge_tts

        async def run():
            comm = edge_tts.Communicate('自检', 'zh-CN-XiaoyiNeural')
            n = 0
            async for chunk in comm.stream():
                if chunk['type'] == 'audio':
                    n += len(chunk['data'])
            return n

        n = asyncio.run(asyncio.wait_for(run(), timeout=20))
        return (OK if n > 1000 else BAD), f'{n // 1024} KB'
    except Exception as e:
        return BAD, f'{type(e).__name__}: {str(e)[:80]}（不影响播报，会走千问兜底）'


def report_proxy():
    keys = [k for k in os.environ if k.lower() in
            ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')]
    if not keys:
        print('  环境代理: 未设置（直连）')
        return
    for k in sorted(keys):
        val = os.environ[k]
        host = urlsplit(val).hostname if '://' in val else val
        port = urlsplit(val).port if '://' in val else None
        alive = '-'
        if host and port:
            import socket
            s = socket.socket()
            s.settimeout(2)
            try:
                s.connect((host, port))
                alive = '在线'
            except Exception:
                alive = '不可用 ← 会导致所有走环境变量的请求失败'
            finally:
                s.close()
        print(f'  {k}={val}  ({alive})')


def main():
    print('=' * 62)
    print(' 咕嘎桌宠 网络自检')
    print('=' * 62)
    try:
        cfg = load_cfg()
    except Exception as e:
        print(f'{BAD} 读取 ai_config.json 失败: {e}')
        return 2

    report_proxy()
    print()

    checks = [
        ('聊天 API', check_chat(cfg), True),
        ('视觉 API', check_vision(cfg), True),
        ('实时语音', check_realtime(cfg), True),
        ('千问 TTS', check_qwen_tts(cfg), True),
        ('edge-tts', check_edge_tts(), False),
    ]
    core_fail = 0
    for name, (tag, detail), required in checks:
        if tag == BAD and required:
            core_fail += 1
        print(f'{tag} {name:8} {detail}')

    print()
    if core_fail:
        print(f'核心链路有 {core_fail} 项不可用，桌宠对应功能会回落到降级方案。')
    else:
        print('核心链路全部可用。')
    return 0 if core_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
