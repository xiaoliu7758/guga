# -*- coding: utf-8 -*-
"""TTS 语音合成引擎 — 咕嘎企鹅版（edge-tts 软萌音优先 + 豆包兜底）

v2 修复（针对崩溃/磁盘泄漏）:
- 后台线程只合成 mp3 文件, 通过 Qt 信号把"已就绪"的文件路径传回主线程,
  QMediaPlayer 的 setMedia/play 只在主线程调用（QObject 必须主线程操作）。
- 临时 mp3 用完即删; 启动时清理本程序遗留的旧 mp3; _temp_files 限长防堆积。
- 合成加超时保护, 防止 edge-tts asyncio 在网络异常时永久挂起。
- 用 speak token 区分每次说话, stop()/新 speak 后旧合成完成不会误播。
"""
import os
import sys
import asyncio
import threading
import tempfile
import time
import uuid
import json
import base64
import re
import glob
from PyQt5.QtCore import QObject, pyqtSignal, QUrl
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

# 朗读前去除标点（TTS 不读标点符号）
_PUNCT_RE = re.compile(r'[，。！？、；：“”‘’（）【】《》〈〉…—·｜|%％~\-_]+')

# 临时文件前缀（用于启动时清理残留）+ 同时限长
_TMP_PREFIX = 'guga_tts_'
_MAX_TEMP_FILES = 4
_SYNTH_TIMEOUT = 20  # 单次合成最长 20 秒


def strip_punct(text: str) -> str:
    text = _PUNCT_RE.sub('', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class TTSEngine(QObject):
    """语音合成引擎

    优先级: edge-tts（软萌少女音）> 豆包语音V3 > 静默
    - edge-tts: 免费，微软神经语音，企鹅用软萌音色 + 提高音调
    - 豆包语音V3: 兜底
    线程模型:
      speak() → 后台线程合成 mp3 → 发 ready 信号 → 主线程播放
      QMediaPlayer 永远只在主线程操作, 杜绝跨线程崩溃
    """

    speak_finished = pyqtSignal()
    speak_started = pyqtSignal(str)

    EDGE_VOICE = "zh-CN-XiaoyiNeural"   # 软萌少女音
    EDGE_RATE = "+15%"
    EDGE_RATE_TUTOR = "+5%"             # 助教模式慢一点
    EDGE_PITCH = "+14Hz"                # 提高音调 → 更软萌
    _tutor_mode = False

    def set_tutor_mode(self, on: bool):
        self._tutor_mode = bool(on)

    def _current_rate(self):
        return self.EDGE_RATE_TUTOR if self._tutor_mode else self.EDGE_RATE

    DOUBAO_API_KEY = ""
    DOUBAO_VOICE = "zh_female_mizai_saturn_bigtts"
    DOUBAO_SPEED = -15
    DOUBAO_RESOURCE = "seed-tts-2.0"

    # 主线程接收: (token, path) — 合成完毕, 主线程负责播放
    _synth_ready = pyqtSignal(int, str)
    # 主线程接收: (token,) — 合成失败, 主线程负责收尾
    _synth_failed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._player = QMediaPlayer()
        self._player.setVolume(80)
        self._player.stateChanged.connect(self._on_state_changed)
        self._temp_files = []   # 主线程持有, 仅主线程修改
        self._is_speaking = False
        self._session = None
        self._speak_token = 0   # 每次 speak 自增, 用于失效旧请求
        self._current_token = 0  # 当前正在播放的 token
        # 分段朗读队列
        self._segments = []
        self._seg_index = 0
        self._voice_profile = None

        try:
            cfg_path = os.path.join(os.path.dirname(__file__), '..', 'ai_config.json')
            with open(cfg_path, encoding='utf-8-sig') as f:
                _cfg = json.load(f)
        except Exception:
            _cfg = {}
        self.DOUBAO_API_KEY = _cfg.get('doubao_tts_api_key', '')
        self._use_doubao = bool(self.DOUBAO_API_KEY)

        # 千问 TTS 兜底: edge-tts 被墙/超时时改用 dashscope qwen3-tts-flash
        _tts_cfg = _cfg.get('tts') or {}
        _qwen_key = str(_tts_cfg.get('qwen_api_key') or _cfg.get('api_key') or '').strip()
        self.QWEN_TTS_KEY = '' if _qwen_key.startswith('YOUR_') else _qwen_key
        self.QWEN_TTS_MODEL = _tts_cfg.get('qwen_model', 'qwen3-tts-flash')
        self.QWEN_TTS_VOICE = _tts_cfg.get('qwen_voice', 'Cherry')
        self.QWEN_TTS_ENABLED = bool(_tts_cfg.get('qwen_enabled', True))
        self._use_qwen = bool(self.QWEN_TTS_KEY) and self.QWEN_TTS_ENABLED
        self._use_edge = self._check_edge_tts()

        if self._use_doubao:
            try:
                import requests
                self._session = requests.Session()
            except ImportError:
                self._use_doubao = False

        # 信号 → 主线程槽
        self._synth_ready.connect(self._on_synth_ready)
        self._synth_failed.connect(self._on_synth_failed)

        # 启动时清理上次崩溃残留的临时 mp3
        self._cleanup_stale_tmp()

        print(f"[TTS] edge-tts(软萌音): {'可用' if self._use_edge else '不可用'}")
        print(f"[TTS] 豆包语音V3: {'可用' if self._use_doubao else '未配置'}")
        print(f"[TTS] 千问兜底({self.QWEN_TTS_MODEL}): {'可用' if self._use_qwen else '未配置'}")

    # ---- 依赖检查 ----
    def _check_edge_tts(self):
        try:
            import edge_tts  # noqa
            return True
        except ImportError:
            return False

    # ---- 对外: 说话 ----
    def speak(self, text: str, voice_profile=None):
        if not text.strip():
            return
        text = strip_punct(text)
        if not text.strip():
            return
        # 中断当前播放并递增 token, 让进行中的旧合成即使完成也不会被播放
        self._stop_playback()
        self._speak_token += 1
        self._is_speaking = True
        # 分段：edge-tts 单次合成有长度上限，超长文本切成多段逐段播放，保证念全
        self._segments = _split_segments(text)
        self._voice_profile = dict(voice_profile) if voice_profile else None
        self._seg_index = 0
        self.speak_started.emit(text)
        self._play_segment()

    def _play_segment(self):
        """合成并播放当前段；已到末尾则结束。"""
        if self._seg_index >= len(self._segments):
            return
        text = self._segments[self._seg_index]
        self._seg_index += 1
        token = self._speak_token
        args = (token, text, self._voice_profile) if self._voice_profile else (token, text)
        threading.Thread(target=self._synth_worker, args=args, daemon=True).start()

    @staticmethod
    def _split_segments(text: str, max_len: int = 280):
        """把长文本按句子边界切成若干段，每段不超过 max_len 字，尽量在句号处断开。"""
        # 先按常见句末标点切分句子，再贪心合并到不超过 max_len
        sentences = re.split(r'(?<=[。！？!?])', text)
        segments = []
        cur = ''
        for s in sentences:
            if not s.strip():
                continue
            if len(cur) + len(s) <= max_len:
                cur += s
            else:
                if cur.strip():
                    segments.append(cur.strip())
                cur = s
                # 单句本身超长：硬切
                while len(cur) > max_len:
                    segments.append(cur[:max_len])
                    cur = cur[max_len:]
        if cur.strip():
            segments.append(cur.strip())
        return segments or [text]

    def stop(self):
        """外部停止: 停播放 + 失效当前 token"""
        self._speak_token += 1  # 让尚未完成的合成无效
        self._stop_playback()

    # ---- 主线程: 停止播放 ----
    def _stop_playback(self):
        if self._is_speaking:
            try:
                self._player.stop()
            except Exception:
                pass
        self._is_speaking = False
        self._segments = []
        self._seg_index = 0
        self._cleanup_temp()

    # ---- 后台线程: 合成 ----
    def _synth_worker(self, token: int, text: str, voice_profile=None):
        """后台线程只负责生成 mp3 文件; 完成后发信号回主线程"""
        tmp_path = None
        try:
            tmp = tempfile.NamedTemporaryFile(
                prefix=_TMP_PREFIX, suffix='.mp3', delete=False,
                dir=tempfile.gettempdir())
            tmp_path = tmp.name
            tmp.close()

            success = False
            if self._use_edge:
                success = self._synth_edge(text,tmp_path,voice_profile) if voice_profile else self._synth_edge(text,tmp_path)
            # A failed companion voice must not silently become Guga's fallback.
            if not success and self._use_doubao and not voice_profile:
                success = self._synth_doubao(text, tmp_path)
            # 最后兜底: 千问 TTS(返回 wav, 单独一个文件, 成功后替换播放路径)
            if not success and self._use_qwen and not voice_profile:
                wav_path = self._synth_qwen(text, os.path.splitext(tmp_path)[0] + '.wav')
                if wav_path:
                    self._safe_remove(tmp_path)
                    tmp_path = wav_path
                    success = True

            if not success:
                # 失败: 清掉空文件, 通知主线程收尾
                self._safe_remove(tmp_path)
                self._synth_failed.emit(token)
                return

            # 校验文件有效
            if not (os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 100):
                self._safe_remove(tmp_path)
                self._synth_failed.emit(token)
                return

            # 成功: 通知主线程播放
            self._synth_ready.emit(token, tmp_path)
        except Exception as e:
            print(f"[TTS] synth_worker 错误: {e}", file=sys.stderr)
            self._safe_remove(tmp_path)
            try:
                self._synth_failed.emit(token)
            except Exception:
                pass

    def _synth_edge(self, text: str, out_path: str, voice_profile=None) -> bool:
        """edge-tts 合成, 加超时防止网络卡死"""
        try:
            import edge_tts

            async def _synth():
                communicate = edge_tts.Communicate(
                    text, (voice_profile or {}).get('edge_voice',self.EDGE_VOICE),
                    rate=(voice_profile or {}).get('edge_rate',self._current_rate()),
                    pitch=(voice_profile or {}).get('edge_pitch',self.EDGE_PITCH),
                    volume="+0%"
                )
                await communicate.save(out_path)

            try:
                # asyncio 超时: 防止 edge-tts 网络异常时永久挂起
                asyncio.run(asyncio.wait_for(_synth(), timeout=_SYNTH_TIMEOUT))
            except asyncio.TimeoutError:
                print("[TTS] edge-tts 合成超时", file=sys.stderr)
                self._safe_remove(out_path)
                return False
            return os.path.exists(out_path) and os.path.getsize(out_path) > 100

        except Exception as e:
            print(f"[TTS] edge-tts 错误: {e}", file=sys.stderr)
            self._safe_remove(out_path)
            return False

    def _synth_doubao(self, text: str, out_path: str) -> bool:
        try:
            import requests
            sess = self._session or requests
            url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
            headers = {
                "Content-Type": "application/json",
                "X-Api-Key": self.DOUBAO_API_KEY,
                "X-Api-Resource-Id": self.DOUBAO_RESOURCE,
                "X-Api-Request-Id": str(uuid.uuid4()),
            }
            body = {
                "user": {"uid": "black_cat_pet"},
                "req_params": {
                    "text": text,
                    "speaker": self.DOUBAO_VOICE,
                    "audio_params": {
                        "format": "mp3",
                        "sample_rate": 24000,
                        "speech_rate": self.DOUBAO_SPEED,
                    }
                }
            }

            resp = sess.post(url, headers=headers, json=body, timeout=30, stream=True)
            audio_parts = []
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    j = json.loads(line.decode('utf-8'))
                    code = j.get("code", -1)
                    if code == 0:
                        d = j.get("data")
                        if d:
                            audio_parts.append(base64.b64decode(d))
                    elif code == 20000000:
                        break
                    elif code not in (0, 20000000):
                        msg = j.get("message", "")
                        print(f"[TTS] 豆包语音响应错误 code={code}: {msg[:100]}",
                              file=sys.stderr)
                except Exception:
                    continue

            if audio_parts:
                audio_data = b"".join(audio_parts)
                with open(out_path, 'wb') as f:
                    f.write(audio_data)
                return True
            return False

        except Exception as e:
            print(f"[TTS] 豆包语音错误: {e}", file=sys.stderr)
            self._safe_remove(out_path)
            return False

    def _synth_qwen(self, text: str, out_path: str):
        """千问 TTS 兜底: 返回 wav 文件路径, 失败返回 None

        dashscope 只返回 wav 的临时下载地址, 所以单独落地成 .wav 再交给播放器,
        不能写进 .mp3 临时文件, 否则 QMediaPlayer 按扩展名选解析器会失败。
        """
        try:
            import requests
            resp = requests.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
                "multimodal-generation/generation",
                headers={
                    "Authorization": f"Bearer {self.QWEN_TTS_KEY}",
                    "Content-Type": "application/json",
                },
                json={"model": self.QWEN_TTS_MODEL,
                      "input": {"text": text, "voice": self.QWEN_TTS_VOICE}},
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"[TTS] 千问TTS HTTP {resp.status_code}: {resp.text[:120]}",
                      file=sys.stderr)
                return None
            url = (((resp.json().get("output") or {}).get("audio") or {}).get("url") or "")
            if not url:
                print("[TTS] 千问TTS 未返回音频地址", file=sys.stderr)
                return None
            audio = requests.get(url, timeout=30)
            if audio.status_code != 200 or len(audio.content) <= 100:
                print(f"[TTS] 千问TTS 下载失败 {audio.status_code}", file=sys.stderr)
                return None
            with open(out_path, 'wb') as f:
                f.write(audio.content)
            return out_path
        except Exception as e:
            print(f"[TTS] 千问TTS 错误: {e}", file=sys.stderr)
            self._safe_remove(out_path)
            return None

    # ---- 主线程槽: 合成完成 ----
    def _on_synth_ready(self, token: int, path: str):
        # 若已经被新的 speak / stop 失效, 直接清理不播放
        if token != self._speak_token:
            self._safe_remove(path)
            return
        # 若 _is_speaking 已被 stop 清掉, 也不要播
        if not self._is_speaking:
            self._safe_remove(path)
            return
        try:
            # 临时文件列表限长: 超出 _MAX_TEMP_FILES 删最旧
            self._temp_files.append(path)
            while len(self._temp_files) > _MAX_TEMP_FILES:
                old = self._temp_files.pop(0)
                self._safe_remove(old)

            url = QUrl.fromLocalFile(path)
            content = QMediaContent(url)
            self._current_token = token
            self._player.setMedia(content)
            self._player.play()
        except Exception as e:
            print(f"[TTS] 播放错误: {e}", file=sys.stderr)
            self._safe_remove(path)
            self._is_speaking = False
            try:
                self.speak_finished.emit()
            except Exception:
                pass

    def _on_synth_failed(self, token: int):
        if token != self._speak_token:
            return
        self._is_speaking = False
        try:
            self.speak_finished.emit()
        except Exception:
            pass

    def _on_state_changed(self, state):
        if state == QMediaPlayer.StoppedState and self._is_speaking:
            # 一段播完：还有下一段则继续合成播放，否则才算真正结束
            if self._seg_index < len(self._segments):
                self._play_segment()
                return
            self._is_speaking = False
            self._cleanup_temp()
            try:
                self.speak_finished.emit()
            except Exception:
                pass

    # ---- 临时文件清理 ----
    def _cleanup_temp(self):
        """主线程调用: 清掉所有已记录的临时 mp3"""
        for f in self._temp_files[:]:
            self._safe_remove(f)
        self._temp_files.clear()

    @staticmethod
    def _safe_remove(path):
        if not path:
            return
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _cleanup_stale_tmp(self):
        """启动时清理上次崩溃/强杀残留的临时音频 (只清前缀 _TMP_PREFIX)"""
        try:
            tmp_dir = tempfile.gettempdir()
            now = time.time()
            for pattern in ('*.mp3', '*.wav'):
                for f in glob.glob(os.path.join(tmp_dir, _TMP_PREFIX + pattern)):
                    try:
                        # 只清 1 天以内的(避免误删他人文件), 老文件系统自己会清
                        if now - os.path.getmtime(f) < 86400:
                            os.remove(f)
                    except Exception:
                        continue
        except Exception:
            pass

    @property
    def is_speaking(self):
        return self._is_speaking
