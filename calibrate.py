#!/usr/bin/env python3
"""
Calibrazione visuale HS Arena Plus.
Mostra 3 sagome carta sovrapponibili allo screenshot.
Ogni sagoma include bordo, mana, titolo (dorato), testo, attacco, vita.
Salva solo le coordinate della fascia nome (usate dall'OCR).
"""
import json
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QBrush

SCREENSHOT_PATH = Path("/tmp/hs_calibration.png")
CALIBRATION_FILE = Path(__file__).parent / "calibration.json"
DISPLAY_MAX_W = 1400
DISPLAY_MAX_H = 850

# ── Proporzioni interne della card (frazioni di width/height del widget) ──────
CARD_ASPECT  = 0.714          # width / height ≈ 5:7
ART_FRAC     = (0.07, 0.07, 0.93, 0.54)
TITLE_FRAC   = (0.08, 0.52, 0.92, 0.62)   # fascia dorata → usata dall'OCR
DESC_FRAC    = (0.10, 0.64, 0.90, 0.83)
MANA_C       = (0.14, 0.12);  MANA_R  = 0.14   # cerchio mana (top-left)
ATK_C        = (0.13, 0.89);  ATK_R   = 0.13   # cerchio attacco (bottom-left)
HP_C         = (0.87, 0.89);  HP_R    = 0.13   # cerchio vita (bottom-right)
HANDLE_SIZE  = 16


def take_screenshot() -> bool:
    r = subprocess.run(['screencapture', '-x', str(SCREENSHOT_PATH)],
                       capture_output=True, timeout=5)
    return r.returncode == 0 and SCREENSHOT_PATH.exists()


class DraggableCard(QWidget):
    changed = pyqtSignal()

    _BORDER   = [QColor(255, 90, 90), QColor(70, 210, 90), QColor(80, 140, 255)]
    _LABELS   = ["Carta 1", "Carta 2", "Carta 3"]

    def __init__(self, index: int, parent: QWidget, x: int, y: int, w: int):
        super().__init__(parent)
        self._color = self._BORDER[index]
        self._label = self._LABELS[index]
        h = int(w / CARD_ASPECT)
        self.setGeometry(x, y, w, h)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_off = None
        self._resizing = False

    # ── geometry helpers ──────────────────────────────────────────────────────

    def _fr(self, fx0, fy0, fx1, fy1) -> QRect:
        w, h = self.width(), self.height()
        return QRect(int(fx0*w), int(fy0*h), int((fx1-fx0)*w), int((fy1-fy0)*h))

    def _fc(self, cx, cy, r) -> QRect:
        w, h = self.width(), self.height()
        rad = int(r * w)
        return QRect(int(cx*w)-rad, int(cy*h)-rad, 2*rad, 2*rad)

    def _handle_rect(self) -> QRect:
        s = HANDLE_SIZE
        return QRect(self.width()-s, self.height()-s, s, s)

    # ── drawing ───────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._color

        # Card border
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 25))
        p.setPen(QPen(c, 3))
        p.drawRoundedRect(1, 1, self.width()-2, self.height()-2, 10, 10)

        # Art frame
        p.setBrush(QColor(c.red(), c.green(), c.blue(), 35))
        p.setPen(QPen(c.lighter(140), 1))
        p.drawRect(self._fr(*ART_FRAC))

        # ── Title banner (dorato — area OCR) ──────────────────────────────────
        p.setBrush(QColor(255, 215, 0, 170))
        p.setPen(QPen(QColor(180, 140, 0), 2))
        p.drawRect(self._fr(*TITLE_FRAC))
        p.setPen(QColor(50, 25, 0))
        font_sz = max(7, self.width() // 18)
        p.setFont(QFont("SF Pro", font_sz, QFont.Weight.Bold))
        p.drawText(self._fr(*TITLE_FRAC), Qt.AlignmentFlag.AlignCenter, self._label)

        # Description box
        p.setBrush(QColor(255, 255, 240, 45))
        p.setPen(QPen(c.lighter(150), 1))
        p.drawRect(self._fr(*DESC_FRAC))

        # Mana circle (blue)
        p.setBrush(QColor(60, 80, 255, 200))
        p.setPen(QPen(QColor(30, 40, 180), 2))
        p.drawEllipse(self._fc(*MANA_C, MANA_R))

        # Attack circle (gold)
        p.setBrush(QColor(255, 200, 30, 210))
        p.setPen(QPen(QColor(160, 110, 0), 2))
        p.drawEllipse(self._fc(*ATK_C, ATK_R))

        # Health circle (red)
        p.setBrush(QColor(230, 50, 50, 210))
        p.setPen(QPen(QColor(160, 0, 0), 2))
        p.drawEllipse(self._fc(*HP_C, HP_R))

        # Resize handle
        p.setBrush(QColor(255, 255, 255, 200))
        p.setPen(QPen(QColor(80, 80, 80), 1))
        p.drawRect(self._handle_rect())

    # ── mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pt = e.position().toPoint()
            if self._handle_rect().contains(pt):
                self._resizing = True
            else:
                self._drag_off = pt
        e.accept()

    def mouseMoveEvent(self, e):
        pt = e.position().toPoint()
        if self._resizing:
            new_w = max(80, pt.x())
            new_h = int(new_w / CARD_ASPECT)
            par = self.parent()
            new_w = min(new_w, par.width() - self.x())
            new_h = min(new_h, par.height() - self.y())
            self.resize(new_w, new_h)
            self.changed.emit()
        elif self._drag_off:
            new_pos = self.pos() + (pt - self._drag_off)
            par = self.parent()
            new_pos.setX(max(0, min(new_pos.x(), par.width()  - self.width())))
            new_pos.setY(max(0, min(new_pos.y(), par.height() - self.height())))
            self.move(new_pos)
            self.changed.emit()
        self.setCursor(
            Qt.CursorShape.SizeFDiagCursor if self._handle_rect().contains(pt)
            else Qt.CursorShape.SizeAllCursor
        )

    def mouseReleaseEvent(self, _):
        self._drag_off = None
        self._resizing = False

    # ── export ────────────────────────────────────────────────────────────────

    def title_region(self, canvas_w: int, canvas_h: int) -> list:
        """Frazioni (x0,y0,x1,y1) della fascia nome rispetto al canvas intero."""
        tx0, ty0, tx1, ty1 = TITLE_FRAC
        w, h = self.width(), self.height()
        return [
            (self.x() + tx0 * w) / canvas_w,
            (self.y() + ty0 * h) / canvas_h,
            (self.x() + tx1 * w) / canvas_w,
            (self.y() + ty1 * h) / canvas_h,
        ]


class ScreenshotCanvas(QLabel):
    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.cards: list[DraggableCard] = []

    def add_card(self, c: DraggableCard):
        self.cards.append(c)

    def get_calibration(self) -> list:
        return [c.title_region(self.width(), self.height()) for c in self.cards]


class CalibrationWindow(QWidget):
    saved = pyqtSignal()

    def __init__(self, screenshot_path: str = None, window_owner: str = None):
        super().__init__()
        self._ss_path = screenshot_path or str(SCREENSHOT_PATH)
        self._window_owner = window_owner
        self.setWindowTitle("HS Arena Plus — Posiziona le zone carta")
        self.canvas = None
        self._build_ui()
        self._load_and_show()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        info = QLabel(
            "Trascina le <b>sagome carta</b> sopra i <b>nomi delle 3 carte</b> "
            "(angolo basso-destra per scalare). "
            "Il riquadro <b style='color:#d4a017'>dorato</b> è l'area letta dall'OCR. "
            "Poi clicca <b>✓ Salva</b>."
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#1a1a2e;color:#eee;padding:8px;border-radius:6px;")
        lay.addWidget(info)

        self._canvas_area = QWidget()
        self._canvas_layout = QHBoxLayout(self._canvas_area)
        self._canvas_layout.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._canvas_area)

        bot = QHBoxLayout()
        self._status = QLabel("")
        self._status.setStyleSheet("color:#aaa;")
        bot.addWidget(self._status)
        bot.addStretch()

        btn_new = QPushButton("Nuovo screenshot")
        btn_new.clicked.connect(self._retake)
        bot.addWidget(btn_new)

        btn_save = QPushButton("✓  Salva calibrazione")
        btn_save.setStyleSheet("background:#4CAF50;color:white;font-weight:bold;padding:6px 16px;")
        btn_save.clicked.connect(self._save)
        bot.addWidget(btn_save)

        lay.addLayout(bot)

    def _retake(self):
        self._status.setText("Screenshot in corso...")
        QApplication.processEvents()
        if not take_screenshot():
            self._status.setText("ERRORE screenshot — Privacy → Registrazione schermo")
            return
        self._ss_path = str(SCREENSHOT_PATH)
        self._load_and_show()

    def _load_and_show(self):
        from PIL import Image
        try:
            img = Image.open(self._ss_path)
            orig_w, orig_h = img.size
        except Exception:
            self._status.setText(f"ERRORE: impossibile aprire {self._ss_path}")
            return

        scale = min(DISPLAY_MAX_W / orig_w, DISPLAY_MAX_H / orig_h, 1.0)
        disp_w = int(orig_w * scale)
        disp_h = int(orig_h * scale)

        pixmap = QPixmap(self._ss_path).scaled(
            disp_w, disp_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if self.canvas:
            self.canvas.setParent(None)
        self.canvas = ScreenshotCanvas(pixmap)

        # Default card size: ~18% of display width
        default_card_w = max(100, int(disp_w * 0.18))
        default_card_h = int(default_card_w / CARD_ASPECT)

        # Try to reconstruct positions from saved title regions
        positions = self._positions_from_saved(disp_w, disp_h, default_card_w, default_card_h)

        colors = [QColor(255,90,90), QColor(70,210,90), QColor(80,140,255)]
        for i, (cx, cy, cw) in enumerate(positions):
            card = DraggableCard(i, self.canvas, cx, cy, cw)
            card.show()
            self.canvas.add_card(card)

        self._canvas_layout.addWidget(self.canvas)
        self._status.setText(
            f"{orig_w}×{orig_h}px — trascina i rettangoli sui nomi delle carte"
        )
        self.adjustSize()

    def _positions_from_saved(self, disp_w, disp_h, def_w, def_h):
        """Ricostruisce posizione/scala di ogni card dai titoli salvati."""
        if CALIBRATION_FILE.exists():
            try:
                data = json.loads(CALIBRATION_FILE.read_text())
                regions = data.get("regions", [])
                if len(regions) == 3:
                    result = []
                    tx0f, ty0f, tx1f, ty1f = TITLE_FRAC
                    for rx0, ry0, rx1, ry1 in regions:
                        title_w_px = (rx1 - rx0) * disp_w
                        card_w = int(title_w_px / (tx1f - tx0f))
                        card_h = int(card_w / CARD_ASPECT)
                        card_x = int(rx0 * disp_w - tx0f * card_w)
                        card_y = int(ry0 * disp_h - ty0f * card_h)
                        result.append((max(0, card_x), max(0, card_y), max(80, card_w)))
                    return result
            except Exception:
                pass
        # Default: 3 cards evenly placed in the lower-centre area
        spacing = disp_w // 4
        y = int(disp_h * 0.25)
        return [
            (int(disp_w * 0.12), y, def_w),
            (int(disp_w * 0.39), y, def_w),
            (int(disp_w * 0.64), y, def_w),
        ]

    def _save(self):
        if not self.canvas:
            return
        regions = self.canvas.get_calibration()
        data = {"regions": regions}
        if self._window_owner:
            data["window_owner"] = self._window_owner
            data["window_label"] = self._window_owner
        CALIBRATION_FILE.write_text(json.dumps(data, indent=2))
        self._status.setText(f"✓ Salvato — {CALIBRATION_FILE}")
        print(f"[calibrate] Salvato — {regions}")
        self.saved.emit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if not SCREENSHOT_PATH.exists():
        take_screenshot()
    w = CalibrationWindow()
    w.show()
    sys.exit(app.exec())
