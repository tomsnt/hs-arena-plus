"""
Deck synergy and mana curve analysis for HS Arena Plus.

Synergy model: each card has PROVIDES and NEEDS tag sets.
Two cards synergize when provides(A) ∩ needs(B) ≠ ∅  (A enables B)
                        OR provides(B) ∩ needs(A) ≠ ∅  (B enables A).
"""
import re
from typing import Dict, List, Set, Tuple, Optional

_MECH_MAP = {
    "BATTLECRY": "battlecry", "DEATHRATTLE": "deathrattle",
    "RUSH": "rush", "DIVINE_SHIELD": "divine_shield",
    "LIFESTEAL": "lifesteal", "TAUNT": "taunt",
    "SPELL_DAMAGE": "spell_damage", "FREEZE": "freeze",
    "DISCOVER": "discover", "REBORN": "reborn", "WINDFURY": "windfury",
    "OUTCAST": "outcast", "COMBO": "combo", "INSPIRE": "inspire",
    "OVERHEAL": "overheal",
}

_KW_PATTERNS = {
    "battlecry":     r"\bbattlecry\b",
    "deathrattle":   r"\bdeathrattle\b",
    "rush":          r"\brush\b",
    "divine_shield": r"divine shield",
    "lifesteal":     r"\blifesteal\b",
    "taunt":         r"\btaunt\b",
    "spell_damage":  r"spell damage",
    "freeze":        r"\bfreeze\b",
    "discover":      r"\bdiscover\b",
    "combo":         r"\bcombo\b",
    "reborn":        r"\breborn\b",
    "outcast":       r"\boutcast\b",
    "inspire":       r"\binspire\b",
    "overheal":      r"\boverheal\b",
}

_ALL_RACES = [
    "DEMON", "BEAST", "DRAGON", "MURLOC", "MECH",
    "PIRATE", "ELEMENTAL", "QUILBOAR", "NAGA", "UNDEAD",
    "TOTEM", "DRAENEI",
]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_keywords(card: dict) -> Set[str]:
    text = _strip_html((card.get("text") or "")).lower()
    kws = set()
    for kw, pat in _KW_PATTERNS.items():
        if re.search(pat, text):
            kws.add(kw)
    for m in card.get("mechanics", []):
        norm = _MECH_MAP.get(m)
        if norm:
            kws.add(norm)
    return kws


def _card_tags(card: dict) -> Tuple[Set[str], Set[str]]:
    """
    Returns (provides, needs) tag sets for a card.
    provides = effects this card creates that amplify OTHER cards
    needs    = conditions/enablers this card benefits from
    """
    raw_text = _strip_html((card.get("text") or ""))
    text     = raw_text.lower()
    kws      = extract_keywords(card)
    ctype    = card.get("type", "MINION")
    race     = (card.get("race") or "").upper()
    cost     = card.get("cost", 4)

    provides: Set[str] = set()
    needs:    Set[str] = set()

    # ── Spell Damage ──────────────────────────────────────────────────────
    # Only provide spell_damage if the card IS a spell-damage minion (mechanic),
    # not just because it mentions "spell damage" in cost-reduction text.
    if "SPELL_DAMAGE" in card.get("mechanics", []):
        provides.add("spell_damage")
    # Only damage spells benefit meaningfully from spell damage bonus
    if ctype == "SPELL" and re.search(r"\bdeal \d+", text):
        needs.add("spell_damage")

    # ── Hero attacks (weapon ecosystem) ───────────────────────────────────
    if ctype == "WEAPON":
        # A weapon lets the hero attack → enables on-attack effects
        provides.add("hero_attack")
        # A weapon also benefits from: bonus attack, lifesteal, immune, on-attack payoffs
        needs.update(["hero_attack_boost", "hero_lifesteal", "hero_immune"])

    # "Give your hero +N attack" → boosts weapons / hero attacks
    if re.search(r"give your hero \+\d+ attack", text):
        provides.add("hero_attack_boost")
        needs.add("hero_attack")          # only useful if hero can attack

    # "Your hero has Lifesteal" → weapons heal on attack
    if re.search(r"your hero (has|gains) lifesteal", text):
        provides.add("hero_lifesteal")
        needs.add("hero_attack")

    # "Your hero is Immune / Immune while attacking" → safe hero attacks
    # Must reference the hero, not a minion ("give a minion Immune this turn" excluded)
    if re.search(r"your hero.{0,20}\bimmune\b|\bimmune\b.{0,20}(while attacking|your hero)|"
                 r"give your hero immune", text):
        provides.add("hero_immune")
        needs.add("hero_attack")

    # "After your hero attacks" on a NON-weapon → needs a weapon to trigger
    if ctype != "WEAPON" and re.search(r"after your hero attacks", text):
        needs.add("hero_attack")

    # "Inspire" = Hero Power payoff
    if "inspire" in kws:
        needs.add("hero_power_use")
    if re.search(r"use your hero power|hero power", text):
        provides.add("hero_power_use")

    # ── Deathrattle ───────────────────────────────────────────────────────
    if "deathrattle" in kws:
        needs.add("deathrattle_trigger")

    if re.search(r"(trigger|resummon|re-trigger|copy) .{0,25}deathrattle"
                 r"|whenever .{0,20}deathrattle"
                 r"|deathrattle triggers? twice", text):
        provides.add("deathrattle_trigger")

    # ── Reborn ────────────────────────────────────────────────────────────
    if "reborn" in kws:
        needs.add("deathrattle_trigger")   # reborn also benefits from death triggers

    # ── Battlecry amplifiers ──────────────────────────────────────────────
    if "battlecry" in kws:
        needs.add("battlecry_trigger")

    if re.search(r"battlecri(es|y) trigger twice|your battlecri(es|y).*twice"
                 r"|whenever you play .{0,10}battlecry", text):
        provides.add("battlecry_trigger")

    # ── Combo ─────────────────────────────────────────────────────────────
    if "combo" in kws:
        needs.add("card_played_first")      # combo needs another card played first

    if ctype in ("SPELL", "MINION") and "combo" not in kws:
        provides.add("card_played_first")   # any non-combo card triggers combos

    # ── Divine Shield ─────────────────────────────────────────────────────
    if "divine_shield" in kws:
        needs.add("grants_divine_shield")

    if re.search(r"give .{0,25}divine shield", text):
        provides.add("grants_divine_shield")

    # Cards with rush/lifesteal/windfury become extra dangerous with divine shield
    if ctype == "MINION" and (kws & {"rush", "lifesteal", "windfury", "divine_shield"}):
        needs.add("grants_divine_shield")

    # ── Freeze ────────────────────────────────────────────────────────────
    if "freeze" in kws and ctype == "SPELL":
        provides.add("freezes_enemies")

    if re.search(r"frozen|while frozen|against frozen", text):
        needs.add("freezes_enemies")

    # ── Tribal synergies ──────────────────────────────────────────────────
    if race and race not in ("ALL", ""):
        needs.add(f"tribal_buff:{race}")

    for r in _ALL_RACES:
        r_lc = r.lower()
        # "give your/all Demons +X" or "friendly Murlocs get" etc.
        if re.search(rf"(give|your|all|friendly) .{{0,20}}{r_lc}s? \+", text):
            provides.add(f"tribal_buff:{r}")
        # Card IS that tribe and text mentions it → tribal payoff card
        if race == r and re.search(rf"\b{r_lc}s?\b", text):
            provides.add(f"tribal_payoff:{r}")
            needs.add(f"tribal_buff:{r}")

    # ── Token generation / wide board ─────────────────────────────────────
    if re.search(r"summon \d+ .{0,20}(1/1|token|copy|copies)|fill .{0,10} board", text):
        provides.add("generates_tokens")
        needs.add("wide_board_buff")

    if re.search(r"give (all )?your minions \+", text):
        provides.add("wide_board_buff")
        needs.add("generates_tokens")

    # ── Discard ───────────────────────────────────────────────────────────
    if re.search(r"\bdiscard\b", text) and not re.search(r"whenever.*discard|after.*discard", text):
        provides.add("causes_discard")
        needs.add("discard_payoff")

    if re.search(r"whenever you discard|after you discard", text):
        provides.add("discard_payoff")
        needs.add("causes_discard")

    # ── Spell payoffs ─────────────────────────────────────────────────────
    if re.search(r"(after|whenever) you cast a spell|spellburst", text):
        provides.add("spell_payoff")
        needs.add("casts_spells")

    if ctype == "SPELL":
        provides.add("casts_spells")

    # ── Overload ──────────────────────────────────────────────────────────
    if re.search(r"overloaded mana crystal", text):
        provides.add("overload_payoff")
        needs.add("causes_overload")

    if re.search(r"\boverload\b", text) and not re.search(r"overloaded mana", text):
        provides.add("causes_overload")
        needs.add("overload_payoff")

    # ── Overheal ──────────────────────────────────────────────────────────
    if "overheal" in kws:
        needs.add("healing_effect")

    if re.search(r"restore \d+ health|heal .{0,15}for \d+", text):
        provides.add("healing_effect")

    # ── Damage to own minions / self-damage payoff ────────────────────────
    if re.search(r"deal \d+ damage to .{0,10}(your|friendly) minion|take \d+ damage", text):
        provides.add("damages_own_minion")

    if re.search(r"whenever .{0,20}(your|a friendly) minion takes damage"
                 r"|whenever .{0,20}takes damage", text):
        needs.add("damages_own_minion")
        provides.add("self_damage_payoff")

    # ── Frenzy / enrage ───────────────────────────────────────────────────
    if re.search(r"\bfrenzy\b|\benrage\b", text):
        needs.add("damages_own_minion")

    return provides, needs


# Tags too generic to count as real synergies (every card pair would match)
_GENERIC_SYNERGY_TAGS = {
    "card_played_first",  # every non-combo card provides this
    "cost_reduction",     # too universal; "Rush the Stage" etc. cause false positives
}


def _has_synergy(offered: dict, deck_card: dict) -> bool:
    """True if there is a meaningful enabler relationship between the two cards."""
    op, on = _card_tags(offered)
    dp, dn = _card_tags(deck_card)
    op -= _GENERIC_SYNERGY_TAGS
    on -= _GENERIC_SYNERGY_TAGS
    dp -= _GENERIC_SYNERGY_TAGS
    dn -= _GENERIC_SYNERGY_TAGS
    if dp & on:
        return True
    if op & dn:
        return True
    return False


def build_deck_profile(deck_ids: List[str], card_db: dict) -> dict:
    curve: Dict[int, int] = {}
    types: Dict[str, int] = {}
    tribes: Dict[str, int] = {}
    keywords: Dict[str, int] = {}

    for cid in deck_ids:
        card = card_db.get(cid, {})
        if not card:
            continue
        cost_key = min(card.get("cost", 0), 7)
        curve[cost_key] = curve.get(cost_key, 0) + 1

        ctype = card.get("type", "MINION")
        types[ctype] = types.get(ctype, 0) + 1

        race = (card.get("race") or "").upper()
        if race and race not in ("ALL", ""):
            tribes[race] = tribes.get(race, 0) + 1

        for kw in extract_keywords(card):
            keywords[kw] = keywords.get(kw, 0) + 1

    return {
        "curve": curve, "types": types,
        "tribes": tribes, "keywords": keywords,
        "total": len(deck_ids),
    }


# Needs excluded from anti-synergy because the card works fine without them
# (they signal "would be better with X", not "is actively hurt without X")
_GENERIC_NEEDS = {
    # Too universal
    "cost_reduction", "card_played_first", "hero_power_use",
    # Mechanic amplifiers — having the mechanic is fine without doublers
    "deathrattle_trigger",   # deathrattle fires once regardless
    "battlecry_trigger",     # battlecry triggers once regardless
    "grants_divine_shield",  # rush/lifesteal/windfury work without DS
    # Weapon enhancers — weapons attack regardless of these
    "hero_immune", "hero_lifesteal", "hero_attack_boost",
    # Spell damage — spells deal their base damage without it
    "spell_damage",
}


def compute_synergy(
    card_id: str,
    card_db: dict,
    deck_ids: List[str],
    deck_profile: dict,
) -> Tuple[int, List[str]]:
    """Returns (synergy_level 0-2, list of synergistic card names from the deck).
    Level: 0=none, 1=1-2 synergies, 2=3+ synergies."""
    card = card_db.get(card_id, {})
    if not card or not deck_profile.get("total"):
        return 0, []

    card_cost = card.get("cost", 4)
    curve     = deck_profile.get("curve", {})

    seen: Set[str] = set()
    unique_names: List[str] = []
    for dcid in deck_ids:
        dc = card_db.get(dcid, {})
        if not dc:
            continue
        if _has_synergy(card, dc):
            name = dc.get("name", dcid)
            if name not in seen:
                seen.add(name)
                unique_names.append(name)

    raw = 0
    if len(unique_names) >= 3:
        raw = 2
    elif len(unique_names) >= 1:
        raw = 1

    # Curve gap bonus
    cost_key = min(card_cost, 7)
    if card_cost <= 5 and curve.get(cost_key, 0) == 0:
        raw = min(raw + 1, 2)
    elif card_cost <= 4 and curve.get(cost_key, 0) == 1:
        raw = min(raw + 1, 2)

    return raw, unique_names


_WEAPON_OVERFLOW = 3   # 3+ weapons already in deck → new weapon is anti-synergy
_DUPE_THRESHOLD  = 2   # already 2+ copies of this card name → 3rd is wasteful


def compute_anti_synergy(
    card_id: str,
    card_db: dict,
    deck_ids: List[str],
) -> Tuple[int, List[str]]:
    """Returns (anti_level 0-2, list of human-readable anti-synergy reasons).
    Anti-synergy sources:
      • specific needs the card has that NO deck card satisfies
      • too many weapons in the deck
      • too many copies of this card already in the deck
    Level: 0=none, 1=1-2 issues, 2=3+ issues."""
    card = card_db.get(card_id, {})
    if not card:
        return 0, []

    reasons: List[str] = []

    # ── 1. Unmet specific needs ───────────────────────────────────────────
    _, needs = _card_tags(card)
    # Also exclude tribal_buff:X — a tribal minion works fine without buff support
    specific_needs = {n for n in needs
                      if n not in _GENERIC_NEEDS and not n.startswith("tribal_buff:")}
    if specific_needs:
        deck_provides: Set[str] = set()
        for dcid in deck_ids:
            dc = card_db.get(dcid, {})
            if dc:
                dp, _ = _card_tags(dc)
                deck_provides |= dp
        for tag in sorted(specific_needs - deck_provides):
            # Make tags human-readable
            label = tag.replace("tribal_buff:", "no tribal buff for ").replace("_", " ")
            reasons.append(label)

    # ── 2. Deck-composition redundancy checks ─────────────────────────────
    card_type = card.get("type", "")
    card_name = card.get("name", "")

    type_counts: Dict[str, int] = {}
    name_counts: Dict[str, int] = {}
    for dcid in deck_ids:
        dc = card_db.get(dcid, {})
        if not dc:
            continue
        t = dc.get("type", "")
        n = dc.get("name", "")
        type_counts[t] = type_counts.get(t, 0) + 1
        if n:
            name_counts[n] = name_counts.get(n, 0) + 1

    if card_type == "WEAPON" and type_counts.get("WEAPON", 0) >= _WEAPON_OVERFLOW:
        reasons.append(f"too many weapons ({type_counts['WEAPON']} in deck)")

    if card_name and name_counts.get(card_name, 0) >= _DUPE_THRESHOLD:
        reasons.append(f"already {name_counts[card_name]}x {card_name}")

    if not reasons:
        return 0, []

    level = 2 if len(reasons) >= 3 else 1
    return level, reasons


def combined_score(base_score: Optional[int], synergy_level: int,
                   anti_level: int = 0) -> Optional[int]:
    if base_score is None:
        return None
    return base_score + synergy_level * 7 - anti_level * 7


def synergy_suffix(syn_level: int, anti_level: int = 0) -> str:
    net = syn_level - anti_level
    if net > 0:
        return "+" * min(net, 2)
    if net < 0:
        return "-" * min(-net, 2)
    return ""


def compute_deck_hints(deck_ids: List[str], card_db: dict) -> Tuple[List[str], int]:
    """Analyzes deck completeness. Returns (hints, score_modifier).
    Modifier is clamped to [-15, +10]."""
    n = len(deck_ids)
    if n < 5:
        return [], 0

    factor = n / 30.0
    hints: List[str] = []
    modifier = 0

    type_counts: Dict[str, int] = {}
    curve: Dict[int, int] = {}
    draw_count = 0
    aoe_count = 0

    hard_removal = 0   # destroy / transform / silence / high-damage (permanent)
    soft_removal = 0   # dormant / freeze / can't attack (temporary CC)
    total_cost = 0

    for cid in deck_ids:
        card = card_db.get(cid, {})
        if not card:
            continue
        ctype = card.get("type", "MINION")
        type_counts[ctype] = type_counts.get(ctype, 0) + 1
        cost_key = min(card.get("cost", 0), 7)
        curve[cost_key] = curve.get(cost_key, 0) + 1
        text = _strip_html((card.get("text") or "")).lower()

        # Hard removal: permanent disposal of a minion
        is_hard = bool(
            re.search(r"destroy .{0,20}(a |an |enemy )?minion", text) or
            re.search(r"transform .{0,15}(a |an |enemy )?minion", text) or   # Hex/Polymorph
            re.search(r"deal [5-9]\d* damage to .{0,15}(a |an |enemy |one )minion", text) or
            re.search(r"\bsilence\b .{0,10}(a |an |enemy )?minion", text)
        )
        # AoE removal (also counts as hard)
        is_aoe = bool(
            re.search(r"deal \d+ damage to all|destroy all minions|deal \d+ damage to each", text)
        )
        if is_hard or is_aoe:
            hard_removal += 1
            aoe_count += (1 if is_aoe else 0)

        # Soft removal: temporary crowd control
        is_soft = bool(
            re.search(r"\bdormant\b", text) or
            re.search(r"freeze .{0,20}(a |an |all |enemy )?minion|freeze all .{0,10}enemies", text) or
            re.search(r"can't attack", text) or
            re.search(r"set .{0,10}attack to 0", text)
        )
        if is_soft and not is_hard:   # don't double-count
            soft_removal += 1

        if re.search(r"\bdraw (\d+|a|an|two|three|four) cards?\b|\bdraw a card\b", text):
            draw_count += 1
        total_cost += card.get("cost", 0)

    minion_count = type_counts.get("MINION", 0)
    spell_count = type_counts.get("SPELL", 0)
    weapon_count = type_counts.get("WEAPON", 0)
    late_count = sum(curve.get(k, 0) for k in (6, 7))
    avg_cost = total_cost / n if n > 0 else 0

    # ── Mana curve ──────────────────────────────────────────────────────
    if n >= 6:
        if curve.get(2, 0) == 0:
            hints.append("missing 2-drops")
            modifier -= 4
        if curve.get(3, 0) == 0:
            hints.append("missing 3-drops")
            modifier -= 3
        if late_count > round(5 * factor):
            hints.append(f"top-heavy ({late_count} cards 6+)")
            modifier -= 3

    # ── Late game threats ────────────────────────────────────────────────
    if n >= 10 and late_count == 0:
        hints.append("no late game threats (6+ mana)")
        modifier -= 4
    elif n >= 15 and late_count < round(3 * factor):
        hints.append(f"few late game threats ({late_count})")
        modifier -= 2

    # ── Minion / spell ratio ────────────────────────────────────────────
    if n >= 10:
        if minion_count < round(12 * factor):
            hints.append(f"low on minions ({minion_count})")
            modifier -= 5
        if spell_count == 0 and n >= 15:
            hints.append("no spells")
            modifier -= 4

    # ── Removal — hard and soft tracked separately ───────────────────────
    if n >= 6:
        hard_threshold = round(2 * factor)

        if hard_removal == 0 and soft_removal == 0:
            hints.append("missing removal")
            modifier -= 10
        elif hard_removal == 0:
            hints.append(f"no hard removal (soft only: {soft_removal})")
            modifier -= 7
        elif hard_removal < hard_threshold:
            hints.append(f"low on hard removal ({hard_removal})")
            modifier -= 4
            if soft_removal == 0 and n >= 12:
                hints.append("no soft removal / CC")
                modifier -= 2
        elif soft_removal == 0 and n >= 15:
            hints.append("no soft removal / CC")
            modifier -= 2

    # ── Card draw ───────────────────────────────────────────────────────
    if n >= 10:
        if draw_count == 0:
            hints.append("no card draw")
            modifier -= 5
        elif draw_count < round(2 * factor) and n >= 12:
            hints.append(f"low on card draw ({draw_count})")
            modifier -= 2

    # ── High average cost ────────────────────────────────────────────────
    if n >= 10 and avg_cost > 4.2:
        hints.append(f"high avg cost ({avg_cost:.1f})")
        modifier -= 2

    # ── Weapons ─────────────────────────────────────────────────────────
    if weapon_count > round(3 * factor):
        hints.append(f"too many weapons ({weapon_count})")
        modifier -= 3

    # ── Positive ────────────────────────────────────────────────────────
    if n >= 20 and not hints:
        hints.append("well balanced")
        modifier += 5

    return hints, max(-15, min(10, modifier))


def curve_note(deck_profile: dict, card_cost: int) -> str:
    if card_cost < 1 or card_cost > 6:
        return ""
    curve = deck_profile.get("curve", {})
    if deck_profile.get("total", 0) < 3:
        return ""
    count = curve.get(card_cost, 0)
    if count == 0:
        return f"missing {card_cost}-drop"
    if count == 1 and card_cost <= 4:
        return f"low on {card_cost}-drops"
    return ""
