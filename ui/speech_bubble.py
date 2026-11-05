"""Non-activating, clickable speech above the pet; does not own audio lifetime."""
from PyQt5.QtCore import Qt, QEvent, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication


class PetSpeechBubble(QFrame):
    clicked = pyqtSignal()
    end_call = pyqtSignal()

    def __init__(self, pet):
        super().__init__(pet, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.pet = pet
        self.call_active = False
        self.speaking = False
        self.conversation_id = None
        self.full_text = ''
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setFont(QFont('Microsoft YaHei UI', 10))
        self.setFixedWidth(326)
        self.setObjectName('SpeechBubble')
        self.setStyleSheet('''
            QFrame#BubbleCard { background:#fffdf8; border:1px solid #d9d7e7; border-radius:16px; }
            QLabel { color:#30334b; background:transparent; border:none; }
            QLabel#BubbleTitle { color:#70628d; font-size:12px; font-weight:600; }
            QLabel#BubbleHint { color:#9793a5; font-size:10px; }
            QPushButton { color:#927b84; background:transparent; border:none; padding:2px 5px; font-size:11px; }
            QPushButton:hover { color:#b6415c; background:#fbeef0; border-radius:6px; }
        ''')
        outer = QVBoxLayout(self); outer.setContentsMargins(3,3,3,8)
        card = QFrame(self); card.setObjectName('BubbleCard')
        layout = QVBoxLayout(card); layout.setContentsMargins(16,12,16,12); layout.setSpacing(7)
        header = QHBoxLayout()
        self.title = QLabel('咕嘎'); self.title.setObjectName('BubbleTitle')
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        header.addWidget(self.title,1)
        self.stop_button = QPushButton('结束通话')
        self.stop_button.setFocusPolicy(Qt.NoFocus)
        self.stop_button.clicked.connect(self.end_call)
        self.stop_button.hide()
        header.addWidget(self.stop_button)
        layout.addLayout(header)
        self.text = QLabel(); self.text.setWordWrap(True); self.text.setTextFormat(Qt.PlainText)
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(self.text)
        hint = QLabel('点击气泡，展开完整对话  ↗'); hint.setObjectName('BubbleHint')
        hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(hint)
        outer.addWidget(card)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self._expire)
        pet.installEventFilter(self)

    def set_call_active(self, active, conversation_id=None):
        self.call_active = bool(active)
        if conversation_id:
            self.conversation_id = conversation_id
        self.stop_button.setVisible(self.call_active)
        self.title.setText('咕嘎 · 正在听' if active else '咕嘎')
        if active:
            self.show_text('我在听，可以直接和我说话。', self.conversation_id)
        elif self.isVisible():
            self.show_text('通话已结束。', self.conversation_id)
            self.timer.start(4000)

    def show_text(self, text, conversation_id=None):
        self.full_text = str(text).strip()
        if not self.full_text:
            return
        if conversation_id:
            self.conversation_id = conversation_id
        # The complete response stays in the conversation; keep the pet unobstructed.
        preview = self.full_text[:220]
        if len(self.full_text)>220:
            preview = preview.rstrip()+'…'
        self.text.setText(preview)
        self.setToolTip('点击打开当前对话')
        self.adjustSize()
        self.follow_pet()
        if self.pet.isVisible():
            self.show()
        if not self.speaking:
            self.timer.start(12000)

    def set_speaking(self, speaking):
        self.speaking = bool(speaking)
        self.title.setText('咕嘎 · 正在回答' if speaking else ('咕嘎 · 正在听' if self.call_active else '咕嘎'))
        if speaking:
            self.timer.stop()
        elif self.isVisible():
            self.timer.start(12000)

    def _expire(self):
        if self.call_active:
            self.text.setText('正在听你说话…')
            self.adjustSize(); self.follow_pet()
        else:
            self.hide()

    def follow_pet(self):
        center = self.pet.frameGeometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        x = center.x()-self.width()//2
        y = self.pet.frameGeometry().top()-self.height()+22
        # At the top screen edge, keep the bubble visible beside the pet.
        if y<area.top():
            y = self.pet.frameGeometry().top()
            x = self.pet.frameGeometry().right()+8
        x = max(area.left(),min(x,area.right()-self.width()+1))
        y = max(area.top(),min(y,area.bottom()-self.height()+1))
        self.move(x,y)

    def eventFilter(self, obj, event):
        if obj is self.pet:
            if event.type() in (QEvent.Move,QEvent.Resize):
                self.follow_pet()
            elif event.type()==QEvent.Hide:
                self.hide()
            elif event.type()==QEvent.Show and self.call_active:
                self.follow_pet(); self.show()
        return super().eventFilter(obj,event)

    def mouseReleaseEvent(self, event):
        if event.button()==Qt.LeftButton:
            self.clicked.emit(); event.accept()
        else:
            super().mouseReleaseEvent(event)
