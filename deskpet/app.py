#!/usr/bin/env python3
"""DeskPet：原创角色明里为默认，其他角色可从 .petpack 导入。

使用 PySide6 的无边框置顶透明 QLabel 和 QTimer 状态机。
素材为内置 `sprites/` 六帧和用户导入的皮肤包。
皮肤规格 = idle_1(睁眼)/idle_2(闭眼)/cheer(动作1)/走路帧 + 可选 fall(动作2):
走路帧数每套皮肤各自探测,4 帧齐走 4 帧循环、只有前 2 帧齐走 2 帧循环,
目录皮肤的必需帧见项目根目录的 README。

运行:
    ./venv/bin/python -B main.py

玩法:
    - 明里会在屏幕底部自己走来走去、站着眨眼;聊天窗开着时只站定不散步(仍可拖拽)
    - 鼠标左键按住可以拖拽她,松手后重力下落、落地轻弹回待机
    - 左键单击她,播放当前皮肤的欢呼动作
    - 双击她或右键选「聊天」,聊天气泡会贴在她头顶(先在「设置」里填 DeepSeek API key)
    - 右键点击她,弹出菜单:皮肤/导入皮肤包/聊天/设置…/退出
"""

import json
import os
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap, QMouseEvent, QAction, QTransform
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QMenu, QMessageBox

from . import pet_config, petpack
from .chat_client import ChatClient
from .chat_window import ChatWindow
from .settings_dialog import SettingsDialog

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_ROOT = getattr(sys, "_MEIPASS", PROJECT_ROOT)
SPRITE_DIR = os.path.join(RESOURCE_ROOT, "sprites")
SKINS_DIR = os.path.join(RESOURCE_ROOT, "skins")
# 内置默认皮肤(sprites/)的显示名;角色 ID 在 pet_config.DEFAULT_CHARACTER_ID
DEFAULT_SKIN_NAME = "默认角色"
DEFAULT_CHARACTER_ID = pet_config.DEFAULT_CHARACTER_ID

# 行为参数(想调节奏就改这里)
SCALE = 3                 # 显示放大倍数(素材 54×80,显示 162×240;必须整数倍)
WALK_SPEED = 9            # 走路速度(逻辑像素/帧,必须是 SCALE 的整数倍,否则错相位抖动)
                          # 9 = 3 源像素/tick:v2 步幅小,零打滑约 204 px/s,9 → 180 px/s 打滑仅 12%
WALK_ANIM_TICKS = 5       # 每 N tick 换一帧(5 × 50ms = 250ms;每 tick 翻太快)
# 走路循环(皮肤 6 图规格):walk_1=contact 低位、walk_2=passing 抬 1 源像素;
# 左右不画第二套图,向右走直接镜像翻转(见 set_frame)。
# 这两个全局只是「2 帧默认值」:实际每套皮肤在 _load_skin 里各自探测走路帧数
# (4 帧齐 → 4 帧循环,只有前 2 帧齐 → 2 帧循环),播放时读 Skin.walk_poses/walk_lift。
WALK_POSES = ("walk_1", "walk_2")
WALK_LIFT = (0, SCALE)
TICK_MS = 50              # 逻辑帧间隔(毫秒)
BLINK_MIN, BLINK_MAX = 40, 120   # 待机多少帧后眨一次眼(随机区间)
WALK_CHANCE = 0.008       # 待机时每一帧开始走路的概率
STOP_CHANCE = 0.01        # 走路时每一帧停下的概率
CHEER_TICKS = 20          # 欢呼持续多少帧(20 * 50ms = 1秒)
# 重力下落手感
GRAVITY = 1.5             # 下落加速度(屏幕像素/帧²)
FALL_V0 = 0               # 松手时的初速度
BOUNCE = 0.35             # 落地回弹系数(每次弹起速度 *= BOUNCE)
BOUNCE_MIN_V = 2.0        # 弹起速度低于此值就停,回待机

# 一套皮肤必须齐备的帧(idle/cheer + 走路;走路帧数每套皮肤各自探测,见
# _probe_walk_frames,这里按 2 帧默认列出)。缺任一必需帧,该皮肤会被跳过
# (内置默认皮肤除外,缺了直接退出)
REQUIRED_FRAMES = ("idle_1", "idle_2", "cheer") + WALK_POSES
# 帧名 → 文件名候选(按序取第一个存在的):走路帧老皮肤是 4 帧文件
# walk_cycle_v2_1..4,老名优先可避免误选 sprites/ 里正面朝向的废弃 walk_1/2;
# 四个走路位置都支持老名回退新名
FRAME_FILES = {
    "walk_1": ("walk_cycle_v2_1", "walk_1"),
    "walk_2": ("walk_cycle_v2_2", "walk_2"),
    "walk_3": ("walk_cycle_v2_3", "walk_3"),
    "walk_4": ("walk_cycle_v2_4", "walk_4"),
}
PET_DISPLAY_H = 80 * SCALE   # 像素皮肤显示高度(逻辑像素)
HD_DISPLAY_H = 240           # 高清皮肤显示高度(逻辑像素);和像素版一致,442px素材缩小到240显示


@dataclass
class Skin:
    """一套皮肤:显示名 + {帧名: 已放大并声明 dpr 的 QPixmap} + 走路循环参数
    (walk_poses=走路帧名元组、walk_lift=每帧对应的抬升像素,两者等长)。
    persona 来自内置目录或 .petpack:{name,user_title,extra},切角色时联动对话。"""
    name: str
    frames: dict
    walk_poses: tuple = WALK_POSES
    walk_lift: tuple = WALK_LIFT
    persona: dict = None
    character_id: str = DEFAULT_CHARACTER_ID


class DeskPetWidget(QLabel):
    def __init__(self):
        super().__init__()

        # 加载素材帧,按 SCALE*dpr 最近邻放大并声明 dpr:
        # Retina 上屏时 1:1 取物理像素,不会再被二次平滑缩放(改单 02)。
        # 皮肤 = 内置默认皮肤(sprites/)+ skins/ 与用户皮肤目录下每套图;右键可切换。
        self.dpr = QApplication.primaryScreen().devicePixelRatio()
        self.skins = self._discover_skins()
        self._character_defaults = self._collect_character_defaults()
        cfg = pet_config.load()
        # 恢复上次使用的皮肤(没配置/皮肤被删/名字对不上 → 回第 0 套)
        self.skin_index = self._index_of(pet_config.get_str(cfg, "last_skin"))
        self.skin = self.skins[self.skin_index]  # 当前皮肤(走路循环参数从这里读)
        self.frames = self.skin.frames           # 状态机其余代码只认 self.frames

        # 窗口:无边框 + 透明 + 置顶
        # 注意:不要加 Qt.Tool —— macOS 上 Tool 窗口会在程序失去焦点时自动隐藏
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        first = self.frames["idle_1"]
        self.setPixmap(first)
        # 窗口/拖拽命中/贴边边界都用逻辑尺寸(162×240),不是物理 324×480
        self.resize(first.deviceIndependentSize().toSize())

        # 状态机
        self.state = "idle"       # idle / walk / cheer / drag / falling
        self.direction = 1        # 走路方向:1 向右,-1 向左
        self.tick_count = 0
        self.next_blink = random.randint(BLINK_MIN, BLINK_MAX)
        self.walk_pose = 0        # 走路循环帧序号(按当前皮肤 walk_poses 长度取模)
        self.cheer_left = 0       # 欢呼剩余帧数
        self.fall_v = 0.0         # 下落竖直速度
        self.walk_anim = 0        # 走路动画计时(到 WALK_ANIM_TICKS 换一帧)
        self.drag_offset = QPoint()

        # 初始位置:屏幕底部中央
        screen = QApplication.primaryScreen().availableGeometry()
        self.floor_y = screen.y() + screen.height() - self.height()
        self.move(screen.x() + (screen.width() - self.width()) // 2, self.floor_y)

        # 主循环定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(TICK_MS)

        # 对话(阶段2):DeepSeek 客户端 + 聊天浮窗;信号接桌宠反应
        self.chat_busy = False
        self.chat_freeze = False   # 聊天窗开着 = 不散步,只许拖拽
        profile = self._character_profile(self.skin.character_id, cfg)
        self.chat = ChatClient(
            api_key=pet_config.get_str(cfg, "deepseek_key"),
            char_name=profile["name"],
            user_title=profile["user_title"],
            model=pet_config.get_str(cfg, "model"),
            character_id=self.skin.character_id,
            extra=profile["extra"],
        )
        self.chat.busy_changed.connect(self._on_chat_busy)
        self.chat.reply_arrived.connect(self._on_chat_reply)
        self.chat.reply_failed.connect(self._on_chat_reply)
        self.chat_window = ChatWindow(self.chat)
        self.chat_window.on_open_settings = self.open_settings
        self.chat_window.hidden.connect(lambda: self._set_chat_freeze(False))
        self.chat_shown_once = False

    # ------------------------------------------------------------------
    # macOS:把窗口钉到系统顶层(NSStatusWindowLevel)
    # ------------------------------------------------------------------
    # Qt 的 WindowStaysOnTopHint 在 macOS 上只是 floating level(1),会被菜单栏、
    # 其他应用浮动面板、全屏窗口盖住。这里在原生层面把 NSWindow 提到
    # NSStatusWindowLevel(25),并让它能跨 Spaces 显示,真正做到"永远在最上层"。
    # 用 PyObjC(已在 venv 里装 pyobjc-framework-Cocoa)。show() 之后调用,因为
    # winId() 需要 native window 已创建。
    def raise_to_status_level(self):
        # Qt offscreen 等测试平台的 winId 不是 NSView 指针,不能交给 PyObjC。
        if sys.platform != "darwin" or QApplication.platformName() != "cocoa":
            return
        try:
            import objc
            from AppKit import (
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
            )
            # winId() 返回 NSView 指针
            ns_view = objc.objc_object(c_void_p=int(self.winId()))
            ns_win = ns_view.window()
            if ns_win is None:
                return
            # macOS otherwise outlines translucent sprite edges with a window shadow.
            ns_win.setHasShadow_(False)
            ns_win.setLevel_(NSStatusWindowLevel)
            beh = ns_win.collectionBehavior()
            ns_win.setCollectionBehavior_(
                beh
                | NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
        except Exception as e:
            print(f"提升窗口层级失败,退回 Qt 默认置顶:{e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # 行为主循环
    # ------------------------------------------------------------------
    def tick(self):
        if self.state == "drag":
            return
        self.tick_count += 1

        if self.state == "falling":
            # 重力下落:v += G,y += v,落地回弹,弹不动就回待机
            self.fall_v += GRAVITY
            y = self.y() + self.fall_v
            if y >= self.floor_y:
                y = self.floor_y
                self.fall_v = -self.fall_v * BOUNCE
                if abs(self.fall_v) < BOUNCE_MIN_V:
                    self.fall_v = 0.0
                    # 落地吸附回 SCALE 网格(拖拽会破坏对齐)
                    self.move(round(self.x() / SCALE) * SCALE, self.floor_y)
                    self.set_state("idle")
                    return
            self.move(self.x(), int(y))
            return

        if self.state == "cheer":
            self.cheer_left -= 1
            if self.cheer_left <= 0:
                self.set_state("idle")
            return

        if self.state == "idle":
            if self.chat_busy:
                return   # 对话思考中:闭眼站定,不眨眼不乱走
            # 眨眼
            if self.tick_count >= self.next_blink:
                self.tick_count = 0
                self.next_blink = random.randint(BLINK_MIN, BLINK_MAX)
                self.set_frame("idle_2")
                QTimer.singleShot(150, lambda: self.set_frame("idle_1"))
            # 随机开始走路(聊天窗开着时不散步只许拖拽,关窗恢复原逻辑)
            elif (not self.chat_freeze) and random.random() < WALK_CHANCE:
                self.direction = random.choice((-1, 1))
                self.set_state("walk")
            return

        if self.state == "walk":
            # 走路帧数/抬升随当前皮肤:2 帧或 4 帧循环
            walk_poses = self.skin.walk_poses
            walk_lift = self.skin.walk_lift
            # 每 WALK_ANIM_TICKS 推进一帧循环(250ms)
            self.walk_anim += 1
            if self.walk_anim >= WALK_ANIM_TICKS:
                self.walk_anim = 0
                self.walk_pose = (self.walk_pose + 1) % len(walk_poses)
                self.set_frame(walk_poses[self.walk_pose])
            # 移动,撞屏幕边缘就掉头;x 始终吸附在 SCALE 网格上
            x = self.x() + self.direction * WALK_SPEED
            screen = QApplication.primaryScreen().availableGeometry()
            if x <= screen.x():
                x, self.direction = screen.x(), 1
            elif x + self.width() >= screen.x() + screen.width():
                x = screen.x() + screen.width() - self.width()
                self.direction = -1
            x -= x % SCALE
            # 起伏与姿势绑定:contact 低位、passing 高位(帧数随当前皮肤)
            self.move(x, self.floor_y - walk_lift[self.walk_pose])
            # 随机停下休息
            if random.random() < STOP_CHANCE:
                self.set_state("idle")

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------
    def set_state(self, state):
        self.state = state
        if state == "idle":
            self.move(self.x(), self.floor_y)   # 走出起伏后落回地面
            self.set_frame("idle_1")
        elif state == "walk":
            # 起步:吸附到 SCALE 网格(否则步长对了相位仍错),立即上 contact 帧(低位)
            self.move(round(self.x() / SCALE) * SCALE, self.floor_y)
            self.walk_anim = 0
            self.walk_pose = 0
            self.set_frame(self.skin.walk_poses[0])
        elif state == "cheer":
            self.move(self.x(), self.floor_y)
            self.cheer_left = CHEER_TICKS
            self.set_frame("cheer")
        elif state == "falling":
            self.fall_v = FALL_V0
            # 下落:有 fall 专用帧就用,否则回退 cheer(高举饭碗);都是正面帧不镜像
            self.set_frame("fall" if "fall" in self.frames else "cheer")

    def set_frame(self, name):
        pm = self.frames[name]
        # 侧面走路帧素材本身朝左:向左走不翻转,向右走水平翻转
        if self.direction > 0 and name.startswith("walk"):
            pm = pm.transformed(QTransform().scale(-1, 1))
            pm.setDevicePixelRatio(self.dpr)   # transformed 会丢 dpr,不重设向右走会糊回去
        self.setPixmap(pm)

        # 动态调整窗口尺寸以适应不同大小的帧(如 fall 帧可能更宽)
        new_size = pm.deviceIndependentSize().toSize()
        if self.size() != new_size:
            old_bottom = self.y() + self.height()  # 记录当前底部位置
            self.resize(new_size)
            # 保持底部位置不变(脚贴地)
            if self.state in ("idle", "walk", "cheer"):
                self.move(self.x(), self.floor_y)
            else:
                # falling/drag 状态保持底部位置
                self.move(self.x(), old_bottom - self.height())

    # ------------------------------------------------------------------
    # 鼠标交互
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.state == "falling":
                return  # 下落期间不响应点击,避免半空中触发欢呼
            self.state = "drag"
            self.drag_offset = event.globalPosition().toPoint() - self.pos()
            self.press_global = event.globalPosition().toPoint()
        elif event.button() == Qt.MouseButton.RightButton:
            self._popup_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.state == "drag":
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.state == "drag":
            # 用按下时的位置判断是"单击"还是"拖拽"(拖动中 pos 会跟着鼠标走,
            # 不能直接拿当前 pos 比较)
            moved = (event.globalPosition().toPoint() - self.press_global).manhattanLength()
            if moved < 5:
                self.set_state("cheer")       # 几乎没动 = 单击,欢呼一下
            else:
                self.set_state("falling")     # 拖走了 = 松手重力下落

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_chat_window()   # 双击 = 开/关聊天(伴随的那声欢呼就当是她开心)

    # ------------------------------------------------------------------
    # 对话(阶段2):浮窗开关 + 桌宠反应
    # ------------------------------------------------------------------
    def toggle_chat_window(self):
        cw = self.chat_window
        if cw.isVisible():
            cw.hide()
            return
        if not self.chat_shown_once:
            self.chat_shown_once = True
            self._position_chat_window()
        cw.show()
        cw.raise_()
        cw.activateWindow()
        self._set_chat_freeze(True)

    def _set_chat_freeze(self, on):
        """聊天期间桌宠不动:开着窗就原地站定(保留眨眼),关窗恢复散步。"""
        self.chat_freeze = on
        if on and self.state in ("walk", "cheer"):
            self.set_state("idle")

    def open_settings(self):
        default_name = self._character_defaults[self.skin.character_id]["name"]
        SettingsDialog(self.chat, default_name, parent=self.chat_window).exec()

    def _position_chat_window(self):
        """聊天气泡放在角色头部旁边,完全不重叠:优先右侧 → 放不下换左侧 →
        两侧都放不下(窄屏/角色居中)就悬在角色正上方,尾巴居中指向头顶。"""
        cw = self.chat_window
        screen = self._screen_geom()
        gap = 10
        x = self.x() + self.width() + gap           # 右侧:与角色间隔 10px
        side = "left"
        if x + cw.width() > screen.right() - 4:
            x = self.x() - gap - cw.width()          # 左侧
            side = "right"
        y = max(screen.y() + 4, self.y() + 46 - cw.height())
        if x < screen.x() + 4:
            # 兜底:角色正上方,气泡底边悬在头顶 6px 处,尾巴垂直指向她
            x = self.x() + (self.width() - cw.width()) // 2
            x = max(screen.x() + 4, min(x, screen.right() + 1 - cw.width()))
            side = "center"
            y = max(screen.y() + 4, self.y() - 6 - cw.height())
        cw.set_tail_side(side)
        cw.move(x, y)

    def _on_chat_busy(self, busy):
        """请求开始:闭眼站定=在想;结束:睁眼。拖拽/下落中不抢状态。"""
        self.chat_busy = busy
        if busy:
            if self.state not in ("drag", "falling"):
                self.set_state("idle")
                self.set_frame("idle_2")
        elif self.state == "idle":
            self.set_frame("idle_1")

    def _on_chat_reply(self, _text):
        """回复/失败文案到达:原地欢呼一下(内容进聊天气泡的记录区)。"""
        if self.state not in ("drag", "falling"):
            self.set_state("cheer")

    def _screen_geom(self):
        return QApplication.primaryScreen().availableGeometry()

    # ------------------------------------------------------------------
    # 皮肤:发现 / 加载 / 菜单 / 切换
    # ------------------------------------------------------------------
    def _collect_character_defaults(self):
        """同一角色只收一份基础人设,不随服装反复覆盖。"""
        default_skin = self.skins[0]
        if default_skin.character_id != DEFAULT_CHARACTER_ID:
            sys.exit("内置皮肤的 character_id 与默认角色配置不一致")
        default_persona = default_skin.persona or {}
        profiles = {DEFAULT_CHARACTER_ID: {
            "name": default_persona.get("name") or DEFAULT_SKIN_NAME,
            "user_title": default_persona.get("user_title") or "主人",
            "extra": default_persona.get("extra") or "",
        }}
        for sk in self.skins:
            if sk.character_id not in profiles:
                persona = sk.persona or {}
                profiles[sk.character_id] = {
                    "name": persona.get("name") or sk.name,
                    "user_title": persona.get("user_title") or "主人",
                    "extra": persona.get("extra") or "",
                }
        return profiles

    def _character_profile(self, character_id, cfg=None):
        defaults = self._character_defaults[character_id]
        fields = pet_config.character_settings(
            cfg if cfg is not None else pet_config.load(), character_id,
            defaults["name"], defaults["user_title"])
        return {**fields, "extra": defaults["extra"]}

    def _discover_skins(self):
        """内置默认皮肤(sprites/)+ skins/ 与用户皮肤目录下的皮肤。
        条目两种形态:子目录 = 明文皮肤;.petpack = 皮肤包。
        重名先到先得(内置 → 目录 → 包),后来跳过。"""
        default_skin = self._load_skin(DEFAULT_SKIN_NAME, SPRITE_DIR)
        if default_skin.persona and default_skin.persona.get("name"):
            default_skin.name = default_skin.persona["name"]
        skins = [default_skin]
        seen = {default_skin.name}

        for base in (SKINS_DIR, pet_config.USER_SKINS_DIR):
            if not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                path = os.path.join(base, name)
                if name.endswith(".petpack") and os.path.isfile(path):
                    sk = self._load_pack(path)
                    if sk is not None and name not in seen and sk.name not in seen:
                        seen.add(name)
                        seen.add(sk.name)
                        skins.append(sk)
                elif os.path.isdir(path) and name not in seen:
                    sk = self._load_skin(name, path, required=False)
                    if sk is not None:
                        seen.add(name)
                        skins.append(sk)
        return skins

    def _load_pack(self, path):
        """读 .petpack 皮肤;坏包/缺帧打一行警告跳过(返回 None),绝不崩。"""
        base = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                pack = petpack.read_pack(f.read())
        except (petpack.PackError, OSError) as e:
            print(f"皮肤包「{base}」跳过:{e}", file=sys.stderr)
            return None
        poses, lift, missing_walk = self._walk_poses_for(
            lambda fn: fn in pack["frames"])
        missing = next((fn for fn in REQUIRED_FRAMES if fn not in pack["frames"]),
                       missing_walk)
        if missing:
            print(f"皮肤包「{base}」跳过:缺帧 {missing}", file=sys.stderr)
            return None
        frames = {}
        if pack["hd"]:
            # 高清目录皮肤会先做帧间内容对齐;包内 PNG 必须走同一流程。
            from io import BytesIO
            import numpy as np
            from PIL import Image as PILImage
            raws = {}
            for fname, png in pack["frames"].items():
                try:
                    raws[fname] = np.array(PILImage.open(BytesIO(png)).convert("RGBA"))
                except (OSError, ValueError):
                    print(f"皮肤包「{base}」跳过:帧 {fname} 解码失败", file=sys.stderr)
                    return None
            for fname, arr in self._align_frames(raws).items():
                frames[fname] = self._scale_frame(self._qpix_from(arr), True)
        else:
            for fname, png in pack["frames"].items():
                pm = QPixmap()
                if not pm.loadFromData(png):
                    print(f"皮肤包「{base}」跳过:帧 {fname} 解码失败", file=sys.stderr)
                    return None
                frames[fname] = self._scale_frame(pm, False)
        return Skin(pack["name"], frames, poses, lift,
                    persona=pack.get("persona"),
                    character_id=pack["character_id"])

    def _index_of(self, name):
        """按显示名找皮肤下标;名字不存在(被删/改名/没配置)回 0(内置默认)。"""
        if isinstance(name, str):
            for i, sk in enumerate(self.skins):
                if sk.name == name:
                    return i
        return 0

    def _frame_file(self, directory, fn):
        """帧名 → 目录里实际存在的文件路径(走路帧兼容老命名 walk_cycle_v2_1..4)。"""
        for cand in FRAME_FILES.get(fn, (fn,)):
            p = os.path.join(directory, cand + ".png")
            if os.path.isfile(p):
                return p
        return os.path.join(directory, fn + ".png")   # 都不存在,返回新名用于报缺帧

    @staticmethod
    def _walk_poses_for(has):
        """走路帧探测通用逻辑。has(帧名) → bool。
        4 帧全齐 → 4 帧循环;只齐前 2 帧 → 2 帧循环;都不齐 → missing=第一个缺帧名。"""
        names = tuple(f"walk_{i}" for i in range(1, 5))
        files = [has(n) for n in names]
        if all(files):
            return (names, (0, SCALE, 0, SCALE), None)
        if files[0] and files[1]:
            return (WALK_POSES, WALK_LIFT, None)
        missing = next(n for n, ok in zip(names, files) if not ok)
        return ((), (), missing)

    def _probe_walk_frames(self, directory):
        """目录版走路帧探测,兼容旧版 walk_cycle_v2_N 命名。"""
        def has(fn):
            return any(os.path.isfile(os.path.join(directory, cand + ".png"))
                       for cand in FRAME_FILES.get(fn, (fn,)))
        return self._walk_poses_for(has)

    @staticmethod
    def _directory_identity(directory):
        """目录版可选 persona.json;无元数据的旧目录皮肤归当前默认角色。"""
        path = os.path.join(directory, "persona.json")
        if not os.path.isfile(path):
            return DEFAULT_CHARACTER_ID, None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("persona.json 必须是对象")
        character_id = data.get("character_id", DEFAULT_CHARACTER_ID)
        if not petpack.valid_character_id(character_id):
            raise ValueError("character_id 不合法")
        if any(not isinstance(data.get(key, ""), str)
               for key in ("name", "user_title", "extra")):
            raise ValueError("角色设定字段必须是字符串")
        persona = {key: data.get(key, "") for key in ("name", "user_title", "extra")}
        return character_id, persona

    def _load_skin(self, name, directory, required=True):
        """从 directory 加载一整套帧。
        required=True 时缺帧直接退出(内置默认必须有);否则缺帧返回 None 并提示。
        走路帧数按目录里实际素材探测(见 _probe_walk_frames),探测结果存进 Skin。
        目录里有 `hd` 标记文件 → 高清皮肤(平滑缩放到 HD_DISPLAY_H 等高、保持比例,
        且自动做帧间内容对齐,消除眨眼/走路时因各帧独立裁剪造成的抖动);
        否则 → 像素皮肤(最近邻 ×SCALE,保硬边;素材生成时已对齐,不再处理)。"""
        try:
            character_id, persona = self._directory_identity(directory)
        except (OSError, ValueError) as e:
            if required:
                sys.exit(f"内置皮肤角色资料无效:{e}")
            print(f"皮肤「{name}」角色资料无效,跳过:{e}", file=sys.stderr)
            return None
        smooth = os.path.exists(os.path.join(directory, "hd"))
        walk_poses, walk_lift, missing_walk = self._probe_walk_frames(directory)
        required_frames = ("idle_1", "idle_2", "cheer") + walk_poses
        # 走路前 2 帧不齐 = 缺帧:把第一个缺失的走路帧名也加进必须存在的清单
        check_frames = required_frames + ((missing_walk,) if missing_walk else ())
        frames = {}
        if smooth:
            # 高清:先收齐原始帧(含可选 fall),统一内容对齐后再缩放
            import numpy as np
            from PIL import Image as PILImage
            raws = {}
            for fn in check_frames + ("fall",):
                p = self._frame_file(directory, fn)
                if os.path.isfile(p):
                    raws[fn] = np.array(PILImage.open(p).convert("RGBA"))
            missing = [fn for fn in check_frames if fn not in raws]
            if missing:
                if required:
                    sys.exit(f"找不到内置皮肤素材 {os.path.join(directory, missing[0])}.png")
                print(f"皮肤「{name}」缺帧 {missing[0]}.png,跳过该皮肤。",
                      file=sys.stderr)
                return None
            for fn, arr in self._align_frames(raws).items():
                frames[fn] = self._scale_frame(self._qpix_from(arr), smooth)
            return Skin(name, frames, walk_poses, walk_lift,
                        persona=persona, character_id=character_id)
        for fn in check_frames:
            pm = QPixmap(self._frame_file(directory, fn))
            if pm.isNull():
                if required:
                    sys.exit(f"找不到内置皮肤素材 {os.path.join(directory, fn)}.png")
                print(f"皮肤「{name}」缺帧 {fn}.png,跳过该皮肤。",
                      file=sys.stderr)
                return None
            frames[fn] = self._scale_frame(pm, smooth)
        # 可选:下落专用帧 fall.png(没有就回退 cheer)
        fall_pm = QPixmap(os.path.join(directory, "fall.png"))
        if not fall_pm.isNull():
            frames["fall"] = self._scale_frame(fall_pm, smooth)
        return Skin(name, frames, walk_poses, walk_lift,
                    persona=persona, character_id=character_id)

    @staticmethod
    def _qpix_from(arr):
        """RGBA numpy 数组 → QPixmap。"""
        from PySide6.QtGui import QImage
        h, w = arr.shape[:2]
        img = QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        return QPixmap.fromImage(img)

    @staticmethod
    def _align_frames(raws):
        """帧间内容对齐(移植 make_sprites.py 的素材工程思想):
        每帧取「上半身(顶部 60%)alpha 质心的 x」+「脚底(最低非透明行)的 y」,
        平移到统一画布(质心 x=画布中心、脚底贴画布底)。
        各帧独立裁剪、宽度不同也不抖:眨眼只是眼睛变,人物纹丝不动。"""
        import numpy as np
        metas = {}
        for fname, arr in raws.items():
            a = arr[..., 3]
            rows = np.where(a.max(axis=1) > 8)[0]
            if not len(rows):
                metas[fname] = None
                continue
            top, bottom = int(rows[0]), int(rows[-1])
            upper = a[top: top + max(1, int((bottom - top) * 0.6))]
            col = upper.sum(axis=0).astype(float)
            tot = col.sum()
            cx = (float((np.arange(arr.shape[1]) * col).sum() / tot)
                  if tot > 0 else arr.shape[1] / 2)
            metas[fname] = (cx, bottom)
        W = max(arr.shape[1] for arr in raws.values())
        H = max(arr.shape[0] for arr in raws.values())
        out = {}
        for fname, arr in raws.items():
            canvas = np.zeros((H, W, 4), dtype=np.uint8)
            m = metas[fname]
            if m is None:
                out[fname] = canvas
                continue
            cx, bottom = m
            dx = int(round(W / 2 - cx))
            dy = int(round(H - 1 - bottom))
            x0, y0 = max(0, dx), max(0, dy)
            x1 = min(W, dx + arr.shape[1])
            y1 = min(H, dy + arr.shape[0])
            if x1 > x0 and y1 > y0:
                canvas[y0:y1, x0:x1] = arr[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
            out[fname] = canvas
        return out

    def _scale_frame(self, pm, smooth):
        """单帧放大并声明 dpr。smooth=True 高清(平滑、按高度等比缩放到 HD_DISPLAY_H);
        否则像素(最近邻 ×SCALE、硬边)。"""
        if smooth:
            k = HD_DISPLAY_H * self.dpr / pm.height()   # 按高度等比缩放到高清目标高度
            big = pm.scaled(
                max(1, round(pm.width() * k)),
                max(1, round(pm.height() * k)),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            big = pm.scaled(
                round(pm.width() * SCALE * self.dpr),
                round(pm.height() * SCALE * self.dpr),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        big.setDevicePixelRatio(self.dpr)
        return big

    def _build_menu(self):
        """构建右键菜单:全部皮肤收进「皮肤」子菜单(当前打勾,悬停展开),
        主菜单保留导入入口;皮肤再多菜单也不会变长。"""
        menu = QMenu(self)
        # 🔴 必须用「带父构造 + addMenu(QMenu*)」:裸 addMenu("皮肤") 返回的
        # 子菜单由 Python 持有所有权,_build_menu 一返回就被 GC 删掉,菜单会变空
        skin_menu = QMenu("皮肤", menu)
        menu.addMenu(skin_menu)
        for i, sk in enumerate(self.skins):
            act = QAction(sk.name, skin_menu)
            act.setCheckable(True)
            act.setChecked(i == self.skin_index)
            act.setEnabled(not self.chat.busy or sk.character_id == self.chat.character_id)
            act.triggered.connect(lambda _checked=False, idx=i: self.apply_skin(idx))
            skin_menu.addAction(act)
        import_action = QAction("导入皮肤包…", menu)
        import_action.setEnabled(not self.chat.busy)
        import_action.triggered.connect(self.import_skin_pack)
        menu.addAction(import_action)
        chat_action = QAction("聊天", self)
        chat_action.triggered.connect(self.toggle_chat_window)
        menu.addAction(chat_action)
        settings_action = QAction("设置…", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        return menu

    def _popup_menu(self, pos):
        self._build_menu().exec(pos)

    def import_skin_pack(self):
        """选择 .petpack，验证后安装到用户目录并立即切换。"""
        if self.chat.busy:
            return
        start_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(start_dir):
            start_dir = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "导入皮肤包", start_dir, "DeskPet 皮肤包 (*.petpack)")
        if not path:
            return
        if not path.lower().endswith(".petpack"):
            QMessageBox.warning(self, "导入失败", "请选择 .petpack 皮肤包文件。")
            return
        skin = self._load_pack(path)
        if skin is None:
            QMessageBox.warning(self, "导入失败", "皮肤包无效或缺少必需图片，请检查文件。")
            return
        existing_names = {item.name for item in self._discover_skins()}
        if skin.name in existing_names:
            QMessageBox.warning(self, "导入失败", f"已有名为「{skin.name}」的皮肤，请先给新包改名。")
            return
        try:
            pet_config.ensure_dirs()
            source_name = os.path.basename(path)
            stem = source_name[:-len(".petpack")]
            install_name = stem + ".petpack"
            fd, temp_path = tempfile.mkstemp(
                prefix=".import-", suffix=".tmp", dir=pet_config.USER_SKINS_DIR)
            try:
                with os.fdopen(fd, "wb") as target, open(path, "rb") as source:
                    shutil.copyfileobj(source, target)
                for number in range(1, 1001):
                    filename = install_name if number == 1 else f"{stem}-{number}.petpack"
                    installed_path = os.path.join(pet_config.USER_SKINS_DIR, filename)
                    try:
                        os.link(temp_path, installed_path)
                        break
                    except FileExistsError:
                        continue
                else:
                    raise OSError("可用文件名已用完")
            finally:
                os.unlink(temp_path)
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", f"无法保存皮肤包：{exc}")
            return
        self.skins.append(skin)
        self._character_defaults = self._collect_character_defaults()
        self.apply_skin(len(self.skins) - 1)
        QMessageBox.information(
            self, "导入成功", f"已安装并切换到「{skin.name}」。以后可从“皮肤”菜单选择。")

    def apply_skin(self, index):
        """同角色只换外观;换角色才换人设与聊天记录。"""
        if not (0 <= index < len(self.skins)) or index == self.skin_index:
            return
        next_skin = self.skins[index]
        if self.chat.busy and next_skin.character_id != self.chat.character_id:
            return  # 等当前回复结束,避免旧角色请求落到新角色气泡
        self.skin_index = index
        self.skin = next_skin
        self.frames = next_skin.frames
        self.walk_pose = 0   # 归零,保证 walk_poses/walk_lift 不越界
        pet_config.update(last_skin=self.skin.name)   # 记住本次选择,下次启动恢复
        if self.skin.character_id != self.chat.character_id:
            profile = self._character_profile(self.skin.character_id)
            self.chat.set_persona(profile["name"], profile["user_title"],
                                  profile["extra"], self.skin.character_id)
        # 尺寸不同的真图:resize + 重算地面,保持水平中心
        first = self.frames["idle_1"]
        new_size = first.deviceIndependentSize().toSize()
        if new_size != self.size():
            cx = self.x() + self.width() // 2
            self.resize(new_size)
            screen = QApplication.primaryScreen().availableGeometry()
            self.floor_y = screen.y() + screen.height() - self.height()
            self.move(cx - self.width() // 2, self.y())
        # 用新皮肤重绘当前帧(走路帧会按 direction 翻转)
        if self.state != "drag":
            self.set_frame(self._current_frame_name())

    def _current_frame_name(self):
        if self.state == "walk":
            return self.skin.walk_poses[self.walk_pose]
        if self.state == "cheer":
            return "cheer"
        if self.state == "falling":
            return "fall" if "fall" in self.frames else "cheer"
        return "idle_1"


def main():
    pet_config.ensure_dirs()   # 首次运行建好配置目录和用户皮肤目录
    app = QApplication(sys.argv)
    pet = DeskPetWidget()
    pet.show()
    pet.raise_to_status_level()   # macOS:提到系统顶层,真正永远置顶
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
