"""Find the people you queue with most (premades) and your record together.

All from match-v5: each participant carries a puuid + Riot ID, so recurring teammates
on your team = your duos/premades. Also seeds synergy data (your champ + their champ WR).
"""
from collections import defaultdict


def analyze_teammates(matches, puuid, champ_map, min_games=3, top=12):
    idname2name = {v.get("id_name"): v.get("name") for v in champ_map.values()}

    def disp(champ_name):  # id-form ("AurelionSol") -> display ("Aurelion Sol")
        return idname2name.get(champ_name, champ_name)

    total_g = total_w = 0
    per = {}
    for m in matches:
        info = m.get("info", {})
        parts = info.get("participants", [])
        me = next((p for p in parts if p.get("puuid") == puuid), None)
        if not me:
            continue
        total_g += 1
        win = bool(me.get("win"))
        total_w += 1 if win else 0
        my_champ = me.get("championName")
        for p in parts:
            if p.get("teamId") != me.get("teamId") or p.get("puuid") == puuid:
                continue
            r = per.setdefault(p.get("puuid"), {
                "name": "", "tag": "", "games": 0, "wins": 0,
                "their": defaultdict(int), "mine": defaultdict(lambda: [0, 0]),
                "pairs": defaultdict(lambda: [0, 0])})
            r["name"] = p.get("riotIdGameName") or p.get("summonerName") or "?"
            r["tag"] = p.get("riotIdTagline") or ""
            r["games"] += 1
            r["wins"] += 1 if win else 0
            tc = p.get("championName")
            r["their"][tc] += 1
            r["mine"][my_champ][0] += 1
            r["mine"][my_champ][1] += 1 if win else 0
            pk = (my_champ, tc)
            r["pairs"][pk][0] += 1
            r["pairs"][pk][1] += 1 if win else 0

    base_wr = round(100 * total_w / total_g) if total_g else 0
    out, all_duos = [], []
    for r in per.values():
        g = r["games"]
        if g < min_games:
            continue
        w = r["wins"]
        wo_g, wo_w = total_g - g, total_w - w
        their = sorted(r["their"].items(), key=lambda kv: kv[1], reverse=True)[:5]
        syn = sorted(r["pairs"].items(), key=lambda kv: kv[1][0], reverse=True)
        synergies = [{"my_champ": disp(mk[0]), "my_icon": mk[0],
                      "their_champ": disp(mk[1]), "their_icon": mk[1],
                      "games": v[0], "win_rate": round(100 * v[1] / v[0])}
                     for mk, v in syn if v[0] >= 2][:6]
        my_champs = [{"champ": disp(c), "icon": c, "games": v[0],
                      "win_rate": round(100 * v[1] / v[0])}
                     for c, v in sorted(r["mine"].items(), key=lambda kv: kv[1][0], reverse=True)[:5]]
        # Best combo: highest WR pairing with a real sample (>=3, fallback >=2).
        combos = [s for s in synergies if s["games"] >= 3] or [s for s in synergies if s["games"] >= 2]
        best = max(combos, key=lambda s: (s["win_rate"], s["games"]), default=None)
        name = r["name"]
        out.append({
            "name": name, "tag": r["tag"],
            "games": g, "wins": w, "lose": g - w,
            "win_rate": round(100 * w / g),
            "wr_without": round(100 * wo_w / wo_g) if wo_g else None,
            "their_champs": [{"champ": disp(c), "icon": c, "games": n} for c, n in their],
            "my_champs": my_champs,
            "synergies": synergies,
            "best_combo": best,
        })
        for s in synergies:
            if s["games"] >= 4:
                all_duos.append({**s, "mate": name})
    out.sort(key=lambda x: x["games"], reverse=True)
    all_duos.sort(key=lambda s: (s["win_rate"], s["games"]), reverse=True)
    return {"base_win_rate": base_wr, "list": out[:top], "best_duos": all_duos[:6]}
