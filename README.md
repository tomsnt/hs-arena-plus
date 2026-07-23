# HS Arena Plus

macOS overlay that shows real-time card ratings, synergies and deck tips during Hearthstone Arena draft.

---

## Easy Install (App)

1. Download `HSArenaPlus.dmg` from [Releases](https://github.com/tomsnt/hs-arena-plus/releases)
2. Open it and drag the app to your Applications folder
3. On first launch macOS may block it — go to **System Settings → Privacy & Security → Open Anyway**
4. When prompted, grant **Screen Recording** permission

---

## Install from Terminal

**Requirements:** macOS 10.15+, Python 3.9+

```bash
git clone https://github.com/tomsnt/hs-arena-plus.git
cd hs-arena-plus
bash install.sh
```

To launch:
```bash
source .venv/bin/activate
python app.py
```

---

## Calibration

If the card name regions don't align with your screen:
```bash
python calibrate.py
```
