# HS Arena Plus

macOS overlay for Hearthstone Arena draft. Shows card ratings, synergies, deck hints and top-tier comparison in real time.

![macOS](https://img.shields.io/badge/macOS-10.15+-blue) ![Python](https://img.shields.io/badge/Python-3.9+-green)

## Features

- **Card ratings** from HearthArena (tier S+ → F, score 0-100)
- **Synergy detection** with cards already in your deck
- **Deck hints** — missing removal, curve gaps, low card draw, no late game threats
- **Top Tier %** bar comparing your deck to HSReplay arena stats
- **Apple Vision OCR** — reads card names directly from the screen, no game files needed

## Requirements

- macOS 10.15 (Catalina) or later
- Python 3.9+
- Hearthstone running in windowed or fullscreen mode

## Quick Install (Terminal)

```bash
git clone https://github.com/tomsnt/hs-arena-plus.git
cd hs-arena-plus
bash install.sh
```

Then launch:
```bash
source .venv/bin/activate
python main.py
```

## Easy Install (DMG)

Download the latest `HSArenaPlus.dmg` from [Releases](../../releases), open it and drag the app to your Applications folder.

> **First launch**: macOS may block the app since it's not notarized. Go to **System Settings → Privacy & Security → Open Anyway**.

## Permissions

On first run, macOS will ask for **Screen Recording** permission — this is required for the OCR to read card names. Go to **System Settings → Privacy & Security → Screen Recording** and enable it for the app (or Terminal if running from source).

## Calibration

If the card name regions don't align with your screen, run the calibration tool:
```bash
python calibrate.py
```

## License

MIT
