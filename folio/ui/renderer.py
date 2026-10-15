"""Lazy, cached page rasterisation driven by an idle timer.

MuPDF is not thread safe, so rendering stays on the GUI thread but happens
one page per event-loop tick, newest request first, keeping scrolling fluid.
"""

from __future__ import annotations

from collections import OrderedDict

import pymupdf
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QTransform

from ..model import DocumentModel, PageRef

MAX_PIXELS = 7000 * 7000
CACHE_BYTES = 600 * 1024 * 1024


def page_transform(w: float, h: float, rotation: int) -> QTransform:
    """Map unrotated page coordinates (w x h) to displayed coordinates."""
    r = rotation % 360
    if r == 90:
        return QTransform(0, 1, -1, 0, h, 0)
    if r == 180:
        return QTransform(-1, 0, 0, -1, w, h)
    if r == 270:
        return QTransform(0, -1, 1, 0, 0, w)
    return QTransform()


def render_page(model: DocumentModel, ref: PageRef, scale: float) -> QImage:
    page = model.fitz_page(ref)
    w, h = page.rect.width, page.rect.height
    scale = min(scale, (MAX_PIXELS / max(w * h, 1)) ** 0.5)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return img.copy()


class Renderer(QObject):
    rendered = Signal(object)  # cache key

    def __init__(self, model: DocumentModel) -> None:
        super().__init__()
        self.model = model
        self._cache: OrderedDict[tuple, tuple[float, QImage]] = OrderedDict()
        self._bytes = 0
        self._pending: OrderedDict[tuple, tuple[PageRef, float]] = OrderedDict()
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._work)

    def set_model(self, model: DocumentModel) -> None:
        self.model = model
        self._cache.clear()
        self._pending.clear()
        self._bytes = 0

    @staticmethod
    def key(ref: PageRef, thumb: bool) -> tuple:
        return (ref.src, ref.index, ref.rotation % 360, thumb)

    def get(self, ref: PageRef, scale: float, thumb: bool = False) -> QImage | None:
        """Best image available now; schedules a sharper one if needed."""
        key = self.key(ref, thumb)
        hit = self._cache.get(key)
        if hit:
            self._cache.move_to_end(key)
            if scale * 0.9 <= hit[0] <= scale * 1.6:
                return hit[1]
        self._pending[key] = (ref, scale)
        self._pending.move_to_end(key)
        if not self._timer.isActive():
            self._timer.start()
        return hit[1] if hit else None

    def _work(self) -> None:
        if not self._pending:
            self._timer.stop()
            return
        key, (ref, scale) = self._pending.popitem(last=True)
        if ref.src not in self.model.sources:
            return
        img = render_page(self.model, ref, scale)
        old = self._cache.pop(key, None)
        if old:
            self._bytes -= old[1].sizeInBytes()
        self._cache[key] = (scale, img)
        self._bytes += img.sizeInBytes()
        while self._bytes > CACHE_BYTES and len(self._cache) > 1:
            _, (_, evicted) = self._cache.popitem(last=False)
            self._bytes -= evicted.sizeInBytes()
        self.rendered.emit(key)
