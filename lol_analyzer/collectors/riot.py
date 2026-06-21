"""Riot API client (official, requires a free dev key).

Unlocks what scraping can't: all queues (incl. normals/ARAM), per-match data with
timestamps (time-of-day form, tilt streaks), and live tier/LP.

The dev key expires every 24h. Provide it via the RIOT_API_KEY env var or a
`riot_key.txt` file in the project root (single line). Match details are immutable
and cached on disk forever, so only new games are fetched on each run.
"""
import gzip
import io
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MATCH_CACHE = ROOT / ".cache" / "matches"
TIMELINE_CACHE = ROOT / ".cache" / "timelines"
RANK_CACHE = ROOT / ".cache" / "ranks.json"

# region slug -> (platform host, regional host)
REGIONS = {
    "euw": ("euw1", "europe"), "eune": ("eun1", "europe"), "tr": ("tr1", "europe"),
    "ru": ("ru", "europe"), "na": ("na1", "americas"), "br": ("br1", "americas"),
    "lan": ("la1", "americas"), "las": ("la2", "americas"), "oce": ("oc1", "sea"),
    "kr": ("kr", "asia"), "jp": ("jp1", "asia"),
}

QUEUE_NAMES = {
    420: "RANKED_SOLO", 440: "RANKED_FLEX", 400: "NORMAL_DRAFT", 430: "NORMAL_BLIND",
    490: "QUICKPLAY", 450: "ARAM", 700: "CLASH", 1700: "ARENA", 480: "SWIFTPLAY",
}
QUEUE_GROUPS = {
    "RANKED": {420, 440}, "RANKED_SOLO": {420}, "RANKED_FLEX": {440},
    "NORMAL": {400, 430, 490, 480}, "ARAM": {450}, "ALL": None,
}


class RiotError(Exception):
    pass


def load_key():
    import os
    key = os.environ.get("RIOT_API_KEY")
    if key:
        return key.strip()
    f = ROOT / "riot_key.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return None


class RiotClient:
    def __init__(self, key, region):
        if region not in REGIONS:
            raise RiotError(f"Región '{region}' no soportada. Usa una de: {', '.join(REGIONS)}")
        self.key = key
        self.platform, self.regional = REGIONS[region]
        self._last = 0.0

    # ---- low level ----
    def _request(self, url):
        # Gentle client-side throttle (well under the 20 req/s dev limit)
        dt = time.time() - self._last
        if dt < 0.06:
            time.sleep(0.06 - dt)
        req = urllib.request.Request(url, headers={
            "X-Riot-Token": self.key,
            "Accept-Encoding": "gzip",
            "User-Agent": "lol-analyzer",
        })
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self._last = time.time()
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:  # rate limited -> respect Retry-After
                    wait = int(e.headers.get("Retry-After", "5"))
                    time.sleep(wait + 1)
                    continue
                if e.code == 401 or e.code == 403:
                    raise RiotError("Key inválida o caducada (401/403). Genera una nueva en developer.riotgames.com.")
                if e.code == 404:
                    return None
                if e.code >= 500:
                    time.sleep(2 + attempt)
                    continue
                raise
        raise RiotError(f"Demasiados reintentos para {url}")

    # ---- endpoints ----
    def account(self, game_name, tag_line):
        url = (f"https://{self.regional}.api.riotgames.com/riot/account/v1/accounts/"
               f"by-riot-id/{urllib.parse.quote(game_name)}/{urllib.parse.quote(tag_line)}")
        data = self._request(url)
        if not data:
            raise RiotError(f"No existe la cuenta {game_name}#{tag_line} en esa región.")
        return data  # {puuid, gameName, tagLine}

    def summoner(self, puuid):
        url = f"https://{self.platform}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return self._request(url) or {}

    def league_entries(self, puuid):
        url = f"https://{self.platform}.api.riotgames.com/lol/league/v4/entries/by-puuid/{puuid}"
        return self._request(url) or []

    def match_ids(self, puuid, queue=None, count=100, max_total=200):
        """Return up to max_total recent match ids, optionally filtered by queue id."""
        ids, start = [], 0
        while len(ids) < max_total:
            url = (f"https://{self.regional}.api.riotgames.com/lol/match/v5/matches/"
                   f"by-puuid/{puuid}/ids?start={start}&count={min(count, 100)}")
            if queue:
                url += f"&queue={queue}"
            batch = self._request(url) or []
            ids.extend(batch)
            if len(batch) < min(count, 100):
                break
            start += len(batch)
        return ids[:max_total]

    def match(self, match_id):
        """Fetch a match, caching it on disk permanently (matches never change)."""
        MATCH_CACHE.mkdir(parents=True, exist_ok=True)
        cf = MATCH_CACHE / f"{match_id}.json"
        if cf.exists():
            return json.loads(cf.read_text(encoding="utf-8"))
        data = self._request(f"https://{self.regional}.api.riotgames.com/lol/match/v5/matches/{match_id}")
        if data:
            cf.write_text(json.dumps(data), encoding="utf-8")
        return data

    def active_game(self, puuid):
        """Current live game (Spectator v5), None if not in a game, or {'_unavailable':True}
        if the key has no Spectator access (Riot error 1010 / 403)."""
        url = (f"https://{self.platform}.api.riotgames.com/lol/spectator/v5/"
               f"active-games/by-puuid/{puuid}")
        try:
            return self._request(url)  # 404 -> None (not in game)
        except RiotError:
            return {"_unavailable": True}

    def solo_ranks(self, puuids, ttl_hours=24, log=None):
        """Return {puuid: {tier,division,lp}} (Solo/Duo) for the given puuids, cached on
        disk with a TTL (ranks are 'current', so a day-old cache is fine)."""
        cache = {}
        if RANK_CACHE.exists():
            try:
                cache = json.loads(RANK_CACHE.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        out, to_fetch = {}, []
        now = time.time()
        for pid in set(puuids):
            e = cache.get(pid)
            if e and (now - e.get("ts", 0)) / 3600 < ttl_hours:
                out[pid] = e
            else:
                to_fetch.append(pid)
        if to_fetch and log:
            log(f"  Rangos: consultando {len(to_fetch)} jugadores (Solo/Duo, se cachean)...")
        for pid in to_fetch:
            solo = None
            try:
                for x in self.league_entries(pid):
                    if x.get("queueType") == "RANKED_SOLO_5x5":
                        solo = x
                        break
            except RiotError:
                pass
            e = {"tier": solo.get("tier") if solo else None,
                 "division": solo.get("rank") if solo else None,
                 "lp": solo.get("leaguePoints") if solo else None, "ts": now}
            cache[pid] = e
            out[pid] = e
        if to_fetch:
            RANK_CACHE.parent.mkdir(parents=True, exist_ok=True)
            RANK_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        return out

    def match_timeline(self, match_id):
        """Fetch a match timeline (per-minute frames), cached on disk permanently."""
        TIMELINE_CACHE.mkdir(parents=True, exist_ok=True)
        cf = TIMELINE_CACHE / f"{match_id}.json"
        if cf.exists():
            return json.loads(cf.read_text(encoding="utf-8"))
        data = self._request(
            f"https://{self.regional}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline")
        if data:
            cf.write_text(json.dumps(data), encoding="utf-8")
        return data


import urllib.parse  # noqa: E402  (used in account())
