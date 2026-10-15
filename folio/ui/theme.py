"""Light/dark palettes, the application stylesheet and tinted SVG icons."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from ..paths import asset_path


@dataclass(frozen=True)
class Colors:
    dark: bool
    window: str
    panel: str
    base: str
    alt: str
    text: str
    muted: str
    border: str
    canvas: str
    hover: str
    accent: str
    accent_text: str
    accent_soft: str
    danger: str


LIGHT = Colors(
    dark=False,
    window="#f3f4f7",
    panel="#fbfbfd",
    base="#ffffff",
    alt="#f0f2f6",
    text="#1c2130",
    muted="#667085",
    border="#dfe3ea",
    canvas="#e6e8ee",
    hover="#e9ecf3",
    accent="#3b5bdb",
    accent_text="#ffffff",
    accent_soft="#dfe6ff",
    danger="#d63c3c",
)

DARK = Colors(
    dark=True,
    window="#1f2228",
    panel="#23262d",
    base="#2a2e36",
    alt="#262a31",
    text="#e7e9ef",
    muted="#98a0b3",
    border="#363b45",
    canvas="#181a1f",
    hover="#30353f",
    accent="#6b8afd",
    accent_text="#0e1430",
    accent_soft="#2c3760",
    danger="#ff6b6b",
)


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self, mode: str = "system") -> None:
        super().__init__()
        self.colors = LIGHT
        self.mode = mode  # "system", "light" or "dark"
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(lambda *_: self.apply())

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.apply()

    def apply(self) -> None:
        if self.mode == "system":
            dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = self.mode == "dark"
        self.colors = DARK if dark else LIGHT
        app = QApplication.instance()
        app.setPalette(_palette(self.colors))
        app.setStyleSheet(_stylesheet(self.colors, _arrow_files(self.colors)))
        icon.cache_clear()
        self.changed.emit()


theme: ThemeManager | None = None


def colors() -> Colors:
    return theme.colors if theme else LIGHT


def install(mode: str = "system") -> ThemeManager:
    global theme
    QApplication.setStyle("Fusion")
    theme = ThemeManager(mode)
    theme.apply()
    return theme


def _palette(c: Colors) -> QPalette:
    p = QPalette()
    q = QColor
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        p.setColor(group, QPalette.ColorRole.Window, q(c.window))
        p.setColor(group, QPalette.ColorRole.WindowText, q(c.text))
        p.setColor(group, QPalette.ColorRole.Base, q(c.base))
        p.setColor(group, QPalette.ColorRole.AlternateBase, q(c.alt))
        p.setColor(group, QPalette.ColorRole.Text, q(c.text))
        p.setColor(group, QPalette.ColorRole.Button, q(c.base))
        p.setColor(group, QPalette.ColorRole.ButtonText, q(c.text))
        p.setColor(group, QPalette.ColorRole.Highlight, q(c.accent))
        p.setColor(group, QPalette.ColorRole.HighlightedText, q(c.accent_text))
        p.setColor(group, QPalette.ColorRole.ToolTipBase, q(c.base))
        p.setColor(group, QPalette.ColorRole.ToolTipText, q(c.text))
        p.setColor(group, QPalette.ColorRole.PlaceholderText, q(c.muted))
        p.setColor(group, QPalette.ColorRole.Link, q(c.accent))
        p.setColor(group, QPalette.ColorRole.Mid, q(c.border))
        p.setColor(group, QPalette.ColorRole.Midlight, q(c.hover))
        p.setColor(group, QPalette.ColorRole.Light, q(c.base))
        p.setColor(group, QPalette.ColorRole.Dark, q(c.border))
        p.setColor(group, QPalette.ColorRole.Shadow, q("#000000"))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(disabled, role, q(c.muted))
    p.setColor(disabled, QPalette.ColorRole.Window, q(c.window))
    p.setColor(disabled, QPalette.ColorRole.Base, q(c.alt))
    p.setColor(disabled, QPalette.ColorRole.Button, q(c.alt))
    return p


def _arrow_files(c: Colors) -> dict[str, str]:
    """Stylesheets need image files for arrows: write tinted chevrons once."""
    import tempfile

    folder = Path(tempfile.gettempdir()) / "folio-theme"
    folder.mkdir(exist_ok=True)
    out = {}
    for name, color in (("chevron-down", c.muted), ("chevron-up", c.muted), ("check", c.accent_text)):
        path = folder / f"{name}-{color.lstrip('#')}.png"
        if not path.exists():
            _tinted(name, color, 16).toImage().save(str(path))
        out[name] = path.as_posix()
    return out


def _stylesheet(c: Colors, arrows: dict[str, str]) -> str:
    down, up, check = arrows["chevron-down"], arrows["chevron-up"], arrows["check"]
    return f"""
    QMainWindow, QDialog {{ background: {c.window}; }}
    QToolBar {{
        background: {c.panel}; border: none; border-bottom: 1px solid {c.border};
        spacing: 2px; padding: 4px 8px;
    }}
    QToolBar::separator {{ background: {c.border}; width: 1px; margin: 6px 6px; }}
    QToolButton {{
        background: transparent; border: 1px solid transparent; border-radius: 6px;
        padding: 5px; color: {c.text};
    }}
    QToolButton:hover {{ background: {c.hover}; }}
    QToolButton:pressed {{ background: {c.border}; }}
    QToolButton:checked {{ background: {c.accent_soft}; border-color: {c.accent_soft}; }}
    QToolButton:disabled {{ color: {c.muted}; }}
    QToolButton[popupMode="1"] {{ padding-right: 16px; }}
    QToolButton[popupMode="2"] {{ padding-right: 18px; }}
    QToolButton::menu-button {{ border: none; width: 14px; }}
    QToolButton::menu-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QToolButton::menu-indicator {{
        image: url({down}); width: 10px; height: 10px;
        subcontrol-origin: padding; subcontrol-position: center right; right: 4px;
    }}
    QStatusBar {{ background: {c.panel}; border-top: 1px solid {c.border}; color: {c.muted}; }}
    QStatusBar::item {{ border: none; }}
    QMenuBar {{ background: {c.panel}; color: {c.text}; }}
    QMenuBar::item {{ padding: 5px 10px; background: transparent; border-radius: 4px; }}
    QMenuBar::item:selected {{ background: {c.hover}; }}
    QMenu {{ background: {c.base}; border: 1px solid {c.border}; padding: 4px; border-radius: 8px; }}
    QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: 5px; color: {c.text}; }}
    QMenu::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
    QMenu::item:disabled {{ color: {c.muted}; }}
    QMenu::separator {{ height: 1px; background: {c.border}; margin: 4px 6px; }}
    QMenu::icon {{ padding-left: 8px; }}
    #SidePanel {{ background: {c.panel}; }}
    #SidePanel[side="left"] {{ border-right: 1px solid {c.border}; }}
    #SidePanel[side="right"] {{ border-left: 1px solid {c.border}; }}
    #PanelTitle {{
        color: {c.muted}; font-weight: 600; font-size: 11px; letter-spacing: 0.5px;
        padding: 10px 12px 4px 12px; text-transform: uppercase;
    }}
    #SectionTitle {{ color: {c.muted}; font-weight: 600; font-size: 11px; padding-top: 6px; }}
    #Hint {{ color: {c.muted}; }}
    QListWidget#Thumbnails {{ background: {c.panel}; border: none; outline: none; }}
    QListWidget#Thumbnails::item {{ border-radius: 8px; padding: 6px; margin: 2px 6px; color: {c.muted}; }}
    QListWidget#Thumbnails::item:hover {{ background: {c.hover}; }}
    QListWidget#Thumbnails::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
    QGraphicsView#PageView {{ background: {c.canvas}; border: none; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
        background: {c.base}; border: 1px solid {c.border}; border-radius: 6px;
        padding: 4px 6px; color: {c.text}; selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
    QPlainTextEdit:focus {{ border-color: {c.accent}; }}
    QComboBox::drop-down {{ border: none; width: 20px; }}
    QComboBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
    QAbstractSpinBox {{ padding-right: 18px; }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border; width: 18px; border: none; background: transparent;
    }}
    QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
    QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {c.hover}; }}
    QAbstractSpinBox::up-arrow {{ image: url({up}); width: 9px; height: 9px; }}
    QAbstractSpinBox::down-arrow {{ image: url({down}); width: 9px; height: 9px; }}
    QComboBox QAbstractItemView {{
        background: {c.base}; border: 1px solid {c.border}; selection-background-color: {c.accent_soft};
        selection-color: {c.text}; outline: none;
    }}
    QPushButton {{
        background: {c.base}; border: 1px solid {c.border}; border-radius: 6px;
        padding: 6px 14px; color: {c.text};
    }}
    QPushButton:hover {{ background: {c.hover}; }}
    QPushButton:disabled {{ color: {c.muted}; background: {c.alt}; }}
    QPushButton[primary="true"] {{
        background: {c.accent}; color: {c.accent_text}; border-color: {c.accent}; font-weight: 600;
    }}
    QPushButton[primary="true"]:hover {{ background: {QColor(c.accent).lighter(110).name()}; }}
    QPushButton[segment="true"] {{ padding: 4px 8px; border-radius: 5px; }}
    QPushButton[segment="true"]:checked {{ background: {c.accent_soft}; border-color: {c.accent}; }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator, QGroupBox::indicator {{
        width: 14px; height: 14px; border: 1px solid {c.muted}; background: {c.base};
    }}
    QCheckBox::indicator, QGroupBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover, QGroupBox::indicator:hover {{ border-color: {c.accent}; }}
    QCheckBox::indicator:checked, QGroupBox::indicator:checked {{
        background: {c.accent}; border-color: {c.accent}; image: url({check});
    }}
    QRadioButton::indicator:checked {{ border: 5px solid {c.accent}; width: 6px; height: 6px; background: {c.base}; }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {c.border}; background: {c.alt}; }}
    QListWidget {{ background: {c.base}; border: 1px solid {c.border}; border-radius: 8px; outline: none; padding: 2px; }}
    QListWidget::item {{ border-radius: 6px; padding: 2px; color: {c.text}; }}
    QListWidget::item:hover {{ background: {c.hover}; }}
    QListWidget::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
    QGroupBox {{ border: 1px solid {c.border}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c.muted}; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {c.base}; border: 2px solid {c.accent}; width: 12px; height: 12px;
        margin: -6px 0; border-radius: 8px;
    }}
    QTabWidget::pane {{ border: 1px solid {c.border}; border-radius: 8px; top: -1px; background: {c.base}; }}
    QTabBar::tab {{
        padding: 7px 16px; color: {c.muted}; border: none; border-bottom: 2px solid transparent;
        background: transparent;
    }}
    QTabBar::tab:selected {{ color: {c.text}; border-bottom-color: {c.accent}; }}
    QTabBar::tab:hover {{ color: {c.text}; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 4px; min-height: 30px; margin: 2px 3px; }}
    QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {c.border}; border-radius: 4px; min-width: 30px; margin: 3px 2px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{ background: {c.base}; color: {c.text}; border: 1px solid {c.border}; padding: 4px 6px; }}
    QProgressBar {{ border: 1px solid {c.border}; border-radius: 5px; background: {c.alt}; text-align: center; height: 10px; }}
    QProgressBar::chunk {{ background: {c.accent}; border-radius: 4px; }}
    #SearchBar {{ background: {c.panel}; border-bottom: 1px solid {c.border}; }}
    #EmptyTitle {{ font-size: 20px; font-weight: 600; color: {c.text}; }}
    #EmptyText {{ color: {c.muted}; }}
    """


def _tinted(name: str, color: str, size: int) -> QPixmap:
    svg = Path(asset_path("icons", f"{name}.svg")).read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    dpr = 2.0
    img = QImage(int(size * dpr), int(size * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter, QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pix = QPixmap.fromImage(img)
    pix.setDevicePixelRatio(dpr)
    return pix


@cache
def icon(name: str, size: int = 18) -> QIcon:
    c = colors()
    ic = QIcon()
    ic.addPixmap(_tinted(name, c.text, size), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(_tinted(name, c.accent, size), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(_tinted(name, c.muted, size), QIcon.Mode.Disabled, QIcon.State.Off)
    ic.addPixmap(_tinted(name, c.muted, size), QIcon.Mode.Disabled, QIcon.State.On)
    return ic


ICON_SIZE = QSize(18, 18)
