"""Lane matchup analysis from Riot match data — your win rate vs the enemy you
laned against. This is data no public site shows, because it's your individual record.
"""
from collections import defaultdict

from ..collectors.riot import QUEUE_GROUPS

# Riot teamPosition -> op.gg role slug
RIOT_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid",
             "BOTTOM": "adc", "UTILITY": "support"}


def _me_and_opponent(match, puuid):
    parts = match.get("info", {}).get("participants", [])
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if not me:
        return None, None
    pos = me.get("teamPosition") or ""
    opp = next((p for p in parts
                if p.get("teamId") != me.get("teamId")
                and p.get("teamPosition") == pos and pos), None)
    return me, opp


def infer_roles(matches, puuid):
    """Most-played role per champion id, from the user's own games (any queue)."""
    counts = defaultdict(lambda: defaultdict(int))
    for m in matches:
        me, _ = _me_and_opponent(m, puuid)
        if not me:
            continue
        pos = me.get("teamPosition")
        if pos:
            counts[me.get("championId")][pos] += 1
    roles = {}
    for cid, posc in counts.items():
        best = max(posc.items(), key=lambda kv: kv[1])[0]
        roles[cid] = RIOT_ROLE.get(best)
    return roles


def analyze_matchups(matches, puuid, queue_group, min_games=4):
    """Return your lane-matchup record vs each enemy champion (overall + per your champ)."""
    qids = QUEUE_GROUPS.get(queue_group)
    vs_enemy = defaultdict(lambda: [0, 0])          # direct lane opponent -> [wins, games]
    # per your champ: (enemy, enemy_role) -> [wins, games]. Botlane counts BOTH enemies.
    by_my_champ = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for m in matches:
        info = m.get("info", {})
        if qids is not None and info.get("queueId") not in qids:
            continue
        parts = info.get("participants", [])
        me = next((p for p in parts if p.get("puuid") == puuid), None)
        if not me:
            continue
        pos = me.get("teamPosition")
        win = 1 if me.get("win") else 0
        mine = me.get("championName")
        opp = next((p for p in parts if p.get("teamId") != me.get("teamId")
                    and p.get("teamPosition") == pos and pos), None)
        targets = []
        if opp:
            vs_enemy[opp.get("championName")][0] += win
            vs_enemy[opp.get("championName")][1] += 1
            targets.append(opp)
        # In botlane you fight two enemies: also record the cross-lane opponent.
        if pos in ("BOTTOM", "UTILITY"):
            other = "UTILITY" if pos == "BOTTOM" else "BOTTOM"
            cross = next((p for p in parts if p.get("teamId") != me.get("teamId")
                          and p.get("teamPosition") == other), None)
            if cross:
                targets.append(cross)
        for o in targets:
            key = (o.get("championName"), RIOT_ROLE.get(o.get("teamPosition"), ""))
            by_my_champ[mine][key][0] += win
            by_my_champ[mine][key][1] += 1

    def rows(d):
        out = [{"enemy": e, "wins": w, "games": g, "win_rate": round(100 * w / g)}
               for e, (w, g) in d.items()]
        out.sort(key=lambda r: (r["games"], -r["win_rate"]), reverse=True)
        return out

    def champ_rows(d):
        out = [{"enemy": k[0], "enemy_role": k[1], "wins": v[0], "games": v[1],
                "win_rate": round(100 * v[0] / v[1])} for k, v in d.items()]
        out.sort(key=lambda r: (r["games"], -r["win_rate"]), reverse=True)
        return out

    all_rows = rows(vs_enemy)
    confident = [r for r in all_rows if r["games"] >= min_games]
    hard = sorted([r for r in confident if r["win_rate"] < 45], key=lambda r: r["win_rate"])
    easy = sorted([r for r in confident if r["win_rate"] > 55], key=lambda r: -r["win_rate"])
    return {
        "available": bool(all_rows),
        "all": all_rows,
        "hard": hard,
        "easy": easy,
        "by_my_champion": {c: champ_rows(d) for c, d in by_my_champ.items()},
    }
