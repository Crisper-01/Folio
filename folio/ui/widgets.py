"""Small reusable widgets."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..fonts import FAMILIES
from . import theme
from .paint import qfont

SWATCHES = [
    "#111111",
    "#4a4f5a",
    "#9aa1ad",
    "#ffffff",
    "#e03131",
    "#f76707",
    "#fcc419",
    "#ffe14d",
    "#2f9e44",
    "#0c8599",
    "#3b5bdb",
    "#0b1f66",
    "#7048e8",
    "#d6336c",
    "#8d5524",
    "#a5d8ff",
]


def swatch_icon(color: str | None, size: int = 16) -> QIcon:
    dpr = 2
    pix = QPixmap(size * dpr, size * dpr)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(1, 1, size - 2, size - 2)
    path = QPainterPath()
    path.addRoundedRect(rect, 4, 4)
    if color:
        p.fillPath(path, QColor(color))
    else:
        p.fillPath(path, QColor("#ffffff"))
        p.setPen(QPen(QColor("#e03131"), 1.6))
        p.drawLine(rect.bottomLeft(), rect.topRight())
    p.setPen(QPen(QColor(0, 0, 0, 70), 1))
    p.drawPath(path)
    p.end()
    return QIcon(pix)


class ColorButton(QToolButton):
    color_changed = Signal(object)  # str | None

    def __init__(self, color: str | None = "#111111", nullable: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.nullable = nullable
        self._color = color
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("QToolButton { border: 1px solid palette(mid); padding: 4px 8px; text-align: left; }")
        menu = QMenu(self)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(8, 8, 8, 4)
        grid.setSpacing(6)
        for i, c in enumerate(SWATCHES):
            b = QToolButton()
            b.setIcon(swatch_icon(c, 20))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(c)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, c=c: self._pick(c))
            grid.addWidget(b, i // 4, i % 4)
        act = QWidgetAction(menu)
        act.setDefaultWidget(holder)
        menu.addAction(act)
        if nullable:
            menu.addAction(swatch_icon(None), "Aucune", lambda: self._pick(None))
        menu.addAction("Personnalisée…", self._custom)
        self.setMenu(menu)
        self._update()

    def color(self) -> str | None:
        return self._color

    def set_color(self, color: str | None) -> None:
        self._color = color
        self._update()

    def _update(self) -> None:
        self.setIcon(swatch_icon(self._color))
        self.setText(self._color.upper() if self._color else "Aucune")

    def _pick(self, color: str | None) -> None:
        self.menu().hide()
        if color != self._color:
            self._color = color
            self._update()
            self.color_changed.emit(color)

    def _custom(self) -> None:
        c = QColorDialog.getColor(QColor(self._color or "#000000"), self, "Choisir une couleur")
        if c.isValid():
            self._pick(c.name())


class FontCombo(QComboBox):
    """Font family picker showing every family in its own typeface."""

    def __init__(self, script_only: bool = False, parent=None) -> None:
        super().__init__(parent)
        for fam in FAMILIES.values():
            if script_only and not fam.script:
                continue
            self.addItem(fam.label, fam.key)
            font = qfont(fam.key, pixel_size=22 if fam.script else 14)
            self.setItemData(self.count() - 1, font, Qt.ItemDataRole.FontRole)

    def family(self) -> str:
        return self.currentData()

    def set_family(self, key: str) -> None:
        i = self.findData(key)
        if i >= 0:
            self.setCurrentIndex(i)


class Segmented(QWidget):
    """Row of checkable push buttons acting as a radio group."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str, str | None]], parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, label, icon_name in options:
            b = QPushButton(label)
            b.setProperty("segment", True)
            b.setCheckable(True)
            b.setAutoDefault(False)
            if icon_name:
                b.setIcon(theme.icon(icon_name, 16))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))

    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return ""

    def set_value(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


def section_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SectionTitle")
    return lab


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet("color: palette(mid);")
    return f


def vbox(*widgets, margins=(0, 0, 0, 0), spacing=6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def primary(button: QPushButton) -> QPushButton:
    button.setProperty("primary", True)
    button.setDefault(True)
    return button
