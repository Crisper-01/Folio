from folio.ui.dialogs.compress import CompressDialog
from folio.ui.dialogs.images_to_pdf import ImagesToPdfDialog
from folio.ui.dialogs.signature import SignatureDialog
from folio.ui.dialogs.tools import PageNumbersDialog, SecurityDialog
from folio.ui.dialogs.watermark import WatermarkDialog


def grab_dialog(d, name, wait=500):
    d.show()
    pump(wait)
    d.grab().save(str(out / f"{name}.png"))
    print("dialog", name, d.size().toTuple())


d = SignatureDialog(w)
d.tabs.setCurrentIndex(d.tabs.indexOf(d.pad.parentWidget()))
d.show()
pump(200)
pad = d.pad
pts = [(40 + i * 6, 120 + 30 * __import__("math").sin(i / 3)) for i in range(70)]
from PySide6.QtCore import QPoint

QTest.mousePress(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*map(int, pts[0])))
for x, y in pts[1:]:
    QTest.mouseMove(pad, QPoint(int(x), int(y)))
QTest.mouseRelease(pad, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(*map(int, pts[-1])))
grab_dialog(d, "10-signature-draw")
d.tabs.setCurrentIndex(d.tabs.indexOf(d.font_list.parentWidget()))
d.name.setText("Jordan Bankole")
grab_dialog(d, "11-signature-type")
d.close()

d = WatermarkDialog(w.model, 0, w)
grab_dialog(d, "12-watermark")
d.form.layout_seg.set_value("tile")
d.form.layout_seg.changed.emit("tile")
grab_dialog(d, "13-watermark-tile")
d.close()

d = CompressDialog(w.model, w)
grab_dialog(d, "14-compress", 6000)
d.close()

d = PageNumbersDialog(w.model, w)
grab_dialog(d, "15-pagenum")
d.close()
d = SecurityDialog(w.model, w)
grab_dialog(d, "16-security")
d.close()

import pymupdf

img = out / "photo.png"
pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 800, 600), False)
for y in range(0, 600, 20):
    pix.set_rect(pymupdf.IRect(0, y, 800, y + 20), (30 + y // 4, 120, 200 - y // 4))
pix.save(str(img))
d = ImagesToPdfDialog([str(img), str(img)], w)
d.wm_group.setChecked(True)
grab_dialog(d, "17-img2pdf", 800)
d.close()
