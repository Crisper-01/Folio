"""Font registry shared by the Qt preview and the PDF baking code.

Both sides load the exact same font files so that what the user sees on
screen matches what is written into the PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pymupdf
import pymupdf_fonts

from .paths import asset_path


@dataclass(frozen=True)
class FontFamily:
    key: str
    label: str
    # face name -> source ("pmf:<name>" for pymupdf-fonts, else a file in assets/fonts)
    faces: dict[str, str]
    script: bool = False

    @property
    def has_bold(self) -> bool:
        return "bold" in self.faces

    @property
    def has_italic(self) -> bool:
        return "italic" in self.faces


def _script(key: str, label: str, file: str) -> FontFamily:
    return FontFamily(key, label, {"regular": file}, script=True)


FAMILIES: dict[str, FontFamily] = {
    f.key: f
    for f in [
        FontFamily(
            "sans",
            "Sans (FiraGO)",
            {"regular": "pmf:figo", "bold": "pmf:figbo", "italic": "pmf:figit", "bolditalic": "pmf:figbi"},
        ),
        FontFamily(
            "serif",
            "Serif (Crimson)",
            {
                "regular": "CrimsonText-Regular.ttf",
                "bold": "CrimsonText-Bold.ttf",
                "italic": "CrimsonText-Italic.ttf",
                "bolditalic": "CrimsonText-BoldItalic.ttf",
            },
        ),
        FontFamily(
            "mono",
            "Mono (Cascadia)",
            {"regular": "pmf:cascadia", "bold": "pmf:cascadiab", "italic": "pmf:cascadiai", "bolditalic": "pmf:cascadiabi"},
        ),
        _script("greatvibes", "Great Vibes", "GreatVibes-Regular.ttf"),
        _script("allura", "Allura", "Allura-Regular.ttf"),
        _script("alexbrush", "Alex Brush", "AlexBrush-Regular.ttf"),
        _script("pinyon", "Pinyon Script", "PinyonScript-Regular.ttf"),
        _script("parisienne", "Parisienne", "Parisienne-Regular.ttf"),
        _script("sacramento", "Sacramento", "Sacramento-Regular.ttf"),
        _script("mrdafoe", "Mr Dafoe", "MrDafoe-Regular.ttf"),
        _script("herrvon", "Herr Von Muellerhoff", "HerrVonMuellerhoff-Regular.ttf"),
        _script("homemade", "Homemade Apple", "HomemadeApple-Regular.ttf"),
    ]
}

SCRIPT_FAMILIES = [f for f in FAMILIES.values() if f.script]


def face_name(bold: bool, italic: bool) -> str:
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


def resolve_face(family: str, bold: bool = False, italic: bool = False) -> tuple[str, str]:
    """Return (family_key, face) falling back gracefully when a face is missing."""
    fam = FAMILIES.get(family) or FAMILIES["sans"]
    face = face_name(bold, italic)
    if face not in fam.faces:
        face = "bold" if bold and "bold" in fam.faces else "italic" if italic and "italic" in fam.faces else "regular"
    return fam.key, face


@cache
def font_bytes(family: str, face: str) -> bytes:
    src = FAMILIES[family].faces[face]
    if src.startswith("pmf:"):
        return pymupdf_fonts.myfont(src[4:])
    return Path(asset_path("fonts", src)).read_bytes()


@cache
def fitz_font(family: str, face: str) -> pymupdf.Font:
    return pymupdf.Font(fontbuffer=font_bytes(family, face))


@dataclass(frozen=True)
class TextLayout:
    lines: list[str]
    widths: list[float]
    ascender: float  # in points for the given size
    line_height: float
    width: float
    height: float

    def baseline(self, i: int) -> float:
        return self.ascender + i * self.line_height

    def line_x(self, i: int, align: str) -> float:
        if align == "center":
            return (self.width - self.widths[i]) / 2
        if align == "right":
            return self.width - self.widths[i]
        return 0.0


def layout_text(text: str, family: str, bold: bool, italic: bool, size: float, spacing: float = 1.2) -> TextLayout:
    fam, face = resolve_face(family, bold, italic)
    font = fitz_font(fam, face)
    lines = text.split("\n") or [""]
    widths = [font.text_length(line, fontsize=size) for line in lines]
    asc = font.ascender * size
    desc = font.descender * size  # negative
    lh = size * spacing
    width = max(widths + [size * 0.5])
    height = (len(lines) - 1) * lh + (asc - desc)
    return TextLayout(lines, widths, asc, lh, width, height)
