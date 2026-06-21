"""Collect a summoner's data from op.gg.

op.gg's JSON API (c-lol-web.op.gg) is WAF-blocked for server-side clients, but the
App Router pages embed all rendered data as RSC chunks (`self.__next_f.push(...)`).
We pull those chunks and parse the structures we need. This is more stable than the
HTML layout because it is the data payload, not the markup.
"""
import json
import re

from ..http import get


def _riot_id_slug(riot_id):
    # "MarcoRubio#5570" -> "MarcoRubio-5570"
    return riot_id.replace("#", "-")


def _rsc_blob(html):
    """Concatenate and unescape all RSC payload chunks from an op.gg App Router page."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
    return "".join(chunks).encode().decode("unicode_escape", "replace")


def _extract_array(text, start):
    """Extract a balanced [...] beginning at index `start` (text[start] == '[')."""
    depth = 0
    in_str = False
    esc = False
    i = start
    while i < len(text):
        c = text[i]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def fetch_champion_stats(riot_id, region):
    """Return per-champion aggregate stats grouped by queue/season.

    Output: list of dicts {game_type, season_id, overall, champions:[...]}.
    Each champion entry carries play/win/lose/win_rate/kda/cs/gold/damage/vision/
    op_score/snowball/multikill fields as op.gg computes them.
    """
    slug = _riot_id_slug(riot_id)
    url = f"https://www.op.gg/summoners/{region}/{slug}/champions"
    html = get(url, referer=f"https://www.op.gg/summoners/{region}/{slug}",
               cache_minutes=30)
    blob = _rsc_blob(html)

    blocks = []
    seen = set()
    for m in re.finditer(r'"game_type":"([A-Z_]+)","season_id":(\d+),'
                         r'"play":\d+,"win":\d+,"lose":\d+,"my_champion_stats":', blob):
        game_type = m.group(1)
        season_id = int(m.group(2))
        arr_start = blob.index("[", m.end() - 1)
        arr_text = _extract_array(blob, arr_start)
        if not arr_text:
            continue
        try:
            champ_list = json.loads(arr_text)
        except json.JSONDecodeError:
            continue
        key = (game_type, season_id)
        if key in seen:  # RSC renders each block twice
            continue
        seen.add(key)

        overall = next((c for c in champ_list if c.get("id") == 0), None)
        champions = [c for c in champ_list if c.get("id", 0) != 0 and c.get("play", 0) > 0]
        blocks.append({
            "game_type": game_type,
            "season_id": season_id,
            "overall": overall,
            "champions": champions,
        })
    return blocks


def fetch_profile(riot_id, region):
    """Return rank/level summary from the main profile page RSC."""
    slug = _riot_id_slug(riot_id)
    url = f"https://www.op.gg/summoners/{region}/{slug}"
    html = get(url, cache_minutes=30)
    blob = _rsc_blob(html)

    profile = {"riot_id": riot_id, "region": region, "ranks": {}, "level": None}

    lvl = re.search(r'"level":(\d+),"profile_image_url"', blob)
    if lvl:
        profile["level"] = int(lvl.group(1))

    # Ranked tier blocks: {"queue_info":{"game_type":"SOLORANKED"...},"tier_info":{"tier":"EMERALD","division":4,"lp":41,...}}
    for m in re.finditer(
        r'"game_type":"(SOLORANKED|FLEXRANKED)".*?"tier_info":\{"tier":"?([A-Z]+)"?,'
        r'"division":(\d+),"lp":(\d+).*?"win":(\d+),"lose":(\d+)', blob):
        queue, tier, div, lp, win, lose = m.groups()
        profile["ranks"][queue] = {
            "tier": tier, "division": int(div), "lp": int(lp),
            "win": int(win), "lose": int(lose),
            "games": int(win) + int(lose),
            "win_rate": round(100 * int(win) / max(1, int(win) + int(lose)), 1),
        }
    return profile


if __name__ == "__main__":
    import sys
    rid = sys.argv[1] if len(sys.argv) > 1 else "MarcoRubio#5570"
    reg = sys.argv[2] if len(sys.argv) > 2 else "euw"
    prof = fetch_profile(rid, reg)
    print("PROFILE:", json.dumps(prof, ensure_ascii=False, indent=2))
    blocks = fetch_champion_stats(rid, reg)
    for b in blocks:
        print(f"\n{b['game_type']} s{b['season_id']}: {len(b['champions'])} champs played")
        for c in sorted(b["champions"], key=lambda x: x["play"], reverse=True)[:8]:
            print(f"  id={c['id']:>4} {c['play']:>3}g {c['win']}/{c['lose']} "
                  f"{c['win_rate']:.0f}%WR kda={c['kda']['kda']} "
                  f"cs/m={c.get('cs_per_min')} op={c.get('op_score')}")
