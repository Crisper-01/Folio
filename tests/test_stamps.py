import pymupdf
import pytest

from folio.export import build_document
from folio.model import DocumentModel
from folio.stamps import (
    PAGENUM,
    WATERMARK,
    ImagesToPdfOptions,
    PageNumberOptions,
    WatermarkOptions,
    apply_page_numbers,
    apply_watermark,
    has_group,
    images_to_model,
)
from tests.test_export import make_pdf, two_tone_png


@pytest.fixture
def model(tmp_path):
    return DocumentModel.from_file(make_pdf(tmp_path / "in.pdf", pages=2))


def word_center(page, word):
    for w in page.get_text("words"):
        if w[4] == word:
            r = pymupdf.Rect(w[:4]) * page.rotation_matrix
            return (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    raise AssertionError(f"{word} not found")


@pytest.mark.parametrize("rot", [0, 90, 270])
def test_watermark_is_centered_and_replaceable(model, rot):
    model.rotate_pages([0, 1], rot)
    apply_watermark(model, WatermarkOptions(text="BROUILLON", angle=0))
    apply_watermark(model, WatermarkOptions(text="FINAL", angle=0))
    doc = build_document(model)
    page = doc[0]
    assert "BROUILLON" not in page.get_text()
    cx, cy = word_center(page, "FINAL")
    assert cx == pytest.approx(page.rect.width / 2, abs=3)
    assert cy == pytest.approx(page.rect.height / 2, abs=6)
    model.undo()
    assert "BROUILLON" in build_document(model)[0].get_text()


def test_tiled_watermark_and_page_subset(model):
    apply_watermark(model, WatermarkOptions(text="COPIE", tiled=True, pages=[1]))
    assert not [o for o in model.pages[0].overlays if o.group == WATERMARK]
    assert len(model.pages[1].overlays) > 3


def test_page_numbers(model):
    apply_page_numbers(model, PageNumberOptions(template="Page {n} sur {total}"))
    assert has_group(model, PAGENUM)
    assert "Page 2 sur 2" in build_document(model)[1].get_text()


def test_images_to_pdf_with_watermark():
    opts = ImagesToPdfOptions(
        images=[two_tone_png(), two_tone_png()], page_size="image", margin=10, watermark=WatermarkOptions(text="ORIGINAL")
    )
    m = images_to_model(opts)
    assert m.dirty and not m.can_undo()
    doc = build_document(m)
    assert doc.page_count == 2
    assert doc[0].rect.width == pytest.approx(20 * 72 / 96 + 20, abs=0.5)
    assert "ORIGINAL" in doc[1].get_text()
