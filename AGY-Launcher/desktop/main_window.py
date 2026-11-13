from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QMimeData, QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from desktop.core import APP_VERSION, AgyProcessManager, build_update_urls, validate_update_site_url
from desktop.dialogs import PluginEditorDialog
from desktop.icons import native_graphic_svg, plugin_graphic_svg, render_svg_pixmap
from desktop.theme import apply_dwm_titlebar_theme, build_stylesheet, get_palette, resolve_is_dark

THEME_MODES = ("auto", "light", "dark")
THEME_LABELS = {"auto": "外观：自动", "light": "外观：浅色", "dark": "外观：深色"}
SUPPORTED_PACKAGE_EXTS = (".zip", ".agypkg", ".agy-plugin")
DROP_HINT_IDLE_TEXT = "拖入插件安装包 (.zip / .agypkg) 自动安装"
DROP_HINT_ACTIVE_TEXT = "松开鼠标立即安装插件包 (.zip / .agypkg)"


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
    """Row container that emits clicked() cleanly while ignoring clicks on interactive children."""

    clicked = Signal()

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            child = self.childAt(event.position().toPoint())
            if not isinstance(child, (QPushButton, ToggleSwitch)):
                self.clicked.emit()
        super().mouseReleaseEvent(event)


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
                self.signals.failed.emit(f"{exc}\n{traceback.format_exc(limit=1)}".strip())
            except RuntimeError:
                pass


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


class MainWindow(QMainWindow):
    """V5 Hybrid desktop UI: Top centered capsule navigation + pure-white status home + scalable plugin directory."""

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

        QTimer.singleShot(40, self.refresh_all)
        update_cfg = config.get("update") if isinstance(config.get("update"), dict) else {}
        if update_cfg.get("autoCheckOnStartup", True) is not False:
            QTimer.singleShot(450, lambda: self._check_for_updates(manual=False))

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
        self.stack.addWidget(self._build_status_tab())           # 0: Status Home (V4 Proposal B)
        self.stack.addWidget(self._build_external_tab())         # 1: My Plugins (Scalable catalog)
        self.stack.addWidget(self._build_marketplace_tab())      # 2: Marketplace (Scalable registry/local discover)
        self.stack.addWidget(self._build_native_tab())           # 3: Native Extensions
        self.stack.addWidget(self._build_logs_tab())             # 4: Live Logs
        self.stack.addWidget(self._build_settings_tab())         # 5: Settings & Maintenance
        self.stack.addWidget(self._build_external_detail_tab())  # 6: External Detail
        self.stack.addWidget(self._build_native_detail_tab())    # 7: Native Detail
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
        brand_box.setSpacing(10)
        logo_frame = QFrame()
        logo_frame.setObjectName("CapsuleDock")
        logo_frame.setFixedSize(28, 28)
        logo_lay = QVBoxLayout(logo_frame)
        logo_lay.setContentsMargins(4, 4, 4, 4)
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setPixmap(self._load_brand_pixmap(18))
        logo_lay.addWidget(logo_lbl)

        title_lbl = QLabel("AGY Plugin Manager")
        title_lbl.setObjectName("BrandTitle")
        brand_box.addWidget(logo_frame)
        brand_box.addWidget(title_lbl)
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
        nav_labels = ("运行状态", "我的插件", "插件市场", "原生扩展", "日志", "设置")
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
        if self.stack.currentIndex() == 0:
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
    # Page 4: Logs
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
    # Page 5: Settings & Maintenance
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
        u_hdr.addWidget(self.update_current_ver_tag)
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
    # Page 6 & 7: Clean Secondary Detail Views
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
        back_btn.clicked.connect(lambda: self._switch_tab(1))

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
        back_btn.clicked.connect(lambda: self._switch_tab(3))
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
        if hasattr(self, "_update_banner_shadow"):
            self._update_banner_shadow.setColor(QColor(0, 0, 0, 120 if is_dark else 42))
        apply_dwm_titlebar_theme(self, is_dark)
        if self._overview:
            self._render_overview()

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

    def _quit_completely(self) -> None:
        self._force_quit = True
        self._overview_timer.stop()
        self._log_timer.stop()
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
        self._overview_timer.stop()
        self._log_timer.stop()
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
        active_nav = 1 if index == 6 else (3 if index == 7 else index)
        for i, btn in enumerate(self.tab_buttons):
            btn.setChecked(i == active_nav)

        self.top_action_btn.setText("刷新状态" if index == 0 else "唤醒 Antigravity")

        if index == 4 and self._log_streaming:
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

        # 3. Active Spotlight
        self.active_ratio_lbl.setText(f"{len(running_plugins)} / {len(plugins)}")
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
        if self.stack.currentIndex() == 6 and self._selected_plugin_id:
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
            pid_lbl = self._row_label(f"进程 {', '.join(map(str, pids))}" if pids else "运行中", "DotOk")
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
            running = bool(p.get("running"))
            enabled = p.get("enabled", True) is not False
            status_pill = QLabel()
            status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status_pill.setFixedWidth(118)
            if running:
                status_pill.setObjectName("PillOk")
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

        if self.stack.currentIndex() == 7 and self._selected_native_dir:
            self._populate_native_detail(self._selected_native_dir)

    # ------------------------------------------------------------------
    # Secondary Detail Pages (Index 6 & 7)
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
        self._switch_tab(6)

    def _populate_external_detail(self, plugin_id: str) -> None:
        p = self._find_plugin(plugin_id)
        if not p:
            self._switch_tab(1)
            return
        self.det_icon_lbl.setPixmap(
            render_svg_pixmap(plugin_graphic_svg(p["id"], p.get("type") or "", p.get("name") or ""), logical_px=56)
        )
        self.det_title_lbl.setText(p.get("name") or p["id"])
        self.det_desc_lbl.setText(p.get("description") or "外部托管插件")

        pids = p.get("pids") or []
        running = bool(p.get("running"))
        enabled = p.get("enabled", True) is not False
        if running:
            self._set_dot(self.det_status_lbl, "ok", f"● 运行中 · 进程 {', '.join(map(str, pids))}" if pids else "● 运行中")
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
        self._switch_tab(7)

    def _populate_native_detail(self, dir_name: str) -> None:
        item = next((x for x in (self._native_plugins or []) if x.get("dir") == dir_name), None)
        if not item:
            self._switch_tab(3)
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
        if self.stack.currentIndex() == 5:
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

        def done(_res: dict[str, Any]) -> None:
            self.quick_launch_btn.setEnabled(True)
            self._show_toast("Antigravity 已就绪")
            self.refresh_all()

        def fail(err: str) -> None:
            self.quick_launch_btn.setEnabled(True)
            QMessageBox.warning(self, "启动失败", err)
            self._notify_error(err)

        self._run_async(run, done, fail)

    def _attach_enabled(self) -> None:
        self.home_attach_btn.setEnabled(False)
        if hasattr(self, "attach_btn"):
            self.attach_btn.setEnabled(False)
        self._show_toast("正在热附着插件...")

        def done(_res: Any) -> None:
            self.home_attach_btn.setEnabled(True)
            if hasattr(self, "attach_btn"):
                self.attach_btn.setEnabled(True)
            self._show_toast("热附着完成")
            self.refresh_all()

        def fail(err: str) -> None:
            self.home_attach_btn.setEnabled(True)
            if hasattr(self, "attach_btn"):
                self.attach_btn.setEnabled(True)
            self._notify_error(err)

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
        self._switch_tab(4)

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
                self._switch_tab(1)
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
        if self._log_streaming and self.stack.currentIndex() == 4:
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
