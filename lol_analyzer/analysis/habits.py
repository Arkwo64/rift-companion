"""Playstyle/habit profile derived from op.gg's overall aggregate.

NOTE ON SCOPE: per-match timestamps are not available without the Riot API, so we
cannot compute time-of-day form or tilt/loss-streak effects here. What we CAN derive
from season aggregates is a robust playstyle fingerprint and pool discipline, which
is most of the actionable "habits" signal.
"""

# Rough benchmarks for a mixed Emerald pool. These are heuristics, not gospel —
# the report labels them as such.
BENCH = {
    "avg_death": (5.0, 6.5),        # (good<=, weak>=) lower is better
    "kill_participation": (55, 45),  # higher is better
    "vision_score": (30, 18),        # higher is better
    "cs_per_min": (6.5, 5.0),        # laner-ish; supports skew this down
    "op_score": (6.2, 5.5),          # op.gg performance score
    "damage_dealt_share": (24, 16),  # carry share
}


def _rate(value, good, weak, higher_better=True):
    if value is None:
        return "n/a"
    if higher_better:
        if value >= good:
            return "fuerte"
        if value <= weak:
            return "flojo"
    else:
        if value <= good:
            return "fuerte"
        if value >= weak:
            return "flojo"
    return "medio"


def profile_from_overall(overall):
    """Build a habit profile dict from the id:0 aggregate of a queue block."""
    if not overall:
        return {"available": False}

    play = overall.get("play", 0) or 1
    kda = overall.get("kda") or {}
    metrics = []

    def add(label, value, key, higher=True, fmt="{:.1f}"):
        good, weak = BENCH[key]
        metrics.append({
            "label": label,
            "value": value,
            "display": (fmt.format(value) if value is not None else "n/a"),
            "rating": _rate(value, good, weak, higher),
        })

    add("Participación en kills", overall.get("kill_participation"), "kill_participation", True, "{:.0f}%")
    add("Muertes por partida", kda.get("avg_death"), "avg_death", False, "{:.1f}")
    add("Visión (score)", overall.get("vision_score"), "vision_score", True, "{:.0f}")
    add("CS por minuto", overall.get("cs_per_min"), "cs_per_min", True, "{:.1f}")
    add("Op Score (rendimiento)", overall.get("op_score"), "op_score", True, "{:.1f}")
    add("Cuota de daño", overall.get("damage_dealt_share"), "damage_dealt_share", True, "{:.0f}%")

    # Aggression / closing: multikills and snowball per game
    per_game = {
        "double_kill": round((overall.get("double_kill", 0) or 0) / play, 2),
        "triple_kill": round((overall.get("triple_kill", 0) or 0) / play, 2),
        "snowball_hit_ratio": overall.get("snowball_hit_ratio"),
        "lane_lead": overall.get("lane_lead"),
    }

    strengths = [m["label"] for m in metrics if m["rating"] == "fuerte"]
    weaknesses = [m["label"] for m in metrics if m["rating"] == "flojo"]

    return {
        "available": True,
        "games": overall.get("play"),
        "metrics": metrics,
        "per_game": per_game,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "kda": kda.get("kda"),
    }


def pool_discipline(champions, min_games):
    """How concentrated is the champion pool? One-trick vs scattered both have costs."""
    played = [c for c in champions if c.get("play", 0) > 0]
    total = sum(c["play"] for c in played) or 1
    played.sort(key=lambda c: c["play"], reverse=True)

    # How many champs cover 80% of games?
    cum, n80 = 0, 0
    for c in played:
        cum += c["play"]
        n80 += 1
        if cum / total >= 0.8:
            break

    confident = [c for c in played if c["play"] >= min_games]
    note = None
    if n80 <= 2:
        note = "Pool muy concentrado: predecible y vulnerable a bans/counters. Ten 1-2 picks de respaldo."
    elif n80 >= 7:
        note = "Pool muy disperso: difícil dominar tantos champs. Reduce a 3-4 mains para subir más rápido."
    else:
        note = "Tamaño de pool saludable para escalar de forma consistente."

    return {
        "total_games": total,
        "distinct_played": len(played),
        "champs_for_80pct": n80,
        "confident_count": len(confident),
        "note": note,
    }
