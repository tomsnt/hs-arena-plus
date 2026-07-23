#!/usr/bin/env python3
"""
HS Arena Plus — main entry point.
Uses screenshot + OCR to detect cards in arena draft,
and shows a transparent overlay with tier ratings from HearthArena.

Usage:
    python main.py           # start normally
    python main.py --demo    # test overlay with fixed cards
"""
import sys
import threading
from ratings import load_card_db, load_ratings
from screen_watcher import ScreenWatcher
from overlay import run_overlay


def main():
    demo_mode = "--demo" in sys.argv

    card_db = {}
    ready_event = threading.Event()

    def preload():
        nonlocal card_db
        card_db = load_card_db()
        load_ratings()
        ready_event.set()
        print("[main] Data loaded. Waiting for arena events...")

    preload_thread = threading.Thread(target=preload, daemon=True)
    preload_thread.start()

    app, overlay = run_overlay()

    if demo_mode:
        demo_cards = ["TOY_504", "REV_956", "MAW_024"]  # S / A / F
        print(f"[main] DEMO MODE — cards: {demo_cards}")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(500, lambda: overlay.push_cards(demo_cards))
    else:
        def start_watcher():
            ready_event.wait()
            watcher = ScreenWatcher(
                on_cards=overlay.push_cards,
                on_draft_end=overlay.push_hide,
            )
            watcher.set_card_db(card_db)
            watcher.start()
            print("[main] Screen watcher started. Go to arena and pick your cards!")

        watcher_thread = threading.Thread(target=start_watcher, daemon=True)
        watcher_thread.start()

    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
