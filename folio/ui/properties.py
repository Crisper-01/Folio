"""Right-hand panel editing the style of the selection or the active tool."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..fonts import FAMILIES
from ..model import DocumentModel
from ..overlays import BoxOverlay, InkOverlay, LineOverlay, Overlay, TextOverlay
from . import theme
from .page_view import PageView, Tool
from .widgets import ColorButton, FontCombo, Segmented, section_title

TOOL_LABELS = {
    Tool.SELECT: "Sélection",
    Tool.TEXT: "Texte",
    Tool.RECT: "Rectangle",
    Tool.ELLIPSE: "Ellipse",
    Tool.LINE: "Ligne",
    Tool.ARROW: "Flèche",
    Tool.PEN: "Dessin libre",
    Tool.HIGHLIGHT: "Surligneur",
    Tool.REDACT: "Caviardage",
    Tool.PLACE: "Placement",
}

KIND_LABELS = {"text": "Texte", "box": "Forme", "line": "Ligne", "ink": "Dessin", "image": "Image"}

HINTS = {
    Tool.SELECT: "Cliquez sur un élément pour le modifier. Glissez pour sélectionner plusieurs éléments. "
    "Double-cliquez sur un texte pour l'éditer.",
    Tool.TEXT: "Cliquez sur la page pour écrire. Échap ou un clic ailleurs termine la saisie.",
    Tool.PEN: "Dessinez librement sur la page. Chaque trait reste modifiable.",
    Tool.HIGHLIGHT: "Glissez sur le texte à surligner.",
    Tool.REDACT: "Glissez sur la zone à masquer. À l'enregistrement, le texte et les images "
    "sous la zone sont définitivement supprimés du PDF.",
    Tool.LINE: "Glissez pour tracer. Maj : angles de 45°.",
    Tool.ARROW: "Glissez pour tracer. Maj : angles de 45°.",
    Tool.RECT: "Glissez pour dessiner. Maj : carré.",
    Tool.ELLIPSE: "Glissez pour dessiner. Maj : cercle.",
}


class StylePanel(QWidget):
    action_requested = Signal(str)  # "duplicate", "rotate", "delete", "front", "back"

    def __init__(self, view: PageView, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self.overlays: list[Overlay] = []
        self._loading = False
        self.setMinimumWidth(236)
        self.setMaximumWidth(300)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 4, 14, 14)
        root.setSpacing(10)
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 14px; font-weight: 600;")
        root.addWidget(self.title)
        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        # --- text
        self.text_box = QWidget()
        tf = QFormLayout(self.text_box)
        tf.setContentsMargins(0, 0, 0, 0)
        tf.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.font_combo = FontCombo()
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(4, 400)
        self.size_spin.setDecimals(1)
        self.size_spin.setSuffix(" pt")
        self.style_seg = QHBoxLayout()
        self.bold = QPushButton("G")
        self.italic = QPushButton("I")
        for b, css in ((self.bold, "font-weight: 700;"), (self.italic, "font-style: italic;")):
            b.setCheckable(True)
            b.setProperty("segment", True)
            b.setStyleSheet(css)
            b.setFixedWidth(36)
            self.style_seg.addWidget(b)
        self.style_seg.addStretch()
        self.bold.setToolTip("Gras")
        self.italic.setToolTip("Italique")
        self.align = Segmented([("left", "", "align-left"), ("center", "", "align-center"), ("right", "", "align-right")])
        self.text_color = ColorButton()
        tf.addRow(section_title("TEXTE"))
        tf.addRow("Police", self.font_combo)
        tf.addRow("Taille", self.size_spin)
        tf.addRow("Style", self.style_seg)
        tf.addRow("Alignement", self.align)
        tf.addRow("Couleur", self.text_color)
        root.addWidget(self.text_box)

        # --- stroke/fill
        self.shape_box = QWidget()
        sf = QFormLayout(self.shape_box)
        sf.setContentsMargins(0, 0, 0, 0)
        self.stroke = ColorButton(nullable=True)
        self.fill = ColorButton(nullable=True)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0, 40)
        self.width_spin.setDecimals(1)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setSuffix(" pt")
        sf.addRow(section_title("FORME"))
        self.stroke_label = QLabel("Contour")
        sf.addRow(self.stroke_label, self.stroke)
        self.fill_label = QLabel("Remplissage")
        sf.addRow(self.fill_label, self.fill)
        self.width_label = QLabel("Épaisseur")
        sf.addRow(self.width_label, self.width_spin)
        root.addWidget(self.shape_box)

        # --- opacity
        self.opacity_box = QWidget()
        of = QFormLayout(self.opacity_box)
        of.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity_val = QLabel()
        self.opacity_val.setMinimumWidth(36)
        row.addWidget(self.opacity)
        row.addWidget(self.opacity_val)
        of.addRow("Opacité", row)
        root.addWidget(self.opacity_box)

        # --- actions
        self.actions_box = QWidget()
        al = QVBoxLayout(self.actions_box)
        al.setContentsMargins(0, 6, 0, 0)
        al.setSpacing(6)
        al.addWidget(section_title("DISPOSITION"))
        r1 = QHBoxLayout()
        r2 = QHBoxLayout()
        for lay, items in (
            (r1, [("duplicate", "Dupliquer", "copy"), ("rotate", "Pivoter", "rotate-cw")]),
            (r2, [("front", "Devant", "chevron-up"), ("back", "Derrière", "chevron-down")]),
        ):
            for key, label, icon_name in items:
                b = QPushButton(theme.icon(icon_name, 16), label)
                b.clicked.connect(lambda _=False, k=key: self.action_requested.emit(k))
                lay.addWidget(b)
            al.addLayout(lay)
        self.delete_btn = QPushButton(theme.icon("trash-2", 16), "Supprimer")
        self.delete_btn.clicked.connect(lambda: self.action_requested.emit("delete"))
        al.addWidget(self.delete_btn)
        root.addWidget(self.actions_box)
        root.addStretch()

        self.font_combo.currentIndexChanged.connect(lambda _: self._apply("family", self.font_combo.family()))
        self.size_spin.valueChanged.connect(lambda v: self._apply("size_pt", v))
        self.bold.toggled.connect(lambda v: self._apply("bold", v))
        self.italic.toggled.connect(lambda v: self._apply("italic", v))
        self.align.changed.connect(lambda v: self._apply("align", v))
        self.text_color.color_changed.connect(lambda c: self._apply("color", c))
        self.stroke.color_changed.connect(lambda c: self._apply("stroke", c))
        self.fill.color_changed.connect(lambda c: self._apply("fill", c))
        self.width_spin.valueChanged.connect(lambda v: self._apply("width", v))
        self.opacity.valueChanged.connect(self._opacity_changed)

        view.selection_changed.connect(self.set_overlays)
        view.tool_changed.connect(lambda _t: self.set_overlays(view.selected_overlays()))
        view.overlay_geometry_changed.connect(self._refresh_size)
        self.set_overlays([])

    # ----------------------------------------------------------- context
    def _context_kinds(self) -> set[str]:
        if self.overlays:
            kinds = set()
            for ov in self.overlays:
                if isinstance(ov, BoxOverlay) and ov.shape in ("highlight", "redact"):
                    kinds.add(ov.shape)
                else:
                    kinds.add(ov.kind)
            return kinds
        t = self.view.tool
        return {
            Tool.TEXT: {"text"},
            Tool.RECT: {"box"},
            Tool.ELLIPSE: {"box"},
            Tool.LINE: {"line"},
            Tool.ARROW: {"line"},
            Tool.PEN: {"ink"},
            Tool.HIGHLIGHT: {"highlight"},
        }.get(t, set())

    def set_overlays(self, overlays: list[Overlay]) -> None:
        self.overlays = list(overlays)
        kinds = self._context_kinds()
        if self.overlays:
            if len(self.overlays) == 1:
                ov = self.overlays[0]
                label = {"highlight": "Surlignage", "redact": "Caviardage"}.get(
                    getattr(ov, "shape", ""), KIND_LABELS.get(ov.kind, "Élément")
                )
                self.title.setText(label)
            else:
                self.title.setText(f"{len(self.overlays)} éléments")
            self.hint.setText(
                "Glissez pour déplacer, utilisez les poignées pour redimensionner. Maj conserve les proportions."
                if len(self.overlays) == 1
                else ""
            )
        else:
            self.title.setText(TOOL_LABELS.get(self.view.tool, ""))
            self.hint.setText(HINTS.get(self.view.tool, ""))
        self.hint.setVisible(bool(self.hint.text()))

        has_text = "text" in kinds
        has_shape = bool(kinds & {"box", "line", "ink", "highlight"})
        self.text_box.setVisible(has_text)
        self.shape_box.setVisible(has_shape)
        only_box = kinds <= {"box"}
        self.fill.setVisible(only_box or kinds == {"highlight"})
        self.fill_label.setVisible(self.fill.isVisible())
        self.fill_label.setText("Couleur" if kinds == {"highlight"} else "Remplissage")
        stroke_vis = bool(kinds & {"box", "line", "ink"})
        self.stroke.setVisible(stroke_vis)
        self.stroke_label.setVisible(stroke_vis)
        self.stroke_label.setText("Couleur" if kinds <= {"line", "ink"} else "Contour")
        self.width_spin.setVisible(stroke_vis)
        self.width_label.setVisible(stroke_vis)
        self.opacity_box.setVisible(bool(kinds & {"text", "box", "line", "ink", "highlight"}))
        self.actions_box.setVisible(bool(self.overlays))
        self._load()

    def _load(self) -> None:
        self._loading = True
        d = self.view.defaults
        first = self.overlays[0] if self.overlays else None
        texts = [o for o in self.overlays if isinstance(o, TextOverlay)]
        t = texts[0] if texts else None
        self.font_combo.set_family(t.family if t else d.text_family)
        self.size_spin.setValue(t.size_pt if t else d.text_size)
        fam = FAMILIES.get(t.family if t else d.text_family)
        self.bold.setEnabled(bool(fam and fam.has_bold))
        self.italic.setEnabled(bool(fam and fam.has_italic))
        self.bold.setChecked(t.bold if t else d.text_bold)
        self.italic.setChecked(t.italic if t else d.text_italic)
        self.align.set_value(t.align if t else d.text_align)
        self.text_color.set_color(t.color if t else d.text_color)

        shapes = [o for o in self.overlays if isinstance(o, (BoxOverlay, LineOverlay, InkOverlay))]
        s = shapes[0] if shapes else None
        tool = self.view.tool
        if isinstance(s, BoxOverlay) and s.shape == "highlight" or (not s and tool == Tool.HIGHLIGHT):
            self.fill.set_color(s.fill if s else d.highlight_color)
            self.opacity.setValue(int(round((s.fill_opacity if s else 0.45) * 100)))
        elif isinstance(s, BoxOverlay):
            self.stroke.set_color(s.stroke)
            self.fill.set_color(s.fill)
            self.width_spin.setValue(s.width)
            self.opacity.setValue(int(round(s.opacity * 100)))
        elif isinstance(s, (LineOverlay, InkOverlay)):
            self.stroke.set_color(s.stroke)
            self.width_spin.setValue(s.width)
            self.opacity.setValue(int(round(s.opacity * 100)))
        elif tool == Tool.PEN:
            self.stroke.set_color(d.pen_color)
            self.width_spin.setValue(d.pen_width)
            self.opacity.setValue(int(round(d.pen_opacity * 100)))
        else:
            self.stroke.set_color(d.shape_stroke)
            self.fill.set_color(d.shape_fill)
            self.width_spin.setValue(d.shape_width)
            self.opacity.setValue(int(round(d.shape_opacity * 100)))
        if t and not s:
            self.opacity.setValue(int(round(t.opacity * 100)))
        self.stroke.nullable = not (isinstance(first, (LineOverlay, InkOverlay)) or tool in (Tool.LINE, Tool.ARROW, Tool.PEN))
        self.opacity_val.setText(f"{self.opacity.value()} %")
        self._loading = False

    def _refresh_size(self) -> None:
        texts = [o for o in self.overlays if isinstance(o, TextOverlay)]
        if texts:
            self._loading = True
            self.size_spin.setValue(texts[0].size_pt)
            self._loading = False

    # ------------------------------------------------------------- apply
    def _opacity_changed(self, v: int) -> None:
        self.opacity_val.setText(f"{v} %")
        self._apply("opacity", v / 100.0)

    def _apply(self, prop: str, value) -> None:
        if self._loading:
            return
        if prop == "family":
            fam = FAMILIES[value]
            self.bold.setEnabled(fam.has_bold)
            self.italic.setEnabled(fam.has_italic)
        self._update_defaults(prop, value)
        if not self.overlays:
            return
        model: DocumentModel = self.view.model

        def edit(ov: Overlay) -> None:
            if isinstance(ov, TextOverlay):
                if prop in ("family", "size_pt", "bold", "italic", "align", "color", "opacity"):
                    setattr(ov, prop, value)
            elif isinstance(ov, BoxOverlay):
                if ov.shape == "highlight":
                    if prop == "fill" and value:
                        ov.fill = value
                    elif prop == "opacity":
                        ov.fill_opacity = value
                elif ov.shape != "redact":
                    if prop in ("stroke", "fill", "width"):
                        setattr(ov, prop, value)
                    elif prop == "opacity":
                        ov.opacity = ov.fill_opacity = value
            elif isinstance(ov, (LineOverlay, InkOverlay)):
                if prop == "stroke" and value:
                    ov.stroke = value
                elif prop in ("width", "opacity"):
                    setattr(ov, prop, value)

        model.edit_overlays([o.uid for o in self.overlays], edit, merge=f"style:{prop}")
        # the model replaced nothing: overlays are edited in place
        self.view.sync_overlays()

    def _update_defaults(self, prop: str, value) -> None:
        d = self.view.defaults
        kinds = self._context_kinds()
        if "text" in kinds:
            mapping = {
                "family": "text_family",
                "size_pt": "text_size",
                "bold": "text_bold",
                "italic": "text_italic",
                "align": "text_align",
                "color": "text_color",
            }
            if prop in mapping:
                setattr(d, mapping[prop], value)
        if "highlight" in kinds and prop == "fill" and value:
            d.highlight_color = value
        if kinds & {"ink"} or self.view.tool == Tool.PEN:
            if prop == "stroke" and value:
                d.pen_color = value
            elif prop == "width":
                d.pen_width = value
            elif prop == "opacity":
                d.pen_opacity = value
        if kinds & {"box", "line"}:
            if prop == "stroke":
                d.shape_stroke = value
            elif prop == "fill":
                d.shape_fill = value
            elif prop == "width":
                d.shape_width = value
            elif prop == "opacity":
                d.shape_opacity = value
