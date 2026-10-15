"""Watermark editor (text or image) with a live page preview.

``WatermarkForm`` is also embedded in the images-to-PDF dialog.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...model import DocumentModel
from ...ranges import RangeError, flat_pages
from ...stamps import WATERMARK, WatermarkOptions, has_group, watermark_for
from .. import theme
from ..paint import paint_overlays_on_page
from ..renderer import page_transform, render_page
from ..widgets import ColorButton, FontCombo, Segmented, primary


class PagePreview(QWidget):
    """A page of a model with extra overlays painted on top."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model: DocumentModel | None = None
        self.index = 0
        self.overlays: list = []
        self.hide_group: str | None = None  # model overlays replaced by the preview
        self._img: QImage | None = None
        self._img_key = None
        self.setMinimumSize(220, 290)

    def set_page(self, model: DocumentModel | None, index: int = 0) -> None:
        self.model, self.index = model, index
        self._img_key = None
        self.update()

    def set_overlays(self, overlays: list) -> None:
        self.overlays = overlays
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = theme.colors()
        p.fillRect(self.rect(), QColor(c.canvas))
        if not self.model or not self.model.pages:
            p.setPen(QColor(c.muted))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Aperçu")
            return
        ref = self.model.pages[min(self.index, len(self.model.pages) - 1)]
        w, h = self.model.display_size(ref)
        s = min((self.width() - 24) / w, (self.height() - 24) / h)
        x, y = (self.width() - w * s) / 2, (self.height() - h * s) / 2
        rect = QRectF(x, y, w * s, h * s)
        key = (ref.src, ref.index, ref.rotation, round(s, 3))
        if key != self._img_key:
            self._img = render_page(self.model, ref, s * self.devicePixelRatioF())
            self._img_key = key
        p.fillRect(rect.adjusted(-1, -1, 1, 2), QColor(0, 0, 0, 50))
        p.drawImage(rect, self._img)
        p.save()
        p.setClipRect(rect)
        p.translate(x, y)
        p.scale(s, s)
        uw, uh = self.model.unrotated_size(ref)
        others = [o for o in ref.overlays if not self.hide_group or o.group != self.hide_group]
        paint_overlays_on_page(p, others + self.overlays, page_transform(uw, uh, ref.rotation))
        p.restore()


def apply_opacity_png(data: bytes, opacity: float) -> bytes:
    img = QImage()
    img.loadFromData(data)
    if img.width() > 2000:
        img = img.scaledToWidth(2000, Qt.TransformationMode.SmoothTransformation)
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(opacity)
    p.drawImage(0, 0, img)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    out.save(buf, "PNG")
    return bytes(buf.data())


class WatermarkForm(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_raw: bytes = b""
        self._image_cache: tuple | None = None
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self.kind = Segmented([("text", "Texte", "type"), ("image", "Image", "image")])
        self.kind.set_value("text")
        form.addRow("Type", self.kind)

        self.stack = QStackedWidget()
        # text page
        tw = QWidget()
        tf = QFormLayout(tw)
        tf.setContentsMargins(0, 0, 0, 0)
        self.text = QLineEdit("CONFIDENTIEL")
        self.font_combo = FontCombo()
        self.bold = QCheckBox("Gras")
        self.bold.setChecked(True)
        frow = QHBoxLayout()
        frow.addWidget(self.font_combo, 1)
        frow.addWidget(self.bold)
        self.color = ColorButton("#d63c3c")
        size_row = QHBoxLayout()
        self.auto_size = QCheckBox("Automatique")
        self.auto_size.setChecked(True)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 300)
        self.size_spin.setValue(60)
        self.size_spin.setSuffix(" pt")
        self.size_spin.setEnabled(False)
        size_row.addWidget(self.auto_size)
        size_row.addWidget(self.size_spin)
        tf.addRow("Texte", self.text)
        tf.addRow("Police", frow)
        tf.addRow("Couleur", self.color)
        tf.addRow("Taille", size_row)
        self.stack.addWidget(tw)
        # image page
        iw = QWidget()
        il = QFormLayout(iw)
        il.setContentsMargins(0, 0, 0, 0)
        pick = QPushButton(theme.icon("folder-open", 16), "Choisir une image…")
        pick.clicked.connect(self._pick)
        self.image_label = QLabel("Aucune image")
        self.image_label.setObjectName("Hint")
        prow = QHBoxLayout()
        prow.addWidget(pick)
        prow.addWidget(self.image_label, 1)
        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(10, 100)
        self.scale.setValue(50)
        il.addRow("Fichier", prow)
        il.addRow("Largeur", self.scale)
        self.stack.addWidget(iw)
        form.addRow(self.stack)

        orow = QHBoxLayout()
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        self.opacity_val = QLabel("25 %")
        self.opacity_val.setMinimumWidth(36)
        orow.addWidget(self.opacity)
        orow.addWidget(self.opacity_val)
        form.addRow("Opacité", orow)

        arow = QHBoxLayout()
        self.angle = QDoubleSpinBox()
        self.angle.setRange(-90, 90)
        self.angle.setDecimals(0)
        self.angle.setSuffix(" °")
        self.angle.setValue(45)
        arow.addWidget(self.angle)
        for v in (0, 45, -45):
            b = QPushButton(f"{v}°")
            b.setProperty("segment", True)
            b.clicked.connect(lambda _=False, v=v: self.angle.setValue(v))
            arow.addWidget(b)
        arow.addStretch()
        form.addRow("Rotation", arow)

        self.layout_seg = Segmented([("center", "Centré", None), ("tile", "Mosaïque", None)])
        self.layout_seg.set_value("center")
        form.addRow("Disposition", self.layout_seg)

        self.kind.changed.connect(self._kind_changed)
        self.auto_size.toggled.connect(self.size_spin.setDisabled)
        self.opacity.valueChanged.connect(lambda v: self.opacity_val.setText(f"{v} %"))
        for sig in (
            self.text.textChanged,
            self.font_combo.currentIndexChanged,
            self.bold.toggled,
            self.color.color_changed,
            self.auto_size.toggled,
            self.size_spin.valueChanged,
            self.scale.valueChanged,
            self.opacity.valueChanged,
            self.angle.valueChanged,
            self.layout_seg.changed,
            self.kind.changed,
        ):
            sig.connect(lambda *_: self.changed.emit())

    def _kind_changed(self, k: str) -> None:
        self.stack.setCurrentIndex(0 if k == "text" else 1)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Image du filigrane", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            with open(path, "rb") as f:
                self._image_raw = f.read()
            self._image_cache = None
            from pathlib import Path

            self.image_label.setText(Path(path).name)
            self.changed.emit()

    def is_valid(self) -> bool:
        return bool(self._image_raw) if self.kind.value() == "image" else bool(self.text.text().strip())

    def options(self) -> WatermarkOptions:
        opacity = self.opacity.value() / 100.0
        image = b""
        if self.kind.value() == "image" and self._image_raw:
            key = (id(self._image_raw), opacity)
            if not self._image_cache or self._image_cache[0] != key:
                self._image_cache = (key, apply_opacity_png(self._image_raw, opacity))
            image = self._image_cache[1]
        return WatermarkOptions(
            text=self.text.text().strip(),
            image=image,
            image_scale=self.scale.value() / 100.0,
            family=self.font_combo.family(),
            bold=self.bold.isChecked(),
            color=self.color.color() or "#d63c3c",
            opacity=opacity,
            size_pt=0.0 if self.auto_size.isChecked() else float(self.size_spin.value()),
            angle=self.angle.value(),
            tiled=self.layout_seg.value() == "tile",
        )


class WatermarkDialog(QDialog):
    REMOVE = 2

    def __init__(self, model: DocumentModel, current: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Filigrane")
        self.model = model
        self.result_options: WatermarkOptions | None = None
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(18)
        left = QVBoxLayout()
        self.form = WatermarkForm()
        left.addWidget(self.form)

        pages = QFormLayout()
        prow = QVBoxLayout()
        self.all_pages = QRadioButton("Toutes les pages")
        self.some_pages = QRadioButton("Pages :")
        self.all_pages.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.all_pages)
        group.addButton(self.some_pages)
        self.range = QLineEdit()
        self.range.setPlaceholderText("ex. 1-3, 5")
        self.range.setEnabled(False)
        self.some_pages.toggled.connect(self.range.setEnabled)
        srow = QHBoxLayout()
        srow.addWidget(self.some_pages)
        srow.addWidget(self.range, 1)
        prow.addWidget(self.all_pages)
        prow.addLayout(srow)
        pages.addRow("Appliquer à", prow)
        left.addLayout(pages)
        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.colors().danger};")
        left.addWidget(self.error)
        left.addStretch()

        buttons = QDialogButtonBox()
        if has_group(model, WATERMARK):
            rm = buttons.addButton("Retirer le filigrane", QDialogButtonBox.ButtonRole.DestructiveRole)
            rm.clicked.connect(lambda: self.done(self.REMOVE))
        buttons.addButton("Annuler", QDialogButtonBox.ButtonRole.RejectRole)
        primary(buttons.addButton("Appliquer", QDialogButtonBox.ButtonRole.AcceptRole))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)
        root.addLayout(left, 3)

        self.preview = PagePreview()
        self.preview.hide_group = WATERMARK
        self.preview.set_page(model, max(current, 0))
        root.addWidget(self.preview, 2)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(120)
        self._timer.timeout.connect(self._update_preview)
        self.form.changed.connect(self._timer.start)
        self._update_preview()
        self.resize(760, 520)

    def _update_preview(self) -> None:
        if not self.model.pages or not self.form.is_valid():
            self.preview.set_overlays([])
            return
        ref = self.model.pages[min(self.preview.index, len(self.model.pages) - 1)]
        self.preview.set_overlays(watermark_for(self.model, ref, self.form.options()))

    def _accept(self) -> None:
        if not self.form.is_valid():
            self.error.setText("Indiquez un texte ou choisissez une image.")
            return
        opts = copy.copy(self.form.options())
        if self.some_pages.isChecked():
            try:
                opts.pages = flat_pages(self.range.text(), self.model.page_count())
            except RangeError as e:
                self.error.setText(str(e))
                return
        self.result_options = opts
        self.accept()
