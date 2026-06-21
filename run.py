"""LoL account analyzer — entry point.

Usage:
    python run.py                      # uses config.json
    python run.py "Name#TAG" euw       # override account

Data source:
- If a Riot API key is available (RIOT_API_KEY env or riot_key.txt), uses the official
  API: all queues (incl. normals/ARAM), per-match habits (time-of-day, tilt) and live LP.
- Otherwise falls back to scraping op.gg (ranked aggregates only).

Cross-references a meta baseline (meta_cache.json), applies the analysis logic, stores a
snapshot for tracking, fetches recommended builds, and writes an HTML report.
"""
import json
import sys
import webbrowser
from pathlib import Path

try:  # nicer accents in the Windows console
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from lol_analyzer.collectors import opgg, ddragon, opgg_build, riot
from lol_analyzer.analysis.champions import analyze_champions
from lol_analyzer.analysis.habits import profile_from_overall, pool_discipline
from lol_analyzer.analysis import matches as matchlib
from lol_analyzer.analysis.recommend import build_recommendations
from lol_analyzer.report.render import render_html, console_summary
from lol_analyzer.store import db

ROOT = Path(__file__).resolve().parent

_RANK_QUEUE = {"RANKED_SOLO_5x5": "SOLORANKED", "RANKED_FLEX_SR": "FLEXRANKED"}


def load_config():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if len(sys.argv) > 1:
        cfg["riot_id"] = sys.argv[1]
    if len(sys.argv) > 2:
        cfg["region"] = sys.argv[2]
    return cfg


def load_meta():
    f = ROOT / "meta_cache.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("by_id", {}), data.get("patch", "?"), data.get("elo", "?")
    return {}, None, None


# ----------------------------- data sources -----------------------------
def gather_via_riot(cfg, key):
    """Returns (profile, focus_block, time_habits, queue_summary) or None on failure."""
    riot_id, region = cfg["riot_id"], cfg["region"]
    focus = cfg.get("focus_queue", "RANKED")
    name, tag = riot_id.split("#", 1)
    client = riot.RiotClient(key, region)

    acct = client.account(name, tag)
    puuid = acct["puuid"]
    summ = client.summoner(puuid)

    profile = {"riot_id": riot_id, "region": region, "ranks": {}, "level": summ.get("summonerLevel")}
    for e in client.league_entries(puuid):
        q = _RANK_QUEUE.get(e.get("queueType"))
        if q:
            w, l = e.get("wins", 0), e.get("losses", 0)
            profile["ranks"][q] = {
                "tier": e.get("tier"), "division": e.get("rank"), "lp": e.get("leaguePoints"),
                "win": w, "lose": l, "games": w + l,
                "win_rate": round(100 * w / max(1, w + l), 1)}

    max_total = cfg.get("match_count", 200)
    group = riot.QUEUE_GROUPS.get(focus)  # set of queue ids, or None for ALL

    # Fetch ids for the focus queue specifically, so a queue you rarely play (e.g. ranked)
    # still gets full coverage instead of being drowned out by normals.
    if group is None:
        focus_ids = client.match_ids(puuid, max_total=max_total)
    else:
        focus_ids = []
        for q in sorted(group):
            focus_ids += client.match_ids(puuid, queue=q, max_total=max_total)
        # match id suffix is monotonic in time -> sort to get the true most-recent N
        focus_ids = sorted(set(focus_ids),
                           key=lambda mid: int(mid.split("_")[-1]) if "_" in mid else 0,
                           reverse=True)[:max_total]

    print(f"  Riot API: {len(focus_ids)} partidas de {focus} (descargando, se cachean)...")
    focus_matches = [m for m in (client.match(mid) for mid in focus_ids) if m]
    focus_block = matchlib.to_champion_block(focus_matches, puuid, focus)
    time_habits = matchlib.time_habits(focus_matches, puuid, focus)

    # Per-queue counts (ids only -> cheap) so every queue is visible even if not the focus.
    queue_summary = []
    for grp in ("RANKED", "NORMAL", "ARAM"):
        cnt = sum(len(client.match_ids(puuid, queue=q, max_total=400))
                  for q in riot.QUEUE_GROUPS[grp])
        if cnt:
            queue_summary.append({"queue": grp, "count": cnt})

    return profile, focus_block, time_habits, queue_summary


def gather_via_opgg(cfg):
    riot_id, region = cfg["riot_id"], cfg["region"]
    profile = opgg.fetch_profile(riot_id, region)
    blocks = opgg.fetch_champion_stats(riot_id, region)
    if not blocks:
        return None
    focus = cfg.get("focus_queue", "RANKED")
    block = next((b for b in blocks if b["game_type"] == focus), None) or \
        max(blocks, key=lambda b: (b.get("overall") or {}).get("play", 0))
    return profile, block, {"available": False}, []


def collect_builds(champ_analysis, meta_by_id, elo):
    targets = [c for c in champ_analysis
               if c["verdict"] in ("main", "lean_in", "bench")
               or (c["confident"] and c["win_rate"] < 50)]
    builds = {}
    for c in targets[:8]:
        meta = meta_by_id.get(str(c["champion_id"])) or {}
        role = meta.get("role")
        if not role or not c.get("slug"):
            continue
        b = opgg_build.fetch_build(c["slug"], role, elo)
        if b:
            builds[c["name"]] = b
    return builds


def trend_text(riot_id, queue, overall):
    prev = db.previous_overall(riot_id, queue)
    if not prev or not overall:
        return None
    dwr = round((overall.get("win_rate") or 0) - (prev["win_rate"] or 0), 1)
    dgames = (overall.get("play") or 0) - (prev["play"] or 0)
    arrow = "▲" if dwr > 0 else ("▼" if dwr < 0 else "▬")
    return f"{arrow} {dwr:+.1f}% WR en {dgames} partidas nuevas"


def main():
    cfg = load_config()
    riot_id, region = cfg["riot_id"], cfg["region"]
    min_games = cfg.get("min_games_for_confidence", 10)
    champ_map = ddragon.champion_map()
    key = riot.load_key()

    print(f"Analizando {riot_id} ({region})  [fuente: {'Riot API' if key else 'op.gg'}]...")
    try:
        result = gather_via_riot(cfg, key) if key else gather_via_opgg(cfg)
    except riot.RiotError as e:
        print(f"  Riot API: {e}\n  Cayendo a op.gg (solo ranked)...")
        result = gather_via_opgg(cfg)

    if not result:
        print("No se pudieron obtener estadísticas (cuenta privada, sin partidas, o fuente caída).")
        return
    profile, block, time_habits, queue_summary = result
    overall = block.get("overall")

    db.save_snapshot(riot_id, [block], champ_map)

    meta_by_id, patch, elo = load_meta()
    champ_analysis = analyze_champions(block["champions"], champ_map, meta_by_id, min_games)
    habits = profile_from_overall(overall)
    pool = pool_discipline(block["champions"], min_games)
    recs = build_recommendations(champ_analysis, habits, pool, min_games, time_habits)
    builds = collect_builds(champ_analysis, meta_by_id, elo or "emerald_plus")

    meta_note = (f"Baseline de meta: parche {patch}, elo {elo} "
                 f"({sum(1 for c in champ_analysis if c['meta_win_rate'] is not None)} champs con dato meta)."
                 if meta_by_id else
                 "Sin meta_cache.json: el ROI vs meta aparece vacío.")

    ctx = {
        "profile": profile, "queue": block["game_type"], "season": block.get("season_id", 0),
        "overall": overall, "champions": champ_analysis, "habits": habits,
        "time_habits": time_habits, "queue_summary": queue_summary,
        "recommendations": recs, "trend": trend_text(riot_id, block["game_type"], overall),
        "meta_note": meta_note, "builds": builds,
        "source": "Riot API" if key else "op.gg",
    }

    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    html_path = out_dir / "report.html"
    html_path.write_text(render_html(ctx), encoding="utf-8")
    ctx["html_path"] = html_path
    print(console_summary(ctx))

    try:
        webbrowser.open(html_path.as_uri())
    except Exception:
        pass


if __name__ == "__main__":
    main()
