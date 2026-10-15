"""Page thumbnails: navigation, multi-selection, drag & drop reordering and
dropping PDF/image files to insert them."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from ..model import DocumentModel
from . import theme
from .paint import paint_overlays_on_page
from .renderer import Renderer, page_transform

THUMB_W = 116
LABEL_H = 22
PAD = 8
OPENABLE = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


class ThumbDelegate(QStyledItemDelegate):
    def __init__(self, panel: ThumbnailPanel) -> None:
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        ref = self.panel.ref_at(index.row())
        if ref is None:
            return QSize(THUMB_W + 2 * PAD, 100)
        w, h = self.panel.model.display_size(ref)
        th = min(THUMB_W * h / w, THUMB_W * 1.6)
        return QSize(THUMB_W + 2 * PAD + 12, int(th) + LABEL_H + 2 * PAD)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        c = theme.colors()
        ref = self.panel.ref_at(index.row())
        if ref is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hover:
            path = QPainterPath()
            path.addRoundedRect(r, 8, 8)
            p.fillPath(path, QColor(c.accent_soft if selected else c.hover))

        model = self.panel.model
        w, h = model.display_size(ref)
        scale = min(THUMB_W / w, THUMB_W * 1.6 / h)
        tw, th = w * scale, h * scale
        x = r.center().x() - tw / 2
        y = r.top() + PAD
        page_rect = QRectF(x, y, tw, th)
        p.fillRect(page_rect.adjusted(-1, -1, 1, 2), QColor(0, 0, 0, 40))
        p.fillRect(page_rect, QColor("#ffffff"))
        dpr = self.panel.devicePixelRatioF()
        img = self.panel.renderer.get(ref, scale * dpr, thumb=True)
        if img is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(page_rect, img)
        if ref.overlays:
            p.save()
            p.setClipRect(page_rect)
            p.translate(x, y)
            p.scale(scale, scale)
            uw, uh = model.unrotated_size(ref)
            paint_overlays_on_page(p, ref.overlays, page_transform(uw, uh, ref.rotation))
            p.restore()
        if selected:
            p.setPen(QPen(QColor(c.accent), 2))
            p.drawRect(page_rect.adjusted(-1, -1, 1, 1))
        font = QFont(p.font())
        font.setPointSizeF(font.pointSizeF() * 0.92)
        if selected:
            font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(c.text if selected else c.muted))
        label = QRectF(r.left(), page_rect.bottom() + 3, r.width(), LABEL_H)
        p.drawText(label, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, str(index.row() + 1))
        p.restore()


class ThumbnailPanel(QListWidget):
    page_activated = Signal(int)
    reordered = Signal(list)  # page uids in the new order
    files_dropped = Signal(list, int)  # paths, insertion index
    context_requested = Signal(QPoint)

    def __init__(self, model: DocumentModel, renderer: Renderer, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Thumbnails")
        self.model = model
        self.renderer = renderer
        self.setItemDelegate(ThumbDelegate(self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(False)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_requested)
        self.itemClicked.connect(lambda item: self.page_activated.emit(self.row(item)))
        self.currentRowChanged.connect(self._on_row)
        renderer.rendered.connect(lambda _k: self.viewport().update())
        self._syncing = False
        self.setMinimumWidth(THUMB_W + 2 * PAD + 30)

    def set_model(self, model: DocumentModel) -> None:
        self.model = model
        self.rebuild()

    def ref_at(self, row: int):
        item = self.item(row)
        if item is None:
            return None
        i = self.model.index_of(item.data(Qt.ItemDataRole.UserRole))
        return self.model.pages[i] if i >= 0 else None

    def rebuild(self) -> None:
        selected = {self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count()) if self.item(i).isSelected()}
        current = self.currentItem().data(Qt.ItemDataRole.UserRole) if self.currentItem() else None
        self._syncing = True
        self.clear()
        for ref in self.model.pages:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, ref.uid)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            self.addItem(item)
            if ref.uid in selected:
                item.setSelected(True)
            if ref.uid == current:
                self.setCurrentItem(item, self.selectionModel().SelectionFlag.NoUpdate)
        self._syncing = False

    def refresh(self) -> None:
        self.viewport().update()

    def selected_rows(self) -> list[int]:
        return sorted(self.row(i) for i in self.selectedItems())

    def set_current(self, row: int) -> None:
        if row < 0 or row >= self.count() or self.currentRow() == row:
            return
        self._syncing = True
        if len(self.selectedItems()) <= 1:
            self.setCurrentRow(row)
        else:
            self.setCurrentRow(row, self.selectionModel().SelectionFlag.NoUpdate)
        self.scrollToItem(self.item(row))
        self._syncing = False

    def _on_row(self, row: int) -> None:
        if not self._syncing and row >= 0:
            self.page_activated.emit(row)

    # ----------------------------------------------------------- drag & drop
    def _external_paths(self, event) -> list[str]:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if Path(u.toLocalFile()).suffix.lower() in OPENABLE]

    def dragEnterEvent(self, event) -> None:
        if self._external_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._external_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def _drop_row(self, pos: QPoint) -> int:
        idx = self.indexAt(pos)
        if not idx.isValid():
            return self.count()
        rect: QRect = self.visualRect(idx)
        return idx.row() + (1 if pos.y() > rect.center().y() else 0)

    def dropEvent(self, event) -> None:
        paths = self._external_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths, self._drop_row(event.position().toPoint()))
            return
        if event.source() is self:
            # Compute the target ourselves; Qt's internal move is not reliable
            # with extended selections.
            rows = self.selected_rows()
            target = self._drop_row(event.position().toPoint())
            event.setDropAction(Qt.DropAction.IgnoreAction)
            event.accept()
            uids = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
            moving = [uids[r] for r in rows]
            before = sum(1 for r in rows if r < target)
            rest = [u for u in uids if u not in moving]
            pos = target - before
            self.reordered.emit(rest[:pos] + moving + rest[pos:])
            return
        super().dropEvent(event)

    def keyPressEvent(self, event) -> None:
        # Delete etc. are handled by window actions; keep arrows/home/end.
        super().keyPressEvent(event)
