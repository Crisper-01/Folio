"""Application entry point."""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    argv = list(sys.argv if argv is None else argv)
    if "--selftest" in argv:
        from .selftest import run

        return run()

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication

    from . import __version__
    from .paths import asset_path
    from .ui import theme, worker
    from .ui.main_window import MainWindow

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Folio")
    app.setOrganizationName("Folio")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("folio")
    app.setWindowIcon(QIcon(asset_path("folio.png")))
    from PySide6.QtCore import QSettings

    theme.install(QSettings("Folio", "Folio").value("theme", "system"))

    files = [a for a in argv[1:] if not a.startswith("-") and Path(a).exists()]
    window = MainWindow()
    window.show()
    for f in files:
        window.open_path(f)
    code = app.exec()
    worker.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
