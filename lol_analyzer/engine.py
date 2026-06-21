"""Analysis engine: fetch once, analyze every queue. Produces a JSON-serializable
payload consumed by both the static report and the local web app.
"""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import ranks as ranklib
from .collectors import ddragon, opgg_build, riot
from .analysis.champions import analyze_champions
from .analysis.habits import profile_from_overall, pool_discipline
from .analysis import matches as matchlib
from .analysis import matchups as matchuplib
from .analysis import mybuilds as mybuildlib
from .analysis import teammates as teamlib
from .analysis import premades as premadelib
from .analysis.recommend import build_recommendations

ROOT = Path(__file__).resolve().parent.parent
_RANK_QUEUE = {"RANKED_SOLO_5x5": "SOLORANKED", "RANKED_FLEX_SR": "FLEXRANKED"}
VIEWS = ["RANKED_SOLO", "RANKED_FLEX", "NORMAL", "ALL"]


def load_meta():
    f = ROOT / "meta_cache.json"
    if f.exists():
        d = json.loads(f.read_text(encoding="utf-8"))
        return d.get("by_id", {}), d.get("patch", "?"), d.get("elo", "emerald_plus")
    return {}, None, "emerald_plus"


def gather(cfg, key, log=print):
    """Fetch profile + all matches (ranked/normal/aram) once. Returns a dataset dict."""
    riot_id, region = cfg["riot_id"], cfg["region"]
    max_total = cfg.get("match_count", 200)
    name, tag = riot_id.split("#", 1)
    client = riot.RiotClient(key, region)

    acct = client.account(name, tag)
    puuid = acct["puuid"]
    summ = client.summoner(puuid)
    profile = {"riot_id": riot_id, "region": region, "ranks": {},
               "level": summ.get("summonerLevel")}
    for e in client.league_entries(puuid):
        q = _RANK_QUEUE.get(e.get("queueType"))
        if q:
            w, l = e.get("wins", 0), e.get("losses", 0)
            profile["ranks"][q] = {
                "tier": e.get("tier"), "division": e.get("rank"), "lp": e.get("leaguePoints"),
                "win": w, "lose": l, "games": w + l,
                "win_rate": round(100 * w / max(1, w + l), 1)}

    # Collect ids per queue group, dedupe, then fetch details (cached on disk).
    # 1) Discover recent matches per queue (to find new games + backfill history).
    id_set = {}
    for grp in ("RANKED_SOLO", "RANKED_FLEX", "NORMAL", "ARAM"):
        gids = []
        for q in sorted(riot.QUEUE_GROUPS[grp]):
            gids += client.match_ids(puuid, queue=q, max_total=max_total)
        for mid in gids:
            id_set[mid] = True

    # 2) Union with EVERYTHING we've ever cached, so the dataset only grows — old
    #    games are never dropped from the analysis (your data accumulates over time).
    if riot.MATCH_CACHE.exists():
        for f in riot.MATCH_CACHE.glob("*.json"):
            id_set[f.stem] = True

    ids = list(id_set)
    log(f"  Riot API: {len(ids)} partidas en el dataset (acumulado, descargando nuevas)...")
    all_matches = [m for m in (client.match(mid) for mid in ids)
                   if m and puuid in m.get("metadata", {}).get("participants", [])]

    # 3) Queue counts reflect the full accumulated dataset.
    qc = Counter()
    for m in all_matches:
        qid = m.get("info", {}).get("queueId")
        for grp in ("RANKED_SOLO", "RANKED_FLEX", "NORMAL", "ARAM"):
            if qid in riot.QUEUE_GROUPS[grp]:
                qc[grp] += 1
    counts = [{"queue": g, "count": qc[g]}
              for g in ("RANKED_SOLO", "RANKED_FLEX", "NORMAL", "ARAM") if qc[g]]

    roles = matchuplib.infer_roles(all_matches, puuid)
    champ_map = ddragon.champion_map()
    meta_by_id, patch, elo = load_meta()

    # Pre-fetch builds for champs the user actually plays (using their real role).
    builds = _collect_builds(all_matches, puuid, champ_map, roles, elo,
                             cfg.get("min_games_for_confidence", 10), log)

    # The user's ACTUAL builds (from match data) for the vs-meta comparison.
    my_builds = mybuildlib.analyze_my_builds(
        all_matches, puuid, champ_map, ddragon.item_map(), ddragon.rune_map(),
        ddragon.summoner_map(), min_games=max(5, cfg.get("min_games_for_confidence", 10) // 2))

    # Early-game leads & snowball need match timelines (extra calls, cached forever).
    early_by_match = _collect_timelines(client, all_matches, puuid,
                                        cfg.get("timeline_count", 150), log)

    # Solo/Duo rank of everyone in your recent games (cached 24h), for the History tab.
    rank_n = cfg.get("rank_match_count", 25)
    recent = sorted(all_matches, key=lambda m: m.get("info", {}).get("gameStartTimestamp", 0),
                    reverse=True)[:rank_n]
    rank_puuids = {p.get("puuid") for m in recent
                   for p in m.get("info", {}).get("participants", [])}
    rank_map = client.solo_ranks(rank_puuids, log=log)
    enemy_ranks = []
    for m in recent:
        parts = m.get("info", {}).get("participants", [])
        me = next((p for p in parts if p.get("puuid") == puuid), None)
        if not me:
            continue
        enemy_ranks += [rank_map.get(p.get("puuid")) for p in parts
                        if p.get("teamId") != me.get("teamId")]
    opponents_avg_rank = ranklib.average(enemy_ranks)
    pair_index = premadelib.build_pair_index(all_matches)

    return {
        "profile": profile, "puuid": puuid, "matches": all_matches, "roles": roles,
        "champ_map": champ_map, "meta_by_id": meta_by_id, "patch": patch, "elo": elo,
        "queue_counts": counts, "builds": builds, "my_builds": my_builds,
        "early_by_match": early_by_match, "rank_map": rank_map,
        "opponents_avg_rank": opponents_avg_rank, "pair_index": pair_index, "cfg": cfg,
    }


def live_game(client, puuid, champ_map, pair_index, rank_ttl_hours=6):
    """Build the live-game lobby view (Spectator) with ranks and inferred premades."""
    g = client.active_game(puuid)
    if not g:
        return {"in_game": False}
    if g.get("_unavailable"):
        return {"in_game": False, "unavailable": True}
    parts = g.get("participants", [])
    ranks = client.solo_ranks([p.get("puuid") for p in parts if p.get("puuid")],
                              ttl_hours=rank_ttl_hours)
    groups = premadelib.premade_groups(parts, pair_index)

    def player(p):
        info = champ_map.get(p.get("championId"), {})
        rid = p.get("riotId") or p.get("summonerName") or ""
        return {"champion": info.get("name", str(p.get("championId"))),
                "champion_icon": info.get("id_name", ""),
                "name": rid.split("#")[0] if rid else "",
                "rank": ranklib.short(ranks.get(p.get("puuid"))),
                "spells": [p.get("spell1Id"), p.get("spell2Id")],
                "is_me": p.get("puuid") == puuid, "team": p.get("teamId"),
                "premade_group": groups.get(p.get("puuid"))}

    players = [player(p) for p in parts]
    bans = [{"champion_icon": champ_map.get(b.get("championId"), {}).get("id_name", ""),
             "team": b.get("teamId")}
            for b in g.get("bannedChampions", []) if b.get("championId", -1) > 0]

    def team_avg(tid):
        return ranklib.average([ranks.get(p.get("puuid")) for p in parts
                                if p.get("teamId") == tid])
    return {
        "in_game": True,
        "queue": matchlib.QUEUE_FRIENDLY.get(g.get("gameQueueConfigId"), "Partida"),
        "length_min": round(g.get("gameLength", 0) / 60),
        "teams": [[p for p in players if p["team"] == 100],
                  [p for p in players if p["team"] == 200]],
        "avg_rank": [team_avg(100), team_avg(200)],
        "bans": bans,
    }


def _collect_timelines(client, matches, puuid, limit, log):
    by_id = {m.get("metadata", {}).get("matchId"): m for m in matches}
    recent = sorted(matches, key=lambda m: m.get("info", {}).get("gameStartTimestamp", 0),
                    reverse=True)[:limit]
    log(f"  Timelines: hasta {len(recent)} partidas (juego temprano, se cachean)...")
    early = {}
    for m in recent:
        mid = m.get("metadata", {}).get("matchId")
        tl = client.match_timeline(mid)
        if tl:
            e = matchlib.parse_early_game(by_id[mid], tl, puuid)
            if e:
                early[mid] = e
    return early


def _collect_builds(matches, puuid, champ_map, roles, elo, min_games, log):
    # champs played enough overall to be worth a build
    from collections import Counter
    plays = Counter()
    for m in matches:
        me = next((p for p in m.get("info", {}).get("participants", [])
                   if p.get("puuid") == puuid), None)
        if me:
            plays[me.get("championId")] += 1
    targets = [cid for cid, n in plays.most_common() if n >= max(5, min_games // 2)]
    builds = {}
    log(f"  Builds: trayendo recomendaciones para {min(len(targets), 14)} champs...")
    for cid in targets[:14]:
        info = champ_map.get(cid, {})
        role = roles.get(cid)
        slug = info.get("slug")
        if not role or not slug:
            continue
        b = opgg_build.fetch_build(slug, role, elo)
        if b:
            builds[info.get("name", str(cid))] = b
    return builds


def analyze_queue(dataset, queue):
    cfg = dataset["cfg"]
    min_games = cfg.get("min_games_for_confidence", 10)
    matches, puuid = dataset["matches"], dataset["puuid"]

    block = matchlib.to_champion_block(matches, puuid, queue)
    overall = block.get("overall")
    champ_analysis = analyze_champions(block["champions"], dataset["champ_map"],
                                       dataset["meta_by_id"], min_games)
    habits = profile_from_overall(overall)
    pool = pool_discipline(block["champions"], min_games)
    th = matchlib.time_habits(matches, puuid, queue)
    mu = matchuplib.analyze_matchups(matches, puuid, queue, min_games=max(4, min_games // 2))

    qids = {m.get("metadata", {}).get("matchId")
            for m in matchlib.filter_matches(matches, queue)}
    early = [e for mid, e in dataset.get("early_by_match", {}).items() if mid in qids]
    early_profile = matchlib.early_game_profile(early)

    recs = build_recommendations(champ_analysis, habits, pool, min_games, th)
    # surface matchup-driven advice
    for r in mu["hard"][:3]:
        recs["habits"].append(
            f"Matchup difícil: vs {r['enemy']} vas {r['win_rate']}% en {r['games']} — "
            f"banéalo o practica ese enfrentamiento.")
    recs["habits"].extend(_early_tips(early_profile))

    return {
        "queue": queue,
        "form": matchlib.recent_form(matches, puuid, queue, 10),
        "early_game": early_profile,
        "overall": {"play": overall["play"], "win": overall["win"],
                    "lose": overall["lose"], "win_rate": round(overall["win_rate"], 1)} if overall else None,
        "champions": champ_analysis,
        "recommendations": recs,
        "habits": habits,
        "time_habits": th,
        "matchups": mu,
    }


def _early_tips(e):
    if not e or not e.get("available") or e["games"] < 10:
        return []
    tips = []
    g = e["avg_gold_diff"]
    if g <= -250:
        tips.append(f"Sueles ir por detrás en línea: {g} oro vs tu rival al min 15. "
                    f"Céntrate en farmear seguro y no morir en fase de líneas.")
    elif g >= 250:
        tips.append(f"Dominas la línea (+{g} oro al min 15): aprovéchalo para forzar objetivos antes.")
    wa, wb = e.get("wr_ahead"), e.get("wr_behind")
    if wa is not None and wb is not None and e["ahead_games"] >= 6 and e["behind_games"] >= 6:
        if wa - wb >= 25 and wb <= 38:
            tips.append(f"Dependes mucho del snowball: yendo por delante a 15 ganas {wa}%, "
                        f"por detrás solo {wb}%. Practica remontar (objetivos, no forzar peleas perdidas).")
    # Note: "remontas bien" (a positive) is surfaced in the summary strengths, not here.
    return tips


def build_payload(dataset):
    meta_by_id = dataset["meta_by_id"]
    n_meta = sum(1 for v in meta_by_id.values() if v.get("meta_win_rate") is not None)
    meta_note = (f"Baseline de meta: parche {dataset['patch']}, elo {dataset['elo']} "
                 f"({n_meta} champs con dato meta)." if meta_by_id else
                 "Sin meta_cache.json: ROI vs meta vacío.")
    my_builds = dataset["my_builds"]
    build_diffs = {name: mybuildlib.compare_to_meta(mb, dataset["builds"].get(name))
                   for name, mb in my_builds.items()}
    item_wr = mybuildlib.item_winrates(dataset["matches"], dataset["puuid"],
                                       dataset["champ_map"], ddragon.item_map())
    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "Riot API",
        "ddragon_version": ddragon.current_version(),
        "rune_icons": {str(k): v for k, v in ddragon.rune_icon_map().items()},
        "spell_icons": {str(k): v for k, v in ddragon.spell_icon_map().items()},
        "profile": dataset["profile"],
        "queue_counts": dataset["queue_counts"],
        "meta_note": meta_note,
        "builds": dataset["builds"],
        "my_builds": my_builds,
        "build_diffs": build_diffs,
        "item_winrates": item_wr,
        "opponents_avg_rank": dataset.get("opponents_avg_rank"),
        "recent_matches": matchlib.recent_matches(
            dataset["matches"], dataset["puuid"], dataset["champ_map"], 25,
            rank_map=dataset.get("rank_map"), pair_index=dataset.get("pair_index")),
        "teammates": teamlib.analyze_teammates(
            dataset["matches"], dataset["puuid"], dataset["champ_map"]),
        "queues": {q: analyze_queue(dataset, q) for q in VIEWS},
    }
