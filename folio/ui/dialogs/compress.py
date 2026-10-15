"""Compress the document: pick a level, see the resulting size, save."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QLabel,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...export import PRESETS, CompressOptions, compress_bytes, document_bytes, write_pdf
from ...model import DocumentModel
from ...ranges import format_size
from .. import theme
from ..widgets import primary
from ..worker import Job

LEVELS = [
    ("light", "Légère", "Qualité maximale, images à 200 ppp."),
    ("medium", "Recommandée", "Bon compromis pour l'écran et l'impression bureautique (150 ppp)."),
    ("strong", "Forte", "Taille minimale pour l'envoi par e-mail (96 ppp)."),
    ("custom", "Personnalisée", "Choisissez la résolution et la qualité JPEG."),
]


class CompressDialog(QDialog):
    def __init__(self, model: DocumentModel, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compresser le PDF")
        self.model = model
        self.job: Job | None = None
        self.result_data: bytes | None = None
        self.saved_path: Path | None = None
        self.source = document_bytes(model)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(12)
        on_disk = model.path.stat().st_size if model.path and model.path.exists() and not model.dirty else None
        size = format_size(on_disk if on_disk else len(self.source))
        head = QLabel(f"Taille actuelle : <b>{size}</b> · {model.page_count()} page(s)")
        root.addWidget(head)

        self.group = QButtonGroup(self)
        for key, label, desc in LEVELS:
            box = QFrame()
            box.setObjectName("LevelCard")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.setSpacing(2)
            rb = QRadioButton(label)
            rb.setStyleSheet("font-weight: 600;")
            rb.setProperty("level", key)
            d = QLabel(desc)
            d.setObjectName("Hint")
            d.setContentsMargins(24, 0, 0, 0)
            lay.addWidget(rb)
            lay.addWidget(d)
            self.group.addButton(rb)
            root.addWidget(box)
            if key == "medium":
                rb.setChecked(True)
        c = theme.colors()
        self.setStyleSheet(f"#LevelCard {{ border: 1px solid {c.border}; border-radius: 8px; background: {c.base}; }}")

        self.custom = QWidget()
        cf = QFormLayout(self.custom)
        cf.setContentsMargins(36, 0, 0, 0)
        self.dpi = QSpinBox()
        self.dpi.setRange(50, 600)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" ppp")
        self.quality = QSpinBox()
        self.quality.setRange(10, 100)
        self.quality.setValue(70)
        self.quality.setSuffix(" %")
        cf.addRow("Résolution des images", self.dpi)
        cf.addRow("Qualité JPEG", self.quality)
        root.addWidget(self.custom)

        self.gray = QCheckBox("Convertir les images en niveaux de gris")
        self.strip = QCheckBox("Supprimer les métadonnées (auteur, logiciel…)")
        root.addWidget(self.gray)
        root.addWidget(self.strip)

        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        root.addWidget(self.progress)
        root.addWidget(self.status)

        buttons = QDialogButtonBox()
        buttons.addButton("Fermer", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_btn = primary(buttons.addButton("Enregistrer sous…", QDialogButtonBox.ButtonRole.AcceptRole))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._run)
        self.group.buttonToggled.connect(lambda *_: self._changed())
        for w in (self.dpi, self.quality):
            w.valueChanged.connect(lambda *_: self._changed())
        for w in (self.gray, self.strip):
            w.toggled.connect(lambda *_: self._changed())
        self._changed()
        self.resize(480, 0)

    def options(self) -> CompressOptions:
        key = self.group.checkedButton().property("level")
        base = PRESETS.get(key) or CompressOptions(
            dpi_threshold=int(self.dpi.value() * 1.1), dpi_target=self.dpi.value(), quality=self.quality.value()
        )
        return CompressOptions(
            images=True,
            dpi_threshold=base.dpi_threshold,
            dpi_target=base.dpi_target,
            quality=base.quality,
            grayscale=self.gray.isChecked(),
            subset_fonts=True,
            strip_metadata=self.strip.isChecked(),
        )

    def _changed(self) -> None:
        self.custom.setVisible(self.group.checkedButton().property("level") == "custom")
        self.result_data = None
        self.save_btn.setEnabled(False)
        self.progress.show()
        self.status.setText("Analyse en cours…")
        self._timer.start()

    def _run(self) -> None:
        if self.job:
            self.job.cancel()
        self.job = Job(compress_bytes, self.source, self.options(), on_done=self._done, on_error=self._error, parent=self)

    def _done(self, data: bytes) -> None:
        self.result_data = data
        self.progress.hide()
        on_disk = self.model.path.stat().st_size if self.model.path and self.model.path.exists() and not self.model.dirty else 0
        before, after = max(len(self.source), on_disk), len(data)
        c = theme.colors()
        if after >= before:
            self.status.setText(f"Ce document est déjà bien compressé : <b>{format_size(after)}</b>.")
        else:
            gain = 100 * (before - after) / before
            self.status.setText(
                f"Taille après compression : <b>{format_size(after)}</b> <span style='color:{c.accent}'>(−{gain:.0f} %)</span>"
            )
        self.save_btn.setEnabled(True)

    def _error(self, err: BaseException) -> None:
        self.progress.hide()
        self.status.setText(f"<span style='color:{theme.colors().danger}'>Échec de la compression : {err}</span>")

    def _save(self) -> None:
        if self.result_data is None:
            return
        base = self.model.path or Path.home() / "document.pdf"
        default = str(base.with_name(f"{base.stem}-compressé.pdf"))
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le PDF compressé", default, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        write_pdf(self.result_data, path, self.model.security)
        self.saved_path = Path(path)
        self.accept()

    def reject(self) -> None:
        if self.job:
            self.job.cancel()
        super().reject()
