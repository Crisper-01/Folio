"""Create a signature (drawn, typed in a calligraphic font or imported) and
keep a small library of saved signatures."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, QSize, QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...fonts import SCRIPT_FAMILIES
from ...overlays import ImageOverlay, InkOverlay, Overlay, TextOverlay
from .. import theme
from ..paint import ink_path, ink_pen, paint_overlay
from ..widgets import Segmented, primary

INK_COLORS = [("#111111", "Noir"), ("#0b1f66", "Bleu nuit"), ("#1f4fd8", "Bleu")]
SIGNATURE_WIDTH = 170.0  # default width on the page, in points


# --------------------------------------------------------------- persistence
def _store() -> Path:
    base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    base.mkdir(parents=True, exist_ok=True)
    return base / "signatures.json"


def to_json(ov: Overlay) -> dict:
    if isinstance(ov, InkOverlay):
        return {"type": "ink", "w": ov.w, "h": ov.h, "strokes": ov.strokes, "color": ov.stroke, "width": ov.width}
    if isinstance(ov, TextOverlay):
        return {"type": "text", "text": ov.text, "family": ov.family, "color": ov.color, "size": ov.size_pt}
    if isinstance(ov, ImageOverlay):
        return {"type": "image", "w": ov.w, "h": ov.h, "data": base64.b64encode(ov.data).decode()}
    raise ValueError(ov)


def from_json(d: dict) -> Overlay:
    if d["type"] == "ink":
        return InkOverlay(
            w=d["w"], h=d["h"], strokes=[[tuple(p) for p in s] for s in d["strokes"]], stroke=d["color"], width=d["width"]
        )
    if d["type"] == "text":
        return TextOverlay(text=d["text"], family=d["family"], color=d["color"], size_pt=d.get("size", 32))
    return ImageOverlay(w=d["w"], h=d["h"], data=base64.b64decode(d["data"]))


def load_signatures() -> list[Overlay]:
    try:
        return [from_json(d) for d in json.loads(_store().read_text(encoding="utf-8"))]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def save_signatures(items: list[Overlay]) -> None:
    _store().write_text(json.dumps([to_json(o) for o in items]), encoding="utf-8")


# -------------------------------------------------------------------- widgets
class SignaturePad(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.strokes: list[list[tuple[float, float]]] = []
        self.color = INK_COLORS[1][0]
        self.pen_width = 2.6
        self.setMinimumSize(520, 210)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def clear(self) -> None:
        self.strokes = []
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.strokes.append([(e.position().x(), e.position().y())])
            self.update()

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.MouseButton.LeftButton and self.strokes:
            last = self.strokes[-1][-1]
            p = (e.position().x(), e.position().y())
            if (p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2 >= 2.0:
                self.strokes[-1].append(p)
                self.update()

    def mouseReleaseEvent(self, e) -> None:
        self.changed.emit()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.colors().border), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(r, 10, 10)
        # baseline guide
        y = self.height() * 0.72
        pen = QPen(QColor("#c5cad6"), 1, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(28, y), QPointF(self.width() - 28, y))
        if not self.strokes:
            p.setPen(QColor("#9aa1ad"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Signez ici avec la souris, le pavé tactile ou un stylet")
        p.strokePath(ink_path(self.strokes), ink_pen(self.color, self.pen_width))

    def overlay(self) -> InkOverlay | None:
        strokes = [s for s in self.strokes if s]
        if not strokes:
            return None
        pad = self.pen_width
        ov = InkOverlay.from_points(strokes, pad=pad, stroke=self.color)
        # scale from screen pixels to a sensible size on the page
        s = SIGNATURE_WIDTH / max(ov.w, 1)
        s = min(s, 70.0 / max(ov.h, 1))
        ov.w, ov.h = ov.w * s, ov.h * s
        ov.width = max(0.8, self.pen_width * s)
        ov.x = ov.y = 0
        return ov


class Preview(QWidget):
    """Renders an overlay scaled into the widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.ov: Overlay | None = None
        self.setMinimumHeight(90)

    def set_overlay(self, ov: Overlay | None) -> None:
        self.ov = ov
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.colors().border), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(r, 10, 10)
        if not self.ov:
            return
        _, _, w, h = self.ov.local_rect()
        if w <= 0 or h <= 0:
            return
        s = min((r.width() - 30) / w, (r.height() - 20) / h)
        p.translate(r.center().x() - w * s / 2, r.center().y() - h * s / 2)
        p.scale(s, s)
        paint_overlay(p, self.ov)


def color_choice() -> Segmented:
    seg = Segmented([(c, name, None) for c, name in INK_COLORS])
    for c, b in seg.buttons.items():
        from ..widgets import swatch_icon

        b.setIcon(swatch_icon(c, 14))
    return seg


class SignatureDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Signature")
        self.result_overlay: Overlay | None = None
        self.saved = load_signatures()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(12)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        # ---- saved
        self.saved_tab = QWidget()
        sl = QVBoxLayout(self.saved_tab)
        self.saved_list = QListWidget()
        self.saved_list.setIconSize(QSize(240, 70))
        self.saved_list.setSpacing(4)
        self.saved_list.itemDoubleClicked.connect(lambda _i: self._accept())
        sl.addWidget(self.saved_list)
        row = QHBoxLayout()
        row.addStretch()
        rm = QPushButton(theme.icon("trash-2", 16), "Supprimer la signature")
        rm.clicked.connect(self._delete_saved)
        row.addWidget(rm)
        sl.addLayout(row)
        self._fill_saved()

        # ---- draw
        draw = QWidget()
        dl = QVBoxLayout(draw)
        dl.setSpacing(10)
        self.pad = SignaturePad()
        dl.addWidget(self.pad, 1)
        row = QHBoxLayout()
        self.draw_color = color_choice()
        self.draw_color.set_value(self.pad.color)
        self.draw_color.changed.connect(self._pad_color)
        row.addWidget(self.draw_color)
        row.addSpacing(12)
        row.addWidget(QLabel("Épaisseur"))
        self.thickness = QSlider(Qt.Orientation.Horizontal)
        self.thickness.setRange(10, 60)
        self.thickness.setValue(26)
        self.thickness.setFixedWidth(110)
        self.thickness.valueChanged.connect(self._pad_width)
        row.addWidget(self.thickness)
        row.addStretch()
        clear = QPushButton(theme.icon("eraser", 16), "Effacer")
        clear.clicked.connect(self.pad.clear)
        row.addWidget(clear)
        dl.addLayout(row)

        # ---- type
        typed = QWidget()
        tl = QVBoxLayout(typed)
        tl.setSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Votre nom")
        self.name.textChanged.connect(self._refresh_fonts)
        tl.addWidget(self.name)
        row = QHBoxLayout()
        self.type_color = color_choice()
        self.type_color.set_value(INK_COLORS[1][0])
        self.type_color.changed.connect(lambda _c: self._refresh_fonts())
        row.addWidget(self.type_color)
        row.addStretch()
        tl.addLayout(row)
        self.font_list = QListWidget()
        self.font_list.setSpacing(2)
        self.font_list.itemDoubleClicked.connect(lambda _i: self._accept())
        tl.addWidget(self.font_list, 1)
        for fam in SCRIPT_FAMILIES:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, fam.key)
            item.setSizeHint(QSize(0, 56))
            self.font_list.addItem(item)
        self.font_list.setCurrentRow(0)

        # ---- import
        imp = QWidget()
        il = QVBoxLayout(imp)
        il.setSpacing(10)
        pick = QPushButton(theme.icon("folder-open", 16), "Choisir une image…")
        pick.clicked.connect(self._pick_image)
        self.remove_bg = QCheckBox("Rendre le fond blanc transparent")
        self.remove_bg.setChecked(True)
        self.remove_bg.toggled.connect(lambda _v: self._load_image())
        row = QHBoxLayout()
        row.addWidget(pick)
        row.addWidget(self.remove_bg)
        row.addStretch()
        il.addLayout(row)
        self.image_preview = Preview()
        il.addWidget(self.image_preview, 1)
        self._image_path: str | None = None

        if self.saved:
            self.tabs.addTab(self.saved_tab, "Enregistrées")
        self.tabs.addTab(draw, theme.icon("pen-tool", 16), "Dessiner")
        self.tabs.addTab(typed, theme.icon("type", 16), "Écrire")
        self.tabs.addTab(imp, theme.icon("image", 16), "Importer")

        self.remember = QCheckBox("Enregistrer pour la réutiliser")
        self.remember.setChecked(True)
        self.tabs.currentChanged.connect(lambda _i: self.remember.setVisible(self.tabs.currentWidget() is not self.saved_tab))
        bottom = QHBoxLayout()
        bottom.addWidget(self.remember)
        bottom.addStretch()
        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Annuler", QDialogButtonBox.ButtonRole.RejectRole)
        ok = primary(buttons.addButton("Placer la signature", QDialogButtonBox.ButtonRole.AcceptRole))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        del cancel, ok
        bottom.addWidget(buttons)
        root.addLayout(bottom)
        self.remember.setVisible(self.tabs.currentWidget() is not self.saved_tab)
        self._refresh_fonts()
        self.resize(640, 460)

    # ------------------------------------------------------------- helpers
    def _fill_saved(self) -> None:
        self.saved_list.clear()
        for i, ov in enumerate(self.saved):
            item = QListWidgetItem()
            item.setIcon(_overlay_icon(ov, QSize(240, 70)))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(0, 82))
            self.saved_list.addItem(item)
        if self.saved:
            self.saved_list.setCurrentRow(0)

    def _delete_saved(self) -> None:
        row = self.saved_list.currentRow()
        if row < 0:
            return
        del self.saved[row]
        save_signatures(self.saved)
        self._fill_saved()

    def _pad_color(self, c: str) -> None:
        self.pad.color = c
        self.pad.update()

    def _pad_width(self, v: int) -> None:
        self.pad.pen_width = v / 10.0
        self.pad.update()

    def _typed_overlay(self, family: str) -> TextOverlay:
        return TextOverlay(text=self.name.text().strip() or "Signature", family=family, size_pt=34, color=self.type_color.value())

    def _refresh_fonts(self) -> None:
        for i in range(self.font_list.count()):
            item = self.font_list.item(i)
            ov = self._typed_overlay(item.data(Qt.ItemDataRole.UserRole))
            item.setIcon(_overlay_icon(ov, QSize(300, 46)))
        self.font_list.setIconSize(QSize(300, 46))

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Image de signature", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._image_path = path
            self._load_image()

    def _image_overlay(self) -> ImageOverlay | None:
        if not self._image_path:
            return None
        img = QImage(self._image_path)
        if img.isNull():
            return None
        if img.width() > 1600:
            img = img.scaledToWidth(1600, Qt.TransformationMode.SmoothTransformation)
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        if self.remove_bg.isChecked():
            img = _whiten_to_alpha(img)
        img = _autocrop(img)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        w = SIGNATURE_WIDTH
        h = w * img.height() / max(img.width(), 1)
        return ImageOverlay(w=w, h=h, data=bytes(buf.data()))

    def _load_image(self) -> None:
        self.image_preview.set_overlay(self._image_overlay())

    def _accept(self) -> None:
        tab = self.tabs.currentWidget()
        ov: Overlay | None = None
        if tab is self.saved_tab:
            row = self.saved_list.currentRow()
            if row >= 0:
                import copy

                ov = copy.deepcopy(self.saved[row])
        elif self.tabs.currentIndex() == self.tabs.indexOf(self.pad.parentWidget()):
            ov = self.pad.overlay()
        elif self.tabs.currentIndex() == self.tabs.indexOf(self.font_list.parentWidget()):
            item = self.font_list.currentItem()
            if item and self.name.text().strip():
                ov = self._typed_overlay(item.data(Qt.ItemDataRole.UserRole))
        else:
            ov = self._image_overlay()
        if ov is None:
            return
        if tab is not self.saved_tab and self.remember.isChecked():
            import copy

            self.saved.insert(0, copy.deepcopy(ov))
            save_signatures(self.saved[:12])
        self.result_overlay = ov
        self.accept()


def _overlay_icon(ov: Overlay, size: QSize):
    from PySide6.QtGui import QIcon, QPixmap

    dpr = 2
    pix = QPixmap(size * dpr)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _, _, w, h = ov.local_rect()
    if w > 0 and h > 0:
        s = min((size.width() - 8) / w, (size.height() - 6) / h)
        p.translate(4, (size.height() - h * s) / 2)
        p.scale(s, s)
        paint_overlay(p, ov)
    p.end()
    icon = QIcon()
    icon.addPixmap(pix, QIcon.Mode.Normal)
    icon.addPixmap(pix, QIcon.Mode.Selected)
    return icon


def _whiten_to_alpha(img: QImage) -> QImage:
    """Fade near-white pixels to transparent (a scanned signature on paper)."""
    gray = img.convertToFormat(QImage.Format.Format_Grayscale8)
    lut = bytes(255 if v <= 200 else max(0, int(255 * (255 - v) / 55)) for v in range(256))
    data = bytes(gray.constBits()).translate(lut)
    mask = QImage(data, gray.width(), gray.height(), gray.bytesPerLine(), QImage.Format.Format_Grayscale8).copy()
    out = img.convertToFormat(QImage.Format.Format_ARGB32)
    out.setAlphaChannel(mask)
    return out


def _autocrop(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    xs, ys = [], []
    step = max(1, min(w, h) // 400)
    for y in range(0, h, step):
        for x in range(0, w, step):
            if img.pixelColor(x, y).alpha() > 16:
                xs.append(x)
                ys.append(y)
    if not xs:
        return img
    pad = 4
    return img.copy(
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(w, max(xs) + pad + step) - max(0, min(xs) - pad),
        min(h, max(ys) + pad + step) - max(0, min(ys) - pad),
    )
