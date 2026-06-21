"""Rank scoring helpers: turn tier/division into a comparable number and back, so we can
average the ranks of a lobby. Apex tiers (Master+) are scored by LP on top of the tier.
"""
TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD",
         "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"]
_APEX = {"MASTER", "GRANDMASTER", "CHALLENGER"}
_DIV = {"IV": 0, "III": 1, "II": 2, "I": 3}
_DIV_R = {0: "IV", 1: "III", 2: "II", 3: "I"}
_BAND = 100  # points per division


def rank_score(tier, division, lp=0):
    if not tier:
        return None
    t = tier.upper()
    if t not in TIERS:
        return None
    base = TIERS.index(t) * 4 * _BAND
    if t in _APEX:
        return base + min(lp or 0, 400)
    return base + _DIV.get(division, 0) * _BAND + min(lp or 0, 99)


def score_to_rank(score):
    if score is None:
        return None
    ti = max(0, min(int(score // (4 * _BAND)), len(TIERS) - 1))
    tier = TIERS[ti]
    if tier in _APEX:
        return tier.title()
    rem = score - ti * 4 * _BAND
    di = min(int(rem // _BAND), 3)
    return f"{tier.title()} {_DIV_R[di]}"


def short(rank):
    """{'tier','division','lp'} -> 'Emerald IV' (or None)."""
    if not rank or not rank.get("tier"):
        return None
    return score_to_rank(rank_score(rank.get("tier"), rank.get("division"), rank.get("lp") or 0))


def average(rank_dicts):
    scores = [rank_score(r.get("tier"), r.get("division"), r.get("lp") or 0)
              for r in rank_dicts if r and r.get("tier")]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return score_to_rank(round(sum(scores) / len(scores)))
