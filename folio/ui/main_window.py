"""Main application window."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pymupdf
from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QIcon, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..export import build_document, document_bytes, write_pdf
from ..model import DocumentModel, PasswordRequired
from ..overlays import ImageOverlay
from ..ranges import format_size
from ..stamps import PAGENUM, WATERMARK, apply_group, apply_page_numbers, apply_watermark
from . import theme
from .page_view import PageView, Tool, ToolDefaults
from .properties import StylePanel
from .renderer import Renderer
from .thumbnails import OPENABLE, ThumbnailPanel

PDF_FILTER = "Documents PDF (*.pdf)"
OPEN_FILTER = "PDF et images (*.pdf *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;Documents PDF (*.pdf)"
INSERT_FILTER = OPEN_FILTER
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
ZOOMS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]

WINDOWS: list[MainWindow] = []


def settings() -> QSettings:
    return QSettings("Folio", "Folio")


class SidePanel(QWidget):
    def __init__(self, title: str, side: str, body: QWidget, header_extra: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("SidePanel")
        self.setProperty("side", side)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 8, 0)
        label = QLabel(title)
        label.setObjectName("PanelTitle")
        head.addWidget(label)
        head.addStretch()
        if header_extra:
            head.addWidget(header_extra)
        lay.addLayout(head)
        lay.addWidget(body, 1)


class EmptyState(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        icon = QLabel()
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(theme.icon("file-text", 56).pixmap(56, 56))
        self.icon = icon
        title = QLabel("Ouvrez un PDF pour commencer")
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel("Glissez-déposez un PDF ou des images dans cette fenêtre,\nou choisissez une action ci-dessous.")
        text.setObjectName("EmptyText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)
        lay.addSpacing(8)
        lay.addWidget(title)
        lay.addWidget(text)
        lay.addSpacing(18)
        row = QHBoxLayout()
        row.addStretch()
        b1 = QPushButton(theme.icon("folder-open", 16), "Ouvrir un PDF…")
        b1.setProperty("primary", True)
        b1.clicked.connect(window.open_dialog)
        b2 = QPushButton(theme.icon("file-image", 16), "Images vers PDF…")
        b2.clicked.connect(window.images_to_pdf)
        b3 = QPushButton(theme.icon("combine", 16), "Fusionner des PDF…")
        b3.clicked.connect(window.merge_files)
        for b in (b1, b2, b3):
            b.setMinimumHeight(34)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.recent_box = QVBoxLayout()
        self.recent_box.setSpacing(2)
        lay.addSpacing(20)
        lay.addLayout(self.recent_box)
        lay.addStretch(3)
        self.window_ = window

    def refresh_recent(self, files: list[str]) -> None:
        while self.recent_box.count():
            w = self.recent_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        files = [f for f in files if Path(f).exists()][:5]
        if not files:
            return
        head = QLabel("RÉCENTS")
        head.setObjectName("PanelTitle")
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_box.addWidget(head)
        for f in files:
            b = QPushButton(theme.icon("file-text", 16), Path(f).name)
            b.setToolTip(f)
            b.setFlat(True)
            b.setStyleSheet(
                "QPushButton { border: none; background: transparent; padding: 4px 10px; } "
                "QPushButton:hover { text-decoration: underline; }"
            )
            b.clicked.connect(lambda _=False, f=f: self.window_.open_path(f))
            row = QHBoxLayout()
            row.addStretch()
            row.addWidget(b)
            row.addStretch()
            holder = QWidget()
            holder.setLayout(row)
            self.recent_box.addWidget(holder)


class SearchBar(QWidget):
    def __init__(self, window: MainWindow) -> None:
        super().__init__()
        self.setObjectName("SearchBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.window_ = window
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Rechercher dans le document…")
        self.edit.setClearButtonEnabled(True)
        self.edit.setMaximumWidth(360)
        self.edit.returnPressed.connect(self.next)
        self.edit.textChanged.connect(lambda _t: self._timer.start())
        self.count = QLabel()
        self.count.setObjectName("Hint")
        prev = QToolButton()
        prev.setIcon(theme.icon("chevron-up"))
        prev.setToolTip("Précédent (Maj+Entrée)")
        prev.clicked.connect(self.prev)
        nxt = QToolButton()
        nxt.setIcon(theme.icon("chevron-down"))
        nxt.setToolTip("Suivant (Entrée)")
        nxt.clicked.connect(self.next)
        close = QToolButton()
        close.setIcon(theme.icon("x"))
        close.clicked.connect(self.close_bar)
        lay.addWidget(self.edit)
        lay.addWidget(prev)
        lay.addWidget(nxt)
        lay.addWidget(self.count)
        lay.addStretch()
        lay.addWidget(close)
        self.hits: list[tuple[int, list]] = []
        self.total = 0
        self.current = -1
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.search)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close_bar()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.prev()
            return
        super().keyPressEvent(e)

    def open_bar(self) -> None:
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self) -> None:
        self.hide()
        self.edit.clear()
        self.hits, self.total, self.current = [], 0, -1
        self.window_.view.show_search_hits([], -1)
        self.window_.view.setFocus()

    def search(self) -> None:
        text = self.edit.text().strip()
        model = self.window_.model
        self.hits, self.total, self.current = [], 0, -1
        if text:
            for i, ref in enumerate(model.pages):
                page = model.fitz_page(ref)
                rects = page.search_for(text)
                if rects:
                    self.hits.append((i, rects))
                    self.total += len(rects)
        if self.total:
            # start at the first hit on or after the current page
            cur_page = self.window_.view.current_page()
            n = 0
            self.current = 0
            for page_index, rects in self.hits:
                if page_index >= cur_page:
                    self.current = n
                    break
                n += len(rects)
        self._show()

    def _show(self) -> None:
        if not self.edit.text().strip():
            self.count.setText("")
        elif not self.total:
            self.count.setText("Aucun résultat")
        else:
            self.count.setText(f"{self.current + 1} sur {self.total}")
        self.window_.view.show_search_hits(self.hits, self.current)

    def next(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self.search()
            return
        if self.total:
            self.current = (self.current + 1) % self.total
            self._show()

    def prev(self) -> None:
        if self.total:
            self.current = (self.current - 1) % self.total
            self._show()


class MainWindow(QMainWindow):
    def __init__(self, model: DocumentModel | None = None) -> None:
        super().__init__()
        WINDOWS.append(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.model = model or DocumentModel.empty()
        self.renderer = Renderer(self.model)
        self.setAcceptDrops(True)
        self.setWindowIcon(QIcon(_app_icon_path()))

        self.view = PageView(self.model, self.renderer)
        self.thumbs = ThumbnailPanel(self.model, self.renderer)
        self.style_panel = StylePanel(self.view)
        self.search_bar = SearchBar(self)
        self.search_bar.hide()
        self.empty = EmptyState(self)

        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.search_bar)
        cl.addWidget(self.view, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(center)

        page_tools = QWidget()
        pl = QHBoxLayout(page_tools)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self._page_tool_buttons = pl

        self.left = SidePanel("Pages", "left", self.thumbs, page_tools)
        self.right = SidePanel("Propriétés", "right", self.style_panel)
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(1, False)
        self.splitter.setSizes([170, 900, 260])
        self.setCentralWidget(self.splitter)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        self.model.subscribe(self._on_model)
        self.view.current_page_changed.connect(self._on_current_page)
        self.view.zoom_changed.connect(self._on_zoom)
        self.view.status_message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.view.page_context_menu.connect(self._page_menu_at)
        self.view.tool_changed.connect(self._on_tool)
        self.view.selection_changed.connect(lambda _s: self._update_actions())
        self.thumbs.page_activated.connect(self.view.go_to_page)
        self.thumbs.reordered.connect(self.model_reorder)
        self.thumbs.files_dropped.connect(self.insert_paths)
        self.thumbs.context_requested.connect(lambda pos: self._page_menu(self.thumbs.viewport().mapToGlobal(pos)))
        self.thumbs.itemSelectionChanged.connect(self._update_actions)
        self.style_panel.action_requested.connect(self._style_action)
        theme.theme.changed.connect(self._retheme)

        self._load_settings()
        self._set_model(self.model)
        self.resize(1360, 860)

    # =============================================================== actions
    def _act(self, text: str, slot, shortcut=None, icon: str | None = None, tip: str | None = None) -> QAction:
        a = QAction(text, self)
        if icon:
            a.setIcon(theme.icon(icon))
            a.setData(icon)
        if shortcut:
            a.setShortcuts(shortcut if isinstance(shortcut, list) else [QKeySequence(shortcut)])
        if tip:
            a.setToolTip(tip)
        elif shortcut:
            sc = shortcut[0] if isinstance(shortcut, list) else QKeySequence(shortcut)
            a.setToolTip(f"{text.replace('…', '')} ({QKeySequence(sc).toString(QKeySequence.SequenceFormat.NativeText)})")
        a.triggered.connect(lambda _=False: slot())
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        S = QKeySequence.StandardKey
        self.a_open = self._act("Ouvrir…", self.open_dialog, S.Open, "folder-open")
        self.a_new_window = self._act("Nouvelle fenêtre", self.new_window, "Ctrl+Shift+N")
        self.a_save = self._act("Enregistrer", self.save, S.Save, "save")
        self.a_save_as = self._act("Enregistrer sous…", self.save_as, S.SaveAs)
        self.a_merge = self._act("Fusionner des PDF…", self.merge_files, None, "combine")
        self.a_img2pdf = self._act("Images vers PDF…", self.images_to_pdf, None, "file-image")
        self.a_export_img = self._act("Exporter en images…", self.export_images, None, "images")
        self.a_print = self._act("Imprimer…", self.print_document, S.Print, "printer")
        self.a_props = self._act("Propriétés du document…", self.edit_properties, "Ctrl+D", "info")
        self.a_close = self._act("Fermer la fenêtre", self.close, S.Close)
        self.a_quit = self._act("Quitter", self.quit_all, S.Quit)

        self.a_undo = self._act("Annuler", self.undo, S.Undo, "undo-2")
        self.a_redo = self._act("Rétablir", self.redo, [QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")], "redo-2")
        self.a_delete = self._act("Supprimer", self.delete_selection, None, "trash-2")
        self.a_dup = self._act("Dupliquer l'élément", self.view.duplicate_selected, "Ctrl+J", "copy")
        self.a_find = self._act("Rechercher…", self.search_bar.open_bar, S.Find, "search")

        self.a_zoom_in = self._act(
            "Zoom avant",
            lambda: self.view.set_zoom(self.view.zoom * 1.2),
            [QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")],
            "zoom-in",
        )
        self.a_zoom_out = self._act("Zoom arrière", lambda: self.view.set_zoom(self.view.zoom / 1.2), "Ctrl+-", "zoom-out")
        self.a_fit_width = self._act("Ajuster à la largeur", lambda: self._fit("width"), "Ctrl+2")
        self.a_fit_page = self._act("Page entière", lambda: self._fit("page"), "Ctrl+1")
        self.a_actual = self._act("Taille réelle", lambda: self.view.set_zoom(1.0), "Ctrl+0")
        self.a_toggle_left = self._act(
            "Panneau des pages", lambda: self.left.setVisible(not self.left.isVisible()), "F4", "panel-left"
        )
        self.a_toggle_right = self._act(
            "Panneau des propriétés", lambda: self.right.setVisible(not self.right.isVisible()), "F6", "panel-right"
        )
        self.a_toggle_left.setCheckable(True)
        self.a_toggle_right.setCheckable(True)

        self.a_insert_blank = self._act("Insérer une page vierge", self.insert_blank, "Ctrl+Shift+B", "file-plus")
        self.a_insert_file = self._act("Insérer depuis un fichier…", self.insert_file_dialog, "Ctrl+Shift+I", "file-up")
        self.a_rot_left = self._act("Pivoter à gauche", lambda: self.rotate_pages(-90), "Ctrl+Shift+L", "rotate-ccw")
        self.a_rot_right = self._act("Pivoter à droite", lambda: self.rotate_pages(90), "Ctrl+Shift+R", "rotate-cw")
        self.a_dup_page = self._act("Dupliquer les pages", self.duplicate_pages, None, "copy")
        self.a_del_page = self._act("Supprimer les pages", self.delete_pages, "Ctrl+Shift+Del", "trash-2")
        self.a_move_up = self._act("Monter", lambda: self.move_pages(-1), "Ctrl+Shift+Up", "chevron-up")
        self.a_move_down = self._act("Descendre", lambda: self.move_pages(1), "Ctrl+Shift+Down", "chevron-down")
        self.a_extract = self._act("Extraire les pages…", self.extract_pages, None, "file-output")
        self.a_split = self._act("Scinder le document…", self.split_document, None, "scissors")
        self.a_select_all_pages = self._act("Sélectionner toutes les pages", self.thumbs.selectAll, None)

        self.a_compress = self._act("Compresser…", self.compress, None, "shrink", "Réduire la taille du PDF")
        self.a_watermark = self._act("Filigrane…", self.watermark, None, "droplet")
        self.a_pagenum = self._act("Numéroter les pages…", self.page_numbers, None, "list-ordered")
        self.a_protect = self._act("Protéger par mot de passe…", self.protect, None, "lock")
        self.a_signature = self._act("Signature…", self.add_signature, None, "signature", "Ajouter une signature")
        self.a_image = self._act("Image…", self.add_image, None, "image", "Insérer une image sur la page")
        self.a_about = self._act("À propos de Folio", self.about)

        # drawing tools
        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, label, icon, key in (
            (Tool.SELECT, "Sélection", "mouse-pointer-2", "V"),
            (Tool.TEXT, "Texte", "type", "T"),
            (Tool.PEN, "Dessin libre", "pen-tool", "P"),
            (Tool.HIGHLIGHT, "Surligner", "highlighter", "H"),
            (Tool.RECT, "Rectangle", "square", "R"),
            (Tool.ELLIPSE, "Ellipse", "circle", "E"),
            (Tool.LINE, "Ligne", "minus", "L"),
            (Tool.ARROW, "Flèche", "move-up-right", "A"),
            (Tool.REDACT, "Caviarder", "eye-off", "X"),
        ):
            a = QAction(theme.icon(icon), label, self)
            a.setData(icon)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(key))
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            a.setToolTip(f"{label} ({key})")
            a.triggered.connect(lambda _=False, t=tool: self.view.set_tool(t))
            self.tool_group.addAction(a)
            self.view.addAction(a)
            self.tool_actions[tool] = a
        self.tool_actions[Tool.SELECT].setChecked(True)
        # Delete key for page thumbnails
        self.thumbs.addAction(self._thumb_delete_action())

    def _thumb_delete_action(self) -> QAction:
        a = QAction(self.thumbs)
        a.setShortcut(QKeySequence.StandardKey.Delete)
        a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        a.triggered.connect(self.delete_pages)
        return a

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("&Fichier")
        f.addAction(self.a_open)
        self.recent_menu = f.addMenu("Ouvrir un fichier récent")
        f.addAction(self.a_new_window)
        f.addSeparator()
        f.addAction(self.a_save)
        f.addAction(self.a_save_as)
        f.addSeparator()
        f.addAction(self.a_merge)
        f.addAction(self.a_img2pdf)
        f.addAction(self.a_export_img)
        f.addSeparator()
        f.addAction(self.a_print)
        f.addAction(self.a_props)
        f.addSeparator()
        f.addAction(self.a_close)
        f.addAction(self.a_quit)

        e = mb.addMenu("&Édition")
        for a in (self.a_undo, self.a_redo, None, self.a_dup, self.a_delete, None, self.a_find):
            e.addSeparator() if a is None else e.addAction(a)

        ins = mb.addMenu("&Insérer")
        ins.addAction(self.tool_actions[Tool.TEXT])
        ins.addAction(self.a_signature)
        ins.addAction(self.a_image)
        ins.addSeparator()
        for t in (Tool.PEN, Tool.HIGHLIGHT, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.REDACT):
            ins.addAction(self.tool_actions[t])

        p = mb.addMenu("&Pages")
        for a in (
            self.a_insert_blank,
            self.a_insert_file,
            None,
            self.a_rot_left,
            self.a_rot_right,
            self.a_move_up,
            self.a_move_down,
            self.a_dup_page,
            self.a_del_page,
            None,
            self.a_extract,
            self.a_split,
            None,
            self.a_select_all_pages,
        ):
            p.addSeparator() if a is None else p.addAction(a)

        t = mb.addMenu("&Outils")
        for a in (self.a_compress, self.a_watermark, self.a_pagenum, self.a_protect):
            t.addAction(a)

        v = mb.addMenu("&Affichage")
        for a in (
            self.a_zoom_in,
            self.a_zoom_out,
            None,
            self.a_fit_width,
            self.a_fit_page,
            self.a_actual,
            None,
            self.a_toggle_left,
            self.a_toggle_right,
        ):
            v.addSeparator() if a is None else v.addAction(a)

        v.addSeparator()
        tm = v.addMenu("Thème")
        group = QActionGroup(self)
        for key, label in (("system", "Comme le système"), ("light", "Clair"), ("dark", "Sombre")):
            a = tm.addAction(label)
            a.setCheckable(True)
            a.setChecked(theme.theme.mode == key)
            a.triggered.connect(lambda _=False, k=key: self._set_theme(k))
            group.addAction(a)
        self._theme_actions = group

        h = mb.addMenu("&Aide")
        h.addAction(self.a_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("Outils")
        tb.setMovable(False)
        tb.setIconSize(theme.ICON_SIZE)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(tb)
        self.toolbar = tb
        tb.addAction(self.a_open)
        tb.addAction(self.a_save)
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addAction(self.a_redo)
        tb.addSeparator()
        for tool in (Tool.SELECT, Tool.TEXT):
            tb.addAction(self.tool_actions[tool])
        tb.addAction(self.a_signature)
        for tool in (Tool.PEN, Tool.HIGHLIGHT):
            tb.addAction(self.tool_actions[tool])
        # shapes in a drop-down
        self.shape_button = QToolButton()
        self.shape_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        shape_menu = QMenu(self.shape_button)
        for t in (Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW):
            shape_menu.addAction(self.tool_actions[t])
            self.tool_actions[t].triggered.connect(lambda _=False, t=t: self.shape_button.setDefaultAction(self.tool_actions[t]))
        self.shape_button.setMenu(shape_menu)
        self.shape_button.setDefaultAction(self.tool_actions[Tool.RECT])
        tb.addWidget(self.shape_button)
        tb.addAction(self.a_image)
        tb.addAction(self.tool_actions[Tool.REDACT])
        tb.addSeparator()

        self.doc_tools = QToolButton()
        self.doc_tools.setText("Outils")
        self.doc_tools.setIcon(theme.icon("settings-2"))
        self.doc_tools.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.doc_tools.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.doc_tools)
        for a in (
            self.a_compress,
            self.a_watermark,
            self.a_pagenum,
            self.a_protect,
            None,
            self.a_merge,
            self.a_split,
            self.a_extract,
            self.a_img2pdf,
            self.a_export_img,
        ):
            m.addSeparator() if a is None else m.addAction(a)
        self.doc_tools.setMenu(m)
        self.a_compress.setIconText("Compresser")
        self.compress_btn = QToolButton()
        self.compress_btn.setDefaultAction(self.a_compress)
        self.compress_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.addWidget(self.compress_btn)
        tb.addWidget(self.doc_tools)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        tb.addAction(self.a_find)
        tb.addSeparator()
        self.page_edit = QLineEdit()
        self.page_edit.setFixedWidth(46)
        self.page_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_edit.returnPressed.connect(self._page_entered)
        self.page_total = QLabel(" / 0")
        self.page_total.setObjectName("Hint")
        tb.addWidget(self.page_edit)
        tb.addWidget(self.page_total)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.setFixedWidth(118)
        self.zoom_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_combo.addItem("Largeur", "width")
        self.zoom_combo.addItem("Page entière", "page")
        for z in ZOOMS:
            self.zoom_combo.addItem(f"{int(z * 100)} %", z)
        self.zoom_combo.activated.connect(self._zoom_chosen)
        self.zoom_combo.lineEdit().returnPressed.connect(self._zoom_typed)
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.a_zoom_in)

        # page tool buttons in the thumbnails header
        for a in (self.a_insert_blank, self.a_insert_file, self.a_rot_right, self.a_del_page):
            b = QToolButton()
            b.setDefaultAction(a)
            b.setIconSize(QSize(16, 16))
            b.setAutoRaise(True)
            self._page_tool_buttons.addWidget(b)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.status_info = QLabel()
        self.status_info.setObjectName("Hint")
        sb.addPermanentWidget(self.status_info)

    def _set_theme(self, mode: str) -> None:
        settings().setValue("theme", mode)
        theme.theme.set_mode(mode)

    def _retheme(self) -> None:
        for a in self.findChildren(QAction):
            name = a.data()
            if isinstance(name, str) and name:
                a.setIcon(theme.icon(name))
        self.doc_tools.setIcon(theme.icon("settings-2"))
        self.empty.icon.setPixmap(theme.icon("file-text", 56).pixmap(56, 56))
        self.thumbs.viewport().update()
        self.view.viewport().update()

    # ============================================================ model glue
    def _set_model(self, model: DocumentModel) -> None:
        self.model = model
        model.subscribe(self._on_model)
        self.renderer.set_model(model)
        self.view.set_model(model)
        self.thumbs.set_model(model)
        self.search_bar.close_bar() if self.search_bar.isVisible() else None
        self._refresh_all()

    def _on_model(self, what: str) -> None:
        if what == "pages":
            self.view.sync_pages()
            self.thumbs.rebuild()
            if self.view.fit_mode:
                self.view.apply_fit()
        elif what == "overlays":
            self.view.sync_overlays()
            self.thumbs.refresh()
        self._refresh_all()

    def _refresh_all(self) -> None:
        has_pages = self.model.page_count() > 0
        self.stack.setCurrentIndex(1 if has_pages else 0)
        if not has_pages:
            self.empty.refresh_recent(self._recent())
        title = self.model.title + (" •" if self.model.dirty else "")
        self.setWindowTitle(f"{title} - Folio")
        self.page_total.setText(f" / {self.model.page_count()}")
        self._on_current_page(self.view.current_page())
        self._update_actions()
        info = f"{self.model.page_count()} page(s)"
        if self.model.security:
            info += " · protégé"
        self.status_info.setText(info)

    def _update_actions(self) -> None:
        has = self.model.page_count() > 0
        self.a_undo.setEnabled(self.model.can_undo())
        self.a_redo.setEnabled(self.model.can_redo())
        for a in (
            self.a_save,
            self.a_save_as,
            self.a_export_img,
            self.a_print,
            self.a_props,
            self.a_find,
            self.a_rot_left,
            self.a_rot_right,
            self.a_dup_page,
            self.a_del_page,
            self.a_move_up,
            self.a_move_down,
            self.a_extract,
            self.a_split,
            self.a_compress,
            self.a_watermark,
            self.a_pagenum,
            self.a_protect,
            self.a_signature,
            self.a_image,
            self.a_zoom_in,
            self.a_zoom_out,
            self.a_fit_page,
            self.a_fit_width,
            self.a_actual,
            self.a_select_all_pages,
        ):
            a.setEnabled(has)
        for a in self.tool_actions.values():
            a.setEnabled(has)
        self.shape_button.setEnabled(has)
        self.doc_tools.setEnabled(True)
        sel = bool(self.view.selected_overlays())
        self.a_dup.setEnabled(sel)
        self.a_delete.setEnabled(sel or bool(self.thumbs.selected_rows()))
        self.a_toggle_left.setChecked(self.left.isVisible())
        self.a_toggle_right.setChecked(self.right.isVisible())
        self.page_edit.setEnabled(has)
        self.zoom_combo.setEnabled(has)

    def _on_current_page(self, idx: int) -> None:
        self.page_edit.setText(str(idx + 1) if idx >= 0 else "")
        if idx >= 0:
            self.thumbs.set_current(idx)

    def _on_zoom(self, z: float) -> None:
        mode = self.view.fit_mode
        if mode:
            self.zoom_combo.setCurrentIndex(self.zoom_combo.findData(mode))
        self.zoom_combo.setEditText(f"{round(z * 100)} %")

    def _on_tool(self, tool: Tool) -> None:
        a = self.tool_actions.get(tool)
        if a:
            a.setChecked(True)
        elif tool == Tool.PLACE:
            for act in self.tool_actions.values():
                act.setChecked(False)
            self.tool_group.checkedAction() and self.tool_group.checkedAction().setChecked(False)

    def _fit(self, mode: str) -> None:
        self.view.fit_mode = mode
        self.view.apply_fit()

    def _zoom_chosen(self, index: int) -> None:
        data = self.zoom_combo.itemData(index)
        if isinstance(data, str):
            self._fit(data)
        else:
            self.view.set_zoom(float(data))

    def _zoom_typed(self) -> None:
        txt = self.zoom_combo.currentText().replace("%", "").replace(",", ".").strip()
        try:
            self.view.set_zoom(float(txt) / 100.0)
        except ValueError:
            self._on_zoom(self.view.zoom)

    def _page_entered(self) -> None:
        try:
            self.view.go_to_page(int(self.page_edit.text()) - 1)
        except ValueError:
            pass
        self.view.setFocus()

    # ================================================================ files
    def _recent(self) -> list[str]:
        val = settings().value("recent", [])
        if isinstance(val, str):
            val = [val]
        return list(val or [])

    def _add_recent(self, path: Path) -> None:
        files = [str(path)] + [f for f in self._recent() if f != str(path)]
        settings().setValue("recent", files[:12])
        for w in WINDOWS:
            w._fill_recent_menu()

    def _fill_recent_menu(self) -> None:
        self.recent_menu.clear()
        files = [f for f in self._recent() if Path(f).exists()]
        for f in files:
            self.recent_menu.addAction(Path(f).name, lambda f=f: self.open_path(f)).setToolTip(f)
        self.recent_menu.setEnabled(bool(files))

    def _start_dir(self) -> str:
        if self.model.path:
            return str(self.model.path.parent)
        return settings().value("last_dir", str(Path.home()))

    def _remember_dir(self, path: str) -> None:
        settings().setValue("last_dir", str(Path(path).parent))

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir", self._start_dir(), OPEN_FILTER)
        if path:
            self.open_path(path)

    def _ask_password(self, name: str, retry: bool) -> str | None:
        text = f"« {name} » est protégé par un mot de passe."
        if retry:
            text = "Mot de passe incorrect. Réessayez.\n\n" + text
        pw, ok = QInputDialog.getText(self, "Document protégé", text, QLineEdit.EchoMode.Password)
        return pw if ok else None

    def _load_model(self, path: str) -> DocumentModel | None:
        password, retry = None, False
        while True:
            try:
                return DocumentModel.from_file(path, password)
            except PasswordRequired:
                password = self._ask_password(Path(path).name, retry)
                retry = True
                if password is None:
                    return None
            except Exception as e:
                QMessageBox.critical(self, "Ouverture impossible", f"Impossible d'ouvrir « {Path(path).name} ».\n\n{e}")
                return None

    def open_path(self, path: str) -> None:
        if Path(path).suffix.lower() != ".pdf":
            self.images_to_pdf([path])
            return
        for w in WINDOWS:
            if w.model.path and w.model.path.resolve() == Path(path).resolve():
                w.raise_()
                w.activateWindow()
                return
        model = self._load_model(path)
        if model is None:
            return
        self._remember_dir(path)
        self._add_recent(Path(path))
        self.show_model(model)

    def show_model(self, model: DocumentModel) -> None:
        """Show a document here if this window is empty, else in a new window."""
        if self.model.page_count() == 0 and not self.model.dirty:
            self._set_model(model)
        else:
            w = MainWindow(model)
            w.show()

    def new_window(self) -> None:
        w = MainWindow()
        w.show()

    def save(self) -> bool:
        if self.model.path is None:
            return self.save_as()
        return self._save_to(self.model.path)

    def save_as(self) -> bool:
        default = str(self.model.path or Path(self._start_dir()) / "document.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer sous", default, PDF_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._remember_dir(path)
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            write_pdf(document_bytes(self.model), path, self.model.security)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Enregistrement impossible", f"Le fichier n'a pas pu être enregistré.\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        self.model.mark_saved(path)
        self._add_recent(path)
        self.statusBar().showMessage(f"Enregistré : {path.name} ({format_size(path.stat().st_size)})", 6000)
        return True

    def merge_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Fusionner des PDF", self._start_dir(), OPEN_FILTER)
        if not files:
            return
        self._remember_dir(files[0])
        if self.model.page_count() == 0 and not self.model.dirty:
            self.insert_paths(files, 0)
        else:
            self.insert_paths(files, self.model.page_count())

    def insert_paths(self, paths: list[str], at: int) -> None:
        inserted = 0
        for p in paths:
            password, retry = None, False
            while True:
                try:
                    inserted += self.model.insert_file(p, at + inserted, password)
                    break
                except PasswordRequired:
                    password = self._ask_password(Path(p).name, retry)
                    retry = True
                    if password is None:
                        break
                except Exception as e:
                    QMessageBox.warning(self, "Fichier ignoré", f"« {Path(p).name} » n'a pas pu être inséré.\n\n{e}")
                    break
        if inserted:
            self.statusBar().showMessage(f"{inserted} page(s) insérée(s)", 5000)
            self.view.go_to_page(at)

    def insert_file_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Insérer des pages", self._start_dir(), INSERT_FILTER)
        if files:
            self.insert_paths(files, self._insert_position())

    def _insert_position(self) -> int:
        rows = self.thumbs.selected_rows()
        if rows:
            return rows[-1] + 1
        cur = self.view.current_page()
        return cur + 1 if cur >= 0 else self.model.page_count()

    # ================================================================= pages
    def _target_pages(self) -> list[int]:
        rows = self.thumbs.selected_rows()
        if rows:
            return rows
        cur = self.view.current_page()
        return [cur] if cur >= 0 else []

    def insert_blank(self) -> None:
        at = self._insert_position()
        self.model.insert_blank(at)
        self.view.go_to_page(at)

    def rotate_pages(self, delta: int) -> None:
        self.model.rotate_pages(self._target_pages(), delta)

    def duplicate_pages(self) -> None:
        self.model.duplicate_pages(self._target_pages())

    def delete_pages(self) -> None:
        pages = self._target_pages()
        if not pages:
            return
        if len(pages) == self.model.page_count():
            QMessageBox.information(self, "Supprimer les pages", "Un document doit garder au moins une page.")
            return
        self.model.delete_pages(pages)

    def move_pages(self, step: int) -> None:
        pages = self._target_pages()
        if not pages:
            return
        uids = [self.model.pages[i].uid for i in pages]
        to = (pages[0] - 1) if step < 0 else (pages[0] + 1)
        self.model.move_pages(pages, max(0, to))
        self._reselect(uids)

    def model_reorder(self, uids: list[str]) -> None:
        moved = [self.thumbs.item(r).data(Qt.ItemDataRole.UserRole) for r in self.thumbs.selected_rows()]
        self.model.reorder(uids)
        self._reselect(moved)

    def _reselect(self, uids: list[str]) -> None:
        self.thumbs.clearSelection()
        first = None
        for i in range(self.thumbs.count()):
            item = self.thumbs.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in uids:
                item.setSelected(True)
                first = i if first is None else first
        if first is not None:
            self.view.go_to_page(first)

    def extract_pages(self) -> None:
        pages = self._target_pages()
        if not pages:
            return
        stem = self.model.path.stem if self.model.path else "document"
        default = str(Path(self._start_dir()) / f"{stem}-extrait.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Extraire les pages", default, PDF_FILTER)
        if not path:
            return
        write_pdf(document_bytes(self.model, pages), path, self.model.security)
        self.statusBar().showMessage(f"{len(pages)} page(s) extraite(s) vers {Path(path).name}", 6000)

    def split_document(self) -> None:
        from .dialogs.tools import SplitDialog

        d = SplitDialog(self.model, self)
        if d.exec():
            self.statusBar().showMessage(f"{len(d.written)} fichier(s) créé(s) dans {d.written[0].parent}", 8000)

    def _page_menu_at(self, index: int, global_pos) -> None:
        if index not in self.thumbs.selected_rows():
            self.thumbs.clearSelection()
            self.thumbs.item(index).setSelected(True)
        self._page_menu(global_pos)

    def _page_menu(self, global_pos) -> None:
        if not self.model.page_count():
            return
        m = QMenu(self)
        for a in (
            self.a_rot_left,
            self.a_rot_right,
            None,
            self.a_insert_blank,
            self.a_insert_file,
            self.a_dup_page,
            None,
            self.a_move_up,
            self.a_move_down,
            None,
            self.a_extract,
            self.a_del_page,
        ):
            m.addSeparator() if a is None else m.addAction(a)
        m.exec(global_pos)

    # ================================================================ edits
    def undo(self) -> None:
        self.model.undo()

    def redo(self) -> None:
        self.model.redo()

    def delete_selection(self) -> None:
        if self.view.selected_overlays():
            self.view.delete_selected()
        elif self.thumbs.hasFocus():
            self.delete_pages()

    def _style_action(self, key: str) -> None:
        {
            "duplicate": self.view.duplicate_selected,
            "rotate": lambda: self.view.rotate_selected(90),
            "delete": self.view.delete_selected,
            "front": lambda: self.view.reorder_selected(True),
            "back": lambda: self.view.reorder_selected(False),
        }[key]()

    def add_signature(self) -> None:
        from .dialogs.signature import SignatureDialog

        d = SignatureDialog(self)
        if d.exec() and d.result_overlay is not None:
            self.view.begin_place(d.result_overlay)
            self.view.setFocus()

    def add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Insérer une image", self._start_dir(), IMAGE_FILTER)
        if not path:
            return
        from .dialogs.images_to_pdf import normalized_image_bytes

        data = normalized_image_bytes(path)
        pix = pymupdf.Pixmap(data)
        ref = self.model.pages[max(self.view.current_page(), 0)]
        pw, ph = self.model.display_size(ref)
        w = min(pw * 0.5, pix.width * 72 / 96)
        h = w * pix.height / pix.width
        if h > ph * 0.6:
            h = ph * 0.6
            w = h * pix.width / pix.height
        self.view.begin_place(ImageOverlay(w=w, h=h, data=data))
        self.view.setFocus()

    # ================================================================ tools
    def compress(self) -> None:
        from .dialogs.compress import CompressDialog

        d = CompressDialog(self.model, self)
        if d.exec() and d.saved_path:
            self.statusBar().showMessage(
                f"PDF compressé enregistré : {d.saved_path.name} ({format_size(d.saved_path.stat().st_size)})", 8000
            )
            self._add_recent(d.saved_path)

    def watermark(self) -> None:
        from .dialogs.watermark import WatermarkDialog

        d = WatermarkDialog(self.model, self.view.current_page(), self)
        code = d.exec()
        if code == WatermarkDialog.REMOVE:
            apply_group(self.model, WATERMARK, {})
        elif code and d.result_options:
            apply_watermark(self.model, d.result_options)

    def page_numbers(self) -> None:
        from .dialogs.tools import PageNumbersDialog

        d = PageNumbersDialog(self.model, self)
        code = d.exec()
        if code == PageNumbersDialog.REMOVE:
            apply_group(self.model, PAGENUM, {})
        elif code and d.options:
            apply_page_numbers(self.model, d.options)

    def protect(self) -> None:
        from .dialogs.tools import SecurityDialog

        d = SecurityDialog(self.model, self)
        code = d.exec()
        if code == SecurityDialog.REMOVE:
            self.model.set_security(None)
            self.statusBar().showMessage("La protection sera retirée au prochain enregistrement", 6000)
        elif code and d.security:
            self.model.set_security(d.security)
            self.statusBar().showMessage("Le document sera chiffré au prochain enregistrement", 6000)

    def edit_properties(self) -> None:
        from .dialogs.tools import PropertiesDialog

        size = self.model.path.stat().st_size if self.model.path and self.model.path.exists() else None
        d = PropertiesDialog(self.model, size, self)
        if d.exec() and d.metadata is not None:
            if any(self.model.metadata.get(k, "") != v for k, v in d.metadata.items()):
                self.model.set_metadata(d.metadata)

    def images_to_pdf(self, paths: list[str] | None = None) -> None:
        from .dialogs.images_to_pdf import ImagesToPdfDialog

        d = ImagesToPdfDialog(paths, self)
        if d.exec() and d.result_model is not None:
            target = self if self.model.page_count() == 0 and not self.model.dirty else MainWindow()
            if target is not self:
                target.show()
            target._set_model(d.result_model)
            QTimer.singleShot(0, target.save_as)

    def export_images(self) -> None:
        from .dialogs.tools import ExportImagesDialog

        d = ExportImagesDialog(self.model, max(self.view.current_page(), 0), self.thumbs.selected_rows(), self)
        if d.exec() and d.written:
            self.statusBar().showMessage(f"{len(d.written)} image(s) exportée(s) dans {d.written[0].parent}", 8000)

    def print_document(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(self.model.title)
        printer.setFromTo(1, self.model.page_count())
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintPageRange, True)
        dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
        if not dlg.exec():
            return
        count = self.model.page_count()
        rng = printer.printRange()
        if rng == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
            pages = list(range(printer.fromPage() - 1, min(printer.toPage(), count)))
        elif rng == QPrinter.PrintRange.CurrentPage:
            pages = [max(self.view.current_page(), 0)]
        else:
            pages = list(range(count))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            doc = build_document(self.model, pages)
            painter = QPainter()
            if not painter.begin(printer):
                raise RuntimeError("Impossible de démarrer l'impression")
            dpi = min(printer.resolution(), 300)
            for k, page in enumerate(doc):
                if k:
                    printer.newPage()
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                from PySide6.QtGui import QImage

                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                area = painter.viewport()
                size = img.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
                x = (area.width() - size.width()) // 2
                y = (area.height() - size.height()) // 2
                painter.drawImage(
                    x, y, img.scaled(size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                )
                QApplication.processEvents()
            painter.end()
        except Exception as e:
            QMessageBox.critical(self, "Impression impossible", str(e))
        finally:
            QApplication.restoreOverrideCursor()

    def about(self) -> None:
        from .. import __version__

        QMessageBox.about(
            self,
            "À propos de Folio",
            f"<h3>Folio {__version__}</h3><p>Éditeur PDF local pour Windows et Linux.</p>"
            "<p>Vos documents ne quittent jamais votre ordinateur.</p>"
            f"<p style='color:gray'>PyMuPDF {pymupdf.VersionBind} · Qt {QApplication.instance().applicationVersion() or ''}</p>",
        )

    # ============================================================== settings
    def _load_settings(self) -> None:
        s = settings()
        geo = s.value("geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        raw = s.value("tool_defaults")
        if raw:
            try:
                data = json.loads(raw)
                fields = {f.name for f in dataclasses.fields(ToolDefaults)}
                self.view.defaults = ToolDefaults(**{k: v for k, v in data.items() if k in fields})
            except (ValueError, TypeError):
                pass
        self.left.setVisible(s.value("show_left", True, type=bool))
        self.right.setVisible(s.value("show_right", True, type=bool))
        self._fill_recent_menu()

    def _save_settings(self) -> None:
        s = settings()
        s.setValue("geometry", self.saveGeometry())
        s.setValue("tool_defaults", json.dumps(dataclasses.asdict(self.view.defaults)))
        s.setValue("show_left", self.left.isVisible())
        s.setValue("show_right", self.right.isVisible())

    # ================================================================ events
    def _confirm_discard(self) -> bool:
        if not self.model.dirty or self.model.page_count() == 0:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Modifications non enregistrées")
        box.setText(f"Enregistrer les modifications de « {self.model.title} » ?")
        box.setInformativeText("Sinon, vos modifications seront perdues.")
        save = box.addButton("Enregistrer", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Ne pas enregistrer", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is save:
            return self.save()
        return box.clickedButton() is discard

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_settings()
        if self in WINDOWS:
            WINDOWS.remove(self)
        event.accept()

    def quit_all(self) -> None:
        for w in list(WINDOWS):
            if not w.close():
                return
        QApplication.quit()

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).suffix.lower() in OPENABLE for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if Path(u.toLocalFile()).suffix.lower() in OPENABLE]
        if not paths:
            return
        pdfs = [p for p in paths if p.lower().endswith(".pdf")]
        images = [p for p in paths if not p.lower().endswith(".pdf")]
        if self.model.page_count() == 0:
            if pdfs and not images and len(pdfs) == 1:
                self.open_path(pdfs[0])
            elif images and not pdfs:
                self.images_to_pdf(images)
            else:
                self.insert_paths(paths, 0)
        else:
            self.insert_paths(paths, self._insert_position())
        e.acceptProposedAction()


def _app_icon_path() -> str:
    from ..paths import asset_path

    return asset_path("folio.png")
