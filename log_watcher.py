"""
Log-based arena draft watcher for Hearthstone.
Monitors /Applications/Hearthstone/Logs/*/Arena.log in real time.
When a new set of 3 cards is offered, calls on_cards(card_ids).
"""
import re
import time
import threading
from pathlib import Path
from typing import Callable, Optional, List, Dict, Set

HS_LOGS = Path("/Applications/Hearthstone/Logs")

RE_DECK_ID  = re.compile(r"DraftManager\.OnChoicesAndContents - Draft Deck ID: (\d+)")
RE_CONTAINS = re.compile(r"DraftManager\.OnChoicesAndContents - Draft deck contains card (\S+)")
RE_SET_MODE = re.compile(r"SetDraftMode - DRAFTING")


def _log(msg: str):
    print(msg)
    try:
        from app import _log_bridge
        _log_bridge.message.emit(msg)
    except Exception:
        pass


def find_latest_arena_log() -> Optional[Path]:
    if not HS_LOGS.exists():
        return None
    candidates = sorted(
        HS_LOGS.glob("Hearthstone_*/Arena.log"),
        key=lambda p: p.stat().st_mtime
    )
    return candidates[-1] if candidates else None


class LogWatcher:
    def __init__(self, on_cards: Callable, on_draft_end: Optional[Callable] = None):
        self.on_cards     = on_cards
        self.on_draft_end = on_draft_end
        self._stop        = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Set of card IDs that are real collectible cards (not tokens)
        self._valid_ids: Set[str] = set()

    def set_card_db(self, card_db: dict):
        # A card is "valid" (pickable in arena) if it has a name and is collectible
        self._valid_ids = set()
        for card_id, card in card_db.items():
            if card.get("name") and card.get("collectible", True):
                self._valid_ids.add(card_id)
        _log(f"[log] Carte collezionabili: {len(self._valid_ids)}")

    def _is_real_card(self, card_id: str) -> bool:
        """Returns True if card_id is a real collectible card (not a token/transform)."""
        if self._valid_ids:
            return card_id in self._valid_ids
        # Fallback heuristic: token IDs often end in 't', 'e', or 'h' with a digit
        return not re.search(r't\d+$|e\d+$|h\d+$', card_id)

    def start(self):
        if not HS_LOGS.exists():
            _log(f"[log] Cartella log non trovata: {HS_LOGS}")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        _log("[log] Watcher avviato — attendo eventi arena...")

    def stop(self):
        self._stop.set()

    def _watch(self):
        current_log: Optional[Path] = None
        pos: int = 0
        # All card IDs seen so far (deck + previous choices); used for diffing
        seen_ids: Set[str] = set()
        last_emitted: List[str] = []

        while not self._stop.is_set():
            latest = find_latest_arena_log()

            if latest != current_log:
                current_log = latest
                pos = 0
                seen_ids = set()
                last_emitted = []
                if current_log:
                    _log(f"[log] Sessione: {current_log.parent.name}")
                else:
                    _log("[log] Nessun log arena — avvia Hearthstone")
                    time.sleep(3)
                    continue

            if not current_log or not current_log.exists():
                time.sleep(2)
                continue

            with open(current_log, "r", errors="replace") as f:
                f.seek(pos)
                new_data = f.read()
                pos = f.tell()

            if new_data:
                self._parse(new_data, seen_ids, last_emitted)

            time.sleep(0.4)

    def _parse(self, text: str, seen_ids: Set[str], last_emitted: List[str]):
        in_block = False
        block_cards: List[str] = []

        for line in text.splitlines():
            if RE_DECK_ID.search(line):
                in_block = True
                block_cards = []
                continue

            if in_block:
                m = RE_CONTAINS.search(line)
                if m:
                    block_cards.append(m.group(1))

            if in_block and RE_SET_MODE.search(line):
                self._process_block(block_cards, seen_ids, last_emitted)
                in_block = False
                block_cards = []

    def _process_block(self, block_cards: List[str], seen_ids: Set[str], last_emitted: List[str]):
        all_block = set(block_cards)

        if not seen_ids:
            # First block in session = deck contents on reconnect.
            # We can't determine current choices from this alone.
            # Mark everything as seen and wait for the user to make a pick.
            seen_ids.update(all_block)
            real_in_deck = [c for c in block_cards if self._is_real_card(c)]
            _log(f"[log] Stato iniziale — carte nel mazzo: {real_in_deck}")
            _log("[log] Fai una scelta in arena per vedere il suggerimento sul prossimo pick")
            return

        # Subsequent blocks: diff to find new cards
        new_ids = [c for c in block_cards if c not in seen_ids]
        new_real = [c for c in new_ids if self._is_real_card(c)]

        _log(f"[log] Nuovo blocco: +{len(new_ids)} IDs, +{len(new_real)} carte reali: {new_real}")

        if len(new_real) == 3:
            choices = new_real
        elif len(new_real) > 3:
            _log(f"[log] Attenzione: {len(new_real)} nuove carte reali (attese 3) — uso le prime 3")
            choices = new_real[:3]
        else:
            # 0, 1, or 2 new real cards — skip (pick confirmation or token update)
            seen_ids.update(all_block)
            return

        seen_ids.update(all_block)

        if choices != last_emitted:
            last_emitted.clear()
            last_emitted.extend(choices)
            _log(f"[log] Scelte per il prossimo pick: {choices}")
            self.on_cards(choices)
