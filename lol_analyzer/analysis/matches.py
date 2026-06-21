"""Turn raw Riot match-v5 data into (a) per-champion blocks compatible with the existing
champion analysis and (b) a per-match habit profile (time-of-day, tilt streaks).
"""
import time
from collections import defaultdict

from ..collectors.riot import QUEUE_NAMES, QUEUE_GROUPS
from .. import ranks as ranklib
from . import premades as premadelib

_RIOT_ROLE = {"TOP": "top", "JUNGLE": "jungle", "MIDDLE": "mid",
              "BOTTOM": "adc", "UTILITY": "support"}
QUEUE_FRIENDLY = {420: "Ranked Solo", 440: "Ranked Flex", 400: "Normal", 430: "Normal",
                  490: "Quickplay", 480: "Swiftplay", 450: "ARAM", 700: "Clash",
                  1700: "Arena", 1900: "URF"}


def _me(match, puuid):
    info = match.get("info", {})
    parts = info.get("participants", [])
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if not me:
        return None, None, None
    team_kills = sum(p.get("kills", 0) for p in parts if p.get("teamId") == me.get("teamId"))
    team_dmg = sum(p.get("totalDamageDealtToChampions", 0) for p in parts if p.get("teamId") == me.get("teamId"))
    return me, team_kills, team_dmg


def _duration_min(info):
    d = info.get("gameDuration", 0)
    if d > 100000:  # legacy milliseconds
        d /= 1000.0
    return max(1.0, d / 60.0)


def filter_matches(matches, queue_group):
    qids = QUEUE_GROUPS.get(queue_group)
    if qids is None:
        return matches
    return [m for m in matches if m.get("info", {}).get("queueId") in qids]


def to_champion_block(matches, puuid, queue_group):
    """Aggregate matches into one block: {game_type, overall, champions:[...]}.

    Field names mirror the op.gg collector so analysis/champions.py and habits.py work
    unchanged. op_score / lane_lead / snowball are absent in match-v5 -> left None.
    """
    sel = filter_matches(matches, queue_group)
    agg = defaultdict(lambda: dict(play=0, win=0, lose=0, k=0, d=0, a=0,
                                   cs=0.0, kp=0.0, vis=0.0, dmgshare=0.0,
                                   dbl=0, trp=0, quad=0, penta=0))

    def add(bucket, me, tk, td, dur):
        bucket["play"] += 1
        bucket["win"] += 1 if me.get("win") else 0
        bucket["lose"] += 0 if me.get("win") else 1
        bucket["k"] += me.get("kills", 0)
        bucket["d"] += me.get("deaths", 0)
        bucket["a"] += me.get("assists", 0)
        cs = me.get("totalMinionsKilled", 0) + me.get("neutralMinionsKilled", 0)
        bucket["cs"] += cs / dur
        bucket["kp"] += (100 * (me.get("kills", 0) + me.get("assists", 0)) / tk) if tk else 0
        bucket["vis"] += me.get("visionScore", 0)
        bucket["dmgshare"] += (100 * me.get("totalDamageDealtToChampions", 0) / td) if td else 0
        bucket["dbl"] += me.get("doubleKills", 0)
        bucket["trp"] += me.get("tripleKills", 0)
        bucket["quad"] += me.get("quadraKills", 0)
        bucket["penta"] += me.get("pentaKills", 0)

    overall = agg[0]
    for m in sel:
        me, tk, td = _me(m, puuid)
        if not me:
            continue
        dur = _duration_min(m["info"])
        cid = me.get("championId", 0)
        add(agg[cid], me, tk, td, dur)
        add(overall, me, tk, td, dur)

    def finalize(cid, b):
        n = b["play"] or 1
        deaths = b["d"]
        kda = round((b["k"] + b["a"]) / max(1, deaths), 2)
        return {
            "id": cid, "play": b["play"], "win": b["win"], "lose": b["lose"],
            "win_rate": round(100 * b["win"] / n, 1),
            "kda": {"kda": kda, "kill": b["k"], "death": deaths, "assist": b["a"],
                    "avg_kill": round(b["k"] / n, 1), "avg_death": round(deaths / n, 1),
                    "avg_assist": round(b["a"] / n, 1)},
            "cs_per_min": round(b["cs"] / n, 1),
            "kill_participation": round(b["kp"] / n, 0),
            "vision_score": round(b["vis"] / n, 0),
            "damage_dealt_share": round(b["dmgshare"] / n, 0),
            "double_kill": b["dbl"], "triple_kill": b["trp"],
            "quadra_kill": b["quad"], "penta_kill": b["penta"],
            "op_score": None, "snowball_hit_ratio": None, "lane_lead": None,
        }

    champions = [finalize(cid, b) for cid, b in agg.items() if cid != 0 and b["play"] > 0]
    champions.sort(key=lambda c: c["play"], reverse=True)
    return {
        "game_type": queue_group,
        "season_id": 0,
        "overall": finalize(0, overall) if overall["play"] else None,
        "champions": champions,
    }


# ----------------------------- habits over time -----------------------------
_DAY_BUCKETS = [("Madrugada (0-6h)", 0, 6), ("Mañana (6-12h)", 6, 12),
                ("Tarde (12-18h)", 12, 18), ("Noche (18-24h)", 18, 24)]
_WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def recent_matches(matches, puuid, champ_map, n=25, rank_map=None, pair_index=None):
    """Flat list of the user's most recent games (any queue) for the History tab."""
    rank_map = rank_map or {}
    rows = []
    for m in matches:
        info = m.get("info", {})
        parts = info.get("participants", [])
        me = next((p for p in parts if p.get("puuid") == puuid), None)
        if not me:
            continue
        enemy_ranks = [rank_map.get(p.get("puuid")) for p in parts
                       if p.get("teamId") != me.get("teamId")] if rank_map else []
        pos = me.get("teamPosition") or ""
        opp = next((p for p in parts if p.get("teamId") != me.get("teamId")
                    and p.get("teamPosition") == pos and pos), None)
        ts = info.get("gameStartTimestamp") or info.get("gameCreation") or 0
        dur = _duration_min(info)
        cs = me.get("totalMinionsKilled", 0) + me.get("neutralMinionsKilled", 0)
        cid = me.get("championId")
        lt = time.localtime(ts / 1000) if ts else None
        k, d, a = me.get("kills", 0), me.get("deaths", 0), me.get("assists", 0)
        rows.append({
            "ts": ts,
            "match_id": m.get("metadata", {}).get("matchId"),
            "date": time.strftime("%d/%m %H:%M", lt) if lt else "",
            "queue": QUEUE_FRIENDLY.get(info.get("queueId"), "Otro"),
            "champion": champ_map.get(cid, {}).get("name", me.get("championName")),
            "champion_icon": me.get("championName"),
            "win": bool(me.get("win")),
            "k": k, "d": d, "a": a,
            "kda": round((k + a) / max(1, d), 2),
            "cs": cs, "cs_per_min": round(cs / dur, 1),
            "duration_min": round(dur),
            "role": _RIOT_ROLE.get(pos, ""),
            "opponent": (champ_map.get(opp.get("championId"), {}).get("name", opp.get("championName"))
                         if opp else None),
            "opponent_icon": opp.get("championName") if opp else None,
            "avg_enemy_rank": ranklib.average(enemy_ranks),
            "premades": premadelib.my_premates(m, puuid, pair_index) if pair_index else [],
        })
    rows.sort(key=lambda r: r["ts"], reverse=True)
    for r in rows:
        r.pop("ts", None)
    return rows[:n]


_ROLE_ORDER = {"TOP": 0, "JUNGLE": 1, "MIDDLE": 2, "BOTTOM": 3, "UTILITY": 4}


def parse_early_game(match, timeline, puuid, minute=15):
    """From a match + its timeline, your gold/CS/XP lead over your lane opponent at `minute`."""
    info = match.get("info", {})
    parts = info.get("participants", [])
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if not me:
        return None
    pos = me.get("teamPosition")
    opp = next((p for p in parts if p.get("teamId") != me.get("teamId")
                and p.get("teamPosition") == pos and pos), None)
    frames = timeline.get("info", {}).get("frames", [])
    if not frames:
        return None
    frame = frames[minute] if len(frames) > minute else frames[-1]
    pf = frame.get("participantFrames", {})
    mf = pf.get(str(me.get("participantId")))
    if not mf:
        return None

    def cs(f):
        return f.get("minionsKilled", 0) + f.get("jungleMinionsKilled", 0)

    res = {"win": bool(me.get("win"))}
    of = pf.get(str(opp.get("participantId"))) if opp else None
    if of:
        res["gold_diff"] = mf.get("totalGold", 0) - of.get("totalGold", 0)
        res["cs_diff"] = cs(mf) - cs(of)
        res["xp_diff"] = mf.get("xp", 0) - of.get("xp", 0)
    return res


def early_game_profile(early_list):
    """Aggregate early-game leads + the snowball signal (WR ahead@15 vs behind@15)."""
    wd = [e for e in early_list if e and e.get("gold_diff") is not None]
    n = len(wd)
    if not n:
        return {"available": False}
    ahead = [e for e in wd if e["gold_diff"] > 0]
    behind = [e for e in wd if e["gold_diff"] < 0]

    def wr(items):
        return round(100 * sum(1 for e in items if e["win"]) / len(items)) if items else None

    return {
        "available": True, "games": n,
        "avg_gold_diff": round(sum(e["gold_diff"] for e in wd) / n),
        "avg_cs_diff": round(sum(e.get("cs_diff", 0) for e in wd) / n, 1),
        "pct_ahead": round(100 * len(ahead) / n),
        "wr_ahead": wr(ahead), "wr_behind": wr(behind),
        "ahead_games": len(ahead), "behind_games": len(behind),
    }


def match_detail(match, puuid, champ_map=None, rank_map=None, pair_index=None):
    """Full scoreboard of one match (both teams) for the history drill-down."""
    info = match.get("info", {})
    parts = info.get("participants", [])
    champ_map = champ_map or {}
    rank_map = rank_map or {}
    groups = premadelib.premade_groups(parts, pair_index) if pair_index else {}

    def player(p):
        cs = p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0)
        cid = p.get("championId")
        return {
            "champion": champ_map.get(cid, {}).get("name", p.get("championName")),
            "champion_icon": p.get("championName"),
            "name": p.get("riotIdGameName") or p.get("summonerName") or "",
            "rank": ranklib.short(rank_map.get(p.get("puuid"))),
            "premade_group": groups.get(p.get("puuid")),
            "k": p.get("kills", 0), "d": p.get("deaths", 0), "a": p.get("assists", 0),
            "cs": cs,
            "items": [p.get(f"item{i}") for i in range(6)],
            "trinket": p.get("item6"),
            "spells": [p.get("summoner1Id"), p.get("summoner2Id")],
            "role": p.get("teamPosition", ""),
            "is_me": p.get("puuid") == puuid,
        }

    teams = {100: [], 200: []}
    for p in parts:
        teams.setdefault(p.get("teamId"), []).append(p)
    for tid in teams:
        teams[tid].sort(key=lambda p: _ROLE_ORDER.get(p.get("teamPosition"), 9))
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    return {
        "queue": QUEUE_FRIENDLY.get(info.get("queueId"), "Otro"),
        "duration_min": round(_duration_min(info)),
        "win": bool(me.get("win")) if me else None,
        "my_team": me.get("teamId") if me else 100,
        "teams": [[player(p) for p in teams.get(100, [])],
                  [player(p) for p in teams.get(200, [])]],
    }


def recent_form(matches, puuid, queue_group, n=10):
    """Last n results (True=win) for a queue, most recent first — for the form dots."""
    qids = QUEUE_GROUPS.get(queue_group)
    res = []
    for m in matches:
        info = m.get("info", {})
        if qids is not None and info.get("queueId") not in qids:
            continue
        me = next((p for p in info.get("participants", []) if p.get("puuid") == puuid), None)
        if not me:
            continue
        ts = info.get("gameStartTimestamp") or info.get("gameCreation") or 0
        res.append((ts, bool(me.get("win"))))
    res.sort(key=lambda r: r[0], reverse=True)
    return [w for _, w in res[:n]]


def time_habits(matches, puuid, queue_group="ALL"):
    """Time-of-day / weekday form and tilt (loss-streak) effects from match timestamps."""
    sel = filter_matches(matches, queue_group)
    rows = []
    for m in sel:
        info = m.get("info", {})
        me, _, _ = _me(m, puuid)
        if not me:
            continue
        ts = info.get("gameStartTimestamp") or info.get("gameCreation")
        if not ts:
            continue
        lt = time.localtime(ts / 1000)
        rows.append({"t": ts, "hour": lt.tm_hour, "wday": lt.tm_wday, "win": bool(me.get("win"))})
    if not rows:
        return {"available": False}
    rows.sort(key=lambda r: r["t"])

    def wr(items):
        n = len(items)
        return (round(100 * sum(1 for x in items if x["win"]) / n, 0), n) if n else (None, 0)

    daypart = []
    for label, lo, hi in _DAY_BUCKETS:
        sub = [r for r in rows if lo <= r["hour"] < hi]
        w, n = wr(sub)
        if n:
            daypart.append({"label": label, "win_rate": w, "games": n})

    weekday = []
    for i, name in enumerate(_WEEKDAYS):
        sub = [r for r in rows if r["wday"] == i]
        w, n = wr(sub)
        if n:
            weekday.append({"label": name, "win_rate": w, "games": n})

    # Tilt: outcome of the game played right after a loss / after a 2+ loss streak
    after_loss, after_streak2 = [], []
    streak = 0
    longest_loss = cur = 0
    for i, r in enumerate(rows):
        if i > 0:
            if rows[i - 1]["win"] is False:
                after_loss.append(r)
            if streak >= 2:
                after_streak2.append(r)
        streak = streak + 1 if r["win"] is False else 0
        cur = streak
        longest_loss = max(longest_loss, streak)

    base_w, base_n = wr(rows)
    al_w, al_n = wr(after_loss)
    as_w, as_n = wr(after_streak2)
    return {
        "available": True, "total": base_n, "base_win_rate": base_w,
        "daypart": daypart, "weekday": weekday,
        "after_loss": {"win_rate": al_w, "games": al_n},
        "after_streak2": {"win_rate": as_w, "games": as_n},
        "longest_loss_streak": longest_loss,
        "current_loss_streak": cur,
    }
