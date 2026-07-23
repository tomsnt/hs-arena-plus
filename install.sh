#!/bin/bash
set -e

echo "=== HS Arena Overlay — Setup ==="

# Crea e attiva virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Installa dipendenze
pip install -q --upgrade pip
pip install -r requirements.txt

# Configura log.config di Hearthstone
python setup_logs.py

echo ""
echo "=== Setup completato! ==="
echo ""
echo "Comandi:"
echo "  source .venv/bin/activate"
echo "  python main.py --demo    # testa overlay"
echo "  python main.py           # usa con Hearthstone"
echo ""
echo "IMPORTANTE: se Hearthstone era aperto, riavvialo ora."
