"""Render the analysis to (a) a console summary and (b) a self-contained HTML dashboard."""
import html
from datetime import datetime

_VERDICT_LABEL = {
    "main": ("MAIN", "#3fb950"),
    "lean_in": ("APROVECHAR", "#58a6ff"),
    "neutral": ("NEUTRAL", "#8b949e"),
    "bench": ("BANQUILLO", "#f85149"),
    "sample": ("MUESTRA CORTA", "#d29922"),
}
_RATING_COLOR = {"fuerte": "#3fb950", "medio": "#8b949e", "flojo": "#f85149", "n/a": "#6e7681"}


# ----------------------------- console -----------------------------
def console_summary(ctx):
    p = ctx["profile"]
    lines = []
    a = lines.append
    a("")
    a(f"  ====== ANÁLISIS DE CUENTA · {p['riot_id']} ({p['region'].upper()}) ======")
    rank = _rank_str(p.get("ranks", {}))
    if rank != "Sin rank":
        a(f"  Rank: {rank}")
    ov = ctx["overall"]
    if ov:
        a(f"  {ctx['queue']}: {ov.get('play')} partidas · "
          f"{ov.get('win')}V/{ov.get('lose')}D · {round(ov.get('win_rate') or 0, 1)}% WR")
    qs = ctx.get("queue_summary", [])
    if qs:
        a("  Por cola: " + " · ".join(f"{q['queue']} {q['count']}" for q in qs))
    if ctx.get("trend"):
        a(f"  Tendencia desde el último run: {ctx['trend']}")
    a("")

    recs = ctx["recommendations"]
    a("  >> JUGAR (tus picks con mejor evidencia):")
    for r in recs["play"] or [{"text": "sin datos suficientes", "why": ""}]:
        a(f"     + {r['text']}")
    a("")
    a("  >> EVITAR / BANQUILLO:")
    for r in recs["avoid"] or [{"text": "nada que marcar", "why": ""}]:
        a(f"     - {r['text']}")
    if recs.get("comfort"):
        a("")
        a("  >> TRAMPAS DE COMFORT (juegas mucho, rindes poco):")
        for r in recs["comfort"]:
            a(f"     ~ {r['text']}")
    if recs["explore"]:
        a("")
        a("  >> EXPLORAR (prometedores, falta muestra):")
        for r in recs["explore"]:
            a(f"     ? {r['text']}")
    if recs["habits"]:
        a("")
        a("  >> HÁBITOS A CORREGIR:")
        for h in recs["habits"]:
            a(f"     ! {h}")
    builds = ctx.get("builds", {})
    if builds:
        a("")
        a("  >> BUILDS RECOMENDADOS:")
        for name, b in list(builds.items())[:4]:
            it = b["items"]
            core = " → ".join(x["name"] if isinstance(x, dict) else x for x in it["core"][:3]) or "—"
            boots = it.get("boots")
            boots = boots["name"] if isinstance(boots, dict) else (boots or "—")
            a(f"     {name} ({b.get('role','')}): {b['runes'].get('keystone','—')} | "
              f"{boots} | {core}")
    a("")
    a(f"  >> POOL: {recs['pool']}")
    a("")
    a(f"  Reporte completo: {ctx['html_path']}")
    a("")
    return "\n".join(lines)


# ----------------------------- HTML -----------------------------
def _chip(text, color):
    return f'<span style="background:{color}22;color:{color};border:1px solid {color}55;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600">{html.escape(text)}</span>'


def render_html(ctx):
    p = ctx["profile"]
    ov = ctx["overall"] or {}
    recs = ctx["recommendations"]
    rows = []
    for c in ctx["champions"]:
        label, color = _VERDICT_LABEL.get(c["verdict"], ("—", "#8b949e"))
        roi = "—" if c["roi"] is None else f'{"+" if c["roi"]>=0 else ""}{c["roi"]:.0f}%'
        roi_color = "#8b949e" if c["roi"] is None else ("#3fb950" if c["roi"] >= 0 else "#f85149")
        meta = "—" if c["meta_win_rate"] is None else f'{c["meta_win_rate"]:.0f}%'
        rows.append(f"""
        <tr>
          <td class="champ">{html.escape(c['name'])}</td>
          <td>{c['play']}</td>
          <td>{c['win']}/{c['lose']}</td>
          <td><b>{c['win_rate']:.0f}%</b></td>
          <td title="win rate ajustado por tamaño de muestra (Wilson)">{c['wilson_lb']:.0f}%</td>
          <td>{meta}</td>
          <td style="color:{roi_color};font-weight:600">{roi}</td>
          <td>{c['kda'] if c['kda'] is not None else '—'}</td>
          <td>{c['op_score'] if c['op_score'] is not None else '—'}</td>
          <td>{_chip(label, color)}</td>
        </tr>""")

    def rec_list(items, empty="—"):
        if not items:
            return f'<li class="muted">{empty}</li>'
        return "".join(
            f'<li><b>{html.escape(i.get("champ",""))}</b> '
            f'<span class="why">{html.escape(i["text"])}</span>'
            f'<div class="sub">{html.escape(i.get("why",""))}</div></li>'
            if i.get("champ") else f'<li>{html.escape(i["text"])}</li>'
            for i in items)

    habit_cards = ""
    if ctx["habits"].get("available"):
        for m in ctx["habits"]["metrics"]:
            col = _RATING_COLOR.get(m["rating"], "#8b949e")
            habit_cards += f"""
            <div class="hcard">
              <div class="hval" style="color:{col}">{html.escape(m['display'])}</div>
              <div class="hlabel">{html.escape(m['label'])}</div>
              <div class="hrate" style="color:{col}">{html.escape(m['rating'])}</div>
            </div>"""

    habit_tips = "".join(f"<li>{html.escape(h)}</li>" for h in recs["habits"]) or '<li class="muted">Sin alertas de hábitos.</li>'

    builds_html = _render_builds(ctx.get("builds", {}))
    timehabits_html = _render_timehabits(ctx.get("time_habits"))
    rank_str = _rank_str(p.get("ranks", {}))
    queues_html = _render_queues(ctx.get("queue_summary", []))

    return _TEMPLATE.format(
        riot_id=html.escape(p["riot_id"]),
        region=html.escape(p["region"].upper()),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        queue=html.escape(ctx["queue"]),
        games=ov.get("play", "—"),
        record=f'{ov.get("win","—")}V / {ov.get("lose","—")}D',
        winrate=round(ov.get("win_rate") or 0, 1) if ov.get("win_rate") is not None else "—",
        trend=html.escape(ctx.get("trend") or "primer registro"),
        play_list=rec_list(recs["play"], "Sin picks con muestra suficiente."),
        avoid_list=rec_list(recs["avoid"], "Nada que banquillar."),
        comfort_list=rec_list(recs.get("comfort", []), "Ninguna detectada — tu volumen está bien repartido en picks que rinden."),
        explore_list=rec_list(recs["explore"], "—"),
        pool_note=html.escape(recs["pool"]),
        habit_cards=habit_cards or '<p class="muted">Perfil de hábitos no disponible.</p>',
        habit_tips=habit_tips,
        rows="".join(rows),
        builds=builds_html,
        source=html.escape(ctx.get("source", "op.gg")),
        timehabits=timehabits_html,
        rank=rank_str,
        queues=queues_html,
        meta_note=html.escape(ctx.get("meta_note", "")),
    )


def _rank_str(ranks):
    solo = ranks.get("SOLORANKED")
    if not solo or not solo.get("tier"):
        return "Sin rank"
    div = solo.get("division", "")
    return f"{solo['tier'].title()} {div} · {solo.get('lp', 0)} LP"


def _render_queues(qs):
    if not qs:
        return ""
    chips = " ".join(
        f'<span class="qchip">{html.escape(q["queue"])}: <b>{q["count"]}</b></span>'
        for q in qs)
    return f'<div class="qrow"><span class="muted">Partidas por cola:</span> {chips}</div>'


def _bar(pct, color):
    pct = max(0, min(100, pct or 0))
    return (f'<div class="bar"><div class="barfill" style="width:{pct}%;background:{color}"></div>'
            f'<span class="barval">{pct:.0f}%</span></div>')


def _render_timehabits(th):
    if not th or not th.get("available"):
        return ('<p class="muted">Disponible solo con la Riot API (hábitos por partida). '
                'Añade tu key para activar forma por hora y detección de tilt.</p>')
    base = th.get("base_win_rate") or 0
    out = [f'<p class="muted">Sobre {th.get("total", 0)} partidas · WR base {base:.0f}%</p>']

    # Tilt cards
    al, a2 = th.get("after_loss", {}), th.get("after_streak2", {})
    def tcard(title, d):
        if not d or d.get("win_rate") is None:
            return ""
        col = "#f85149" if d["win_rate"] < base - 3 else ("#3fb950" if d["win_rate"] > base + 3 else "#8b949e")
        return (f'<div class="hcard"><div class="hval" style="color:{col}">{d["win_rate"]:.0f}%</div>'
                f'<div class="hlabel">{title}</div><div class="hrate muted">{d.get("games",0)} casos</div></div>')
    out.append('<div class="hgrid">'
               + tcard("WR tras una derrota", al)
               + tcard("WR tras 2+ derrotas", a2)
               + f'<div class="hcard"><div class="hval">{th.get("longest_loss_streak",0)}</div>'
                 f'<div class="hlabel">Peor racha de derrotas</div></div>'
               + '</div>')

    # Daypart bars
    if th.get("daypart"):
        rows = ""
        for d in th["daypart"]:
            col = "#3fb950" if d["win_rate"] >= base else "#f85149"
            rows += (f'<tr><td>{html.escape(d["label"])}</td><td style="width:55%">{_bar(d["win_rate"], col)}</td>'
                     f'<td class="muted">{d["games"]}g</td></tr>')
        out.append(f'<table class="tbar">{rows}</table>')
    return "".join(out)


def _render_builds(builds):
    if not builds:
        return '<p class="muted">Sin builds (champs sin rol en meta_cache.json).</p>'
    cards = ""
    for name, b in builds.items():
        r = b["runes"]
        it = b["items"]
        keystone = html.escape(r.get("keystone") or "—")
        trees = " · ".join(filter(None, [r.get("primary_tree"), r.get("secondary_tree")]))
        def names(v):
            if isinstance(v, dict):
                return v.get("name", "")
            return v
        boots = html.escape(names(it.get("boots")) or "—")
        core = " → ".join(html.escape(names(x)) for x in it.get("core", [])[:4]) or "—"
        starter = ", ".join(html.escape(names(x)) for x in it.get("starter", [])) or "—"
        cards += f"""
        <div class="bcard">
          <div class="bname">{html.escape(name)} <span class="muted">· {html.escape(b.get('role',''))}</span></div>
          <div class="brow"><span class="blabel">Runa clave</span> {keystone} <span class="muted">({html.escape(trees)})</span></div>
          <div class="brow"><span class="blabel">Inicio</span> {starter}</div>
          <div class="brow"><span class="blabel">Botas</span> {boots}</div>
          <div class="brow"><span class="blabel">Core</span> {core}</div>
        </div>"""
    return cards


_TEMPLATE = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LoL Analyzer · {riot_id}</title>
<style>
  body{{margin:0;background:#0d1117;color:#c9d1d9;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}}
  .wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
  h1{{font-size:24px;margin:0 0 2px}} .subtitle{{color:#8b949e;margin-bottom:22px}}
  .kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:26px}}
  .kpi{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px 18px;min-width:120px}}
  .kpi .v{{font-size:26px;font-weight:700}} .kpi .l{{color:#8b949e;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}
  h2{{font-size:17px;margin:30px 0 12px;border-bottom:1px solid #21262d;padding-bottom:6px}}
  .cols{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
  @media(max-width:760px){{.cols{{grid-template-columns:1fr}}}}
  ul.recs{{list-style:none;padding:0;margin:0}} ul.recs li{{padding:9px 0;border-bottom:1px solid #21262d}}
  ul.recs .why{{color:#c9d1d9}} ul.recs .sub{{color:#8b949e;font-size:13px;margin-top:2px}}
  .muted{{color:#6e7681}}
  .hgrid{{display:flex;gap:12px;flex-wrap:wrap}}
  .hcard{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px;min-width:120px;text-align:center;flex:1}}
  .hval{{font-size:22px;font-weight:700}} .hlabel{{font-size:12px;color:#8b949e;margin-top:3px}} .hrate{{font-size:11px;text-transform:uppercase;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;margin-top:6px;font-size:14px}}
  th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #21262d}}
  th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}}
  td.champ{{font-weight:600}} tr:hover td{{background:#161b2255}}
  .bgrid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
  @media(max-width:760px){{.bgrid{{grid-template-columns:1fr}}}}
  .bcard{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px 16px}}
  .bname{{font-weight:700;font-size:15px;margin-bottom:8px}}
  .brow{{font-size:13px;padding:2px 0}} .blabel{{display:inline-block;width:78px;color:#8b949e;font-size:11px;text-transform:uppercase}}
  .qrow{{margin:-14px 0 22px;font-size:13px}} .qchip{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:3px 9px;margin-right:6px;display:inline-block}}
  .bar{{position:relative;background:#21262d;border-radius:6px;height:18px;overflow:hidden}}
  .barfill{{height:100%}} .barval{{position:absolute;right:8px;top:0;font-size:11px;line-height:18px;color:#fff}}
  table.tbar td{{border:none;padding:5px 8px}} table.tbar{{margin-bottom:8px}}
  .note{{background:#161b22;border:1px solid #30363d;border-left:3px solid #58a6ff;border-radius:8px;padding:12px 14px;margin:18px 0;color:#c9d1d9}}
  .foot{{color:#6e7681;font-size:12px;margin-top:30px}}
</style></head><body><div class="wrap">
  <h1>{riot_id} <span class="muted">· {region}</span></h1>
  <div class="subtitle">Análisis generado {generated} · cola {queue}</div>
  <div class="kpis">
    <div class="kpi"><div class="v" style="font-size:18px">{rank}</div><div class="l">Rank (Solo/Duo)</div></div>
    <div class="kpi"><div class="v">{games}</div><div class="l">Partidas</div></div>
    <div class="kpi"><div class="v">{record}</div><div class="l">Récord</div></div>
    <div class="kpi"><div class="v">{winrate}%</div><div class="l">Win rate</div></div>
    <div class="kpi"><div class="v" style="font-size:15px">{trend}</div><div class="l">Tendencia</div></div>
  </div>
  {queues}

  <div class="cols">
    <div><h2>✅ Jugar</h2><ul class="recs">{play_list}</ul></div>
    <div><h2>⛔ Evitar / Banquillo</h2><ul class="recs">{avoid_list}</ul></div>
  </div>
  <div class="cols">
    <div><h2>🪤 Trampas de comfort</h2><ul class="recs">{comfort_list}</ul></div>
    <div><h2>🔬 Explorar</h2><ul class="recs">{explore_list}</ul></div>
  </div>
  <div class="cols">
    <div><h2>🧠 Hábitos a corregir</h2><ul class="recs">{habit_tips}</ul></div>
    <div><h2>🎯 Pool</h2><div class="note" style="margin-top:12px">{pool_note}</div></div>
  </div>

  <h2>📊 Perfil de hábitos</h2>
  <div class="hgrid">{habit_cards}</div>

  <h2>⏰ Forma y tilt <span class="muted" style="font-size:13px;font-weight:400">(por partida)</span></h2>
  {timehabits}

  <h2>🛠️ Builds recomendados <span class="muted" style="font-size:13px;font-weight:400">(op.gg · tu elo)</span></h2>
  <div class="bgrid">{builds}</div>

  <h2>🏆 Todos los campeones</h2>
  <table>
    <tr><th>Champ</th><th>Part.</th><th>V/D</th><th>WR</th><th>WR ajust.</th><th>WR meta</th><th>ROI</th><th>KDA</th><th>OP</th><th>Veredicto</th></tr>
    {rows}
  </table>

  <div class="note">{meta_note}</div>
  <div class="foot">Fuente de tus partidas: {source} · builds de op.gg · baseline de meta de lolalytics. "WR ajust." = win rate ajustado por tamaño de muestra (límite inferior de Wilson): penaliza pocas partidas para no fiarse de rachas cortas. ROI = tu WR − WR del meta en tu elo (calibrado para ranked).</div>
</div></body></html>"""
