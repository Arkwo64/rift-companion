"""Synthesize champion analysis + habits into concrete recommendations."""


def build_recommendations(champ_analysis, habits, pool, min_games, time_habits=None):
    mains = [c for c in champ_analysis if c["verdict"] == "main"]
    lean = [c for c in champ_analysis if c["verdict"] == "lean_in"]
    bench = [c for c in champ_analysis if c["verdict"] == "bench"]
    promising = [c for c in champ_analysis
                 if c["verdict"] == "sample" and c["win_rate"] >= 60 and c["play"] >= 4]

    # Comfort traps: champs you play a LOT but where you don't outperform — the time
    # sink that quietly holds your rank back. This is the cross-reference the stat
    # pages can't make, because it needs your volume + your WR + the meta WR together.
    confident = [c for c in champ_analysis if c["confident"]]
    by_play = sorted(confident, key=lambda c: c["play"], reverse=True)
    top_played = by_play[:6]
    bench_names = {c["name"] for c in bench}
    comfort = [c for c in top_played
               if (c["win_rate"] < 50 or (c["roi"] is not None and c["roi"] <= -2))
               and c["name"] not in bench_names]

    recs = {"play": [], "avoid": [], "explore": [], "comfort": [],
            "habits": [], "pool": pool["note"]}

    for c in (mains + lean)[:5]:
        line = f"{c['name']} — {c['win_rate']:.0f}% WR en {c['play']} (piso {c['wilson_lb']:.0f}%)"
        if c["roi"] is not None:
            line += f", {'+' if c['roi'] >= 0 else ''}{c['roi']:.0f}% vs meta"
        recs["play"].append({"text": line, "champ": c["name"], "why": c["reason"]})

    for c in bench[:5]:
        line = f"{c['name']} — {c['win_rate']:.0f}% WR en {c['play']} (piso {c['wilson_lb']:.0f}%)"
        recs["avoid"].append({"text": line, "champ": c["name"], "why": c["reason"]})

    for c in comfort[:4]:
        roi_txt = "" if c["roi"] is None else f" ({'+' if c['roi'] >= 0 else ''}{c['roi']:.0f}% vs meta)"
        recs["comfort"].append({
            "text": f"{c['name']} — {c['play']} partidas pero solo {c['win_rate']:.0f}% WR{roi_txt}",
            "champ": c["name"],
            "why": "De tus más jugados pero no rindes por encima — invierte ese tiempo en tus picks fuertes para subir más rápido."})

    for c in promising[:4]:
        recs["explore"].append({
            "text": f"{c['name']} — {c['win_rate']:.0f}% en solo {c['play']} partidas",
            "champ": c["name"],
            "why": f"Buen arranque; juega hasta {min_games}+ para confirmar si es un main real."})

    # Habit-driven advice
    if habits.get("available"):
        for m in habits["metrics"]:
            if m["rating"] == "flojo":
                recs["habits"].append(_habit_tip(m))
        pg = habits["per_game"]
        if pg.get("snowball_hit_ratio") is not None and pg["snowball_hit_ratio"] < 40:
            recs["habits"].append("Aprovechas poco las ventajas (snowball bajo): cuando vas adelante, fuerza objetivos en vez de farmear.")

    # Per-match (Riot API) tilt + timing advice
    if time_habits and time_habits.get("available"):
        recs["habits"].extend(_tilt_tips(time_habits))

    return recs


def _tilt_tips(th):
    tips = []
    base = th.get("base_win_rate")
    al = th.get("after_loss", {})
    a2 = th.get("after_streak2", {})
    if base is not None and al.get("games", 0) >= 8 and al["win_rate"] is not None and al["win_rate"] <= base - 6:
        tips.append(f"Tilt confirmado: tras una derrota tu WR cae a {al['win_rate']:.0f}% "
                    f"(vs {base:.0f}% normal). Toma un respiro antes de la siguiente.")
    if a2.get("games", 0) >= 5 and a2["win_rate"] is not None and a2["win_rate"] <= 42:
        tips.append(f"Tras 2 derrotas seguidas ganas solo {a2['win_rate']:.0f}% ({a2['games']} casos): "
                    f"deja de jugar ranked ese día.")
    # Best / worst daypart
    dp = [d for d in th.get("daypart", []) if d["games"] >= 8]
    if len(dp) >= 2:
        best = max(dp, key=lambda d: d["win_rate"])
        worst = min(dp, key=lambda d: d["win_rate"])
        if best["win_rate"] - worst["win_rate"] >= 12:
            tips.append(f"Rindes mejor de {best['label'].lower()} ({best['win_rate']:.0f}%) y peor de "
                        f"{worst['label'].lower()} ({worst['win_rate']:.0f}%). Agenda tus rankeds acorde.")
    if th.get("current_loss_streak", 0) >= 3:
        tips.append(f"Vienes de {th['current_loss_streak']} derrotas seguidas — para hoy, estás en zona de tilt.")
    return tips


def _habit_tip(metric):
    label = metric["label"]
    tips = {
        "Muertes por partida": f"{label}: {metric['display']} es alto. Muere menos — revisa posicionamiento y respeta los timers de jungla rival.",
        "Visión (score)": f"{label}: {metric['display']} es bajo. Compra control wards cada vuelta y barre con sweeper antes de objetivos.",
        "Participación en kills": f"{label}: {metric['display']}. Estás poco presente en las peleas — roa más con tu equipo tras pushear.",
        "CS por minuto": f"{label}: {metric['display']} es bajo. Practica últimos golpes; apunta a +1 CS/min en 10 partidas.",
        "Op Score (rendimiento)": f"{label}: {metric['display']}. Tu impacto medio por partida es bajo — prioriza champs donde rindes mejor.",
        "Cuota de daño": f"{label}: {metric['display']}. Aportas poco daño — revisa builds y timings de teamfight.",
    }
    return tips.get(label, f"{label}: {metric['display']} (punto a mejorar).")
