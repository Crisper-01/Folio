"""Locate bundled assets both from source and from a PyInstaller build."""

from __future__ import annotations

import sys
from pathlib import Path


def _root() -> Path:
    frozen = getattr(sys, "_MEIPASS", None)
    if frozen:
        return Path(frozen) / "folio"
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> str:
    return str(_root().joinpath("assets", *parts))
