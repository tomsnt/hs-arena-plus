"""
Fetches and caches arena card ratings from HearthArena (score 0-100)
with HearthstoneJSON as fallback for card name/data lookup.
"""
import html as _html
import json
import re
import time
import requests
from pathlib import Path
from typing import Optional, Union, Dict, List

CACHE_DIR = Path.home() / ".cache" / "hs-arena-overlay"
CARDS_CACHE = CACHE_DIR / "cards.json"
RATINGS_CACHE = CACHE_DIR / "ratings.json"
HSREPLAY_CACHE = CACHE_DIR / "hsreplay_arena.json"
CACHE_TTL = 3600 * 6   # 6 hours
HSREPLAY_TTL = 3600 * 12  # 12 hours

HEARTHSTONE_JSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.collectible.json"
HEARTHARENA_URL = "https://www.heartharena.com/tierlist"
HSREPLAY_ARENA_URL = (
    "https://hsreplay.net/analytics/query/card_list_free/"
    "?GameType=ARENA&TimeRange=CURRENT_PATCH"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

# Browser-like headers required by Cloudflare on HSReplay
_HSREPLAY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://hsreplay.net/arena/",
    "X-Requested-With": "XMLHttpRequest",
}


def _is_fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < CACHE_TTL


def _load_json(path: Path) -> Optional[Union[dict, list]]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _save_json(path: Path, data):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Card name/data lookup (HearthstoneJSON)
# ---------------------------------------------------------------------------

_card_db: Dict[str, dict] = {}


def load_card_db() -> Dict[str, dict]:
    global _card_db
    if _card_db:
        return _card_db
    if _is_fresh(CARDS_CACHE):
        data = _load_json(CARDS_CACHE)
    else:
        print("[ratings] Downloading card data from HearthstoneJSON...")
        try:
            resp = requests.get(HEARTHSTONE_JSON_URL, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            _save_json(CARDS_CACHE, data)
        except Exception as e:
            print(f"[ratings] Error downloading cards: {e}")
            data = _load_json(CARDS_CACHE) or []
    _card_db = {c["id"]: c for c in data if "id" in c}
    for c in data:
        if "dbfId" in c:
            _card_db[str(c["dbfId"])] = c
    print(f"[ratings] Loaded {len(_card_db)} cards.")
    return _card_db


# ---------------------------------------------------------------------------
# Arena ratings (HearthArena scraping)
# ---------------------------------------------------------------------------
# HearthArena HTML structure:
#   <dl class="card score_80">
#     <dt ... data-card-image=".../CS2_029.webp">Fireball</dt>
#     <dd class="score score_80">80</dd>
#   </dl>

_ratings: Dict[str, dict] = {}
_ratings_by_name: Dict[str, dict] = {}   # name_ha.lower() → rating entry

# <dl> format: <dt data-card-image="...ID.webp">Name</dt><dd class="score score_N">N [opt span]</dd>
RE_DL = re.compile(
    r'data-card-image="[^"]+/([A-Za-z0-9_]+)\.webp"[^>]*>\s*([^<]+?)\s*(?:<span[^>]*>[^<]*</span>\s*)?</dt>'
    r'\s*<dd class="score[^"]*">(\d+)',
    re.DOTALL,
)
# <table> format: <td data-card-image="...ID.webp">Name</td><td>Class</td><td></td><td>SCORE</td>
RE_TABLE = re.compile(
    r'data-card-image="[^"]+/([A-Za-z0-9_]+)\.webp"[^>]*>\s*([^<]+?)\s*</td>'
    r'(?:\s*<td>[^<]*</td>){1,3}\s*<td>(\d+)</td>',
    re.DOTALL,
)


def load_ratings() -> Dict[str, dict]:
    """Returns dict keyed by card ID -> {score, tier}, merged from all class tierlists."""
    global _ratings, _ratings_by_name
    if _ratings:
        return _ratings
    if _is_fresh(RATINGS_CACHE):
        _ratings = _load_json(RATINGS_CACHE) or {}
        if _ratings:
            print(f"[ratings] Ratings in cache: {len(_ratings)} carte.")
            _build_name_index()
            return _ratings
    print("[ratings] Downloading arena ratings from HearthArena...")
    try:
        resp = requests.get(HEARTHARENA_URL, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        _ratings = _parse_heartharena(resp.text)
        _save_json(RATINGS_CACHE, _ratings)
        print(f"[ratings] Caricate ratings per {len(_ratings)} carte.")
    except Exception as e:
        print(f"[ratings] Failed to download ratings: {e}")
        _ratings = {}
    _build_name_index()
    return _ratings


def _build_name_index():
    global _ratings_by_name
    _ratings_by_name = {
        v["name_ha"].lower(): v
        for v in _ratings.values()
        if v.get("name_ha")
    }


def _parse_heartharena(html_text: str) -> Dict[str, dict]:
    result = {}
    for regex in (RE_DL, RE_TABLE):
        for m in regex.finditer(html_text):
            card_id = m.group(1)
            if card_id in result:
                continue
            name = _html.unescape(m.group(2).strip())
            score = int(m.group(3))
            result[card_id] = {
                "score": score,
                "tier": _score_to_tier(score),
                "name_ha": name,
            }
    return result


def _score_to_tier(score: int) -> str:
    if score >= 100:
        return "SS"
    if score >= 90:
        return "S"
    if score >= 75:
        return "A"
    if score >= 60:
        return "B"
    if score >= 45:
        return "C"
    if score >= 30:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_card_info(card_id: str) -> dict:
    """Returns combined card info + rating for a given Hearthstone card ID."""
    db = load_card_db()
    ratings = load_ratings()

    card = db.get(card_id, {})

    # 1. Direct ID lookup
    rating = ratings.get(card_id) or {}

    # 2. Strip CORE_ prefix (HearthArena uses original IDs)
    if not rating and card_id.startswith("CORE_"):
        rating = ratings.get(card_id[5:]) or {}

    # 3. Name-based fallback (catches ID scheme mismatches for new sets)
    if not rating:
        card_name = card.get("name", "")
        if card_name and _ratings_by_name:
            rating = _ratings_by_name.get(card_name.lower()) or {}

    name = card.get("name") or rating.get("name_ha") or card_id
    cost = card.get("cost", "?")
    card_type = card.get("type", "")
    rarity = card.get("rarity", "")
    score = rating.get("score")
    tier = rating.get("tier", "?")

    score_display = str(score) if score is not None else "N/A"

    return {
        "card_id": card_id,
        "name": name,
        "cost": cost,
        "type": card_type,
        "rarity": rarity,
        "tier": tier,
        "winrate": score_display,   # repurpose field: shows HearthArena score
        "score": score,
    }


# ---------------------------------------------------------------------------
# HSReplay arena win-rate stats
# ---------------------------------------------------------------------------

_hsreplay_stats: Optional[Dict[str, list]] = None   # CLASS → [{dbf_id, included_winrate, …}]


def load_hsreplay_arena_stats() -> Dict[str, list]:
    """Fetches per-class arena card win-rates from HSReplay. Returns {} on failure."""
    global _hsreplay_stats
    if _hsreplay_stats is not None:
        return _hsreplay_stats

    if HSREPLAY_CACHE.exists() and (time.time() - HSREPLAY_CACHE.stat().st_mtime) < HSREPLAY_TTL:
        cached = _load_json(HSREPLAY_CACHE)
        if cached:
            _hsreplay_stats = cached
            total = sum(len(v) for v in _hsreplay_stats.values())
            print(f"[ratings] HSReplay arena stats from cache: {total} cards.")
            return _hsreplay_stats

    print("[ratings] Downloading arena win-rates from HSReplay...")
    try:
        resp = requests.get(HSREPLAY_ARENA_URL, headers=_HSREPLAY_HEADERS, timeout=15)
        resp.raise_for_status()
        raw = resp.json()
        _hsreplay_stats = raw.get("series", {}).get("data", {})
        if _hsreplay_stats:
            _save_json(HSREPLAY_CACHE, _hsreplay_stats)
            total = sum(len(v) for v in _hsreplay_stats.values())
            print(f"[ratings] HSReplay: {total} card stats, {len(_hsreplay_stats)} classi.")
        else:
            print("[ratings] HSReplay: unexpected format — using fallback.")
            _hsreplay_stats = {}
    except Exception as e:
        print(f"[ratings] HSReplay unavailable ({e}) — using HearthArena fallback.")
        _hsreplay_stats = _load_json(HSREPLAY_CACHE) or {}

    return _hsreplay_stats


def _detect_player_class(deck_ids: List[str], card_db: dict) -> Optional[str]:
    counts: Dict[str, int] = {}
    for cid in deck_ids:
        card = card_db.get(cid, {})
        classes = card.get("classes") or ([card.get("cardClass")] if card.get("cardClass") else [])
        for cc in classes:
            if cc and cc not in ("NEUTRAL", ""):
                counts[cc] = counts.get(cc, 0) + 1
    return max(counts, key=counts.get) if counts else None


def compute_top_tier_pct(deck_ids: List[str], card_db: dict) -> Optional[int]:
    """
    Returns 0-100: how close the deck is to the best possible picks for the class.
    Primary source: HSReplay arena included_winrate per class.
    Fallback: HearthArena score comparison.
    """
    if not deck_ids:
        return None

    player_class = _detect_player_class(deck_ids, card_db)

    # ── Primary: HSReplay win-rate data ─────────────────────────────────────
    hsreplay = load_hsreplay_arena_stats()
    class_stats = (hsreplay.get(player_class, []) if player_class else [])

    if class_stats:
        wr_by_dbf: Dict[int, float] = {
            int(e["dbf_id"]): float(e["included_winrate"])
            for e in class_stats
            if "dbf_id" in e and "included_winrate" in e
        }
        player_wr: List[float] = []
        for cid in deck_ids:
            dbf = card_db.get(cid, {}).get("dbfId")
            if dbf and int(dbf) in wr_by_dbf:
                player_wr.append(wr_by_dbf[int(dbf)])
        # Only use HSReplay if we matched at least 1/3 of the deck
        if len(player_wr) >= max(2, len(deck_ids) // 3):
            player_avg_wr = sum(player_wr) / len(player_wr)
            all_wr = sorted(wr_by_dbf.values(), reverse=True)
            top30_avg_wr = sum(all_wr[:30]) / min(30, len(all_wr))
            if top30_avg_wr > 0:
                return min(100, int(round(player_avg_wr / top30_avg_wr * 100)))

    # ── Fallback: HearthArena score comparison ───────────────────────────────
    load_ratings()
    player_scores: List[int] = []
    for cid in deck_ids:
        r = _ratings.get(cid) or {}
        if not r and cid.startswith("CORE_"):
            r = _ratings.get(cid[5:]) or {}
        if not r:
            name = card_db.get(cid, {}).get("name", "")
            if name:
                r = _ratings_by_name.get(name.lower()) or {}
        s = r.get("score")
        if s is not None:
            player_scores.append(s)

    if not player_scores:
        return None

    player_avg = sum(player_scores) / len(player_scores)

    eligible: List[int] = []
    seen: set = set()
    for cid, card in card_db.items():
        if cid.startswith("CORE_"):
            continue
        if card.get("type") in ("HERO", "HERO_POWER", "ENCHANTMENT"):
            continue
        cc = card.get("cardClass", "NEUTRAL")
        if player_class and cc not in (player_class, "NEUTRAL"):
            continue
        name = card.get("name", "")
        if name in seen:
            continue
        r = _ratings.get(cid) or _ratings_by_name.get(name.lower()) or {}
        s = r.get("score")
        if s is not None:
            seen.add(name)
            eligible.append(s)

    if len(eligible) < 30:
        return None

    top30_avg = sum(sorted(eligible, reverse=True)[:30]) / 30
    return min(100, int(round(player_avg / top30_avg * 100))) if top30_avg > 0 else None


TIER_COLORS = {
    "SS": "#FFD700",  # gold (same as S — absolute top)
    "S":  "#FFD700",  # gold
    "A":  "#4CAF50",  # green
    "B":  "#2196F3",  # blue
    "C":  "#FF9800",  # orange
    "D":  "#F44336",  # red
    "F":  "#B71C1C",  # dark red
    "?":  "#9E9E9E",  # grey
}

CLASS_DISPLAY_NAMES = {
    "DRUID": "Druid",
    "HUNTER": "Hunter",
    "MAGE": "Mage",
    "PALADIN": "Paladin",
    "PRIEST": "Priest",
    "ROGUE": "Rogue",
    "SHAMAN": "Shaman",
    "WARLOCK": "Warlock",
    "WARRIOR": "Warrior",
    "DEMONHUNTER": "Demon Hunter",
    "DEATHKNIGHT": "Death Knight",
}

HERO_RATINGS_CACHE = CACHE_DIR / "hero_ratings.json"
_hero_ratings: Optional[Dict[str, dict]] = None


def load_hero_ratings() -> Dict[str, dict]:
    """Returns per-class arena strength. Keys: class constant (DRUID, MAGE, …).
    Computed from HSReplay included_winrate (primary) or HearthArena card scores (fallback)."""
    global _hero_ratings
    if _hero_ratings is not None:
        return _hero_ratings
    if HERO_RATINGS_CACHE.exists() and (time.time() - HERO_RATINGS_CACHE.stat().st_mtime) < CACHE_TTL:
        cached = _load_json(HERO_RATINGS_CACHE)
        if cached:
            _hero_ratings = cached
            print(f"[ratings] Hero ratings from cache: {len(_hero_ratings)} classes.")
            return _hero_ratings
    print("[ratings] Computing hero ratings...")
    _hero_ratings = _compute_hero_ratings()
    if _hero_ratings:
        _save_json(HERO_RATINGS_CACHE, _hero_ratings)
    return _hero_ratings


def _compute_hero_ratings() -> Dict[str, dict]:
    result: Dict[str, dict] = {}

    # Primary: HSReplay per-class card included_winrate
    hsreplay = load_hsreplay_arena_stats()
    if hsreplay:
        for cls, cards in hsreplay.items():
            if not cards:
                continue
            wrs = sorted(
                [float(c["included_winrate"]) for c in cards if "included_winrate" in c],
                reverse=True,
            )
            if len(wrs) < 5:
                continue
            top30 = wrs[:30]
            avg_wr = sum(top30) / len(top30)
            # Normalize: 50% → 0, 56% → 100 (typical arena WR band)
            score = int(min(100, max(0, (avg_wr - 50.0) / 6.0 * 100)))
            result[cls] = {
                "score": score,
                "tier": _score_to_tier(score),
                "display": CLASS_DISPLAY_NAMES.get(cls, cls.capitalize()),
                "avg_winrate": round(avg_wr, 2),
            }

    # Fallback: average top-30 HearthArena scores per class
    if not result:
        ratings = load_ratings()
        card_db = load_card_db()
        class_scores: Dict[str, List[int]] = {}
        for card_id, rating in ratings.items():
            card = card_db.get(card_id) or card_db.get("CORE_" + card_id, {})
            cls = card.get("cardClass", "")
            if not cls or cls == "NEUTRAL":
                continue
            s = rating.get("score")
            if s is not None:
                class_scores.setdefault(cls, []).append(s)
        for cls, scores in class_scores.items():
            top30 = sorted(scores, reverse=True)[:30]
            if len(top30) < 10:
                continue
            avg = sum(top30) / len(top30)
            result[cls] = {
                "score": int(avg),
                "tier": _score_to_tier(int(avg)),
                "display": CLASS_DISPLAY_NAMES.get(cls, cls.capitalize()),
                "avg_winrate": None,
            }

    print(f"[ratings] Hero ratings computed: {list(result.keys())}")
    return result
