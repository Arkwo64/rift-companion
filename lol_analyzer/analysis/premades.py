"""Infer premade (party) groups from match history.

Riot's API has no party field, so we infer it: players who repeatedly appear on the SAME
team across your games are almost certainly queuing together. This nails your own premades
and any enemy duos you face often; it can't see one-off randoms (no data to go on).
"""
from collections import defaultdict

PREMADE_MIN = 3  # times on the same team before we call it a premade


def build_pair_index(matches):
    """{frozenset(puuidA, puuidB): times_on_the_same_team} over all matches."""
    idx = defaultdict(int)
    for m in matches:
        teams = defaultdict(list)
        for p in m.get("info", {}).get("participants", []):
            if p.get("puuid"):
                teams[p.get("teamId")].append(p["puuid"])
        for members in teams.values():
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    idx[frozenset((members[i], members[j]))] += 1
    return idx


def premade_groups(participants, pair_index, min_games=PREMADE_MIN):
    """Given a lobby's participants ([{puuid, teamId}...]), return {puuid: group_id} for
    players that form a premade (connected by enough same-team co-occurrences). Solo
    players are omitted. Group ids are stable within one call."""
    by_team = defaultdict(list)
    for p in participants:
        if p.get("puuid"):
            by_team[p.get("teamId")].append(p["puuid"])
    groups, gid = {}, 0
    for members in by_team.values():
        adj = {pp: set() for pp in members}
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if pair_index.get(frozenset((a, b)), 0) >= min_games:
                    adj[a].add(b)
                    adj[b].add(a)
        seen = set()
        for pp in members:
            if pp in seen:
                continue
            comp, stack = [], [pp]
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack.extend(adj[x] - seen)
            if len(comp) >= 2:
                gid += 1
                for x in comp:
                    groups[x] = gid
    return groups


def match_groups(match, puuid, pair_index, min_games=PREMADE_MIN):
    """All detected premade groups in a match, tagged ally/enemy relative to you.
    Returns [{side:'ally'|'enemy', with_me:bool, names:[...], size:int}]."""
    parts = match.get("info", {}).get("participants", [])
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    my_team = me.get("teamId") if me else None
    groups = premade_groups(parts, pair_index, min_games)
    members = defaultdict(list)
    for p in parts:
        gid = groups.get(p.get("puuid"))
        if gid:
            members[gid].append(p)
    out = []
    for gid, mem in members.items():
        with_me = any(p.get("puuid") == puuid for p in mem)
        side = "ally" if mem[0].get("teamId") == my_team else "enemy"
        names = [p.get("riotIdGameName") or p.get("summonerName") or "?"
                 for p in mem if not (with_me and p.get("puuid") == puuid)]
        out.append({"side": side, "with_me": with_me, "names": names, "size": len(mem)})
    out.sort(key=lambda g: (0 if g["with_me"] else 1 if g["side"] == "ally" else 2))
    return out


def my_premates(match, puuid, pair_index, champ_map=None, min_games=PREMADE_MIN):
    """Names of YOUR premade teammates in a single match (for the history glance)."""
    parts = match.get("info", {}).get("participants", [])
    me = next((p for p in parts if p.get("puuid") == puuid), None)
    if not me:
        return []
    out = []
    for p in parts:
        if p.get("teamId") == me.get("teamId") and p.get("puuid") != puuid:
            if pair_index.get(frozenset((puuid, p.get("puuid"))), 0) >= min_games:
                out.append(p.get("riotIdGameName") or p.get("summonerName") or "?")
    return out
