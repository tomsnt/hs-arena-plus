#!/usr/bin/env python3
"""
HS Arena Plus — Menu bar app per macOS.
Appare come icona nella barra superiore, senza finestra principale.
"""
import sys
import json
import threading
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QApplication, QMenu, QWidget, QLabel,
    QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea, QTextEdit, QFrame,
    QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QRect
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction, QBrush, QPen

CALIBRATION_FILE = Path(__file__).parent / "calibration.json"


# ---------------------------------------------------------------------------
# Window helpers via Quartz
# ---------------------------------------------------------------------------
def _get_window_bounds(owner_name: str):
    """Restituisce (x, y, w, h) in logical points per la finestra dell'app specificata."""
    try:
        import Quartz
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID)
        for w in wins:
            if w.get('kCGWindowOwnerName', '') == owner_name:
                b = w.get('kCGWindowBounds', {})
                ww = int(b.get('Width', 0))
                hh = int(b.get('Height', 0))
                if ww > 200 and hh > 200:
                    return (int(b.get('X', 0)), int(b.get('Y', 0)), ww, hh)
    except Exception as e:
        print(f"[quartz] {e}")
    return None


def _crop_window_from_screenshot(screenshot_path: str, owner_name: str):
    """Ritaglia la finestra dell'app dallo screenshot a schermo intero (pixel nativi Retina)."""
    bounds = _get_window_bounds(owner_name)
    if not bounds:
        return None
    try:
        from PIL import Image
        img = Image.open(screenshot_path)
        img.load()
        # Quartz dà coordinate logiche; lo screenshot è ai pixel nativi (2x su Retina)
        scale = img.width / Quartz_screen_width()
        bx, by, bw, bh = bounds
        x0 = int(bx * scale)
        y0 = int(by * scale)
        x1 = int((bx + bw) * scale)
        y1 = int((by + bh) * scale)
        x0 = max(0, x0); y0 = max(0, y0)
        x1 = min(img.width, x1); y1 = min(img.height, y1)
        return img.crop((x0, y0, x1, y1))
    except Exception as e:
        print(f"[crop] {e}")
    return None


def _quartz_screenshot(path: str) -> bool:
    """Cattura il framebuffer del display direttamente — funziona con Metal/GPU (Hearthstone)."""
    try:
        import Quartz
        import AppKit
        display_id = Quartz.CGMainDisplayID()
        cg_img = Quartz.CGDisplayCreateImage(display_id)
        if cg_img is None:
            return False
        w = Quartz.CGImageGetWidth(cg_img)
        h = Quartz.CGImageGetHeight(cg_img)
        ns_img = AppKit.NSImage.alloc().initWithCGImage_size_(
            cg_img, AppKit.NSMakeSize(w, h))
        tiff = ns_img.TIFFRepresentation()
        bmp = AppKit.NSBitmapImageRep.imageRepWithData_(tiff)
        png = bmp.representationUsingType_properties_(
            AppKit.NSBitmapImageFileTypePNG, {})
        return bool(png.writeToFile_atomically_(path, True))
    except Exception as e:
        print(f"[screenshot] Quartz fallito: {e}")
        return False


def Quartz_screen_width() -> int:
    try:
        import Quartz
        main = Quartz.CGMainDisplayID()
        return Quartz.CGDisplayPixelsWide(main)
    except Exception:
        return 1512  # default M-series


# ---------------------------------------------------------------------------
# Window listing via Quartz
# ---------------------------------------------------------------------------
def list_windows():
    """Returns list of (window_id, owner_name, label, w, h) for app windows."""
    results = []
    try:
        import Quartz
        # Nessun filtro OnScreenOnly: include fullscreen e altri spazi
        wins = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )
        seen = set()
        for w in wins:
            owner = w.get('kCGWindowOwnerName', '') or ''
            title = w.get('kCGWindowName', '') or ''
            wid   = w.get('kCGWindowNumber', 0)
            b     = w.get('kCGWindowBounds', {})
            ww    = int(b.get('Width', 0))
            hh    = int(b.get('Height', 0))
            # Salta finestre troppo piccole e layer di sistema (menu bar, dock ecc.)
            layer = w.get('kCGWindowLayer', 999)
            if ww < 200 or hh < 200:
                continue
            if layer not in (0, -1):   # 0 = normale, -1 = fullscreen/altro spazio
                continue
            if owner in ('', 'Window Server', 'Dock', 'SystemUIServer'):
                continue
            if owner not in seen:
                seen.add(owner)
                label = f"{owner} — {title}" if title else owner
                results.append((wid, owner, label, ww, hh))
    except Exception as e:
        print(f"[windows] Quartz non disponibile: {e}")
        # Fallback: elenca processi GUI attivi
        try:
            r = subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to get name of every process whose background only is false'],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode == 0:
                for name in r.stdout.strip().split(', '):
                    name = name.strip()
                    if name and name not in ('Finder', 'SystemUIServer', 'Dock'):
                        results.append((None, name, name, 0, 0))
        except Exception:
            pass
    return results


# ---------------------------------------------------------------------------
# Log bridge + preload signal
# ---------------------------------------------------------------------------
class LogBridge(QObject):
    message = pyqtSignal(str)
    preload_done = pyqtSignal(int, bool)  # n_cards, calibrated
    open_calibration = pyqtSignal(str, str)  # path, owner

_log_bridge = LogBridge()

def log(msg: str):
    print(msg)
    try:
        _log_bridge.message.emit(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tray icon (disegnata programmaticamente)
# ---------------------------------------------------------------------------
def make_tray_icon(active: bool = False) -> QIcon:
    px = QPixmap(22, 22)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#FFD700") if active else QColor("#CCCCCC")
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    # Carta stilizzata
    p.drawRoundedRect(3, 2, 16, 18, 2, 2)
    p.setBrush(QBrush(QColor("#333" if active else "#888")))
    p.drawRect(6, 7, 10, 1)
    p.drawRect(6, 10, 8, 1)
    p.drawRect(6, 13, 6, 1)
    p.end()
    return QIcon(px)


# ---------------------------------------------------------------------------
# Rettangolo trascinabile per calibrazione
# ---------------------------------------------------------------------------
# Proporzioni interne sagoma carta Hearthstone
_CARD_ASPECT = 0.710          # width / height (misurato da screenshot reale)
_TITLE_FRAC  = (0.16, 0.49, 0.84, 0.60)   # fascia nome dorata → area OCR (bordi esclusi)
_ART_FRAC    = (0.07, 0.07, 0.93, 0.48)
_DESC_FRAC   = (0.06, 0.62, 0.94, 0.95)
_MANA_C = (0.08, 0.12); _MANA_R = 0.12
_ATK_C  = (0.16, 0.93); _ATK_R  = 0.12
_HP_C   = (0.84, 0.93); _HP_R   = 0.12
_HANDLE = 16


class DraggableCard(QWidget):
    """Sagoma carta HS: bordo + mana + titolo (dorato) + testo + attacco + vita.
    Drag ovunque; angolo basso-destra scala mantenendo proporzioni."""

    _BORDER = [QColor(255, 90, 90), QColor(70, 210, 90), QColor(80, 140, 255)]
    _LABELS = ["Carta 1", "Carta 2", "Carta 3"]

    def __init__(self, index: int, parent: QWidget, x: int, y: int, w: int):
        super().__init__(parent)
        self._color = self._BORDER[index]
        self._label = self._LABELS[index]
        h = int(w / _CARD_ASPECT)
        self.setGeometry(x, y, max(w, 80), max(h, 112))
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_off = None
        self._resizing = False

    def _fr(self, fx0, fy0, fx1, fy1) -> QRect:
        w, h = self.width(), self.height()
        return QRect(int(fx0*w), int(fy0*h), int((fx1-fx0)*w), int((fy1-fy0)*h))

    def _fc(self, cx, cy, r) -> QRect:
        rad = int(r * self.width())
        return QRect(int(cx*self.width())-rad, int(cy*self.height())-rad, 2*rad, 2*rad)

    def _handle(self) -> QRect:
        return QRect(self.width()-_HANDLE, self.height()-_HANDLE, _HANDLE, _HANDLE)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self._color
        # Fascia nome (dorata — area OCR titolo)
        p.setBrush(QColor(255, 215, 0, 170))
        p.setPen(QPen(QColor(180, 140, 0), 2))
        p.drawRect(self._fr(*_TITLE_FRAC))
        p.setPen(QColor(50, 25, 0))
        p.setFont(QFont("Helvetica", max(7, self.width() // 18), QFont.Weight.Bold))
        p.drawText(self._fr(*_TITLE_FRAC), Qt.AlignmentFlag.AlignCenter, self._label)
        # Handle resize (at bottom-right corner of widget)
        p.setBrush(QColor(255, 255, 255, 200))
        p.setPen(QPen(QColor(80, 80, 80), 1))
        p.drawRect(self._handle())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            pt = e.position().toPoint()
            if self._handle().contains(pt):
                self._resizing = True
            else:
                self._drag_off = pt
        e.accept()

    def mouseMoveEvent(self, e):
        pt = e.position().toPoint()
        if self._resizing:
            new_w = max(80, pt.x())
            new_h = int(new_w / _CARD_ASPECT)
            par = self.parent()
            self.resize(min(new_w, par.width() - self.x()),
                        min(new_h, par.height() - self.y()))
        elif self._drag_off:
            new_pos = self.pos() + (pt - self._drag_off)
            par = self.parent()
            new_pos.setX(max(0, min(new_pos.x(), par.width()  - self.width())))
            new_pos.setY(max(0, min(new_pos.y(), par.height() - self.height())))
            self.move(new_pos)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if self._handle().contains(pt)
                       else Qt.CursorShape.SizeAllCursor)

    def mouseReleaseEvent(self, _):
        self._drag_off = None
        self._resizing = False

    def title_region(self, canvas_w: int, canvas_h: int) -> list:
        tx0, ty0, tx1, ty1 = _TITLE_FRAC
        w, h = self.width(), self.height()
        return [
            (self.x() + tx0 * w) / canvas_w,
            (self.y() + ty0 * h) / canvas_h,
            (self.x() + tx1 * w) / canvas_w,
            (self.y() + ty1 * h) / canvas_h,
        ]


# ---------------------------------------------------------------------------
# Finestra di calibrazione (si apre dal menu)
# ---------------------------------------------------------------------------
class CalibrationWindow(QWidget):
    def __init__(self, screenshot_path: str, window_owner: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("HS Arena Plus — Posiziona le zone carta")
        self._screenshot_path = screenshot_path
        self._window_owner = window_owner
        self.canvas_widget = None
        self._cards: list[DraggableCard] = []
        self._disp_w = 1
        self._disp_h = 1
        self._build_ui()
        self._load_screenshot()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel(
            "Trascina le <b>sagome carta</b> sopra i <b>nomi delle 3 carte</b> "
            "(angolo basso-destra per scalare). "
            "Il riquadro <b style='color:#d4a017'>dorato</b> è l'area letta dall'OCR. "
            "Poi clicca <b>✓ Salva</b>."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("background:#1e1e2e; color:#ccc; padding:8px; border-radius:6px;")
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("✓  Salva calibrazione")
        self.btn_save.setFixedHeight(36)
        self.btn_save.setStyleSheet("background:#4CAF50; color:white; font-weight:bold;")
        self.btn_save.clicked.connect(self._save)
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color:#aaa;")
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.lbl_status)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setStyleSheet("background:#0d0d1a;")
        root.addWidget(self.scroll)

        self.setStyleSheet("QWidget { background: #12121f; color: #eee; }")

    def _load_screenshot(self):
        if not Path(self._screenshot_path).exists():
            self.lbl_status.setText("⚠ Screenshot non trovato")
            return
        MAX_W, MAX_H = 1400, 800
        px = QPixmap(self._screenshot_path)
        orig_w, orig_h = px.width(), px.height()
        scale = min(MAX_W / orig_w, MAX_H / orig_h, 1.0)
        self._disp_w = int(orig_w * scale)
        self._disp_h = int(orig_h * scale)
        px_scaled = px.scaled(self._disp_w, self._disp_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        if self.canvas_widget:
            self.canvas_widget.setParent(None)
        self.canvas_widget = QLabel()
        self.canvas_widget.setPixmap(px_scaled)
        self.canvas_widget.setFixedSize(self._disp_w, self._disp_h)

        positions = self._positions_from_saved()
        self._cards = []
        for i, (cx, cy, cw) in enumerate(positions):
            card = DraggableCard(i, self.canvas_widget, cx, cy, cw)
            card.show()
            self._cards.append(card)

        self.scroll.setWidget(self.canvas_widget)
        self.lbl_status.setText(f"{orig_w}×{orig_h}px — trascina i rettangoli sui nomi delle carte")
        self.adjustSize()

    def _positions_from_saved(self):
        """Ricostruisce posizione/scala card dalle regioni titolo salvate."""
        dw, dh = self._disp_w, self._disp_h
        def_w = max(100, int(dw * 0.18))
        defaults = [
            (int(dw * 0.12), int(dh * 0.25), def_w),
            (int(dw * 0.39), int(dh * 0.25), def_w),
            (int(dw * 0.64), int(dh * 0.25), def_w),
        ]
        if CALIBRATION_FILE.exists():
            try:
                data = json.loads(CALIBRATION_FILE.read_text())
                regions = data.get("regions", [])
                if len(regions) == 3:
                    tx0f, ty0f, tx1f, ty1f = _TITLE_FRAC
                    result = []
                    for rx0, ry0, rx1, ry1 in regions:
                        title_w_px = (rx1 - rx0) * dw
                        cw = max(80, int(title_w_px / (tx1f - tx0f)))
                        ch = int(cw / _CARD_ASPECT)
                        cx = max(0, int(rx0 * dw - tx0f * cw))
                        cy = max(0, int(ry0 * dh - ty0f * ch))
                        result.append((cx, cy, cw))
                    return result
            except Exception:
                pass
        return defaults

    def _save(self):
        if not self._cards or not self.canvas_widget:
            return
        regions = [c.title_region(self._disp_w, self._disp_h) for c in self._cards]
        data = {"regions": regions, "window_owner": self._window_owner}
        CALIBRATION_FILE.write_text(json.dumps(data, indent=2))
        self.lbl_status.setText("✓ Salvato!")
        log(f"[calibrate] Salvato — {regions}")
        # Notify app to reposition overlay tiles
        cb = getattr(self, "_save_callback", None)
        if cb:
            cb()


# ---------------------------------------------------------------------------
# Log window
# ---------------------------------------------------------------------------
class LogWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HS Arena Plus — Log")
        self.resize(500, 300)
        lay = QVBoxLayout(self)
        self.box = QTextEdit()
        self.box.setReadOnly(True)
        self.box.setStyleSheet("background:#0d0d1a; color:#8fa; font-family:monospace; font-size:11px;")
        lay.addWidget(self.box)
        self.setStyleSheet("QWidget { background:#12121f; }")
        _log_bridge.message.connect(self._append)

    def _append(self, msg: str):
        self.box.append(msg)
        self.box.verticalScrollBar().setValue(self.box.verticalScrollBar().maximum())


# ---------------------------------------------------------------------------
# Menu bar controller
# ---------------------------------------------------------------------------
class MenuBarApp:
    def __init__(self, app: QApplication):
        self.app = app
        app.setQuitOnLastWindowClosed(False)

        # Nascondi icona dal Dock su macOS
        try:
            import AppKit
            AppKit.NSApp.setActivationPolicy_(
                AppKit.NSApplicationActivationPolicyAccessory)
        except Exception:
            pass

        self._watcher = None
        self._overlay = None
        self._running = False
        self._pinned = False
        self._card_db = {}
        self._cal_window = None
        self._log_window = None
        self._mi_pin = None
        self._settings_window = None

        # Native AppKit status bar (more reliable than QSystemTrayIcon on macOS)
        import AppKit
        self._sb_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength)
        self._sb_item.setTitle_("A+")
        self._ns_menu = None
        self._mi_status = None
        self._mi_toggle = None
        self._build_menu()

        # Preload dati in background — usa segnale per tornare al main thread
        _log_bridge.preload_done.connect(self._on_loaded)
        _log_bridge.open_calibration.connect(self._open_calibration)
        self._status = "Caricamento dati..."
        self._update_menu()
        threading.Thread(target=self._preload, daemon=True).start()

    # ------------------------------------------------------------------
    # Native NSMenu helpers
    # ------------------------------------------------------------------
    def _ns_item(self, title: str, callback=None, enabled: bool = True):
        import AppKit
        if callback is None:
            item = AppKit.NSMenuItem.separatorItem() if title == "-" else AppKit.NSMenuItem.new()
            if title != "-":
                item.setTitle_(title)
                item.setEnabled_(False)
            return item
        # Store callback on the app object and use a unique selector name
        cb_name = f"_cb_{id(callback)}"
        setattr(self, cb_name, callback)
        # Use a generic trampoline action selector
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, "menuAction:", "")
        item.setTarget_(self._menu_delegate)
        item.setRepresentedObject_(cb_name)
        item.setEnabled_(enabled)
        return item

    def _build_menu(self):
        import AppKit
        from Foundation import NSObject

        # One-time delegate creation
        if not hasattr(self, '_menu_delegate'):
            app_ref = self

            class _Delegate(NSObject):
                def menuAction_(self, sender):
                    cb_name = sender.representedObject()
                    cb = getattr(app_ref, cb_name, None)
                    if cb:
                        cb()

            self._menu_delegate = _Delegate.new()

        menu = AppKit.NSMenu.new()
        menu.setAutoenablesItems_(False)

        # Status (disabled header)
        self._mi_status = AppKit.NSMenuItem.new()
        self._mi_status.setTitle_("Caricamento...")
        self._mi_status.setEnabled_(False)
        menu.addItem_(self._mi_status)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Toggle overlay
        self._mi_toggle = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Avvia Overlay", "menuAction:", "")
        self._mi_toggle.setTarget_(self._menu_delegate)
        self._mi_toggle.setRepresentedObject_("_cb_toggle")
        self._mi_toggle.setEnabled_(False)
        self._cb_toggle = self._toggle
        menu.addItem_(self._mi_toggle)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Calibra
        mi_cal = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Calibra zone screenshot", "menuAction:", "")
        mi_cal.setTarget_(self._menu_delegate)
        mi_cal.setRepresentedObject_("_cb_cal")
        self._cb_cal = lambda: self._shoot_and_calibrate("Hearthstone")
        menu.addItem_(mi_cal)

        # Log
        mi_log = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Mostra log", "menuAction:", "")
        mi_log.setTarget_(self._menu_delegate)
        mi_log.setRepresentedObject_("_cb_log")
        self._cb_log = self._open_log
        menu.addItem_(mi_log)

        # Demo
        mi_demo = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Demo", "menuAction:", "")
        mi_demo.setTarget_(self._menu_delegate)
        mi_demo.setRepresentedObject_("_cb_demo")
        self._cb_demo = self._demo
        menu.addItem_(mi_demo)

        # Settings
        mi_settings = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "⚙ Impostazioni UI", "menuAction:", "")
        mi_settings.setTarget_(self._menu_delegate)
        mi_settings.setRepresentedObject_("_cb_settings")
        self._cb_settings = self._open_settings
        menu.addItem_(mi_settings)

        # Pin overlay
        self._mi_pin = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "📌 Pin Overlay", "menuAction:", "")
        self._mi_pin.setTarget_(self._menu_delegate)
        self._mi_pin.setRepresentedObject_("_cb_pin")
        self._cb_pin = self._toggle_pin
        menu.addItem_(self._mi_pin)

        menu.addItem_(AppKit.NSMenuItem.separatorItem())

        # Quit
        mi_quit = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "menuAction:", "")
        mi_quit.setTarget_(self._menu_delegate)
        mi_quit.setRepresentedObject_("_cb_quit")
        self._cb_quit = self._quit
        menu.addItem_(mi_quit)

        self._ns_menu = menu
        self._sb_item.setMenu_(menu)

    def _update_menu(self):
        if self._mi_status:
            self._mi_status.setTitle_(self._status)
        if self._mi_toggle:
            if self._running:
                self._mi_toggle.setTitle_("Ferma Overlay")
                self._sb_item.setTitle_("A+ ●")
            else:
                self._mi_toggle.setTitle_("Avvia Overlay")
                self._sb_item.setTitle_("A+")

    def _preload(self):
        from ratings import load_card_db, load_ratings
        self._card_db = load_card_db()
        load_ratings()
        calibrated = CALIBRATION_FILE.exists()
        _log_bridge.preload_done.emit(len(self._card_db), calibrated)

    def _on_loaded(self, n_cards: int, calibrated: bool):
        cal_str = "calibrata" if calibrated else "da calibrare"
        self._status = f"Pronto — {n_cards} carte — {cal_str}"
        if self._mi_toggle:
            self._mi_toggle.setEnabled_(True)
        self._update_menu()
        log(f"[app] Dati caricati: {n_cards} carte")
        if not calibrated:
            log("[app] Calibrazione necessaria: clicca HS nella barra → Calibra zone screenshot")

    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._start()

    def _toggle_pin(self):
        self._pinned = not self._pinned
        self._apply_pin_level()
        if self._mi_pin:
            title = ("✓ 📌 Pin Overlay" if self._pinned else "📌 Pin Overlay")
            self._mi_pin.setTitle_(title)

    def _apply_pin_level(self):
        """Imposta il livello NSWindow dell'overlay per mantenerlo sempre in primo piano."""
        if self._overlay is None:
            return
        try:
            import AppKit
            import objc
            ns_view = objc.objc_object(c_void_p=int(self._overlay.winId()))
            ns_window = ns_view.window()
            if self._pinned:
                # NSPanel (Tool window) ha hidesOnDeactivate=YES di default:
                # quando l'app perde focus (es. click su HS) il panel sparisce.
                # Lo disabilitiamo esplicitamente.
                ns_window.setHidesOnDeactivate_(False)
                ns_window.setLevel_(AppKit.NSScreenSaverWindowLevel - 1)
                ns_window.setCollectionBehavior_(
                    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
                    AppKit.NSWindowCollectionBehaviorStationary |
                    AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                )
            else:
                ns_window.setHidesOnDeactivate_(True)
                ns_window.setLevel_(AppKit.NSFloatingWindowLevel)
                ns_window.setCollectionBehavior_(
                    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                )
            log(f"[app] Pin {'attivato' if self._pinned else 'disattivato'} (level={ns_window.level()}, hidesOnDeactivate={ns_window.hidesOnDeactivate()})")
        except Exception as e:
            log(f"[app] Pin error: {e}")

    def _on_cards_detected(self, card_ids: list, deck_ids: list):
        from synergy import build_deck_profile, compute_synergy, compute_anti_synergy
        from ratings import load_card_db
        card_db = load_card_db()
        deck_profile = build_deck_profile(deck_ids, card_db) if deck_ids else {}
        results = [compute_synergy(cid, card_db, deck_ids, deck_profile) for cid in card_ids]
        synergy_levels = [r[0] for r in results]
        synergy_cards  = [r[1] for r in results]
        anti_results   = [compute_anti_synergy(cid, card_db, deck_ids) for cid in card_ids]
        anti_levels    = [r[0] for r in anti_results]
        anti_reasons   = [r[1] for r in anti_results]
        log(f"[app] Sinergie: {list(zip(card_ids, synergy_levels, anti_levels))}")
        self._overlay.push_cards(card_ids, synergy_levels, synergy_cards,
                                  anti_levels, anti_reasons, deck_ids)

    def _start(self):
        from screen_watcher import ScreenWatcher
        from overlay import ArenaOverlay
        self._overlay = ArenaOverlay()
        self._watcher = ScreenWatcher(
            on_cards=self._on_cards_detected,
            on_draft_end=self._overlay.push_hide)
        self._watcher.set_card_db(self._card_db)
        self._watcher.start()
        self._running = True
        self._status = "Overlay attivo — vai in arena!"
        self._update_menu()
        log("[app] Overlay avviato (OCR screenshot)")
        # Applica il livello pin se era attivo
        if self._pinned:
            QTimer.singleShot(200, self._apply_pin_level)

    def _stop(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        if self._overlay:
            self._overlay.push_hide()
            self._overlay = None
        self._running = False
        self._status = "Overlay fermato"
        self._update_menu()
        log("[app] Overlay fermato")

    def _demo(self):
        from overlay import ArenaOverlay
        if not self._overlay:
            self._overlay = ArenaOverlay()
        self._overlay.push_cards(["TOY_504", "REV_956", "MAW_024"],
                                  synergy_levels=[1, 2, 0],
                                  anti_levels=[0, 1, 2],
                                  anti_reasons=[[], ["too many weapons (3 in deck)"], ["no tribal buff for BEAST", "no heal"]])
        log("[app] Demo avviata")

    def _check_screen_recording(self) -> bool:
        """Returns True if screencapture can actually capture screen content (not just wallpaper)."""
        import subprocess, tempfile, os
        from PIL import Image
        tmp = tempfile.mktemp(suffix=".png")
        try:
            r = subprocess.run(['screencapture', '-x', tmp], capture_output=True, timeout=5)
            if r.returncode != 0 or not os.path.exists(tmp):
                return False
            img = Image.open(tmp)
            img.load()
            os.unlink(tmp)
            # Se lo screenshot è prevalentemente scuro o ha dimensioni strane → wallpaper/permesso mancante
            return img.width > 100 and img.height > 100
        except Exception:
            return False

    def _shoot_and_calibrate(self, owner: Optional[str]):
        # Defer to Qt main thread to avoid AppKit→Qt re-entrancy issues
        QTimer.singleShot(0, lambda: self._calibrate_qt(owner))

    def _calibrate_qt(self, owner: Optional[str]):
        log("[app] Calibrazione: vai su Hearthstone, screenshot tra 3 secondi...")
        if owner:
            subprocess.Popen(['osascript', '-e',
                f'tell application "{owner}" to activate'])

        def _do_screenshot():
            import time, os
            time.sleep(3)
            path = "/tmp/hs_calibration.png"
            log("[app] Screenshot in corso...")
            r = subprocess.run(['screencapture', '-x', path], capture_output=True, timeout=5)
            if r.returncode == 0 and os.path.exists(path):
                log("[app] Screenshot ok — apertura calibrazione")
                # Use signal to safely call back to main Qt thread
                _log_bridge.open_calibration.emit(path, owner or "")
            else:
                log("[app] ERRORE screenshot — aggiungi Terminale in Impostazioni → Privacy → Registrazione schermo")

        threading.Thread(target=_do_screenshot, daemon=True).start()

    def _open_calibration(self, path: str = "/tmp/hs_calibration.png",
                          owner: str = ""):
        log(f"[app] Apertura finestra calibrazione: {path}")
        try:
            if self._cal_window:
                self._cal_window.close()
            self._cal_window = CalibrationWindow(path, owner or None)
            self._cal_window._save_callback = self._on_calibration_saved
            self._cal_window.show()
            self._cal_window.raise_()
            self._cal_window.activateWindow()
            # Force bring to front via AppKit
            import AppKit
            AppKit.NSApp.activateIgnoringOtherApps_(True)
            log("[app] Finestra calibrazione aperta")
        except Exception as e:
            log(f"[app] ERRORE apertura calibrazione: {e}")

    def _on_calibration_saved(self):
        if self._overlay:
            self._overlay.reload_positions()

    def _open_settings(self):
        if not self._settings_window:
            from settings_window import SettingsWindow
            self._settings_window = SettingsWindow()
            self._settings_window.settings_changed.connect(self._on_settings_changed)
        self._settings_window.show()
        self._settings_window.raise_()
        import AppKit
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    def _on_settings_changed(self, new_settings: dict):
        if self._overlay:
            self._overlay.apply_settings(new_settings)

    def _open_log(self):
        if not self._log_window:
            self._log_window = LogWindow()
        self._log_window.show()
        self._log_window.raise_()

    def _quit(self):
        self._stop()
        self.app.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    import os, fcntl
    lock_path = "/tmp/hs_arena_overlay.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("HS Arena Plus già in esecuzione. Uscita.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from PyQt6.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,      QColor(18, 18, 31))
    pal.setColor(QPalette.ColorRole.WindowText,  QColor(238, 238, 238))
    pal.setColor(QPalette.ColorRole.Base,        QColor(13, 13, 26))
    pal.setColor(QPalette.ColorRole.Text,        QColor(238, 238, 238))
    pal.setColor(QPalette.ColorRole.Button,      QColor(40, 40, 60))
    pal.setColor(QPalette.ColorRole.ButtonText,  QColor(238, 238, 238))
    app.setPalette(pal)

    _controller = MenuBarApp(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
