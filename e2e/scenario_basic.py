from folio.ui.page_view import Tool

w.view.set_tool(Tool.TEXT)
QTest.mouseClick(w.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, page_point(0, 320, 470))
pump()
type_text("Test d'écriture à Noël")
shot("02-typing")
QTest.keyClick(w.view.viewport(), Qt.Key.Key_Escape)
shot("03-text-done")
w.view.set_tool(Tool.RECT)
drag(page_point(0, 60, 330), page_point(0, 260, 400))
shot("04-rect")
w.view.set_tool(Tool.PEN)
drag(page_point(0, 330, 360), page_point(0, 480, 330))
w.view.set_tool(Tool.ARROW)
drag(page_point(0, 300, 380), page_point(0, 420, 440))
w.view.set_tool(Tool.HIGHLIGHT)
drag(page_point(0, 315, 100), page_point(0, 520, 118))
w.view.set_tool(Tool.SELECT)
shot("05-shapes")
print("overlays:", [(o.kind, getattr(o, "text", "")) for o in w.model.pages[0].overlays])
saved = out / "saved.pdf"
w._save_to(saved)
import pymupdf

d = pymupdf.open(saved)
d[0].get_pixmap(dpi=100).save(str(out / "06-saved-page1.png"))
print("saved size", saved.stat().st_size, "title:", w.windowTitle())
print("text in pdf:", "Noël" in d[0].get_text())
