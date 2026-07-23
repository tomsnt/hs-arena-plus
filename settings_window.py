"""
UI Settings panel — live preview while editing.
"""
import re
from typing import Callable

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QSpinBox, QPushButton, QLabel, QScrollArea, QFrame, QSizePolicy,
    QSlider, QColorDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

import ui_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_color(s: str) -> QColor:
    s = s.strip()
    m = re.match(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\s*\)', s)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = int(m.group(4)) if m.group(4) is not None else 255
        return QColor(r, g, b, a)
    c = QColor(s)
    return c if c.isValid() else QColor(128, 128, 128, 200)


def _color_to_str(c: QColor) -> str:
    if c.alpha() < 255:
        return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"
    return c.name()


# ---------------------------------------------------------------------------
# Slider widget (int value + live % label)
# ---------------------------------------------------------------------------

class SliderWidget(QWidget):
    value_changed = pyqtSignal(int)

    def __init__(self, mn: int, mx: int, suffix: str = "%", parent=None):
        super().__init__(parent)
        self._suffix = suffix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(mn, mx)
        self._slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px; background: #444; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; margin: -5px 0;
                background: #9090ff; border-radius: 7px;
            }
            QSlider::sub-page:horizontal { background: #6060cc; border-radius: 2px; }
        """)
        lay.addWidget(self._slider, 1)

        self._lbl = QLabel(f"{mn}{suffix}")
        self._lbl.setFixedWidth(36)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl.setStyleSheet("color: #ddd; font-size: 11px;")
        lay.addWidget(self._lbl)

        self._slider.valueChanged.connect(self._on_change)

    def _on_change(self, v: int):
        self._lbl.setText(f"{v}{self._suffix}")
        self.value_changed.emit(v)

    def value(self) -> int:
        return self._slider.value()

    def set_value(self, v: int):
        self._slider.setValue(int(v))


# ---------------------------------------------------------------------------
# Color picker button
# ---------------------------------------------------------------------------

class ColorButton(QPushButton):
    color_changed = pyqtSignal(str)

    def __init__(self, color_str: str, parent=None):
        super().__init__(parent)
        self._value = color_str
        self.setFixedSize(72, 26)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self):
        c = _parse_color(self._value)
        lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
        txt = "#000" if lum > 128 else "#fff"
        # Show hex + alpha hint
        label = f"α={c.alpha()}" if c.alpha() < 255 else c.name().upper()
        self.setText(label)
        self.setStyleSheet(
            f"background: {self._value}; color: {txt}; "
            f"border: 1px solid rgba(255,255,255,80); border-radius: 3px; font-size: 9px;"
        )

    def _pick(self):
        c = _parse_color(self._value)
        new_c = QColorDialog.getColor(
            c, self, "Scegli colore",
            QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if new_c.isValid():
            self._value = _color_to_str(new_c)
            self._refresh()
            self.color_changed.emit(self._value)

    def value(self) -> str:
        return self._value

    def set_value(self, s: str):
        self._value = s
        self._refresh()


# ---------------------------------------------------------------------------
# Settings window
# ---------------------------------------------------------------------------

class SettingsWindow(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HS Arena Plus — Impostazioni UI")
        self.setMinimumWidth(380)
        self._controls: dict = {}
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(80)
        self._debounce.timeout.connect(self._emit)
        self._build()
        self._load_values()
        self.setStyleSheet("QWidget { background: #12121f; color: #eee; }")

    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        root.addWidget(scroll)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        vlay = QVBoxLayout(inner)
        vlay.setContentsMargins(0, 0, 6, 0)
        vlay.setSpacing(10)
        scroll.setWidget(inner)

        # ── Layout group ─────────────────────────────────────────────────
        vlay.addWidget(self._group("Layout", [
            ("tile_height",        "Altezza max tile (px, 0=auto)", "int", 0, 400),
            ("tile_max_width",     "Larghezza max tile (px, 0=auto)", "int", 0, 800),
            ("tile_y_offset",      "Offset Y tile (px)",       "int",  -50, 200),
            ("margin_h",           "Margine orizzontale",      "int",    0,  60),
            ("margin_v",           "Margine verticale",        "int",    0,  60),
            ("spacing",            "Spaziatura base righe",    "int",    0,  30),
            ("gap_header_name",    "Gap header → nome",        "int",    0,  40),
            ("gap_name_stats",     "Gap nome → mana/tipo",     "int",    0,  40),
            ("gap_stats_content",    "Gap mana → curva/sinergie",   "int", 0, 40),
            ("gap_curve_syn",        "Gap curva → sinergie titolo", "int", 0, 40),
            ("gap_syn_title_cards",  "Gap titolo → lista sinergie", "int", 0, 40),
            ("tier_col_pct",         "Larghezza colonna tier",      "slider", 10, 90, "%"),
        ]))

        # ── Fonts group ───────────────────────────────────────────────────
        vlay.addWidget(self._group("Font (pt)", [
            ("font_tier",      "Tier (lettera)",   "int", 6, 60),
            ("font_score",     "Score",            "int", 6, 40),
            ("font_name",      "Nome carta",       "int", 6, 40),
            ("font_stats",     "Mana / tipo",      "int", 6, 40),
            ("font_curve",     "Nota curva",       "int", 6, 40),
            ("font_syn_title", "Sinergie titolo",  "int", 6, 30),
            ("font_syn_cards", "Sinergie lista",   "int", 6, 30),
        ]))

        # ── Deck widget group ─────────────────────────────────────────────
        vlay.addWidget(self._group("Deck Rating Widget", [
            ("deck_x_pct",       "Posizione X (% schermo)", "slider",  0, 100, "%"),
            ("deck_y_pct",       "Posizione Y (% schermo)", "slider",  0, 100, "%"),
            ("color_deck_bg",     "Sfondo",                 "color"),
            ("color_deck_border", "Bordo",                  "color"),
        ]))

        # ── Colors group ──────────────────────────────────────────────────
        vlay.addWidget(self._group("Colori tile", [
            ("color_bg",          "Sfondo tile"),
            ("color_bg_best",     "Sfondo migliore"),
            ("color_border",      "Bordo"),
            ("color_border_best", "Bordo migliore"),
            ("color_score",       "Testo score"),
            ("color_stats",       "Testo mana/tipo"),
            ("color_curve",       "Testo curva"),
            ("color_syn_title",   "Titolo sinergie"),
            ("color_syn_cards",   "Lista sinergie"),
        ]))

        vlay.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_reset = QPushButton("↺  Ripristina default")
        btn_reset.setFixedHeight(32)
        btn_reset.setStyleSheet(
            "background: #333; color: #ccc; border: 1px solid #555; border-radius: 4px;"
        )
        btn_reset.clicked.connect(self._reset)
        btn_save = QPushButton("✓  Salva")
        btn_save.setFixedHeight(32)
        btn_save.setStyleSheet(
            "background: #4CAF50; color: white; font-weight: bold; border-radius: 4px;"
        )
        btn_save.clicked.connect(self._save_and_close)
        btn_row.addWidget(btn_reset)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

    def _group(self, title: str, fields: list) -> QGroupBox:
        box = QGroupBox(title)
        box.setStyleSheet("""
            QGroupBox {
                color: #aaa; font-weight: bold;
                border: 1px solid rgba(255,255,255,40);
                border-radius: 6px; margin-top: 8px; padding-top: 4px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        """)
        form = QFormLayout(box)
        form.setContentsMargins(10, 14, 10, 10)
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        for row in fields:
            key = row[0]
            label = row[1]
            kind = row[2] if len(row) > 2 else "color"

            if kind == "int":
                mn, mx = row[3], row[4]
                ctrl = QSpinBox()
                ctrl.setRange(mn, mx)
                ctrl.setFixedWidth(72)
                ctrl.setStyleSheet(
                    "background: #1e1e38; color: #eee; border: 1px solid #444; border-radius: 3px;"
                )
                ctrl.valueChanged.connect(lambda _: self._debounce.start())
            elif kind == "slider":
                mn, mx = row[3], row[4]
                suffix = row[5] if len(row) > 5 else ""
                ctrl = SliderWidget(mn, mx, suffix)
                ctrl.value_changed.connect(lambda _: self._debounce.start())
            else:  # color
                ctrl = ColorButton(ui_settings.DEFAULTS[key])
                ctrl.color_changed.connect(lambda _: self._debounce.start())

            self._controls[key] = ctrl
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #ccc; font-weight: normal;")
            form.addRow(lbl, ctrl)

        return box

    # ------------------------------------------------------------------
    def _load_values(self):
        s = ui_settings.get()
        for key, ctrl in self._controls.items():
            v = s.get(key, ui_settings.DEFAULTS[key])
            if isinstance(ctrl, QSpinBox):
                ctrl.setValue(int(v))
            elif isinstance(ctrl, SliderWidget):
                ctrl.set_value(int(v))
            else:
                ctrl.set_value(str(v))

    def _collect(self) -> dict:
        result = {}
        for key, ctrl in self._controls.items():
            result[key] = ctrl.value()
        return result

    def _emit(self):
        self.settings_changed.emit(self._collect())

    def _reset(self):
        for key, ctrl in self._controls.items():
            d = ui_settings.DEFAULTS[key]
            if isinstance(ctrl, QSpinBox):
                ctrl.setValue(int(d))
            elif isinstance(ctrl, SliderWidget):
                ctrl.set_value(int(d))
            else:
                ctrl.set_value(str(d))

    def _save_and_close(self):
        s = self._collect()
        ui_settings.save(s)
        self.settings_changed.emit(s)
        self.hide()
