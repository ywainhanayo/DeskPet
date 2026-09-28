"""settings_dialog.py —— 设置对话框(阶段2)。

用户可见三项:DeepSeek API key(密文)、角色名、称呼用户。
保存时若角色名相对上次(persona_of)有变化且填了 key,自动触发「角色设定检索」:
级联 ①deepseek-flash 内置知识 → ②萌娘百科 API 资料让模型提炼;
两级都查不到就不写设定(soul 通用模板兜底,无手填兜底;用户随时可手改 soul.md)。
生成结果先弹预览,确认才写进 personas/<角色ID>.md;共用 soul.md 不动。
「重新生成设定」按钮对当前名字手动触发同一流程。
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import pet_config


class PreviewDialog(QDialog):
    """生成的角色设定预览:确认写入 / 跳过。"""

    def __init__(self, name, character_id, text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("角色设定预览")
        self.resize(400, 320)
        tip = QLabel(f"确认后会保存「{name}」的角色设定，不影响其他角色。")
        tip.setWordWrap(True)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存角色设定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("跳过")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tip)
        lay.addWidget(box)
        lay.addWidget(buttons)


class SettingsDialog(QDialog):
    def __init__(self, client, default_char_name, parent=None):
        super().__init__(parent)
        self.client = client
        self.character_id = client.character_id
        self._default_name = default_char_name
        self.setWindowTitle("桌宠设置")
        self.setMinimumWidth(400)

        self.key_edit = QLineEdit(client.api_key)
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("输入自己的 API key")
        show_box = QCheckBox("显示")
        show_box.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))

        self.name_edit = QLineEdit(client.char_name)
        self.name_edit.setPlaceholderText(default_char_name)
        regen_btn = QPushButton("重新生成设定")
        regen_btn.clicked.connect(self._regen)
        name_row = QHBoxLayout()
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(regen_btn)

        self.title_edit = QLineEdit(client.user_title)
        self.title_edit.setPlaceholderText("主人")

        form = QFormLayout()
        form.addRow("DeepSeek API key:", self.key_edit)
        form.addRow("", show_box)
        form.addRow("角色叫什么:", name_row)
        form.addRow("称呼用户什么:", self.title_edit)

        self.gen_status = QLabel("")
        self.gen_status.setWordWrap(True)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.gen_status)
        layout.addWidget(self.buttons)

    # ---- 保存与生成 ----------------------------------------------------------
    def _persist_fields(self):
        """三个字段落盘并热更新客户端;返回 (name, key)。"""
        key = self.key_edit.text().strip()
        name = self.name_edit.text().strip() or self._default_name
        title = self.title_edit.text().strip() or "主人"
        pet_config.update_character(
            self.character_id, global_updates={"deepseek_key": key},
            name=name, user_title=title)
        self.client.set_api_key(key)
        self.client.set_persona(name, title)
        return name, key

    def _save(self):
        name, key = self._persist_fields()
        persona_of = pet_config.character_settings(
            pet_config.load(), self.character_id, self._default_name)["persona_of"]
        if key and name != persona_of:
            # 新角色:保存后自动检索设定,完成(或跳过)后自动关闭
            self._start_generate(name, close_on_done=True)
        else:
            self.accept()

    def _regen(self):
        self._persist_fields()
        self._start_generate(self.name_edit.text().strip() or self._default_name,
                             close_on_done=False)

    def _start_generate(self, name, close_on_done):
        if not self.client.api_key:
            self.gen_status.setText("先填 DeepSeek API key 才能检索角色设定。")
            return
        self.gen_status.setText(f"正在联网获取「{name}」的角色资料…")
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)
        self.client.generate_persona_brief(
            name,
            lambda ok, text, source: self._on_brief(ok, text, source, name, close_on_done))

    def _on_brief(self, ok, text, _source, name, close_on_done):
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(True)
        if not ok:
            self.gen_status.setText("没查到这个角色的资料,本次未写入设定"
                                    "(不影响聊天;可改名重试或编辑对应角色文件)。")
            return
        dlg = PreviewDialog(name, self.character_id, text, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pet_config.upsert_persona_section(self.character_id, name, text)
            pet_config.update_character(self.character_id, persona_of=name)
            self.gen_status.setText("角色设定已保存。")
            if close_on_done:
                self.accept()
        else:
            pet_config.update_character(self.character_id, persona_of=name)
            self.gen_status.setText("已跳过角色设定。")
            if close_on_done:
                self.accept()
