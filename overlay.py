"""
Transparent full-screen overlay.
Each card tile is positioned directly below the corresponding arena card
using coordinates from calibration.json.
"""
import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QHBoxLayout, QVBoxLayout, QFrame,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QPainter, QColor

from ratings import get_card_info, TIER_COLORS
from synergy import synergy_suffix, curve_note
import ui_settings


# ---------------------------------------------------------------------------
# Custom progress bar for top-tier % display
# ---------------------------------------------------------------------------

class _TierBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 0
        self.setFixedHeight(6)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(sp)

    def set_pct(self, pct: int):
        self._pct = max(0, min(100, pct))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        # Track
        p.setBrush(QColor(255, 255, 255, 25))
        p.drawRoundedRect(0, 0, self.width(), self.height(), 3, 3)
        # Fill
        fill_w = max(0, int(self.width() * self._pct / 100))
        if fill_w:
            if self._pct >= 85:
                c = QColor("#4CAF50")   # green
            elif self._pct >= 70:
                c = QColor("#FFD700")   # gold
            elif self._pct >= 50:
                c = QColor("#FF6B35")   # orange
            else:
                c = QColor("#F44336")   # red
            p.setBrush(c)
            p.drawRoundedRect(0, 0, fill_w, self.height(), 3, 3)
        p.end()

CALIBRATION_FILE = Path(__file__).parent / "calibration.json"
# Must stay in sync with app.py constants
_TITLE_FRAC = (0.16, 0.49, 0.84, 0.60)
_CARD_ASPECT = 0.710


class Signals(QObject):
    update_cards = pyqtSignal(list, list, list, list, list, list)  # card_ids, syn_levels, syn_cards, anti_levels, anti_reasons, deck_ids
    hide_overlay = pyqtSignal()


# ---------------------------------------------------------------------------
# Deck rating widget (top-right corner)
# ---------------------------------------------------------------------------

class DeckRatingWidget(QWidget):
    """Small floating panel in the top-right corner showing the overall deck grade."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self.hide()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)

        header = QLabel("DECK")
        header.setFont(QFont("Helvetica", 9, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("color: rgba(255,255,255,120); margin: 0; padding: 0;")
        lay.addWidget(header)

        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFixedHeight(1)
        hline.setStyleSheet("background: rgba(255,255,255,35);")
        lay.addWidget(hline)

        self.grade_lbl = QLabel("–")
        self.grade_lbl.setFont(QFont("Helvetica", 30, QFont.Weight.Bold))
        self.grade_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.grade_lbl)

        self.score_lbl = QLabel("")
        self.score_lbl.setFont(QFont("Helvetica", 10))
        self.score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_lbl.setStyleSheet("color: rgba(255,255,255,170); margin: 0; padding: 0;")
        lay.addWidget(self.score_lbl)

        # ── Top-tier % section ────────────────────────────────────────────
        self._tier_div = QFrame()
        self._tier_div.setFrameShape(QFrame.Shape.HLine)
        self._tier_div.setFixedHeight(1)
        self._tier_div.setStyleSheet("background: rgba(255,255,255,25);")
        lay.addWidget(self._tier_div)

        tier_hdr = QLabel("TOP TIER")
        tier_hdr.setFont(QFont("Helvetica", 8, QFont.Weight.Bold))
        tier_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tier_hdr.setStyleSheet("color: rgba(255,255,255,80); margin: 0; padding: 0;")
        lay.addWidget(tier_hdr)
        self._tier_hdr = tier_hdr

        bar_row = QHBoxLayout()
        bar_row.setSpacing(5)
        bar_row.setContentsMargins(0, 2, 0, 2)
        self._tier_bar = _TierBar()
        bar_row.addWidget(self._tier_bar, 1)
        self._tier_pct_lbl = QLabel("–")
        self._tier_pct_lbl.setFont(QFont("Helvetica", 9, QFont.Weight.Bold))
        self._tier_pct_lbl.setFixedWidth(34)
        self._tier_pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._tier_pct_lbl.setStyleSheet("color: rgba(255,255,255,200);")
        bar_row.addWidget(self._tier_pct_lbl)
        lay.addLayout(bar_row)

        self._tier_div.hide()
        self._tier_hdr.hide()
        self._tier_bar.hide()
        self._tier_pct_lbl.hide()

        # ── Hints section ─────────────────────────────────────────────────
        self._hints_div = QFrame()
        self._hints_div.setFrameShape(QFrame.Shape.HLine)
        self._hints_div.setFixedHeight(1)
        self._hints_div.setStyleSheet("background: rgba(255,255,255,25);")
        lay.addWidget(self._hints_div)

        self.hints_lbl = QLabel("")
        self.hints_lbl.setFont(QFont("Helvetica", 9))
        self.hints_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.hints_lbl.setWordWrap(True)
        self.hints_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.hints_lbl)

        self._hints_div.hide()
        self.hints_lbl.hide()

        self.setFixedWidth(170)
        self._refresh_style()

    def _refresh_style(self):
        s = ui_settings.get()
        self.setStyleSheet(f"""
            DeckRatingWidget {{
                background: {s.get("color_deck_bg", "rgba(10,12,22,215)")};
                border: 2px solid {s.get("color_deck_border", "rgba(255,255,255,55)")};
                border-radius: 10px;
            }}
        """)

    def apply_settings(self):
        self._refresh_style()

    def update_deck(self, deck_ids: list, card_db: dict = None):
        from ratings import load_ratings, compute_top_tier_pct
        from synergy import compute_deck_hints
        ratings = load_ratings()
        scores = []
        for cid in deck_ids:
            r = ratings.get(cid)
            if r and r.get("score") is not None:
                scores.append(r["score"])

        if not scores:
            self.hide()
            return

        avg = sum(scores) / len(scores)

        hints, modifier = [], 0
        if card_db:
            hints, modifier = compute_deck_hints(deck_ids, card_db)

        final = avg + modifier

        if final >= 100:  tier = "SS"
        elif final >= 90: tier = "S"
        elif final >= 75: tier = "A"
        elif final >= 60: tier = "B"
        elif final >= 45: tier = "C"
        elif final >= 30: tier = "D"
        else:             tier = "F"

        color = TIER_COLORS.get(tier, "#9E9E9E")
        self.grade_lbl.setText(tier)
        self.grade_lbl.setStyleSheet(f"color: {color}; font-size: 30px; font-weight: bold;")

        mod_str = f" ({modifier:+d})" if modifier else ""
        self.score_lbl.setText(f"{avg:.0f}{mod_str}  ({len(scores)} carte)")

        # ── Top-tier % bar ────────────────────────────────────────────────
        pct = compute_top_tier_pct(deck_ids, card_db) if card_db else None
        if pct is not None:
            self._tier_bar.set_pct(pct)
            self._tier_pct_lbl.setText(f"{pct}%")
            # Color the % label to match the bar
            if pct >= 85:
                pct_color = "#4CAF50"
            elif pct >= 70:
                pct_color = "#FFD700"
            elif pct >= 50:
                pct_color = "#FF6B35"
            else:
                pct_color = "#F44336"
            self._tier_pct_lbl.setStyleSheet(f"color: {pct_color}; font-weight: bold;")
            self._tier_div.show()
            self._tier_hdr.show()
            self._tier_bar.show()
            self._tier_pct_lbl.show()
        else:
            self._tier_div.hide()
            self._tier_hdr.hide()
            self._tier_bar.hide()
            self._tier_pct_lbl.hide()

        # ── Hints ─────────────────────────────────────────────────────────
        if hints:
            is_positive = hints == ["well balanced"]
            hint_color = "#80e880" if is_positive else "rgba(255,200,100,220)"
            self.hints_lbl.setText("\n".join(f"· {h}" for h in hints))
            self.hints_lbl.setStyleSheet(f"color: {hint_color}; margin: 0; padding: 2px 0;")
            self._hints_div.show()
            self.hints_lbl.show()
        else:
            self._hints_div.hide()
            self.hints_lbl.hide()

        self.adjustSize()
        self.show()


# ---------------------------------------------------------------------------
# Spacer helper — a fixed-height invisible widget used as a row gap
# ---------------------------------------------------------------------------

class _Gap(QWidget):
    def __init__(self, h: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(h)
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setSizePolicy(sp)


# ---------------------------------------------------------------------------
# Card tile
# ---------------------------------------------------------------------------

class CardTile(QFrame):
    """Compact card tile: [Tier | Score] / Name / Mana•Type / Curve / Synergies"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_kwargs: dict = {}
        self._build()
        self.hide()

    # ── fixed size policy helper ──────────────────────────────────────────
    @staticmethod
    def _fixed_v(w: QWidget):
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        w.setSizePolicy(sp)

    def _build(self):
        s = ui_settings.get()
        root = QVBoxLayout(self)
        root.setContentsMargins(s["margin_h"], s["margin_v"], s["margin_h"], s["margin_v"])
        root.setSpacing(s["spacing"])

        # ── Row 1: Tier  |  Score ─────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 0, 0)

        self.tier_lbl = QLabel("?")
        self.tier_lbl.setFont(QFont("Helvetica", s["font_tier"], QFont.Weight.Bold))
        self.tier_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fixed_v(self.tier_lbl)
        top.addWidget(self.tier_lbl)

        vline = QFrame()
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setFixedWidth(1)
        vline.setStyleSheet("background: rgba(255,255,255,40);")
        top.addWidget(vline)

        self.score_lbl = QLabel("Score: –")
        self.score_lbl.setFont(QFont("Helvetica", s["font_score"]))
        self.score_lbl.setStyleSheet(f"color: {s['color_score']};")
        self.score_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._fixed_v(self.score_lbl)
        top.addWidget(self.score_lbl)

        # Apply initial column split via stretch factors
        pct = s["tier_col_pct"]
        top.setStretch(0, pct)
        top.setStretch(2, 100 - pct)

        self._top_layout = top
        root.addLayout(top)

        # ── Divider ───────────────────────────────────────────────────────
        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFixedHeight(1)
        hline.setStyleSheet("background: rgba(255,255,255,35);")
        root.addWidget(hline)

        # ── Gap 1 ─────────────────────────────────────────────────────────
        self._gap1 = _Gap(s["gap_header_name"])
        root.addWidget(self._gap1)

        # ── Row 2: Card name ──────────────────────────────────────────────
        self.name_lbl = QLabel("")
        self.name_lbl.setFont(QFont("Helvetica", s["font_name"], QFont.Weight.Bold))
        self.name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_lbl.setWordWrap(True)
        self.name_lbl.setStyleSheet("color: #FFFFFF; margin: 0; padding: 0;")
        root.addWidget(self.name_lbl)

        # ── Gap 2 ─────────────────────────────────────────────────────────
        self._gap2 = _Gap(s["gap_name_stats"])
        root.addWidget(self._gap2)

        # ── Row 3: Mana + type ────────────────────────────────────────────
        self.stats_lbl = QLabel("")
        self.stats_lbl.setFont(QFont("Helvetica", s["font_stats"]))
        self.stats_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats_lbl.setStyleSheet(f"color: {s['color_stats']}; margin: 0; padding: 0;")
        self._fixed_v(self.stats_lbl)
        root.addWidget(self.stats_lbl)

        # ── Gap 3 ─────────────────────────────────────────────────────────
        self._gap3 = _Gap(s["gap_stats_content"])
        root.addWidget(self._gap3)

        # ── Row 4: Curve note ─────────────────────────────────────────────
        self.curve_note_lbl = QLabel("")
        self.curve_note_lbl.setFont(QFont("Helvetica", s["font_curve"]))
        self.curve_note_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.curve_note_lbl.setStyleSheet(f"color: {s['color_curve']}; margin: 0; padding: 0;")
        self._fixed_v(self.curve_note_lbl)
        root.addWidget(self.curve_note_lbl)

        # ── Gap 4 ─────────────────────────────────────────────────────────
        self._gap4 = _Gap(s["gap_curve_syn"])
        root.addWidget(self._gap4)

        # ── Row 5: Synergy title ──────────────────────────────────────────
        self.syn_title_lbl = QLabel("Synergies:")
        self.syn_title_lbl.setFont(QFont("Helvetica", s["font_syn_title"], QFont.Weight.Bold))
        self.syn_title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.syn_title_lbl.setStyleSheet(f"color: {s['color_syn_title']}; margin: 0; padding: 0;")
        self._fixed_v(self.syn_title_lbl)
        root.addWidget(self.syn_title_lbl)

        # ── Gap 5 ─────────────────────────────────────────────────────────
        self._gap5 = _Gap(s["gap_syn_title_cards"])
        root.addWidget(self._gap5)

        # ── Row 6: Synergy card list ──────────────────────────────────────
        self.syn_cards_lbl = QLabel("")
        self.syn_cards_lbl.setFont(QFont("Helvetica", s["font_syn_cards"]))
        self.syn_cards_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.syn_cards_lbl.setWordWrap(True)
        self.syn_cards_lbl.setStyleSheet(f"color: {s['color_syn_cards']}; margin: 0; padding: 0;")
        root.addWidget(self.syn_cards_lbl)

        # ── Row 7: Anti-synergy title ─────────────────────────────────────
        self.anti_title_lbl = QLabel("Anti-sinergie:")
        self.anti_title_lbl.setFont(QFont("Helvetica", s["font_syn_title"], QFont.Weight.Bold))
        self.anti_title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.anti_title_lbl.setStyleSheet("color: rgba(255,100,80,220); margin: 0; padding: 0;")
        self._fixed_v(self.anti_title_lbl)
        root.addWidget(self.anti_title_lbl)

        # ── Row 8: Anti-synergy reason list ──────────────────────────────
        self.anti_cards_lbl = QLabel("")
        self.anti_cards_lbl.setFont(QFont("Helvetica", s["font_syn_cards"]))
        self.anti_cards_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.anti_cards_lbl.setWordWrap(True)
        self.anti_cards_lbl.setStyleSheet("color: rgba(255,140,110,200); margin: 0; padding: 0;")
        root.addWidget(self.anti_cards_lbl)
        # No stretch — height is determined by actual content

    def set_info(self, info: dict, is_best: bool, synergy_level: int = 0,
                 anti_level: int = 0, combined: int = None,
                 deck_profile: dict = None, synergy_cards: list = None,
                 anti_reasons: list = None):
        # Store for live-settings refresh
        self._last_kwargs = dict(
            info=info, is_best=is_best, synergy_level=synergy_level,
            anti_level=anti_level, combined=combined,
            deck_profile=deck_profile, synergy_cards=synergy_cards,
            anti_reasons=anti_reasons,
        )
        s = ui_settings.get()

        # Apply layout settings
        lay = self.layout()
        lay.setContentsMargins(s["margin_h"], s["margin_v"], s["margin_h"], s["margin_v"])
        lay.setSpacing(s["spacing"])

        # Update gap heights
        self._gap1.setFixedHeight(max(0, s["gap_header_name"]))
        self._gap2.setFixedHeight(max(0, s["gap_name_stats"]))
        self._gap3.setFixedHeight(max(0, s["gap_stats_content"]))
        self._gap4.setFixedHeight(max(0, s["gap_curve_syn"]))
        self._gap5.setFixedHeight(max(0, s["gap_syn_title_cards"]))

        # Update header column split
        pct = s["tier_col_pct"]
        self._top_layout.setStretch(0, pct)
        self._top_layout.setStretch(2, 100 - pct)

        # ── Tier label — fixed font size regardless of text length ─────────
        tier   = info.get("tier", "?")
        color  = TIER_COLORS.get(tier, "#9E9E9E")
        suffix = synergy_suffix(synergy_level, anti_level)
        tier_text = f"{tier}{suffix}"
        self.tier_lbl.setText(tier_text)
        self.tier_lbl.setFont(QFont("Helvetica", s["font_tier"], QFont.Weight.Bold))
        self.tier_lbl.setStyleSheet(f"color: {color}; font-weight: bold;")

        # ── Score ─────────────────────────────────────────────────────────
        base_score = info.get("winrate", "N/A")
        if combined is not None:
            score_text = str(combined)
            if base_score != "N/A":
                delta = combined - int(base_score)
                if delta > 0:
                    score_text += f" (+{delta})"
                elif delta < 0:
                    score_text += f" ({delta})"
        else:
            score_text = base_score if base_score != "N/A" else "N/A"
        self.score_lbl.setText(score_text)
        self.score_lbl.setFont(QFont("Helvetica", s["font_score"]))
        self.score_lbl.setStyleSheet(f"color: {s['color_score']};")

        # ── Name ──────────────────────────────────────────────────────────
        self.name_lbl.setText(info.get("name", ""))
        self.name_lbl.setFont(QFont("Helvetica", s["font_name"], QFont.Weight.Bold))

        # ── Stats ─────────────────────────────────────────────────────────
        cost  = info.get("cost", "?")
        ctype = info.get("type", "").capitalize()
        self.stats_lbl.setText(f"Mana: {cost}  •  {ctype}" if ctype else f"Mana: {cost}")
        self.stats_lbl.setFont(QFont("Helvetica", s["font_stats"]))
        self.stats_lbl.setStyleSheet(f"color: {s['color_stats']}; margin: 0; padding: 0;")

        # ── Curve note ────────────────────────────────────────────────────
        note = ""
        if deck_profile and deck_profile.get("total", 0) > 0:
            try:
                cost_int = int(cost)
            except (ValueError, TypeError):
                cost_int = 0
            note = curve_note(deck_profile, cost_int)
        self.curve_note_lbl.setText(note)
        self.curve_note_lbl.setFont(QFont("Helvetica", s["font_curve"]))
        self.curve_note_lbl.setStyleSheet(f"color: {s['color_curve']}; margin: 0; padding: 0;")
        self.curve_note_lbl.setVisible(bool(note))

        # ── Synergy card list ─────────────────────────────────────────────
        names = synergy_cards or []
        self.syn_title_lbl.setFont(QFont("Helvetica", s["font_syn_title"], QFont.Weight.Bold))
        self.syn_title_lbl.setStyleSheet(f"color: {s['color_syn_title']}; margin: 0; padding: 0;")
        self.syn_cards_lbl.setFont(QFont("Helvetica", s["font_syn_cards"]))
        self.syn_cards_lbl.setStyleSheet(f"color: {s['color_syn_cards']}; margin: 0; padding: 0;")

        if names:
            self.syn_cards_lbl.setText("\n".join(f"· {n}" for n in names))
            self.syn_title_lbl.show()
            self.syn_cards_lbl.show()
        else:
            self.syn_title_lbl.hide()
            self.syn_cards_lbl.hide()

        # ── Anti-synergy reasons ──────────────────────────────────────────
        self.anti_title_lbl.setFont(QFont("Helvetica", s["font_syn_title"], QFont.Weight.Bold))
        self.anti_cards_lbl.setFont(QFont("Helvetica", s["font_syn_cards"]))
        reasons = anti_reasons or []
        if reasons:
            self.anti_cards_lbl.setText("\n".join(f"· {r}" for r in reasons))
            self.anti_title_lbl.show()
            self.anti_cards_lbl.show()
        else:
            self.anti_title_lbl.hide()
            self.anti_cards_lbl.hide()

        # ── Background / border ───────────────────────────────────────────
        border = s["color_border_best"] if is_best else s["color_border"]
        bg     = s["color_bg_best"]     if is_best else s["color_bg"]
        self.setStyleSheet(f"""
            CardTile {{
                background: {bg};
                border: 2px solid {border};
                border-radius: 10px;
            }}
        """)

        # Resize to content; respect optional max-height cap
        self.setMaximumHeight(16777215)
        self.adjustSize()
        max_h = s.get("tile_height", 0)
        if max_h and max_h > 0:
            self.setMaximumHeight(max_h)

        self.show()

    def apply_settings(self):
        """Re-render with stored card data using current settings."""
        if self._last_kwargs:
            self.set_info(**self._last_kwargs)


# ---------------------------------------------------------------------------
# Main overlay window
# ---------------------------------------------------------------------------

class ArenaOverlay(QWidget):
    """Full-screen transparent window; tiles are absolute-positioned children."""

    def __init__(self):
        super().__init__()
        self.signals = Signals()
        self.signals.update_cards.connect(self._on_update)
        self.signals.hide_overlay.connect(self._hide_all)
        self._setup_window()
        self._tiles = [CardTile(self), CardTile(self), CardTile(self)]
        self._deck_widget = DeckRatingWidget(self)
        self.reload_positions()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    def reload_positions(self):
        """Recalculate tile positions from calibration.json (call after recalibration too)."""
        screen = QApplication.primaryScreen().geometry()
        sw, sh = screen.width(), screen.height()
        tx0, _, tx1, ty1 = _TITLE_FRAC
        s = ui_settings.get()
        y_off = s["tile_y_offset"]

        regions = []
        try:
            data = json.loads(CALIBRATION_FILE.read_text())
            regions = data.get("regions", [])
        except Exception:
            pass

        if len(regions) != 3:
            tile_w = 190
            max_w = s["tile_max_width"]
            if max_w and max_w > 0:
                tile_w = min(tile_w, max_w)
            for i, tile in enumerate(self._tiles):
                x = int(sw * (0.18 + i * 0.27)) - tile_w // 2
                y = int(sh * 0.63)
                tile.setFixedWidth(tile_w)
                tile.move(x, y)
        else:
            for i, (rx0, _, rx1, ry1) in enumerate(regions):
                strip_w = (rx1 - rx0) * sw
                card_w  = strip_w / (tx1 - tx0)
                card_h  = card_w / _CARD_ASPECT

                card_bottom = ry1 * sh + (1.0 - ty1) * card_h
                card_cx = (rx0 + rx1) / 2.0 * sw

                tile_w = int(card_w)
                max_w = s["tile_max_width"]
                if max_w and max_w > 0:
                    tile_w = min(tile_w, max_w)
                tile_x = int(card_cx - tile_w / 2)
                tile_y = int(card_bottom) + y_off

                tile_x = max(0, min(tile_x, sw - tile_w))
                tile_y = max(0, min(tile_y, sh - 50))

                self._tiles[i].setFixedWidth(tile_w)
                self._tiles[i].move(tile_x, tile_y)

        # Deck rating widget: fixed width, dynamic height → use move() not setGeometry()
        dw_w = 170
        dw_x = max(0, min(int(sw * s["deck_x_pct"] / 100), sw - dw_w))
        dw_y = max(0, min(int(sh * s["deck_y_pct"] / 100), sh - 300))
        self._deck_widget.setFixedWidth(dw_w)
        self._deck_widget.move(dw_x, dw_y)

    def apply_settings(self, new_settings: dict = None):
        """Apply (possibly new) settings and refresh all visible tiles."""
        if new_settings is not None:
            ui_settings._current = {k: new_settings.get(k, ui_settings.DEFAULTS[k])
                                     for k in ui_settings.DEFAULTS}
        s = ui_settings.get()
        pct = s["tier_col_pct"]
        self.reload_positions()
        self._deck_widget.apply_settings()
        for tile in self._tiles:
            # Always update column split, even on tiles with no cached card data
            tile._top_layout.setStretch(0, pct)
            tile._top_layout.setStretch(2, 100 - pct)
            tile.apply_settings()

    def _on_update(self, cards: list, synergy_levels: list, synergy_cards_list: list,
                   anti_levels: list, anti_reasons_list: list, deck_ids: list):
        from synergy import build_deck_profile, combined_score
        from ratings import load_card_db
        card_db = load_card_db()
        deck_profile = build_deck_profile(deck_ids, card_db) if deck_ids else {}

        infos = [get_card_info(cid) for cid in cards]
        combineds = []
        for i, info in enumerate(infos):
            base = info.get("score")
            syn  = synergy_levels[i] if i < len(synergy_levels) else 0
            anti = anti_levels[i]    if i < len(anti_levels)    else 0
            combineds.append(combined_score(base, syn, anti))

        def sort_key(i):
            c = combineds[i]
            if c is not None:
                return c
            return {"SS": 7, "S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}.get(
                infos[i].get("tier", ""), 0
            )

        best = max(range(len(infos)), key=sort_key)

        for i, (tile, info) in enumerate(zip(self._tiles, infos)):
            syn     = synergy_levels[i]    if i < len(synergy_levels)    else 0
            anti    = anti_levels[i]       if i < len(anti_levels)       else 0
            scards  = synergy_cards_list[i] if i < len(synergy_cards_list) else []
            areasons = anti_reasons_list[i] if i < len(anti_reasons_list) else []
            tile.set_info(info, is_best=(i == best),
                          synergy_level=syn, anti_level=anti,
                          combined=combineds[i],
                          deck_profile=deck_profile,
                          synergy_cards=scards,
                          anti_reasons=areasons)

        if deck_ids:
            self._deck_widget.update_deck(deck_ids, card_db)

        self.show()
        self.raise_()

    def _hide_all(self):
        for t in self._tiles:
            t.hide()
        self._deck_widget.hide()

    def push_cards(self, card_ids: list, synergy_levels: list = None,
                   synergy_cards: list = None, anti_levels: list = None,
                   anti_reasons: list = None, deck_ids: list = None):
        self.signals.update_cards.emit(
            card_ids,
            synergy_levels or [0, 0, 0],
            synergy_cards  or [[], [], []],
            anti_levels    or [0, 0, 0],
            anti_reasons   or [[], [], []],
            deck_ids or []
        )

    def push_hide(self):
        self.signals.hide_overlay.emit()
