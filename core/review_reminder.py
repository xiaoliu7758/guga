# -*- coding: utf-8 -*-
"""咕嘎复习提醒 —— 定时检查 FSRS 间隔重复库中到期的概念，用气泡提醒饲养员复习。

设计要点：
  - 纯逻辑 + 一个 QTimer；由 pet 在主线程创建并启动。
  - 定时检查（默认每 15 分钟），发现到期概念时弹气泡 + 语音提醒。
  - 防打扰：咕嘎正忙/语音通话/最近刚提醒过时跳过，避免刷屏。
  - 提醒过的概念记入「已提醒集合」，用户复习（卡片 due 后移）后才可能再次提醒。
  - 点击气泡可进入对话，直接说「复习」即可开始间隔重复。
"""
import time
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer

ROOT = Path(__file__).resolve().parents[1]


def _load_due():
    """返回到期的概念列表；无 fsrs 或读取失败返回空列表。"""
    try:
        from core.learning_tutor import due_reviews
        result = due_reviews(limit=10)
        if isinstance(result, dict) and 'due' in result:
            return result['due']
    except Exception:
        pass
    return []


class ReviewReminder(QObject):
    def __init__(self, pet, parent=None):
        super().__init__(parent)
        self.pet = pet
        self.timer = QTimer(self)
        self.timer.setInterval(self._interval_ms())
        self.timer.timeout.connect(self.tick)
        self._notified = set()       # 已提醒过的概念，避免重复刷屏
        self._last_notify_at = 0.0   # 上次提醒时间（防频繁打扰）
        self._cooldown = 1800        # 两次提醒之间至少间隔 30 分钟
        self.enabled = True

    # ---- 配置 ----
    @staticmethod
    def _interval_ms():
        try:
            minutes = 15
            settings = None
            return max(5, minutes) * 60 * 1000
        except Exception:
            return 15 * 60 * 1000

    def start(self):
        if self.enabled:
            self.timer.start()

    def stop(self):
        self.timer.stop()

    def status(self):
        return dict(active=self.timer.isActive(), notified=sorted(self._notified),
                    last_notify_at=self._last_notify_at, enabled=self.enabled)

    # ---- 主逻辑 ----
    def tick(self):
        if not self.enabled:
            return
        if self._busy():
            return
        due = _load_due()
        if not due:
            return
        # 过滤掉已经提醒过且尚未被复习的概念
        fresh = [c for c in due if c not in self._notified]
        if not fresh:
            return
        now = time.monotonic()
        if self._last_notify_at and now - self._last_notify_at < self._cooldown:
            return
        self._notify(fresh)

    def _busy(self):
        pet = self.pet
        if not pet.isVisible():
            return False  # 隐藏时也提醒（气泡会跟随显示）
        panel = getattr(pet, '_agent_panel', None)
        if panel is not None and getattr(panel, 'busy', False):
            return True
        if panel is not None and getattr(panel, 'voice_active', False):
            return True
        if getattr(pet, '_realtime_active', None) and pet._realtime_active():
            return True
        return False

    def _notify(self, concepts):
        self._last_notify_at = time.monotonic()
        for c in concepts:
            self._notified.add(c)
        count = len(concepts)
        first = concepts[0]
        if count == 1:
            text = '咕嘎~ 有个知识点到期该复习啦：%s。跟我说「复习」就开始吧！' % first
        else:
            text = '咕嘎~ 有 %d 个知识点到期啦，比如「%s」。跟我说「复习」一起巩固吧！' % (count, first)
        try:
            # 用助教式气泡 + 语音；动作 peek 显得温和
            self.pet._say_with_expression(text, 'playful', 'peek')
        except Exception:
            try:
                self.pet._show_agent_bubble(text)
            except Exception:
                pass

    def on_reviewed(self, concepts):
        """用户完成复习后调用，把这些概念从「已提醒」里移除，允许后续再次提醒。"""
        for c in concepts:
            self._notified.discard(c)
