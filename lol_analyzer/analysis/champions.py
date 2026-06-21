"""Per-champion analysis: the logic the raw stat pages don't apply.

Key ideas:
- Wilson score lower bound: a sample-size-aware "true win rate floor". 70% over 4
  games is weaker evidence than 56% over 40 games; Wilson encodes that honestly.
- ROI vs meta: your WR minus the champion's meta WR in your elo. Positive means you
  outperform the average player on that champ -> a genuine signal to lean in.
- Classification turns those two numbers into an action (main / lean-in / bench / sample).
"""
import math


def wilson_lower_bound(wins, n, z=1.0):
    """Sample-adjusted win-rate floor (Wilson lower bound).

    z=1.0 (~84% one-sided) is deliberate: at 95% (z=1.96) even 60% over 30 games
    floors near 42%, which would brand every champ unreliable. z=1.0 keeps the
    sample-size penalty meaningful without being absurdly punishing for LoL volumes.
    """
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return round(100 * (centre - margin) / denom, 1)


def analyze_champions(champions, champ_map, meta_by_id, min_games):
    """Return enriched, sorted champion analysis records."""
    out = []
    for ch in champions:
        cid = ch["id"]
        play = ch.get("play", 0)
        win = ch.get("win", 0)
        wr = ch.get("win_rate", 0.0)
        kda = (ch.get("kda") or {}).get("kda")
        info = champ_map.get(cid, {})
        meta = meta_by_id.get(str(cid)) or meta_by_id.get(cid) or {}
        meta_wr = meta.get("meta_win_rate")

        wilson = wilson_lower_bound(win, play)
        roi = round(wr - meta_wr, 1) if meta_wr is not None else None

        rec = {
            "champion_id": cid,
            "name": info.get("name", str(cid)),
            "slug": info.get("slug", ""),
            "id_name": info.get("id_name", ""),
            "play": play, "win": win, "lose": ch.get("lose", 0),
            "win_rate": round(wr, 1),
            "wilson_lb": wilson,
            "kda": kda,
            "cs_per_min": ch.get("cs_per_min"),
            "op_score": ch.get("op_score"),
            "kill_participation": ch.get("kill_participation"),
            "meta_win_rate": meta_wr,
            "meta_tier": meta.get("tier"),
            "roi": roi,
            "confident": play >= min_games,
        }
        rec["verdict"], rec["reason"] = _classify(rec, min_games)
        out.append(rec)

    # Rank: confident first, then by Wilson lower bound (the honest signal)
    out.sort(key=lambda r: (r["confident"], r["wilson_lb"], r["play"]), reverse=True)
    return out


def _classify(r, min_games):
    play, wr, adj, roi = r["play"], r["win_rate"], r["wilson_lb"], r["roi"]

    if play < min_games:
        if wr >= 60 and play >= max(3, min_games // 2):
            return "sample", f"Prometedor ({wr:.0f}% en {play}) pero muestra corta — juega más para confirmar."
        return "sample", f"Muestra insuficiente ({play} partidas) para concluir."

    # --- confident sample (play >= min_games) ---
    strong = adj >= 52 or wr >= 55
    beats_meta = roi is not None and roi >= 4
    under_meta = roi is not None and roi <= -4
    losing = wr <= 46  # genuinely below average, not merely uncertain

    if strong and not under_meta:
        why = f"WR sólido y consistente ({wr:.0f}% en {play}, ajustado {adj:.0f}%)"
        if beats_meta:
            why += f"; +{roi:.0f}% sobre el meta"
        return "main", why + "."
    if beats_meta and wr >= 49:
        return "lean_in", f"Rindes +{roi:.0f}% sobre el meta en {play} partidas — tu ventaja personal, priorízalo."
    if losing or under_meta:
        why = f"{wr:.0f}% WR en {play} partidas"
        if under_meta:
            why += f", {roi:.0f}% bajo el meta (lo fuerzas)"
        return "bench", why + " — bájalo de la rotación."
    return "neutral", f"Rendimiento promedio ({wr:.0f}% WR, ajustado {adj:.0f}%)."
