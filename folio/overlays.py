"""Editable objects placed on top of a page until the document is saved.

Every overlay lives in the *unrotated* coordinate space of its page (the
space PyMuPDF drawing methods use, origin at the top-left). ``x``/``y`` is the
origin of the overlay's local frame and ``rotation`` (degrees, clockwise)
rotates that frame around it. Local geometry always starts at (0, 0).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .fonts import TextLayout, layout_text


def new_uid() -> str:
    return uuid.uuid4().hex


@dataclass
class Overlay:
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    uid: str = field(default_factory=new_uid)
    # Tag for overlays generated as a set (e.g. "watermark", "pagenum") so the
    # generating tool can find, replace or remove them later.
    group: str = ""

    kind = "overlay"

    def size(self) -> tuple[float, float]:
        raise NotImplementedError

    def local_rect(self) -> tuple[float, float, float, float]:
        w, h = self.size()
        return (0.0, 0.0, w, h)

    def resize(self, w: float, h: float) -> None:
        raise NotImplementedError


@dataclass
class TextOverlay(Overlay):
    text: str = ""
    family: str = "sans"
    size_pt: float = 14.0
    color: str = "#111111"
    bold: bool = False
    italic: bool = False
    align: str = "left"
    opacity: float = 1.0
    spacing: float = 1.2

    kind = "text"

    def layout(self) -> TextLayout:
        return layout_text(self.text, self.family, self.bold, self.italic, self.size_pt, self.spacing)

    def size(self) -> tuple[float, float]:
        lay = self.layout()
        return lay.width, lay.height

    def resize(self, w: float, h: float) -> None:
        # Text boxes scale their font size with the box height.
        _, cur_h = self.size()
        if cur_h > 0 and h > 0:
            self.size_pt = max(4.0, min(400.0, self.size_pt * h / cur_h))


# Box shapes: "rect", "ellipse", "highlight", "redact"
@dataclass
class BoxOverlay(Overlay):
    shape: str = "rect"
    w: float = 100.0
    h: float = 60.0
    stroke: str | None = "#1f4fd8"
    fill: str | None = None
    width: float = 2.0
    opacity: float = 1.0
    fill_opacity: float = 1.0

    kind = "box"

    def size(self) -> tuple[float, float]:
        return self.w, self.h

    def resize(self, w: float, h: float) -> None:
        self.w, self.h = max(1.0, w), max(1.0, h)


# Line shapes: "line", "arrow". The line goes from (0, 0) to (dx, dy).
@dataclass
class LineOverlay(Overlay):
    shape: str = "line"
    dx: float = 100.0
    dy: float = 0.0
    stroke: str = "#1f4fd8"
    width: float = 2.0
    opacity: float = 1.0

    kind = "line"

    def size(self) -> tuple[float, float]:
        return abs(self.dx), abs(self.dy)

    def local_rect(self) -> tuple[float, float, float, float]:
        return (min(0, self.dx), min(0, self.dy), abs(self.dx), abs(self.dy))

    def resize(self, w: float, h: float) -> None:
        pass

    def arrow_head(self) -> list[tuple[float, float]] | None:
        """Triangle of the arrow head (tip first), or None for a plain line."""
        if self.shape != "arrow":
            return None
        import math

        length = math.hypot(self.dx, self.dy)
        if length < 1e-6:
            return None
        ux, uy = self.dx / length, self.dy / length
        head = min(length * 0.6, max(8.0, self.width * 4.0))
        half = head * 0.5
        bx, by = self.dx - ux * head, self.dy - uy * head
        return [(self.dx, self.dy), (bx - uy * half, by + ux * half), (bx + uy * half, by - ux * half)]

    def shaft_end(self) -> tuple[float, float]:
        """End of the shaft: stop under the head so the tip stays sharp."""
        head = self.arrow_head()
        if not head:
            return self.dx, self.dy
        (_, _), (ax, ay), (bx, by) = head
        return (ax + bx) / 2, (ay + by) / 2


@dataclass
class InkOverlay(Overlay):
    """Free-hand strokes. Points are normalised to the [0, 1] box (w x h)."""

    w: float = 100.0
    h: float = 50.0
    strokes: list[list[tuple[float, float]]] = field(default_factory=list)
    stroke: str = "#0b1f66"
    width: float = 2.0
    opacity: float = 1.0
    keep_ratio = True

    kind = "ink"

    def size(self) -> tuple[float, float]:
        return self.w, self.h

    def resize(self, w: float, h: float) -> None:
        self.w, self.h = max(1.0, w), max(1.0, h)

    def scaled_strokes(self) -> list[list[tuple[float, float]]]:
        return [[(px * self.w, py * self.h) for px, py in s] for s in self.strokes]

    @classmethod
    def from_points(cls, strokes: list[list[tuple[float, float]]], pad: float = 0.0, **kw) -> InkOverlay:
        """Build from absolute strokes; the overlay origin becomes their bbox corner."""
        xs = [p[0] for s in strokes for p in s]
        ys = [p[1] for s in strokes for p in s]
        x0, y0 = min(xs) - pad, min(ys) - pad
        w = max(max(xs) + pad - x0, 1.0)
        h = max(max(ys) + pad - y0, 1.0)
        norm = [[((px - x0) / w, (py - y0) / h) for px, py in s] for s in strokes]
        return cls(x=x0, y=y0, w=w, h=h, strokes=norm, **kw)


@dataclass
class ImageOverlay(Overlay):
    w: float = 100.0
    h: float = 100.0
    data: bytes = b""
    keep_ratio = True

    kind = "image"

    def size(self) -> tuple[float, float]:
        return self.w, self.h

    def resize(self, w: float, h: float) -> None:
        self.w, self.h = max(1.0, w), max(1.0, h)


def smooth_path(points: list[tuple[float, float]]) -> list[tuple]:
    """Turn a polyline into drawing commands with quadratic midpoint smoothing.

    Returns ("M", p) / ("L", p) / ("Q", ctrl, end) commands shared by the Qt
    painter and the PDF writer so both draw the exact same curve.
    """
    if not points:
        return []
    if len(points) < 3:
        return [("M", points[0])] + [("L", p) for p in points[1:]]
    cmds: list[tuple] = [("M", points[0])]
    for i in range(1, len(points) - 1):
        mid = ((points[i][0] + points[i + 1][0]) / 2, (points[i][1] + points[i + 1][1]) / 2)
        cmds.append(("Q", points[i], mid))
    cmds.append(("L", points[-1]))
    return cmds
