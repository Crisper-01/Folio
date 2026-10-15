"""Convert JPG/PNG/... images into a PDF, optionally watermarked."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImageIOHandler, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ...model import DocumentModel
from ...stamps import ImagesToPdfOptions, images_to_model
from .. import theme
from ..widgets import primary
from .watermark import PagePreview, WatermarkForm

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
MARGINS = [("Aucune", 0.0), ("Petite", 18.0), ("Normale", 36.0)]


def normalized_image_bytes(path: str) -> bytes:
    """JPEG/PNG are embedded as-is; other formats, and photos carrying an
    EXIF rotation, are re-encoded upright."""
    p = Path(path)
    reader = QImageReader(path)
    upright = reader.transformation() == QImageIOHandler.Transformation.TransformationNone
    if upright and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return p.read_bytes()
    reader.setAutoTransform(True)
    img = reader.read()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if p.suffix.lower() in (".jpg", ".jpeg"):
        img.save(buf, "JPEG", 92)
    else:
        img.save(buf, "PNG")
    return bytes(buf.data())


class ImagesToPdfDialog(QDialog):
    def __init__(self, paths: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Images vers PDF")
        self.setAcceptDrops(True)
        self.result_model: DocumentModel | None = None
        self._preview_model: DocumentModel | None = None
        self._preview_key = None

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Images")
        title.setStyleSheet("font-weight: 600;")
        head.addWidget(title)
        head.addStretch()
        add = QPushButton(theme.icon("plus", 16), "Ajouter…")
        add.clicked.connect(self._add)
        head.addWidget(add)
        left.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMinimumHeight(160)
        self.list.model().rowsMoved.connect(lambda *_: self._schedule())
        self.list.currentRowChanged.connect(lambda _r: self._schedule())
        left.addWidget(self.list, 1)
        self.hint = QLabel("Glissez des images ici ou cliquez sur « Ajouter ». Glissez les lignes pour changer l'ordre.")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        left.addWidget(self.hint)
        row = QHBoxLayout()
        rm = QPushButton(theme.icon("trash-2", 16), "Retirer")
        rm.clicked.connect(self._remove)
        row.addWidget(rm)
        row.addStretch()
        left.addLayout(row)

        form = QFormLayout()
        self.page_size = QComboBox()
        self.page_size.addItem("A4 (orientation automatique)", "a4")
        self.page_size.addItem("Lettre US (orientation automatique)", "letter")
        self.page_size.addItem("Taille de l'image", "image")
        self.margin = QComboBox()
        for label, value in MARGINS:
            self.margin.addItem(label, value)
        form.addRow("Format de page", self.page_size)
        form.addRow("Marges", self.margin)
        left.addLayout(form)

        self.wm_group = QGroupBox("Ajouter un filigrane")
        self.wm_group.setCheckable(True)
        self.wm_group.setChecked(False)
        gl = QVBoxLayout(self.wm_group)
        self.wm = WatermarkForm()
        gl.addWidget(self.wm)
        left.addWidget(self.wm_group)

        self.error = QLabel()
        self.error.setStyleSheet(f"color: {theme.colors().danger};")
        left.addWidget(self.error)
        buttons = QDialogButtonBox()
        buttons.addButton("Annuler", QDialogButtonBox.ButtonRole.RejectRole)
        self.ok = primary(buttons.addButton("Créer le PDF", QDialogButtonBox.ButtonRole.AcceptRole))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)
        root.addLayout(left, 3)

        self.preview = PagePreview()
        root.addWidget(self.preview, 2)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._update_preview)
        for sig in (self.page_size.currentIndexChanged, self.margin.currentIndexChanged, self.wm_group.toggled, self.wm.changed):
            sig.connect(lambda *_: self._schedule())

        for p in paths or []:
            self._add_path(p)
        self._schedule()
        self.resize(860, 640)

    # --------------------------------------------------------------- images
    def _add(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Ajouter des images", "", IMAGE_FILTER)
        for f in files:
            self._add_path(f)
        self._schedule()

    def _add_path(self, path: str) -> None:
        if Path(path).suffix.lower() not in IMAGE_EXT:
            return
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(QSize(96, 96), Qt.AspectRatioMode.KeepAspectRatio))
        img = reader.read()
        item = QListWidgetItem(QIcon(QPixmap.fromImage(img)), Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._schedule()

    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for url in e.mimeData().urls():
            self._add_path(url.toLocalFile())
        self._schedule()

    # -------------------------------------------------------------- preview
    def _options(self, paths: list[str]) -> ImagesToPdfOptions:
        wm = self.wm.options() if self.wm_group.isChecked() and self.wm.is_valid() else None
        return ImagesToPdfOptions(
            page_size=self.page_size.currentData(),
            margin=self.margin.currentData(),
            watermark=wm,
            images=[normalized_image_bytes(p) for p in paths],
        )

    def _schedule(self) -> None:
        self.ok.setEnabled(self.list.count() > 0)
        self._timer.start()

    def _update_preview(self) -> None:
        row = max(self.list.currentRow(), 0)
        paths = self.paths()
        if not paths:
            self.preview.set_page(None)
            return
        try:
            model = images_to_model(self._options([paths[min(row, len(paths) - 1)]]))
        except Exception as e:  # unreadable image
            self.error.setText(f"Image illisible : {e}")
            self.preview.set_page(None)
            return
        self.error.clear()
        self._preview_model = model
        self.preview.set_page(model, 0)
        self.preview.set_overlays([])

    def _accept(self) -> None:
        paths = self.paths()
        if not paths:
            return
        if self.wm_group.isChecked() and not self.wm.is_valid():
            self.error.setText("Complétez le filigrane ou décochez-le.")
            return
        try:
            self.result_model = images_to_model(self._options(paths), name="Images")
        except Exception as e:
            self.error.setText(f"Conversion impossible : {e}")
            return
        self.accept()
