"""Recommended build (runes + items) for a champion/role from op.gg's build page.

Runes come straight from op.gg's embedded data. Items are rendered as UI components,
so we extract the ordered item-id sequence and classify it (boots/starter/core) using
Data Dragon item metadata (see ddragon.item_map).
"""
import re

from ..http import get
from . import ddragon

# meta_cache roles -> op.gg url role slug
_ROLE = {"support": "support", "mid": "mid", "middle": "mid", "top": "top",
         "jungle": "jungle", "adc": "adc", "bottom": "adc"}


def _blob(slug, role, tier):
    url = f"https://www.op.gg/lol/champions/{slug}/build/{role}?tier={tier}"
    html = get(url, referer="https://www.op.gg/", cache_minutes=720)
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
    return "".join(chunks).encode().decode("unicode_escape", "replace")


def _runes(blob):
    """First (recommended) rune page: keystone + both trees + win rate."""
    m = re.search(
        r'"primary_perk_style":\{"id":\d+,"name":"([^"]+)"[^}]*\},'
        r'"perk_sub_style":\{"id":\d+,"name":"([^"]+)"', blob)
    primary_tree, secondary_tree = (m.group(1), m.group(2)) if m else (None, None)

    k = re.search(r'"win_rate":([0-9.]+),"primary_rune":\{"id":(\d+),"name":"([^"]+)"', blob)
    win_rate = round(float(k.group(1)) * 100, 1) if k else None
    keystone_id = int(k.group(2)) if k else None
    keystone = k.group(3) if k else None
    return {"keystone": keystone, "keystone_id": keystone_id, "primary_tree": primary_tree,
            "secondary_tree": secondary_tree, "win_rate": win_rate}


def _items(blob, item_map):
    """Split the rendered item-id sequence into starter / boots / core / situational.

    op.gg lists items in build order: a 3-item core first, then situational options.
    """
    seq = [int(x) for x in re.findall(r'"metaType":"item","metaId":(\d+)', blob)]
    boots, starters, completed, seen = None, [], [], set()
    for iid in seq:
        meta = item_map.get(iid)
        if not meta or iid in seen:
            continue
        entry = {"id": iid, "name": meta["name"]}
        if meta["boots"] and boots is None:
            boots = entry
            seen.add(iid)
        elif meta["completed"] and len(completed) < 8:
            completed.append(entry)
            seen.add(iid)
        elif meta["starter"] and not meta["consumable"] and len(starters) < 2 and not completed:
            starters.append(entry)
            seen.add(iid)
    return {"starter": starters, "boots": boots,
            "core": completed[:3], "situational": completed[3:8]}


def fetch_build(slug, role, tier="emerald_plus"):
    role_slug = _ROLE.get((role or "").lower())
    if not slug or not role_slug:
        return None
    try:
        blob = _blob(slug, role_slug, tier)
    except Exception:
        return None
    item_map = ddragon.item_map()
    build = {"role": role_slug, "runes": _runes(blob), "items": _items(blob, item_map)}
    if not build["runes"]["keystone"] and not build["items"]["core"]:
        return None
    return build


if __name__ == "__main__":
    import json, sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "swain"
    role = sys.argv[2] if len(sys.argv) > 2 else "support"
    print(json.dumps(fetch_build(slug, role), ensure_ascii=False, indent=2))
