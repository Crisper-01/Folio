"""Document model: an ordered list of page references plus their overlays.

Source PDFs are kept untouched in memory. Page operations only reshuffle
lightweight ``PageRef`` objects, which makes every operation cheap and
trivially undoable. The final PDF is produced by ``export.build_document``.
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .overlays import Overlay, new_uid

A4 = (595.276, 841.89)

_state_ids = itertools.count(1)


class PasswordRequired(Exception):
    pass


@dataclass
class Source:
    id: str
    doc: pymupdf.Document
    name: str


@dataclass
class PageRef:
    src: str
    index: int
    rotation: int = 0
    overlays: list[Overlay] = field(default_factory=list)
    uid: str = field(default_factory=new_uid)


@dataclass
class Security:
    user_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = True


def open_pdf_bytes(data: bytes, password: str | None = None, filetype: str = "pdf") -> pymupdf.Document:
    doc = pymupdf.open(stream=data, filetype=filetype)
    if doc.needs_pass:
        if not password or not doc.authenticate(password):
            doc.close()
            raise PasswordRequired()
    if not doc.is_pdf:
        pdf = pymupdf.open("pdf", doc.convert_to_pdf())
        doc.close()
        doc = pdf
    return doc


LETTER = (612.0, 792.0)


def image_page_doc(
    image_bytes: bytes, page_size: tuple[float, float] | None = A4, margin: float = 0.0, doc: pymupdf.Document | None = None
) -> pymupdf.Document:
    """Add a page holding the image, fitted on a page of matching orientation.

    ``page_size=None`` makes the page exactly the size of the image (at its
    own resolution, 96 dpi when unknown).
    """
    pix = pymupdf.Pixmap(image_bytes)
    iw, ih = pix.width, pix.height
    if page_size is None:
        dpi = pix.xres if pix.xres and pix.xres > 1 else 96
        pw, ph = iw * 72 / dpi + 2 * margin, ih * 72 / dpi + 2 * margin
    else:
        pw, ph = page_size if ih >= iw else (page_size[1], page_size[0])
    doc = doc if doc is not None else pymupdf.open()
    page = doc.new_page(width=pw, height=ph)
    scale = min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih)
    w, h = iw * scale, ih * scale
    rect = pymupdf.Rect((pw - w) / 2, (ph - h) / 2, (pw + w) / 2, (ph + h) / 2)
    page.insert_image(rect, stream=image_bytes)
    return doc


class DocumentModel:
    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.pages: list[PageRef] = []
        self.path: Path | None = None
        self.metadata: dict[str, str] = {}
        self.security: Security | None = None
        self.toc: list = []
        self.toc_source: str | None = None
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self._state = next(_state_ids)
        self._saved_state = self._state
        self._listeners: list[Callable[[str], None]] = []
        self._merge: str | None = None

    # ------------------------------------------------------------------ events
    def subscribe(self, fn: Callable[[str], None]) -> None:
        self._listeners.append(fn)

    def notify(self, what: str) -> None:
        """what: "pages" (structure changed), "overlays", "meta" or "saved"."""
        for fn in list(self._listeners):
            fn(what)

    # ------------------------------------------------------------- creation
    @classmethod
    def from_file(cls, path: str | Path, password: str | None = None) -> DocumentModel:
        path = Path(path)
        model = cls()
        data = path.read_bytes()
        doc = open_pdf_bytes(data, password, filetype=path.suffix.lstrip(".").lower() or "pdf")
        src = model._add_source(doc, path.name)
        model.pages = [PageRef(src.id, i, doc[i].rotation) for i in range(doc.page_count)]
        model.path = path if path.suffix.lower() == ".pdf" else None
        meta = doc.metadata or {}
        model.metadata = {k: meta.get(k) or "" for k in ("title", "author", "subject", "keywords", "creator", "producer")}
        model.toc = doc.get_toc(simple=False)
        model.toc_source = src.id
        if password:
            model.security = Security(user_password=password, owner_password=password)
        return model

    @classmethod
    def empty(cls) -> DocumentModel:
        return cls()

    def _add_source(self, doc: pymupdf.Document, name: str) -> Source:
        src = Source(new_uid(), doc, name)
        self.sources[src.id] = src
        return src

    # ---------------------------------------------------------------- state
    @property
    def dirty(self) -> bool:
        return self._state != self._saved_state

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Sans titre"

    def mark_saved(self, path: Path) -> None:
        self.path = path
        self._saved_state = self._state
        self._merge = None
        self.notify("saved")

    def _snapshot(self) -> tuple:
        return (copy.deepcopy(self.pages), dict(self.metadata), copy.deepcopy(self.security), self._state)

    def checkpoint(self, merge: str | None = None) -> None:
        """Call before every mutation so it can be undone.

        Consecutive checkpoints with the same ``merge`` key (e.g. dragging a
        slider) collapse into a single undo step.
        """
        if merge is not None and merge == self._merge and self._undo:
            self._state = next(_state_ids)
            return
        self._merge = merge
        self._undo.append(self._snapshot())
        if len(self._undo) > 200:
            self._undo.pop(0)
        self._redo.clear()
        self._state = next(_state_ids)

    def clear_history(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def discard_checkpoint(self) -> None:
        """Roll back to the last checkpoint without making it redoable."""
        if self._undo:
            self._restore(self._undo.pop())

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def _restore(self, snap: tuple) -> None:
        self._merge = None
        self.pages, self.metadata, self.security, self._state = snap
        self.notify("pages")

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self._snapshot())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self._snapshot())
            self._restore(self._redo.pop())

    # -------------------------------------------------------------- queries
    def page_count(self) -> int:
        return len(self.pages)

    def fitz_page(self, ref: PageRef) -> pymupdf.Page:
        page = self.sources[ref.src].doc[ref.index]
        if page.rotation != ref.rotation:
            page.set_rotation(ref.rotation)
        return page

    def unrotated_size(self, ref: PageRef) -> tuple[float, float]:
        box = self.sources[ref.src].doc[ref.index].cropbox
        return box.width, box.height

    def display_size(self, ref: PageRef) -> tuple[float, float]:
        w, h = self.unrotated_size(ref)
        return (h, w) if ref.rotation % 180 else (w, h)

    def index_of(self, uid: str) -> int:
        for i, ref in enumerate(self.pages):
            if ref.uid == uid:
                return i
        return -1

    def find_overlay(self, uid: str) -> tuple[PageRef, Overlay] | None:
        for ref in self.pages:
            for ov in ref.overlays:
                if ov.uid == uid:
                    return ref, ov
        return None

    # ------------------------------------------------------- page operations
    def insert_document(self, doc: pymupdf.Document, name: str, at: int, pages: Iterable[int] | None = None) -> int:
        src = self._add_source(doc, name)
        idx = list(pages) if pages is not None else list(range(doc.page_count))
        refs = [PageRef(src.id, i, doc[i].rotation) for i in idx]
        self.checkpoint()
        self.pages[at:at] = refs
        if not self.toc_source and doc.get_toc():
            self.toc, self.toc_source = doc.get_toc(simple=False), src.id
        self.notify("pages")
        return len(refs)

    def insert_file(self, path: str | Path, at: int, password: str | None = None) -> int:
        path = Path(path)
        data = path.read_bytes()
        ext = path.suffix.lower().lstrip(".")
        if ext == "pdf":
            doc = open_pdf_bytes(data, password)
        else:
            doc = image_page_doc(data)
        return self.insert_document(doc, path.name, at)

    def insert_blank(self, at: int, size: tuple[float, float] | None = None) -> None:
        if size is None:
            ref = self.pages[min(max(at - 1, 0), len(self.pages) - 1)] if self.pages else None
            size = self.display_size(ref) if ref else A4
        doc = pymupdf.open()
        doc.new_page(width=size[0], height=size[1])
        self.insert_document(doc, "Page vierge", at)

    def delete_pages(self, indices: Iterable[int]) -> None:
        drop = set(indices)
        if not drop:
            return
        self.checkpoint()
        self.pages = [p for i, p in enumerate(self.pages) if i not in drop]
        self.notify("pages")

    def duplicate_pages(self, indices: Iterable[int]) -> None:
        idx = sorted(set(indices))
        if not idx:
            return
        self.checkpoint()
        copies = []
        for i in idx:
            dup = copy.deepcopy(self.pages[i])
            dup.uid = new_uid()
            for ov in dup.overlays:
                ov.uid = new_uid()
            copies.append(dup)
        self.pages[idx[-1] + 1 : idx[-1] + 1] = copies
        self.notify("pages")

    def rotate_pages(self, indices: Iterable[int], delta: int) -> None:
        idx = sorted(set(indices))
        if not idx:
            return
        self.checkpoint()
        for i in idx:
            self.pages[i].rotation = (self.pages[i].rotation + delta) % 360
        self.notify("pages")

    def move_pages(self, indices: Iterable[int], to: int) -> None:
        """Move the given pages so the first of them lands at position ``to``
        (index computed in the list *without* the moved pages)."""
        idx = sorted(set(indices))
        if not idx:
            return
        moving = [self.pages[i] for i in idx]
        rest = [p for i, p in enumerate(self.pages) if i not in set(idx)]
        to = max(0, min(to, len(rest)))
        new = rest[:to] + moving + rest[to:]
        if [p.uid for p in new] == [p.uid for p in self.pages]:
            return
        self.checkpoint()
        self.pages = new
        self.notify("pages")

    def reorder(self, uids: list[str]) -> None:
        by_uid = {p.uid: p for p in self.pages}
        new = [by_uid[u] for u in uids if u in by_uid]
        if len(new) != len(self.pages) or [p.uid for p in new] == [p.uid for p in self.pages]:
            return
        self.checkpoint()
        self.pages = new
        self.notify("pages")

    # ---------------------------------------------------- overlay operations
    def add_overlays(self, page_index: int, overlays: list[Overlay]) -> None:
        self.checkpoint()
        self.pages[page_index].overlays.extend(overlays)
        self.notify("overlays")

    def remove_overlays(self, uids: Iterable[str]) -> None:
        drop = set(uids)
        if not drop:
            return
        self.checkpoint()
        for ref in self.pages:
            ref.overlays = [o for o in ref.overlays if o.uid not in drop]
        self.notify("overlays")

    def edit_overlays(self, uids: Iterable[str], fn: Callable[[Overlay], None], merge: str | None = None) -> None:
        targets = [f[1] for u in uids if (f := self.find_overlay(u))]
        if not targets:
            return
        self.checkpoint(merge)
        for ov in targets:
            fn(ov)
        self.notify("overlays")

    def set_metadata(self, meta: dict[str, str]) -> None:
        self.checkpoint()
        self.metadata.update(meta)
        self.notify("meta")

    def set_security(self, security: Security | None) -> None:
        self.checkpoint()
        self.security = security
        self.notify("meta")
