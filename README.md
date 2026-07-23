# HS Arena Plus

Overlay per macOS che mostra rating, sinergie e consigli per il draft Arena di Hearthstone in tempo reale.

---

## Installazione facile (App)

1. Scarica `HSArenaPlus.dmg` dalla sezione [Releases](https://github.com/tomsnt/hs-arena-plus/releases)
2. Aprilo e trascina l'app nella cartella Applicazioni
3. Al primo avvio macOS potrebbe bloccarla — vai in **Impostazioni → Privacy e Sicurezza → Apri comunque**
4. Alla prima esecuzione concedi il permesso di **Registrazione Schermo** quando richiesto

---

## Installazione da terminale

**Requisiti:** macOS 10.15+, Python 3.9+

```bash
git clone https://github.com/tomsnt/hs-arena-plus.git
cd hs-arena-plus
bash install.sh
```

Per avviare:
```bash
source .venv/bin/activate
python main.py
```

---

## Calibrazione

Se le zone di riconoscimento non sono allineate al tuo schermo:
```bash
python calibrate.py
```
