"""chat_window.py —— 聊天窗(阶段2修订:整个窗口就是漫画气泡)。

窗口本身 = 漫画对话气泡:圆角白底气泡体 + 底部一条与轮廓连成一体的弧形尾巴
(单条 QPainterPath 画完,填充+描边无接缝),尾巴在左下还是右下由 main
摆位时决定(set_tail_side)。里面是对话记录和输入行,回车发送;
请求中禁输入;Esc 或 × 关闭(隐藏,历史保留)。空白处可拖动。
半透明背景只画气泡形状,不画矩形窗底。
"""

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, \
    QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

BORDER = 2        # 气泡描边宽
TAIL = 14         # 尾巴高度
RADIUS = 13.0     # 气泡圆角
INK = "#3a3a3a"

STYLE = """
QTextBrowser { border: none; background: transparent; font-size: 13px; color:#333333; }
QLineEdit { border: 1px solid #d8d2c4; border-radius: 6px; padding: 5px 8px;
            background: #ffffff; font-size: 13px; }
QLineEdit:disabled { background: #f4f1e9; color: #999; }
QPushButton { border: 1px solid #d8d2c4; border-radius: 6px; padding: 5px 14px;
              background: #f6f2e8; font-size: 13px; }
QPushButton:hover { background: #efe8d8; }
QLabel { color: #6b6152; background: transparent; }
"""


class ChatWindow(QWidget):
    """纯 UI 壳:所有网络行为都在 ChatClient,本类只管显示与开关输入。"""
    hidden = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._active_character_id = client.character_id
        self._messages = {client.character_id: []}
        self._drafts = {}
        self.on_open_settings = None   # 由 main 注入:打开设置对话框
        self._drag_offset = None
        self._tail_side = "left"       # 尾巴在底边的哪一侧(指向角色)
        self.setWindowTitle("聊天")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(320, 420)
        self.setStyleSheet(STYLE)

        self.title = QLabel()
        set_btn = QPushButton("设置")
        set_btn.clicked.connect(self._open_settings)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("font-size: 13px; padding: 0; font-weight: bold;")
        close_btn.clicked.connect(self.hide)
        header = QHBoxLayout()
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(set_btn)
        header.addSpacing(6)
        header.addWidget(close_btn)

        self.log = QTextBrowser()
        self.log.setReadOnly(True)

        self.input = QLineEdit()
        self.input.setPlaceholderText("和她说点什么…")
        self.send_btn = QPushButton("发送")
        input_row = QHBoxLayout()
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn)

        layout = QVBoxLayout(self)
        # 底部留出尾巴的高度,内容不许画进气泡尾巴里
        layout.setContentsMargins(12, 12, 12, TAIL + 8)
        layout.addLayout(header)
        layout.addWidget(self.log, 1)
        layout.addLayout(input_row)

        self.input.returnPressed.connect(self._send)
        self.send_btn.clicked.connect(self._send)
        self.client.reply_arrived.connect(self._on_reply)
        self.client.reply_failed.connect(self._on_fail)
        self.client.busy_changed.connect(self._on_busy)
        self.client.persona_changed.connect(self._refresh_title)
        self.client.character_changed.connect(self._on_character_changed)
        self._refresh_title()

    # ---- 形状 --------------------------------------------------------------
    def set_tail_side(self, side):
        """尾巴位置:'left'(窗在角色右侧)/'right'(窗在角色左侧)/'center'(窗在头顶正上方)。"""
        self._tail_side = side
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w, h = self.width(), self.height()
            bh = h - TAIL                      # 气泡体底边
            x0, y0, x1, y1 = 1.0, 1.0, w - 1.0, bh - 1.0   # 内缩 1px 给描边留位
            # 尾巴:尖端朝角色一侧偏移(尾巴在左下=窗在角色右侧 → 尖端向左),
            # center = 窗在头顶正上方,尾巴垂直向下指
            if self._tail_side == "left":
                tx, toward = 44.0, -16.0
            elif self._tail_side == "right":
                tx, toward = w - 44.0, 16.0
            else:
                tx, toward = w / 2.0, 0.0
            base = 20.0
            tip_x = tx + toward

            path = QPainterPath()
            path.moveTo(x0 + RADIUS, y0)
            path.lineTo(x1 - RADIUS, y0)
            path.quadTo(x1, y0, x1, y0 + RADIUS)                 # 右上圆角
            path.lineTo(x1, y1 - RADIUS)
            path.quadTo(x1, y1, x1 - RADIUS, y1)                 # 右下圆角
            path.lineTo(tx + base, y1)                           # 底边右段
            # 尾巴:右根 → 尖端 → 左根,两条二次曲线
            path.quadTo(tx + base * 0.45, y1 + TAIL * 0.9, tip_x, y1 + TAIL)
            path.quadTo(tx + toward * 0.25, y1 + TAIL * 0.35,
                        tx - base, y1)
            path.lineTo(x0 + RADIUS, y1)                         # 底边左段
            path.quadTo(x0, y1, x0, y1 - RADIUS)                 # 左下圆角
            path.lineTo(x0, y0 + RADIUS)
            path.quadTo(x0, y0, x0 + RADIUS, y0)                 # 左上圆角
            path.closeSubpath()

            pen = QPen(QColor(INK), BORDER)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(QBrush(QColor("#ffffff")))
            p.drawPath(path)
        finally:
            # 🔴 paintEvent 里抛异常时必须保证 painter 结束,否则
            # "endPaint called with active painter" 会一路腐蚀到 backing store 段错误
            p.end()

    # ---- 显示 ------------------------------------------------------------
    def _refresh_title(self, name=None):
        self.title.setText(f"和 {name or self.client.char_name} 聊天")

    def _append(self, html_frag):
        """追加一条消息,并**显式强制左对齐**。
        🔴 不能用 <p align=…> 或裸 append():QTextEdit.append 会继承上一段的
        对齐(上一条右对齐会把她的回复带歪),HTML 里的 align="left" 又会被
        解析器当默认值丢掉——所以插入后用光标对刚插入的块统一设 AlignLeft。"""
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        start = cursor.position()
        if self.log.toPlainText():
            cursor.insertBlock()          # 每条消息独立段落(首条不用,避免顶部空行)
        cursor.insertHtml(html_frag)
        end = self.log.textCursor().position()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        bf = QTextBlockFormat()
        bf.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cursor.setBlockFormat(bf)         # 作用于选区内所有块
        cursor.clearSelection()           # 光标停末尾且不带选区,自动滚到底
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _remember(self, kind, text):
        self._messages.setdefault(self._active_character_id, []).append((kind, text))

    def _say_user(self, text, record=True):
        # 我的消息:左对齐,名字冷蓝,正文深色
        if record:
            self._remember("user", text)
        body = html.escape(text).replace("\n", "<br>")
        self._append(f'<b style="color:#3a6ea5">你</b>'
                     f'<span style="color:#333333">　{body}</span>')

    def _say_pet(self, text, record=True):
        # 她的回复:左对齐,名字暖红,正文深色
        if record:
            self._remember("pet", text)
        name = html.escape(self.client.char_name)
        body = html.escape(text).replace("\n", "<br>")
        self._append(f'<b style="color:#b0523f">{name}</b>'
                     f'<span style="color:#333333">　{body}</span>')

    def _say_sys(self, text, record=True):
        if record:
            self._remember("system", text)
        self._append(f'<span style="color:#8a8274"><i>{html.escape(text)}</i></span>')

    def _on_character_changed(self, character_id):
        """气泡记录和未发送草稿也跟着角色切换,避免显示旧角色的对话。"""
        self._drafts[self._active_character_id] = self.input.text()
        self._active_character_id = character_id
        self.input.setText(self._drafts.get(character_id, ""))
        self.log.clear()
        for kind, text in self._messages.setdefault(character_id, []):
            if kind == "user":
                self._say_user(text, record=False)
            elif kind == "pet":
                self._say_pet(text, record=False)
            else:
                self._say_sys(text, record=False)

    # ---- 发送与回调 --------------------------------------------------------
    def _send(self):
        text = self.input.text().strip()
        if not text or self.client.busy:
            return
        self._say_user(text)
        self.input.clear()
        self.client.send(text)   # 无 key 时 client 会自己发 reply_failed 引导

    def _on_busy(self, busy):
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)
        self.input.setPlaceholderText("她在想…" if busy else "和她说点什么…")

    def _on_reply(self, text):
        self._say_pet(text)

    def _on_fail(self, text):
        self._say_sys(text)

    def _open_settings(self):
        if callable(self.on_open_settings):
            self.on_open_settings()

    # ---- 窗口行为 ----------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.hidden.emit()

    # 空白处/标题可拖动(输入框、按钮、记录区自己消费鼠标事件,不会误触发)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
