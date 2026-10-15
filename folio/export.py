"""Turn a DocumentModel into a real PDF: copy pages, burn overlays, save."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .fonts import fitz_font, resolve_face
from .model import DocumentModel, Security
from .overlays import BoxOverlay, ImageOverlay, InkOverlay, LineOverlay, Overlay, TextOverlay, smooth_path


def hex_rgb(color: str | None) -> tuple[float, float, float] | None:
    if not color:
        return None
    c = color.lstrip("#")
    return tuple(int(c[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _local_to_page(ov: Overlay, px: float, py: float) -> pymupdf.Point:
    return pymupdf.Point(px, py) * pymupdf.Matrix(ov.rotation) + (ov.x, ov.y)


def _morph(ov: Overlay):
    # PyMuPDF applies morph matrices in PDF space (y up), hence the sign flip.
    return (pymupdf.Point(ov.x, ov.y), pymupdf.Matrix(-ov.rotation)) if ov.rotation else None


def _page_rect(ov: Overlay) -> pymupdf.Rect:
    """Axis-aligned bounding box of the overlay in page coordinates."""
    x, y, w, h = ov.local_rect()
    pts = [_local_to_page(ov, px, py) for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h))]
    return pymupdf.Rect(min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts))


def _draw_text(page: pymupdf.Page, ov: TextOverlay) -> None:
    if not ov.text.strip():
        return
    lay = ov.layout()
    fam, face = resolve_face(ov.family, ov.bold, ov.italic)
    font = fitz_font(fam, face)
    tw = pymupdf.TextWriter(page.rect)
    for i, line in enumerate(lay.lines):
        if line:
            tw.append((ov.x + lay.line_x(i, ov.align), ov.y + lay.baseline(i)), line, font=font, fontsize=ov.size_pt)
    tw.write_text(page, color=hex_rgb(ov.color), opacity=ov.opacity, morph=_morph(ov))


def _draw_box(page: pymupdf.Page, ov: BoxOverlay) -> None:
    rect = pymupdf.Rect(ov.x, ov.y, ov.x + ov.w, ov.y + ov.h)
    if ov.shape == "highlight":
        annot = page.add_highlight_annot(quads=_page_rect(ov).quad)
        annot.set_colors(stroke=hex_rgb(ov.fill or "#ffe14d"))
        annot.set_opacity(min(1.0, max(0.1, ov.fill_opacity)))
        annot.update()
        return
    shape = page.new_shape()
    if ov.shape == "ellipse":
        shape.draw_oval(rect)
    else:
        shape.draw_rect(rect)
    stroke = hex_rgb(ov.stroke) if ov.width > 0 else None
    shape.finish(
        color=stroke,
        fill=hex_rgb(ov.fill),
        width=ov.width if stroke else 0,
        stroke_opacity=ov.opacity,
        fill_opacity=ov.fill_opacity,
        morph=_morph(ov),
    )
    shape.commit()


def _draw_line(page: pymupdf.Page, ov: LineOverlay) -> None:
    shape = page.new_shape()
    o = pymupdf.Point(ov.x, ov.y)
    ex, ey = ov.shaft_end()
    shape.draw_line(o, o + (ex, ey))
    shape.finish(color=hex_rgb(ov.stroke), width=ov.width, lineCap=1, stroke_opacity=ov.opacity, morph=_morph(ov))
    head = ov.arrow_head()
    if head:
        shape.draw_polyline([o + p for p in head])
        shape.finish(
            color=hex_rgb(ov.stroke),
            fill=hex_rgb(ov.stroke),
            width=max(ov.width * 0.5, 0.5),
            lineJoin=1,
            closePath=True,
            stroke_opacity=ov.opacity,
            fill_opacity=ov.opacity,
            morph=_morph(ov),
        )
    shape.commit()


def _draw_ink(page: pymupdf.Page, ov: InkOverlay) -> None:
    shape = page.new_shape()
    o = pymupdf.Point(ov.x, ov.y)
    drew = False
    for stroke in ov.scaled_strokes():
        if len(stroke) == 1:
            stroke = [stroke[0], (stroke[0][0] + 0.01, stroke[0][1])]
        cur = None
        for cmd in smooth_path(stroke):
            if cmd[0] == "M":
                cur = o + cmd[1]
            elif cmd[0] == "L":
                end = o + cmd[1]
                shape.draw_line(cur, end)
                cur = end
            else:  # quadratic -> cubic
                ctrl, end = o + cmd[1], o + cmd[2]
                c1 = cur + (ctrl - cur) * (2 / 3)
                c2 = end + (ctrl - end) * (2 / 3)
                shape.draw_bezier(cur, c1, c2, end)
                cur = end
            drew = True
    if drew:
        shape.finish(
            color=hex_rgb(ov.stroke),
            width=ov.width,
            lineCap=1,
            lineJoin=1,
            closePath=False,
            stroke_opacity=ov.opacity,
            morph=_morph(ov),
        )
        shape.commit()


def _draw_image(page: pymupdf.Page, ov: ImageOverlay) -> None:
    if not ov.data:
        return
    # insert_image only rotates by multiples of 90 within the target rect.
    rot = int(round(ov.rotation / 90.0)) * 90 % 360
    page.insert_image(_page_rect(ov), stream=ov.data, rotate=(-rot) % 360, keep_proportion=False)


DRAWERS = {"text": _draw_text, "box": _draw_box, "line": _draw_line, "ink": _draw_ink, "image": _draw_image}


def burn_overlays(page: pymupdf.Page, overlays: list[Overlay]) -> None:
    redactions = [o for o in overlays if isinstance(o, BoxOverlay) and o.shape == "redact"]
    for ov in redactions:
        page.add_redact_annot(_page_rect(ov), fill=hex_rgb(ov.fill or "#000000"))
    if redactions:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
    for ov in overlays:
        if ov in redactions:
            continue
        DRAWERS[ov.kind](page, ov)


def _remap_toc(model: DocumentModel) -> list:
    if not model.toc or not model.toc_source:
        return []
    new_pos: dict[int, int] = {}
    for pos, ref in enumerate(model.pages):
        if ref.src == model.toc_source:
            new_pos.setdefault(ref.index, pos + 1)
    out, last_level = [], 0
    for entry in model.toc:
        level, title, page = entry[0], entry[1], entry[2]
        if page - 1 not in new_pos:
            continue
        level = min(level, last_level + 1)
        out.append([level, title, new_pos[page - 1]])
        last_level = level
    return out


def build_document(model: DocumentModel, pages: list[int] | None = None) -> pymupdf.Document:
    """Assemble the final PDF in memory (optionally only some pages)."""
    out = pymupdf.open()
    refs = [model.pages[i] for i in pages] if pages is not None else model.pages
    i = 0
    while i < len(refs):
        # Copy runs of consecutive source pages in one go.
        j = i
        while j + 1 < len(refs) and refs[j + 1].src == refs[i].src and refs[j + 1].index == refs[j].index + 1:
            j += 1
        out.insert_pdf(model.sources[refs[i].src].doc, from_page=refs[i].index, to_page=refs[j].index)
        i = j + 1
    for page, ref in zip(out, refs, strict=True):
        page.set_rotation(ref.rotation)
        if ref.overlays:
            burn_overlays(page, ref.overlays)
    if pages is None:
        toc = _remap_toc(model)
        if toc:
            out.set_toc(toc)
    meta = {k: v for k, v in model.metadata.items() if v}
    meta.setdefault("producer", "Folio (PyMuPDF)")
    out.set_metadata(meta)
    return out


SAVE_OPTS = dict(garbage=3, deflate=True, use_objstms=1)


def document_bytes(model: DocumentModel, pages: list[int] | None = None) -> bytes:
    doc = build_document(model, pages)
    try:
        return doc.tobytes(**SAVE_OPTS)
    finally:
        doc.close()


def _encryption_args(sec: Security | None) -> dict:
    if not sec or not (sec.user_password or sec.owner_password):
        return {}
    perm = pymupdf.PDF_PERM_ACCESSIBILITY
    if sec.allow_print:
        perm |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if sec.allow_copy:
        perm |= pymupdf.PDF_PERM_COPY
    if sec.allow_modify:
        perm |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_ANNOTATE | pymupdf.PDF_PERM_FORM | pymupdf.PDF_PERM_ASSEMBLE
    return dict(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw=sec.user_password,
        owner_pw=sec.owner_password or sec.user_password,
        permissions=perm,
    )


def write_pdf(data: bytes, path: str | Path, security: Security | None = None) -> None:
    """Atomically write PDF bytes to ``path``, encrypting them if requested."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".folio-", suffix=".pdf", dir=path.parent)
    os.close(fd)
    try:
        enc = _encryption_args(security)
        if enc:
            doc = pymupdf.open(stream=data, filetype="pdf")
            doc.save(tmp, **SAVE_OPTS, **enc)
            doc.close()
        else:
            Path(tmp).write_bytes(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ------------------------------------------------------------------ compression
@dataclass(frozen=True)
class CompressOptions:
    images: bool = True
    dpi_threshold: int = 150
    dpi_target: int = 120
    quality: int = 70
    grayscale: bool = False
    subset_fonts: bool = True
    strip_metadata: bool = False


PRESETS = {
    "light": CompressOptions(dpi_threshold=225, dpi_target=200, quality=85),
    "medium": CompressOptions(dpi_threshold=165, dpi_target=150, quality=72),
    "strong": CompressOptions(dpi_threshold=110, dpi_target=96, quality=55),
}


def compress_bytes(data: bytes, opts: CompressOptions) -> bytes:
    """CPU heavy: meant to run in a worker process."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        if opts.images:
            doc.rewrite_images(
                dpi_threshold=opts.dpi_threshold,
                dpi_target=opts.dpi_target,
                quality=opts.quality,
                set_to_gray=opts.grayscale,
            )
        if opts.subset_fonts:
            try:
                doc.subset_fonts()
            except Exception:
                pass  # Subsetting is best effort; some exotic fonts refuse it.
        doc.scrub(
            attached_files=False,
            clean_pages=False,
            embedded_files=False,
            hidden_text=False,
            javascript=False,
            metadata=opts.strip_metadata,
            redactions=False,
            remove_links=False,
            reset_fields=False,
            reset_responses=False,
            thumbnails=True,
            xml_metadata=opts.strip_metadata,
        )
        result = doc.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
    finally:
        doc.close()
    return result if len(result) < len(data) else data
