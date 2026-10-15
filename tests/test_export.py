import pymupdf
import pytest

from folio.export import PRESETS, build_document, compress_bytes, document_bytes, write_pdf
from folio.model import DocumentModel, PasswordRequired, Security
from folio.overlays import BoxOverlay, ImageOverlay, InkOverlay, LineOverlay, TextOverlay


def make_pdf(path, pages=3, size=(300, 400)):
    doc = pymupdf.open()
    for i in range(pages):
        p = doc.new_page(width=size[0], height=size[1])
        p.insert_text((40, 60), f"Page {i + 1}", fontsize=20)
    doc.set_toc([[1, "Un", 1], [2, "Deux", 2], [1, "Trois", 3]])
    doc.save(path)
    return path


@pytest.fixture
def pdf(tmp_path):
    return make_pdf(tmp_path / "in.pdf")


def texts(doc):
    return [p.get_text().strip() for p in doc]


def test_page_operations_and_undo(pdf):
    m = DocumentModel.from_file(pdf)
    assert m.page_count() == 3 and not m.dirty
    m.move_pages([2], 0)
    m.rotate_pages([0], 90)
    m.duplicate_pages([1])
    m.delete_pages([3])
    out = build_document(m)
    assert texts(out) == ["Page 3", "Page 1", "Page 1"]
    assert out[0].rotation == 90
    assert m.dirty
    for _ in range(4):
        m.undo()
    assert not m.dirty
    assert texts(build_document(m)) == ["Page 1", "Page 2", "Page 3"]
    m.redo()
    assert texts(build_document(m))[0] == "Page 3"


def test_toc_is_remapped(pdf):
    m = DocumentModel.from_file(pdf)
    m.move_pages([2], 0)
    m.delete_pages([2])  # drops original page 2 ("Deux")
    toc = build_document(m).get_toc()
    assert toc == [[1, "Un", 2], [1, "Trois", 1]]


def test_text_on_rotated_page_is_upright(pdf):
    m = DocumentModel.from_file(pdf)
    m.rotate_pages([0], 90)
    # The UI counter-rotates overlays so they look upright on a rotated page.
    m.add_overlays(0, [TextOverlay(x=100, y=200, rotation=-90, text="Bonjour é")])
    page = build_document(m)[0]
    lines = [ln for b in page.get_text("dict")["blocks"] for ln in b.get("lines", []) if "Bonjour" in ln["spans"][0]["text"]]
    assert lines, "text not written"
    dx, dy = lines[0]["dir"]
    # In display space the direction must be left-to-right.
    vec = pymupdf.Point(dx, dy) * pymupdf.Matrix(
        page.rotation_matrix.a, page.rotation_matrix.b, page.rotation_matrix.c, page.rotation_matrix.d, 0, 0
    )
    assert vec.x == pytest.approx(1, abs=1e-3) and vec.y == pytest.approx(0, abs=1e-3)
    assert "Bonjour é" in page.get_text()


def two_tone_png():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 10), False)
    pix.set_rect(pymupdf.IRect(0, 0, 10, 10), (255, 0, 0))
    pix.set_rect(pymupdf.IRect(10, 0, 20, 10), (0, 0, 255))
    return pix.tobytes("png")


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_image_orientation_matches_display(pdf, rot):
    m = DocumentModel.from_file(pdf)
    m.rotate_pages([0], rot)
    # 80x40 image whose local frame is counter-rotated, i.e. upright on screen.
    import math

    # Choose the origin so the image lands inside the page whatever the rotation.
    w, h = m.unrotated_size(m.pages[0])
    cx, cy = w / 2, h / 2
    ov = ImageOverlay(w=80, h=40, data=two_tone_png(), rotation=-rot)
    # place local centre (40, 20) at page centre
    a = math.radians(-rot)
    ov.x = cx - (40 * math.cos(a) - 20 * math.sin(a))
    ov.y = cy - (40 * math.sin(a) + 20 * math.cos(a))
    m.add_overlays(0, [ov])
    page = build_document(m)[0]
    pix = page.get_pixmap()
    W, H = pix.width, pix.height
    left = pix.pixel(int(W / 2 - 20), int(H / 2))
    right = pix.pixel(int(W / 2 + 20), int(H / 2))
    assert left[0] > 200 and left[2] < 60, (rot, left)
    assert right[2] > 200 and right[0] < 60, (rot, right)


def test_all_overlay_kinds_render(pdf):
    m = DocumentModel.from_file(pdf)
    m.add_overlays(
        0,
        [
            BoxOverlay(x=10, y=10, w=50, h=30, fill="#ff0000"),
            BoxOverlay(shape="ellipse", x=70, y=10, w=50, h=30),
            BoxOverlay(shape="highlight", x=40, y=40, w=80, h=25, fill="#ffe14d", stroke=None, fill_opacity=0.4),
            LineOverlay(shape="arrow", x=10, y=100, dx=100, dy=40),
            InkOverlay.from_points([[(10, 200), (20, 210), (40, 205), (60, 220)]]),
            TextOverlay(x=10, y=300, text="Signé", family="greatvibes", size_pt=30),
        ],
    )
    page = build_document(m)[0]
    assert len(list(page.annots())) == 1
    assert len(page.get_drawings()) >= 4
    assert "Signé" in page.get_text()


def test_redaction_removes_text(pdf):
    m = DocumentModel.from_file(pdf)
    m.add_overlays(0, [BoxOverlay(shape="redact", x=30, y=30, w=200, h=50, fill="#000000", stroke=None)])
    page = build_document(m)[0]
    assert "Page 1" not in page.get_text()


def test_save_encrypted_and_reopen(pdf, tmp_path):
    m = DocumentModel.from_file(pdf)
    m.set_security(Security(user_password="secret", owner_password="owner"))
    out = tmp_path / "enc.pdf"
    write_pdf(document_bytes(m), out, m.security)
    with pytest.raises(PasswordRequired):
        DocumentModel.from_file(out)
    m2 = DocumentModel.from_file(out, password="secret")
    assert m2.page_count() == 3


def test_compression_shrinks_images(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    big = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 2400, 3200), False)
    import random

    random.seed(1)
    for y in range(0, 3200, 40):
        for x in range(0, 2400, 40):
            big.set_rect(pymupdf.IRect(x, y, x + 40, y + 40), (random.randrange(256), random.randrange(256), 120))
    page.insert_image(page.rect, stream=big.tobytes("png"))
    data = doc.tobytes()
    small = compress_bytes(data, PRESETS["medium"])
    assert len(small) < len(data) * 0.5
    assert pymupdf.open(stream=small).page_count == 1


def test_insert_image_as_page(pdf, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(two_tone_png())
    m = DocumentModel.from_file(pdf)
    m.insert_file(img, 1)
    out = build_document(m)
    assert out.page_count == 4
    assert out[1].rect.width > out[1].rect.height  # landscape image -> landscape page


def test_rotated_box_lands_where_the_screen_shows_it(pdf):
    m = DocumentModel.from_file(pdf)
    # Qt convention: +90 is clockwise in y-down space, so (50x10) at (100,100)
    # covers x in [90, 100] and y in [100, 150].
    m.add_overlays(0, [BoxOverlay(x=100, y=100, w=50, h=10, rotation=90, fill="#ff0000", stroke=None)])
    rect = build_document(m)[0].get_drawings()[0]["rect"]
    assert (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1)) == (90, 100, 100, 150)
