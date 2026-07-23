"""
Configures Hearthstone's log.config to enable DraftManager logging.
Run once before using the overlay.
"""
import os
from pathlib import Path

LOG_CONFIG_PATH = Path.home() / "Library/Preferences/Blizzard/Hearthstone/log.config"

REQUIRED_SECTIONS = {
    "DraftManager": {
        "LogLevel": "1",
        "FilePrinting": "true",
        "Verbose": "1",
    },
    "Arena": {
        "LogLevel": "1",
        "FilePrinting": "true",
    },
}


def read_config(path: Path) -> dict:
    config = {}
    current_section = None
    if not path.exists():
        return config
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            config[current_section] = {}
        elif "=" in line and current_section:
            key, _, value = line.partition("=")
            config[current_section][key.strip()] = value.strip()
    return config


def write_config(path: Path, config: dict):
    lines = []
    for section, keys in config.items():
        lines.append(f"[{section}]")
        for k, v in keys.items():
            lines.append(f"{k}={v}")
        lines.append("")
    path.write_text("\n".join(lines))


def fix_permissions():
    """Il file potrebbe essere owned da root (capita dopo aggiornamenti Blizzard)."""
    import subprocess, os
    stat = LOG_CONFIG_PATH.stat()
    if stat.st_uid != os.getuid():
        print(f"[setup] Il file e' owned da root. Correggendo con sudo...")
        result = subprocess.run(
            ["sudo", "chown", f"{os.getlogin()}:staff", str(LOG_CONFIG_PATH)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[setup] ERRORE: {result.stderr}")
            print(f"\nEsegui manualmente:")
            print(f"  sudo chown {os.getlogin()}:staff {LOG_CONFIG_PATH}")
            return False
        print("[setup] Permessi corretti.")
    return True


def setup():
    LOG_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config = read_config(LOG_CONFIG_PATH)
    changed = False
    for section, keys in REQUIRED_SECTIONS.items():
        if section not in config:
            config[section] = {}
        for k, v in keys.items():
            if config[section].get(k) != v:
                config[section][k] = v
                changed = True
    if changed:
        if not LOG_CONFIG_PATH.exists() or LOG_CONFIG_PATH.stat().st_uid == __import__("os").getuid():
            write_config(LOG_CONFIG_PATH, config)
            print(f"[setup] log.config aggiornato: {LOG_CONFIG_PATH}")
        else:
            if not fix_permissions():
                return
            write_config(LOG_CONFIG_PATH, config)
            print(f"[setup] log.config aggiornato: {LOG_CONFIG_PATH}")
    else:
        print("[setup] log.config gia' configurato correttamente.")
    print("[setup] Riavvia Hearthstone se era aperto.")


if __name__ == "__main__":
    setup()
