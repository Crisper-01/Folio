"""Rasterise assets/folio.svg into the PNG/ICO files used by the app and builds."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "folio" / "assets"


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(ASSETS / "folio.svg")).render(p)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication([])
    render(256).save(str(ASSETS / "folio.png"))
    render(256).save(str(ASSETS / "folio.ico"))
    print("ok")
