"""Overlays generated in bulk: watermarks, page numbers, image-to-PDF.

They are regular overlays tagged with a ``group``, so they stay editable,
show up live in the editor and can be replaced or removed in one step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf

from .model import A4, DocumentModel, PageRef, image_page_doc
from .overlays import ImageOverlay, Overlay, TextOverlay

WATERMARK = "watermark"
PAGENUM = "pagenum"


def display_to_unrotated(model: DocumentModel, ref: PageRef, X: float, Y: float) -> tuple[float, float]:
    w, h = model.unrotated_size(ref)
    r = ref.rotation % 360
    if r == 90:
        return Y, h - X
    if r == 180:
        return w - X, h - Y
    if r == 270:
        return w - Y, X
    return X, Y


def place_centered(model: DocumentModel, ref: PageRef, ov: Overlay, X: float, Y: float, angle: float = 0.0) -> None:
    """Put the overlay's centre on display point (X, Y), upright on screen,
    then turned counter-clockwise by ``angle`` degrees."""
    ov.rotation = (-ref.rotation - angle) % 360
    lx, ly, lw, lh = ov.local_rect()
    cx, cy = lx + lw / 2, ly + lh / 2
    a = math.radians(ov.rotation)
    rx, ry = cx * math.cos(a) - cy * math.sin(a), cx * math.sin(a) + cy * math.cos(a)
    ux, uy = display_to_unrotated(model, ref, X, Y)
    ov.x, ov.y = ux - rx, uy - ry


def _rotated_extent(w: float, h: float, angle: float) -> tuple[float, float]:
    a = math.radians(angle)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    return w * c + h * s, w * s + h * c


@dataclass
class WatermarkOptions:
    text: str = "CONFIDENTIEL"
    image: bytes = b""  # PNG with the opacity already applied; used when set
    image_scale: float = 0.5  # fraction of the page width
    family: str = "sans"
    bold: bool = True
    color: str = "#d63c3c"
    opacity: float = 0.25
    size_pt: float = 0.0  # 0 = fit the page
    angle: float = 45.0
    tiled: bool = False
    pages: list[int] | None = None  # None = all pages


def watermark_for(model: DocumentModel, ref: PageRef, o: WatermarkOptions) -> list[Overlay]:
    W, H = model.display_size(ref)

    def make() -> Overlay:
        if o.image:
            pix = pymupdf.Pixmap(o.image)
            target_w = W * o.image_scale * (0.45 if o.tiled else 1.0)
            return ImageOverlay(w=target_w, h=target_w * pix.height / pix.width, data=o.image, group=WATERMARK)
        ov = TextOverlay(text=o.text, family=o.family, bold=o.bold, color=o.color, opacity=o.opacity, group=WATERMARK)
        ov.align = "center"
        if o.size_pt > 0:
            ov.size_pt = o.size_pt
        else:
            # Fit the rotated text inside 80% of the page (or a tile).
            ov.size_pt = 100.0
            tw, th = ov.size()
            ew, eh = _rotated_extent(tw, th, o.angle)
            frac = 0.8 if not o.tiled else 0.3
            ov.size_pt = max(6.0, min(400.0, 100.0 * min(W * frac / ew, H * frac / eh)))
        return ov

    angle = 0.0 if o.image and not o.tiled else o.angle
    if not o.tiled:
        ov = make()
        place_centered(model, ref, ov, W / 2, H / 2, angle)
        return [ov]

    probe = make()
    ew, eh = _rotated_extent(*probe.size(), angle)
    step_x, step_y = ew * 1.35 + 24, eh * 1.6 + 24
    out: list[Overlay] = []
    rows = int(H / step_y) + 2
    cols = int(W / step_x) + 2
    for r in range(rows):
        offset = step_x / 2 if r % 2 else 0
        for c in range(-1, cols):
            X, Y = c * step_x + offset + step_x / 2, r * step_y + step_y / 2
            if -ew / 2 < X < W + ew / 2 and -eh / 2 < Y < H + eh / 2:
                ov = make()
                place_centered(model, ref, ov, X, Y, angle)
                out.append(ov)
    return out


def apply_group(model: DocumentModel, group: str, per_page: dict[int, list[Overlay]]) -> None:
    """Replace every overlay of ``group`` with the given ones (one undo step)."""
    model.checkpoint()
    for i, ref in enumerate(model.pages):
        ref.overlays = [o for o in ref.overlays if o.group != group] + per_page.get(i, [])
    model.notify("overlays")


def has_group(model: DocumentModel, group: str) -> bool:
    return any(o.group == group for ref in model.pages for o in ref.overlays)


def apply_watermark(model: DocumentModel, opts: WatermarkOptions) -> None:
    pages = range(model.page_count()) if opts.pages is None else opts.pages
    apply_group(model, WATERMARK, {i: watermark_for(model, model.pages[i], opts) for i in pages})


# ----------------------------------------------------------------- page numbers
POSITIONS = {
    "bottom-center": ("bottom", "center"),
    "bottom-right": ("bottom", "right"),
    "bottom-left": ("bottom", "left"),
    "top-center": ("top", "center"),
    "top-right": ("top", "right"),
    "top-left": ("top", "left"),
}


@dataclass
class PageNumberOptions:
    template: str = "{n} / {total}"
    position: str = "bottom-center"
    margin: float = 28.0
    family: str = "sans"
    size_pt: float = 10.0
    color: str = "#444444"
    start: int = 1
    skip_first: bool = False


def apply_page_numbers(model: DocumentModel, o: PageNumberOptions) -> None:
    vert, horiz = POSITIONS.get(o.position, POSITIONS["bottom-center"])
    first = 1 if o.skip_first else 0
    total = model.page_count() - first + o.start - 1
    per_page: dict[int, list[Overlay]] = {}
    for i in range(first, model.page_count()):
        ref = model.pages[i]
        W, H = model.display_size(ref)
        n = i - first + o.start
        ov = TextOverlay(
            text=o.template.replace("{n}", str(n)).replace("{total}", str(total)),
            family=o.family,
            size_pt=o.size_pt,
            color=o.color,
            group=PAGENUM,
        )
        tw, th = ov.size()
        X = {"left": o.margin + tw / 2, "center": W / 2, "right": W - o.margin - tw / 2}[horiz]
        Y = o.margin + th / 2 if vert == "top" else H - o.margin - th / 2
        place_centered(model, ref, ov, X, Y)
        per_page[i] = [ov]
    apply_group(model, PAGENUM, per_page)


# ---------------------------------------------------------------- images to PDF
PAGE_SIZES: dict[str, tuple[float, float] | None] = {
    "a4": A4,
    "letter": (612.0, 792.0),
    "image": None,
}


@dataclass
class ImagesToPdfOptions:
    page_size: str = "a4"
    margin: float = 0.0
    watermark: WatermarkOptions | None = None
    images: list[bytes] = field(default_factory=list)


def images_to_model(opts: ImagesToPdfOptions, name: str = "Images") -> DocumentModel:
    model = DocumentModel.empty()
    doc = pymupdf.open()
    for data in opts.images:
        image_page_doc(data, PAGE_SIZES.get(opts.page_size, A4), opts.margin, doc=doc)
    model.insert_document(doc, name, 0)
    if opts.watermark:
        apply_watermark(model, opts.watermark)
    # A brand new document: nothing to undo yet, but it is unsaved.
    model.clear_history()
    return model
