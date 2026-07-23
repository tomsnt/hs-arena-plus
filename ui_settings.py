"""
Persistent UI settings with defaults.
Load once; access via get(). Save via save().
"""
import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "ui_settings.json"

DEFAULTS: dict = {
    # Layout
    "tile_height":    0,       # 0 = auto-fit to content; >0 = max height cap in px
    "tile_max_width": 0,      # 0 = no cap (uses calibrated card width)
    "tile_y_offset":  6,
    # Padding / spacing
    "margin_h":       9,
    "margin_v":       6,
    "spacing":        0,
    # Per-row vertical gaps (px)
    "gap_header_name":    3,
    "gap_name_stats":     1,
    "gap_stats_content":  3,
    "gap_curve_syn":      1,
    "gap_syn_title_cards": 0,
    # Header column split: tier label width as % of tile width (score fills the rest)
    "tier_col_pct":   35,
    # Deck rating widget position (% of screen width/height from top-left)
    "deck_x_pct":     82,
    "deck_y_pct":     4,
    # Deck rating widget colors
    "color_deck_bg":     "rgba(10,12,22,215)",
    "color_deck_border": "rgba(255,255,255,55)",
    # Font sizes (pt)
    "font_tier":      26,
    "font_score":     13,
    "font_name":      12,
    "font_stats":     11,
    "font_curve":     10,
    "font_syn_title": 9,
    "font_syn_cards": 9,
    # Colors (CSS strings accepted by Qt stylesheets)
    "color_bg":           "rgba(10,12,22,215)",
    "color_bg_best":      "rgba(10,25,12,220)",
    "color_border":       "rgba(255,255,255,55)",
    "color_border_best":  "rgba(76,175,80,210)",
    "color_score":        "rgba(255,255,255,200)",
    "color_stats":        "rgba(255,255,255,155)",
    "color_curve":        "rgba(100,220,120,210)",
    "color_syn_title":    "rgba(180,160,255,220)",
    "color_syn_cards":    "rgba(200,185,255,200)",
}

_current: dict = {}


def get() -> dict:
    global _current
    if not _current:
        load()
    return _current


def load() -> dict:
    global _current
    _current = dict(DEFAULTS)
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text())
            _current.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except Exception:
            pass
    return _current


def save(settings: dict):
    global _current
    _current = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    SETTINGS_FILE.write_text(json.dumps(_current, indent=2))
