from __future__ import annotations

import re
import shlex
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop.theme import apply_dwm_titlebar_theme, resolve_is_dark


def parse_args_text(text: str) -> list[str]:
    stripped = (text or "").strip()
    if not stripped:
        return []
    if "\n" in stripped:
        return [line.strip() for line in stripped.splitlines() if line.strip()]
    try:
        return shlex.split(stripped, posix=False)
    except ValueError:
        return stripped.split()


class PluginEditorDialog(QDialog):
    """Clean dialog for adding or editing a managed external plugin."""

    def __init__(
        self,
        parent: QWidget | None = None,
        plugin: dict[str, Any] | None = None,
        theme_mode: str = "auto",
    ) -> None:
        super().__init__(parent)
        self._theme_mode = theme_mode
        self.mode = "edit" if plugin else "create"
        self.setWindowTitle(
            f"配置 · {plugin.get('name') or plugin.get('id')}" if plugin else "导入外部插件"
        )
        self.setMinimumWidth(520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(11)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.id_edit = QLineEdit(plugin.get("id", "") if plugin else "")
        self.id_edit.setPlaceholderText("my-plugin")
        if self.mode == "edit":
            self.id_edit.setReadOnly(True)

        self.name_edit = QLineEdit(plugin.get("name", "") if plugin else "")
        self.name_edit.setPlaceholderText("插件名称")

        self.version_edit = QLineEdit(plugin.get("version", "") if plugin else "")
        self.version_edit.setPlaceholderText("可选，如 1.0.1（有 package.json 或健康接口时自动识别）")

        self.desc_edit = QLineEdit(plugin.get("description", "") if plugin else "")
        self.desc_edit.setPlaceholderText("一句话功能描述")

        self.type_combo = QComboBox()
        self.type_combo.addItems(["custom-cdp", "node-cdp", "exe-cdp"])
        if plugin and plugin.get("type"):
            idx = self.type_combo.findText(str(plugin["type"]))
            if idx >= 0:
                self.type_combo.setCurrentIndex(idx)

        self.cmd_edit = QLineEdit(plugin.get("command", "") if plugin else "")
        self.cmd_edit.setPlaceholderText(r"node 或 plugins\demo\index.exe")

        self.launch_args_edit = QPlainTextEdit("\n".join(plugin.get("launchArgs") or []) if plugin else "")
        self.launch_args_edit.setPlaceholderText("支持 {CDP_PORT} / {BASE_DIR}")
        self.launch_args_edit.setFixedHeight(62)

        self.attach_args_edit = QPlainTextEdit("\n".join(plugin.get("attachArgs") or []) if plugin else "")
        self.attach_args_edit.setPlaceholderText("留空则复用启动参数")
        self.attach_args_edit.setFixedHeight(62)

        self.health_edit = QLineEdit(plugin.get("healthUrl", "") if plugin else "")
        self.health_edit.setPlaceholderText("可选，http://127.0.0.1:PORT/health")

        self.match_edit = QLineEdit(plugin.get("processMatch", "") if plugin else "")
        self.match_edit.setPlaceholderText("可选，命令行进程匹配关键字")

        form.addRow("插件 ID *", self.id_edit)
        form.addRow("显示名称 *", self.name_edit)
        form.addRow("版本号", self.version_edit)
        form.addRow("简介", self.desc_edit)
        form.addRow("运行类型", self.type_combo)
        form.addRow("启动命令 *", self.cmd_edit)
        form.addRow("启动参数", self.launch_args_edit)
        form.addRow("附着参数", self.attach_args_edit)
        form.addRow("健康地址", self.health_edit)
        form.addRow("进程标识", self.match_edit)
        root.addLayout(form)

        toggles = QHBoxLayout()
        toggles.setSpacing(20)
        self.enabled_check = QCheckBox("启用插件")
        self.enabled_check.setChecked(True if not plugin else plugin.get("enabled", True) is not False)
        self.auto_attach_check = QCheckBox("随主程序自动附着")
        self.auto_attach_check.setChecked(True if not plugin else plugin.get("autoAttach", True) is not False)
        toggles.addWidget(self.enabled_check)
        toggles.addWidget(self.auto_attach_check)
        toggles.addStretch(1)
        root.addLayout(toggles)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        root.addLayout(buttons)

        if self.mode == "create":
            self.id_edit.setFocus()
        else:
            self.name_edit.setFocus()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        apply_dwm_titlebar_theme(self, resolve_is_dark(self._theme_mode))

    def _on_save(self) -> None:
        plugin_id = self.id_edit.text().strip()
        if not re.match(r"^[a-z0-9][a-z0-9-_]{1,63}$", plugin_id, re.IGNORECASE):
            QMessageBox.warning(self, "格式有误", "插件 ID 仅支持字母、数字、连字符和下划线（2–64 位）。")
            return
        if not self.cmd_edit.text().strip():
            QMessageBox.warning(self, "缺少命令", "启动命令不能为空。")
            return
        self.accept()

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id_edit.text().strip(),
            "name": self.name_edit.text().strip() or self.id_edit.text().strip(),
            "version": self.version_edit.text().strip(),
            "description": self.desc_edit.text().strip(),
            "type": self.type_combo.currentText(),
            "command": self.cmd_edit.text().strip(),
            "launchArgs": parse_args_text(self.launch_args_edit.toPlainText()),
            "attachArgs": parse_args_text(self.attach_args_edit.toPlainText()),
            "healthUrl": self.health_edit.text().strip(),
            "processMatch": self.match_edit.text().strip(),
            "enabled": self.enabled_check.isChecked(),
            "autoAttach": self.auto_attach_check.isChecked(),
        }
