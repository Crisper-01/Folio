"""Smaller dialogs: page numbers, split, export images, security, properties."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from ...export import build_document
from ...model import DocumentModel, Security
from ...ranges import RangeError, flat_pages, parse_ranges
from ...stamps import PAGENUM, PageNumberOptions, has_group
from .. import theme
from ..widgets import ColorButton, FontCombo, primary


def _buttons(dialog: QDialog, ok_label: str, extra: tuple[str, int] | None = None) -> QDialogButtonBox:
    box = QDialogButtonBox()
    if extra:
        b = box.addButton(extra[0], QDialogButtonBox.ButtonRole.DestructiveRole)
        b.clicked.connect(lambda: dialog.done(extra[1]))
    box.addButton("Annuler", QDialogButtonBox.ButtonRole.RejectRole)
    primary(box.addButton(ok_label, QDialogButtonBox.ButtonRole.AcceptRole))
    box.rejected.connect(dialog.reject)
    return box


def _error_label() -> QLabel:
    lab = QLabel()
    lab.setStyleSheet(f"color: {theme.colors().danger};")
    lab.setWordWrap(True)
    return lab


class PagesChoice(QVBoxLayout):
    """All pages / current page / a custom range."""

    def __init__(self, count: int, current: int, selected: list[int] | None = None) -> None:
        super().__init__()
        self.count, self.current, self.selected = count, current, selected or []
        self.all = QRadioButton("Toutes les pages")
        self.cur = QRadioButton(f"Page actuelle ({current + 1})")
        self.sel = QRadioButton(f"Pages sélectionnées ({len(self.selected)})")
        self.rng = QRadioButton("Pages :")
        self.text = QLineEdit()
        self.text.setPlaceholderText("ex. 1-3, 5")
        self.text.setEnabled(False)
        self.rng.toggled.connect(self.text.setEnabled)
        group = QButtonGroup(self)
        for b in (self.all, self.cur, self.sel, self.rng):
            group.addButton(b)
        self.all.setChecked(True)
        self.addWidget(self.all)
        self.addWidget(self.cur)
        if len(self.selected) > 1:
            self.addWidget(self.sel)
        row = QHBoxLayout()
        row.addWidget(self.rng)
        row.addWidget(self.text, 1)
        self.addLayout(row)

    def pages(self) -> list[int]:
        if self.cur.isChecked():
            return [self.current]
        if self.sel.isChecked():
            return list(self.selected)
        if self.rng.isChecked():
            return flat_pages(self.text.text(), self.count)
        return list(range(self.count))


# ------------------------------------------------------------- page numbers
class PageNumbersDialog(QDialog):
    REMOVE = 2

    def __init__(self, model: DocumentModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Numéroter les pages")
        self.options: PageNumberOptions | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        form = QFormLayout()
        form.setSpacing(10)
        self.template = QComboBox()
        self.template.setEditable(True)
        for t in ("{n} / {total}", "{n}", "Page {n}", "Page {n} sur {total}", "- {n} -"):
            self.template.addItem(t)
        self.position = QComboBox()
        for key, label in (
            ("bottom-center", "En bas, centré"),
            ("bottom-right", "En bas, à droite"),
            ("bottom-left", "En bas, à gauche"),
            ("top-center", "En haut, centré"),
            ("top-right", "En haut, à droite"),
            ("top-left", "En haut, à gauche"),
        ):
            self.position.addItem(label, key)
        self.font_combo = FontCombo()
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(5, 72)
        self.size_spin.setValue(10)
        self.size_spin.setSuffix(" pt")
        self.color = ColorButton("#444444")
        self.margin = QDoubleSpinBox()
        self.margin.setRange(4, 144)
        self.margin.setValue(28)
        self.margin.setSuffix(" pt")
        self.start = QSpinBox()
        self.start.setRange(0, 100000)
        self.start.setValue(1)
        self.skip_first = QCheckBox("Ne pas numéroter la première page (couverture)")
        form.addRow("Format", self.template)
        form.addRow("", _hint("{n} = numéro de page, {total} = nombre de pages"))
        form.addRow("Position", self.position)
        form.addRow("Police", self.font_combo)
        form.addRow("Taille", self.size_spin)
        form.addRow("Couleur", self.color)
        form.addRow("Marge", self.margin)
        form.addRow("Commencer à", self.start)
        form.addRow("", self.skip_first)
        root.addLayout(form)
        extra = ("Retirer la numérotation", self.REMOVE) if has_group(model, PAGENUM) else None
        box = _buttons(self, "Appliquer", extra)
        box.accepted.connect(self._accept)
        root.addWidget(box)

    def _accept(self) -> None:
        self.options = PageNumberOptions(
            template=self.template.currentText() or "{n}",
            position=self.position.currentData(),
            margin=self.margin.value(),
            family=self.font_combo.family(),
            size_pt=self.size_spin.value(),
            color=self.color.color() or "#444444",
            start=self.start.value(),
            skip_first=self.skip_first.isChecked(),
        )
        self.accept()


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Hint")
    return lab


# -------------------------------------------------------------------- split
class SplitDialog(QDialog):
    def __init__(self, model: DocumentModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scinder le document")
        self.model = model
        self.written: list[Path] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)
        self.every = QRadioButton("Un fichier toutes les")
        self.n = QSpinBox()
        self.n.setRange(1, 10000)
        self.n.setValue(1)
        self.n.setSuffix(" page(s)")
        row = QHBoxLayout()
        row.addWidget(self.every)
        row.addWidget(self.n)
        row.addStretch()
        root.addLayout(row)
        self.ranges = QRadioButton("Un fichier par plage :")
        self.text = QLineEdit()
        self.text.setPlaceholderText("ex. 1-3, 4-10, 11-")
        row = QHBoxLayout()
        row.addWidget(self.ranges)
        row.addWidget(self.text, 1)
        root.addLayout(row)
        group = QButtonGroup(self)
        group.addButton(self.every)
        group.addButton(self.ranges)
        self.every.setChecked(True)
        self.text.textEdited.connect(lambda _t: self.ranges.setChecked(True))

        form = QFormLayout()
        self.folder = QLineEdit(str(model.path.parent if model.path else Path.home()))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        frow = QHBoxLayout()
        frow.addWidget(self.folder, 1)
        frow.addWidget(browse)
        self.prefix = QLineEdit((model.path.stem if model.path else "document") + "-partie")
        form.addRow("Dossier", frow)
        form.addRow("Nom des fichiers", self.prefix)
        root.addLayout(form)
        self.error = _error_label()
        root.addWidget(self.error)
        box = _buttons(self, "Scinder")
        box.accepted.connect(self._accept)
        root.addWidget(box)
        self.resize(520, 0)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.folder.text())
        if d:
            self.folder.setText(d)

    def _accept(self) -> None:
        count = self.model.page_count()
        try:
            if self.every.isChecked():
                n = self.n.value()
                groups = [list(range(i, min(i + n, count))) for i in range(0, count, n)]
            else:
                groups = parse_ranges(self.text.text(), count)
        except RangeError as e:
            self.error.setText(str(e))
            return
        folder = Path(self.folder.text())
        if not folder.is_dir():
            self.error.setText("Le dossier n'existe pas.")
            return
        doc = build_document(self.model)
        width = len(str(len(groups)))
        for k, g in enumerate(groups, 1):
            out = pymupdf.open()
            for i in g:
                out.insert_pdf(doc, from_page=i, to_page=i)
            path = folder / f"{self.prefix.text() or 'partie'}-{k:0{width}d}.pdf"
            out.save(path, garbage=3, deflate=True)
            self.written.append(path)
        self.accept()


# ------------------------------------------------------------ export images
class ExportImagesDialog(QDialog):
    def __init__(self, model: DocumentModel, current: int, selected: list[int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exporter en images")
        self.model = model
        self.written: list[Path] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        form = QFormLayout()
        form.setSpacing(10)
        self.pages = PagesChoice(model.page_count(), current, selected)
        form.addRow("Pages", self.pages)
        self.fmt = QComboBox()
        self.fmt.addItem("PNG (sans perte)", "png")
        self.fmt.addItem("JPEG (plus léger)", "jpg")
        self.dpi = QComboBox()
        for d in (72, 150, 200, 300, 600):
            self.dpi.addItem(f"{d} ppp", d)
        self.dpi.setCurrentIndex(1)
        form.addRow("Format", self.fmt)
        form.addRow("Résolution", self.dpi)
        self.folder = QLineEdit(str(model.path.parent if model.path else Path.home()))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow("Dossier", row)
        root.addLayout(form)
        self.error = _error_label()
        root.addWidget(self.error)
        box = _buttons(self, "Exporter")
        box.accepted.connect(self._accept)
        root.addWidget(box)
        self.resize(520, 0)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", self.folder.text())
        if d:
            self.folder.setText(d)

    def _accept(self) -> None:
        try:
            pages = self.pages.pages()
        except RangeError as e:
            self.error.setText(str(e))
            return
        folder = Path(self.folder.text())
        if not folder.is_dir():
            self.error.setText("Le dossier n'existe pas.")
            return
        stem = self.model.path.stem if self.model.path else "page"
        doc = build_document(self.model, pages)
        ext, dpi = self.fmt.currentData(), self.dpi.currentData()
        width = len(str(max(pages) + 1))
        for page, idx in zip(doc, pages, strict=True):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            path = folder / f"{stem}-{idx + 1:0{width}d}.{ext}"
            if ext == "jpg":
                pix.save(path, jpg_quality=90)
            else:
                pix.save(path)
            self.written.append(path)
        self.accept()


# ----------------------------------------------------------------- security
class SecurityDialog(QDialog):
    REMOVE = 2

    def __init__(self, model: DocumentModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Protéger par mot de passe")
        self.security: Security | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)
        intro = QLabel("Le PDF sera chiffré (AES-256) à l'enregistrement. Sans le mot de passe, il ne pourra pas être ouvert.")
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        root.addWidget(intro)
        form = QFormLayout()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit()
        self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_pw = QCheckBox("Afficher")
        self.show_pw.toggled.connect(self._toggle)
        form.addRow("Mot de passe", self.pw)
        form.addRow("Confirmation", self.pw2)
        form.addRow("", self.show_pw)
        self.owner = QLineEdit()
        self.owner.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner.setPlaceholderText("Facultatif (par défaut : le même)")
        form.addRow("Mot de passe propriétaire", self.owner)
        root.addLayout(form)
        self.print_ = QCheckBox("Autoriser l'impression")
        self.copy = QCheckBox("Autoriser la copie du texte")
        self.modify = QCheckBox("Autoriser les modifications")
        sec = model.security
        for cb, val in (
            (self.print_, sec.allow_print if sec else True),
            (self.copy, sec.allow_copy if sec else True),
            (self.modify, sec.allow_modify if sec else True),
        ):
            cb.setChecked(val)
            root.addWidget(cb)
        if sec:
            self.pw.setText(sec.user_password)
            self.pw2.setText(sec.user_password)
        self.error = _error_label()
        root.addWidget(self.error)
        box = _buttons(self, "Protéger", ("Retirer la protection", self.REMOVE) if sec else None)
        box.accepted.connect(self._accept)
        root.addWidget(box)
        self.resize(440, 0)

    def _toggle(self, on: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        for w in (self.pw, self.pw2, self.owner):
            w.setEchoMode(mode)

    def _accept(self) -> None:
        if not self.pw.text():
            self.error.setText("Saisissez un mot de passe.")
            return
        if self.pw.text() != self.pw2.text():
            self.error.setText("Les mots de passe ne correspondent pas.")
            return
        self.security = Security(
            user_password=self.pw.text(),
            owner_password=self.owner.text() or self.pw.text(),
            allow_print=self.print_.isChecked(),
            allow_copy=self.copy.isChecked(),
            allow_modify=self.modify.isChecked(),
        )
        self.accept()


# --------------------------------------------------------------- properties
class PropertiesDialog(QDialog):
    def __init__(self, model: DocumentModel, file_size: int | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Propriétés du document")
        self.metadata: dict[str, str] | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        form = QFormLayout()
        form.setSpacing(10)
        self.fields: dict[str, QLineEdit] = {}
        for key, label in (("title", "Titre"), ("author", "Auteur"), ("subject", "Sujet"), ("keywords", "Mots-clés")):
            e = QLineEdit(model.metadata.get(key, ""))
            self.fields[key] = e
            form.addRow(label, e)
        from ...ranges import format_size

        info = [("Fichier", str(model.path) if model.path else "Non enregistré"), ("Pages", str(model.page_count()))]
        if file_size is not None:
            info.append(("Taille", format_size(file_size)))
        if model.metadata.get("producer"):
            info.append(("Producteur", model.metadata["producer"]))
        info.append(("Protection", "Mot de passe" if model.security else "Aucune"))
        for label, value in info:
            v = QLabel(value)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setObjectName("Hint")
            v.setWordWrap(True)
            form.addRow(label, v)
        root.addLayout(form)
        box = _buttons(self, "Enregistrer")
        box.accepted.connect(self._accept)
        root.addWidget(box)
        self.resize(480, 0)

    def _accept(self) -> None:
        self.metadata = {k: e.text().strip() for k, e in self.fields.items()}
        self.accept()


def confirm(parent, title: str, text: str, ok: str = "Continuer") -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    yes = box.addButton(ok, QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    return box.clickedButton() is yes
