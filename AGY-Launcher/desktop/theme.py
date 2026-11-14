from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

from PySide6.QtWidgets import QWidget


def detect_windows_dark_mode() -> bool:
    """Checks Windows Personalize registry key for dark mode."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return False


def resolve_is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return detect_windows_dark_mode()


def get_palette(is_dark: bool) -> dict[str, str]:
    if is_dark:
        return {
            "canvas": "#0F1218",
            "surface": "#161A23",
            "surface_soft": "#1B202B",
            "elevated": "#1D222E",
            "row_hover": "#1E2432",
            "subtle": "#232938",
            "hover": "#2B3244",
            "hairline": "#242A37",
            "border_strong": "#343D52",
            "text": "#F1F4F9",
            "muted": "#9CA6B8",
            "faint": "#687387",
            "primary_bg": "#F1F4F9",
            "primary_hover": "#DCE2EC",
            "primary_text": "#0F1218",
            "accent": "#10B981",
            "accent_soft": "rgba(16, 185, 129, 0.14)",
            "link": "#60A5FA",
            "switch_off": "#343D52",
            "ok": "#34D399",
            "ok_bg": "rgba(16, 185, 129, 0.14)",
            "warn": "#FBBF24",
            "warn_bg": "rgba(245, 158, 11, 0.14)",
            "danger": "#F87171",
            "danger_bg": "rgba(239, 68, 68, 0.12)",
            "info": "#60A5FA",
            "info_bg": "rgba(59, 130, 246, 0.14)",
            "log_bg": "#0A0D12",
            "log_text": "#DCE3EC",
        }
    return {
        "canvas": "#F7F8FA",
        "surface": "#FFFFFF",
        "surface_soft": "#FAFBFD",
        "elevated": "#FFFFFF",
        "row_hover": "#F8F9FC",
        "subtle": "#F1F3F6",
        "hover": "#E8ECF1",
        "hairline": "#E8EAEF",
        "border_strong": "#D2D7E0",
        "text": "#1B1E24",
        "muted": "#666D7A",
        "faint": "#8C93A0",
        "primary_bg": "#1B1E24",
        "primary_hover": "#2D323B",
        "primary_text": "#FFFFFF",
        "accent": "#10B981",
        "accent_soft": "#EBF5F0",
        "link": "#2B59C3",
        "switch_off": "#D5D9DF",
        "ok": "#059669",
        "ok_bg": "#ECFDF5",
        "warn": "#B45309",
        "warn_bg": "#FEF3C7",
        "danger": "#DC2626",
        "danger_bg": "#FEF2F2",
        "info": "#2563EB",
        "info_bg": "#EFF6FF",
        "log_bg": "#FAFBFD",
        "log_text": "#1F242D",
    }


def _hex_to_colorref(hex_color: str) -> int:
    clean = hex_color.lstrip("#")
    r = int(clean[0:2], 16)
    g = int(clean[2:4], 16)
    b = int(clean[4:6], 16)
    return (b << 16) | (g << 8) | r


def apply_dwm_titlebar_theme(widget: QWidget, is_dark: bool) -> None:
    """Syncs native Windows DWM titlebar background, text, and border seamlessly with window canvas."""
    try:
        c = get_palette(is_dark)
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi

        dark_flag = ctypes.c_int(1 if is_dark else 0)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_flag), ctypes.sizeof(dark_flag))

        caption_color = ctypes.c_uint32(_hex_to_colorref(c["canvas"]))
        text_color = ctypes.c_uint32(_hex_to_colorref(c["text"]))
        border_color = ctypes.c_uint32(_hex_to_colorref(c["canvas"]))

        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption_color), ctypes.sizeof(caption_color))
        dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text_color), ctypes.sizeof(text_color))
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_color), ctypes.sizeof(border_color))
    except Exception:
        pass


def build_stylesheet(is_dark: bool, assets_dir: Path | str | None = None) -> str:
    c = get_palette(is_dark)
    if assets_dir is not None:
        assets_root = Path(assets_dir)
    else:
        meipass = getattr(sys, "_MEIPASS", None)
        assets_root = Path(meipass) if meipass else Path(__file__).resolve().parent.parent
    check_svg = (assets_root / "assets" / "check.svg").as_posix()
    return f"""
    QWidget {{
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
      font-size: 9.5pt;
      color: {c["text"]};
      outline: none;
    }}
    QMainWindow, QDialog {{
      background-color: {c["canvas"]};
    }}
    QScrollArea, QWidget#ScrollViewport {{
      background-color: transparent;
    }}

    /* Top Centered Capsule Dock Bar */
    QFrame#CapsuleDock {{
      background-color: {c["surface"]};
      border: 1px solid {c["hairline"]};
      border-radius: 19px;
    }}
    QPushButton#DockTab {{
      background-color: transparent;
      border: none;
      border-radius: 15px;
      padding: 6px 16px;
      font-size: 9.5pt;
      font-weight: 500;
      color: {c["muted"]};
    }}
    QPushButton#DockTab:hover {{
      color: {c["text"]};
      background-color: {c["surface_soft"]};
    }}
    QPushButton#DockTab:checked {{
      background-color: {c["subtle"]};
      color: {c["text"]};
      font-weight: 500;
    }}

    /* Pure White Card Surfaces */
    QFrame#WhiteCard {{
      background-color: {c["surface"]};
      border: 1px solid {c["hairline"]};
      border-radius: 16px;
    }}
    QFrame#PluginDropContainer {{
      background-color: {c["surface"]};
      border: 1px solid {c["hairline"]};
      border-radius: 16px;
    }}
    QFrame#PluginDropContainer[dragActive="true"] {{
      background-color: {c["accent_soft"]};
      border: 2px dashed {c["accent"]};
      border-radius: 16px;
    }}
    QFrame#DropHintBanner {{
      background-color: {c["surface_soft"]};
      border: 1px dashed {c["border_strong"]};
      border-radius: 10px;
    }}
    QFrame#DropHintBanner[dragActive="true"] {{
      background-color: {c["accent_soft"]};
      border: 1px dashed {c["accent"]};
      border-radius: 10px;
    }}
    QLabel#DropHintLabel {{
      font-size: 8.8pt;
      font-weight: 500;
      color: {c["muted"]};
    }}
    QLabel#DropHintLabel[dragActive="true"] {{
      font-size: 8.8pt;
      font-weight: 600;
      color: {c["ok"]};
    }}
    QFrame#SoftInsetBox {{
      background-color: {c["surface_soft"]};
      border: 1px solid {c["hairline"]};
      border-radius: 12px;
    }}
    QFrame#MiniMetricTile {{
      background-color: {c["surface_soft"]};
      border: 1px solid {c["hairline"]};
      border-radius: 10px;
    }}
    QFrame#ActivePluginTile {{
      background-color: {c["surface_soft"]};
      border: 1px solid {c["hairline"]};
      border-radius: 12px;
    }}
    QFrame#ActivePluginTile:hover {{
      background-color: {c["row_hover"]};
      border-color: {c["border_strong"]};
    }}
    QFrame#PluginItemRow {{
      background-color: transparent;
      border: none;
      border-bottom: 1px solid {c["hairline"]};
    }}
    QFrame#PluginItemRow:hover {{
      background-color: {c["row_hover"]};
    }}
    QFrame#NativeItemRow {{
      background-color: transparent;
      border: none;
      border-bottom: 1px solid {c["hairline"]};
    }}
    QFrame#NativeItemRow:hover {{
      background-color: {c["row_hover"]};
    }}
    QFrame#DetailSpecBox {{
      background-color: {c["surface"]};
      border: 1px solid {c["hairline"]};
      border-radius: 14px;
    }}
    QFrame#HairlineRule {{
      background-color: {c["hairline"]};
      max-height: 1px;
      min-height: 1px;
      border: none;
    }}

    /* Typography */
    QLabel#BrandTitle {{
      font-size: 10.5pt;
      font-weight: 700;
      color: {c["text"]};
    }}
    QLabel#HeroTitle {{
      font-size: 14pt;
      font-weight: 700;
      color: {c["text"]};
    }}
    QLabel#PageTitle {{
      font-size: 14pt;
      font-weight: 700;
      color: {c["text"]};
    }}
    QLabel#SectionTitle {{
      font-size: 10.5pt;
      font-weight: 600;
      color: {c["text"]};
    }}
    QLabel#CardTitle {{
      font-size: 10pt;
      font-weight: 600;
      color: {c["text"]};
    }}
    QLabel#MetricValue {{
      font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
      font-size: 10.5pt;
      font-weight: bold;
      color: {c["text"]};
    }}
    QLabel#MutedLabel {{
      font-size: 9pt;
      color: {c["muted"]};
    }}
    QLabel#FaintLabel {{
      font-size: 8.5pt;
      color: {c["faint"]};
    }}
    QLabel#MonoLabel {{
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 8.5pt;
      color: {c["faint"]};
    }}
    QLabel#VersionTag {{
      background-color: {c["subtle"]};
      color: {c["muted"]};
      border-radius: 6px;
      padding: 2px 7px;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 8pt;
      font-weight: 500;
    }}
    QLabel#PillOk {{
      background-color: {c["ok_bg"]};
      color: {c["ok"]};
      border-radius: 10px;
      padding: 3px 10px;
      font-size: 8.5pt;
      font-weight: 600;
    }}
    QLabel#PillWarn {{
      background-color: {c["warn_bg"]};
      color: {c["warn"]};
      border-radius: 10px;
      padding: 3px 10px;
      font-size: 8.5pt;
      font-weight: 600;
    }}
    QLabel#PillInfo {{
      background-color: {c["info_bg"]};
      color: {c["info"]};
      border-radius: 10px;
      padding: 3px 10px;
      font-size: 8.5pt;
      font-weight: 600;
    }}
    QLabel#PillDanger {{
      background-color: {c["danger_bg"]};
      color: {c["danger"]};
      border-radius: 10px;
      padding: 3px 10px;
      font-size: 8.5pt;
      font-weight: 600;
    }}
    QLabel#PillMuted {{
      background-color: {c["subtle"]};
      color: {c["muted"]};
      border-radius: 10px;
      padding: 3px 10px;
      font-size: 8.5pt;
      font-weight: 500;
    }}
    QLabel#DotOk {{
      font-size: 8.5pt;
      font-weight: 600;
      color: {c["ok"]};
    }}
    QLabel#DotWarn {{
      font-size: 8.5pt;
      font-weight: 600;
      color: {c["warn"]};
    }}
    QLabel#DotMuted {{
      font-size: 8.5pt;
      font-weight: 500;
      color: {c["faint"]};
    }}
    QLabel#FloatingToast {{
      background-color: {c["primary_bg"]};
      color: {c["primary_text"]};
      border-radius: 10px;
      padding: 8px 16px;
      font-size: 9pt;
      font-weight: 500;
    }}
    QFrame#FloatingUpdateCard {{
      background-color: {c["elevated"]};
      border: 1px solid {c["border_strong"]};
      border-radius: 14px;
    }}
    QLabel#FloatingUpdateTitle {{
      font-size: 10pt;
      font-weight: 700;
      color: {c["text"]};
    }}
    QLabel#FloatingUpdateBody {{
      font-size: 8.8pt;
      color: {c["muted"]};
    }}
    QPushButton#FloatingCloseBtn {{
      background-color: transparent;
      border: none;
      border-radius: 8px;
      color: {c["faint"]};
      font-size: 10.5pt;
      font-weight: 600;
      min-width: 22px;
      min-height: 22px;
      padding: 0px 4px;
    }}
    QPushButton#FloatingCloseBtn:hover {{
      background-color: {c["subtle"]};
      color: {c["text"]};
    }}

    /* Buttons */
    QPushButton {{
      background-color: {c["surface"]};
      color: {c["text"]};
      border: 1px solid {c["hairline"]};
      border-radius: 9px;
      padding: 6px 14px;
      font-size: 9pt;
      font-weight: 500;
      min-height: 20px;
    }}
    QPushButton:hover {{
      background-color: {c["surface_soft"]};
      border-color: {c["border_strong"]};
    }}
    QPushButton:pressed {{
      background-color: {c["subtle"]};
    }}
    QPushButton:disabled {{
      color: {c["faint"]};
      background-color: {c["surface_soft"]};
      border-color: {c["hairline"]};
    }}
    QPushButton#PrimaryButton {{
      background-color: {c["primary_bg"]};
      color: {c["primary_text"]};
      border: 1px solid {c["primary_bg"]};
      border-radius: 10px;
      padding: 7px 18px;
      font-weight: 600;
    }}
    QPushButton#PrimaryButton:hover {{
      background-color: {c["primary_hover"]};
      border-color: {c["primary_hover"]};
    }}
    QPushButton#PrimaryButton:disabled {{
      background-color: {c["subtle"]};
      color: {c["faint"]};
      border-color: {c["hairline"]};
    }}
    QPushButton#TopPillBtn {{
      background-color: {c["surface"]};
      color: {c["muted"]};
      border: 1px solid {c["hairline"]};
      border-radius: 16px;
      padding: 6px 14px;
      font-size: 8.8pt;
      font-weight: 500;
    }}
    QPushButton#TopPillBtn:hover {{
      color: {c["text"]};
      border-color: {c["border_strong"]};
      background-color: {c["surface"]};
    }}
    QPushButton#FilterChip {{
      background-color: transparent;
      border: 1px solid transparent;
      border-radius: 8px;
      padding: 5px 12px;
      font-size: 8.8pt;
      color: {c["muted"]};
    }}
    QPushButton#FilterChip:hover {{
      background-color: {c["subtle"]};
      color: {c["text"]};
    }}
    QPushButton#FilterChip[active="true"] {{
      background-color: {c["subtle"]};
      color: {c["text"]};
      font-weight: 600;
    }}
    QPushButton#LinkButton {{
      background-color: transparent;
      border: none;
      color: {c["link"]};
      padding: 2px 4px;
      font-size: 9pt;
      font-weight: 600;
    }}
    QPushButton#LinkButton:hover {{
      text-decoration: underline;
    }}
    QPushButton#BackLinkButton {{
      background-color: transparent;
      border: none;
      color: {c["muted"]};
      padding: 4px 2px;
      font-size: 9.5pt;
      font-weight: 500;
      text-align: left;
    }}
    QPushButton#BackLinkButton:hover {{
      color: {c["text"]};
    }}
    QPushButton#DangerGhostButton {{
      background-color: {c["danger_bg"]};
      border: 1px solid transparent;
      color: {c["danger"]};
      border-radius: 9px;
      padding: 6px 14px;
    }}
    QPushButton#DangerGhostButton:hover {{
      border-color: {c["danger"]};
    }}
    QPushButton#WarningGhostButton {{
      background-color: {c["warn_bg"]};
      border: 1px solid transparent;
      color: {c["warn"]};
      border-radius: 9px;
      padding: 6px 14px;
      font-weight: 500;
    }}
    QPushButton#WarningGhostButton:hover {{
      border-color: {c["warn"]};
    }}

    /* Storage Management Controls */
    QFrame#SegmentBar {{
      background-color: {c["surface_soft"]};
      border: 1px solid {c["hairline"]};
      border-radius: 10px;
    }}
    QPushButton#SegmentBtn {{
      background-color: transparent;
      border: none;
      border-radius: 7px;
      padding: 4px 12px;
      font-size: 8.8pt;
      font-weight: 500;
      color: {c["muted"]};
      min-height: 18px;
    }}
    QPushButton#SegmentBtn:hover {{
      color: {c["text"]};
    }}
    QPushButton#SegmentBtn:checked {{
      background-color: {c["surface"]};
      color: {c["text"]};
      font-weight: 600;
      border: 1px solid {c["hairline"]};
    }}
    QPushButton#BreadcrumbBtn {{
      background-color: transparent;
      border: none;
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 8.6pt;
      color: {c["muted"]};
      min-height: 16px;
    }}
    QPushButton#BreadcrumbBtn:hover {{
      background-color: {c["subtle"]};
      color: {c["text"]};
    }}
    QPushButton#BreadcrumbBtn[current="true"] {{
      background-color: {c["subtle"]};
      color: {c["text"]};
      font-weight: 600;
    }}
    QFrame#RankedItemRow {{
      background-color: {c["surface_soft"]};
      border: 1px solid {c["hairline"]};
      border-radius: 9px;
    }}
    QFrame#RankedItemRow:hover {{
      background-color: {c["row_hover"]};
      border-color: {c["border_strong"]};
    }}
    QFrame#RankedItemRow[selected="true"] {{
      background-color: {c["row_hover"]};
      border: 1.5px solid {c["accent"]};
    }}
    QProgressBar#StorageBar {{
      background-color: {c["hairline"]};
      border: none;
      border-radius: 2px;
      max-height: 4px;
      min-height: 4px;
    }}
    QProgressBar#StorageBar::chunk {{
      background-color: {c["accent"]};
      border-radius: 2px;
    }}
    QProgressBar#ScanProgressBar {{
      background-color: {c["subtle"]};
      border: none;
      border-radius: 2px;
      max-height: 4px;
      min-height: 4px;
    }}
    QProgressBar#ScanProgressBar::chunk {{
      background-color: {c["accent"]};
      border-radius: 2px;
    }}
    QLabel#StorageHoverLabel {{
      font-size: 8.8pt;
      color: {c["muted"]};
    }}
    QLabel#StorageHoverLabel[tone="safe"] {{
      color: {c["ok"]};
      font-weight: 500;
    }}
    QLabel#StorageHoverLabel[tone="caution"] {{
      color: {c["warn"]};
      font-weight: 500;
    }}
    QLabel#StorageHoverLabel[tone="protected"] {{
      color: {c["muted"]};
      font-weight: 500;
    }}
    QLabel#StoragePurposeLabel {{
      font-size: 8.5pt;
      color: {c["muted"]};
    }}
    QPushButton#SortPillBtn {{
      background-color: {c["surface"]};
      color: {c["muted"]};
      border: 1px solid {c["hairline"]};
      border-radius: 8px;
      padding: 4px 10px;
      font-size: 8.6pt;
      font-weight: 500;
    }}
    QPushButton#SortPillBtn:hover {{
      color: {c["text"]};
      border-color: {c["border_strong"]};
      background-color: {c["subtle"]};
    }}
    QPushButton#SortPillBtn:checked {{
      background-color: {c["accent_soft"]};
      color: {c["accent"]};
      border-color: {c["accent"]};
      font-weight: 600;
    }}
    QPushButton#AgeFilterBtn {{
      background-color: transparent;
      color: {c["muted"]};
      border: 1px solid {c["hairline"]};
      border-radius: 7px;
      padding: 3px 9px;
      font-size: 8.3pt;
      font-weight: 500;
    }}
    QPushButton#AgeFilterBtn:hover {{
      color: {c["text"]};
      background-color: {c["subtle"]};
    }}
    QPushButton#AgeFilterBtn:checked {{
      background-color: {c["text"]};
      color: {c["surface"]};
      border-color: {c["text"]};
      font-weight: 600;
    }}
    QFrame#StorageListHeader {{
      background-color: {c["surface_soft"]};
      border: none;
      border-bottom: 1px solid {c["hairline"]};
      border-top-left-radius: 13px;
      border-top-right-radius: 13px;
    }}
    QFrame#StorageSessionRow {{
      background-color: transparent;
      border: none;
      border-bottom: 1px solid {c["hairline"]};
      border-radius: 0px;
    }}
    QFrame#StorageSessionRow:hover {{
      background-color: {c["row_hover"]};
    }}
    QFrame#StorageSessionRow[checked="true"] {{
      background-color: {c["accent_soft"]};
    }}
    QPushButton#MiniWarnBtn {{
      background-color: {c["warn_bg"]};
      color: {c["warn"]};
      border: none;
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 8.1pt;
      font-weight: 600;
    }}
    QPushButton#MiniWarnBtn:hover {{
      background-color: {c["hover"]};
    }}
    QPushButton#MiniDangerBtn {{
      background-color: {c["danger_bg"]};
      color: {c["danger"]};
      border: none;
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 8.1pt;
      font-weight: 600;
    }}
    QPushButton#MiniDangerBtn:hover {{
      background-color: {c["hover"]};
    }}
    QPushButton#MiniNeutralBtn {{
      background-color: {c["subtle"]};
      color: {c["text"]};
      border: none;
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 8.1pt;
      font-weight: 500;
    }}
    QPushButton#MiniNeutralBtn:hover {{
      background-color: {c["hover"]};
    }}
    QFrame#BatchActionBar {{
      background-color: {c["surface"]};
      border: 1px solid {c["hairline"]};
      border-radius: 12px;
    }}
    QCheckBox#RowCheckBox {{
      spacing: 0px;
    }}

    /* Inputs & Combos */
    QLineEdit, QPlainTextEdit, QComboBox {{
      background-color: {c["surface_soft"]};
      color: {c["text"]};
      border: 1px solid {c["hairline"]};
      border-radius: 9px;
      padding: 7px 12px;
      font-size: 9.2pt;
      selection-background-color: {c["accent"]};
      selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
      background-color: {c["surface"]};
      border-color: {c["border_strong"]};
    }}
    QComboBox::drop-down {{
      border: none;
      width: 24px;
    }}
    QComboBox QAbstractItemView {{
      background-color: {c["surface"]};
      color: {c["text"]};
      border: 1px solid {c["hairline"]};
      border-radius: 8px;
      selection-background-color: {c["subtle"]};
      selection-color: {c["text"]};
    }}
    QPlainTextEdit#LogConsole {{
      background-color: {c["log_bg"]};
      color: {c["log_text"]};
      border: 1px solid {c["hairline"]};
      border-radius: 14px;
      padding: 16px;
      font-family: "Cascadia Code", "Consolas", monospace;
      font-size: 9pt;
    }}

    /* Checkboxes */
    QCheckBox {{
      spacing: 8px;
      font-size: 9.5pt;
      color: {c["text"]};
    }}
    QCheckBox::indicator {{
      width: 16px;
      height: 16px;
      border-radius: 5px;
      border: 1px solid {c["border_strong"]};
      background-color: {c["surface"]};
    }}
    QCheckBox::indicator:checked {{
      background-color: {c["accent"]};
      border-color: {c["accent"]};
      image: url({check_svg});
    }}

    /* Subtle Floating Scrollbars */
    QScrollBar:vertical {{
      background: transparent;
      width: 6px;
      margin: 4px 0;
    }}
    QScrollBar::handle:vertical {{
      background: {c["border_strong"]};
      border-radius: 3px;
      min-height: 28px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
      height: 0px;
    }}
    """
