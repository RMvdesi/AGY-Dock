from __future__ import annotations

import hashlib
from html import escape

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PALETTES = (
    ("#EEF2FF", "#4338CA"),  # Indigo tint
    ("#ECFDF5", "#047857"),  # Mint tint
    ("#EFF6FF", "#1D4ED8"),  # Cobalt tint
    ("#FEF3C7", "#B45309"),  # Amber tint
    ("#F3E8FF", "#6D28D9"),  # Violet tint
    ("#F1F5F9", "#334155"),  # Slate tint
)


def render_svg_pixmap(svg_markup: str, logical_px: int = 36, scale: int = 3) -> QPixmap:
    """Renders crisp vector SVG markup into a high-DPI QPixmap with smooth anti-aliasing."""
    hi = logical_px * scale
    img = QImage(hi, hi, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup.encode("utf-8")))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, hi, hi))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(float(scale))
    return pm


def _short_monogram(name_or_id: str) -> str:
    raw = (name_or_id or "").strip()
    lower = raw.lower()
    if "hans" in lower or "cn" in lower or "i18n" in lower:
        return "中/A"
    if "office" in lower or "viewer" in lower or "doc" in lower:
        return "DOC"
    if "markdown" in lower or lower.startswith("md"):
        return "MD"
    if "git" in lower:
        return "GIT"
    if "sql" in lower:
        return "SQL"
    if "api" in lower or "rest" in lower:
        return "API"

    parts = [p for p in raw.replace("_", "-").split("-") if p]
    if len(parts) >= 2:
        letters = "".join(p[0].upper() for p in parts[:3] if p[0].isascii())
        if letters:
            return letters[:3]
    ascii_chars = "".join(ch for ch in raw if ch.isalnum() and ch.isascii())
    if ascii_chars:
        return ascii_chars[:3].upper()
    return raw[:2] or "EXT"


def plugin_graphic_svg(plugin_id: str, plugin_type: str = "", label: str = "") -> str:
    """Returns a soft-tinted rounded square SVG badge usable uniformly for any third-party plugin."""
    pid = (plugin_id or "").lower()
    if "hans" in pid or "cn" in pid or "i18n" in pid:
        bg, fg = _PALETTES[0]
    elif "office" in pid or "viewer" in pid:
        bg, fg = _PALETTES[1]
    elif "node" in (plugin_type or "").lower():
        bg, fg = _PALETTES[2]
    else:
        idx = int(hashlib.md5(pid.encode("utf-8")).hexdigest()[:4], 16) % len(_PALETTES)
        bg, fg = _PALETTES[idx]

    token = escape(_short_monogram(label or plugin_id))
    font_size = 18 if len(token) <= 2 else (14.5 if len(token) == 3 else 12)
    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <rect x="2" y="2" width="60" height="60" rx="16" fill="{bg}"/>
      <text x="32" y="38.5" text-anchor="middle"
            font-family="Segoe UI, Microsoft YaHei UI, sans-serif"
            font-size="{font_size}" font-weight="700" fill="{fg}">{token}</text>
    </svg>"""


def native_graphic_svg(dir_name: str) -> str:
    """Returns a clean pale-tinted vector badge for native Antigravity extensions."""
    d = (dir_name or "").lower()
    if "science" in d:
        bg, fg = "#ECFDF5", "#0D9488"
        glyph = '<path d="M26 19h12M29 19v10l-7 13.5a2.4 2.4 0 0 0 2.1 3.5h15.8a2.4 2.4 0 0 0 2.1-3.5L35 29V19" fill="none" stroke="#0D9488" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>'
    elif "chrome" in d or "devtools" in d:
        bg, fg = "#EFF6FF", "#2563EB"
        glyph = '<circle cx="32" cy="32" r="13" fill="none" stroke="#2563EB" stroke-width="2.8"/><circle cx="32" cy="32" r="5" fill="#2563EB"/>'
    elif "android" in d:
        bg, fg = "#F0FDF4", "#16A34A"
        glyph = '<rect x="22" y="17" width="20" height="30" rx="4" fill="none" stroke="#16A34A" stroke-width="2.8"/><line x1="29" y1="42" x2="35" y2="42" stroke="#16A34A" stroke-width="2.8" stroke-linecap="round"/>'
    elif "web" in d:
        bg, fg = "#F5F3FF", "#6D28D9"
        glyph = '<rect x="17" y="20" width="30" height="24" rx="4" fill="none" stroke="#6D28D9" stroke-width="2.8"/><line x1="17" y1="28" x2="47" y2="28" stroke="#6D28D9" stroke-width="2.5"/>'
    else:
        idx = int(hashlib.md5(d.encode("utf-8")).hexdigest()[:4], 16) % len(_PALETTES)
        bg, fg = _PALETTES[idx]
        glyph = f'<rect x="20" y="22" width="24" height="20" rx="5" fill="none" stroke="{fg}" stroke-width="2.8"/><circle cx="28" cy="32" r="2.5" fill="{fg}"/><circle cx="36" cy="32" r="2.5" fill="{fg}"/>'

    return f"""
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <rect x="2" y="2" width="60" height="60" rx="16" fill="{bg}"/>
      {glyph}
    </svg>"""
