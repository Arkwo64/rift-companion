"""SQLite persistence so we can track stats over time across runs.

Each run writes one snapshot per (queue, champion) plus an overall snapshot.
History lets the report show deltas: WR trend, op_score trend, games played.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "history.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS overall_snapshot (
                ts TEXT, riot_id TEXT, queue TEXT, season INTEGER,
                play INTEGER, win INTEGER, lose INTEGER, win_rate REAL
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS champ_snapshot (
                ts TEXT, riot_id TEXT, queue TEXT, season INTEGER,
                champion_id INTEGER, champion TEXT,
                play INTEGER, win INTEGER, lose INTEGER, win_rate REAL,
                kda REAL, cs_per_min REAL, op_score REAL
            )""")


def save_snapshot(riot_id, blocks, champ_map):
    init()
    ts = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        for b in blocks:
            ov = b.get("overall") or {}
            c.execute(
                "INSERT INTO overall_snapshot VALUES (?,?,?,?,?,?,?,?)",
                (ts, riot_id, b["game_type"], b["season_id"],
                 ov.get("play"), ov.get("win"), ov.get("lose"), ov.get("win_rate")))
            for ch in b["champions"]:
                name = champ_map.get(ch["id"], {}).get("name", str(ch["id"]))
                c.execute(
                    "INSERT INTO champ_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ts, riot_id, b["game_type"], b["season_id"], ch["id"], name,
                     ch.get("play"), ch.get("win"), ch.get("lose"), ch.get("win_rate"),
                     (ch.get("kda") or {}).get("kda"), ch.get("cs_per_min"),
                     ch.get("op_score")))
    return ts


def previous_overall(riot_id, queue):
    """Return the most recent overall snapshot strictly before the latest one."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT ts FROM overall_snapshot WHERE riot_id=? AND queue=? "
            "ORDER BY ts DESC LIMIT 2", (riot_id, queue)).fetchall()
        if len(rows) < 2:
            return None
        prev_ts = rows[1]["ts"]
        return c.execute(
            "SELECT * FROM overall_snapshot WHERE riot_id=? AND queue=? AND ts=?",
            (riot_id, queue, prev_ts)).fetchone()


def champ_history(riot_id, queue, champion_id):
    with _conn() as c:
        return c.execute(
            "SELECT ts, win_rate, op_score, play FROM champ_snapshot "
            "WHERE riot_id=? AND queue=? AND champion_id=? ORDER BY ts",
            (riot_id, queue, champion_id)).fetchall()
