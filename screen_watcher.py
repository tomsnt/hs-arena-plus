"""
Screen-based watcher: finds the Hearthstone window via Quartz,
takes screenshots and OCRs card names during arena draft.
"""
import subprocess
import time
import threading
import difflib
import re
from pathlib import Path
from typing import Optional, List, Callable, Dict, Tuple

def log(msg: str):
    print(msg)
    try:
        from app import _log_bridge
        _log_bridge.message.emit(msg)
    except Exception:
        pass

from PIL import Image, ImageEnhance

SCREENSHOT_PATH = Path("/tmp/hs_arena_capture.png")
CROP_DEBUG_PATH = Path("/tmp/hs_arena_crop_{}.png")
POLL_INTERVAL = 2.0
CALIBRATION_FILE = Path(__file__).parent / "calibration.json"

# Fixed region for "Your Deck" panel (fraction of full screen)
DECK_REGION = (0.636, 0.085, 0.958, 0.83)

# Default: posizioni relative dei nomi carte (% schermo intero)
# Sovrascrivibile con calibrate.py
DEFAULT_REGIONS = [
    (0.08, 0.52, 0.38, 0.64),
    (0.37, 0.52, 0.65, 0.64),
    (0.64, 0.52, 0.93, 0.64),
]

# Default regions for hero class name text in hero selection screen
DEFAULT_HERO_REGIONS = [
    (0.08, 0.70, 0.33, 0.80),
    (0.37, 0.70, 0.62, 0.80),
    (0.65, 0.70, 0.90, 0.80),
]

CLASS_NORMALIZE = {
    "demon hunter": "DEMONHUNTER",
    "demonhunter": "DEMONHUNTER",
    "death knight": "DEATHKNIGHT",
    "deathknight": "DEATHKNIGHT",
    "druid": "DRUID",
    "hunter": "HUNTER",
    "mage": "MAGE",
    "paladin": "PALADIN",
    "priest": "PRIEST",
    "rogue": "ROGUE",
    "shaman": "SHAMAN",
    "warlock": "WARLOCK",
    "warrior": "WARRIOR",
}


def load_calibration():
    """Returns (regions, window_owner). window_owner None = full screen."""
    if CALIBRATION_FILE.exists():
        try:
            import json
            data = json.loads(CALIBRATION_FILE.read_text())
            regions = [tuple(r) for r in data.get("regions", [])]
            owner = data.get("window_owner")
            label = data.get("window_label", "full screen")
            if len(regions) == 3:
                log(f"[screen] Calibration loaded — window: {label}")
                return regions, owner
        except Exception:
            pass
    log("[screen] Using default regions — calibrate from app before starting")
    return DEFAULT_REGIONS, None


def load_hero_regions() -> list:
    if CALIBRATION_FILE.exists():
        try:
            import json
            data = json.loads(CALIBRATION_FILE.read_text())
            hero_regions = [tuple(r) for r in data.get("hero_regions", [])]
            if len(hero_regions) == 3:
                return hero_regions
        except Exception:
            pass
    return DEFAULT_HERO_REGIONS


def _match_class(text: str) -> Optional[str]:
    if not text:
        return None
    clean = re.sub(r"[^a-z ]", "", text.strip().lower()).strip()
    if clean in CLASS_NORMALIZE:
        return CLASS_NORMALIZE[clean]
    matches = difflib.get_close_matches(clean, list(CLASS_NORMALIZE.keys()), n=1, cutoff=0.70)
    if matches:
        return CLASS_NORMALIZE[matches[0]]
    return None


def load_regions():
    regions, _ = load_calibration()
    return regions


def check_dependencies() -> bool:
    if not _VISION_AVAILABLE:
        log("[screen] ERROR: Apple Vision not available (macOS 10.15+ required)")
        return False
    return True


def is_hearthstone_running() -> bool:
    r = subprocess.run(['pgrep', '-x', 'Hearthstone'], capture_output=True)
    return r.returncode == 0


def get_hearthstone_bounds() -> Optional[Tuple[int, int, int, int]]:
    """Trova la finestra Hearthstone usando Quartz (nessun permesso necessario)."""
    try:
        import Quartz
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID
        )
        for w in windows:
            owner = w.get('kCGWindowOwnerName', '')
            if 'Hearthstone' in owner:
                b = w.get('kCGWindowBounds', {})
                x = int(b.get('X', 0))
                y = int(b.get('Y', 0))
                w_ = int(b.get('Width', 0))
                h_ = int(b.get('Height', 0))
                if w_ > 200 and h_ > 200:
                    return (x, y, w_, h_)
    except ImportError:
        pass
    except Exception as e:
        log(f"[screen] Quartz error: {e}")
    return None


def take_screenshot(window_id: Optional[int] = None) -> Optional[Image.Image]:
    try:
        if window_id is not None:
            cmd = ['screencapture', '-x', '-l', str(window_id), str(SCREENSHOT_PATH)]
        else:
            cmd = ['screencapture', '-x', str(SCREENSHOT_PATH)]
        r = subprocess.run(cmd, capture_output=True, timeout=5)
        if r.returncode == 0 and SCREENSHOT_PATH.exists():
            img = Image.open(str(SCREENSHOT_PATH))
            img.load()
            return img
    except Exception as e:
        log(f"[screen] Screenshot error: {e}")
    return None


def crop_card_name(img: Image.Image, bounds: Tuple[int,int,int,int], region: Tuple, scale: float) -> Image.Image:
    """Ritaglia l'area del nome di una carta, tenendo conto del DPI Retina."""
    bx, by, bw, bh = bounds
    rx0, ry0, rx1, ry1 = region
    # Converti coordinate logiche → pixel screenshot (Retina = 2x)
    x0 = int((bx + bw * rx0) * scale)
    y0 = int((by + bh * ry0) * scale)
    x1 = int((bx + bw * rx1) * scale)
    y1 = int((by + bh * ry1) * scale)
    x0, x1 = max(0, x0), min(img.width, x1)
    y0, y1 = max(0, y0), min(img.height, y1)
    return img.crop((x0, y0, x1, y1))


def preprocess(img: Image.Image) -> Image.Image:
    img = img.convert('L')
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    return img


_VISION_AVAILABLE = False
try:
    import Vision as _Vision
    import Foundation as _Foundation
    _VISION_AVAILABLE = True
except ImportError:
    pass

_OCR_TMP = Path("/tmp/_hs_ocr_vision.png")


def _vision_ocr(img: Image.Image) -> str:
    """Apple Vision — returns the first recognized text line."""
    return next(iter(_vision_ocr_lines(img)), "")


def _vision_ocr_lines(img: Image.Image) -> List[str]:
    """Apple Vision — returns all recognized text lines."""
    img.save(str(_OCR_TMP))
    url = _Foundation.NSURL.fileURLWithPath_(str(_OCR_TMP))
    req = _Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(_Vision.VNRequestTextRecognitionLevelAccurate)
    req.setUsesLanguageCorrection_(False)
    handler = _Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    handler.performRequests_error_([req], None)
    return [obs.topCandidates_(1)[0].string()
            for obs in (req.results() or [])
            if obs.topCandidates_(1)[0].string()]


def ocr_card_name(img: Image.Image) -> str:
    try:
        return _vision_ocr(img)
    except Exception as e:
        log(f"[screen] Vision OCR error: {e}")
    return ""


def _clean_ocr(text: str) -> str:
    """Rimuove caratteri non-alfanumerici lasciando solo lettere, cifre, spazi, trattini."""
    cleaned = re.sub(r"[^A-Za-z0-9 '\-]", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def find_card_id(name_ocr: str, name_to_id: Dict[str, str], cutoff: float = 0.60) -> Optional[str]:
    if not name_ocr:
        return None
    cleaned = _clean_ocr(name_ocr)
    if not cleaned:
        return None
    cleaned_lower = cleaned.lower()
    # Match esatto (su testo pulito)
    for name, cid in name_to_id.items():
        if name.lower() == cleaned_lower:
            return cid
    names = list(name_to_id.keys())
    matches = difflib.get_close_matches(cleaned, names, n=1, cutoff=cutoff)
    if matches:
        return name_to_id[matches[0]], matches[0]
    return None


class ScreenWatcher:
    def __init__(self, on_cards: Callable, on_draft_end: Optional[Callable] = None,
                 on_heroes: Optional[Callable] = None):
        self.on_cards = on_cards
        self.on_draft_end = on_draft_end
        self.on_heroes = on_heroes
        self._stop = threading.Event()
        self._thread = None
        self._last_cards = None
        self._last_heroes: Optional[List] = None
        self._name_to_id: Dict[str, str] = {}
        # Retina scale: screenshot pixels / logical pixels
        self._scale: float = 2.0

    def set_card_db(self, card_db: dict):
        self._name_to_id = {}
        for card_id, card in card_db.items():
            name = card.get("name")
            if not name or len(card_id) >= 15 or card_id.isdigit():
                continue
            # Hero cards (e.g. "Qiu Niu Tsulong") never appear as arena draft choices
            if card.get("type") == "HERO":
                continue
            existing = self._name_to_id.get(name)
            if existing is None:
                self._name_to_id[name] = card_id
            else:
                # Prefer non-CORE IDs: ratings are indexed by original IDs (e.g. CFM_753 not CORE_CFM_753)
                if card_id.startswith("CORE_") and not existing.startswith("CORE_"):
                    continue
                if not card_id.startswith("CORE_") and existing.startswith("CORE_"):
                    self._name_to_id[name] = card_id
        log(f"[screen] Index: {len(self._name_to_id)} card names")

    def start(self):
        if not check_dependencies():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _detect_scale(self, img: Image.Image, bounds: Tuple) -> float:
        """Stima il fattore Retina confrontando dimensioni screenshot vs finestra."""
        _, _, bw, bh = bounds
        if bw > 0:
            return img.width / bw  # approssimazione usando larghezza schermo
        return 2.0

    def _grab_window(self, window_owner: Optional[str]) -> Optional[Image.Image]:
        """Screenshot schermo intero + ritaglio finestra (Metal/GPU-safe)."""
        img = take_screenshot(None)
        if img is None:
            log("[screen] Screenshot failed — add Terminal in Privacy → Screen Recording")
            return None
        if not window_owner:
            return img
        # Ritaglia alla finestra dell'app tramite Quartz
        try:
            import Quartz
            screen_w = Quartz.CGDisplayPixelsWide(Quartz.CGMainDisplayID())
            scale = img.width / screen_w
            wins = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListExcludeDesktopElements,
                Quartz.kCGNullWindowID)
            best_b, best_area = None, 0
            for w in wins:
                if w.get('kCGWindowOwnerName', '') == window_owner:
                    b = w.get('kCGWindowBounds', {})
                    ww = int(b.get('Width', 0))
                    hh = int(b.get('Height', 0))
                    if ww > 200 and hh > 200 and ww * hh > best_area:
                        best_b = b
                        best_area = ww * hh
            if best_b:
                ww = int(best_b.get('Width', 0))
                hh = int(best_b.get('Height', 0))
                x0 = int(best_b.get('X', 0) * scale)
                y0 = int(best_b.get('Y', 0) * scale)
                x1 = int((best_b.get('X', 0) + ww) * scale)
                y1 = int((best_b.get('Y', 0) + hh) * scale)
                x0 = max(0, x0); y0 = max(0, y0)
                x1 = min(img.width, x1); y1 = min(img.height, y1)
                cropped = img.crop((x0, y0, x1, y1))
                log(f"[screen] Cropped {window_owner}: {cropped.size}")
                return cropped
        except Exception as e:
            log(f"[screen] Quartz crop error: {e}")
        return img

    def _ocr_deck_panel(self, img: "Image.Image") -> List[str]:
        """OCR the 'Your Deck' right panel and return matched card IDs."""
        if not _VISION_AVAILABLE:
            return []
        try:
            rx0, ry0, rx1, ry1 = DECK_REGION
            x0 = int(rx0 * img.width)
            y0 = int(ry0 * img.height)
            x1 = int(rx1 * img.width)
            y1 = int(ry1 * img.height)
            crop = img.crop((x0, y0, x1, y1))
            lines = _vision_ocr_lines(crop)
            deck_ids: List[str] = []
            seen: set = set()
            for line in lines:
                # Strip leading mana-cost digit and "x2" count suffix
                clean = re.sub(r"^\d+\s+", "", line.strip())
                clean = re.sub(r"\s*[xX×]\d+\s*$", "", clean).strip()
                if len(clean) < 3:
                    continue
                # Stricter cutoff for deck panel: names are clearly printed in a list
                result = find_card_id(clean, self._name_to_id, cutoff=0.72)
                if result:
                    cid, matched = (result[0], result[1]) if isinstance(result, tuple) else (result, clean)
                    log(f"[deck] OCR '{clean}' → '{matched}'")
                    if cid not in seen:
                        seen.add(cid)
                        deck_ids.append(cid)
                else:
                    log(f"[deck] OCR '{clean}' → no match")
            return deck_ids
        except Exception as e:
            log(f"[screen] Deck OCR error: {e}")
            return []

    def _watch(self):
        regions, window_owner = load_calibration()
        log(f"[screen] Started — full screen regions")

        while not self._stop.is_set():
            # Use full-screen screenshot so calibration coordinates (drawn on full screen) match
            img = take_screenshot(None)
            if img is None:
                log("[screen] Screenshot failed — add Terminal in Privacy → Screen Recording")
                time.sleep(5)
                continue
            bounds = (0, 0, img.width, img.height)
            self._scale = 1.0

            # OCR i 3 nomi carte
            card_ids = []
            card_names = []
            for i, region in enumerate(regions):
                crop = crop_card_name(img, bounds, region, self._scale)
                debug_path = str(CROP_DEBUG_PATH).format(i)
                try:
                    crop.save(debug_path)
                except Exception:
                    pass
                proc = preprocess(crop)
                name_ocr = ocr_card_name(proc)
                log(f"[screen] Card {i+1} OCR: {name_ocr!r}")

                result = find_card_id(name_ocr, self._name_to_id)
                if result and isinstance(result, tuple):
                    cid, matched_name = result
                    card_ids.append(cid)
                    card_names.append(matched_name)
                elif isinstance(result, str):
                    card_ids.append(result)
                    card_names.append(name_ocr)

            log(f"[screen] Cards identified: {card_names}")

            # OCR deck panel
            deck_ids = self._ocr_deck_panel(img)
            log(f"[screen] Deck ({len(deck_ids)} cards): {deck_ids[:5]}{'…' if len(deck_ids)>5 else ''}")

            if len(card_ids) >= 3 and card_ids[:3] != self._last_cards:
                self._last_cards = card_ids[:3]
                self._last_heroes = None  # reset hero state when cards detected
                self.on_cards(card_ids[:3], deck_ids)
            elif len(card_ids) < 2 and self.on_heroes:
                heroes = self._detect_heroes(img, bounds)
                if heroes != self._last_heroes:
                    self._last_heroes = heroes
                    self.on_heroes(heroes)

            time.sleep(POLL_INTERVAL)

    def _detect_heroes(self, img, bounds) -> Optional[List]:
        """OCR hero name regions; returns [cls1, cls2, cls3] if ≥2 match known classes, else None."""
        hero_regions = load_hero_regions()
        classes = []
        for region in hero_regions:
            crop = crop_card_name(img, bounds, region, self._scale)
            proc = preprocess(crop)
            text = ocr_card_name(proc)
            cls = _match_class(text)
            log(f"[screen] Hero OCR: {text!r} → {cls}")
            classes.append(cls)
        found = [c for c in classes if c]
        if len(found) >= 2:
            return classes
        return None
