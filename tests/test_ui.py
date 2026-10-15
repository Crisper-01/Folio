"""Drive the real main window (offscreen) like a user would."""

import pymupdf
import pytest
from PySide6.QtCore import QEvent, QPointF, QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from folio.overlays import BoxOverlay, TextOverlay
from folio.ui import theme, worker
from folio.ui.page_view import Tool

from .test_export import make_pdf


@pytest.fixture
def win(qtbot, tmp_path, monkeypatch):
    QApplication.instance().setOrganizationName("FolioPytest")
    monkeypatch.setattr("folio.ui.main_window.settings", lambda: QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    if theme.theme is None:
        theme.install("light")
    from folio.ui.main_window import MainWindow

    w = MainWindow()

    def discard_changes(widget):
        widget.model._saved_state = widget.model._state  # no "unsaved changes" prompt

    qtbot.addWidget(w, before_close_func=discard_changes)
    w.resize(1280, 860)
    w.show()
    qtbot.waitExposed(w)
    w.open_path(str(make_pdf(tmp_path / "doc.pdf", pages=3, size=(595, 842))))
    QTest.qWait(200)
    yield w
    worker.shutdown()


def vp(w, x, y, page=0):
    item = w.view.pages[page]
    return w.view.mapFromScene(item.mapToScene(QPointF(x, y)))


def type_text(text):
    for ch in text:
        target = QApplication.focusWidget()
        code = ord(ch.upper()) if ch.isascii() and ch.isalnum() else 0
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier, ch))


def drag(w, a, b):
    v = w.view.viewport()
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for i in range(1, 9):
        QTest.mouseMove(v, a + (b - a) * i / 8)
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)


def test_type_text_and_save(win, tmp_path):
    win.view.set_tool(Tool.TEXT)
    QTest.mouseClick(win.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, vp(win, 100, 200))
    type_text("Été à Noël")
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    QTest.qWait(50)
    texts = [o for o in win.model.pages[0].overlays if isinstance(o, TextOverlay)]
    assert [t.text for t in texts] == ["Été à Noël"]
    assert win.model.dirty and win.windowTitle().startswith("doc.pdf •")
    out = tmp_path / "out.pdf"
    assert win._save_to(out)
    assert "Été à Noël" in pymupdf.open(out)[0].get_text()
    assert not win.model.dirty


def test_draw_resize_move_undo(win):
    win.view.set_tool(Tool.RECT)
    drag(win, vp(win, 100, 400), vp(win, 200, 460))
    box = win.model.pages[0].overlays[-1]
    assert isinstance(box, BoxOverlay) and round(box.w) == 100 and round(box.h) == 60
    win.view.set_tool(Tool.SELECT)
    win.view.select_uids([box.uid])
    drag(win, vp(win, 200, 460), vp(win, 250, 500))  # bottom-right handle
    assert (box.w, box.h) == (pytest.approx(150, abs=1.5), pytest.approx(100, abs=1.5))
    drag(win, vp(win, 150, 430), vp(win, 170, 430))  # body
    assert box.x == pytest.approx(120, abs=1.5)
    win.undo()
    win.undo()
    box = win.model.pages[0].overlays[-1]
    assert (box.x, box.w) == (pytest.approx(100, abs=1.5), pytest.approx(100, abs=1.5))
    win.redo()
    assert win.model.pages[0].overlays[-1].w == pytest.approx(150, abs=1.5)


def test_rotate_and_reorder_pages(win):
    win.thumbs.setCurrentRow(1)
    win.thumbs.item(1).setSelected(True)
    win.rotate_pages(90)
    assert win.model.pages[1].rotation == 90
    assert win.view.pages[1].w > win.view.pages[1].h
    uids = [p.uid for p in win.model.pages]
    win.model_reorder([uids[2], uids[0], uids[1]])
    assert [p.index for p in win.model.pages] == [2, 0, 1]
    assert win.thumbs.count() == 3
    win.undo()
    assert [p.index for p in win.model.pages] == [0, 1, 2]


def test_delete_last_page_is_refused(win, monkeypatch):
    shown = []
    monkeypatch.setattr("folio.ui.main_window.QMessageBox.information", lambda *a: shown.append(a))
    win.thumbs.selectAll()
    win.delete_pages()
    assert win.model.page_count() == 3 and shown


def test_compress_dialog_runs_in_worker(win, qtbot):
    from folio.ui.dialogs.compress import CompressDialog

    d = CompressDialog(win.model, win)
    d.show()
    qtbot.waitUntil(lambda: d.result_data is not None, timeout=60000)
    assert d.save_btn.isEnabled()
    d.reject()


def test_watermark_dialog_applies(win):
    from folio.ui.dialogs.watermark import WatermarkDialog

    d = WatermarkDialog(win.model, 0, win)
    d.form.text.setText("SPÉCIMEN")
    d._accept()
    assert d.result_options and d.result_options.text == "SPÉCIMEN"
    from folio.stamps import apply_watermark

    apply_watermark(win.model, d.result_options)
    assert all(any(o.group == "watermark" for o in p.overlays) for p in win.model.pages)


def test_search_finds_text(win):
    win.search_bar.open_bar()
    win.search_bar.edit.setText("Page 2")
    win.search_bar.search()
    assert win.search_bar.total == 1
    assert win.search_bar.count.text() == "1 sur 1"
