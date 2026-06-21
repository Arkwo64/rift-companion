"""Champion/item id<->name mapping from Riot's public Data Dragon CDN (no API key needed)."""
import json
from pathlib import Path

from ..http import get, get_json

_CACHE = Path(__file__).resolve().parent.parent.parent / ".cache" / "champions.json"
_ITEM_CACHE = Path(__file__).resolve().parent.parent.parent / ".cache" / "items.json"


def _latest_version():
    versions = get_json("https://ddragon.leagueoflegends.com/api/versions.json",
                        cache_minutes=1440)
    return versions[0]


def current_version():
    return _latest_version()


def champion_map():
    """Return {numeric_id: {'name': str, 'slug': str}} for all champions.

    slug is the lolalytics/url form (lowercase, alphanumeric): 'Aurelion Sol' -> 'aurelionsol'.
    """
    if _CACHE.exists():
        return {int(k): v for k, v in json.loads(_CACHE.read_text(encoding="utf-8")).items()}

    ver = _latest_version()
    data = get_json(
        f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/champion.json",
        cache_minutes=1440)
    out = {}
    for champ in data["data"].values():
        cid = int(champ["key"])
        name = champ["name"]
        slug = "".join(ch for ch in name.lower() if ch.isalnum())
        out[cid] = {"name": name, "slug": slug, "id_name": champ["id"]}
    _CACHE.parent.mkdir(exist_ok=True)
    _CACHE.write_text(json.dumps({str(k): v for k, v in out.items()},
                                 ensure_ascii=False), encoding="utf-8")
    return out


_RUNE_CACHE = Path(__file__).resolve().parent.parent.parent / ".cache" / "runes.json"
_SPELL_CACHE = Path(__file__).resolve().parent.parent.parent / ".cache" / "spells.json"


def rune_map():
    """Return {perk_id: name} for keystones/runes and {style_id: name} for trees."""
    if _RUNE_CACHE.exists():
        d = json.loads(_RUNE_CACHE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in d.items()}
    ver = _latest_version()
    data = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/runesReforged.json",
                    cache_minutes=1440)
    out = {}
    for style in data:
        out[style["id"]] = style["name"]
        for slot in style.get("slots", []):
            for r in slot.get("runes", []):
                out[r["id"]] = r["name"]
    _RUNE_CACHE.parent.mkdir(exist_ok=True)
    _RUNE_CACHE.write_text(json.dumps({str(k): v for k, v in out.items()}, ensure_ascii=False),
                           encoding="utf-8")
    return out


def summoner_map():
    """Return {numeric_id: name} for summoner spells (Flash, Ignite, ...)."""
    if _SPELL_CACHE.exists():
        d = json.loads(_SPELL_CACHE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in d.items()}
    ver = _latest_version()
    data = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/summoner.json",
                    cache_minutes=1440)
    out = {int(s["key"]): s["name"] for s in data["data"].values()}
    _SPELL_CACHE.parent.mkdir(exist_ok=True)
    _SPELL_CACHE.write_text(json.dumps({str(k): v for k, v in out.items()}, ensure_ascii=False),
                            encoding="utf-8")
    return out


def rune_icon_map():
    """{perk_id: icon_url} for keystones/runes/styles (rune icons are versionless)."""
    data = get_json("https://ddragon.leagueoflegends.com/api/versions.json", cache_minutes=1440)
    ver = data[0]
    runes = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/runesReforged.json",
                     cache_minutes=1440)
    out = {}
    base = "https://ddragon.leagueoflegends.com/cdn/img/"
    for style in runes:
        out[style["id"]] = base + style["icon"]
        for slot in style.get("slots", []):
            for r in slot.get("runes", []):
                out[r["id"]] = base + r["icon"]
    return out


def spell_icon_map():
    """{numeric_id: icon_url} for summoner spells."""
    ver = _latest_version()
    data = get_json(f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/summoner.json",
                    cache_minutes=1440)
    return {int(s["key"]): f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/spell/{s['id']}.png"
            for s in data["data"].values()}


def item_map():
    """Return {numeric_id: {'name','gold','tags','boots','starter','completed'}}.

    Classification uses Data Dragon's tags/gold so the build collector can split an
    item-id sequence into boots / starter / core without parsing op.gg's markup.
    """
    if _ITEM_CACHE.exists():
        return {int(k): v for k, v in json.loads(_ITEM_CACHE.read_text(encoding="utf-8")).items()}

    ver = _latest_version()
    data = get_json(
        f"https://ddragon.leagueoflegends.com/cdn/{ver}/data/en_US/item.json",
        cache_minutes=1440)
    out = {}
    for sid, it in data["data"].items():
        tags = it.get("tags", [])
        gold = it.get("gold", {}).get("total", 0)
        into = it.get("into")  # items that build out of this one -> not final if present
        is_boots = "Boots" in tags
        is_consumable = "Consumable" in tags or "Vision" in tags and gold < 100
        # "completed" = a finished item worth showing in a core build
        completed = (gold >= 1100 and not into and not is_boots
                     and "Consumable" not in tags and it.get("maps", {}).get("11", True))
        starter = (gold <= 600 and not is_boots) or "Lane" in tags
        out[int(sid)] = {
            "name": it["name"], "gold": gold, "tags": tags,
            "boots": is_boots, "starter": starter,
            "consumable": "Consumable" in tags, "completed": bool(completed),
        }
    _ITEM_CACHE.parent.mkdir(exist_ok=True)
    _ITEM_CACHE.write_text(json.dumps({str(k): v for k, v in out.items()},
                                      ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    m = champion_map()
    print(f"{len(m)} champions")
    for cid in (50, 136, 17, 26, 427, 9, 15, 120):
        print(cid, m.get(cid))
