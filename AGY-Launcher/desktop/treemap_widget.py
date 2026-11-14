from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QRectF, QTimer, QVariantAnimation, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from desktop.storage import StorageNode, format_storage_bytes
from desktop.theme import get_palette


@dataclass
class _PaintRegion:
    rect: QRectF
    node: StorageNode
    parent_node: StorageNode | None
    is_header: bool = False


_CATEGORY_COLORS_LIGHT: dict[str, tuple[str, str, str]] = {
    # (fill, header_fill, border)
    "session": ("#EBF2FE", "#DCE8FC", "#93B7F8"),
    "conversations": ("#EEF0FE", "#E0E4FD", "#9DA5F7"),
    "docs": ("#E8F7F1", "#D5F1E5", "#7FD4B3"),
    "images": ("#E7F7F5", "#D2F0EC", "#6DCFC5"),
    "videos": ("#FDF0F6", "#F9DFEB", "#ECA5C6"),
    "audio": ("#F5F0FD", "#EAE0FC", "#C2A6F4"),
    "logs": ("#FEF6E7", "#FCECCB", "#F0BE65"),
    "code": ("#EFF6FF", "#DFECFE", "#8EB8F8"),
    "cache": ("#FFF1E8", "#FDE2D1", "#F2A574"),
    "rules": ("#F5EEFE", "#EADCFD", "#B888F3"),
    "other": ("#F1F4F8", "#E4E8EF", "#BDC6D4"),
}

_CATEGORY_COLORS_DARK: dict[str, tuple[str, str, str]] = {
    "session": ("#1B2840", "#223454", "#3B66AD"),
    "conversations": ("#212344", "#2A2D58", "#5056A8"),
    "docs": ("#162F28", "#1C3D34", "#2B7A62"),
    "images": ("#153031", "#1B3F40", "#297A7D"),
    "videos": ("#361D2C", "#462439", "#8E4370"),
    "audio": ("#2A1F3D", "#362750", "#6B4CA3"),
    "logs": ("#342815", "#44341B", "#9A7029"),
    "code": ("#1A293D", "#213650", "#3D679D"),
    "cache": ("#382317", "#492D1D", "#9E5830"),
    "rules": ("#2C1E3E", "#392752", "#7C4FB5"),
    "other": ("#202632", "#28303F", "#475368"),
}


def compute_squarified_layout(
    items: list[tuple[Any, float]],
    rect: QRectF,
) -> list[tuple[Any, QRectF]]:
    """Computes a Bruls-Huizing-van Wijk squarified treemap layout inside rect."""
    if rect.width() <= 0.5 or rect.height() <= 0.5:
        return []
    positive = [(item, float(val)) for item, val in items if float(val) > 0]
    if not positive:
        return []
    positive.sort(key=lambda pair: pair[1], reverse=True)

    total_val = sum(v for _, v in positive)
    total_area = rect.width() * rect.height()
    if total_val <= 0 or total_area <= 0:
        return []

    scaled: list[tuple[Any, float]] = [(item, (val / total_val) * total_area) for item, val in positive]
    results: list[tuple[Any, QRectF]] = []

    cx = float(rect.x())
    cy = float(rect.y())
    cw = float(rect.width())
    ch = float(rect.height())

    def _worst_ratio(row: list[tuple[Any, float]], side: float) -> float:
        if not row or side <= 0:
            return float("inf")
        area_sum = sum(a for _, a in row)
        if area_sum <= 0:
            return float("inf")
        max_a = max(a for _, a in row)
        min_a = min(a for _, a in row)
        s2 = side * side
        sum2 = area_sum * area_sum
        return max((s2 * max_a) / sum2, sum2 / (s2 * min_a))

    idx = 0
    n = len(scaled)
    while idx < n and cw > 0.2 and ch > 0.2:
        short_side = min(cw, ch)
        horizontal = cw >= ch
        row: list[tuple[Any, float]] = [scaled[idx]]
        idx += 1
        while idx < n:
            candidate = [*row, scaled[idx]]
            if _worst_ratio(candidate, short_side) <= _worst_ratio(row, short_side):
                row = candidate
                idx += 1
            else:
                break

        row_area = sum(a for _, a in row)
        if horizontal:
            strip_w = min(cw, row_area / ch) if ch > 0 else cw
            ry = cy
            for item, area in row:
                item_h = (area / strip_w) if strip_w > 0 else 0.0
                results.append((item, QRectF(cx, ry, strip_w, max(0.0, item_h))))
                ry += item_h
            cx += strip_w
            cw = max(0.0, cw - strip_w)
        else:
            strip_h = min(ch, row_area / cw) if cw > 0 else ch
            rx = cx
            for item, area in row:
                item_w = (area / strip_h) if strip_h > 0 else 0.0
                results.append((item, QRectF(rx, cy, max(0.0, item_w), strip_h)))
                rx += item_w
            cy += strip_h
            ch = max(0.0, ch - strip_h)

    return results


def format_compact_bytes(size: int | float) -> str:
    """Formats a byte count into ultra-compact labels (e.g. 5.2M, 440K) for narrow tiles."""
    val = max(0.0, float(size or 0))
    if val < 1024.0:
        return f"{int(val)}B"
    if val < 1024.0 * 1024.0:
        kb = val / 1024.0
        return f"{kb:.0f}K" if kb >= 100.0 else f"{kb:.1f}K"
    if val < 1024.0 * 1024.0 * 1024.0:
        mb = val / (1024.0 * 1024.0)
        return f"{mb:.0f}M" if mb >= 100.0 else f"{mb:.1f}M"
    gb = val / (1024.0 * 1024.0 * 1024.0)
    return f"{gb:.1f}G" if gb >= 10.0 else f"{gb:.2f}G"


def _lerp_rect(src: QRectF, dst: QRectF, t: float) -> QRectF:
    """Linearly interpolates between two QRectF rectangles."""
    return QRectF(
        src.x() + (dst.x() - src.x()) * t,
        src.y() + (dst.y() - src.y()) * t,
        src.width() + (dst.width() - src.width()) * t,
        src.height() + (dst.height() - src.height()) * t,
    )


_SKELETON_TILES: tuple[tuple[str, float], ...] = (
    ("session", 34.0),
    ("conversations", 22.0),
    ("images", 15.0),
    ("cache", 11.0),
    ("logs", 7.5),
    ("docs", 5.5),
    ("code", 4.0),
    ("videos", 3.0),
    ("audio", 2.2),
    ("rules", 1.7),
    ("other", 1.3),
    ("cache", 1.0),
    ("logs", 0.8),
    ("other", 0.6),
)


class SpaceTreemapWidget(QWidget):
    """SpaceSniffer-inspired interactive squarified treemap canvas with nested frames."""

    nodeHovered = Signal(object)
    nodeSelected = Signal(object)
    nodeActivated = Signal(object)
    nodeContextMenuRequested = Signal(object, QPoint)

    def __init__(self, parent: QWidget | None = None, *, is_dark: bool = False) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(340)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._root_node: StorageNode | None = None
        self._total_root_bytes: int = 1
        self._selected_id: str = ""
        self._hovered_id: str = ""
        self._is_dark: bool = bool(is_dark)
        self._regions: list[_PaintRegion] = []
        self._last_rects: dict[str, QRectF] = {}
        self._last_agg_rects: dict[str, QRectF] = {}

        # Zoom transition state
        self._transition_anim: QVariantAnimation | None = None
        self._transition_kind: str = "none"
        self._transition_progress: float = 1.0
        self._transition_old_pixmap: QPixmap | None = None
        self._transition_new_pixmap: QPixmap | None = None
        self._transition_anchor_rect: QRectF = QRectF()

        # Scanning overlay animation state (30fps)
        self._scan_active: bool = False
        self._scan_progress: float = 0.0
        self._scan_status_text: str = ""
        self._scan_files: int = 0
        self._scan_bytes: int = 0
        self._scan_phase: float = 0.0
        self._scan_timer: QTimer = QTimer(self)
        self._scan_timer.setInterval(33)
        self._scan_timer.timeout.connect(self._on_scan_tick)
        self.destroyed.connect(self._scan_timer.stop)

    def set_theme(self, is_dark: bool) -> None:
        if self._is_dark != is_dark:
            self._is_dark = is_dark
            self._stop_transition()
            self.update()

    def rect_for_node(self, node_id: str) -> QRectF | None:
        """Returns the last computed bounding QRectF for node_id inside this widget, or None."""
        rect = self._last_rects.get(node_id)
        return QRectF(rect) if rect is not None else None

    def _work_rect(self) -> QRectF:
        return QRectF(6.0, 6.0, max(0.0, self.width() - 12.0), max(0.0, self.height() - 12.0))

    def _fallback_anchor_rect(self) -> QRectF:
        wr = self._work_rect()
        return QRectF(
            wr.x() + wr.width() * 0.32,
            wr.y() + wr.height() * 0.32,
            max(16.0, wr.width() * 0.36),
            max(16.0, wr.height() * 0.36),
        )

    def _stop_transition(self) -> None:
        anim = self._transition_anim
        self._transition_anim = None
        if anim is not None:
            try:
                anim.valueChanged.disconnect(self._on_transition_value_changed)
                anim.finished.disconnect(self._on_transition_finished)
            except (RuntimeError, TypeError):
                pass
            anim.stop()
            anim.deleteLater()
        self._transition_kind = "none"
        self._transition_progress = 1.0
        self._transition_old_pixmap = None
        self._transition_new_pixmap = None
        self._transition_anchor_rect = QRectF()

    def _on_transition_value_changed(self, value: object) -> None:
        try:
            self._transition_progress = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            self._transition_progress = 1.0
        self.update()

    def _on_transition_finished(self) -> None:
        self._stop_transition()
        self.update()

    def set_root_node(
        self,
        node: StorageNode | None,
        *,
        total_root_bytes: int | None = None,
        selected_id: str = "",
        transition: str = "none",
        anchor_node_id: str = "",
    ) -> None:
        self._stop_transition()

        mode = transition if transition in ("in", "out") else "none"
        can_animate = (
            mode != "none"
            and node is not None
            and self._root_node is not None
            and self._root_node.size_bytes > 0
            and bool(self._root_node.children)
            and self.width() > 16
            and self.height() > 16
        )

        old_pixmap: QPixmap | None = None
        source_anchor_rect: QRectF | None = None
        if can_animate:
            if mode == "in":
                lookup_id = anchor_node_id or self._selected_id
                source_anchor_rect = self.rect_for_node(lookup_id) or (
                    QRectF(self._last_agg_rects[lookup_id]) if lookup_id in self._last_agg_rects else None
                )
            old_pixmap = self._render_scene_pixmap()

        self._root_node = node
        self._total_root_bytes = max(1, int(total_root_bytes or (node.size_bytes if node else 1) or 1))
        self._selected_id = selected_id
        self._hovered_id = ""
        self._rebuild_layout_cache()

        if can_animate and old_pixmap is not None and node is not None and node.size_bytes > 0 and node.children:
            if mode == "out":
                lookup_id = anchor_node_id or selected_id
                target_rect = self.rect_for_node(lookup_id) or (
                    QRectF(self._last_agg_rects[lookup_id]) if lookup_id in self._last_agg_rects else None
                )
                anchor_rect = target_rect if target_rect is not None else self._fallback_anchor_rect()
            else:
                anchor_rect = source_anchor_rect if source_anchor_rect is not None else self._fallback_anchor_rect()

            new_pixmap = self._render_scene_pixmap()
            if new_pixmap is not None:
                self._transition_kind = mode
                self._transition_progress = 0.0
                self._transition_old_pixmap = old_pixmap
                self._transition_new_pixmap = new_pixmap
                self._transition_anchor_rect = anchor_rect

                anim = QVariantAnimation(self)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setDuration(240 if mode == "in" else 230)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.valueChanged.connect(self._on_transition_value_changed)
                anim.finished.connect(self._on_transition_finished)
                self._transition_anim = anim
                anim.start()
                self.update()
                return

        self.update()

    def set_selected_id(self, node_id: str) -> None:
        if self._selected_id != node_id:
            self._selected_id = node_id
            self.update()

    def set_scanning(
        self,
        active: bool,
        progress: float = 0.0,
        status_text: str = "",
        scanned_files: int = 0,
        scanned_bytes: int = 0,
    ) -> None:
        """Controls the SpaceSniffer-style scanning animation and embedded progress overlay."""
        self._scan_active = bool(active)
        self._scan_progress = max(0.0, min(1.0, float(progress or 0.0)))
        self._scan_status_text = str(status_text or "")
        self._scan_files = max(0, int(scanned_files or 0))
        self._scan_bytes = max(0, int(scanned_bytes or 0))

        if self._scan_active:
            if not self._scan_timer.isActive():
                self._scan_timer.start()
        else:
            if self._scan_timer.isActive():
                self._scan_timer.stop()
            self._scan_phase = 0.0
        self.update()

    def _on_scan_tick(self) -> None:
        if not self._scan_active:
            self._scan_timer.stop()
            return
        self._scan_phase = (self._scan_phase + 0.14) % (math.pi * 200.0)
        self.update()

    def resizeEvent(self, event) -> None:
        self._stop_transition()
        self._rebuild_layout_cache()
        super().resizeEvent(event)

    def hideEvent(self, event) -> None:
        if self._scan_timer.isActive():
            self._scan_timer.stop()
        self._stop_transition()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if self._scan_active and not self._scan_timer.isActive():
            self._scan_timer.start()
        super().showEvent(event)

    def _category_style(self, category: str) -> tuple[str, str, str]:
        table = _CATEGORY_COLORS_DARK if self._is_dark else _CATEGORY_COLORS_LIGHT
        return table.get(category, table["other"])

    def _prepare_children(self, node: StorageNode, avail_rect: QRectF, max_items: int) -> list[StorageNode]:
        positive = [c for c in node.children if c.size_bytes > 0]
        if not positive:
            return []
        total = sum(c.size_bytes for c in positive)
        avail_area = avail_rect.width() * avail_rect.height()
        if total <= 0 or avail_area <= 0:
            return []

        visible: list[StorageNode] = []
        tail: list[StorageNode] = []
        min_area = 210.0

        for idx, child in enumerate(positive):
            est_area = (child.size_bytes / total) * avail_area
            if idx < max_items and (est_area >= min_area or idx < 8):
                visible.append(child)
            else:
                tail.append(child)

        if len(tail) == 1:
            visible.append(tail[0])
        elif len(tail) > 1:
            agg_size = sum(t.size_bytes for t in tail)
            agg_count = sum(t.file_count for t in tail)
            visible.append(
                StorageNode(
                    node_id=f"__agg__:{node.node_id}",
                    name=f"其余 {len(tail)} 项",
                    kind="aggregate",
                    category=node.category,
                    size_bytes=agg_size,
                    file_count=agg_count,
                    path=node.path,
                    subtitle=f"双击钻取查看剩余 {len(tail)} 个较小条目",
                    purpose_desc=f"此处折叠了 {len(tail)} 个占用空间较小的条目，双击即可展开逐项查看与清理。",
                    deletability="caution",
                    deletability_label="聚合折叠 · 展开查看",
                    children=tail,
                )
            )
        return visible

    def node_for_id(self, node_id: str) -> StorageNode | None:
        if not node_id:
            return None
        for reg in self._regions:
            if reg.node.node_id == node_id:
                return reg.node
        return None

    def _rebuild_layout_cache(self) -> None:
        self._regions = []
        self._last_rects = {}
        self._last_agg_rects = {}
        root = self._root_node
        if root is None or not root.children or root.size_bytes <= 0:
            return
        if self.width() <= 12 or self.height() <= 12:
            return
        self._process_level(
            None,
            root,
            self._work_rect(),
            depth=0,
            pal=None,
            fonts=None,
            rects_out=self._last_rects,
            agg_rects_out=self._last_agg_rects,
            regions_out=self._regions,
        )

    def _render_scene_pixmap(self) -> QPixmap | None:
        w, h = self.width(), self.height()
        if w <= 2 or h <= 2:
            return None
        dpr = max(1.0, float(self.devicePixelRatioF()))
        pm = QPixmap(max(1, int(round(w * dpr))), max(1, int(round(h * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        pal = get_palette(self._is_dark)
        canvas_rect = QRectF(0.5, 0.5, max(0.0, w - 1.0), max(0.0, h - 1.0))
        work_rect = self._work_rect()
        self._paint_treemap_scene(painter, canvas_rect, work_rect, pal, update_regions=False)
        painter.end()
        return pm

    def _make_fonts(self, depth: int) -> tuple[QFont, QFontMetricsF, QFont, QFontMetricsF, QFont, QFontMetricsF, QFont, QFontMetricsF]:
        base = self.font()
        title_font = QFont(base)
        title_font.setPointSizeF(8.8 if depth == 0 else 8.2)
        title_font.setWeight(QFont.Weight.DemiBold)

        sub_font = QFont(base)
        sub_font.setPointSizeF(8.0)

        compact_title_font = QFont(base)
        compact_title_font.setPointSizeF(7.4)
        compact_title_font.setWeight(QFont.Weight.DemiBold)

        compact_sub_font = QFont(base)
        compact_sub_font.setPointSizeF(7.2)

        return (
            title_font,
            QFontMetricsF(title_font),
            sub_font,
            QFontMetricsF(sub_font),
            compact_title_font,
            QFontMetricsF(compact_title_font),
            compact_sub_font,
            QFontMetricsF(compact_sub_font),
        )

    def paintEvent(self, _event) -> None:
        pal = get_palette(self._is_dark)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        canvas_rect = QRectF(0.5, 0.5, max(0.0, self.width() - 1.0), max(0.0, self.height() - 1.0))
        work_rect = self._work_rect()

        if (
            self._transition_kind in ("in", "out")
            and self._transition_old_pixmap is not None
            and self._transition_new_pixmap is not None
        ):
            self._paint_transition(painter, canvas_rect, pal)
        else:
            self._paint_treemap_scene(painter, canvas_rect, work_rect, pal, update_regions=True)

        if self._scan_active:
            has_data = bool(self._root_node and self._root_node.children and self._root_node.size_bytes > 0)
            if has_data:
                self._paint_rescan_overlay(painter, canvas_rect, work_rect, pal)
            else:
                self._paint_initial_scan_overlay(painter, canvas_rect, work_rect, pal)

    def _paint_transition(self, painter: QPainter, canvas_rect: QRectF, pal: dict[str, str]) -> None:
        old_pm = self._transition_old_pixmap
        new_pm = self._transition_new_pixmap
        if old_pm is None or new_pm is None:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal["surface_soft"]))
        painter.drawRoundedRect(canvas_rect, 12.0, 12.0)

        clip_path = QPainterPath()
        clip_path.addRoundedRect(canvas_rect, 12.0, 12.0)
        painter.save()
        painter.setClipPath(clip_path)

        t = max(0.0, min(1.0, self._transition_progress))
        full_rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        anchor_rect = self._transition_anchor_rect
        if anchor_rect.width() <= 1.0 or anchor_rect.height() <= 1.0:
            anchor_rect = self._fallback_anchor_rect()

        if self._transition_kind == "in":
            # Outgoing parent view zooms outward around anchor center and fades away
            anchor_c = anchor_rect.center()
            bg_scale = 1.0 + 0.16 * t
            bg_rect = QRectF(
                anchor_c.x() - (anchor_c.x() - full_rect.x()) * bg_scale,
                anchor_c.y() - (anchor_c.y() - full_rect.y()) * bg_scale,
                full_rect.width() * bg_scale,
                full_rect.height() * bg_scale,
            )
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(max(0.0, 1.0 - t * 1.15))
            painter.drawPixmap(bg_rect, old_pm, QRectF(old_pm.rect()))
            painter.restore()

            # Incoming child view expands smoothly from anchor_rect -> full_rect
            cur_rect = _lerp_rect(anchor_rect, full_rect, t)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(min(1.0, 0.25 + 0.75 * (t ** 0.7)))
            in_path = QPainterPath()
            in_path.addRoundedRect(cur_rect, 7.0 + 5.0 * t, 7.0 + 5.0 * t)
            painter.setClipPath(in_path, Qt.ClipOperation.IntersectClip)
            painter.drawPixmap(cur_rect, new_pm, QRectF(new_pm.rect()))
            painter.restore()

            border_alpha = int(max(0, round(150 * (1.0 - t))))
            if border_alpha > 4:
                c = QColor(pal["accent"])
                c.setAlpha(border_alpha)
                painter.setPen(QPen(c, 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(cur_rect, 7.0 + 5.0 * t, 7.0 + 5.0 * t)
        else:
            # Incoming parent view fades in and gently settles from slight zoom
            target_c = anchor_rect.center()
            bg_scale = 1.0 + 0.06 * (1.0 - t)
            bg_rect = QRectF(
                target_c.x() - (target_c.x() - full_rect.x()) * bg_scale,
                target_c.y() - (target_c.y() - full_rect.y()) * bg_scale,
                full_rect.width() * bg_scale,
                full_rect.height() * bg_scale,
            )
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(0.30 + 0.70 * t)
            painter.drawPixmap(bg_rect, new_pm, QRectF(new_pm.rect()))
            painter.restore()

            # Departing child view shrinks smoothly from full_rect -> anchor_rect
            cur_rect = _lerp_rect(full_rect, anchor_rect, t)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.setOpacity(max(0.0, 1.0 - (t ** 1.6)))
            out_path = QPainterPath()
            out_path.addRoundedRect(cur_rect, 12.0 - 5.0 * t, 12.0 - 5.0 * t)
            painter.setClipPath(out_path, Qt.ClipOperation.IntersectClip)
            painter.drawPixmap(cur_rect, old_pm, QRectF(old_pm.rect()))
            painter.restore()

            border_alpha = int(max(0, round(140 * (1.0 - t))))
            if border_alpha > 4:
                c = QColor(pal["info"])
                c.setAlpha(border_alpha)
                painter.setPen(QPen(c, 1.4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(cur_rect, 12.0 - 5.0 * t, 12.0 - 5.0 * t)

        painter.restore()
        painter.setPen(QPen(QColor(pal["hairline"]), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(canvas_rect, 12.0, 12.0)

    def _paint_treemap_scene(
        self,
        painter: QPainter,
        canvas_rect: QRectF,
        work_rect: QRectF,
        pal: dict[str, str],
        *,
        update_regions: bool,
    ) -> None:
        painter.setPen(QPen(QColor(pal["hairline"]), 1.0))
        painter.setBrush(QColor(pal["surface_soft"]))
        painter.drawRoundedRect(canvas_rect, 12.0, 12.0)

        root = self._root_node
        if root is None or not root.children or root.size_bytes <= 0:
            if update_regions:
                self._regions = []
                self._last_rects = {}
                self._last_agg_rects = {}
            if not self._scan_active:
                painter.setPen(QColor(pal["muted"]))
                painter.drawText(canvas_rect, Qt.AlignmentFlag.AlignCenter, "暂无可展示的存储数据")
            return

        rects_out: dict[str, QRectF] = {}
        agg_out: dict[str, QRectF] = {}
        regions_out: list[_PaintRegion] | None = [] if update_regions else None
        self._process_level(
            painter,
            root,
            work_rect,
            depth=0,
            pal=pal,
            fonts=None,
            rects_out=rects_out,
            agg_rects_out=agg_out,
            regions_out=regions_out,
        )
        if update_regions and regions_out is not None:
            self._regions = regions_out
            self._last_rects = rects_out
            self._last_agg_rects = agg_out

    def _process_level(
        self,
        painter: QPainter | None,
        parent: StorageNode,
        bounds: QRectF,
        *,
        depth: int,
        pal: dict[str, str] | None,
        fonts: tuple[Any, ...] | None,
        rects_out: dict[str, QRectF],
        agg_rects_out: dict[str, QRectF],
        regions_out: list[_PaintRegion] | None,
    ) -> None:
        items = self._prepare_children(parent, bounds, max_items=44 if depth == 0 else 18)
        if not items:
            return

        laid_out = compute_squarified_layout([(n, float(n.size_bytes)) for n in items], bounds)
        level_fonts = self._make_fonts(depth) if painter is not None else None

        for node, raw_rect in laid_out:
            pad = 2.5 if depth == 0 else 1.8
            r = raw_rect.adjusted(pad, pad, -pad, -pad)
            if r.width() < 4.0 or r.height() < 4.0:
                continue

            rects_out[node.node_id] = QRectF(r)
            if node.kind == "aggregate":
                for hidden_child in node.children:
                    agg_rects_out[hidden_child.node_id] = QRectF(r)

            can_nest = (
                depth == 0
                and node.kind != "aggregate"
                and len(node.children) > 0
                and r.width() >= 124.0
                and r.height() >= 82.0
            )

            if painter is not None and pal is not None and level_fonts is not None:
                (
                    title_font,
                    title_fm,
                    sub_font,
                    sub_fm,
                    _ct_font,
                    _ct_fm,
                    _cs_font,
                    _cs_fm,
                ) = level_fonts
                fill_hex, header_hex, border_hex = self._category_style(node.category)
                is_selected = node.node_id == self._selected_id
                is_hovered = node.node_id == self._hovered_id

                radius = 7.0 if depth == 0 else 5.0
                fill_color = QColor(fill_hex)
                if is_hovered:
                    fill_color = fill_color.lighter(108 if self._is_dark else 97)

                if is_selected:
                    pen = QPen(QColor(pal["accent"]), 2.2, Qt.PenStyle.SolidLine)
                elif is_hovered:
                    pen = QPen(QColor(pal["info"]), 1.6, Qt.PenStyle.SolidLine)
                elif node.protected:
                    pen = QPen(QColor(border_hex), 1.2, Qt.PenStyle.DashLine)
                else:
                    pen = QPen(QColor(border_hex), 1.0, Qt.PenStyle.SolidLine)

                painter.setPen(pen)
                painter.setBrush(fill_color)
                painter.drawRoundedRect(r, radius, radius)

                if can_nest:
                    header_h = 22.0
                    header_rect = QRectF(r.x() + 1.0, r.y() + 1.0, max(0.0, r.width() - 2.0), header_h)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(header_hex))
                    painter.drawRoundedRect(header_rect, radius - 1.0, radius - 1.0)

                    size_text = format_storage_bytes(node.size_bytes)
                    display_name = f"🛡 {node.name}" if node.protected else node.name
                    size_w = sub_fm.horizontalAdvance(size_text) + 10.0
                    name_avail = max(24.0, r.width() - size_w - 14.0)

                    painter.save()
                    painter.setClipRect(r.adjusted(2.0, 1.0, -2.0, -1.0))
                    painter.setFont(title_font)
                    painter.setPen(QColor(pal["text"]))
                    painter.drawText(
                        QRectF(r.x() + 7.0, r.y() + 1.0, name_avail, header_h),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        title_fm.elidedText(display_name, Qt.TextElideMode.ElideRight, name_avail),
                    )
                    painter.setFont(sub_font)
                    painter.setPen(QColor(pal["muted"]))
                    painter.drawText(
                        QRectF(r.right() - size_w - 6.0, r.y() + 1.0, size_w, header_h),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                        size_text,
                    )
                    painter.restore()
                else:
                    self._draw_tile_label(painter, r, node, pal, level_fonts)

            if can_nest:
                header_h = 22.0
                if regions_out is not None:
                    regions_out.append(_PaintRegion(rect=r, node=node, parent_node=parent, is_header=True))
                inner_rect = QRectF(
                    r.x() + 4.0,
                    r.y() + header_h + 3.0,
                    max(0.0, r.width() - 8.0),
                    max(0.0, r.height() - header_h - 7.0),
                )
                self._process_level(
                    painter,
                    node,
                    inner_rect,
                    depth=depth + 1,
                    pal=pal,
                    fonts=None,
                    rects_out=rects_out,
                    agg_rects_out=agg_rects_out,
                    regions_out=regions_out,
                )
            elif regions_out is not None:
                regions_out.append(_PaintRegion(rect=r, node=node, parent_node=parent, is_header=False))

    def _draw_tile_label(
        self,
        painter: QPainter,
        r: QRectF,
        node: StorageNode,
        pal: dict[str, str],
        fonts: tuple[Any, ...],
    ) -> None:
        w = r.width()
        h = r.height()
        if w < 16.0 or h < 14.0:
            return

        (
            title_font,
            title_fm,
            sub_font,
            sub_fm,
            compact_title_font,
            compact_title_fm,
            compact_sub_font,
            compact_sub_fm,
        ) = fonts

        raw_name = node.name or "-"
        display_name = f"🛡 {raw_name}" if (node.protected and w >= 46.0) else raw_name
        full_size = format_storage_bytes(node.size_bytes)
        compact_size = format_compact_bytes(node.size_bytes)
        size_text = full_size if w >= 54.0 else compact_size

        painter.save()
        painter.setClipRect(r.adjusted(2.0, 1.0, -2.0, -1.0))

        # Tier A: standard 2-line layout (name + size)
        if w >= 46.0 and h >= 36.0:
            use_normal = w >= 58.0 and h >= 42.0
            t_font, t_fm = (title_font, title_fm) if use_normal else (compact_title_font, compact_title_fm)
            s_font, s_fm = (sub_font, sub_fm) if use_normal else (compact_sub_font, compact_sub_fm)
            px = 6.0 if use_normal else 4.0
            py = 5.0 if use_normal else 3.0
            avail_w = max(8.0, w - px * 2.0)
            line1_h = max(13.0, min(18.0, t_fm.height() + 1.0))
            line2_h = max(12.0, min(16.0, s_fm.height() + 1.0))

            painter.setFont(t_font)
            painter.setPen(QColor(pal["text"]))
            painter.drawText(
                QRectF(r.x() + px, r.y() + py, avail_w, line1_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                t_fm.elidedText(display_name, Qt.TextElideMode.ElideRight, avail_w),
            )
            painter.setFont(s_font)
            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRectF(r.x() + px, r.y() + py + line1_h + 1.0, avail_w, line2_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                s_fm.elidedText(size_text, Qt.TextElideMode.ElideRight, avail_w),
            )

        # Tier B: small rectangular boxes (2 compact lines: truncated name... + compact size)
        elif w >= 26.0 and h >= 24.0:
            px = 3.0
            py = 2.0
            avail_w = max(8.0, w - px * 2.0)
            inner_h = max(18.0, h - py * 2.0)
            line1_h = inner_h * 0.54
            line2_h = inner_h - line1_h

            elided_name = compact_title_fm.elidedText(display_name, Qt.TextElideMode.ElideRight, avail_w)
            painter.setFont(compact_title_font)
            painter.setPen(QColor(pal["text"]))
            painter.drawText(
                QRectF(r.x() + px, r.y() + py, avail_w, line1_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                elided_name,
            )
            painter.setFont(compact_sub_font)
            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRectF(r.x() + px, r.y() + py + line1_h, avail_w, line2_h),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                compact_sub_fm.elidedText(size_text, Qt.TextElideMode.ElideRight, avail_w),
            )

        # Tier C: short flat boxes (1 compact line: elided name + size, or name alone if tight)
        elif w >= 28.0 and 14.0 <= h < 24.0:
            px = 3.0
            avail_w = max(8.0, w - px * 2.0)
            flat_size = full_size if w >= 74.0 else compact_size
            size_w = compact_sub_fm.horizontalAdvance(flat_size)
            if avail_w >= size_w + 20.0:
                name_w = avail_w - size_w - 4.0
                painter.setFont(compact_title_font)
                painter.setPen(QColor(pal["text"]))
                painter.drawText(
                    QRectF(r.x() + px, r.y() + 1.0, name_w, h - 2.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    compact_title_fm.elidedText(display_name, Qt.TextElideMode.ElideRight, name_w),
                )
                painter.setFont(compact_sub_font)
                painter.setPen(QColor(pal["muted"]))
                painter.drawText(
                    QRectF(r.right() - px - size_w, r.y() + 1.0, size_w, h - 2.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    flat_size,
                )
            else:
                elided_name = compact_title_fm.elidedText(display_name, Qt.TextElideMode.ElideRight, avail_w)
                if len(elided_name.rstrip("…")) >= 1:
                    painter.setFont(compact_title_font)
                    painter.setPen(QColor(pal["text"]))
                    painter.drawText(
                        QRectF(r.x() + px, r.y() + 1.0, avail_w, h - 2.0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        elided_name,
                    )
                elif size_w <= avail_w:
                    painter.setFont(compact_sub_font)
                    painter.setPen(QColor(pal["muted"]))
                    painter.drawText(
                        QRectF(r.x() + px, r.y() + 1.0, avail_w, h - 2.0),
                        Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                        flat_size,
                    )

        # Tier D: ultra-narrow mini tiles (16 <= w < 28 and h >= 14)
        else:
            px = 2.5
            avail_w = max(4.0, w - px * 2.0)
            elided_name = compact_title_fm.elidedText(raw_name, Qt.TextElideMode.ElideRight, avail_w)
            has_name_chars = len(elided_name.rstrip("…")) >= 1
            size_fits = compact_sub_fm.horizontalAdvance(compact_size) <= avail_w

            if h >= 24.0 and has_name_chars and size_fits:
                inner_h = h - 4.0
                l1 = inner_h * 0.54
                painter.setFont(compact_title_font)
                painter.setPen(QColor(pal["text"]))
                painter.drawText(
                    QRectF(r.x() + px, r.y() + 2.0, avail_w, l1),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    elided_name,
                )
                painter.setFont(compact_sub_font)
                painter.setPen(QColor(pal["muted"]))
                painter.drawText(
                    QRectF(r.x() + px, r.y() + 2.0 + l1, avail_w, inner_h - l1),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    compact_size,
                )
            elif has_name_chars:
                painter.setFont(compact_title_font)
                painter.setPen(QColor(pal["text"]))
                painter.drawText(
                    QRectF(r.x() + px, r.y() + 1.0, avail_w, h - 2.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    elided_name,
                )
            elif size_fits:
                painter.setFont(compact_sub_font)
                painter.setPen(QColor(pal["muted"]))
                painter.drawText(
                    QRectF(r.x() + px, r.y() + 1.0, avail_w, h - 2.0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    compact_size,
                )

        painter.restore()

    def _paint_initial_scan_overlay(
        self,
        painter: QPainter,
        canvas_rect: QRectF,
        work_rect: QRectF,
        pal: dict[str, str],
    ) -> None:
        clip_path = QPainterPath()
        clip_path.addRoundedRect(canvas_rect, 12.0, 12.0)
        painter.save()
        painter.setClipPath(clip_path)

        # Animated SpaceSniffer skeleton tiles that gently breathe & pulse
        animated_items: list[tuple[tuple[int, str], float]] = []
        for idx, (cat, base_w) in enumerate(_SKELETON_TILES):
            pulse = 1.0 + 0.08 * math.sin(self._scan_phase * 0.85 + idx * 0.7)
            animated_items.append(((idx, cat), base_w * pulse))

        laid_out = compute_squarified_layout(animated_items, work_rect)
        for (idx, cat), raw_rect in laid_out:
            r = raw_rect.adjusted(2.5, 2.5, -2.5, -2.5)
            if r.width() < 6.0 or r.height() < 6.0:
                continue
            fill_hex, header_hex, border_hex = self._category_style(cat)
            wave = 0.5 + 0.5 * math.sin(self._scan_phase * 1.4 - (r.center().x() + r.center().y()) * 0.012 + idx * 0.25)

            fill_c = QColor(fill_hex)
            fill_c.setAlpha(int(120 + 85 * wave))
            border_c = QColor(border_hex)
            border_c.setAlpha(int(105 + 85 * wave))

            painter.setPen(QPen(border_c, 1.0))
            painter.setBrush(fill_c)
            painter.drawRoundedRect(r, 7.0, 7.0)

            if r.width() >= 76.0 and r.height() >= 48.0:
                bar_c = QColor(header_hex)
                bar_c.setAlpha(int(130 + 70 * wave))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bar_c)
                painter.drawRoundedRect(QRectF(r.x() + 8.0, r.y() + 8.0, min(r.width() * 0.52, 92.0), 8.0), 4.0, 4.0)
                painter.drawRoundedRect(QRectF(r.x() + 8.0, r.y() + 22.0, min(r.width() * 0.30, 52.0), 6.0), 3.0, 3.0)

        # Sleek centered SpaceSniffer scanning banner
        card_w = min(460.0, max(240.0, work_rect.width() - 48.0))
        card_h = 110.0
        card_rect = QRectF(
            work_rect.center().x() - card_w * 0.5,
            work_rect.center().y() - card_h * 0.5,
            card_w,
            card_h,
        )
        self._draw_scan_banner_card(painter, card_rect, pal, compact=False)
        painter.restore()

    def _paint_rescan_overlay(
        self,
        painter: QPainter,
        canvas_rect: QRectF,
        work_rect: QRectF,
        pal: dict[str, str],
    ) -> None:
        clip_path = QPainterPath()
        clip_path.addRoundedRect(canvas_rect, 12.0, 12.0)
        painter.save()
        painter.setClipPath(clip_path)

        # Translucent diagonal scan sweep sheen across existing treemap
        sweep_cycle = (self._scan_phase * 0.16) % 1.45 - 0.22
        x0 = work_rect.x() + work_rect.width() * (sweep_cycle - 0.14)
        x1 = work_rect.x() + work_rect.width() * (sweep_cycle + 0.14)
        grad = QLinearGradient(QPointF(x0, work_rect.y()), QPointF(x1, work_rect.bottom()))
        accent_c = QColor(pal["accent"])
        edge_c = QColor(accent_c)
        edge_c.setAlpha(0)
        mid_c = QColor(accent_c)
        mid_c.setAlpha(34 if self._is_dark else 26)
        grad.setColorAt(0.0, edge_c)
        grad.setColorAt(0.5, mid_c)
        grad.setColorAt(1.0, edge_c)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawRect(work_rect)

        # Compact floating top progress indicator bar
        bar_w = min(520.0, max(240.0, work_rect.width() - 32.0))
        bar_h = 46.0
        bar_rect = QRectF(
            work_rect.center().x() - bar_w * 0.5,
            work_rect.y() + 10.0,
            bar_w,
            bar_h,
        )
        self._draw_scan_banner_card(painter, bar_rect, pal, compact=True)
        painter.restore()

    def _draw_scan_banner_card(
        self,
        painter: QPainter,
        card_rect: QRectF,
        pal: dict[str, str],
        *,
        compact: bool,
    ) -> None:
        bg_c = QColor(pal["elevated"])
        bg_c.setAlpha(242 if self._is_dark else 246)
        border_c = QColor(pal["border_strong"])
        painter.setPen(QPen(border_c, 1.0))
        painter.setBrush(bg_c)
        painter.drawRoundedRect(card_rect, 10.0, 10.0)

        accent_c = QColor(pal["accent"])
        pulse = 0.55 + 0.45 * math.sin(self._scan_phase * 2.1)
        dot_c = QColor(accent_c)
        dot_c.setAlpha(int(140 + 115 * pulse))

        base_font = self.font()
        title_font = QFont(base_font)
        title_font.setPointSizeF(9.0 if not compact else 8.4)
        title_font.setWeight(QFont.Weight.DemiBold)
        meta_font = QFont(base_font)
        meta_font.setPointSizeF(8.0 if not compact else 7.6)

        title_fm = QFontMetricsF(title_font)
        meta_fm = QFontMetricsF(meta_font)

        stats_text = f"已扫描 {self._scan_files:,} 文件 · {format_storage_bytes(self._scan_bytes)}"
        pct_text = f"{int(round(self._scan_progress * 100))}%" if self._scan_progress > 0.005 else "扫描中"
        path_text = self._scan_status_text or "正在遍历本地会话与缓存目录…"

        if not compact:
            px = 16.0
            dot_r = 4.5
            dot_c_pt = QPointF(card_rect.x() + px + dot_r, card_rect.y() + 23.0)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_c)
            painter.drawEllipse(dot_c_pt, dot_r, dot_r)

            pct_w = meta_fm.horizontalAdvance(pct_text) + 8.0
            title_avail = max(60.0, card_rect.width() - px * 2.0 - 18.0 - pct_w)
            painter.setFont(title_font)
            painter.setPen(QColor(pal["text"]))
            painter.drawText(
                QRectF(card_rect.x() + px + 16.0, card_rect.y() + 12.0, title_avail, 22.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title_fm.elidedText("正在分析 Antigravity 存储占用…", Qt.TextElideMode.ElideRight, title_avail),
            )
            painter.setFont(meta_font)
            painter.setPen(accent_c)
            painter.drawText(
                QRectF(card_rect.right() - px - pct_w, card_rect.y() + 12.0, pct_w, 22.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                pct_text,
            )

            track_rect = QRectF(card_rect.x() + px, card_rect.y() + 43.0, card_rect.width() - px * 2.0, 6.0)
            self._draw_progress_track(painter, track_rect, pal)

            painter.setFont(meta_font)
            painter.setPen(QColor(pal["text"]))
            painter.drawText(
                QRectF(card_rect.x() + px, card_rect.y() + 57.0, card_rect.width() - px * 2.0, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                meta_fm.elidedText(stats_text, Qt.TextElideMode.ElideRight, card_rect.width() - px * 2.0),
            )
            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRectF(card_rect.x() + px, card_rect.y() + 77.0, card_rect.width() - px * 2.0, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                meta_fm.elidedText(path_text, Qt.TextElideMode.ElideMiddle, card_rect.width() - px * 2.0),
            )
        else:
            px = 12.0
            dot_r = 4.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_c)
            painter.drawEllipse(QPointF(card_rect.x() + px + dot_r, card_rect.y() + 17.0), dot_r, dot_r)

            pct_w = meta_fm.horizontalAdvance(pct_text) + 6.0
            top_avail = max(80.0, card_rect.width() - px * 2.0 - 16.0 - pct_w)
            top_line = f"重新扫描中 · {stats_text}"
            painter.setFont(title_font)
            painter.setPen(QColor(pal["text"]))
            painter.drawText(
                QRectF(card_rect.x() + px + 14.0, card_rect.y() + 7.0, top_avail, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title_fm.elidedText(top_line, Qt.TextElideMode.ElideRight, top_avail),
            )
            painter.setFont(meta_font)
            painter.setPen(accent_c)
            painter.drawText(
                QRectF(card_rect.right() - px - pct_w, card_rect.y() + 7.0, pct_w, 18.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                pct_text,
            )

            painter.setPen(QColor(pal["muted"]))
            painter.drawText(
                QRectF(card_rect.x() + px + 14.0, card_rect.y() + 24.0, card_rect.width() - px * 2.0 - 14.0, 14.0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                meta_fm.elidedText(path_text, Qt.TextElideMode.ElideMiddle, card_rect.width() - px * 2.0 - 14.0),
            )

            track_rect = QRectF(card_rect.x() + 10.0, card_rect.bottom() - 5.0, card_rect.width() - 20.0, 3.0)
            self._draw_progress_track(painter, track_rect, pal)

    def _draw_progress_track(self, painter: QPainter, track_rect: QRectF, pal: dict[str, str]) -> None:
        radius = track_rect.height() * 0.5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal["subtle"]))
        painter.drawRoundedRect(track_rect, radius, radius)

        accent_c = QColor(pal["accent"])
        if self._scan_progress > 0.005:
            fill_w = max(track_rect.height(), track_rect.width() * self._scan_progress)
            fill_rect = QRectF(track_rect.x(), track_rect.y(), fill_w, track_rect.height())
            painter.setBrush(accent_c)
            painter.drawRoundedRect(fill_rect, radius, radius)

            # Moving highlight shimmer inside determinate fill
            shimmer_pos = ((self._scan_phase * 0.25) % 1.4) - 0.2
            sx = fill_rect.x() + fill_w * shimmer_pos
            sw = min(fill_w * 0.45, 48.0)
            if sw > 4.0:
                sh_rect = fill_rect.intersected(QRectF(sx - sw * 0.5, fill_rect.y(), sw, fill_rect.height()))
                if not sh_rect.isEmpty():
                    hi = QColor("#FFFFFF")
                    hi.setAlpha(75)
                    painter.setBrush(hi)
                    painter.drawRoundedRect(sh_rect, radius, radius)
        else:
            seg_w = max(24.0, track_rect.width() * 0.30)
            travel = max(0.0, track_rect.width() - seg_w)
            t_osc = 0.5 - 0.5 * math.cos(self._scan_phase * 1.15)
            seg_rect = QRectF(track_rect.x() + travel * t_osc, track_rect.y(), seg_w, track_rect.height())
            painter.setBrush(accent_c)
            painter.drawRoundedRect(seg_rect, radius, radius)

    def _hit_test(self, pos: QPointF) -> _PaintRegion | None:
        # Search in reverse paint order so innermost nested child tiles match before outer frames
        for reg in reversed(self._regions):
            if reg.rect.contains(pos):
                return reg
        return None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        reg = self._hit_test(event.position())
        nid = reg.node.node_id if reg else ""
        if nid != self._hovered_id:
            self._hovered_id = nid
            self.update()
            self.nodeHovered.emit(reg.node if reg else None)
        if reg is not None:
            pct = (reg.node.size_bytes / self._total_root_bytes) * 100.0
            tip = f"{reg.node.name}\n{format_storage_bytes(reg.node.size_bytes)} ({pct:.1f}%) · {reg.node.file_count} 个文件"
            if reg.node.path:
                tip += f"\n{reg.node.path}"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_id:
            self._hovered_id = ""
            self.update()
            self.nodeHovered.emit(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        reg = self._hit_test(event.position())
        if reg is not None:
            target = reg.node
            self._selected_id = target.node_id
            self.update()
            self.nodeSelected.emit(target)
            if event.button() == Qt.MouseButton.RightButton:
                self.nodeContextMenuRequested.emit(target, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            reg = self._hit_test(event.position())
            if reg is not None:
                target = reg.node
                if (
                    not target.children
                    and reg.parent_node is not None
                    and self._root_node is not None
                    and reg.parent_node.node_id != self._root_node.node_id
                    and reg.parent_node.children
                ):
                    target = reg.parent_node
                self.nodeActivated.emit(target)
        super().mouseDoubleClickEvent(event)
