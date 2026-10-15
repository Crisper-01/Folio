"""`folio --selftest`: check a packaged build end to end without a display.

Exercises the bundled fonts, overlay rendering, PDF baking and the
compression worker process, then prints OK (exit code 0) or the error.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def run() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    from .export import PRESETS, compress_bytes, document_bytes, write_pdf
    from .fonts import FAMILIES, font_bytes
    from .model import DocumentModel
    from .overlays import InkOverlay, TextOverlay
    from .stamps import WatermarkOptions, apply_watermark
    from .ui import theme, worker
    from .ui.paint import paint_overlay

    app = QApplication.instance() or QApplication(["folio"])
    theme.install("light")
    try:
        for fam in FAMILIES.values():
            for face in fam.faces:
                assert font_bytes(fam.key, face), f"missing font {fam.key}/{face}"
        model = DocumentModel.empty()
        model.insert_blank(0)
        model.add_overlays(0, [TextOverlay(x=50, y=50, text="Signé à Noël", family="greatvibes", size_pt=30)])
        model.add_overlays(0, [InkOverlay.from_points([[(50, 150), (90, 170), (130, 150)]])])
        apply_watermark(model, WatermarkOptions(text="TEST"))
        img = QImage(200, 100, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        for ov in model.pages[0].overlays:
            paint_overlay(painter, ov)
        painter.end()
        data = document_bytes(model)
        out = Path(tempfile.gettempdir()) / "folio-selftest.pdf"
        write_pdf(data, out)
        import pymupdf

        assert "Signé à Noël" in pymupdf.open(out)[0].get_text()
        result: dict = {}
        job = worker.Job(
            compress_bytes,
            data,
            PRESETS["medium"],
            on_done=lambda r: (result.setdefault("ok", r), app.quit()),
            on_error=lambda e: (result.setdefault("err", e), app.quit()),
        )
        app.exec()
        del job
        worker.shutdown()
        if "err" in result:
            raise result["err"]
        assert pymupdf.open(stream=result["ok"]).page_count == 1
        out.unlink(missing_ok=True)
    except BaseException as e:  # report anything, this is a diagnostic
        print(f"FAIL: {e!r}", file=sys.stderr)
        return 1
    print("OK")
    return 0
