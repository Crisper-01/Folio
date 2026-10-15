"""Paint overlays with QPainter, mirroring what export.py writes to the PDF."""

from __future__ import annotations

from functools import cache, lru_cache

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QGlyphRun,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRawFont,
)

from ..fonts import FAMILIES, fitz_font, font_bytes, resolve_face
from ..overlays import BoxOverlay, ImageOverlay, InkOverlay, LineOverlay, Overlay, TextOverlay, smooth_path


def qcolor(hex_color: str | None, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color or "#000000")
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# --------------------------------------------------------------------- fonts
@cache
def qt_family(family: str, face: str = "regular") -> str:
    """Register the font file with Qt (once) and return its family name."""
    fid = QFontDatabase.addApplicationFontFromData(QByteArray(font_bytes(family, face)))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    return fams[0] if fams else "Sans Serif"


def qfont(family: str, bold: bool = False, italic: bool = False, pixel_size: int = 100) -> QFont:
    fam, face = resolve_face(family, bold, italic)
    for f in FAMILIES[fam].faces:
        qt_family(fam, f)
    font = QFont(qt_family(fam, "regular"))
    font.setBold(face in ("bold", "bolditalic"))
    font.setItalic(face in ("italic", "bolditalic"))
    font.setPixelSize(pixel_size)
    font.setKerning(False)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


@lru_cache(maxsize=64)
def _raw_font(family: str, face: str, size: float) -> QRawFont:
    return QRawFont(QByteArray(font_bytes(family, face)), size, QFont.HintingPreference.PreferNoHinting)


def _glyph_run(family: str, face: str, size: float, text: str) -> QGlyphRun:
    """Glyphs positioned with the PDF font's own advances (exact WYSIWYG)."""
    raw = _raw_font(family, face, size)
    advances = fitz_font(family, face).char_lengths(text, fontsize=size)
    glyphs, positions, x = [], [], 0.0
    for ch, adv in zip(text, advances, strict=True):
        idx = raw.glyphIndexesForString(ch)
        if idx:
            glyphs.append(idx[0])
            positions.append(QPointF(x, 0))
        x += adv
    run = QGlyphRun()
    run.setRawFont(raw)
    run.setGlyphIndexes(glyphs)
    run.setPositions(positions)
    return run


def paint_text(p: QPainter, ov: TextOverlay, draw_text: bool = True) -> None:
    if not draw_text:
        return
    lay = ov.layout()
    fam, face = resolve_face(ov.family, ov.bold, ov.italic)
    p.setPen(qcolor(ov.color, ov.opacity))
    for i, line in enumerate(lay.lines):
        if line:
            p.drawGlyphRun(QPointF(lay.line_x(i, ov.align), lay.baseline(i)), _glyph_run(fam, face, ov.size_pt, line))


# -------------------------------------------------------------------- shapes
def paint_box(p: QPainter, ov: BoxOverlay) -> None:
    rect = QRectF(0, 0, ov.w, ov.h)
    if ov.shape == "highlight":
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        p.fillRect(rect, qcolor(ov.fill or "#ffe14d", ov.fill_opacity))
        p.restore()
        return
    if ov.shape == "redact":
        p.fillRect(rect, qcolor(ov.fill or "#000000"))
        return
    path = QPainterPath()
    if ov.shape == "ellipse":
        path.addEllipse(rect)
    else:
        path.addRect(rect)
    if ov.fill:
        p.fillPath(path, qcolor(ov.fill, ov.fill_opacity))
    if ov.stroke and ov.width > 0:
        pen = QPen(qcolor(ov.stroke, ov.opacity), ov.width)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.strokePath(path, pen)


def paint_line(p: QPainter, ov: LineOverlay) -> None:
    color = qcolor(ov.stroke, ov.opacity)
    pen = QPen(color, ov.width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    ex, ey = ov.shaft_end()
    p.drawLine(QPointF(0, 0), QPointF(ex, ey))
    head = ov.arrow_head()
    if head:
        pen = QPen(color, max(ov.width * 0.5, 0.5))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(QBrush(color))
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in head]))
        p.setBrush(Qt.BrushStyle.NoBrush)


def ink_path(strokes: list[list[tuple[float, float]]]) -> QPainterPath:
    path = QPainterPath()
    for stroke in strokes:
        if len(stroke) == 1:
            stroke = [stroke[0], (stroke[0][0] + 0.01, stroke[0][1])]
        for cmd in smooth_path(stroke):
            if cmd[0] == "M":
                path.moveTo(*cmd[1])
            elif cmd[0] == "L":
                path.lineTo(*cmd[1])
            else:
                path.quadTo(QPointF(*cmd[1]), QPointF(*cmd[2]))
    return path


def ink_pen(color: str, width: float, opacity: float = 1.0) -> QPen:
    pen = QPen(qcolor(color, opacity), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def paint_ink(p: QPainter, ov: InkOverlay) -> None:
    p.strokePath(ink_path(ov.scaled_strokes()), ink_pen(ov.stroke, ov.width, ov.opacity))


@lru_cache(maxsize=32)
def _qimage(data: bytes) -> QImage:
    img = QImage()
    img.loadFromData(data)
    return img


def paint_image(p: QPainter, ov: ImageOverlay) -> None:
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawImage(QRectF(0, 0, ov.w, ov.h), _qimage(ov.data))


def paint_overlay(p: QPainter, ov: Overlay, draw_text: bool = True) -> None:
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if isinstance(ov, TextOverlay):
        paint_text(p, ov, draw_text)
    elif isinstance(ov, BoxOverlay):
        paint_box(p, ov)
    elif isinstance(ov, LineOverlay):
        paint_line(p, ov)
    elif isinstance(ov, InkOverlay):
        paint_ink(p, ov)
    elif isinstance(ov, ImageOverlay):
        paint_image(p, ov)


def overlay_margin(ov: Overlay) -> float:
    """How far painting may exceed local_rect (stroke widths)."""
    w = getattr(ov, "width", 0.0) or 0.0
    if isinstance(ov, LineOverlay) and ov.shape == "arrow":
        w = max(w * 4, 8)
    return w


def paint_overlays_on_page(p: QPainter, overlays: list[Overlay], unrotated_to_display) -> None:
    """Paint all overlays given a QTransform mapping unrotated page space to
    the painter's current coordinate system (used for thumbnails/printing)."""
    for ov in overlays:
        p.save()
        p.setTransform(unrotated_to_display, True)
        p.translate(ov.x, ov.y)
        p.rotate(ov.rotation)
        paint_overlay(p, ov)
        p.restore()
