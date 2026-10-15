from folio.overlays import TextOverlay
from folio.stamps import PageNumberOptions, WatermarkOptions, apply_page_numbers, apply_watermark
from folio.ui.page_view import Tool

# rotate page 1 to landscape, then write on it
w.thumbs.setCurrentRow(0)
w.rotate_pages(90)
pump(500)
w.view.go_to_page(0)
pump(300)
w.view.set_tool(Tool.TEXT)
QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, page_point(0, 120, 120))
pump()
type_text("Texte droit sur page pivotée")
QTest.keyClick(w.view.viewport(), Qt.Key.Key_Escape)
pump()
# place a typed signature
sig = TextOverlay(text="Jordan Bankole", family="greatvibes", size_pt=34, color="#0b1f66")
w.view.begin_place(sig)
QTest.mouseMove(w.view.viewport(), page_point(0, 600, 300))
pump(200)
shot("20-placing-signature")
QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, page_point(0, 600, 300))
pump()
apply_watermark(w.model, WatermarkOptions(text="COPIE"))
apply_page_numbers(w.model, PageNumberOptions())
pump(500)
shot("21-rotated-annotated")
# drag page 4 thumbnail to the top
src = w.thumbs.visualItemRect(w.thumbs.item(3)).center()
print("order before", [w.model.pages[i].index for i in range(4)])
w.model_reorder([w.model.pages[i].uid for i in (3, 0, 1, 2)])
pump(400)
print("order after", [w.model.pages[i].index for i in range(4)])
shot("22-reordered")
w.undo()
pump(300)
print("order after undo", [w.model.pages[i].index for i in range(4)])
saved = out / "pages.pdf"
w._save_to(saved)
import pymupdf

d = pymupdf.open(saved)
print("pages", d.page_count, "rot", d[0].rotation, "text0:", d[0].get_text()[:0])
d[0].get_pixmap(dpi=70).save(str(out / "23-saved-rotated.png"))
