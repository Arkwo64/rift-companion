"""Launch the local web app:  python app.py  [Name#TAG] [region]

Opens an interactive dashboard at http://127.0.0.1:8770 with tabs for Ranked / Normal /
Todo, lane matchups, builds and habits. Needs the Riot API key (riot_key.txt).
"""
import json
import sys
from pathlib import Path

try:  # avoid cp1252 crashes when stdout isn't UTF-8 (e.g. launched by tooling)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from lol_analyzer import server
from lol_analyzer.collectors import riot

ROOT = Path(__file__).resolve().parent


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if len(sys.argv) > 1:
        cfg["riot_id"] = sys.argv[1]
    if len(sys.argv) > 2:
        cfg["region"] = sys.argv[2]
    server.serve(cfg, riot.load_key(), port=cfg.get("port", 8770))


if __name__ == "__main__":
    main()
