from __future__ import annotations

import os
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetricsF,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from desktop.core import APP_VERSION, AgyProcessManager, build_update_urls, validate_update_site_url
from desktop.dialogs import PluginEditorDialog, StorageDeleteConfirmDialog
from desktop.icons import native_graphic_svg, plugin_graphic_svg, render_svg_pixmap
from desktop.storage import (
    StorageNode,
    StorageScanSnapshot,
    build_storage_tree,
    format_idle_age,
    format_mtime,
    format_storage_bytes,
    idle_age_days,
)
from desktop.theme import apply_dwm_titlebar_theme, build_stylesheet, get_palette, resolve_is_dark
from desktop.treemap_widget import SpaceTreemapWidget

THEME_MODES = ("auto", "light", "dark")
THEME_LABELS = {"auto": "外观：自动", "light": "外观：浅色", "dark": "外观：深色"}
SUPPORTED_PACKAGE_EXTS = (".zip", ".agypkg", ".agy-plugin")
DROP_HINT_IDLE_TEXT = "拖入插件安装包 (.zip / .agypkg) 自动安装"
DROP_HINT_ACTIVE_TEXT = "松开鼠标立即安装插件包 (.zip / .agypkg)"

PAGE_STATUS = 0
PAGE_EXTERNAL = 1
PAGE_MARKET = 2
PAGE_NATIVE = 3
PAGE_STORAGE = 4
PAGE_LOGS = 5
PAGE_SETTINGS = 6
PAGE_EXT_DETAIL = 7
PAGE_NAT_DETAIL = 8


def _extract_plugin_package_paths(mime_data: QMimeData | None) -> list[str]:
    """Extracts valid local plugin package paths (.zip / .agypkg / .agy-plugin) from Qt drag data."""
    if mime_data is None or not mime_data.hasUrls():
        return []
    paths: list[str] = []
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        local_path = url.toLocalFile()
        if local_path.lower().endswith(SUPPORTED_PACKAGE_EXTS) and Path(local_path).is_file():
            paths.append(local_path)
    return paths


class PluginDropContainer(QFrame):
    """Drop-enabled container around the plugin catalog card with light/dark drag highlight state."""

    packageDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PluginDropContainer")
        self.setAcceptDrops(True)
        self.setProperty("dragActive", False)
        self._drag_active = False
        self._hint_banner: QFrame | None = None
        self._hint_label: QLabel | None = None

    def bind_hint_widgets(self, banner: QFrame, label: QLabel) -> None:
        self._hint_banner = banner
        self._hint_label = label

    def set_drag_active(self, active: bool) -> None:
        if self._drag_active == active:
            return
        self._drag_active = active
        targets: list[QWidget] = [self]
        if self._hint_banner is not None:
            targets.append(self._hint_banner)
        if self._hint_label is not None:
            self._hint_label.setText(DROP_HINT_ACTIVE_TEXT if active else DROP_HINT_IDLE_TEXT)
            targets.append(self._hint_label)
        for widget in targets:
            widget.setProperty("dragActive", active)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _extract_plugin_package_paths(event.mimeData()):
            event.acceptProposedAction()
            self.set_drag_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _extract_plugin_package_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_drag_active(False)
        paths = _extract_plugin_package_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        for pkg_path in paths:
            self.packageDropped.emit(pkg_path)


class _ElidedTitleLabel(QLabel):
    """Single-line CardTitle label that hugs short titles and elides smoothly on narrow widths."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setObjectName("CardTitle")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        base = super().sizeHint()
        w = self.fontMetrics().horizontalAdvance(self._full_text) + 2
        return QSize(max(base.width(), w), base.height())

    def minimumSizeHint(self) -> QSize:
        sh = self.sizeHint()
        return QSize(min(60, sh.width()), sh.height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if elided != self.text():
            super().setText(elided)


class ClickableRow(QFrame):
    """Row container that emits clicked()/doubleClicked() cleanly while ignoring clicks on interactive children."""

    clicked = Signal()
    doubleClicked = Signal()

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, (QPushButton, ToggleSwitch, QCheckBox)):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, (QPushButton, ToggleSwitch, QCheckBox)):
                self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class ToggleSwitch(QAbstractButton):
    """Smooth custom-painted pill toggle switch."""

    def __init__(self, checked: bool = False, is_dark: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 20)
        self._is_dark = is_dark

    def set_dark_mode(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(38, 20)

    def paintEvent(self, _event) -> None:
        pal = get_palette(self._is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        track_color = QColor(pal["accent"] if self.isChecked() else pal["switch_off"])
        painter.setBrush(track_color)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)

        thumb_x = float(self.width() - 17.5) if self.isChecked() else 2.5
        painter.setBrush(QColor(0, 0, 0, 26))
        painter.drawEllipse(QRectF(thumb_x, 3.2, 15.0, 15.0))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(thumb_x, 2.5, 15.0, 15.0))


class HeroStatusIcon(QWidget):
    """Rounded status badge emblem for the connection hero banner."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._tone = "muted"
        self._is_dark = False

    def set_state(self, tone: str, is_dark: bool) -> None:
        self._tone = tone
        self._is_dark = is_dark
        self.update()

    def paintEvent(self, _event) -> None:
        pal = get_palette(self._is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._tone == "ok":
            bg = QColor(pal["ok_bg"])
            fg = QColor(pal["ok"])
        elif self._tone == "warn":
            bg = QColor(pal["warn_bg"])
            fg = QColor(pal["warn"])
        else:
            bg = QColor(pal["subtle"])
            fg = QColor(pal["faint"])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(0, 0, 48, 48), 14, 14)

        pen = QPen(fg, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._tone == "ok":
            path = QPainterPath()
            path.moveTo(15.5, 24.5)
            path.lineTo(21.5, 30.5)
            path.lineTo(32.5, 18.5)
            painter.drawPath(path)
        elif self._tone == "warn":
            painter.drawEllipse(QRectF(17, 17, 14, 14))
            painter.setBrush(fg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(21.5, 21.5, 5, 5))
        else:
            painter.drawEllipse(QRectF(17, 17, 14, 14))


class TopologyDiagramWidget(QWidget):
    """Vector-painted architecture bridge diagram between Antigravity, External Sandbox, and Native Extensions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(186)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._is_dark = False
        self._cdp_ready = False
        self._port = 0
        self._main_cnt = 0
        self._ext_running = 0
        self._ext_total = 0
        self._nat_enabled = 0
        self._nat_total = 0

    def update_state(
        self,
        *,
        is_dark: bool,
        cdp_ready: bool,
        port: int,
        main_cnt: int,
        ext_running: int,
        ext_total: int,
        nat_enabled: int,
        nat_total: int,
    ) -> None:
        self._is_dark = is_dark
        self._cdp_ready = cdp_ready
        self._port = port
        self._main_cnt = main_cnt
        self._ext_running = ext_running
        self._ext_total = ext_total
        self._nat_enabled = nat_enabled
        self._nat_total = nat_total
        self.update()

    def paintEvent(self, _event) -> None:
        pal = get_palette(self._is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        w = float(self.width())
        h = float(self.height())
        if w < 120 or h < 90:
            return

        pad_x = max(12.0, min(26.0, w * 0.04))
        host_w = min(172.0, max(130.0, w * 0.31))
        host_h = 76.0
        host_x = pad_x
        host_y = (h - host_h) / 2.0

        node_w = min(228.0, max(168.0, w * 0.43))
        node_h = 60.0
        node_x = w - pad_x - node_w
        gap_y = 18.0
        top_y = (h - (node_h * 2 + gap_y)) / 2.0
        bot_y = top_y + node_h + gap_y

        # Bezier conduits
        src_pt = QPointF(host_x + host_w, host_y + host_h / 2.0)
        dst_top = QPointF(node_x, top_y + node_h / 2.0)
        dst_bot = QPointF(node_x, bot_y + node_h / 2.0)
        mid_x = (src_pt.x() + dst_top.x()) / 2.0

        top_path = QPainterPath(src_pt)
        top_path.cubicTo(QPointF(mid_x, src_pt.y()), QPointF(mid_x, dst_top.y()), dst_top)

        top_line_color = QColor(pal["ok"] if (self._cdp_ready or self._ext_running > 0) else pal["border_strong"])
        painter.setPen(QPen(top_line_color, 2.0, Qt.PenStyle.SolidLine if self._ext_running > 0 else Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(top_path)

        bot_path = QPainterPath(src_pt)
        bot_path.cubicTo(QPointF(mid_x, src_pt.y()), QPointF(mid_x, dst_bot.y()), dst_bot)
        pen_bot = QPen(QColor(pal["border_strong"]), 1.8, Qt.PenStyle.DashLine)
        painter.setPen(pen_bot)
        painter.drawPath(bot_path)

        # Helper to draw rounded node boxes cleanly
        title_font = QFont(self.font())
        title_font.setPointSizeF(9.5)
        title_font.setWeight(QFont.Weight.DemiBold)
        sub_font = QFont(self.font())
        sub_font.setPointSizeF(8.5)

        def draw_node(
            rect: QRectF,
            border_color: str,
            title: str,
            subtitle: str,
            dot_color: str | None = None,
            sub_color: str | None = None,
            centered: bool = False,
        ) -> None:
            painter.setPen(QPen(QColor(border_color), 1.3))
            painter.setBrush(QColor(pal["surface"]))
            painter.drawRoundedRect(rect, 12, 12)

            title_fm = QFontMetricsF(title_font)
            sub_fm = QFontMetricsF(sub_font)
            if centered:
                avail = max(40.0, rect.width() - 16.0)
                painter.setFont(title_font)
                painter.setPen(QColor(pal["text"]))
                painter.drawText(
                    QRectF(rect.x() + 8, rect.y() + 14, avail, 22),
                    Qt.AlignmentFlag.AlignCenter,
                    title_fm.elidedText(title, Qt.TextElideMode.ElideRight, avail),
                )
                painter.setFont(sub_font)
                painter.setPen(QColor(sub_color or pal["muted"]))
                painter.drawText(
                    QRectF(rect.x() + 8, rect.y() + 38, avail, 20),
                    Qt.AlignmentFlag.AlignCenter,
                    sub_fm.elidedText(subtitle, Qt.TextElideMode.ElideRight, avail),
                )
            else:
                text_x = rect.x() + 30 if dot_color else rect.x() + 14
                avail = max(40.0, rect.width() - (text_x - rect.x()) - 10.0)
                if dot_color:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(dot_color))
                    painter.drawEllipse(QRectF(rect.x() + 14, rect.center().y() - 4.0, 8.0, 8.0))
                painter.setFont(title_font)
                painter.setPen(QColor(pal["text"]))
                painter.drawText(
                    QRectF(text_x, rect.y() + 10, avail, 20),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    title_fm.elidedText(title, Qt.TextElideMode.ElideRight, avail),
                )
                painter.setFont(sub_font)
                painter.setPen(QColor(sub_color or pal["muted"]))
                painter.drawText(
                    QRectF(text_x, rect.y() + 31, avail, 18),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    sub_fm.elidedText(subtitle, Qt.TextElideMode.ElideRight, avail),
                )

        host_sub = (
            f"端口 {self._port}" if self._cdp_ready and self._port
            else (f"{self._main_cnt} 个主窗口" if self._main_cnt > 0 else "未运行")
        )
        draw_node(
            QRectF(host_x, host_y, host_w, host_h),
            pal["ok"] if self._cdp_ready else pal["border_strong"],
            "Antigravity",
            host_sub,
            centered=True,
        )

        ext_border = pal["ok"] if self._ext_running > 0 else pal["hairline"]
        ext_dot = pal["ok"] if self._ext_running > 0 else pal["faint"]
        ext_sub_color = pal["ok"] if self._ext_running > 0 else pal["muted"]
        draw_node(
            QRectF(node_x, top_y, node_w, node_h),
            ext_border,
            "外部托管沙盒",
            f"{self._ext_running} / {self._ext_total} 运行中",
            dot_color=ext_dot,
            sub_color=ext_sub_color,
        )

        nat_dot = pal["info"] if self._nat_enabled > 0 else pal["faint"]
        draw_node(
            QRectF(node_x, bot_y, node_w, node_h),
            pal["hairline"],
            "原生扩展清单",
            f"{self._nat_enabled} / {self._nat_total} 已启用",
            dot_color=nat_dot,
            sub_color=pal["muted"],
        )


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class TaskWorker(QRunnable):
    """Runs blocking process/disk tasks off the Qt UI thread."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            res = self.fn()
            try:
                self.signals.finished.emit(res)
            except RuntimeError:
                pass
        except Exception as exc:
            try:
                self.signals.failed.emit(f"{exc}\n{traceback.format_exc(limit=8)}".strip())
            except RuntimeError:
                pass


def format_bytes(size: int | float) -> str:
    return format_storage_bytes(size)


class MainWindow(QMainWindow):
    """V5 Hybrid desktop UI: Top centered capsule navigation + pure-white status home + scalable plugin directory."""

    _storageScanProgress = Signal(dict)

    def __init__(self, manager: AgyProcessManager, icon: QIcon) -> None:
        super().__init__()
        self.manager = manager
        self.app_icon = icon
        self.thread_pool = QThreadPool.globalInstance()

        self._overview: dict[str, Any] | None = None
        self._native_plugins: list[dict[str, Any]] = []
        self._selected_plugin_id: str | None = None
        self._selected_native_dir: str | None = None
        self._plugin_filter = "all"
        self._refreshing = False
        self._tray_hint_shown = False
        self._force_quit = False
        self._log_streaming = True
        self._switches: list[ToggleSwitch] = []
        self._saw_antigravity_main = False
        self._exit_zero_streak = 0
        self._cleanup_in_flight = False
        self._update_check_in_flight = False
        self._latest_update_info: dict[str, Any] | None = None
        self._storage_snapshot: StorageScanSnapshot | None = None
        self._storage_scanning = False
        self._storage_view_mode = "session"
        self._storage_display_style = "treemap"
        self._storage_list_sort_key = "time"
        self._storage_list_sort_asc = True
        self._storage_list_age_filter = "all"
        self._storage_list_attr_filters: set[str] = set()
        self._storage_list_selected_ids: set[str] = set()
        self._storage_list_last_idx: int | None = None
        self._storage_list_items: list[StorageNode] = []
        self._storage_list_row_widgets: dict[str, tuple[ClickableRow, QCheckBox]] = {}
        self._storage_include_appdata = True
        self._storage_path_ids: list[str] = []
        self._storage_selected_id: str = ""
        self._storage_tree_root: StorageNode | None = None
        self._storage_agg_members: dict[str, list[str]] = {}
        self._pending_treemap_transition: tuple[str, str] = ("none", "")
        try:
            _, default_landing_url = build_update_urls(current_version=APP_VERSION)
        except Exception:
            default_landing_url = "https://ahmustudyhelper.xyz"
        self._current_update_url = default_landing_url

        config = self.manager.load_config()
        ui_cfg = config.get("ui") or {}
        self._theme_mode = ui_cfg.get("theme", "auto")
        if self._theme_mode not in THEME_MODES:
            self._theme_mode = "auto"
        self._minimize_to_tray = ui_cfg.get("minimizeToTray", True) is not False

        self.setWindowTitle("AGY Plugin Manager")
        self.setWindowIcon(self.app_icon)
        self.resize(1100, 710)
        self.setMinimumSize(860, 560)

        self._build_ui()
        self._storageScanProgress.connect(
            self._on_storage_scan_progress,
            Qt.ConnectionType.QueuedConnection,
        )
        self._build_tray()
        self._apply_theme()

        self._overview_timer = QTimer(self)
        self._overview_timer.setInterval(4000)
        self._overview_timer.timeout.connect(self.refresh_all)
        self._overview_timer.start()

        self._log_timer = QTimer(self)
        self._log_timer.setInterval(1500)
        self._log_timer.timeout.connect(self.refresh_logs)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast_lbl.hide)

        self._startup_timers: list[QTimer] = []

        def _schedule_startup(delay_ms: int, callback: Any) -> None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(delay_ms)
            t.timeout.connect(callback)
            self._startup_timers.append(t)
            t.start()

        _schedule_startup(40, self.refresh_all)
        if ui_cfg.get("autoCreateShortcutsOnStartup", True) is not False:
            _schedule_startup(250, self._ensure_default_shortcuts)
        update_cfg = config.get("update") if isinstance(config.get("update"), dict) else {}
        if update_cfg.get("autoCheckOnStartup", True) is not False:
            _schedule_startup(450, lambda: self._check_for_updates(manual=False))

    # ------------------------------------------------------------------
    # UI Construction: Proposal 4 Top Capsule Dock + Multi-Page Canvas
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(32, 16, 32, 18)
        root_lay.setSpacing(16)

        root_lay.addWidget(self._build_top_bar())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_status_tab())           # 0: Status Home
        self.stack.addWidget(self._build_external_tab())         # 1: My Plugins
        self.stack.addWidget(self._build_marketplace_tab())      # 2: Marketplace
        self.stack.addWidget(self._build_native_tab())           # 3: Native Extensions
        self.stack.addWidget(self._build_storage_tab())          # 4: AGY Storage Management
        self.stack.addWidget(self._build_logs_tab())             # 5: Live Logs
        self.stack.addWidget(self._build_settings_tab())         # 6: Settings & Maintenance
        self.stack.addWidget(self._build_external_detail_tab())  # 7: External Detail
        self.stack.addWidget(self._build_native_detail_tab())    # 8: Native Detail
        root_lay.addWidget(self.stack, 1)

        self.toast_lbl = QLabel("", self)
        self.toast_lbl.setObjectName("FloatingToast")
        self.toast_lbl.hide()

        self._build_floating_update_banner()

    def _make_clean_scroll(
        self,
        margins: tuple[int, int, int, int] = (6, 2, 6, 4),
        spacing: int = 0,
    ) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("ScrollViewport")
        container.setMinimumWidth(0)
        box = QVBoxLayout(container)
        box.setContentsMargins(*margins)
        box.setSpacing(spacing)
        box.addStretch(1)
        scroll.setWidget(container)
        return scroll, box

    @staticmethod
    def _row_label(text: str, object_name: str, *, word_wrap: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(object_name)
        lbl.setMinimumWidth(0)
        lbl.setWordWrap(word_wrap)
        lbl.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred if word_wrap else QSizePolicy.Policy.Fixed,
        )
        return lbl

    @staticmethod
    def _format_version_text(version: Any) -> str:
        raw = str(version or "").strip()
        if not raw:
            return "未标注"
        return raw if raw.lower().startswith("v") else f"v{raw}"

    @classmethod
    def _make_title_version_row(cls, title: str, version: Any) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        name_lbl = _ElidedTitleLabel(title)

        ver_lbl = QLabel(cls._format_version_text(version))
        ver_lbl.setObjectName("VersionTag")
        ver_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        row.addWidget(name_lbl)
        row.addWidget(ver_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return row

    def _load_brand_pixmap(self, logical_px: int = 20) -> QPixmap:
        assets_root = Path(getattr(self.manager.paths, "assets_dir", self.manager.base_dir))
        png_path = assets_root / "assets" / "app.png"
        if png_path.exists():
            pm = QPixmap(str(png_path))
            if not pm.isNull():
                scaled = pm.scaled(
                    logical_px * 3,
                    logical_px * 3,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                scaled.setDevicePixelRatio(3.0)
                return scaled
        return self.app_icon.pixmap(logical_px, logical_px)

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Left Brand Mark inside symmetric equal-width slot
        left_slot = QWidget()
        left_slot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        brand_box = QHBoxLayout(left_slot)
        brand_box.setContentsMargins(0, 0, 0, 0)
        brand_box.setSpacing(0)
        logo_lbl = QLabel()
        logo_lbl.setFixedSize(24, 24)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setPixmap(self._load_brand_pixmap(24))
        logo_lbl.setToolTip("AGY Plugin Manager")
        brand_box.addWidget(logo_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        brand_box.addStretch(1)

        # Center Floating Capsule Dock (Proposal 4 Style)
        dock = QFrame()
        dock.setObjectName("CapsuleDock")
        dock_lay = QHBoxLayout(dock)
        dock_lay.setContentsMargins(4, 4, 4, 4)
        dock_lay.setSpacing(2)

        self.tab_buttons: list[QPushButton] = []
        self.tab_group = QButtonGroup(bar)
        self.tab_group.setExclusive(True)
        nav_labels = ("运行状态", "我的插件", "插件市场", "原生扩展", "存储管理", "日志", "设置")
        for idx, text in enumerate(nav_labels):
            btn = QPushButton(text)
            btn.setObjectName("DockTab")
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=idx: self._switch_tab(i))
            dock_lay.addWidget(btn)
            self.tab_group.addButton(btn, idx)
            self.tab_buttons.append(btn)

        # Right Quick Pill inside symmetric equal-width slot
        right_slot = QWidget()
        right_slot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        right_box = QHBoxLayout(right_slot)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.addStretch(1)
        self.top_action_btn = QPushButton("刷新状态")
        self.top_action_btn.setObjectName("TopPillBtn")
        self.top_action_btn.setFixedWidth(136)
        self.top_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top_action_btn.clicked.connect(self._on_top_right_clicked)
        right_box.addWidget(self.top_action_btn)

        lay.addWidget(left_slot, 1)
        lay.addWidget(dock, 0)
        lay.addWidget(right_slot, 1)
        return bar

    def _on_top_right_clicked(self) -> None:
        if self.stack.currentIndex() == PAGE_STATUS:
            self.refresh_all(notify=True)
        else:
            self._quick_launch()

    # ------------------------------------------------------------------
    # Page 0: Status Home (Proposal 2 Status Layout)
    # ------------------------------------------------------------------
    def _build_status_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)

        # 1. Top Connection Hero Banner
        hero = QFrame()
        hero.setObjectName("WhiteCard")
        hero_lay = QHBoxLayout(hero)
        hero_lay.setContentsMargins(24, 20, 24, 20)
        hero_lay.setSpacing(16)

        self.hero_badge = HeroStatusIcon()
        hero_text = QVBoxLayout()
        hero_text.setSpacing(3)
        self.hero_title_lbl = QLabel("正在检测 Antigravity")
        self.hero_title_lbl.setObjectName("HeroTitle")
        self.hero_sub_lbl = QLabel("端口 --")
        self.hero_sub_lbl.setObjectName("MutedLabel")
        hero_text.addWidget(self.hero_title_lbl)
        hero_text.addWidget(self.hero_sub_lbl)

        self.home_attach_btn = QPushButton("热附着")
        self.home_attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.home_attach_btn.clicked.connect(self._attach_enabled)

        self.quick_launch_btn = QPushButton("启动 Antigravity")
        self.quick_launch_btn.setObjectName("PrimaryButton")
        self.quick_launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_launch_btn.clicked.connect(self._quick_launch)

        hero_lay.addWidget(self.hero_badge)
        hero_lay.addLayout(hero_text, 1)
        hero_lay.addWidget(self.home_attach_btn)
        hero_lay.addWidget(self.quick_launch_btn)
        lay.addWidget(hero)

        # 2. Asymmetric Two-Column Status Workspace
        mid_lay = QHBoxLayout()
        mid_lay.setSpacing(16)

        # Left Panel: Topology & Core Metrics
        arch_card = QFrame()
        arch_card.setObjectName("WhiteCard")
        arch_lay = QVBoxLayout(arch_card)
        arch_lay.setContentsMargins(22, 20, 22, 20)
        arch_lay.setSpacing(14)

        arch_hdr = QHBoxLayout()
        arch_title = QLabel("运行架构")
        arch_title.setObjectName("SectionTitle")
        self.arch_tag_lbl = QLabel("实时")
        self.arch_tag_lbl.setObjectName("FaintLabel")
        arch_hdr.addWidget(arch_title)
        arch_hdr.addStretch(1)
        arch_hdr.addWidget(self.arch_tag_lbl)
        arch_lay.addLayout(arch_hdr)

        topo_box = QFrame()
        topo_box.setObjectName("SoftInsetBox")
        topo_lay = QVBoxLayout(topo_box)
        topo_lay.setContentsMargins(10, 10, 10, 10)
        self.topology_widget = TopologyDiagramWidget()
        topo_lay.addWidget(self.topology_widget)
        arch_lay.addWidget(topo_box, 1)

        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(10)
        self.metric_port_val = self._add_metric_tile(tiles_row, "调试端口", "--")
        self.metric_sidecar_val = self._add_metric_tile(tiles_row, "伴生进程", "--")
        self.metric_dll_val = self._add_metric_tile(tiles_row, "兼容层 version.dll", "--")
        self.metric_plugin_mem_val = self._add_metric_tile(tiles_row, "插件总内存", "--")
        arch_lay.addLayout(tiles_row)

        mid_lay.addWidget(arch_card, 13)

        # Right Panel: Active Plugin Spotlight (capped cleanly so Home stays uncluttered)
        active_card = QFrame()
        active_card.setObjectName("WhiteCard")
        act_lay = QVBoxLayout(active_card)
        act_lay.setContentsMargins(22, 20, 22, 18)
        act_lay.setSpacing(14)

        act_hdr = QHBoxLayout()
        act_title = QLabel("活跃插件")
        act_title.setObjectName("SectionTitle")
        self.active_ratio_lbl = QLabel("0 / 0")
        self.active_ratio_lbl.setObjectName("FaintLabel")
        act_hdr.addWidget(act_title)
        act_hdr.addStretch(1)
        act_hdr.addWidget(self.active_ratio_lbl)
        act_lay.addLayout(act_hdr)

        scroll, self.home_active_list = self._make_clean_scroll(margins=(0, 0, 2, 0), spacing=10)
        act_lay.addWidget(scroll, 1)

        divider = QFrame()
        divider.setObjectName("HairlineRule")
        act_lay.addWidget(divider)

        foot_links = QHBoxLayout()
        manage_link = QPushButton("管理全部插件")
        manage_link.setObjectName("LinkButton")
        manage_link.setCursor(Qt.CursorShape.PointingHandCursor)
        manage_link.clicked.connect(lambda: self._switch_tab(1))

        market_link = QPushButton("插件市场")
        market_link.setObjectName("LinkButton")
        market_link.setCursor(Qt.CursorShape.PointingHandCursor)
        market_link.clicked.connect(lambda: self._switch_tab(2))

        foot_links.addWidget(manage_link)
        foot_links.addStretch(1)
        foot_links.addWidget(market_link)
        act_lay.addLayout(foot_links)

        mid_lay.addWidget(active_card, 10)
        lay.addLayout(mid_lay, 1)

        # 3. Minimal Quiet Footer (zero bloat)
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 0, 2, 0)
        sandbox_note = QLabel("独立沙盒托管")
        sandbox_note.setObjectName("FaintLabel")

        self.theme_btn = QPushButton(THEME_LABELS[self._theme_mode])
        self.theme_btn.setObjectName("FilterChip")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._cycle_theme)

        footer.addWidget(sandbox_note)
        footer.addStretch(1)
        footer.addWidget(self.theme_btn)
        lay.addLayout(footer)
        return page

    def _add_metric_tile(self, parent_lay: QHBoxLayout, label: str, initial: str) -> QLabel:
        tile = QFrame()
        tile.setObjectName("MiniMetricTile")
        t_lay = QVBoxLayout(tile)
        t_lay.setContentsMargins(13, 11, 13, 11)
        t_lay.setSpacing(3)
        k_lbl = QLabel(label)
        k_lbl.setObjectName("FaintLabel")
        v_lbl = QLabel(initial)
        v_lbl.setObjectName("MetricValue")
        t_lay.addWidget(k_lbl)
        t_lay.addWidget(v_lbl)
        parent_lay.addWidget(tile, 1)
        return v_lbl

    # ------------------------------------------------------------------
    # Page 1: My Plugins (Scalable Multi-Plugin Catalog)
    # ------------------------------------------------------------------
    def _build_external_tab(self) -> QWidget:
        page = QWidget()
        page.setAcceptDrops(True)
        page.installEventFilter(self)
        self._external_page = page
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        toolbar = QFrame()
        toolbar.setObjectName("WhiteCard")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(16, 11, 16, 11)
        tb_lay.setSpacing(8)

        self.ext_search = QLineEdit()
        self.ext_search.setPlaceholderText("搜索插件名称、简介或 ID...")
        self.ext_search.setFixedWidth(220)
        self.ext_search.textChanged.connect(self._re_render_external)

        self.filter_chips: dict[str, QPushButton] = {}
        for key, label in (("all", "全部"), ("running", "运行中"), ("idle", "待命")):
            chip = QPushButton(label)
            chip.setObjectName("FilterChip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setProperty("active", key == "all")
            chip.clicked.connect(lambda _=False, k=key: self._set_plugin_filter(k))
            self.filter_chips[key] = chip

        add_btn = QPushButton("+ 导入插件")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._open_add_plugin)

        self.install_pkg_btn = QPushButton("安装插件包")
        self.install_pkg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_pkg_btn.clicked.connect(self._install_plugin_package_dialog)

        market_btn = QPushButton("浏览市场")
        market_btn.setObjectName("PrimaryButton")
        market_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        market_btn.clicked.connect(lambda: self._switch_tab(2))

        tb_lay.addWidget(self.ext_search)
        for chip in self.filter_chips.values():
            tb_lay.addWidget(chip)
        tb_lay.addStretch(1)
        tb_lay.addWidget(add_btn)
        tb_lay.addWidget(self.install_pkg_btn)
        tb_lay.addWidget(market_btn)
        lay.addWidget(toolbar)

        self.plugin_drop_container = PluginDropContainer()
        drop_lay = QVBoxLayout(self.plugin_drop_container)
        drop_lay.setContentsMargins(0, 4, 0, 10)
        drop_lay.setSpacing(8)

        scroll, self.external_list = self._make_clean_scroll(margins=(6, 2, 6, 4), spacing=0)
        self.external_scroll = scroll
        drop_lay.addWidget(scroll, 1)

        self.drop_hint_banner = QFrame()
        self.drop_hint_banner.setObjectName("DropHintBanner")
        self.drop_hint_banner.setProperty("dragActive", False)
        banner_lay = QHBoxLayout(self.drop_hint_banner)
        banner_lay.setContentsMargins(14, 8, 14, 8)
        self.drop_hint_label = QLabel(DROP_HINT_IDLE_TEXT)
        self.drop_hint_label.setObjectName("DropHintLabel")
        self.drop_hint_label.setProperty("dragActive", False)
        self.drop_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_lay.addWidget(self.drop_hint_label, 1)

        banner_wrap = QHBoxLayout()
        banner_wrap.setContentsMargins(12, 0, 12, 0)
        banner_wrap.addWidget(self.drop_hint_banner)
        drop_lay.addLayout(banner_wrap)

        self.plugin_drop_container.bind_hint_widgets(self.drop_hint_banner, self.drop_hint_label)
        self.plugin_drop_container.packageDropped.connect(self._install_plugin_package)
        lay.addWidget(self.plugin_drop_container, 1)
        return page

    # ------------------------------------------------------------------
    # Page 2: Plugin Marketplace (Local Packages & Registry Ready)
    # ------------------------------------------------------------------
    def _build_marketplace_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        bar = QFrame()
        bar.setObjectName("WhiteCard")
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(16, 11, 16, 11)
        bar_lay.setSpacing(10)

        self.market_search = QLineEdit()
        self.market_search.setPlaceholderText("搜索本地插件包或扩展目录...")
        self.market_search.setFixedWidth(260)
        self.market_search.textChanged.connect(self._render_marketplace)

        import_btn = QPushButton("+ 手动配置导入")
        import_btn.setObjectName("PrimaryButton")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self._open_add_plugin)

        bar_lay.addWidget(self.market_search)
        bar_lay.addStretch(1)
        bar_lay.addWidget(import_btn)
        lay.addWidget(bar)

        card = QFrame()
        card.setObjectName("WhiteCard")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 4, 0, 4)

        scroll, self.market_list = self._make_clean_scroll(margins=(6, 2, 6, 4), spacing=0)
        card_lay.addWidget(scroll, 1)
        lay.addWidget(card, 1)

        foot = QLabel("支持从 plugins 目录发现或手动导入第三方扩展；远程市场源接入就绪")
        foot.setObjectName("FaintLabel")
        lay.addWidget(foot)
        return page

    # ------------------------------------------------------------------
    # Page 3: Native Extensions
    # ------------------------------------------------------------------
    def _build_native_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        bar = QFrame()
        bar.setObjectName("WhiteCard")
        b_lay = QHBoxLayout(bar)
        b_lay.setContentsMargins(16, 11, 16, 11)
        b_lay.setSpacing(10)

        title = QLabel("原生扩展")
        title.setObjectName("SectionTitle")
        self.native_search = QLineEdit()
        self.native_search.setPlaceholderText("搜索扩展名称...")
        self.native_search.setFixedWidth(240)
        self.native_search.textChanged.connect(self._render_native_plugins)

        b_lay.addWidget(title)
        b_lay.addStretch(1)
        b_lay.addWidget(self.native_search)
        lay.addWidget(bar)

        card = QFrame()
        card.setObjectName("WhiteCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(0, 4, 0, 4)

        scroll, self.native_list = self._make_clean_scroll(margins=(6, 2, 6, 4), spacing=0)
        c_lay.addWidget(scroll, 1)
        lay.addWidget(card, 1)
        return page

    # ------------------------------------------------------------------
    # Page 4: AGY Storage Management (SpaceSniffer Treemap)
    # ------------------------------------------------------------------
    def _build_storage_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        # Toolbar card: view segments + search + include_appdata + rescan + summary + breadcrumbs
        bar = QFrame()
        bar.setObjectName("WhiteCard")
        bar_lay = QVBoxLayout(bar)
        bar_lay.setContentsMargins(16, 11, 16, 11)
        bar_lay.setSpacing(8)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        seg_frame = QFrame()
        seg_frame.setObjectName("SegmentBar")
        seg_lay = QHBoxLayout(seg_frame)
        seg_lay.setContentsMargins(3, 3, 3, 3)
        seg_lay.setSpacing(2)

        self.storage_view_group = QButtonGroup(page)
        self.storage_view_group.setExclusive(True)
        self.storage_view_buttons: dict[str, QPushButton] = {}
        for mode_key, label in (("session", "按会话"), ("type", "按文件类型"), ("dir", "按目录结构")):
            sbtn = QPushButton(label)
            sbtn.setObjectName("SegmentBtn")
            sbtn.setCheckable(True)
            sbtn.setChecked(mode_key == self._storage_view_mode)
            sbtn.setCursor(Qt.CursorShape.PointingHandCursor)
            sbtn.clicked.connect(lambda _=False, m=mode_key: self._set_storage_view_mode(m))
            seg_lay.addWidget(sbtn)
            self.storage_view_group.addButton(sbtn)
            self.storage_view_buttons[mode_key] = sbtn

        # Orthogonal display style switcher: Treemap (方框) vs List (列表)
        style_frame = QFrame()
        style_frame.setObjectName("SegmentBar")
        style_lay = QHBoxLayout(style_frame)
        style_lay.setContentsMargins(3, 3, 3, 3)
        style_lay.setSpacing(2)

        self.storage_style_group = QButtonGroup(page)
        self.storage_style_group.setExclusive(True)
        self.storage_style_buttons: dict[str, QPushButton] = {}
        for style_key, style_label in (("treemap", "方框"), ("list", "列表")):
            st_btn = QPushButton(style_label)
            st_btn.setObjectName("SegmentBtn")
            st_btn.setCheckable(True)
            st_btn.setChecked(style_key == self._storage_display_style)
            st_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            st_btn.clicked.connect(lambda _=False, s=style_key: self._set_storage_display_style(s))
            style_lay.addWidget(st_btn)
            self.storage_style_group.addButton(st_btn)
            self.storage_style_buttons[style_key] = st_btn

        self.storage_search = QLineEdit()
        self.storage_search.setPlaceholderText("搜索会话名 / UUID / 文件...")
        self.storage_search.setFixedWidth(185)
        self.storage_search.textChanged.connect(self._on_storage_filter_changed)

        self.storage_appdata_chk = QCheckBox("含应用缓存")
        self.storage_appdata_chk.setChecked(self._storage_include_appdata)
        self.storage_appdata_chk.toggled.connect(self._on_storage_appdata_toggled)

        self.storage_orphan_btn = QPushButton("清理失效记录")
        self.storage_orphan_btn.setObjectName("WarningGhostButton")
        self.storage_orphan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_orphan_btn.setToolTip(
            "清理本地文件已删除但仍残留在 Antigravity 对话列表索引中的失效记录"
        )
        self.storage_orphan_btn.clicked.connect(self._clean_orphan_storage_summaries)
        self.storage_orphan_btn.hide()

        self.storage_rescan_btn = QPushButton("重新扫描")
        self.storage_rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_rescan_btn.clicked.connect(self._refresh_storage_scan)

        ctrl_row.addWidget(seg_frame)
        ctrl_row.addWidget(style_frame)
        ctrl_row.addWidget(self.storage_search)
        ctrl_row.addWidget(self.storage_appdata_chk)
        ctrl_row.addStretch(1)
        ctrl_row.addWidget(self.storage_orphan_btn)
        ctrl_row.addWidget(self.storage_rescan_btn)
        bar_lay.addLayout(ctrl_row)

        # Second row: stacked between Treemap Breadcrumbs and List Sort/Filter controls
        self.storage_subbar_stack = QStackedWidget()

        crumb_bar = QWidget()
        crumb_row = QHBoxLayout(crumb_bar)
        crumb_row.setContentsMargins(0, 0, 0, 0)
        crumb_row.setSpacing(6)
        self.storage_up_btn = QPushButton("← 返回上级")
        self.storage_up_btn.setObjectName("BreadcrumbBtn")
        self.storage_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_up_btn.clicked.connect(self._storage_navigate_up)
        self.storage_up_btn.setEnabled(False)
        crumb_row.addWidget(self.storage_up_btn)

        self.storage_crumb_lay = QHBoxLayout()
        self.storage_crumb_lay.setContentsMargins(0, 0, 0, 0)
        self.storage_crumb_lay.setSpacing(2)
        crumb_row.addLayout(self.storage_crumb_lay)
        crumb_row.addStretch(1)

        self.storage_summary_lbl = QLabel("点击「重新扫描」或切换视图加载本地 AGY 存储占用")
        self.storage_summary_lbl.setObjectName("MonoLabel")
        crumb_row.addWidget(self.storage_summary_lbl)
        self.storage_subbar_stack.addWidget(crumb_bar)

        list_subbar = QWidget()
        list_sub_lay = QHBoxLayout(list_subbar)
        list_sub_lay.setContentsMargins(0, 0, 0, 0)
        list_sub_lay.setSpacing(8)

        self.storage_list_up_btn = QPushButton("← 返回上级")
        self.storage_list_up_btn.setObjectName("BreadcrumbBtn")
        self.storage_list_up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_list_up_btn.clicked.connect(self._storage_navigate_up)
        self.storage_list_up_btn.hide()
        list_sub_lay.addWidget(self.storage_list_up_btn)

        sort_lbl = QLabel("排序：")
        sort_lbl.setObjectName("MutedLabel")
        list_sub_lay.addWidget(sort_lbl)

        self.storage_sort_time_btn = QPushButton("最近更新 ↑ 最久未用")
        self.storage_sort_time_btn.setObjectName("SortPillBtn")
        self.storage_sort_time_btn.setCheckable(True)
        self.storage_sort_time_btn.setChecked(self._storage_list_sort_key == "time")
        self.storage_sort_time_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_sort_time_btn.clicked.connect(lambda: self._set_storage_list_sort("time"))
        list_sub_lay.addWidget(self.storage_sort_time_btn)

        self.storage_sort_size_btn = QPushButton("占用空间 ↓")
        self.storage_sort_size_btn.setObjectName("SortPillBtn")
        self.storage_sort_size_btn.setCheckable(True)
        self.storage_sort_size_btn.setChecked(self._storage_list_sort_key == "size")
        self.storage_sort_size_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_sort_size_btn.clicked.connect(lambda: self._set_storage_list_sort("size"))
        list_sub_lay.addWidget(self.storage_sort_size_btn)

        self.storage_age_filter_box = QWidget()
        age_lay = QHBoxLayout(self.storage_age_filter_box)
        age_lay.setContentsMargins(6, 0, 0, 0)
        age_lay.setSpacing(4)
        age_lbl = QLabel("筛选：")
        age_lbl.setObjectName("MutedLabel")
        age_lay.addWidget(age_lbl)
        self.storage_age_group = QButtonGroup(page)
        self.storage_age_group.setExclusive(True)
        self.storage_age_buttons: dict[str, QPushButton] = {}
        for fkey, flabel in (("all", "全部时间"), ("7d", "> 7天未用"), ("30d", "> 30天未用")):
            fbtn = QPushButton(flabel)
            fbtn.setObjectName("AgeFilterBtn")
            fbtn.setCheckable(True)
            fbtn.setChecked(fkey == self._storage_list_age_filter)
            fbtn.setCursor(Qt.CursorShape.PointingHandCursor)
            fbtn.clicked.connect(lambda _=False, fk=fkey: self._set_storage_list_age_filter(fk))
            age_lay.addWidget(fbtn)
            self.storage_age_group.addButton(fbtn)
            self.storage_age_buttons[fkey] = fbtn

        attr_sep = QFrame()
        attr_sep.setFixedSize(1, 14)
        attr_sep.setStyleSheet("background-color: rgba(140, 147, 160, 0.35);")
        age_lay.addWidget(attr_sep)

        self.storage_attr_buttons: dict[str, QPushButton] = {}
        for akey, alabel in (("archived", "已归档"), ("subagent", "子代理会话"), ("unnamed", "未命名会话")):
            abtn = QPushButton(alabel)
            abtn.setObjectName("AgeFilterBtn")
            abtn.setCheckable(True)
            abtn.setChecked(akey in self._storage_list_attr_filters)
            abtn.setCursor(Qt.CursorShape.PointingHandCursor)
            abtn.toggled.connect(lambda checked, ak=akey: self._set_storage_list_attr_filter(ak, checked))
            age_lay.addWidget(abtn)
            self.storage_attr_buttons[akey] = abtn

        list_sub_lay.addWidget(self.storage_age_filter_box)

        list_sub_lay.addStretch(1)
        self.storage_list_summary_lbl = QLabel("")
        self.storage_list_summary_lbl.setObjectName("MonoLabel")
        list_sub_lay.addWidget(self.storage_list_summary_lbl)
        self.storage_subbar_stack.addWidget(list_subbar)

        bar_lay.addWidget(self.storage_subbar_stack)

        self.storage_scan_bar = QProgressBar()
        self.storage_scan_bar.setObjectName("ScanProgressBar")
        self.storage_scan_bar.setTextVisible(False)
        self.storage_scan_bar.setRange(0, 1000)
        self.storage_scan_bar.setValue(0)
        self.storage_scan_bar.hide()
        bar_lay.addWidget(self.storage_scan_bar)

        lay.addWidget(bar)

        # Workspace stack: Index 0 = Treemap + Inspector; Index 1 = Sortable Multi-Select List + Batch Dock
        self.storage_workspace_stack = QStackedWidget()

        treemap_page = QWidget()
        split = QHBoxLayout(treemap_page)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(14)

        map_card = QFrame()
        map_card.setObjectName("WhiteCard")
        map_lay = QVBoxLayout(map_card)
        map_lay.setContentsMargins(14, 14, 14, 12)
        map_lay.setSpacing(8)

        self.storage_treemap = SpaceTreemapWidget(is_dark=resolve_is_dark(self._theme_mode))
        self.storage_treemap.nodeHovered.connect(self._on_storage_node_hovered)
        self.storage_treemap.nodeSelected.connect(self._on_storage_node_selected)
        self.storage_treemap.nodeActivated.connect(self._on_storage_node_activated)
        self.storage_treemap.nodeContextMenuRequested.connect(self._on_storage_context_menu)
        map_lay.addWidget(self.storage_treemap, 1)

        self.storage_hover_lbl = QLabel("悬停任意方块查看该目录/文件存放的内容及是否可安全删除")
        self.storage_hover_lbl.setObjectName("StorageHoverLabel")
        self.storage_hover_lbl.setProperty("tone", "")
        self.storage_hover_lbl.setWordWrap(False)
        self.storage_hover_lbl.setMinimumWidth(0)
        self.storage_hover_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        map_lay.addWidget(self.storage_hover_lbl)

        split.addWidget(map_card, 13)

        # Right column: Inspector card + Ranked children card
        right_card = QFrame()
        right_card.setObjectName("WhiteCard")
        right_card.setMinimumWidth(300)
        right_card.setMaximumWidth(370)
        r_lay = QVBoxLayout(right_card)
        r_lay.setContentsMargins(16, 14, 16, 14)
        r_lay.setSpacing(10)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(6)
        self.st_insp_kind_pill = QLabel("总览")
        self.st_insp_kind_pill.setObjectName("PillInfo")
        self.st_insp_del_pill = QLabel("可安全清理")
        self.st_insp_del_pill.setObjectName("PillOk")
        self.st_insp_del_pill.hide()
        self.st_insp_prot_pill = QLabel("规则受保护")
        self.st_insp_prot_pill.setObjectName("PillWarn")
        self.st_insp_prot_pill.hide()
        badge_row.addWidget(self.st_insp_kind_pill)
        badge_row.addWidget(self.st_insp_del_pill)
        badge_row.addWidget(self.st_insp_prot_pill)
        badge_row.addStretch(1)
        r_lay.addLayout(badge_row)

        self.st_insp_title = QLabel("等待扫描")
        self.st_insp_title.setObjectName("CardTitle")
        self.st_insp_title.setWordWrap(True)
        r_lay.addWidget(self.st_insp_title)

        self.st_insp_path = QLabel("-")
        self.st_insp_path.setObjectName("MonoLabel")
        self.st_insp_path.setWordWrap(True)
        r_lay.addWidget(self.st_insp_path)

        self.st_insp_purpose = QLabel("")
        self.st_insp_purpose.setObjectName("StoragePurposeLabel")
        self.st_insp_purpose.setWordWrap(True)
        self.st_insp_purpose.hide()
        r_lay.addWidget(self.st_insp_purpose)

        stats_box = QFrame()
        stats_box.setObjectName("SoftInsetBox")
        stats_lay = QHBoxLayout(stats_box)
        stats_lay.setContentsMargins(10, 8, 10, 8)
        stats_lay.setSpacing(8)
        self.st_stat_size = self._add_storage_mini_stat(stats_lay, "占用空间", "--")
        self.st_stat_share = self._add_storage_mini_stat(stats_lay, "占比", "--")
        self.st_stat_count = self._add_storage_mini_stat(stats_lay, "文件数", "--")
        r_lay.addWidget(stats_box)

        # Context-sensitive action buttons
        act_grid = QVBoxLayout()
        act_grid.setSpacing(6)
        act_row1 = QHBoxLayout()
        act_row1.setSpacing(6)
        self.st_btn_clean_files = QPushButton("仅删会话文件")
        self.st_btn_clean_files.setObjectName("WarningGhostButton")
        self.st_btn_clean_files.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_btn_clean_files.clicked.connect(self._storage_action_clean_session_files)

        self.st_btn_del_session = QPushButton("删除会话")
        self.st_btn_del_session.setObjectName("DangerGhostButton")
        self.st_btn_del_session.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_btn_del_session.clicked.connect(self._storage_action_delete_session)

        self.st_btn_del_item = QPushButton("清理此项")
        self.st_btn_del_item.setObjectName("DangerGhostButton")
        self.st_btn_del_item.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_btn_del_item.clicked.connect(self._storage_action_delete_selected)

        act_row1.addWidget(self.st_btn_clean_files)
        act_row1.addWidget(self.st_btn_del_session)
        act_row1.addWidget(self.st_btn_del_item)
        act_grid.addLayout(act_row1)

        act_row2 = QHBoxLayout()
        act_row2.setSpacing(6)
        self.st_btn_drill = QPushButton("深入查看")
        self.st_btn_drill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_btn_drill.clicked.connect(self._storage_action_drill_selected)

        self.st_btn_reveal = QPushButton("打开所在目录")
        self.st_btn_reveal.setCursor(Qt.CursorShape.PointingHandCursor)
        self.st_btn_reveal.clicked.connect(self._storage_action_open_explorer)

        act_row2.addWidget(self.st_btn_drill)
        act_row2.addWidget(self.st_btn_reveal)
        act_grid.addLayout(act_row2)
        r_lay.addLayout(act_grid)

        rank_hdr = QHBoxLayout()
        self.st_rank_hdr_lbl = QLabel("当前层级大项排行")
        self.st_rank_hdr_lbl.setObjectName("MutedLabel")
        rank_hdr.addWidget(self.st_rank_hdr_lbl)
        rank_hdr.addStretch(1)
        r_lay.addLayout(rank_hdr)

        r_scroll, self.storage_rank_list = self._make_clean_scroll(margins=(0, 2, 2, 2), spacing=6)
        r_lay.addWidget(r_scroll, 1)

        split.addWidget(right_card, 7)
        self.storage_workspace_stack.addWidget(treemap_page)

        # List workspace (Index 1): Checkable sortable table + Batch cleanup dock
        list_page = QWidget()
        list_page_lay = QVBoxLayout(list_page)
        list_page_lay.setContentsMargins(0, 0, 0, 0)
        list_page_lay.setSpacing(10)

        list_card = QFrame()
        list_card.setObjectName("WhiteCard")
        lc_lay = QVBoxLayout(list_card)
        lc_lay.setContentsMargins(0, 0, 0, 0)
        lc_lay.setSpacing(0)

        list_hdr = QFrame()
        list_hdr.setObjectName("StorageListHeader")
        list_hdr.setFixedHeight(36)
        lh_lay = QHBoxLayout(list_hdr)
        lh_lay.setContentsMargins(14, 0, 20, 0)
        lh_lay.setSpacing(12)

        self.storage_select_all_chk = QCheckBox()
        self.storage_select_all_chk.setObjectName("RowCheckBox")
        self.storage_select_all_chk.setFixedWidth(22)
        self.storage_select_all_chk.setToolTip("全选 / 取消全选当前列表")
        self.storage_select_all_chk.clicked.connect(self._on_storage_list_select_all_clicked)

        self.storage_list_col_name_lbl = QLabel("会话名称 / 标识")
        self.storage_list_col_name_lbl.setObjectName("FaintLabel")
        col_time_lbl = QLabel("最近更新")
        col_time_lbl.setObjectName("FaintLabel")
        col_time_lbl.setFixedWidth(185)
        col_size_lbl = QLabel("占用空间 / 构成")
        col_size_lbl.setObjectName("FaintLabel")
        col_size_lbl.setFixedWidth(165)
        col_act_lbl = QLabel("快捷操作")
        col_act_lbl.setObjectName("FaintLabel")
        col_act_lbl.setFixedWidth(124)
        col_act_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lh_lay.addWidget(self.storage_select_all_chk)
        lh_lay.addWidget(self.storage_list_col_name_lbl, 1)
        lh_lay.addWidget(col_time_lbl)
        lh_lay.addWidget(col_size_lbl)
        lh_lay.addWidget(col_act_lbl)
        lc_lay.addWidget(list_hdr)

        l_scroll, self.storage_list_container = self._make_clean_scroll(margins=(0, 0, 2, 4), spacing=0)
        lc_lay.addWidget(l_scroll, 1)
        list_page_lay.addWidget(list_card, 1)

        batch_bar = QFrame()
        batch_bar.setObjectName("BatchActionBar")
        bb_lay = QHBoxLayout(batch_bar)
        bb_lay.setContentsMargins(16, 10, 16, 10)
        bb_lay.setSpacing(10)

        bb_info = QVBoxLayout()
        bb_info.setSpacing(2)
        self.storage_batch_title = QLabel("未选择任何会话")
        self.storage_batch_title.setStyleSheet("font-weight: 600; font-size: 9.4pt;")
        self.storage_batch_sub = QLabel("勾选条目（支持 Shift 连选）可批量清理会话产出文件或删除整个会话")
        self.storage_batch_sub.setObjectName("FaintLabel")
        bb_info.addWidget(self.storage_batch_title)
        bb_info.addWidget(self.storage_batch_sub)
        bb_lay.addLayout(bb_info, 1)

        self.storage_list_invert_btn = QPushButton("反选")
        self.storage_list_invert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_list_invert_btn.clicked.connect(self._invert_storage_list_selection)
        bb_lay.addWidget(self.storage_list_invert_btn)

        self.storage_list_clear_btn = QPushButton("清空选择")
        self.storage_list_clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_list_clear_btn.clicked.connect(self._clear_storage_list_selection)
        self.storage_list_clear_btn.setEnabled(False)
        bb_lay.addWidget(self.storage_list_clear_btn)

        self.storage_batch_files_btn = QPushButton("仅删除会话文件（保留记录）")
        self.storage_batch_files_btn.setObjectName("WarningGhostButton")
        self.storage_batch_files_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_batch_files_btn.clicked.connect(self._storage_batch_clean_session_files)
        self.storage_batch_files_btn.setEnabled(False)
        bb_lay.addWidget(self.storage_batch_files_btn)

        self.storage_batch_sessions_btn = QPushButton("删除所选会话")
        self.storage_batch_sessions_btn.setObjectName("DangerGhostButton")
        self.storage_batch_sessions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_batch_sessions_btn.clicked.connect(self._storage_batch_delete_sessions)
        self.storage_batch_sessions_btn.setEnabled(False)
        bb_lay.addWidget(self.storage_batch_sessions_btn)

        self.storage_batch_items_btn = QPushButton("清理所选条目")
        self.storage_batch_items_btn.setObjectName("DangerGhostButton")
        self.storage_batch_items_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.storage_batch_items_btn.clicked.connect(self._storage_batch_delete_items)
        self.storage_batch_items_btn.setEnabled(False)
        self.storage_batch_items_btn.hide()
        bb_lay.addWidget(self.storage_batch_items_btn)

        list_page_lay.addWidget(batch_bar)
        self.storage_workspace_stack.addWidget(list_page)

        self.storage_subbar_stack.setCurrentIndex(1 if self._storage_display_style == "list" else 0)
        self.storage_workspace_stack.setCurrentIndex(1 if self._storage_display_style == "list" else 0)
        lay.addWidget(self.storage_workspace_stack, 1)
        return page

    @staticmethod
    def _add_storage_mini_stat(parent_lay: QHBoxLayout, label: str, val: str) -> QLabel:
        col = QVBoxLayout()
        col.setSpacing(2)
        k = QLabel(label)
        k.setObjectName("FaintLabel")
        v = QLabel(val)
        v.setObjectName("MonoLabel")
        col.addWidget(k)
        col.addWidget(v)
        parent_lay.addLayout(col, 1)
        return v

    # ------------------------------------------------------------------
    # Page 5: Logs
    # ------------------------------------------------------------------
    def _build_logs_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        bar = QFrame()
        bar.setObjectName("WhiteCard")
        b_lay = QHBoxLayout(bar)
        b_lay.setContentsMargins(16, 11, 16, 11)
        b_lay.setSpacing(10)

        self.log_source_combo = QComboBox()
        self.log_source_combo.addItem("launcher.log", "launcher")
        self.log_source_combo.currentIndexChanged.connect(self.refresh_logs)

        self.log_tail_combo = QComboBox()
        for count in (100, 200, 500):
            self.log_tail_combo.addItem(f"最近 {count} 行", count)
        self.log_tail_combo.setCurrentIndex(1)
        self.log_tail_combo.currentIndexChanged.connect(self.refresh_logs)

        self.log_bytes_lbl = QLabel("0 B")
        self.log_bytes_lbl.setObjectName("MonoLabel")

        self.log_stream_btn = QPushButton("暂停")
        self.log_stream_btn.clicked.connect(self._toggle_log_stream)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_current_log)

        b_lay.addWidget(self.log_source_combo)
        b_lay.addWidget(self.log_tail_combo)
        b_lay.addWidget(self.log_bytes_lbl)
        b_lay.addStretch(1)
        b_lay.addWidget(self.log_stream_btn)
        b_lay.addWidget(clear_btn)
        lay.addWidget(bar)

        self.log_path_lbl = QLabel("logs/launcher.log")
        self.log_path_lbl.setObjectName("MonoLabel")
        self.log_path_lbl.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(self.log_path_lbl)

        self.log_console = QPlainTextEdit()
        self.log_console.setObjectName("LogConsole")
        self.log_console.setReadOnly(True)
        lay.addWidget(self.log_console, 1)
        return page

    # ------------------------------------------------------------------
    # Page 6: Settings & Maintenance
    # ------------------------------------------------------------------
    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        bar = QFrame()
        bar.setObjectName("WhiteCard")
        b_lay = QHBoxLayout(bar)
        b_lay.setContentsMargins(18, 12, 18, 12)
        t_lbl = QLabel("设置与维护")
        t_lbl.setObjectName("SectionTitle")
        save_btn = QPushButton("保存配置")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_settings)
        b_lay.addWidget(t_lbl)
        b_lay.addStretch(1)
        b_lay.addWidget(save_btn)
        lay.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("ScrollViewport")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 2, 8)
        body_lay.setSpacing(14)

        # Card 1: Maintenance Actions
        m_card = QFrame()
        m_card.setObjectName("WhiteCard")
        m_lay = QVBoxLayout(m_card)
        m_lay.setContentsMargins(20, 18, 20, 18)
        m_lay.setSpacing(12)
        m_t = QLabel("快捷维护")
        m_t.setObjectName("CardTitle")
        m_btns = QHBoxLayout()
        m_btns.setSpacing(10)
        self.attach_btn = QPushButton("热附着启用插件")
        self.attach_btn.clicked.connect(self._attach_enabled)
        self.stop_all_btn = QPushButton("停止全部扩展")
        self.stop_all_btn.clicked.connect(self._stop_all_plugins)
        self.cleanup_btn = QPushButton("清理残留进程")
        self.cleanup_btn.clicked.connect(self._cleanup_residuals)
        self.shortcut_btn = QPushButton("更新桌面图标")
        self.shortcut_btn.clicked.connect(self._create_shortcuts)
        self.refresh_btn = QPushButton("刷新状态")
        self.refresh_btn.clicked.connect(lambda: self.refresh_all(notify=True))
        m_btns.addWidget(self.attach_btn)
        m_btns.addWidget(self.stop_all_btn)
        m_btns.addWidget(self.cleanup_btn)
        m_btns.addWidget(self.shortcut_btn)
        m_btns.addWidget(self.refresh_btn)
        m_btns.addStretch(1)
        m_lay.addWidget(m_t)
        m_lay.addLayout(m_btns)
        body_lay.addWidget(m_card)

        # Card 1.5: Software Update
        u_card = QFrame()
        u_card.setObjectName("WhiteCard")
        u_lay = QVBoxLayout(u_card)
        u_lay.setContentsMargins(20, 18, 20, 18)
        u_lay.setSpacing(8)
        u_hdr = QHBoxLayout()
        u_t = QLabel("版本与更新")
        u_t.setObjectName("CardTitle")
        self.update_current_ver_tag = QLabel(f"v{APP_VERSION}")
        self.update_current_ver_tag.setObjectName("VersionTag")
        self.update_current_ver_tag.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.update_status_lbl = QLabel("每次启动自动检查更新（非强制）")
        self.update_status_lbl.setObjectName("DotMuted")
        self.open_update_site_btn = QPushButton("前往官网")
        self.open_update_site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_update_site_btn.clicked.connect(self._open_update_website)
        self.check_update_btn = QPushButton("检查更新")
        self.check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_update_btn.clicked.connect(lambda: self._check_for_updates(manual=True))
        u_hdr.addWidget(u_t)
        u_hdr.addSpacing(8)
        u_hdr.addWidget(self.update_current_ver_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        u_hdr.addSpacing(8)
        u_hdr.addWidget(self.update_status_lbl)
        u_hdr.addStretch(1)
        u_hdr.addWidget(self.open_update_site_btn)
        u_hdr.addWidget(self.check_update_btn)
        u_hint = QLabel("更新检测与文案由 HaoAn Lab 官网统一提供，发现新版本时将在右上角悬浮提示，可随时忽略继续使用。")
        u_hint.setObjectName("MutedLabel")
        u_hint.setWordWrap(True)
        u_lay.addLayout(u_hdr)
        u_lay.addWidget(u_hint)
        body_lay.addWidget(u_card)

        # Card 2: Antigravity Path
        agy_card = QFrame()
        agy_card.setObjectName("WhiteCard")
        agy_lay = QVBoxLayout(agy_card)
        agy_lay.setContentsMargins(20, 18, 20, 18)
        agy_lay.setSpacing(12)
        agy_hdr = QHBoxLayout()
        agy_t = QLabel("Antigravity 主程序")
        agy_t.setObjectName("CardTitle")
        self.agy_path_status_lbl = QLabel("")
        self.agy_path_status_lbl.setObjectName("DotMuted")
        self.agy_detect_btn = QPushButton("自动检测")
        self.agy_detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.agy_detect_btn.clicked.connect(self._detect_antigravity_path)
        self.agy_browse_btn = QPushButton("浏览")
        self.agy_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.agy_browse_btn.clicked.connect(self._browse_antigravity_path)
        agy_hdr.addWidget(agy_t)
        agy_hdr.addSpacing(8)
        agy_hdr.addWidget(self.agy_path_status_lbl)
        agy_hdr.addStretch(1)
        agy_hdr.addWidget(self.agy_detect_btn)
        agy_hdr.addWidget(self.agy_browse_btn)

        agy_form = QFormLayout()
        agy_form.setSpacing(10)
        agy_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.agy_exe_edit = QLineEdit()
        self.agy_exe_edit.setPlaceholderText("自动检测或选择 Antigravity.exe 路径")
        agy_form.addRow("Antigravity 路径", self.agy_exe_edit)
        agy_lay.addLayout(agy_hdr)
        agy_lay.addLayout(agy_form)
        body_lay.addWidget(agy_card)

        # Card 3: Proxy
        p_card = QFrame()
        p_card.setObjectName("WhiteCard")
        p_lay = QVBoxLayout(p_card)
        p_lay.setContentsMargins(20, 18, 20, 18)
        p_lay.setSpacing(12)
        p_hdr = QHBoxLayout()
        p_t = QLabel("按需代理注入")
        p_t.setObjectName("CardTitle")
        self.proxy_detect_status_lbl = QLabel("")
        self.proxy_detect_status_lbl.setObjectName("DotMuted")
        self.proxy_detect_btn = QPushButton("自动检测系统代理")
        self.proxy_detect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.proxy_detect_btn.clicked.connect(self._auto_detect_proxy)
        p_hdr.addWidget(p_t)
        p_hdr.addSpacing(8)
        p_hdr.addWidget(self.proxy_detect_status_lbl)
        p_hdr.addStretch(1)
        p_hdr.addWidget(self.proxy_detect_btn)
        self.proxy_enabled_chk = QCheckBox("仅在启动 Antigravity 时传入代理参数")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.proxy_http_edit = QLineEdit()
        self.proxy_http_edit.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_https_edit = QLineEdit()
        self.proxy_https_edit.setPlaceholderText("http://127.0.0.1:7890")
        self.proxy_all_edit = QLineEdit()
        self.proxy_all_edit.setPlaceholderText("socks5://127.0.0.1:7890")
        self.proxy_no_edit = QLineEdit()
        self.proxy_no_edit.setPlaceholderText("127.0.0.1,localhost,::1")
        self.proxy_electron_edit = QLineEdit()
        self.proxy_electron_edit.setPlaceholderText("http=127.0.0.1:7890;https=127.0.0.1:7890")
        form.addRow("HTTP Proxy", self.proxy_http_edit)
        form.addRow("HTTPS Proxy", self.proxy_https_edit)
        form.addRow("ALL Proxy", self.proxy_all_edit)
        form.addRow("NO Proxy", self.proxy_no_edit)
        form.addRow("--proxy-server", self.proxy_electron_edit)
        p_lay.addLayout(p_hdr)
        p_lay.addWidget(self.proxy_enabled_chk)
        p_lay.addLayout(form)
        body_lay.addWidget(p_card)

        # Card 3: Window & Appearance
        w_card = QFrame()
        w_card.setObjectName("WhiteCard")
        w_lay = QVBoxLayout(w_card)
        w_lay.setContentsMargins(20, 18, 20, 18)
        w_lay.setSpacing(10)
        w_t = QLabel("窗口与生命周期")
        w_t.setObjectName("CardTitle")
        self.tray_close_chk = QCheckBox("关闭窗口时最小化到系统托盘")
        self.tray_close_chk.setChecked(self._minimize_to_tray)
        self.auto_cleanup_chk = QCheckBox("Antigravity 退出后自动清理残留伴生进程 (Sidecar / language_server)")
        self.auto_cleanup_chk.setChecked(True)
        self.stop_plugins_on_exit_chk = QCheckBox("Antigravity 退出时同步停止全部托管插件")
        self.stop_plugins_on_exit_chk.setChecked(True)
        w_lay.addWidget(w_t)
        w_lay.addWidget(self.tray_close_chk)
        w_lay.addWidget(self.auto_cleanup_chk)
        w_lay.addWidget(self.stop_plugins_on_exit_chk)
        body_lay.addWidget(w_card)

        body_lay.addStretch(1)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)
        return page

    # ------------------------------------------------------------------
    # Page 7 & 8: Clean Secondary Detail Views
    # ------------------------------------------------------------------
    def _build_external_detail_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        top = QFrame()
        top.setObjectName("WhiteCard")
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(18, 12, 18, 12)
        back_btn = QPushButton("← 返回我的插件")
        back_btn.setObjectName("BackLinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self._switch_tab(PAGE_EXTERNAL))

        self.det_edit_btn = QPushButton("编辑配置")
        self.det_edit_btn.clicked.connect(self._detail_edit_plugin)
        self.det_del_btn = QPushButton("移除")
        self.det_del_btn.setObjectName("DangerGhostButton")
        self.det_del_btn.clicked.connect(self._detail_delete_plugin)

        top_lay.addWidget(back_btn)
        top_lay.addStretch(1)
        top_lay.addWidget(self.det_edit_btn)
        top_lay.addWidget(self.det_del_btn)
        lay.addWidget(top)

        card = QFrame()
        card.setObjectName("WhiteCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(26, 24, 26, 24)
        c_lay.setSpacing(20)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.det_icon_lbl = QLabel()
        self.det_icon_lbl.setFixedSize(56, 56)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        self.det_title_lbl = QLabel("")
        self.det_title_lbl.setObjectName("PageTitle")
        self.det_desc_lbl = QLabel("")
        self.det_desc_lbl.setObjectName("MutedLabel")
        self.det_desc_lbl.setWordWrap(True)
        self.det_status_lbl = QLabel("")
        hero_text.addWidget(self.det_title_lbl)
        hero_text.addWidget(self.det_desc_lbl)
        hero_text.addWidget(self.det_status_lbl)

        hero.addWidget(self.det_icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        hero.addLayout(hero_text, 1)
        c_lay.addLayout(hero)

        act_row = QHBoxLayout()
        act_row.setSpacing(10)
        self.det_start_btn = QPushButton("启动")
        self.det_start_btn.setObjectName("PrimaryButton")
        self.det_start_btn.clicked.connect(lambda: self._detail_plugin_action("start"))

        self.det_restart_btn = QPushButton("重启")
        self.det_restart_btn.clicked.connect(lambda: self._detail_plugin_action("restart"))

        self.det_stop_btn = QPushButton("停止")
        self.det_stop_btn.clicked.connect(lambda: self._detail_plugin_action("stop"))

        self.det_logs_btn = QPushButton("实时日志")
        self.det_logs_btn.clicked.connect(self._detail_open_log)

        act_row.addWidget(self.det_start_btn)
        act_row.addWidget(self.det_restart_btn)
        act_row.addWidget(self.det_stop_btn)
        act_row.addWidget(self.det_logs_btn)
        act_row.addStretch(1)
        c_lay.addLayout(act_row)

        spec_box = QFrame()
        spec_box.setObjectName("SoftInsetBox")
        spec_form = QFormLayout(spec_box)
        spec_form.setContentsMargins(18, 16, 18, 16)
        spec_form.setSpacing(11)
        self.det_id_val = QLabel("-")
        self.det_id_val.setObjectName("MonoLabel")
        self.det_ver_val = QLabel("-")
        self.det_ver_val.setObjectName("MonoLabel")
        self.det_type_val = QLabel("-")
        self.det_type_val.setObjectName("MonoLabel")
        self.det_cmd_val = QLabel("-")
        self.det_cmd_val.setObjectName("MonoLabel")
        self.det_cmd_val.setWordWrap(True)
        self.det_health_val = QLabel("-")
        self.det_health_val.setObjectName("MutedLabel")
        self.det_exe_val = QLabel("-")
        self.det_exe_val.setObjectName("MutedLabel")

        spec_form.addRow("插件 ID", self.det_id_val)
        spec_form.addRow("当前版本", self.det_ver_val)
        spec_form.addRow("运行类型", self.det_type_val)
        spec_form.addRow("命令状态", self.det_exe_val)
        spec_form.addRow("健康监测", self.det_health_val)
        spec_form.addRow("启动命令", self.det_cmd_val)
        c_lay.addWidget(spec_box)
        c_lay.addStretch(1)
        lay.addWidget(card, 1)
        return page

    def _build_native_detail_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        top = QFrame()
        top.setObjectName("WhiteCard")
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(18, 12, 18, 12)
        back_btn = QPushButton("← 返回原生扩展")
        back_btn.setObjectName("BackLinkButton")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self._switch_tab(PAGE_NATIVE))
        top_lay.addWidget(back_btn)
        top_lay.addStretch(1)
        lay.addWidget(top)

        card = QFrame()
        card.setObjectName("WhiteCard")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(26, 24, 26, 24)
        c_lay.setSpacing(20)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.nat_det_icon = QLabel()
        self.nat_det_icon.setFixedSize(56, 56)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(4)
        self.nat_det_title = QLabel("")
        self.nat_det_title.setObjectName("PageTitle")
        self.nat_det_desc = QLabel("")
        self.nat_det_desc.setObjectName("MutedLabel")
        self.nat_det_desc.setWordWrap(True)
        self.nat_det_status = QLabel("")
        hero_text.addWidget(self.nat_det_title)
        hero_text.addWidget(self.nat_det_desc)
        hero_text.addWidget(self.nat_det_status)

        hero.addWidget(self.nat_det_icon, 0, Qt.AlignmentFlag.AlignTop)
        hero.addLayout(hero_text, 1)
        c_lay.addLayout(hero)

        spec_box = QFrame()
        spec_box.setObjectName("SoftInsetBox")
        spec_form = QFormLayout(spec_box)
        spec_form.setContentsMargins(18, 16, 18, 16)
        spec_form.setSpacing(11)
        self.nat_det_dir = QLabel("-")
        self.nat_det_dir.setObjectName("MonoLabel")
        self.nat_det_ver = QLabel("-")
        self.nat_det_ver.setObjectName("MonoLabel")
        self.nat_det_caps = QLabel("-")
        self.nat_det_caps.setObjectName("MutedLabel")

        spec_form.addRow("目录", self.nat_det_dir)
        spec_form.addRow("版本", self.nat_det_ver)
        spec_form.addRow("组件", self.nat_det_caps)
        c_lay.addWidget(spec_box)
        c_lay.addStretch(1)
        lay.addWidget(card, 1)
        return page

    def _build_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip("AGY Plugin Manager")
        menu = QMenu()

        act_launch = QAction("唤醒 Antigravity", self)
        act_launch.triggered.connect(self._quick_launch)
        act_show = QAction("打开主窗口", self)
        act_show.triggered.connect(self.show_and_raise)
        act_attach = QAction("热附着插件", self)
        act_attach.triggered.connect(self._attach_enabled)
        act_stop = QAction("停止全部扩展", self)
        act_stop.triggered.connect(self._stop_all_plugins)
        act_cleanup = QAction("清理残留进程", self)
        act_cleanup.triggered.connect(self._cleanup_residuals)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit_completely)

        menu.addAction(act_launch)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_attach)
        menu.addAction(act_stop)
        menu.addAction(act_cleanup)
        menu.addSeparator()
        menu.addAction(act_quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    # ------------------------------------------------------------------
    # Theme, Titlebar, Floating Toast & Lifecycle
    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        is_dark = resolve_is_dark(self._theme_mode)
        self.theme_btn.setText(THEME_LABELS[self._theme_mode])
        app = QApplication.instance()
        if app:
            assets_root = Path(getattr(self.manager.paths, "assets_dir", self.manager.base_dir))
            app.setStyleSheet(build_stylesheet(is_dark, assets_dir=assets_root))
        for sw in self._switches:
            sw.set_dark_mode(is_dark)
        if hasattr(self, "storage_treemap"):
            self.storage_treemap.set_theme(is_dark)
        if hasattr(self, "_update_banner_shadow"):
            self._update_banner_shadow.setColor(QColor(0, 0, 0, 120 if is_dark else 42))
        apply_dwm_titlebar_theme(self, is_dark)
        if self._overview:
            self._render_overview()
        if self._storage_snapshot is not None:
            self._render_storage_view()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        apply_dwm_titlebar_theme(self, resolve_is_dark(self._theme_mode))
        self._position_update_banner()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._position_toast()
        self._position_update_banner()

    def _build_floating_update_banner(self) -> None:
        self.update_banner = QFrame(self)
        self.update_banner.setObjectName("FloatingUpdateCard")
        self.update_banner.setFixedWidth(332)
        shadow = QGraphicsDropShadowEffect(self.update_banner)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 42))
        self._update_banner_shadow = shadow
        self.update_banner.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self.update_banner)
        lay.setContentsMargins(16, 14, 14, 14)
        lay.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.setSpacing(8)
        self.update_badge_lbl = QLabel("发现新版本")
        self.update_badge_lbl.setObjectName("PillOk")
        self.update_close_btn = QPushButton("×")
        self.update_close_btn.setObjectName("FloatingCloseBtn")
        self.update_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_close_btn.setToolTip("关闭提示")
        self.update_close_btn.clicked.connect(self._dismiss_update_banner)
        hdr.addWidget(self.update_badge_lbl)
        hdr.addStretch(1)
        hdr.addWidget(self.update_close_btn)

        self.update_title_lbl = QLabel("")
        self.update_title_lbl.setObjectName("FloatingUpdateTitle")
        self.update_title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.update_title_lbl.setWordWrap(True)

        self.update_body_lbl = QLabel("")
        self.update_body_lbl.setObjectName("FloatingUpdateBody")
        self.update_body_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.update_body_lbl.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.update_dismiss_btn = QPushButton("暂不更新")
        self.update_dismiss_btn.setObjectName("LinkButton")
        self.update_dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_dismiss_btn.clicked.connect(self._dismiss_update_banner)
        self.update_now_btn = QPushButton("立即更新")
        self.update_now_btn.setObjectName("PrimaryButton")
        self.update_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_now_btn.clicked.connect(self._open_update_website)
        actions.addWidget(self.update_dismiss_btn)
        actions.addStretch(1)
        actions.addWidget(self.update_now_btn)

        lay.addLayout(hdr)
        lay.addWidget(self.update_title_lbl)
        lay.addWidget(self.update_body_lbl)
        lay.addLayout(actions)
        self.update_banner.hide()

    def _position_update_banner(self) -> None:
        if not hasattr(self, "update_banner"):
            return
        self.update_banner.adjustSize()
        x = max(24, self.width() - self.update_banner.width() - 32)
        y = 66
        self.update_banner.move(x, y)

    def _show_update_banner(self, result: dict[str, Any]) -> None:
        self._latest_update_info = dict(result)
        latest = str(result.get("latestVersion") or "").strip()
        prompt = result.get("prompt") if isinstance(result.get("prompt"), dict) else {}
        title = str(prompt.get("title") or "").strip() or (
            f"AGY Plugin Manager v{latest} 已发布" if latest else "发现新版本"
        )
        body = str(prompt.get("body") or "").strip() or "前往 HaoAn Lab 官网查看更新日志并获取最新版本。"
        changelog = str(result.get("changelog") or "").strip()
        if changelog and changelog not in body:
            first_lines = [line.strip() for line in changelog.splitlines() if line.strip()][:2]
            if first_lines:
                body = f"{body}\n" + " · ".join(first_lines)
        update_url = str(result.get("updateUrl") or "").strip()
        if update_url:
            try:
                validate_update_site_url(update_url)
                self._current_update_url = update_url
            except Exception:
                pass
        self.update_badge_lbl.setText(f"新版本 v{latest}" if latest else "发现新版本")
        self.update_title_lbl.setText(title)
        self.update_body_lbl.setText(body)
        self.update_now_btn.setText("立即更新")
        self.update_banner.adjustSize()
        self._position_update_banner()
        self.update_banner.show()
        self.update_banner.raise_()

    def _dismiss_update_banner(self) -> None:
        if hasattr(self, "update_banner"):
            self.update_banner.hide()

    def _ensure_default_shortcuts(self) -> None:
        self._run_async(
            self.manager.ensure_default_shortcuts_once,
            lambda _res: None,
            lambda _err: None,
        )

    def _open_update_website(self) -> None:
        target = self._current_update_url or "https://ahmustudyhelper.xyz"
        try:
            parsed = QUrl(validate_update_site_url(target))
        except Exception:
            parsed = QUrl("https://ahmustudyhelper.xyz")
        QDesktopServices.openUrl(parsed)

    def _check_for_updates(self, manual: bool = False) -> None:
        if self._update_check_in_flight:
            return
        self._update_check_in_flight = True
        if hasattr(self, "check_update_btn"):
            self.check_update_btn.setEnabled(False)
            self.check_update_btn.setText("检查中...")
        if hasattr(self, "update_status_lbl") and manual:
            self._set_dot(self.update_status_lbl, "muted", "正在连接官网检查更新...")

        def run() -> dict[str, Any]:
            return self.manager.check_for_updates()

        def done(result: dict[str, Any]) -> None:
            self._update_check_in_flight = False
            if hasattr(self, "check_update_btn"):
                self.check_update_btn.setEnabled(True)
                self.check_update_btn.setText("检查更新")
            self._handle_update_check_result(result, manual=manual)

        def fail(err: str) -> None:
            self._update_check_in_flight = False
            if hasattr(self, "check_update_btn"):
                self.check_update_btn.setEnabled(True)
                self.check_update_btn.setText("检查更新")
            if hasattr(self, "update_status_lbl"):
                tone = "warn" if manual else "muted"
                self._set_dot(self.update_status_lbl, tone, "暂无法连接更新服务")
            if manual:
                self._notify_error(err)

        self._run_async(run, done, fail)

    def _handle_update_check_result(self, result: dict[str, Any], *, manual: bool) -> None:
        status = str(result.get("status") or "")
        msg = str(result.get("message") or "").strip()
        update_url = str(result.get("updateUrl") or "").strip()
        if update_url:
            try:
                validate_update_site_url(update_url)
                self._current_update_url = update_url
            except Exception:
                pass

        if result.get("hasUpdate"):
            latest = str(result.get("latestVersion") or "").strip()
            if hasattr(self, "update_status_lbl"):
                self._set_dot(self.update_status_lbl, "ok", f"发现新版本 v{latest}")
            self._show_update_banner(result)
            return

        if status == "ok":
            if hasattr(self, "update_status_lbl"):
                self._set_dot(self.update_status_lbl, "ok", msg or f"已是最新版本 (v{APP_VERSION})")
            self._dismiss_update_banner()
            if manual:
                self._show_toast(msg or "当前已是最新版本")
            return

        if status == "unpublished":
            if hasattr(self, "update_status_lbl"):
                self._set_dot(self.update_status_lbl, "muted", msg or "官网暂未发布新版本")
            if manual:
                self._show_toast(msg or "官网暂未发布新版本")
            return

        # Network or response error: never disrupt normal usage; notify toast only on manual trigger.
        if hasattr(self, "update_status_lbl"):
            self._set_dot(self.update_status_lbl, "warn" if manual else "muted", "暂无法连接更新服务")
        if manual:
            self._show_toast(msg or "检查更新失败")
        else:
            self.manager.log(f"启动自动检查更新未完成（已跳过，不影响正常使用）: {msg or 'network unavailable'}")

    def _position_toast(self) -> None:
        if not hasattr(self, "toast_lbl"):
            return
        self.toast_lbl.adjustSize()
        x = max(24, self.width() - self.toast_lbl.width() - 32)
        y = max(24, self.height() - self.toast_lbl.height() - 28)
        self.toast_lbl.move(x, y)

    def _cycle_theme(self) -> None:
        idx = THEME_MODES.index(self._theme_mode)
        self._theme_mode = THEME_MODES[(idx + 1) % len(THEME_MODES)]
        self._apply_theme()
        try:
            self.manager.save_ui_preferences(theme=self._theme_mode)
        except Exception:
            pass

    def _show_toast(self, message: str) -> None:
        self.toast_lbl.setText(message)
        self.toast_lbl.adjustSize()
        self._position_toast()
        self.toast_lbl.show()
        self.toast_lbl.raise_()
        self._toast_timer.start(2600)

    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        apply_dwm_titlebar_theme(self, resolve_is_dark(self._theme_mode))

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_and_raise()

    def stop_background_timers(self) -> None:
        self._overview_timer.stop()
        self._log_timer.stop()
        self._toast_timer.stop()
        for t in self._startup_timers:
            t.stop()

    def _quit_completely(self) -> None:
        self._force_quit = True
        self.stop_background_timers()
        self.tray_icon.hide()
        self.thread_pool.waitForDone(2000)
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._force_quit and self._minimize_to_tray and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray_icon.showMessage(
                    "AGY Plugin Manager",
                    "已最小化到系统托盘，双击图标可恢复窗口。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000,
                )
            return
        self.stop_background_timers()
        self.tray_icon.hide()
        self.thread_pool.waitForDone(2000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Async Worker & Navigation
    # ------------------------------------------------------------------
    def _run_async(
        self,
        fn: Callable[[], Any],
        on_ok: Callable[[Any], None],
        on_err: Callable[[str], None] | None = None,
    ) -> None:
        worker = TaskWorker(fn)
        worker.signals.setParent(self)
        worker.signals.finished.connect(on_ok)
        worker.signals.failed.connect(on_err or self._notify_error)
        self.thread_pool.start(worker)

    def _notify_error(self, message: str) -> None:
        first_line = message.splitlines()[0] if message else "未知错误"
        self._show_toast(f"失败：{first_line}")

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        active_nav = PAGE_EXTERNAL if index == PAGE_EXT_DETAIL else (PAGE_NATIVE if index == PAGE_NAT_DETAIL else index)
        for i, btn in enumerate(self.tab_buttons):
            btn.setChecked(i == active_nav)

        self.top_action_btn.setText("刷新状态" if index == PAGE_STATUS else "唤醒 Antigravity")

        if index == PAGE_STORAGE and self._storage_snapshot is None and not self._storage_scanning:
            self._refresh_storage_scan()

        if index == PAGE_LOGS and self._log_streaming:
            self.refresh_logs()
            self._log_timer.start()
        else:
            self._log_timer.stop()

    def _set_plugin_filter(self, key: str) -> None:
        self._plugin_filter = key
        for k, chip in self.filter_chips.items():
            chip.setProperty("active", k == key)
            chip.style().unpolish(chip)
            chip.style().polish(chip)
        self._re_render_external()

    # ------------------------------------------------------------------
    # Data Refresh & Rendering
    # ------------------------------------------------------------------
    def refresh_all(self, notify: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True

        def load() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            return self.manager.get_overview(), self.manager.list_native_plugins()

        def done(payload: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
            self._refreshing = False
            self._overview, self._native_plugins = payload
            self._render_overview()
            self._render_native_plugins()
            if notify:
                self._show_toast("状态已更新")

        def fail(err: str) -> None:
            self._refreshing = False
            self._notify_error(err)

        self._run_async(load, done, fail)

    @staticmethod
    def _set_dot(lbl: QLabel, tone: str, text: str) -> None:
        obj_map = {"ok": "DotOk", "warn": "DotWarn", "muted": "DotMuted"}
        lbl.setObjectName(obj_map.get(tone, "DotMuted"))
        lbl.setText(text)
        lbl.style().unpolish(lbl)
        lbl.style().polish(lbl)

    def _clear_vbox(self, lay: QVBoxLayout, clear_switches: bool = False) -> None:
        if clear_switches:
            self._switches.clear()
        while lay.count():
            item = lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                sub = item.layout()
                while sub.count():
                    sub_item = sub.takeAt(0)
                    if sub_item.widget() is not None:
                        sub_item.widget().hide()
                        sub_item.widget().setParent(None)
                        sub_item.widget().deleteLater()

    def _render_overview(self) -> None:
        ov = self._overview
        if not ov:
            return

        is_dark = resolve_is_dark(self._theme_mode)
        cdp = ov.get("cdp") or {}
        main_cnt = int(cdp.get("mainProcessCount") or 0)
        sidecar_cnt = int(cdp.get("sidecarProcessCount") or 0)
        port = int(cdp.get("port") or 0)
        cdp_ready = bool(cdp.get("ready"))
        plugins = ov.get("plugins") or []
        natives = self._native_plugins or []

        running_plugins = [p for p in plugins if p.get("running")]
        nat_enabled = sum(1 for n in natives if n.get("enabled"))

        # Update top capsule tab counters concisely
        self.tab_buttons[1].setText(f"我的插件 {len(plugins)}")
        self.tab_buttons[3].setText(f"原生 {len(natives)}")

        # 1. Hero Banner
        if cdp_ready:
            self.hero_badge.set_state("ok", is_dark)
            self.hero_title_lbl.setText("Antigravity 已连接")
            self.hero_sub_lbl.setText(f"端口 {port} 监听中 · {main_cnt} 主窗口 · {sidecar_cnt} 伴生服务")
            self.quick_launch_btn.setText("唤醒主窗口")
        elif main_cnt > 0:
            self.hero_badge.set_state("warn", is_dark)
            self.hero_title_lbl.setText("Antigravity 正在准备")
            self.hero_sub_lbl.setText(f"{main_cnt} 主窗口运行中，等待调试通道就绪")
            self.quick_launch_btn.setText("唤醒主窗口")
        else:
            self.hero_badge.set_state("muted", is_dark)
            self.hero_title_lbl.setText("Antigravity 未运行" if sidecar_cnt == 0 else "Antigravity 后台驻留")
            self.hero_sub_lbl.setText(
                "点击右侧一键启动并挂载已启用扩展" if sidecar_cnt == 0 else f"检测到 {sidecar_cnt} 个后台进程"
            )
            self.quick_launch_btn.setText("启动 Antigravity")

        # 2. Topology & Metrics
        self.topology_widget.update_state(
            is_dark=is_dark,
            cdp_ready=cdp_ready,
            port=port,
            main_cnt=main_cnt,
            ext_running=len(running_plugins),
            ext_total=len(plugins),
            nat_enabled=nat_enabled,
            nat_total=len(natives),
        )
        self.metric_port_val.setText(str(port) if cdp_ready and port else "未连接")
        self.metric_sidecar_val.setText(f"{sidecar_cnt} 进程")
        self.metric_dll_val.setText("已就绪" if ov.get("versionDllExists") else "未检测到")
        total_mem = int(ov.get("totalPluginMemoryBytes") or 0)
        if total_mem <= 0 and running_plugins:
            total_mem = sum(int(p.get("memoryBytes") or 0) for p in running_plugins)
        self.metric_plugin_mem_val.setText(
            format_bytes(total_mem) if total_mem > 0 else ("运行中" if running_plugins else "0 B")
        )

        # 3. Active Spotlight
        self.active_ratio_lbl.setText(
            f"{len(running_plugins)} / {len(plugins)} · {format_bytes(total_mem)}"
            if total_mem > 0
            else f"{len(running_plugins)} / {len(plugins)}"
        )
        self._render_home_active(running_plugins)

        # 4. Dependent pages
        self._render_external_plugins(plugins)
        self._render_marketplace()
        self._sync_log_sources(plugins)
        self._sync_settings_form(
            ov.get("proxy") or {},
            ov.get("lifecycle") or {},
            antigravity_exe=str(ov.get("antigravityExe") or ""),
            antigravity_exists=bool(ov.get("antigravityExists")),
        )
        if self.stack.currentIndex() == PAGE_EXT_DETAIL and self._selected_plugin_id:
            self._populate_external_detail(self._selected_plugin_id)

        # 5. Lifecycle auto-cleanup watcher (Antigravity main exit -> clean residuals & plugins)
        self._handle_exit_lifecycle(main_cnt, sidecar_cnt, len(running_plugins), ov.get("lifecycle") or {})

    def _render_home_active(self, running_plugins: list[dict[str, Any]]) -> None:
        self._clear_vbox(self.home_active_list)
        if not running_plugins:
            empty_box = QFrame()
            empty_box.setObjectName("SoftInsetBox")
            e_lay = QVBoxLayout(empty_box)
            e_lay.setContentsMargins(16, 26, 16, 26)
            e_lay.setSpacing(6)
            lbl = QLabel("当前无活跃扩展")
            lbl.setObjectName("MutedLabel")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e_lay.addWidget(lbl)
            self.home_active_list.addWidget(empty_box)
            self.home_active_list.addStretch(1)
            return

        for p in running_plugins:
            tile = ClickableRow("ActivePluginTile")
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tile.clicked.connect(lambda pid=p["id"]: self._open_external_detail(pid))

            row_lay = QHBoxLayout(tile)
            row_lay.setContentsMargins(13, 11, 13, 11)
            row_lay.setSpacing(12)

            ico = QLabel()
            ico.setFixedSize(34, 34)
            ico.setPixmap(
                render_svg_pixmap(plugin_graphic_svg(p["id"], p.get("type") or "", p.get("name") or ""), logical_px=34)
            )
            row_lay.addWidget(ico)

            info = QVBoxLayout()
            info.setSpacing(2)
            name_lbl = self._row_label(p.get("name") or p["id"], "CardTitle")
            pids = p.get("pids") or []
            mem_bytes = int(p.get("memoryBytes") or 0)
            mem_suffix = f" · 内存 {format_bytes(mem_bytes)}" if mem_bytes > 0 else ""
            pid_text = f"进程 {', '.join(map(str, pids))}{mem_suffix}" if pids else f"运行中{mem_suffix}"
            pid_lbl = self._row_label(pid_text, "DotOk")
            info.addWidget(name_lbl)
            info.addWidget(pid_lbl)
            row_lay.addLayout(info, 1)

            stop_btn = QPushButton("停止")
            stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            stop_btn.clicked.connect(lambda _=False, pid=p["id"]: self._plugin_action(pid, "stop"))
            row_lay.addWidget(stop_btn)

            self.home_active_list.addWidget(tile)

        self.home_active_list.addStretch(1)

    def _re_render_external(self) -> None:
        plugins = (self._overview or {}).get("plugins") or []
        self._render_external_plugins(plugins)

    def _render_external_plugins(self, plugins: list[dict[str, Any]]) -> None:
        is_dark = resolve_is_dark(self._theme_mode)
        query = self.ext_search.text().strip().lower() if hasattr(self, "ext_search") else ""

        filtered: list[dict[str, Any]] = []
        for p in plugins:
            running = bool(p.get("running"))
            if self._plugin_filter == "running" and not running:
                continue
            if self._plugin_filter == "idle" and running:
                continue
            if query:
                hay = f"{p.get('id', '')} {p.get('name', '')} {p.get('version', '')} {p.get('description', '')}".lower()
                if query not in hay:
                    continue
            filtered.append(p)

        self._clear_vbox(self.external_list, clear_switches=True)
        if not filtered:
            empty = QLabel("未找到匹配的扩展" if plugins else "暂无已安装扩展，可点击「+ 导入插件」")
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 56, 0, 56)
            self.external_list.addWidget(empty)
            self.external_list.addStretch(1)
            return

        for p in filtered:
            row = ClickableRow("PluginItemRow")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.clicked.connect(lambda pid=p["id"]: self._open_external_detail(pid))
            lay = QHBoxLayout(row)
            lay.setContentsMargins(16, 13, 16, 13)
            lay.setSpacing(14)

            ico = QLabel()
            ico.setFixedSize(36, 36)
            ico.setPixmap(
                render_svg_pixmap(plugin_graphic_svg(p["id"], p.get("type") or "", p.get("name") or ""), logical_px=36)
            )
            lay.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)

            info = QVBoxLayout()
            info.setSpacing(2)
            title_row = self._make_title_version_row(p.get("name") or p["id"], p.get("version"))
            desc_lbl = self._row_label(p.get("description") or "外部扩展", "MutedLabel", word_wrap=True)
            info.addLayout(title_row)
            info.addWidget(desc_lbl)
            lay.addLayout(info, 1)

            type_lbl = QLabel(str(p.get("type") or "custom-cdp"))
            type_lbl.setObjectName("FaintLabel")
            type_lbl.setFixedWidth(92)
            lay.addWidget(type_lbl)

            pids = p.get("pids") or []
            mem_bytes = int(p.get("memoryBytes") or 0)
            running = bool(p.get("running"))
            enabled = p.get("enabled", True) is not False
            status_pill = QLabel()
            status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_pill.setFixedWidth(142)
            if running:
                status_pill.setObjectName("PillOk")
                if mem_bytes > 0:
                    status_pill.setText(f"● {pids[0]} · {format_bytes(mem_bytes)}" if pids else f"● {format_bytes(mem_bytes)}")
                else:
                    status_pill.setText(f"● 运行 {pids[0]}" if pids else "● 运行中")
            elif enabled:
                status_pill.setObjectName("PillMuted")
                status_pill.setText("○ 待命")
            else:
                status_pill.setObjectName("PillWarn")
                status_pill.setText("已禁用")
            lay.addWidget(status_pill, 0, Qt.AlignmentFlag.AlignVCenter)

            lay.addSpacing(8)
            toggle = ToggleSwitch(checked=enabled, is_dark=is_dark)
            toggle.toggled.connect(lambda state, pid=p["id"]: self._toggle_plugin(pid, state))
            self._switches.append(toggle)
            lay.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)

            lay.addSpacing(6)
            det_btn = QPushButton("详情")
            det_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            det_btn.clicked.connect(lambda _=False, pid=p["id"]: self._open_external_detail(pid))
            lay.addWidget(det_btn, 0, Qt.AlignmentFlag.AlignVCenter)

            self.external_list.addWidget(row)

        self.external_list.addStretch(1)

    def _discover_local_plugin_dirs(self) -> list[dict[str, str]]:
        """Scans AGY-Launcher/plugins for local plugin directories."""
        return self.manager.discover_local_plugins((self._overview or {}).get("plugins"))

    def _render_marketplace(self) -> None:
        if not hasattr(self, "market_list"):
            return
        query = self.market_search.text().strip().lower() if hasattr(self, "market_search") else ""
        items = self._discover_local_plugin_dirs()
        if query:
            items = [
                x
                for x in items
                if query in x["displayName"].lower()
                or query in x["dir"].lower()
                or query in str(x.get("version") or "").lower()
                or query in x["desc"].lower()
            ]

        self._clear_vbox(self.market_list)
        if not items:
            empty = QLabel("未发现可接入的本地扩展包，点击右上角「+ 手动配置导入」")
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 56, 0, 56)
            self.market_list.addWidget(empty)
            self.market_list.addStretch(1)
            return

        for item in items:
            row = ClickableRow("PluginItemRow")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(14)

            ico = QLabel()
            ico.setFixedSize(36, 36)
            ico.setPixmap(render_svg_pixmap(plugin_graphic_svg(item["dir"], "", item["displayName"]), logical_px=36))
            lay.addWidget(ico)

            info = QVBoxLayout()
            info.setSpacing(2)
            title_row = self._make_title_version_row(item["displayName"], item.get("version"))
            d_lbl = self._row_label(item["desc"], "MutedLabel", word_wrap=True)
            info.addLayout(title_row)
            info.addWidget(d_lbl)
            lay.addLayout(info, 1)

            if item["installedId"]:
                badge = QLabel("已接入")
                badge.setObjectName("PillOk")
                btn = QPushButton("管理")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, pid=item["installedId"]: self._open_external_detail(pid))
            else:
                badge = QLabel("本地包")
                badge.setObjectName("PillMuted")
                btn = QPushButton("导入")
                btn.setObjectName("PrimaryButton")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, it=item: self._open_add_plugin(
                        prefill={
                            "id": it["dir"],
                            "name": it["displayName"],
                            "version": it.get("version") or "",
                            "description": it["desc"] if it["desc"] != "发现未注册本地插件目录" else "",
                        }
                    )
                )

            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addSpacing(8)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)
            self.market_list.addWidget(row)

        self.market_list.addStretch(1)

    def _render_native_plugins(self) -> None:
        all_items = self._native_plugins or []
        if hasattr(self, "tab_buttons") and len(self.tab_buttons) > 3:
            self.tab_buttons[3].setText(f"原生 {len(all_items)}")

        query = self.native_search.text().strip().lower()
        filtered = (
            [
                p
                for p in all_items
                if query in p["name"].lower()
                or query in p["dir"].lower()
                or query in (p.get("description") or "").lower()
            ]
            if query
            else all_items
        )

        self._clear_vbox(self.native_list)
        if not filtered:
            empty = QLabel("未找到匹配的原生扩展")
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 56, 0, 56)
            self.native_list.addWidget(empty)
            self.native_list.addStretch(1)
            return

        for p in filtered:
            row = ClickableRow("NativeItemRow")
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.clicked.connect(lambda d=p["dir"]: self._open_native_detail(d))
            lay = QHBoxLayout(row)
            lay.setContentsMargins(16, 13, 16, 13)
            lay.setSpacing(14)

            ico = QLabel()
            ico.setFixedSize(36, 36)
            ico.setPixmap(render_svg_pixmap(native_graphic_svg(p["dir"]), logical_px=36))
            lay.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)

            info = QVBoxLayout()
            info.setSpacing(2)
            name_lbl = self._row_label(p["name"], "CardTitle")
            desc_lbl = self._row_label(p.get("description") or "内置扩展", "MutedLabel", word_wrap=True)
            info.addWidget(name_lbl)
            info.addWidget(desc_lbl)
            lay.addLayout(info, 1)

            skill_cnt = int(p.get("skillCount", 0))
            if skill_cnt > 0:
                cnt_lbl = QLabel(f"{skill_cnt} 技能")
                cnt_lbl.setObjectName("FaintLabel")
                lay.addWidget(cnt_lbl)
                lay.addSpacing(8)

            pill = QLabel("● 已启用" if p.get("enabled") else "已禁用")
            pill.setObjectName("PillOk" if p.get("enabled") else "PillMuted")
            lay.addWidget(pill)

            det_btn = QPushButton("详情")
            det_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            det_btn.clicked.connect(lambda _=False, d=p["dir"]: self._open_native_detail(d))
            lay.addSpacing(6)
            lay.addWidget(det_btn)

            self.native_list.addWidget(row)

        self.native_list.addStretch(1)

        if self.stack.currentIndex() == PAGE_NAT_DETAIL and self._selected_native_dir:
            self._populate_native_detail(self._selected_native_dir)

    # ------------------------------------------------------------------
    # Secondary Detail Pages (Index 7 & 8)
    # ------------------------------------------------------------------
    def _find_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        plugins = (self._overview or {}).get("plugins") or []
        for p in plugins:
            if p.get("id") == plugin_id:
                return p
        return None

    def _open_external_detail(self, plugin_id: str) -> None:
        self._selected_plugin_id = plugin_id
        self._populate_external_detail(plugin_id)
        self._switch_tab(PAGE_EXT_DETAIL)

    def _populate_external_detail(self, plugin_id: str) -> None:
        p = self._find_plugin(plugin_id)
        if not p:
            self._switch_tab(PAGE_EXTERNAL)
            return
        self.det_icon_lbl.setPixmap(
            render_svg_pixmap(plugin_graphic_svg(p["id"], p.get("type") or "", p.get("name") or ""), logical_px=56)
        )
        self.det_title_lbl.setText(p.get("name") or p["id"])
        self.det_desc_lbl.setText(p.get("description") or "外部托管插件")

        pids = p.get("pids") or []
        mem_bytes = int(p.get("memoryBytes") or 0)
        running = bool(p.get("running"))
        enabled = p.get("enabled", True) is not False
        if running:
            mem_part = f" · 内存 {format_bytes(mem_bytes)}" if mem_bytes > 0 else ""
            pid_part = f" · 进程 {', '.join(map(str, pids))}" if pids else ""
            self._set_dot(self.det_status_lbl, "ok", f"● 运行中{pid_part}{mem_part}")
        elif enabled:
            self._set_dot(self.det_status_lbl, "muted", "○ 待命")
        else:
            self._set_dot(self.det_status_lbl, "warn", "已禁用")

        self.det_start_btn.setText("运行中" if running else "启动")
        self.det_start_btn.setEnabled(not running)
        self.det_stop_btn.setEnabled(running)

        self.det_id_val.setText(p["id"])
        self.det_ver_val.setText(self._format_version_text(p.get("version")))
        self.det_type_val.setText(p.get("type") or "custom-cdp")
        self.det_exe_val.setText("可执行" if p.get("executableExists", True) else "未找到可执行文件")

        health = p.get("health")
        if isinstance(health, dict) and health.get("port"):
            self.det_health_val.setText(f"HTTP :{health['port']} 正常")
        elif health:
            self.det_health_val.setText("通过")
        else:
            self.det_health_val.setText("命令行特征监测")

        cmd_txt = f"{p.get('command', '')} {' '.join(p.get('launchArgs') or [])}".strip()
        self.det_cmd_val.setText(cmd_txt or "-")

    def _open_native_detail(self, dir_name: str) -> None:
        self._selected_native_dir = dir_name
        self._populate_native_detail(dir_name)
        self._switch_tab(PAGE_NAT_DETAIL)

    def _populate_native_detail(self, dir_name: str) -> None:
        item = next((x for x in (self._native_plugins or []) if x.get("dir") == dir_name), None)
        if not item:
            self._switch_tab(PAGE_NATIVE)
            return
        self.nat_det_icon.setPixmap(render_svg_pixmap(native_graphic_svg(dir_name), logical_px=56))
        self.nat_det_title.setText(item["name"])
        self.nat_det_desc.setText(item.get("description") or "内置原生扩展")
        self._set_dot(
            self.nat_det_status,
            "ok" if item.get("enabled") else "muted",
            "● 已启用" if item.get("enabled") else "已禁用",
        )
        self.nat_det_dir.setText(f"~/.gemini/config/plugins/{item['dir']}")
        self.nat_det_ver.setText(f"v{item.get('version', '1.0.0')}")
        caps: list[str] = [f"{item.get('skillCount', 0)} Skills"]
        if item.get("hasMcp"):
            caps.append("MCP")
        if item.get("hasRules"):
            caps.append("Rules")
        if item.get("sidecars"):
            caps.append("Sidecar")
        self.nat_det_caps.setText(" / ".join(caps))

    def _detail_plugin_action(self, action: str) -> None:
        if self._selected_plugin_id:
            self._plugin_action(self._selected_plugin_id, action)

    def _detail_open_log(self) -> None:
        if self._selected_plugin_id:
            self._open_plugin_log(self._selected_plugin_id)

    def _detail_edit_plugin(self) -> None:
        if self._selected_plugin_id:
            p = self._find_plugin(self._selected_plugin_id)
            if p:
                self._open_edit_plugin(p)

    def _detail_delete_plugin(self) -> None:
        if self._selected_plugin_id:
            self._delete_plugin(self._selected_plugin_id, return_to_list=True)

    # ------------------------------------------------------------------
    # Logs & Settings Sync
    # ------------------------------------------------------------------
    def _sync_log_sources(self, plugins: list[dict[str, Any]]) -> None:
        current_id = self.log_source_combo.currentData() or "launcher"
        desired: list[tuple[str, str]] = [("launcher.log", "launcher")]
        for p in plugins:
            desired.append((f"{p['id']}.out.log", p["id"]))
            desired.append((f"{p['id']}.err.log", f"{p['id']}.err"))

        existing = [
            (self.log_source_combo.itemText(i), self.log_source_combo.itemData(i))
            for i in range(self.log_source_combo.count())
        ]
        if existing != desired:
            self.log_source_combo.blockSignals(True)
            self.log_source_combo.clear()
            for label, val in desired:
                self.log_source_combo.addItem(label, val)
            idx = self.log_source_combo.findData(current_id)
            if idx >= 0:
                self.log_source_combo.setCurrentIndex(idx)
            self.log_source_combo.blockSignals(False)

    def _sync_settings_form(
        self,
        proxy: dict[str, Any],
        lifecycle: dict[str, Any] | None = None,
        antigravity_exe: str | None = None,
        antigravity_exists: bool | None = None,
    ) -> None:
        if self.stack.currentIndex() == PAGE_SETTINGS:
            focus = QApplication.focusWidget()
            if focus is not None and focus.window() is self:
                return
        if antigravity_exe is not None and hasattr(self, "agy_exe_edit"):
            self.agy_exe_edit.setText(str(antigravity_exe))
            self._update_agy_path_status(str(antigravity_exe), exists=antigravity_exists)
        self.proxy_enabled_chk.setChecked(bool(proxy.get("enabled")))
        self.proxy_http_edit.setText(str(proxy.get("httpProxy") or ""))
        self.proxy_https_edit.setText(str(proxy.get("httpsProxy") or ""))
        self.proxy_all_edit.setText(str(proxy.get("allProxy") or ""))
        self.proxy_no_edit.setText(str(proxy.get("noProxy") or "127.0.0.1,localhost,::1"))
        self.proxy_electron_edit.setText(str(proxy.get("electronProxyServer") or ""))
        lc = lifecycle or {}
        self.auto_cleanup_chk.setChecked(lc.get("autoCleanupOnExit", True) is not False)
        self.stop_plugins_on_exit_chk.setChecked(lc.get("stopPluginsOnExit", True) is not False)

    def _update_agy_path_status(self, exe_path: str, *, exists: bool | None = None, source: str = "") -> None:
        if not hasattr(self, "agy_path_status_lbl"):
            return
        cleaned = exe_path.strip()
        if not cleaned:
            self._set_dot(self.agy_path_status_lbl, "warn", "未配置")
            return
        is_ok = Path(cleaned).exists() if exists is None else bool(exists)
        if is_ok:
            label = f"已检测到 ({source})" if source else "路径有效"
            self._set_dot(self.agy_path_status_lbl, "ok", label)
        else:
            self._set_dot(self.agy_path_status_lbl, "warn", "文件不存在")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is getattr(self, "_external_page", None):
            etype = event.type()
            if etype == QEvent.Type.DragEnter:
                drag_evt = event  # type: ignore[assignment]
                if _extract_plugin_package_paths(drag_evt.mimeData()):
                    drag_evt.acceptProposedAction()
                    self.plugin_drop_container.set_drag_active(True)
                    return True
            elif etype == QEvent.Type.DragMove:
                drag_evt = event  # type: ignore[assignment]
                if _extract_plugin_package_paths(drag_evt.mimeData()):
                    drag_evt.acceptProposedAction()
                    return True
            elif etype == QEvent.Type.DragLeave:
                self.plugin_drop_container.set_drag_active(False)
            elif etype == QEvent.Type.Drop:
                drop_evt = event  # type: ignore[assignment]
                self.plugin_drop_container.set_drag_active(False)
                paths = _extract_plugin_package_paths(drop_evt.mimeData())
                if paths:
                    drop_evt.acceptProposedAction()
                    for pkg_path in paths:
                        self._install_plugin_package(pkg_path)
                    return True
        return super().eventFilter(watched, event)

    def _handle_exit_lifecycle(
        self,
        main_cnt: int,
        sidecar_cnt: int,
        running_plugin_cnt: int,
        lifecycle: dict[str, Any],
    ) -> None:
        if main_cnt > 0:
            self._saw_antigravity_main = True
            self._exit_zero_streak = 0
            return
        if not self._saw_antigravity_main or self._cleanup_in_flight:
            return
        if lifecycle.get("autoCleanupOnExit", True) is False:
            self._saw_antigravity_main = False
            self._exit_zero_streak = 0
            return

        self._exit_zero_streak += 1
        if self._exit_zero_streak == 1:
            QTimer.singleShot(2000, self.refresh_all)
            return

        self._saw_antigravity_main = False
        self._exit_zero_streak = 0
        if sidecar_cnt == 0 and running_plugin_cnt == 0:
            return

        self._cleanup_in_flight = True

        def done(res: dict[str, Any]) -> None:
            self._cleanup_in_flight = False
            if not res.get("skipped"):
                killed_cnt = len(res.get("killedPids") or [])
                self._show_toast(f"Antigravity 已退出，已清理 {killed_cnt} 个残留进程并停止插件")
                self.refresh_all()

        def fail(_err: str) -> None:
            self._cleanup_in_flight = False

        self._run_async(self.manager.cleanup_antigravity_residuals, done, fail)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _quick_launch(self) -> None:
        self.quick_launch_btn.setEnabled(False)
        self._show_toast("正在启动并挂载插件...")

        def run() -> dict[str, Any]:
            return self.manager.launch_antigravity_and_attach(focus_if_running=True)

        def done(res: dict[str, Any]) -> None:
            self.quick_launch_btn.setEnabled(True)
            errors = [item for item in (res.get("results") or []) if item.get("status") == "error"]
            if errors:
                err_summary = "; ".join(f"{e.get('id')}: {e.get('error')}" for e in errors[:2])
                self._show_toast("Antigravity 已启动（部分插件失败）")
                QMessageBox.warning(self, "部分插件启动失败", err_summary)
            else:
                self._show_toast("Antigravity 已就绪")
            self.refresh_all()

        def fail(err: str) -> None:
            self.quick_launch_btn.setEnabled(True)
            QMessageBox.warning(self, "启动失败", err)
            self._notify_error(err)
            self.refresh_all()

        self._run_async(run, done, fail)

    def _attach_enabled(self) -> None:
        self.home_attach_btn.setEnabled(False)
        if hasattr(self, "attach_btn"):
            self.attach_btn.setEnabled(False)
        self._show_toast("正在热附着插件...")

        def done(res: Any) -> None:
            self.home_attach_btn.setEnabled(True)
            if hasattr(self, "attach_btn"):
                self.attach_btn.setEnabled(True)
            errors = [item for item in (res if isinstance(res, list) else []) if isinstance(item, dict) and item.get("status") == "error"]
            if errors:
                err_summary = "; ".join(f"{e.get('id')}: {e.get('error')}" for e in errors[:2])
                self._show_toast("热附着完成（存在失败）")
                QMessageBox.warning(self, "部分插件热附着失败", err_summary)
            else:
                self._show_toast("热附着完成")
            self.refresh_all()

        def fail(err: str) -> None:
            self.home_attach_btn.setEnabled(True)
            if hasattr(self, "attach_btn"):
                self.attach_btn.setEnabled(True)
            self._notify_error(err)
            self.refresh_all()

        self._run_async(self.manager.attach_enabled_plugins, done, fail)

    def _stop_all_plugins(self) -> None:
        self._show_toast("正在停止全部插件...")
        self._run_async(
            self.manager.stop_all_plugins,
            lambda _res: (self._show_toast("已停止全部插件"), self.refresh_all()),
        )

    def _cleanup_residuals(self) -> None:
        self._show_toast("正在检查并清理残留进程...")

        def done(res: dict[str, Any]) -> None:
            if res.get("skipped"):
                self._show_toast(str(res.get("reason") or "Antigravity 主窗口仍在运行，已跳过"))
            else:
                killed = len(res.get("killedPids") or [])
                self._show_toast(f"已清理 {killed} 个残留进程并停止全部插件")
            self.refresh_all()

        self._run_async(self.manager.cleanup_antigravity_residuals, done)

    def _toggle_plugin(self, plugin_id: str, enabled: bool) -> None:
        self._run_async(
            lambda: self.manager.toggle_plugin(plugin_id, enabled),
            lambda _res: (self._show_toast(f"{plugin_id} 已{'启用' if enabled else '禁用'}"), self.refresh_all()),
        )

    def _plugin_action(self, plugin_id: str, action: str) -> None:
        def op() -> Any:
            if action == "start":
                return self.manager.start_plugin(plugin_id, "attach")
            if action == "stop":
                return self.manager.stop_plugin(plugin_id)
            return self.manager.restart_plugin(plugin_id)

        label_map = {"start": "已启动", "stop": "已停止", "restart": "已重启"}
        self._run_async(
            op,
            lambda _res: (self._show_toast(f"{plugin_id} {label_map[action]}"), self.refresh_all()),
        )

    def _open_plugin_log(self, plugin_id: str) -> None:
        idx = self.log_source_combo.findData(plugin_id)
        if idx >= 0:
            self.log_source_combo.setCurrentIndex(idx)
        self._switch_tab(PAGE_LOGS)

    def _open_add_plugin(self, prefill: dict[str, Any] | None = None) -> None:
        dlg = PluginEditorDialog(self, plugin=None, theme_mode=self._theme_mode)
        if prefill:
            dlg.id_edit.setText(str(prefill.get("id") or ""))
            dlg.name_edit.setText(str(prefill.get("name") or ""))
        if dlg.exec() == PluginEditorDialog.DialogCode.Accepted:
            try:
                self.manager.save_plugin_entry("create", dlg.payload())
                self._show_toast("已保存新插件")
                self.refresh_all()
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))

    def _open_edit_plugin(self, plugin: dict[str, Any]) -> None:
        dlg = PluginEditorDialog(self, plugin=plugin, theme_mode=self._theme_mode)
        if dlg.exec() == PluginEditorDialog.DialogCode.Accepted:
            try:
                self.manager.save_plugin_entry("edit", dlg.payload())
                self._show_toast("配置已更新")
                self.refresh_all()
            except Exception as exc:
                QMessageBox.warning(self, "保存失败", str(exc))

    def _delete_plugin(self, plugin_id: str, return_to_list: bool = False) -> None:
        ans = QMessageBox.question(
            self,
            "确认移除",
            f"确定移除「{plugin_id}」并停止关联进程吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        def after(_res: Any) -> None:
            self._show_toast(f"已移除 {plugin_id}")
            if return_to_list:
                self._switch_tab(PAGE_EXTERNAL)
            self.refresh_all()

        self._run_async(lambda: self.manager.delete_plugin_entry(plugin_id), after)

    def _create_shortcuts(self) -> None:
        self.shortcut_btn.setEnabled(False)

        def done(_res: dict[str, str]) -> None:
            self.shortcut_btn.setEnabled(True)
            self._show_toast("桌面图标已更新")

        def fail(err: str) -> None:
            self.shortcut_btn.setEnabled(True)
            QMessageBox.warning(self, "生成失败", err)

        self._run_async(self.manager.create_all_shortcuts, done, fail)

    def _install_plugin_package_dialog(self) -> None:
        start_dir = str(getattr(self.manager.paths, "data_dir", self.manager.base_dir))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择插件安装包",
            start_dir,
            "插件安装包 (*.zip *.agypkg *.agy-plugin)",
        )
        if file_path:
            self._install_plugin_package(file_path)

    def _install_plugin_package(self, file_path: str) -> None:
        self._show_toast("正在安装插件包...")

        def run() -> dict[str, Any]:
            res = self.manager.install_plugin_package(file_path, overwrite=True)
            plugin = res.get("plugin") or {}
            plugin_id = str(plugin.get("id") or "").strip()
            activated = False
            attach_error = ""
            if (
                plugin_id
                and plugin.get("enabled", True) is not False
                and plugin.get("autoAttach", True) is not False
            ):
                cdp = self.manager.get_active_cdp_info()
                if cdp.get("ready"):
                    try:
                        self.manager.start_plugin(plugin_id, mode="attach")
                        activated = True
                    except Exception as exc:
                        attach_error = str(exc)
            return {**res, "activated": activated, "attachError": attach_error}

        def done(res: dict[str, Any]) -> None:
            plugin = res.get("plugin") or {}
            label = str(plugin.get("name") or plugin.get("id") or Path(file_path).stem)
            if res.get("activated"):
                self._show_toast(f"已安装并激活插件: {label}")
            elif res.get("attachError"):
                self._show_toast(f"已安装插件: {label}（自动激活失败: {res['attachError']}）")
            else:
                self._show_toast(f"已安装插件: {label}")
            self.refresh_all()

        self._run_async(run, done)

    def _detect_antigravity_path(self) -> None:
        self.agy_detect_btn.setEnabled(False)
        self._set_dot(self.agy_path_status_lbl, "muted", "正在检测...")

        def done(res: dict[str, Any]) -> None:
            self.agy_detect_btn.setEnabled(True)
            if res.get("found") and res.get("path"):
                detected_path = str(res["path"])
                source = str(res.get("source") or "auto")
                self.agy_exe_edit.setText(detected_path)
                self._update_agy_path_status(detected_path, exists=True, source=source)
                self._show_toast(f"已检测到 Antigravity ({source})")
            else:
                self._set_dot(self.agy_path_status_lbl, "warn", "未自动检测到，请手动选择")
                self._show_toast("未检测到 Antigravity.exe，请点击「浏览」手动选择")

        def fail(err: str) -> None:
            self.agy_detect_btn.setEnabled(True)
            self._set_dot(self.agy_path_status_lbl, "warn", "检测失败")
            self._notify_error(err)

        self._run_async(self.manager.detect_antigravity, done, fail)

    def _browse_antigravity_path(self) -> None:
        current = self.agy_exe_edit.text().strip()
        start_dir = str(Path(current).parent) if current and Path(current).parent.exists() else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Antigravity.exe",
            start_dir,
            "Antigravity 可执行文件 (Antigravity.exe);;可执行文件 (*.exe)",
        )
        if file_path:
            self.agy_exe_edit.setText(file_path)
            self._update_agy_path_status(file_path)

    def _auto_detect_proxy(self) -> None:
        self.proxy_detect_btn.setEnabled(False)
        self._set_dot(self.proxy_detect_status_lbl, "muted", "正在检测...")

        def run() -> dict[str, Any]:
            res = self.manager.detect_system_proxy()
            if res.get("detected"):
                self.manager.save_proxy_config(
                    {
                        "enabled": True,
                        "httpProxy": str(res.get("httpProxy") or ""),
                        "httpsProxy": str(res.get("httpsProxy") or ""),
                        "allProxy": str(res.get("allProxy") or ""),
                        "noProxy": str(res.get("noProxy") or "127.0.0.1,localhost,::1"),
                        "electronProxyServer": str(res.get("electronProxyServer") or ""),
                    }
                )
            return res

        def done(res: dict[str, Any]) -> None:
            self.proxy_detect_btn.setEnabled(True)
            if res.get("detected"):
                self.proxy_http_edit.setText(str(res.get("httpProxy") or ""))
                self.proxy_https_edit.setText(str(res.get("httpsProxy") or ""))
                self.proxy_all_edit.setText(str(res.get("allProxy") or ""))
                self.proxy_no_edit.setText(str(res.get("noProxy") or "127.0.0.1,localhost,::1"))
                self.proxy_electron_edit.setText(str(res.get("electronProxyServer") or ""))
                self.proxy_enabled_chk.setChecked(True)
                source = str(res.get("source") or "auto")
                proc = str(res.get("processName") or "").strip()
                src_text = f"{source}: {proc}" if proc else source
                self._set_dot(self.proxy_detect_status_lbl, "ok", f"已自动配置 ({src_text})")
                self._show_toast(f"已自动配置 ({src_text})")
                self.refresh_all()
            else:
                self._set_dot(self.proxy_detect_status_lbl, "muted", "未检测到活动代理，请开启代理客户端或手动填写")
                self._show_toast("未检测到系统或本地代理")

        def fail(err: str) -> None:
            self.proxy_detect_btn.setEnabled(True)
            self._set_dot(self.proxy_detect_status_lbl, "warn", "检测失败")
            self._notify_error(err)

        self._run_async(run, done, fail)

    def _save_settings(self) -> None:
        try:
            agy_path = self.agy_exe_edit.text().strip()
            saved_agy = self.manager.save_antigravity_exe(agy_path)
            self._update_agy_path_status(agy_path, exists=bool(saved_agy.get("exists")))
            self.manager.save_proxy_config(
                {
                    "enabled": self.proxy_enabled_chk.isChecked(),
                    "httpProxy": self.proxy_http_edit.text().strip(),
                    "httpsProxy": self.proxy_https_edit.text().strip(),
                    "allProxy": self.proxy_all_edit.text().strip(),
                    "noProxy": self.proxy_no_edit.text().strip(),
                    "electronProxyServer": self.proxy_electron_edit.text().strip(),
                }
            )
            self.manager.save_lifecycle_config(
                {
                    "autoCleanupOnExit": self.auto_cleanup_chk.isChecked(),
                    "stopPluginsOnExit": self.stop_plugins_on_exit_chk.isChecked(),
                }
            )
            self._minimize_to_tray = self.tray_close_chk.isChecked()
            self.manager.save_ui_preferences(minimize_to_tray=self._minimize_to_tray)
            self._show_toast("设置已保存")
            self.refresh_all()
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    # ------------------------------------------------------------------
    # AGY Storage Management (SpaceSniffer Treemap)
    # ------------------------------------------------------------------
    def _set_storage_view_mode(self, mode: str) -> None:
        if mode not in ("session", "type", "dir"):
            mode = "session"
        self._storage_view_mode = mode
        if hasattr(self, "storage_view_buttons") and mode in self.storage_view_buttons:
            self.storage_view_buttons[mode].setChecked(True)
        self._storage_path_ids = []
        self._storage_selected_id = ""
        self._storage_agg_members.clear()
        self._storage_list_selected_ids.clear()
        self._storage_list_last_idx = None
        if hasattr(self, "storage_age_filter_box"):
            self.storage_age_filter_box.setVisible(mode == "session")
        if hasattr(self, "storage_list_col_name_lbl"):
            self.storage_list_col_name_lbl.setText("会话名称 / 标识" if mode == "session" else "目录 / 分类名称")
        if hasattr(self, "storage_batch_files_btn"):
            is_sess = mode == "session"
            self.storage_batch_files_btn.setVisible(is_sess)
            self.storage_batch_sessions_btn.setVisible(is_sess)
            self.storage_batch_items_btn.setVisible(not is_sess)
        if self._storage_snapshot is None and not self._storage_scanning:
            self._refresh_storage_scan()
        else:
            self._render_storage_view()

    def _set_storage_display_style(self, style: str) -> None:
        if style not in ("treemap", "list"):
            style = "treemap"
        self._storage_display_style = style
        if hasattr(self, "storage_style_buttons") and style in self.storage_style_buttons:
            self.storage_style_buttons[style].setChecked(True)
        idx = 1 if style == "list" else 0
        if hasattr(self, "storage_subbar_stack"):
            self.storage_subbar_stack.setCurrentIndex(idx)
        if hasattr(self, "storage_workspace_stack"):
            self.storage_workspace_stack.setCurrentIndex(idx)
        if self._storage_snapshot is None and not self._storage_scanning:
            self._refresh_storage_scan()
        else:
            self._render_storage_view()

    def _set_storage_list_sort(self, sort_key: str) -> None:
        if sort_key not in ("time", "size"):
            sort_key = "time"
        if self._storage_list_sort_key == sort_key:
            self._storage_list_sort_asc = not self._storage_list_sort_asc
        else:
            self._storage_list_sort_key = sort_key
            self._storage_list_sort_asc = sort_key == "time"
        self._update_storage_sort_buttons()
        self._render_storage_view()

    def _update_storage_sort_buttons(self) -> None:
        if hasattr(self, "storage_sort_time_btn"):
            is_time = self._storage_list_sort_key == "time"
            self.storage_sort_time_btn.setChecked(is_time)
            if is_time:
                self.storage_sort_time_btn.setText(
                    "最近更新 ↑ 最久未用" if self._storage_list_sort_asc else "最近更新 ↓ 最新在前"
                )
            else:
                self.storage_sort_time_btn.setText("最近更新")
        if hasattr(self, "storage_sort_size_btn"):
            is_size = self._storage_list_sort_key == "size"
            self.storage_sort_size_btn.setChecked(is_size)
            if is_size:
                self.storage_sort_size_btn.setText(
                    "占用空间 ↑ 最小在前" if self._storage_list_sort_asc else "占用空间 ↓ 最大在前"
                )
            else:
                self.storage_sort_size_btn.setText("占用空间")

    def _set_storage_list_age_filter(self, age_filter: str) -> None:
        if age_filter not in ("all", "7d", "30d"):
            age_filter = "all"
        self._storage_list_age_filter = age_filter
        if hasattr(self, "storage_age_buttons") and age_filter in self.storage_age_buttons:
            self.storage_age_buttons[age_filter].setChecked(True)
        self._storage_list_last_idx = None
        self._render_storage_view()

    def _set_storage_list_attr_filter(self, attr_key: str, active: bool | None = None) -> None:
        if attr_key not in ("archived", "subagent", "unnamed"):
            return
        new_state = (attr_key not in self._storage_list_attr_filters) if active is None else bool(active)
        if new_state:
            self._storage_list_attr_filters.add(attr_key)
        else:
            self._storage_list_attr_filters.discard(attr_key)
        if hasattr(self, "storage_attr_buttons") and attr_key in self.storage_attr_buttons:
            btn = self.storage_attr_buttons[attr_key]
            if btn.isChecked() != new_state:
                btn.blockSignals(True)
                btn.setChecked(new_state)
                btn.blockSignals(False)
        self._storage_list_last_idx = None
        self._render_storage_view()

    def _on_storage_filter_changed(self, _text: str) -> None:
        self._storage_path_ids = []
        self._storage_selected_id = ""
        self._storage_agg_members.clear()
        self._render_storage_view()

    def _on_storage_appdata_toggled(self, checked: bool) -> None:
        self._storage_include_appdata = bool(checked)
        self._storage_path_ids = []
        self._storage_selected_id = ""
        self._storage_agg_members.clear()
        self._render_storage_view()

    def _refresh_storage_scan(self) -> None:
        if self._storage_scanning:
            return
        self._storage_scanning = True
        if hasattr(self, "storage_rescan_btn"):
            self.storage_rescan_btn.setEnabled(False)
            self.storage_rescan_btn.setText("扫描中...")
        if hasattr(self, "storage_summary_lbl"):
            self.storage_summary_lbl.setText("正在扫描本地 AGY 存储...")
        if hasattr(self, "storage_list_summary_lbl"):
            self.storage_list_summary_lbl.setText("正在扫描本地 AGY 存储...")
        if hasattr(self, "storage_scan_bar"):
            self.storage_scan_bar.setRange(0, 0)
            self.storage_scan_bar.show()
        if hasattr(self, "storage_treemap"):
            self.storage_treemap.set_scanning(True, 0.0, "正在发现 AGY 存储目录...", 0, 0)

        def emit_progress(info: dict[str, Any]) -> None:
            try:
                self._storageScanProgress.emit(info)
            except RuntimeError:
                pass

        def run() -> StorageScanSnapshot:
            return self.manager.scan_agy_storage(progress_cb=emit_progress)

        def done(snap: StorageScanSnapshot) -> None:
            self._storage_scanning = False
            self._storage_snapshot = snap
            if hasattr(self, "storage_scan_bar"):
                self.storage_scan_bar.hide()
            if hasattr(self, "storage_treemap"):
                self.storage_treemap.set_scanning(False)
            if hasattr(self, "storage_rescan_btn"):
                self.storage_rescan_btn.setEnabled(True)
                self.storage_rescan_btn.setText("重新扫描")
            self._render_storage_view()

        def fail(err: str) -> None:
            self._storage_scanning = False
            if hasattr(self, "storage_scan_bar"):
                self.storage_scan_bar.hide()
            if hasattr(self, "storage_treemap"):
                self.storage_treemap.set_scanning(False)
            if hasattr(self, "storage_rescan_btn"):
                self.storage_rescan_btn.setEnabled(True)
                self.storage_rescan_btn.setText("重新扫描")
            if hasattr(self, "storage_summary_lbl"):
                self.storage_summary_lbl.setText("扫描失败")
            self._notify_error(err)

        self._run_async(run, done, fail)

    @Slot(dict)
    def _on_storage_scan_progress(self, payload: dict[str, Any]) -> None:
        if not self._storage_scanning:
            return
        phase = str(payload.get("phase") or "scanning")
        fraction = max(0.0, min(1.0, float(payload.get("fraction") or 0.0)))
        root_idx = int(payload.get("rootIndex") or 0)
        root_count = int(payload.get("rootCount") or 0)
        root_label = str(payload.get("rootLabel") or "").strip()
        current_path = str(payload.get("currentPath") or "").strip()
        scanned_files = max(0, int(payload.get("scannedFiles") or 0))
        scanned_bytes = max(0, int(payload.get("scannedBytes") or 0))

        if hasattr(self, "storage_scan_bar"):
            if phase == "roots" and fraction <= 0.005:
                if self.storage_scan_bar.maximum() != 0:
                    self.storage_scan_bar.setRange(0, 0)
            else:
                if self.storage_scan_bar.maximum() != 1000:
                    self.storage_scan_bar.setRange(0, 1000)
                self.storage_scan_bar.setValue(max(0, min(1000, int(round(fraction * 1000)))))
            if not self.storage_scan_bar.isVisible():
                self.storage_scan_bar.show()

        if hasattr(self, "storage_summary_lbl") or hasattr(self, "storage_list_summary_lbl"):
            if phase == "roots":
                scan_text = "正在发现 AGY 存储目录..."
            else:
                short_root = root_label.split("(")[0].strip() if root_label else ""
                prefix = f"扫描中 ({root_idx}/{root_count}) {short_root}" if (root_count > 0 and short_root) else "扫描中"
                scan_text = f"{prefix} · {scanned_files} 文件 · {format_bytes(scanned_bytes)}"
            if hasattr(self, "storage_summary_lbl"):
                self.storage_summary_lbl.setText(scan_text)
            if hasattr(self, "storage_list_summary_lbl"):
                self.storage_list_summary_lbl.setText(scan_text)

        if hasattr(self, "storage_treemap"):
            status_text = current_path or root_label or "正在发现 AGY 存储目录..."
            self.storage_treemap.set_scanning(True, fraction, status_text, scanned_files, scanned_bytes)

    @staticmethod
    def _find_storage_trail(
        root: StorageNode,
        path_ids: list[str],
        agg_members: dict[str, list[str]] | None = None,
    ) -> tuple[StorageNode, list[StorageNode]]:
        trail = [root]
        curr = root
        for nid in path_ids:
            nxt = next((ch for ch in curr.children if ch.node_id == nid), None)
            if nxt is None and agg_members and nid in agg_members:
                member_set = set(agg_members[nid])
                live_children = [ch for ch in curr.children if ch.node_id in member_set]
                if live_children:
                    nxt = StorageNode(
                        node_id=nid,
                        name=f"其余 {len(live_children)} 项",
                        kind="aggregate",
                        category=curr.category,
                        size_bytes=sum(c.size_bytes for c in live_children),
                        file_count=sum(c.file_count for c in live_children),
                        path=curr.path,
                        subtitle=f"聚合查看 {len(live_children)} 个较小条目",
                        purpose_desc=f"此处折叠了 {len(live_children)} 个占用空间较小的条目，双击即可展开逐项查看与清理。",
                        deletability="caution",
                        deletability_label="聚合折叠 · 展开查看",
                        children=live_children,
                    )
            if nxt is None:
                break
            trail.append(nxt)
            curr = nxt
        return curr, trail

    @staticmethod
    def _storage_kind_label(node: StorageNode) -> str:
        mapping = {
            "root": "总览",
            "session": "会话",
            "session_files": "会话产出文件",
            "session_pb": "会话记录 (.pb)",
            "category": "文件分类",
            "dir": "目录",
            "file": "文件",
            "aggregate": "聚合项",
        }
        return mapping.get(node.kind, "存储项")

    def _render_storage_view(self) -> None:
        transition, anchor_id = self._pending_treemap_transition
        self._pending_treemap_transition = ("none", "")
        if not hasattr(self, "storage_treemap"):
            return
        if self._storage_snapshot is None:
            self.storage_treemap.set_root_node(None)
            self._clear_storage_rank_list()
            self._clear_storage_list_view()
            if hasattr(self, "storage_orphan_btn"):
                self.storage_orphan_btn.hide()
            return

        if hasattr(self, "storage_orphan_btn"):
            orphan_cnt = len(getattr(self._storage_snapshot, "orphan_summary_ids", ()) or ())
            self.storage_orphan_btn.setVisible(orphan_cnt > 0)
            if orphan_cnt > 0:
                self.storage_orphan_btn.setText(f"清理失效记录 ({orphan_cnt})")

        query = self.storage_search.text().strip() if hasattr(self, "storage_search") else ""
        tree = build_storage_tree(
            self._storage_snapshot,
            self._storage_view_mode,
            include_appdata=self._storage_include_appdata,
            query=query,
        )
        self._storage_tree_root = tree

        focus_node, trail = self._find_storage_trail(tree, self._storage_path_ids, self._storage_agg_members)
        self._storage_path_ids = [n.node_id for n in trail[1:]]
        self.storage_up_btn.setEnabled(len(trail) > 1)

        total_root_bytes = max(1, tree.size_bytes)
        sess_cnt = sum(1 for c in tree.children if c.kind == "session") if self._storage_view_mode == "session" else len(self._storage_snapshot.sessions)
        summary_txt = f"共 {format_bytes(tree.size_bytes)} · {tree.file_count} 文件 · {sess_cnt} 会话"
        self.storage_summary_lbl.setText(summary_txt)

        if self._storage_display_style == "list":
            self._render_storage_list_view(tree, focus_node, trail)
            return

        # Pick selected node inside focus level (or nested child / synthetic aggregate)
        selected_node: StorageNode | None = None
        if self._storage_selected_id:
            if focus_node.node_id == self._storage_selected_id:
                selected_node = focus_node
            else:
                selected_node = next((c for c in focus_node.children if c.node_id == self._storage_selected_id), None)
                if selected_node is None:
                    for mid in focus_node.children:
                        selected_node = next((gc for gc in mid.children if gc.node_id == self._storage_selected_id), None)
                        if selected_node is not None:
                            break
        if selected_node is None:
            selected_node = focus_node.children[0] if focus_node.children else focus_node
        self._storage_selected_id = selected_node.node_id

        self.storage_treemap.set_root_node(
            focus_node,
            total_root_bytes=total_root_bytes,
            selected_id=selected_node.node_id,
            transition=transition,
            anchor_node_id=anchor_id,
        )
        self._render_storage_breadcrumbs(trail)
        self._render_storage_inspector(selected_node, total_root_bytes)
        self._render_storage_ranked_list(focus_node, selected_node.node_id)
        self._on_storage_node_hovered(None)

    def _clear_storage_list_view(self) -> None:
        self._storage_list_items = []
        self._storage_list_row_widgets.clear()
        if hasattr(self, "storage_list_container"):
            self._clear_vbox(self.storage_list_container)
        self._update_storage_list_batch_bar()

    @staticmethod
    def _session_storage_breakdown(node: StorageNode) -> tuple[int, int, int]:
        """Returns `(files_bytes, pb_bytes, files_count)` for a session node."""
        files_b = 0
        files_cnt = 0
        pb_b = 0
        for ch in node.children:
            if ch.kind == "session_files":
                files_b += ch.size_bytes
                files_cnt += ch.file_count
            elif ch.kind == "session_pb":
                pb_b += ch.size_bytes
        return files_b, pb_b, files_cnt

    def _get_storage_list_items(
        self,
        tree: StorageNode,
        focus_node: StorageNode,
        *,
        now: float | None = None,
    ) -> list[StorageNode]:
        if self._storage_view_mode == "session":
            items = [c for c in tree.children if c.kind == "session"]
            ref_now = time.time() if now is None else float(now)
            if self._storage_list_age_filter == "7d":
                items = [c for c in items if (d := idle_age_days(c.mtime, ref_now)) is not None and d >= 7]
            elif self._storage_list_age_filter == "30d":
                items = [c for c in items if (d := idle_age_days(c.mtime, ref_now)) is not None and d >= 30]
            if "archived" in self._storage_list_attr_filters:
                items = [c for c in items if c.is_archived]
            if "subagent" in self._storage_list_attr_filters:
                items = [c for c in items if c.is_subagent]
            if "unnamed" in self._storage_list_attr_filters:
                items = [c for c in items if c.is_unnamed]
        else:
            items = list(focus_node.children)

        if self._storage_list_sort_key == "time":
            if self._storage_list_sort_asc:
                items.sort(key=lambda n: (0 if n.mtime > 0 else 1, n.mtime if n.mtime > 0 else 0.0, -n.size_bytes))
            else:
                items.sort(key=lambda n: (n.mtime if n.mtime > 0 else -1.0, n.size_bytes), reverse=True)
        else:
            if self._storage_list_sort_asc:
                items.sort(key=lambda n: (n.size_bytes, n.mtime))
            else:
                items.sort(key=lambda n: (n.size_bytes, n.mtime), reverse=True)
        return items

    def _render_storage_list_view(self, tree: StorageNode, focus_node: StorageNode, trail: list[StorageNode]) -> None:
        if not hasattr(self, "storage_list_container"):
            return
        self._clear_vbox(self.storage_list_container)
        self._storage_list_row_widgets.clear()
        self._update_storage_sort_buttons()

        if hasattr(self, "storage_list_up_btn"):
            self.storage_list_up_btn.setVisible(self._storage_view_mode != "session" and len(trail) > 1)

        now_ts = time.time()
        items = self._get_storage_list_items(tree, focus_node, now=now_ts)
        self._storage_list_items = items

        visible_ids = {item.node_id for item in items}
        self._storage_list_selected_ids &= visible_ids
        if self._storage_list_last_idx is not None and self._storage_list_last_idx >= len(items):
            self._storage_list_last_idx = None

        total_list_bytes = sum(i.size_bytes for i in items)
        max_item_bytes = max((i.size_bytes for i in items), default=1) or 1
        denom_bytes = max(1, total_list_bytes)
        if hasattr(self, "storage_list_summary_lbl"):
            if self._storage_view_mode == "session":
                self.storage_list_summary_lbl.setText(f"共 {len(items)} 个会话 · {format_bytes(total_list_bytes)}")
            else:
                loc = " › ".join(n.name for n in trail[1:]) if len(trail) > 1 else self._storage_kind_label(focus_node)
                self.storage_list_summary_lbl.setText(f"{loc} · {len(items)} 项 · {format_bytes(focus_node.size_bytes)}")

        if not items:
            empty = QLabel("当前筛选条件下没有可清理的会话或存储条目")
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(20, 48, 20, 48)
            self.storage_list_container.addWidget(empty)
            self.storage_list_container.addStretch(1)
            self._sync_storage_list_selection_ui()
            return

        is_session_mode = self._storage_view_mode == "session"
        tone_pill = {
            "ok": "PillOk",
            "muted": "PillMuted",
            "warn": "PillWarn",
            "danger": "PillDanger",
        }

        for idx, node in enumerate(items):
            is_checked = node.node_id in self._storage_list_selected_ids
            row = ClickableRow("StorageSessionRow")
            row.setProperty("checked", "true" if is_checked else "false")
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(14, 9, 14, 9)
            r_lay.setSpacing(12)

            chk = QCheckBox()
            chk.setObjectName("RowCheckBox")
            chk.setFixedWidth(22)
            chk.blockSignals(True)
            chk.setChecked(is_checked)
            chk.blockSignals(False)
            chk.clicked.connect(lambda checked, nid=node.node_id, ridx=idx: self._on_storage_list_select_item(nid, checked, ridx))
            r_lay.addWidget(chk)

            # Column 1: Title + subtitle
            col_name = QVBoxLayout()
            col_name.setSpacing(3)
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(6)
            title_lbl = _ElidedTitleLabel(node.name)
            title_row.addWidget(title_lbl)

            if is_session_mode and (node.is_archived or "已归档" in (node.subtitle or "")):
                arch_pill = QLabel("已归档")
                arch_pill.setObjectName("PillMuted")
                title_row.addWidget(arch_pill)
            if is_session_mode and (node.is_subagent or "子代理会话" in (node.subtitle or "")):
                sub_pill = QLabel("子代理")
                sub_pill.setObjectName("PillInfo")
                title_row.addWidget(sub_pill)
            elif not is_session_mode and node.protected:
                prot_pill = QLabel("受保护")
                prot_pill.setObjectName("PillWarn")
                title_row.addWidget(prot_pill)
            title_row.addStretch(1)

            meta_text = node.subtitle or node.path or self._storage_kind_label(node)
            if is_session_mode:
                files_b, pb_b, _fcnt = self._session_storage_breakdown(node)
                split_hint = f"产出 {format_bytes(files_b)} · 对话库 {format_bytes(pb_b)}" if files_b > 0 else f"仅保留对话库 {format_bytes(pb_b)}"
                meta_text = f"{meta_text} · {split_hint}" if meta_text else split_hint
            meta_lbl = QLabel(meta_text)
            meta_lbl.setObjectName("FaintLabel")
            meta_lbl.setWordWrap(False)
            meta_lbl.setMinimumWidth(0)
            col_name.addLayout(title_row)
            col_name.addWidget(meta_lbl)
            r_lay.addLayout(col_name, 1)

            # Column 2: Update time + idle age badge
            col_time = QWidget()
            col_time.setFixedWidth(185)
            ct_lay = QVBoxLayout(col_time)
            ct_lay.setContentsMargins(0, 0, 0, 0)
            ct_lay.setSpacing(3)
            mt_lbl = QLabel(format_mtime(node.mtime))
            mt_lbl.setObjectName("MonoLabel")
            age_text, age_tone = format_idle_age(node.mtime, now_ts)
            age_row = QHBoxLayout()
            age_row.setContentsMargins(0, 0, 0, 0)
            age_row.setSpacing(0)
            age_pill = QLabel(age_text)
            age_pill.setObjectName(tone_pill.get(age_tone, "PillMuted"))
            age_row.addWidget(age_pill)
            age_row.addStretch(1)
            ct_lay.addWidget(mt_lbl)
            ct_lay.addLayout(age_row)
            r_lay.addWidget(col_time)

            # Column 3: Size + bar + breakdown
            col_size = QWidget()
            col_size.setFixedWidth(165)
            cs_lay = QVBoxLayout(col_size)
            cs_lay.setContentsMargins(0, 0, 0, 0)
            cs_lay.setSpacing(4)
            sz_top = QHBoxLayout()
            sz_top.setContentsMargins(0, 0, 0, 0)
            sz_val = QLabel(format_bytes(node.size_bytes))
            sz_val.setStyleSheet("font-weight: 600; font-size: 9.2pt;")
            pct_lbl = QLabel(f"{(node.size_bytes / denom_bytes) * 100.0:.1f}%")
            pct_lbl.setObjectName("FaintLabel")
            sz_top.addWidget(sz_val)
            sz_top.addStretch(1)
            sz_top.addWidget(pct_lbl)

            bar = QProgressBar()
            bar.setObjectName("StorageBar")
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(max(8 if node.size_bytes > 0 else 0, int(round((node.size_bytes / max_item_bytes) * 1000))))

            sub_sz_txt = (
                f"{node.file_count} 个文件"
                if not is_session_mode
                else (f"{node.file_count} 文件 · 可保留记录" if files_b > 0 else f"{node.file_count} 文件 · 仅记录")
            )
            sub_sz = QLabel(sub_sz_txt)
            sub_sz.setObjectName("FaintLabel")
            cs_lay.addLayout(sz_top)
            cs_lay.addWidget(bar)
            cs_lay.addWidget(sub_sz)
            r_lay.addWidget(col_size)

            # Column 4: Quick actions
            col_act = QWidget()
            col_act.setFixedWidth(124)
            ca_lay = QHBoxLayout(col_act)
            ca_lay.setContentsMargins(0, 0, 0, 0)
            ca_lay.setSpacing(6)
            ca_lay.addStretch(1)

            if is_session_mode:
                files_b, _pb_b, _fc = self._session_storage_breakdown(node)
                b_files = QPushButton("删文件")
                b_files.setObjectName("MiniWarnBtn")
                b_files.setCursor(Qt.CursorShape.PointingHandCursor)
                b_files.setEnabled(files_b > 0)
                b_files.setToolTip("仅删除 brain 产出文件，保留对话记录" if files_b > 0 else "该会话暂无可删产出文件")
                b_files.clicked.connect(lambda _=False, n=node: self._storage_action_clean_session_files(n))

                b_sess = QPushButton("删会话")
                b_sess.setObjectName("MiniDangerBtn")
                b_sess.setCursor(Qt.CursorShape.PointingHandCursor)
                b_sess.setToolTip("删除整个会话（含 .pb / .db 记录与所有产出）")
                b_sess.clicked.connect(lambda _=False, n=node: self._storage_action_delete_session(n))
                ca_lay.addWidget(b_files)
                ca_lay.addWidget(b_sess)
            else:
                if node.children:
                    b_open = QPushButton("展开")
                    b_open.setObjectName("MiniNeutralBtn")
                    b_open.setCursor(Qt.CursorShape.PointingHandCursor)
                    b_open.clicked.connect(lambda _=False, n=node: self._storage_list_drill_node(n))
                    ca_lay.addWidget(b_open)
                b_del = QPushButton("清理")
                b_del.setObjectName("MiniDangerBtn")
                b_del.setCursor(Qt.CursorShape.PointingHandCursor)
                b_del.setEnabled(not node.protected and bool(node.delete_targets))
                b_del.clicked.connect(lambda _=False, n=node: self._storage_action_delete_selected(n))
                ca_lay.addWidget(b_del)

            r_lay.addWidget(col_act)

            row.clicked.connect(
                lambda nid=node.node_id, ridx=idx: self._on_storage_list_select_item(
                    nid, nid not in self._storage_list_selected_ids, ridx
                )
            )
            if not is_session_mode and node.children:
                row.doubleClicked.connect(lambda n=node: self._storage_list_drill_node(n))
            elif is_session_mode:
                row.doubleClicked.connect(lambda n=node: self._storage_action_open_explorer(n))

            self.storage_list_container.addWidget(row)
            self._storage_list_row_widgets[node.node_id] = (row, chk)

        self.storage_list_container.addStretch(1)
        self._sync_storage_list_selection_ui()

    def _storage_list_drill_node(self, node: StorageNode) -> None:
        if not node.children:
            return
        self._storage_path_ids.append(node.node_id)
        self._storage_selected_id = ""
        self._storage_list_selected_ids.clear()
        self._storage_list_last_idx = None
        self._render_storage_view()

    def _on_storage_list_select_item(self, node_id: str, checked: bool, row_idx: int) -> None:
        modifiers = QApplication.keyboardModifiers()
        if (
            (modifiers & Qt.KeyboardModifier.ShiftModifier)
            and self._storage_list_last_idx is not None
            and 0 <= self._storage_list_last_idx < len(self._storage_list_items)
            and 0 <= row_idx < len(self._storage_list_items)
        ):
            lo = min(self._storage_list_last_idx, row_idx)
            hi = max(self._storage_list_last_idx, row_idx)
            for i in range(lo, hi + 1):
                nid = self._storage_list_items[i].node_id
                if checked:
                    self._storage_list_selected_ids.add(nid)
                else:
                    self._storage_list_selected_ids.discard(nid)
        else:
            if checked:
                self._storage_list_selected_ids.add(node_id)
            else:
                self._storage_list_selected_ids.discard(node_id)
        self._storage_list_last_idx = row_idx
        self._sync_storage_list_selection_ui()

    def _on_storage_list_select_all_clicked(self, checked: bool) -> None:
        if checked:
            self._storage_list_selected_ids = {item.node_id for item in self._storage_list_items}
        else:
            self._storage_list_selected_ids.clear()
        self._storage_list_last_idx = None
        self._sync_storage_list_selection_ui()

    def _invert_storage_list_selection(self) -> None:
        visible_ids = {item.node_id for item in self._storage_list_items}
        self._storage_list_selected_ids = visible_ids - self._storage_list_selected_ids
        self._storage_list_last_idx = None
        self._sync_storage_list_selection_ui()

    def _clear_storage_list_selection(self) -> None:
        self._storage_list_selected_ids.clear()
        self._storage_list_last_idx = None
        self._sync_storage_list_selection_ui()

    def _sync_storage_list_selection_ui(self) -> None:
        for nid, (row, chk) in self._storage_list_row_widgets.items():
            checked = nid in self._storage_list_selected_ids
            if chk.isChecked() != checked:
                chk.blockSignals(True)
                chk.setChecked(checked)
                chk.blockSignals(False)
            target_prop = "true" if checked else "false"
            if row.property("checked") != target_prop:
                row.setProperty("checked", target_prop)
                row.style().unpolish(row)
                row.style().polish(row)

        if hasattr(self, "storage_select_all_chk"):
            all_selected = bool(self._storage_list_items) and all(
                item.node_id in self._storage_list_selected_ids for item in self._storage_list_items
            )
            self.storage_select_all_chk.blockSignals(True)
            self.storage_select_all_chk.setChecked(all_selected)
            self.storage_select_all_chk.blockSignals(False)

        self._update_storage_list_batch_bar()

    def _update_storage_list_batch_bar(self) -> None:
        if not hasattr(self, "storage_batch_title"):
            return
        selected_nodes = [n for n in self._storage_list_items if n.node_id in self._storage_list_selected_ids]
        cnt = len(selected_nodes)
        is_sess = self._storage_view_mode == "session"

        if hasattr(self, "storage_list_invert_btn"):
            self.storage_list_invert_btn.setEnabled(bool(self._storage_list_items))
        if hasattr(self, "storage_list_clear_btn"):
            self.storage_list_clear_btn.setEnabled(cnt > 0)

        if cnt == 0:
            self.storage_batch_title.setText("未选择任何会话" if is_sess else "未选择任何条目")
            self.storage_batch_sub.setText(
                "勾选条目（支持 Shift 连选）可批量清理会话产出文件或删除整个会话"
                if is_sess
                else "勾选条目（支持 Shift 连选）可批量清理所选文件或目录"
            )
            self.storage_batch_files_btn.setEnabled(False)
            self.storage_batch_sessions_btn.setEnabled(False)
            self.storage_batch_items_btn.setEnabled(False)
            return

        total_b = sum(n.size_bytes for n in selected_nodes)
        if is_sess:
            total_files_b = 0
            total_pb_b = 0
            for n in selected_nodes:
                fb, pb, _fc = self._session_storage_breakdown(n)
                total_files_b += fb
                total_pb_b += pb
            self.storage_batch_title.setText(f"已选中 {cnt} 个会话 · 合计 {format_bytes(total_b)}")
            self.storage_batch_sub.setText(
                f"包含产出文件 {format_bytes(total_files_b)} · 对话库 {format_bytes(total_pb_b)}"
            )
            self.storage_batch_files_btn.setEnabled(total_files_b > 0)
            self.storage_batch_sessions_btn.setEnabled(True)
        else:
            deletable = [n for n in selected_nodes if not n.protected and n.delete_targets]
            del_b = sum(n.size_bytes for n in deletable)
            self.storage_batch_title.setText(f"已选中 {cnt} 项 · 合计 {format_bytes(total_b)}")
            self.storage_batch_sub.setText(
                f"其中 {len(deletable)} 项可执行清理（预计释放 {format_bytes(del_b)}）"
                if len(deletable) < cnt
                else f"预计释放 {format_bytes(del_b)}"
            )
            self.storage_batch_items_btn.setEnabled(bool(deletable))

    def _render_storage_breadcrumbs(self, trail: list[StorageNode]) -> None:
        while self.storage_crumb_lay.count():
            item = self.storage_crumb_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        for idx, node in enumerate(trail):
            if idx > 0:
                sep = QLabel("›")
                sep.setObjectName("FaintLabel")
                self.storage_crumb_lay.addWidget(sep)
            btn = QPushButton(node.name if idx == 0 else node.name[:24])
            btn.setObjectName("BreadcrumbBtn")
            btn.setProperty("current", idx == len(trail) - 1)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            target_prefix = [n.node_id for n in trail[1 : idx + 1]]
            btn.clicked.connect(lambda _=False, p=target_prefix: self._storage_jump_crumb(p))
            self.storage_crumb_lay.addWidget(btn)

    def _storage_jump_crumb(self, prefix_ids: list[str]) -> None:
        target_ids = list(prefix_ids)
        if target_ids == self._storage_path_ids:
            return
        if len(target_ids) < len(self._storage_path_ids):
            departed_id = self._storage_path_ids[len(target_ids)]
            self._pending_treemap_transition = ("out", departed_id)
        self._storage_path_ids = target_ids
        self._storage_selected_id = ""
        self._render_storage_view()

    def _storage_navigate_up(self) -> None:
        if self._storage_path_ids:
            departed_id = self._storage_path_ids.pop()
            self._pending_treemap_transition = ("out", departed_id)
            self._storage_selected_id = ""
            self._render_storage_view()

    def _render_storage_inspector(self, node: StorageNode, total_root_bytes: int) -> None:
        self.st_insp_kind_pill.setText(self._storage_kind_label(node))

        del_state = node.deletability if node.deletability in ("safe", "caution", "protected") else (
            "protected" if node.protected else "caution"
        )
        del_label = (node.deletability_label or "").strip()
        if not del_label:
            del_label = {"safe": "可安全清理", "caution": "谨慎清理", "protected": "受保护配置"}.get(del_state, "谨慎清理")
        del_pill_obj = {"safe": "PillOk", "caution": "PillWarn", "protected": "PillDanger"}.get(del_state, "PillMuted")
        if self.st_insp_del_pill.objectName() != del_pill_obj:
            self.st_insp_del_pill.setObjectName(del_pill_obj)
            self.st_insp_del_pill.style().unpolish(self.st_insp_del_pill)
            self.st_insp_del_pill.style().polish(self.st_insp_del_pill)
        self.st_insp_del_pill.setText(del_label)
        self.st_insp_del_pill.setVisible(bool(del_label))

        self.st_insp_prot_pill.setVisible(bool(node.protected) and del_label != "受保护配置")
        self.st_insp_title.setText(node.name)
        self.st_insp_path.setText(node.path or node.subtitle or "-")

        purpose_text = (node.purpose_desc or "").strip()
        self.st_insp_purpose.setText(purpose_text)
        self.st_insp_purpose.setVisible(bool(purpose_text))

        pct = (node.size_bytes / max(1, total_root_bytes)) * 100.0
        self.st_stat_size.setText(format_bytes(node.size_bytes))
        self.st_stat_share.setText(f"{pct:.1f}%")
        self.st_stat_count.setText(str(node.file_count))

        has_session_files = False
        if node.kind == "session":
            has_session_files = any(ch.kind == "session_files" and ch.file_count > 0 for ch in node.children)
        elif node.kind == "session_files":
            has_session_files = bool(node.delete_targets)

        show_session_actions = node.kind in ("session", "session_files") and bool(node.session_id)
        self.st_btn_clean_files.setVisible(show_session_actions)
        self.st_btn_clean_files.setEnabled(has_session_files)

        self.st_btn_del_session.setVisible(node.kind == "session" and bool(node.session_id))
        self.st_btn_del_session.setEnabled(node.kind == "session" and bool(node.session_id))

        show_generic_del = node.kind not in ("root", "session", "session_files", "aggregate")
        self.st_btn_del_item.setVisible(show_generic_del)
        self.st_btn_del_item.setText("删除此文件" if node.kind == "file" else "清理此项")
        self.st_btn_del_item.setEnabled(bool(node.delete_targets))

        self.st_btn_drill.setEnabled(bool(node.children))
        can_reveal = bool(node.path) and Path(node.path).exists()
        self.st_btn_reveal.setEnabled(can_reveal)

    def _clear_storage_rank_list(self) -> None:
        if hasattr(self, "storage_rank_list"):
            self._clear_vbox(self.storage_rank_list)

    def _render_storage_ranked_list(self, focus_node: StorageNode, selected_id: str) -> None:
        self._clear_storage_rank_list()
        children = sorted(focus_node.children, key=lambda n: n.size_bytes, reverse=True)
        self.st_rank_hdr_lbl.setText(f"当前层级（{len(children)} 项）")

        if not children:
            empty = QLabel("当前层级无更多子项")
            empty.setObjectName("MutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setContentsMargins(0, 28, 0, 28)
            self.storage_rank_list.addWidget(empty)
            self.storage_rank_list.addStretch(1)
            return

        parent_bytes = max(1, focus_node.size_bytes)
        for ch in children[:120]:
            row = ClickableRow("RankedItemRow")
            row.setProperty("selected", ch.node_id == selected_id)
            row.setProperty("nodeId", ch.node_id)
            row.setMinimumHeight(60)
            row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            row.clicked.connect(lambda _n=ch: self._on_storage_ranked_clicked(_n))
            row.doubleClicked.connect(lambda _n=ch: self._on_storage_node_activated(_n))

            r_lay = QVBoxLayout(row)
            r_lay.setContentsMargins(10, 8, 10, 8)
            r_lay.setSpacing(4)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)
            display_title = f"🛡 {ch.name}" if ch.protected else ch.name
            title_lbl = self._row_label(display_title, "CardTitle")
            size_lbl = QLabel(format_bytes(ch.size_bytes))
            size_lbl.setObjectName("MonoLabel")
            top_row.addWidget(title_lbl, 1)
            top_row.addWidget(size_lbl)
            r_lay.addLayout(top_row)

            sub_text = ch.subtitle or f"{ch.file_count} 文件 · {format_mtime(ch.mtime)}"
            sub_lbl = self._row_label(sub_text, "FaintLabel")
            r_lay.addWidget(sub_lbl)

            bar = QProgressBar()
            bar.setObjectName("StorageBar")
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(max(8, min(1000, int((ch.size_bytes / parent_bytes) * 1000))))
            r_lay.addWidget(bar)

            self.storage_rank_list.addWidget(row)

        self.storage_rank_list.addStretch(1)
        cont = self.storage_rank_list.parentWidget()
        if cont is not None:
            cont.updateGeometry()
            cont.adjustSize()

    def _sync_storage_rank_selection(self, selected_id: str) -> None:
        if not hasattr(self, "storage_rank_list"):
            return
        for i in range(self.storage_rank_list.count()):
            w = self.storage_rank_list.itemAt(i).widget()
            if w is not None and w.property("nodeId") is not None:
                is_sel = w.property("nodeId") == selected_id
                if bool(w.property("selected")) != is_sel:
                    w.setProperty("selected", is_sel)
                    w.style().unpolish(w)
                    w.style().polish(w)

    def _find_selected_storage_node(self) -> StorageNode | None:
        if not self._storage_tree_root:
            return None
        focus_node, _ = self._find_storage_trail(
            self._storage_tree_root, self._storage_path_ids, self._storage_agg_members
        )
        if focus_node.node_id == self._storage_selected_id:
            return focus_node
        found = next((c for c in focus_node.children if c.node_id == self._storage_selected_id), None)
        if found is None:
            for mid in focus_node.children:
                found = next((gc for gc in mid.children if gc.node_id == self._storage_selected_id), None)
                if found is not None:
                    break
        if found is None and hasattr(self, "storage_treemap"):
            found = self.storage_treemap.node_for_id(self._storage_selected_id)
        return found or focus_node

    def _set_storage_hover_hint(self, text: str, tone: str = "") -> None:
        if not hasattr(self, "storage_hover_lbl"):
            return
        lbl = self.storage_hover_lbl
        if str(lbl.property("tone") or "") != tone:
            lbl.setProperty("tone", tone)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        avail = lbl.width() - 4
        shown = QFontMetricsF(lbl.font()).elidedText(text, Qt.TextElideMode.ElideRight, float(avail)) if avail > 60 else text
        lbl.setText(shown)
        lbl.setToolTip(text if shown != text else "")

    def _on_storage_node_hovered(self, node: StorageNode | None) -> None:
        if not hasattr(self, "storage_hover_lbl"):
            return
        if node is None:
            self._set_storage_hover_hint("悬停任意方块查看该目录/文件存放的内容及是否可安全删除", "")
            return
        if node.kind == "aggregate" and not node.purpose_desc:
            desc = node.subtitle or "多个较小条目聚合；双击可展开或从右侧排行逐项查看。"
            self._set_storage_hover_hint(f"[聚合项] {desc}", "")
            return
        tone = node.deletability if node.deletability in ("safe", "caution", "protected") else (
            "protected" if node.protected else ""
        )
        del_label = (node.deletability_label or "").strip() or (
            "受保护配置" if node.protected else ("可安全清理" if tone == "safe" else "说明")
        )
        desc = (node.purpose_desc or "").strip() or (node.subtitle or "").strip() or "本地 AGY 存储条目"
        self._set_storage_hover_hint(f"[{del_label}] {desc}", tone)

    def _on_storage_ranked_clicked(self, node: StorageNode) -> None:
        self._storage_selected_id = node.node_id
        self.storage_treemap.set_selected_id(node.node_id)
        self._sync_storage_rank_selection(node.node_id)
        total_root = max(1, self._storage_tree_root.size_bytes) if self._storage_tree_root else 1
        self._render_storage_inspector(node, total_root)

    def _on_storage_node_selected(self, node: StorageNode) -> None:
        self._storage_selected_id = node.node_id
        self._sync_storage_rank_selection(node.node_id)
        total_root = max(1, self._storage_tree_root.size_bytes) if self._storage_tree_root else 1
        self._render_storage_inspector(node, total_root)

    def _on_storage_node_activated(self, node: StorageNode) -> None:
        if not node.children or not self._storage_tree_root:
            return
        focus_node, _ = self._find_storage_trail(
            self._storage_tree_root, self._storage_path_ids, self._storage_agg_members
        )
        if node.kind == "aggregate":
            self._storage_agg_members[node.node_id] = [c.node_id for c in node.children]

        anchor_id = ""
        if any(c.node_id == node.node_id for c in focus_node.children):
            anchor_id = node.node_id
            self._storage_path_ids.append(node.node_id)
        elif node.kind == "aggregate" and node.node_id == f"__agg__:{focus_node.node_id}":
            anchor_id = node.node_id
            self._storage_path_ids.append(node.node_id)
        else:
            for mid in focus_node.children:
                if any(gc.node_id == node.node_id for gc in mid.children) or (
                    node.kind == "aggregate" and node.node_id == f"__agg__:{mid.node_id}"
                ):
                    anchor_id = node.node_id
                    self._storage_path_ids.append(mid.node_id)
                    self._storage_path_ids.append(node.node_id)
                    break
        if not anchor_id:
            return
        self._pending_treemap_transition = ("in", anchor_id)
        self._storage_selected_id = ""
        self._render_storage_view()

    def _on_storage_context_menu(self, node: StorageNode, global_pos: QPoint) -> None:
        self._on_storage_node_selected(node)
        menu = QMenu(self)
        if node.kind in ("session", "session_files") and node.session_id:
            has_files = (
                any(ch.kind == "session_files" and ch.file_count > 0 for ch in node.children)
                if node.kind == "session"
                else bool(node.delete_targets)
            )
            if has_files:
                act_clean = QAction("仅删除会话产出文件（保留历史记录）", self)
                act_clean.triggered.connect(lambda: self._storage_action_clean_session_files(node))
                menu.addAction(act_clean)
            if node.kind == "session":
                act_del_sess = QAction("删除整个会话（文件 + 记录）", self)
                act_del_sess.triggered.connect(lambda: self._storage_action_delete_session(node))
                menu.addAction(act_del_sess)
        elif node.kind != "root" and node.delete_targets:
            act_del = QAction("删除此文件" if node.kind == "file" else "清理此项", self)
            act_del.triggered.connect(lambda: self._storage_action_delete_selected(node))
            menu.addAction(act_del)

        if node.children:
            act_drill = QAction("深入查看子项", self)
            act_drill.triggered.connect(lambda: self._on_storage_node_activated(node))
            menu.addAction(act_drill)

        if node.path and Path(node.path).exists():
            act_open = QAction("打开所在目录", self)
            act_open.triggered.connect(lambda: self._storage_action_open_explorer(node))
            menu.addAction(act_open)

        if not menu.isEmpty():
            menu.exec(global_pos)

    def _storage_action_drill_selected(self) -> None:
        node = self._find_selected_storage_node()
        if node and node.children:
            self._on_storage_node_activated(node)

    def _storage_action_open_explorer(self, node: StorageNode | None = None) -> None:
        target = node or self._find_selected_storage_node()
        if not target or not target.path:
            return
        p = Path(target.path)
        if not p.exists():
            return
        try:
            if p.is_file() and os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(p)])
            else:
                folder = p if p.is_dir() else p.parent
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as exc:
            self._notify_error(str(exc))

    def _storage_action_clean_session_files(self, node: StorageNode | None = None) -> None:
        target = node or self._find_selected_storage_node()
        if not target or not target.session_id or not self._storage_snapshot:
            return
        files_node = (
            next((c for c in target.children if c.kind == "session_files"), None)
            if target.kind == "session"
            else target
        )
        size_val = files_node.size_bytes if files_node else target.size_bytes
        cnt_val = files_node.file_count if files_node else target.file_count
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title="仅删除会话产出文件",
            description="将清理此会话产生的图片、制品、日志与临时文件，保留对话记录 (.pb / .pbtxt) 以便在 Antigravity 历史列表中仍可追溯。",
            target_name=target.name,
            target_path=(files_node.path if files_node else target.path),
            size_text=format_bytes(size_val),
            file_count=cnt_val,
            is_protected=target.protected,
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            sid = target.session_id
            perm = dlg.permanent
            self._execute_storage_delete(lambda: self.manager.delete_storage_session_files(snap, sid, permanent=perm))

    def _storage_action_delete_session(self, node: StorageNode | None = None) -> None:
        target = node or self._find_selected_storage_node()
        if not target or not target.session_id or not self._storage_snapshot:
            return
        cdp_info = (self._overview or {}).get("cdp") or {}
        agy_running = int(cdp_info.get("processCount") or cdp_info.get("mainProcessCount") or 0) > 0
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title="删除整个会话",
            description="将删除该会话全部产出文件、对话本体 (.pb / .db) 与元数据 (.pbtxt)；若 Antigravity 未运行，还将同步移除历史索引与对话列表记录。",
            target_name=target.name,
            target_path=f"会话 ID: {target.session_id}",
            size_text=format_bytes(target.size_bytes),
            file_count=target.file_count,
            is_protected=target.protected,
            agy_running_warning=agy_running,
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            sid = target.session_id
            perm = dlg.permanent
            self._execute_storage_delete(lambda: self.manager.delete_storage_session(snap, sid, permanent=perm))

    def _storage_action_delete_selected(self, node: StorageNode | None = None) -> None:
        target = node or self._find_selected_storage_node()
        if not target or not target.delete_targets or not self._storage_snapshot:
            return
        title = "删除文件" if target.kind == "file" else "清理选定目录 / 分类"
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title=title,
            description="将清理以下路径对应的本地存储内容，默认安全移入 Windows 回收站。",
            target_name=target.name,
            target_path=target.path or "\n".join(target.delete_targets[:3]),
            size_text=format_bytes(target.size_bytes),
            file_count=target.file_count,
            is_protected=target.protected,
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            paths = list(target.delete_targets)
            perm = dlg.permanent
            self._execute_storage_delete(lambda: self.manager.delete_storage_paths(snap, paths, permanent=perm))

    def _storage_batch_clean_session_files(self) -> None:
        if not self._storage_snapshot:
            return
        selected_nodes = [
            n
            for n in self._storage_list_items
            if n.node_id in self._storage_list_selected_ids and n.session_id and self._session_storage_breakdown(n)[0] > 0
        ]
        if not selected_nodes:
            return
        sids = [n.session_id for n in selected_nodes]
        total_b = sum(self._session_storage_breakdown(n)[0] for n in selected_nodes)
        total_fc = sum(self._session_storage_breakdown(n)[2] for n in selected_nodes)
        target_name = selected_nodes[0].name if len(selected_nodes) == 1 else f"共 {len(selected_nodes)} 个会话（仅产出文件）"
        preview = "\n".join(f"• {n.name} ({n.session_id[:8]})" for n in selected_nodes[:5])
        if len(selected_nodes) > 5:
            preview += f"\n... 以及其余 {len(selected_nodes) - 5} 个会话"
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title="批量仅删除会话文件（保留记录）",
            description="将仅删除所选会话的 brain 产出文件（图片、产物、日志与工作区），保留对话记录 (.pb / .db / .pbtxt) 以便继续在历史列表中追溯。",
            target_name=target_name,
            target_path=preview,
            size_text=format_bytes(total_b),
            file_count=total_fc,
            is_protected=False,
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            perm = dlg.permanent
            self._execute_storage_delete(
                lambda: self.manager.delete_storage_multiple_session_files(snap, sids, permanent=perm)
            )

    def _storage_batch_delete_sessions(self) -> None:
        if not self._storage_snapshot:
            return
        selected_nodes = [
            n for n in self._storage_list_items if n.node_id in self._storage_list_selected_ids and n.session_id
        ]
        if not selected_nodes:
            return
        sids = [n.session_id for n in selected_nodes]
        total_b = sum(n.size_bytes for n in selected_nodes)
        total_fc = sum(n.file_count for n in selected_nodes)
        cdp_info = (self._overview or {}).get("cdp") or {}
        agy_running = int(cdp_info.get("processCount") or cdp_info.get("mainProcessCount") or 0) > 0
        target_name = selected_nodes[0].name if len(selected_nodes) == 1 else f"共 {len(selected_nodes)} 个会话（完整会话）"
        preview = "\n".join(f"• {n.name} ({n.session_id[:8]})" for n in selected_nodes[:5])
        if len(selected_nodes) > 5:
            preview += f"\n... 以及其余 {len(selected_nodes) - 5} 个会话"
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title="批量删除所选会话",
            description="将删除所选会话的全部产出文件、对话本体 (.pb / .db) 与元数据 (.pbtxt)；若 Antigravity 未运行，还将同步清理历史索引与对话列表记录。",
            target_name=target_name,
            target_path=preview,
            size_text=format_bytes(total_b),
            file_count=total_fc,
            is_protected=False,
            agy_running_warning=agy_running,
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            perm = dlg.permanent
            self._execute_storage_delete(
                lambda: self.manager.delete_storage_multiple_sessions(snap, sids, permanent=perm)
            )

    def _storage_batch_delete_items(self) -> None:
        if not self._storage_snapshot:
            return
        selected_nodes = [
            n
            for n in self._storage_list_items
            if n.node_id in self._storage_list_selected_ids and not n.protected and n.delete_targets
        ]
        if not selected_nodes:
            return
        seen_paths: set[str] = set()
        paths: list[str] = []
        for n in selected_nodes:
            for p in n.delete_targets:
                if p not in seen_paths:
                    seen_paths.add(p)
                    paths.append(p)
        total_b = sum(n.size_bytes for n in selected_nodes)
        total_fc = sum(n.file_count for n in selected_nodes)
        target_name = selected_nodes[0].name if len(selected_nodes) == 1 else f"共 {len(selected_nodes)} 个存储条目"
        preview = "\n".join(f"• {n.name}" for n in selected_nodes[:5])
        if len(selected_nodes) > 5:
            preview += f"\n... 以及其余 {len(selected_nodes) - 5} 项"
        dlg = StorageDeleteConfirmDialog(
            self,
            action_title="批量清理所选条目",
            description="将清理以下所选目录或文件对应的本地存储内容，默认安全移入 Windows 回收站。",
            target_name=target_name,
            target_path=preview,
            size_text=format_bytes(total_b),
            file_count=total_fc,
            is_protected=any(n.protected for n in selected_nodes),
            theme_mode=self._theme_mode,
        )
        if dlg.exec() == StorageDeleteConfirmDialog.DialogCode.Accepted:
            snap = self._storage_snapshot
            perm = dlg.permanent
            self._execute_storage_delete(lambda: self.manager.delete_storage_paths(snap, paths, permanent=perm))

    def _clean_orphan_storage_summaries(self) -> None:
        if not self._storage_snapshot:
            return
        orphan_ids = list(getattr(self._storage_snapshot, "orphan_summary_ids", ()) or ())
        if not orphan_ids:
            self._show_toast("当前没有失效的历史列表记录")
            return
        if self.manager.is_antigravity_active():
            QMessageBox.information(
                self,
                "请先关闭 Antigravity",
                "检测到 Antigravity（或其后台语言服务）仍在运行。\n\n"
                "为防止内存中的历史列表重新覆盖磁盘索引，请先完全退出 Antigravity 后，再点击「清理失效记录」。",
            )
            return
        ans = QMessageBox.question(
            self,
            "清理失效会话列表记录",
            f"检测到 {len(orphan_ids)} 条本地对话文件已不存在的失效记录"
            "（通常来自此前清理文件后仍停留在 Antigravity 侧栏的幽灵会话）。\n\n"
            "确认将它们从 conversation_summaries.db、agyhub_summaries_proto.pb 与 app_storage.json 中同步移除吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans == QMessageBox.StandardButton.Yes:
            snap = self._storage_snapshot
            self._execute_storage_delete(lambda: self.manager.clean_orphan_storage_summaries(snap))

    def _execute_storage_delete(self, fn: Callable[[], dict[str, Any]]) -> None:
        self._show_toast("正在清理存储...")

        def done(res: dict[str, Any]) -> None:
            freed = format_bytes(int(res.get("freedBytes") or 0))
            cnt = int(res.get("deletedCount") or len(res.get("deletedPaths") or []))
            locked_paths = [str(p) for p in (res.get("lockedPaths") or []) if str(p).strip()]
            warnings = [str(w) for w in (res.get("warnings") or []) if str(w).strip()]
            mode = str(res.get("mode") or "")

            if mode == "orphan_summaries":
                if res.get("antigravityRunning"):
                    self._show_toast("Antigravity 正在运行，请先关闭后重试")
                    QMessageBox.information(
                        self,
                        "请先关闭 Antigravity",
                        "检测到 Antigravity 正在运行，暂未修改历史索引数据库；请先关闭 Antigravity 后重试。",
                    )
                elif cnt > 0 and not (res.get("dbCleaned") or res.get("protoCleaned") or res.get("appStorageCleaned")):
                    self._show_toast("未能写入历史索引（可能仍被占用），请确认 AGY 已彻底退出")
                    QMessageBox.warning(
                        self,
                        "未能清理失效记录",
                        "历史数据库或缓存文件可能仍被占用，未能移除这些记录；请确认 Antigravity 已完全退出后再试。",
                    )
                else:
                    self._show_toast(f"已同步移除 {cnt} 条失效列表记录")
            elif locked_paths or warnings:
                if cnt > 0:
                    self._show_toast(f"部分清理：释放 {freed}，{len(locked_paths) or len(warnings)} 项被占用未删")
                else:
                    self._show_toast("文件正被占用，未能删除（请先关闭 Antigravity）")
                details = "\n".join(f"• {w}" for w in (warnings or locked_paths)[:6])
                if len(warnings or locked_paths) > 6:
                    details += f"\n... 以及其余 {len(warnings or locked_paths) - 6} 项"
                QMessageBox.warning(
                    self,
                    "部分文件正被程序占用",
                    "以下文件正被运行中的 Antigravity 或其他程序占用，暂时无法删除；其余未占用文件已完成清理。\n\n"
                    "如需彻底删除这些会话并同步更新 Antigravity 对话列表，请先退出 Antigravity 后重试：\n"
                    f"{details}",
                )
            else:
                mode_lbl = "已彻底删除" if res.get("permanent") else "已移入回收站"
                extra = ""
                if mode == "session" and res.get("antigravityRunning"):
                    extra = "（AGY 运行中未同步列表；关闭 AGY 后可点“清理失效记录”）"
                elif mode == "session" and (res.get("dbCleaned") or res.get("protoCleaned")):
                    extra = " · 已同步 Antigravity 对话列表"
                self._show_toast(f"{mode_lbl} {cnt} 项 · 释放 {freed}{extra}")
            self._storage_list_selected_ids.clear()
            self._storage_list_last_idx = None
            self._refresh_storage_scan()

        self._run_async(fn, done)

    def refresh_logs(self) -> None:
        log_id = self.log_source_combo.currentData() or "launcher"
        tail = int(self.log_tail_combo.currentData() or 200)
        try:
            data = self.manager.read_log_tail(str(log_id), tail)
            self.log_path_lbl.setText(data["path"])
            self.log_bytes_lbl.setText(format_bytes(data["bytes"]))
            content = data["content"].strip() or "暂无日志"
            sb = self.log_console.verticalScrollBar()
            at_bottom = (sb.maximum() - sb.value()) <= 12
            if self.log_console.toPlainText() != content:
                self.log_console.setPlainText(content)
                if at_bottom:
                    sb.setValue(sb.maximum())
        except Exception as exc:
            self.log_console.setPlainText(f"读取失败: {exc}")

    def _toggle_log_stream(self) -> None:
        self._log_streaming = not self._log_streaming
        self.log_stream_btn.setText("暂停" if self._log_streaming else "继续")
        if self._log_streaming and self.stack.currentIndex() == PAGE_LOGS:
            self.refresh_logs()
            self._log_timer.start()
        else:
            self._log_timer.stop()

    def _clear_current_log(self) -> None:
        log_id = str(self.log_source_combo.currentData() or "launcher")
        try:
            self.manager.clear_log(log_id)
            self.log_console.setPlainText("暂无日志")
            self.log_bytes_lbl.setText("0 B")
            self._show_toast("已清空日志")
        except Exception as exc:
            QMessageBox.warning(self, "清空失败", str(exc))
