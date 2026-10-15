"""Continuous page view with editable overlays and drawing tools."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontMetricsF,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QGraphicsView,
    QMenu,
    QStyleOptionGraphicsItem,
)

from ..model import DocumentModel, PageRef
from ..overlays import BoxOverlay, InkOverlay, LineOverlay, Overlay, TextOverlay, new_uid
from . import theme
from .paint import overlay_margin, paint_overlay, qcolor, qfont
from .renderer import Renderer, page_transform

PAGE_GAP = 18.0
SCENE_MARGIN = 28.0
HANDLE_PX = 9.0


class Tool(Enum):
    SELECT = "select"
    TEXT = "text"
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    PEN = "pen"
    HIGHLIGHT = "highlight"
    REDACT = "redact"
    PLACE = "place"  # placing a pending image/signature


DRAW_TOOLS = {Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.PEN, Tool.HIGHLIGHT, Tool.REDACT}


@dataclass
class ToolDefaults:
    text_family: str = "sans"
    text_size: float = 14.0
    text_color: str = "#111111"
    text_bold: bool = False
    text_italic: bool = False
    text_align: str = "left"
    shape_stroke: str | None = "#3b5bdb"
    shape_fill: str | None = None
    shape_width: float = 2.0
    shape_opacity: float = 1.0
    pen_color: str = "#0b1f66"
    pen_width: float = 2.0
    pen_opacity: float = 1.0
    highlight_color: str = "#ffe14d"


# ======================================================================= items
class FrameItem(QGraphicsItem):
    """Invisible parent holding overlays in unrotated page coordinates."""

    def __init__(self, parent: QGraphicsItem) -> None:
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemHasNoContents)

    def boundingRect(self) -> QRectF:
        return QRectF()

    def paint(self, *args) -> None:
        pass


class PageItem(QGraphicsItem):
    def __init__(self, view: PageView, ref: PageRef) -> None:
        super().__init__()
        self.view = view
        self.ref = ref
        self.frame = FrameItem(self)
        self.search_items: list[QGraphicsRectItem] = []
        self.overlay_items: dict[str, OverlayItem] = {}
        self.set_ref(ref)

    def set_ref(self, ref: PageRef) -> None:
        self.prepareGeometryChange()
        self.ref = ref
        model = self.view.model
        self.w, self.h = model.display_size(ref)
        uw, uh = model.unrotated_size(ref)
        self.frame.setTransform(page_transform(uw, uh, ref.rotation))
        self.update()

    @property
    def index(self) -> int:
        return self.view.model.index_of(self.ref.uid)

    def boundingRect(self) -> QRectF:
        return QRectF(-3, -2, self.w + 6, self.h + 6)

    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        rect = QRectF(0, 0, self.w, self.h)
        lod = option.levelOfDetailFromTransform(p.worldTransform())
        px = 1.0 / max(lod, 1e-6)
        # soft shadow
        shadow = QColor(0, 0, 0, 60 if theme.colors().dark else 28)
        for i, a in ((3, 0.35), (2, 0.6), (1, 1.0)):
            c = QColor(shadow)
            c.setAlphaF(shadow.alphaF() * a)
            p.fillRect(rect.adjusted(-i * px, -i * px + px, i * px, i * px + 2 * px), c)
        p.fillRect(rect, QColor("#ffffff"))
        dpr = widget.devicePixelRatioF() if widget else 1.0
        img = self.view.renderer.get(self.ref, lod * dpr)
        if img is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(rect, img)


class OverlayItem(QGraphicsObject):
    """Interactive wrapper around one overlay (or a not-yet-committed draft)."""

    def __init__(self, view: PageView, ov: Overlay, parent: QGraphicsItem, draft: bool = False) -> None:
        super().__init__(parent)
        self.view = view
        self.ov = ov
        self.draft = draft  # not in the model yet
        self.editor: QGraphicsTextItem | None = None
        self._syncing = False
        self._drag: dict | None = None
        flags = QGraphicsItem.GraphicsItemFlag
        if not draft:
            self.setFlags(flags.ItemIsSelectable | flags.ItemIsMovable | flags.ItemSendsGeometryChanges | flags.ItemIsFocusable)
            self.setAcceptHoverEvents(True)
        self.refresh()

    # ------------------------------------------------------------ geometry
    def refresh(self, ov: Overlay | None = None) -> None:
        if ov is not None:
            self.ov = ov
        self._syncing = True
        self.prepareGeometryChange()
        self.setPos(self.ov.x, self.ov.y)
        self.setRotation(self.ov.rotation)
        self._syncing = False
        self.update()

    def _px(self) -> float:
        """Size of one screen pixel in item units."""
        return 1.0 / max(self.view.transform().m11(), 1e-6)

    def boundingRect(self) -> QRectF:
        x, y, w, h = self.ov.local_rect()
        m = overlay_margin(self.ov) + HANDLE_PX * self._px() + 2
        return QRectF(x - m, y - m, w + 2 * m, h + 2 * m)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        x, y, w, h = self.ov.local_rect()
        if isinstance(self.ov, LineOverlay):
            line = QPainterPath(QPointF(0, 0))
            line.lineTo(self.ov.dx, self.ov.dy)
            stroker = QPainterPathStroker()
            stroker.setWidth(max(self.ov.width, 8 * self._px()) + 4 * self._px())
            path = stroker.createStroke(line)
        else:
            pad = 3 * self._px()
            path.addRect(QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad))
        if self.isSelected():
            # handles overlap the body: winding fill keeps them solid
            path.setFillRule(Qt.FillRule.WindingFill)
            r = HANDLE_PX * self._px()
            for hp in self.handles():
                if hp is None:
                    continue
                path.addRect(QRectF(hp.x() - r, hp.y() - r, 2 * r, 2 * r))
        return path

    def handles(self) -> list[QPointF]:
        ov = self.ov
        if isinstance(ov, LineOverlay):
            return [QPointF(0, 0), QPointF(ov.dx, ov.dy)]
        w, h = ov.size()
        corners = [
            QPointF(0, 0),
            QPointF(w / 2, 0),
            QPointF(w, 0),
            QPointF(w, h / 2),
            QPointF(w, h),
            QPointF(w / 2, h),
            QPointF(0, h),
            QPointF(0, h / 2),
        ]
        if isinstance(ov, TextOverlay) or getattr(ov, "keep_ratio", False):
            return [c if i % 2 == 0 else None for i, c in enumerate(corners)]  # type: ignore[misc]
        return corners

    def handle_at(self, pos: QPointF) -> int | None:
        if not self.isSelected():
            return None
        r = HANDLE_PX * self._px()
        for i, hp in enumerate(self.handles()):
            if hp is not None and abs(hp.x() - pos.x()) <= r and abs(hp.y() - pos.y()) <= r:
                return i
        return None

    # ----------------------------------------------------------------- paint
    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:
        p.save()
        paint_overlay(p, self.ov, draw_text=self.editor is None)
        p.restore()
        if self.isSelected() or self.editor is not None:
            self._paint_selection(p)

    def _paint_selection(self, p: QPainter) -> None:
        px = self._px()
        accent = QColor(theme.colors().accent)
        x, y, w, h = self.ov.local_rect()
        if self.editor is not None:
            # Qt's editor lays text out a hair wider than the PDF metrics
            w = max(w, self.editor.boundingRect().width() * self.editor.scale())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not isinstance(self.ov, LineOverlay):
            pen = QPen(accent, 1.2 * px, Qt.PenStyle.DashLine)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            pad = 2 * px
            p.drawRect(QRectF(x - pad, y - pad, w + 2 * pad, h + 2 * pad))
        if self.editor is not None:
            return
        r = 4.5 * px
        p.setPen(QPen(accent, 1.4 * px))
        p.setBrush(QBrush(QColor("#ffffff")))
        for hp in self.handles():
            if hp is not None:
                p.drawEllipse(hp, r, r) if isinstance(self.ov, LineOverlay) else p.drawRect(
                    QRectF(hp.x() - r, hp.y() - r, 2 * r, 2 * r)
                )

    # ----------------------------------------------------------- interaction
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self._syncing and not self.draft:
            self.view.touch()
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._syncing:
            self.ov.x, self.ov.y = self.pos().x(), self.pos().y()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.prepareGeometryChange()
        return super().itemChange(change, value)

    def hoverMoveEvent(self, event) -> None:
        idx = self.handle_at(event.pos())
        if idx is None:
            self.setCursor(Qt.CursorShape.SizeAllCursor if self.view.tool == Tool.SELECT else self.view.tool_cursor())
            return
        if isinstance(self.ov, LineOverlay):
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        # pick a resize cursor matching the on-screen direction of the handle
        hp = self.handles()[idx]
        w, h = self.ov.size()
        vec = self.sceneTransform().map(hp) - self.sceneTransform().map(QPointF(w / 2, h / 2))
        ang = math.degrees(math.atan2(vec.y(), vec.x())) % 180
        cursors = [
            Qt.CursorShape.SizeHorCursor,
            Qt.CursorShape.SizeFDiagCursor,
            Qt.CursorShape.SizeVerCursor,
            Qt.CursorShape.SizeBDiagCursor,
        ]
        self.setCursor(cursors[int(((ang + 22.5) % 180) // 45)])

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.handle_at(event.pos())
            if idx is not None:
                self._drag = {
                    "handle": idx,
                    "inv": self.sceneTransform().inverted()[0],
                    "to_parent": self.itemTransform(self.parentItem())[0],
                    "ov": copy.deepcopy(self.ov),
                }
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        self.view.touch()
        d = self._drag
        m = d["inv"].map(event.scenePos())
        start: Overlay = d["ov"]
        to_parent: QTransform = d["to_parent"]
        idx = d["handle"]
        ov = self.ov
        if isinstance(ov, LineOverlay):
            if idx == 0:
                o = to_parent.map(m)
                ov.x, ov.y = o.x(), o.y()
                ov.dx, ov.dy = start.dx - m.x(), start.dy - m.y()
            else:
                ov.dx, ov.dy = m.x(), m.y()
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    ov.dx, ov.dy = _snap45(ov.dx, ov.dy)
        else:
            w0, h0 = start.size()
            left, right = idx in (0, 6, 7), idx in (2, 3, 4)
            top, bottom = idx in (0, 1, 2), idx in (4, 5, 6)
            w = w0 - m.x() if left else m.x() if right else w0
            h = h0 - m.y() if top else m.y() if bottom else h0
            w, h = max(w, 4.0), max(h, 4.0)
            keep = (
                isinstance(ov, TextOverlay)
                or getattr(ov, "keep_ratio", False)
                or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            )
            if keep and (left or right) and (top or bottom):
                s = max(w / w0, h / h0)
                w, h = w0 * s, h0 * s
            # reset from the starting state, then apply the new size
            for k, v in vars(start).items():
                if k not in ("uid", "group"):
                    setattr(ov, k, copy.deepcopy(v))
            ov.resize(w, h)
            aw, ah = ov.size()
            o = to_parent.map(QPointF(w0 - aw if left else 0.0, h0 - ah if top else 0.0))
            ov.x, ov.y = o.x(), o.y()
        self.refresh()
        self.view.overlay_geometry_changed.emit()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag is not None:
            self._drag = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if isinstance(self.ov, TextOverlay):
            self.start_editing()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        if not self.isSelected():
            self.scene().clearSelection()
            self.setSelected(True)
        self.view.overlay_context_menu(event.screenPos())
        event.accept()

    # ---------------------------------------------------------- text editing
    def start_editing(self, select_all: bool = False) -> None:
        if not isinstance(self.ov, TextOverlay) or self.editor is not None:
            return
        ov = self.ov
        self.view.begin_text_edit()
        ed = TextEditor(self)
        self.editor = ed
        ed.setFont(qfont(ov.family, ov.bold, ov.italic, 100))
        ed.setDefaultTextColor(qcolor(ov.color))
        ed.document().setDocumentMargin(0)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.NoWrap)
        opt.setAlignment(
            {"center": Qt.AlignmentFlag.AlignHCenter, "right": Qt.AlignmentFlag.AlignRight}.get(
                ov.align, Qt.AlignmentFlag.AlignLeft
            )
        )
        ed.document().setDefaultTextOption(opt)
        ed.setPlainText(ov.text)
        ed.setScale(ov.size_pt / 100.0)
        ed.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self._place_editor()
        ed.document().contentsChanged.connect(self._editor_changed)
        self.view.setFocus(Qt.FocusReason.MouseFocusReason)
        ed.setFocus(Qt.FocusReason.MouseFocusReason)
        cur = ed.textCursor()
        if select_all:
            cur.select(QTextCursor.SelectionType.Document)
        else:
            cur.movePosition(QTextCursor.MoveOperation.End)
        ed.setTextCursor(cur)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.update()

    def _place_editor(self) -> None:
        ov, ed = self.ov, self.editor
        lay = ov.layout()
        # Align the editor's first baseline with the one we paint.
        ascent = QFontMetricsF(ed.font()).ascent() * ov.size_pt / 100.0
        ed.setTextWidth(lay.width * 100.0 / ov.size_pt if ov.align != "left" else -1)
        ed.setPos(0, lay.ascender - ascent)

    def _editor_changed(self) -> None:
        if self.editor is None:
            return
        text = self.editor.toPlainText()
        if text == self.ov.text:
            return
        if not self.draft:
            self.view.touch()
        self.prepareGeometryChange()
        self.ov.text = text
        self._place_editor()
        self.update()

    def finish_editing(self) -> None:
        if self.editor is None:
            return
        ed, self.editor = self.editor, None
        self.ov.text = ed.toPlainText().rstrip("\n") if ed.toPlainText().strip() else ""
        ed.setParentItem(None)
        if ed.scene():
            ed.scene().removeItem(ed)
        ed.deleteLater()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.prepareGeometryChange()
        self.update()
        self.view.end_text_edit(self)


class TextEditor(QGraphicsTextItem):
    def __init__(self, owner: OverlayItem) -> None:
        super().__init__(owner)
        self.owner = owner

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            QTimer.singleShot(0, self.owner.finish_editing)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.owner.finish_editing()
            return
        super().keyPressEvent(event)


def _snap45(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return length * math.cos(ang), length * math.sin(ang)


# ======================================================================= view
class PageView(QGraphicsView):
    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    selection_changed = Signal(list)  # list[Overlay]
    tool_changed = Signal(object)
    overlay_geometry_changed = Signal()
    status_message = Signal(str)
    page_context_menu = Signal(int, object)  # page index, global pos

    def __init__(self, model: DocumentModel, renderer: Renderer, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self.model = model
        self.renderer = renderer
        self.defaults = ToolDefaults()
        self.tool = Tool.SELECT
        self.zoom = 1.0
        self.fit_mode: str | None = "width"
        self.pages: list[PageItem] = []
        self.pending_place: Overlay | None = None
        self._place_preview: OverlayItem | None = None
        self._draft: OverlayItem | None = None
        self._draft_page: PageItem | None = None
        self._draft_start = QPointF()
        self._touched = False
        self._text_session = False
        self._current = -1
        self._panning: QPointF | None = None
        self._space = False
        self._search_hits: list[tuple[int, list]] = []

        scene = QGraphicsScene(self)
        # Overlay bounds depend on the zoom (screen-sized handles); a BSP index
        # would go stale, and linear lookup is cheap at document scale.
        scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        self.setScene(scene)
        scene.selectionChanged.connect(self._on_selection)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setMouseTracking(True)
        renderer.rendered.connect(lambda _key: self.viewport().update())
        self.verticalScrollBar().valueChanged.connect(self._update_current)
        theme.theme and theme.theme.changed.connect(self.viewport().update)

    # -------------------------------------------------------------- model sync
    def set_model(self, model: DocumentModel) -> None:
        self.model = model
        self.scene().clear()
        self.pages = []
        self._draft = None
        self._place_preview = None
        self.pending_place = None
        self._search_hits = []
        self.sync_pages()
        self.fit_mode = "width"
        self.apply_fit()
        self._current = -1
        self.verticalScrollBar().setValue(0)
        self._update_current()
        # the viewport may still resize once the window is laid out
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(0))

    def sync_pages(self) -> None:
        existing = {p.ref.uid: p for p in self.pages}
        new_pages: list[PageItem] = []
        for ref in self.model.pages:
            item = existing.pop(ref.uid, None)
            if item is None:
                item = PageItem(self, ref)
                self.scene().addItem(item)
            else:
                item.set_ref(ref)
            new_pages.append(item)
        for item in existing.values():
            self.scene().removeItem(item)
        self.pages = new_pages
        self._layout()
        self.sync_overlays()
        self._update_current()

    def _layout(self) -> None:
        y = SCENE_MARGIN
        maxw = 0.0
        for item in self.pages:
            item.setPos(-item.w / 2, y)
            y += item.h + PAGE_GAP
            maxw = max(maxw, item.w)
        maxw = max(maxw, 200)
        self.scene().setSceneRect(
            QRectF(-maxw / 2 - SCENE_MARGIN, 0, maxw + 2 * SCENE_MARGIN, max(y - PAGE_GAP + SCENE_MARGIN, 100))
        )

    def sync_overlays(self) -> None:
        for page in self.pages:
            want = {ov.uid: ov for ov in page.ref.overlays}
            for uid, item in list(page.overlay_items.items()):
                if uid not in want:
                    if item.editor is not None:
                        item.editor = None
                    self.scene().removeItem(item)
                    del page.overlay_items[uid]
            for z, ov in enumerate(page.ref.overlays):
                item = page.overlay_items.get(ov.uid)
                if item is None:
                    item = OverlayItem(self, ov, page.frame)
                    page.overlay_items[ov.uid] = item
                elif item.editor is None:
                    item.refresh(ov)
                else:
                    item.ov = ov
                item.setZValue(z)
        self._on_selection()

    # ---------------------------------------------------------------- zoom
    def _base_scale(self) -> float:
        return self.logicalDpiX() / 72.0

    def set_zoom(self, zoom: float, anchor: QPointF | None = None, fit: str | None = None) -> None:
        zoom = max(0.1, min(8.0, zoom))
        self.fit_mode = fit
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        scene_anchor = self.mapToScene(anchor.toPoint())
        self.zoom = zoom
        s = zoom * self._base_scale()
        self.setTransform(QTransform.fromScale(s, s))
        # keep the anchor point under the cursor
        delta = self.mapFromScene(scene_anchor) - anchor.toPoint()
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta.y())
        for page in self.pages:
            for item in page.overlay_items.values():
                item.prepareGeometryChange()
        self.zoom_changed.emit(zoom)

    def apply_fit(self) -> None:
        if not self.pages or not self.fit_mode:
            return
        vw = self.viewport().width() - 2 * 24
        vh = self.viewport().height() - 2 * 16
        ref = self.pages[max(self._current, 0)] if self.pages else None
        if self.fit_mode == "width":
            # the scene adds a margin on each side of the widest page
            maxw = max(p.w for p in self.pages) + 2 * SCENE_MARGIN
            z = (self.viewport().width() - 2) / (maxw * self._base_scale())
        else:
            z = min(vw / (ref.w * self._base_scale()), vh / (ref.h * self._base_scale()))
        current = max(self._current, 0)
        # keep what is at the top of the viewport in place (not the centre),
        # so a freshly opened document stays at the top of its first page
        self.set_zoom(z, anchor=QPointF(self.viewport().width() / 2, 0), fit=self.fit_mode)
        if self.fit_mode == "page":
            self.go_to_page(current)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120.0
            self.set_zoom(self.zoom * (1.15**steps), anchor=event.position())
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------ navigation
    def _update_current(self) -> None:
        if not self.pages:
            if self._current != -1:
                self._current = -1
                self.current_page_changed.emit(-1)
            return
        center = self.mapToScene(self.viewport().rect().center())
        top = self.mapToScene(0, 0).y()
        idx = 0
        for i, page in enumerate(self.pages):
            if page.y() <= center.y() or page.y() <= top + 4:
                idx = i
        if idx != self._current:
            self._current = idx
            self.current_page_changed.emit(idx)

    def current_page(self) -> int:
        return self._current

    def go_to_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        page = self.pages[index]
        top = self.mapFromScene(QPointF(0, page.y() - PAGE_GAP / 2)).y()
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + top)
        self._update_current()

    def page_at(self, scene_pos: QPointF) -> PageItem | None:
        for page in self.pages:
            if page.sceneBoundingRect().adjusted(3, 2, -3, -4).contains(scene_pos):
                return page
        return None

    # ----------------------------------------------------------------- tools
    def set_tool(self, tool: Tool) -> None:
        if tool != Tool.PLACE:
            self._cancel_place()
        self.tool = tool
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if tool == Tool.SELECT else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(self.tool_cursor())
        if tool not in (Tool.SELECT, Tool.TEXT, Tool.PLACE):
            self.scene().clearSelection()
        self.tool_changed.emit(tool)
        self._on_selection()

    def tool_cursor(self) -> Qt.CursorShape:
        if self.tool == Tool.TEXT:
            return Qt.CursorShape.IBeamCursor
        if self.tool in DRAW_TOOLS:
            return Qt.CursorShape.CrossCursor
        if self.tool == Tool.PLACE:
            return Qt.CursorShape.DragCopyCursor
        return Qt.CursorShape.ArrowCursor

    def begin_place(self, ov: Overlay) -> None:
        """Let the user click where an image/signature should go."""
        self._cancel_place()
        self.pending_place = ov
        self.set_tool(Tool.PLACE)
        self.status_message.emit("Cliquez sur une page pour placer l'élément (Échap pour annuler)")

    def _cancel_place(self) -> None:
        if self._place_preview is not None:
            self.scene().removeItem(self._place_preview)
            self._place_preview = None
        self.pending_place = None

    def _update_place_preview(self, scene_pos: QPointF) -> None:
        page = self.page_at(scene_pos)
        if page is None or self.pending_place is None:
            if self._place_preview:
                self._place_preview.hide()
            return
        ov = self._centered_overlay(page, self.pending_place, scene_pos)
        if self._place_preview is None or self._place_preview.parentItem() is not page.frame:
            if self._place_preview is not None:
                self.scene().removeItem(self._place_preview)
            self._place_preview = OverlayItem(self, ov, page.frame, draft=True)
            self._place_preview.setOpacity(0.6)
            self._place_preview.setZValue(10_000)
        else:
            self._place_preview.refresh(ov)
        self._place_preview.show()

    def _centered_overlay(self, page: PageItem, template: Overlay, scene_pos: QPointF) -> Overlay:
        ov = copy.deepcopy(template)
        ov.rotation = (-page.ref.rotation) % 360
        local = page.frame.mapFromScene(scene_pos)
        _, _, w, h = ov.local_rect()
        t = QTransform().rotate(ov.rotation)
        c = t.map(QPointF(w / 2, h / 2))
        ov.x, ov.y = local.x() - c.x(), local.y() - c.y()
        return ov

    # --------------------------------------------------------- edit sessions
    def touch(self) -> None:
        """Called before an interactive change mutates an overlay."""
        if not self._touched:
            self._touched = True
            self.model.checkpoint()

    def _end_gesture(self) -> None:
        if self._touched and not self._text_session:
            self._touched = False
            self.model.notify("overlays")

    def begin_text_edit(self) -> None:
        self._text_session = True
        self._touched = False

    def end_text_edit(self, item: OverlayItem) -> None:
        self._text_session = False
        touched, self._touched = self._touched, False
        page = item.parentItem().parentItem()
        if item.draft:
            self.scene().removeItem(item)
            if item.ov.text.strip():
                item.ov.uid = new_uid()
                self.model.add_overlays(page.index, [item.ov])
                self.select_uids([item.ov.uid])
            return
        if not item.ov.text.strip():
            if touched:
                # Drop the text edit so deleting the box is a single undo step.
                self.model.discard_checkpoint()
            self.model.remove_overlays([item.ov.uid])
            return
        if touched:
            self.model.notify("overlays")

    # --------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        self._touched = False if not self._text_session else self._touched
        pos = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton or (self._space and event.button() == Qt.MouseButton.LeftButton):
            self._panning = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool == Tool.PLACE:
                page = self.page_at(pos)
                if page is not None and self.pending_place is not None:
                    ov = self._centered_overlay(page, self.pending_place, pos)
                    ov.uid = new_uid()
                    self._cancel_place()
                    self.model.add_overlays(page.index, [ov])
                    self.set_tool(Tool.SELECT)
                    self.select_uids([ov.uid])
                event.accept()
                return
            if self.tool == Tool.TEXT:
                hit = self._overlay_at(event.position().toPoint())
                if isinstance(hit, OverlayItem) and isinstance(hit.ov, TextOverlay):
                    super().mousePressEvent(event)
                    return
                page = self.page_at(pos)
                if page is not None:
                    self._create_text(page, pos)
                event.accept()
                return
            if self.tool in DRAW_TOOLS:
                page = self.page_at(pos)
                if page is not None:
                    self._start_draft(page, pos)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning is not None:
            delta = event.position() - self._panning
            self._panning = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        pos = self.mapToScene(event.position().toPoint())
        if self.tool == Tool.PLACE:
            self._update_place_preview(pos)
        if self._draft is not None:
            self._update_draft(pos, event.modifiers())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning is not None:
            self._panning = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if self._space else self.tool_cursor())
            event.accept()
            return
        if self._draft is not None and event.button() == Qt.MouseButton.LeftButton:
            self._commit_draft()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._end_gesture()

    def contextMenuEvent(self, event) -> None:
        item = self._overlay_at(event.pos())
        if item is not None:
            super().contextMenuEvent(event)
            return
        page = self.page_at(self.mapToScene(event.pos()))
        if page is not None:
            self.page_context_menu.emit(page.index, event.globalPos())

    def _overlay_at(self, view_pos) -> OverlayItem | None:
        for it in self.items(view_pos):
            while it is not None and not isinstance(it, OverlayItem):
                it = it.parentItem()
            if isinstance(it, OverlayItem) and not it.draft:
                return it
        return None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._text_session:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if key == Qt.Key.Key_Escape:
            if self._draft is not None:
                self.scene().removeItem(self._draft)
                self._draft = None
            elif self.tool != Tool.SELECT:
                self.set_tool(Tool.SELECT)
            else:
                self.scene().clearSelection()
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected_items():
            self.delete_selected()
            return
        arrows = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0), Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if key in arrows and self.selected_items():
            step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
            dx, dy = arrows[key]
            self._touched = False
            for item in self.selected_items():
                page = item.parentItem().parentItem()
                # nudge in screen direction: map through the page rotation
                inv = page.frame.transform().inverted()[0]
                v = inv.map(QPointF(dx * step, dy * step)) - inv.map(QPointF(0, 0))
                item.moveBy(v.x(), v.y())
            self._end_gesture()
            return
        if key == Qt.Key.Key_Return and len(self.selected_items()) == 1 and isinstance(self.selected_items()[0].ov, TextOverlay):
            self.selected_items()[0].start_editing()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(self.tool_cursor())
            return
        super().keyReleaseEvent(event)

    # --------------------------------------------------------------- drafts
    def _create_text(self, page: PageItem, scene_pos: QPointF) -> None:
        d = self.defaults
        ov = TextOverlay(
            text="",
            family=d.text_family,
            size_pt=d.text_size,
            color=d.text_color,
            bold=d.text_bold,
            italic=d.text_italic,
            align=d.text_align,
        )
        local = page.frame.mapFromScene(scene_pos)
        ov.rotation = (-page.ref.rotation) % 360
        # click point = start of the first line, vertically centred on the cursor
        lay = ov.layout()
        off = QTransform().rotate(ov.rotation).map(QPointF(0, lay.height / 2))
        ov.x, ov.y = local.x() - off.x(), local.y() - off.y()
        self.scene().clearSelection()
        item = OverlayItem(self, ov, page.frame, draft=True)
        item.setZValue(10_000)
        item.start_editing()

    def _start_draft(self, page: PageItem, scene_pos: QPointF) -> None:
        d = self.defaults
        local = page.frame.mapFromScene(scene_pos)
        t = self.tool
        if t in (Tool.LINE, Tool.ARROW):
            ov: Overlay = LineOverlay(
                shape="arrow" if t == Tool.ARROW else "line",
                x=local.x(),
                y=local.y(),
                dx=0,
                dy=0,
                stroke=d.shape_stroke or "#000000",
                width=d.shape_width,
                opacity=d.shape_opacity,
            )
        elif t == Tool.PEN:
            ov = InkOverlay(x=0, y=0, w=1, h=1, stroke=d.pen_color, width=d.pen_width, opacity=d.pen_opacity)
            ov._points = [(local.x(), local.y())]  # type: ignore[attr-defined]
        elif t == Tool.HIGHLIGHT:
            ov = BoxOverlay(
                shape="highlight",
                x=local.x(),
                y=local.y(),
                w=0,
                h=0,
                stroke=None,
                fill=d.highlight_color,
                width=0,
                fill_opacity=0.45,
            )
        elif t == Tool.REDACT:
            ov = BoxOverlay(shape="redact", x=local.x(), y=local.y(), w=0, h=0, stroke=None, fill="#000000", width=0)
        else:
            ov = BoxOverlay(
                shape="ellipse" if t == Tool.ELLIPSE else "rect",
                x=local.x(),
                y=local.y(),
                w=0,
                h=0,
                stroke=d.shape_stroke,
                fill=d.shape_fill,
                width=d.shape_width,
                opacity=d.shape_opacity,
                fill_opacity=d.shape_opacity,
            )
        self._draft_page = page
        self._draft_start = local
        self._draft = OverlayItem(self, ov, page.frame, draft=True)
        self._draft.setZValue(10_000)

    def _update_draft(self, scene_pos: QPointF, mods) -> None:
        page = self._draft_page
        local = page.frame.mapFromScene(scene_pos)
        ov = self._draft.ov
        s = self._draft_start
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if isinstance(ov, LineOverlay):
            ov.dx, ov.dy = local.x() - s.x(), local.y() - s.y()
            if shift:
                ov.dx, ov.dy = _snap45(ov.dx, ov.dy)
        elif isinstance(ov, InkOverlay):
            pts = ov._points  # type: ignore[attr-defined]
            last = pts[-1]
            if math.hypot(local.x() - last[0], local.y() - last[1]) >= 0.8 / max(self.zoom, 0.1):
                pts.append((local.x(), local.y()))
                new = InkOverlay.from_points([pts], stroke=ov.stroke, width=ov.width, opacity=ov.opacity)
                new._points = pts  # type: ignore[attr-defined]
                self._draft.ov = new
        else:
            dx, dy = local.x() - s.x(), local.y() - s.y()
            if shift:
                m = max(abs(dx), abs(dy))
                dx, dy = math.copysign(m, dx), math.copysign(m, dy)
            ov.x, ov.y = min(s.x(), s.x() + dx), min(s.y(), s.y() + dy)
            ov.w, ov.h = abs(dx), abs(dy)
        self._draft.refresh()

    def _commit_draft(self) -> None:
        item, page = self._draft, self._draft_page
        self._draft = None
        self.scene().removeItem(item)
        ov = item.ov
        min_size = 3.0
        if isinstance(ov, LineOverlay):
            ok = math.hypot(ov.dx, ov.dy) >= min_size
        elif isinstance(ov, InkOverlay):
            ok = True
            pts = getattr(ov, "_points", [])
            ov = InkOverlay.from_points([pts], stroke=ov.stroke, width=ov.width, opacity=ov.opacity)
        else:
            ok = ov.w >= min_size and ov.h >= min_size
        if ok:
            ov.uid = new_uid()
            self.model.add_overlays(page.index, [ov])
            if not isinstance(ov, InkOverlay):
                self.select_uids([ov.uid])

    # ------------------------------------------------------------ selection
    def selected_items(self) -> list[OverlayItem]:
        return [i for i in self.scene().selectedItems() if isinstance(i, OverlayItem)]

    def selected_overlays(self) -> list[Overlay]:
        return [i.ov for i in self.selected_items()]

    def select_uids(self, uids: list[str]) -> None:
        self.scene().clearSelection()
        for page in self.pages:
            for uid in uids:
                item = page.overlay_items.get(uid)
                if item is not None:
                    item.setSelected(True)
        self.setFocus()

    def _on_selection(self) -> None:
        if self.scene() is None:
            return
        self.selection_changed.emit(self.selected_overlays())

    def delete_selected(self) -> None:
        uids = [o.uid for o in self.selected_overlays()]
        if uids:
            self.model.remove_overlays(uids)

    def duplicate_selected(self) -> None:
        items = self.selected_items()
        if not items:
            return
        self.model.checkpoint()
        new_uids = []
        for item in items:
            page = item.parentItem().parentItem()
            dup = copy.deepcopy(item.ov)
            dup.uid = new_uid()
            dup.group = ""
            off = page.frame.transform().inverted()[0].map(QPointF(12, 12)) - page.frame.transform().inverted()[0].map(
                QPointF(0, 0)
            )
            dup.x += off.x()
            dup.y += off.y()
            page.ref.overlays.append(dup)
            new_uids.append(dup.uid)
        self.model.notify("overlays")
        self.select_uids(new_uids)

    def rotate_selected(self, delta: float = 90) -> None:
        uids = [o.uid for o in self.selected_overlays() if not isinstance(o, LineOverlay)]

        def rot(ov: Overlay) -> None:
            # rotate around the centre
            _, _, w, h = ov.local_rect()
            before = QTransform().rotate(ov.rotation).map(QPointF(w / 2, h / 2))
            ov.rotation = (ov.rotation + delta) % 360
            after = QTransform().rotate(ov.rotation).map(QPointF(w / 2, h / 2))
            ov.x += before.x() - after.x()
            ov.y += before.y() - after.y()

        self.model.edit_overlays(uids, rot)

    def reorder_selected(self, to_front: bool) -> None:
        uids = {o.uid for o in self.selected_overlays()}
        if not uids:
            return
        self.model.checkpoint()
        for ref in self.model.pages:
            sel = [o for o in ref.overlays if o.uid in uids]
            rest = [o for o in ref.overlays if o.uid not in uids]
            ref.overlays = rest + sel if to_front else sel + rest
        self.model.notify("overlays")

    def overlay_context_menu(self, global_pos) -> None:
        menu = QMenu(self)
        menu.addAction(theme.icon("copy"), "Dupliquer", self.duplicate_selected)
        menu.addAction(theme.icon("rotate-cw"), "Pivoter de 90°", lambda: self.rotate_selected(90))
        menu.addSeparator()
        menu.addAction(theme.icon("chevron-up"), "Premier plan", lambda: self.reorder_selected(True))
        menu.addAction(theme.icon("chevron-down"), "Arrière-plan", lambda: self.reorder_selected(False))
        menu.addSeparator()
        menu.addAction(theme.icon("trash-2"), "Supprimer", self.delete_selected)
        menu.exec(global_pos)

    # --------------------------------------------------------------- search
    def show_search_hits(self, hits: list[tuple[int, list]], current: int) -> None:
        for page in self.pages:
            for r in page.search_items:
                self.scene().removeItem(r)
            page.search_items = []
        accent = QColor(theme.colors().accent)
        n = 0
        for page_index, rects in hits:
            page = self.pages[page_index]
            for rect in rects:
                is_cur = n == current
                item = QGraphicsRectItem(QRectF(rect.x0, rect.y0, rect.width, rect.height), page.frame)
                fill = QColor("#ff9632" if is_cur else "#ffd84d")
                fill.setAlphaF(0.45)
                item.setBrush(fill)
                item.setPen(QPen(accent if is_cur else Qt.PenStyle.NoPen, 0))
                item.setZValue(-1)
                page.search_items.append(item)
                if is_cur:
                    self.ensureVisible(item.sceneBoundingRect(), 80, 120)
                n += 1
