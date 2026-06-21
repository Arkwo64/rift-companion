"""Extract the user's ACTUAL builds from their matches (items, keystone, summoners) so
we can compare them against the meta build (op.gg). Uses data already in match-v5 —
no extra requests.
"""
from collections import defaultdict


def _wr(rec):
    return round(100 * rec["w"] / rec["g"]) if rec["g"] else 0


def analyze_my_builds(matches, puuid, champ_map, item_map, rune_map, spell_map,
                      queue_group_ids=None, min_games=6):
    """Return {champion_name: {...your build...}} for champs with >= min_games."""
    per = defaultdict(lambda: {
        "games": 0, "wins": 0,
        "items": defaultdict(lambda: {"g": 0, "w": 0}),
        "boots": defaultdict(lambda: {"g": 0, "w": 0}),
        "keystone": defaultdict(lambda: {"g": 0, "w": 0}),
        "spells": defaultdict(lambda: {"g": 0, "w": 0}),
    })

    for m in matches:
        info = m.get("info", {})
        if queue_group_ids is not None and info.get("queueId") not in queue_group_ids:
            continue
        me = next((p for p in info.get("participants", []) if p.get("puuid") == puuid), None)
        if not me:
            continue
        cid = me.get("championId")
        d = per[cid]
        win = bool(me.get("win"))
        d["games"] += 1
        d["wins"] += 1 if win else 0
        for i in range(7):
            iid = me.get(f"item{i}")
            meta = item_map.get(iid)
            if not meta:
                continue
            if meta["boots"]:
                bucket = d["boots"][iid]
            elif meta["completed"]:
                bucket = d["items"][iid]
            else:
                continue
            bucket["g"] += 1
            bucket["w"] += 1 if win else 0
        styles = me.get("perks", {}).get("styles", [])
        sel = styles[0].get("selections", []) if styles else []
        if sel:
            k = sel[0].get("perk")
            d["keystone"][k]["g"] += 1
            d["keystone"][k]["w"] += 1 if win else 0
        sp = tuple(sorted([me.get("summoner1Id"), me.get("summoner2Id")]))
        d["spells"][sp]["g"] += 1
        d["spells"][sp]["w"] += 1 if win else 0

    out = {}
    for cid, d in per.items():
        if d["games"] < min_games:
            continue
        name = champ_map.get(cid, {}).get("name", str(cid))

        def top_items(src, n):
            rows = sorted(src.items(), key=lambda kv: kv[1]["g"], reverse=True)[:n]
            return [{"id": iid, "name": item_map.get(iid, {}).get("name", str(iid)),
                     "games": r["g"], "win_rate": _wr(r)} for iid, r in rows]

        ks = max(d["keystone"].items(), key=lambda kv: kv[1]["g"], default=(None, {"g": 0, "w": 0}))
        sp = max(d["spells"].items(), key=lambda kv: kv[1]["g"], default=(None, {"g": 0, "w": 0}))
        out[name] = {
            "games": d["games"],
            "win_rate": round(100 * d["wins"] / d["games"]),
            "core": top_items(d["items"], 4),
            "boots": top_items(d["boots"], 1),
            "keystone": {"id": ks[0], "name": rune_map.get(ks[0], "—"),
                         "games": ks[1]["g"], "win_rate": _wr(ks[1])} if ks[0] else None,
            "summoners": {"names": " + ".join(spell_map.get(s, "?") for s in sp[0]),
                          "ids": list(sp[0])} if sp[0] else None,
        }
    return out


def item_winrates(matches, puuid, champ_map, item_map, min_champ_games=8, min_item_games=4):
    """Per champ, your win rate with each completed/boots item you build.

    CAVEAT: won games carry more finished items, so this is correlation, not causation —
    most useful for comparing item CHOICES. Guarded by min builds per item.
    """
    per = defaultdict(lambda: {"games": 0, "wins": 0, "items": defaultdict(lambda: [0, 0])})
    for m in matches:
        me = next((p for p in m.get("info", {}).get("participants", [])
                   if p.get("puuid") == puuid), None)
        if not me:
            continue
        d = per[me.get("championId")]
        win = bool(me.get("win"))
        d["games"] += 1
        d["wins"] += 1 if win else 0
        seen = set()
        for i in range(7):
            iid = me.get(f"item{i}")
            meta = item_map.get(iid)
            if not meta or iid in seen or not (meta["completed"] or meta["boots"]):
                continue
            seen.add(iid)
            d["items"][iid][0] += 1
            d["items"][iid][1] += 1 if win else 0

    out = []
    for cid, d in per.items():
        if d["games"] < min_champ_games:
            continue
        items = [{"id": iid, "name": item_map.get(iid, {}).get("name", str(iid)),
                  "games": v[0], "win_rate": round(100 * v[1] / v[0])}
                 for iid, v in d["items"].items() if v[0] >= min_item_games]
        if not items:
            continue
        items.sort(key=lambda x: (x["win_rate"], x["games"]), reverse=True)
        info = champ_map.get(cid, {})
        out.append({"champ": info.get("name", str(cid)), "id_name": info.get("id_name", ""),
                    "games": d["games"], "win_rate": round(100 * d["wins"] / d["games"]),
                    "items": items})
    out.sort(key=lambda c: c["games"], reverse=True)
    return out


def compare_to_meta(my_build, meta_build):
    """Return a list of human diffs between the user's build and the op.gg meta build."""
    diffs = []
    if not my_build or not meta_build:
        return diffs
    mk = (my_build.get("keystone") or {}).get("name")
    metak = (meta_build.get("runes") or {}).get("keystone")
    if mk and metak and mk != metak:
        wr = (my_build.get("keystone") or {}).get("win_rate")
        diffs.append(f"Runa: tú llevas {mk} ({wr}% WR), el meta {metak}.")
    my_core = {i["name"] for i in my_build.get("core", [])[:3]}
    meta_core_names = [i["name"] for i in (meta_build.get("items") or {}).get("core", [])[:3]]
    missing = [c for c in meta_core_names if c not in my_core]
    extra = [i["name"] for i in my_build.get("core", [])[:3] if i["name"] not in meta_core_names]
    if missing:
        diffs.append("Items del meta que casi no compras: " + ", ".join(missing) + ".")
    if extra:
        diffs.append("Items tuyos que no están en el core meta: " + ", ".join(extra) + ".")
    return diffs
