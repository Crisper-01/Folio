"""Drive the real app and save screenshots.

    python e2e/shot.py <out_dir> <pdf> [scenario]      (FOLIO_THEME=light|dark)

Scenarios live in e2e/scenario_<name>.py and run with this module's globals.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out: Path
w = app = None


def pump(ms=300):
    QTest.qWait(ms)


def shot(name):
    pump(400)
    w.grab().save(str(out / f"{name}.png"))
    print("saved", name)


def type_text(text):
    """Send real key events (QTest.keyClicks aborts on non-ASCII characters)."""
    for ch in text:
        target = QApplication.focusWidget() or w.view.viewport()
        code = ord(ch.upper()) if ch.isascii() and ch.isalnum() else (Qt.Key.Key_Space if ch == " " else 0)
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier, ch))
        QTest.qWait(5)


def drag(a, b, steps=12):
    vp = w.view.viewport()
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, steps + 1):
        QTest.mouseMove(vp, a + (b - a) * i / steps)
        QTest.qWait(10)
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    pump(100)


def page_point(page_index, x, y):
    """Display coordinates on a page (points) -> viewport point."""
    page = w.view.pages[page_index]
    return w.view.mapFromScene(page.mapToScene(QPointF(x, y)))


def main():
    global out, w, app
    from folio.ui import theme, worker
    from folio.ui.main_window import MainWindow

    out = Path(sys.argv[1])
    pdf = sys.argv[2]
    scenario = sys.argv[3] if len(sys.argv) > 3 else "basic"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setOrganizationName("FolioTest")
    app.setApplicationName("FolioTest")
    theme.install(os.environ.get("FOLIO_THEME", "system"))
    w = MainWindow()
    w.resize(1360, 860)
    w.show()
    w.activateWindow()

    def run():
        shot("00-empty")
        w.open_path(pdf)
        pump(800)
        shot("01-opened")
        try:
            code = (Path(__file__).parent / f"scenario_{scenario}.py").read_text(encoding="utf-8")
            exec(code, globals())
        except BaseException:
            import traceback

            traceback.print_exc()
        for win in QApplication.topLevelWidgets():
            if hasattr(win, "model"):
                win.model._saved_state = win.model._state  # skip the "unsaved" prompt
        app.quit()

    QTimer.singleShot(200, run)
    app.exec()
    worker.shutdown()


if __name__ == "__main__":
    main()
