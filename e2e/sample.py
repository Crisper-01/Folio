"""Generate a realistic multi-page sample PDF for manual and E2E testing."""

import random
import sys

import pymupdf

LOREM = (
    "Le présent contrat a pour objet de définir les conditions dans lesquelles le prestataire "
    "s'engage à réaliser les missions décrites ci-après. Les parties conviennent que toute "
    "modification devra faire l'objet d'un avenant écrit et signé. "
)


def make(path: str, pages: int = 4) -> None:
    doc = pymupdf.open()
    random.seed(3)
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((60, 70), f"Contrat de prestation - page {i + 1}", fontsize=18, fontname="hebo")
        page.insert_textbox(pymupdf.Rect(60, 95, 535, 400), LOREM * 4, fontsize=11, fontname="helv")
        if i == 0:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1200, 700), False)
            for y in range(0, 700, 25):
                for x in range(0, 1200, 25):
                    pix.set_rect(pymupdf.IRect(x, y, x + 25, y + 25), (60 + x // 8 % 190, 90 + y // 6 % 160, 200))
            page.insert_image(pymupdf.Rect(60, 420, 535, 697), stream=pix.tobytes("png"))
        page.insert_text((60, 790), "Signature du client :", fontsize=11, fontname="helv")
    doc.set_toc([[1, f"Page {i + 1}", i + 1] for i in range(pages)])
    doc.save(path)


if __name__ == "__main__":
    make(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4)
