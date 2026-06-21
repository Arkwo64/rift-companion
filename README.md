# LoL Account Analyzer

Centraliza tus estadísticas de League of Legends (Riot API + op.gg), las cruza con un
**baseline de meta** y aplica lógica estadística para decirte qué jugar, qué evitar y
qué hábitos corregir — cosas que ninguna página por separado te muestra.

Sin dependencias externas: solo Python (librería estándar).

## Uso

**App web local (recomendado):**
```bash
python app.py                       # abre http://127.0.0.1:8770 en tu navegador
python app.py "MarcoRubio#5570" euw # sobreescribe cuenta/región
```
O usa el **acceso directo del escritorio** (`LoL Analyzer`) — doble clic y se abre solo.
El lanzador es `LoL Analyzer.bat`; cierra la ventana de consola para detener la app.

Dashboard interactivo con **5 pestañas**: **Resumen** (lo importante de un vistazo) ·
**Campeones** (con desplegable de cola: Solo/Flex/Normal/Todo) · **Compañeros** ·
**Historial** · **Live**. Arriba hay un **buscador de campeón**: escribe cualquier champ
tuyo y abre su ficha (historial reciente, win rate, matchups por línea, tu build vs meta
e items por winrate). Todo en `127.0.0.1`.

**Se actualiza solo:** el servidor vuelve a consultar la Riot API cada
`auto_refresh_minutes` (10 por defecto) y la web se refresca sola cada 60s. Tras
terminar una partida, aparece en 1-2 min sin tocar nada (o pulsa *Refrescar* para ya).
No actualiza *durante* la partida: Riot solo expone partidas terminadas.

**Desde el móvil (misma WiFi):**
En `config.json` pon `"host": "0.0.0.0"` y un `"access_token"` (una palabra secreta). Al
arrancar, la consola imprime la URL para el móvil, p.ej. `http://192.168.1.50:8770/?token=tu_token`.
Ábrela en el navegador del móvil (con el PC encendido y en la misma red). El token se guarda
en una cookie, así que solo lo pones la primera vez. Si dejas `host` en `127.0.0.1`, la app
solo es accesible desde tu PC (sin token). Si expones por LAN sin token, se genera uno
automático y se imprime en la consola (nunca queda abierto sin protección).

**Reporte estático (one-shot, sin servidor):**
```bash
python run.py                       # genera output/report.html (una cola)
```

Ambos guardan un snapshot en `data/history.db` para el **tracking en el tiempo**.

## Riot API (recomendado)

Con una API key activas: **todas las colas (normales, ARAM, flex…)**, **hábitos por
partida** (forma por hora del día, detección de tilt tras derrotas), **rank/LP en vivo**
y datos partida-a-partida fiables.

1. Saca la key en **developer.riotgames.com** (la dev key es gratis e instantánea; caduca
   cada 24h. Una *personal/production key* aprobada no caduca).
2. Ponla en `riot_key.txt` (una línea) o en la variable de entorno `RIOT_API_KEY`.
   `riot_key.txt` está en `.gitignore` para no filtrarla.

Sin key, el programa cae automáticamente a **op.gg** (solo ranked, agregados de
temporada, sin hábitos por partida ni LP en vivo).

### Incluir las normales (o cualquier cola)

`focus_queue` en `config.json` controla qué cola se analiza a fondo:
`RANKED` (solo+flex), `RANKED_SOLO`, `RANKED_FLEX`, `NORMAL`, `ARAM` o `ALL` (todo junto).
El reporte siempre muestra el conteo de partidas de cada cola arriba.

> Nota: el **ROI vs meta** está calibrado para ranked en tu elo. En `NORMAL`/`ALL` el
> resto del análisis (WR, Wilson, hábitos) sigue siendo válido, pero el ROI es orientativo.

## Qué analiza

| Sección | Lógica aplicada |
|---|---|
| **★ Resumen** | Pestaña inicial: destila todo en **fortalezas** (qué jugar, mejor dúo, líneas fáciles, si remontas/no tilteas) y **dónde mejorar** (comfort traps, banquillo, matchup a evitar, gap de build, hábitos). El "qué hago con todo esto". |
| **Jugar** | Champs con WR sólido y consistente. Ordenados por win rate **ajustado por muestra** (límite inferior de Wilson) para no fiarse de rachas cortas. |
| **ROI vs meta** | Tu WR − el WR del jugador medio en ese champ/rol y tu elo. `+20%` en Sivir = rindes muchísimo por encima de la media → es tu ventaja personal. |
| **Trampas de comfort** | Champs que **juegas mucho** pero donde **no superas el meta**. El tiempo que te frena. |
| **Evitar / Banquillo** | Champs donde pierdes de verdad (WR bajo con muestra suficiente, o muy por debajo del meta). |
| **Explorar** | Champs con buen arranque pero pocas partidas: juega más para confirmar. |
| **Hábitos** | Perfil de muertes, visión, participación en kills, CS/min, daño, con alertas accionables. |
| **Forma y tilt** *(Riot API)* | WR por franja horaria, WR tras 1 derrota y tras rachas de 2+, peor racha. Detecta si juegas peor tilteado o a ciertas horas. |
| **Matchups en línea** *(Riot API)* | Tu WR vs el campeón enemigo de tu carril (líneas fáciles/difíciles). En el drill-down de cada champ, **agrupado por línea enemiga** (en bot ves tanto vs ADC como vs Support rivales). Son tus datos individuales por matchup, que ningún sitio muestra. |
| **Items por winrate** | Pestaña con tu WR por item y campeón (mejores/peores), guardado por muestra. Con aviso: es correlación, no causa (las victorias llevan más items). |
| **Builds** | Build recomendado (runas + inicio + botas + core de 3 + situacionales) por champ, de op.gg en tu elo. Funciona para todos tus champs (el rol se infiere de tus partidas). Nombres de item vía Data Dragon. |
| **Tu build vs meta** | En el drill-down de cada champ: tu build REAL (runa, hechizos, items con TU winrate por item) frente al build meta de op.gg, con las diferencias resaltadas. Ej.: "llevas Aery (39% WR), el meta Conqueror; cuando compras Malignance ganas 71% pero casi nunca la montas". |
| **Historial** | Tus últimas ~25 partidas: champ, V/D, KDA, CS, rival de línea, cola, fecha. Muestra el **rango medio (Solo/Duo) de los rivales** que enfrentas y, por partida, el rango medio del equipo enemigo. **Clic** → scoreboard completo con el **rango de cada jugador** (tú resaltado). Rangos = actuales, cacheados 24h. |
| **🔴 Live** | Partida en vivo (Spectator): ambos equipos, campeones, rango de cada jugador, rango medio por equipo, bans y premades. **Requiere una key con acceso a la Spectator API** (si no, avisa con un mensaje claro). |
| **Premades (ambos equipos)** | En el historial, el scoreboard y el Live, marca quién va en grupo — **aliados y enemigos** — inferido de tu histórico (jugadores que coinciden en el mismo equipo varias veces). Detecta tus premades y dúos enemigos recurrentes; no randoms de una sola partida. |
| **Iconos** | Builds con iconos de item, runa y hechizo (Data Dragon), tanto en el meta como en tu build. |
| **Compañeros + sinergias** | Tus premades detectados: WR juntos vs sin ellos, "duos óptimos" (mejores combos tú+ellos), mejor combo recomendado por persona, y en el drawer tus champs con esa persona + todas las sinergias. |
| **Juego temprano / snowball** *(timeline)* | Oro/CS vs tu rival al minuto 15, % de partidas por delante, y **tu WR yendo por delante vs por detrás @15** (¿conviertes ventajas?, ¿remontas?). |
| **Tabla ordenable** | Clic en las cabeceras (Part., WR, ROI, KDA…) para ordenar tus campeones. |
| **Forma reciente** | Puntos verde/rojo (últimas 10 partidas de la cola) en los KPIs de cada vista. |
| **Pool** | Si tu pool está demasiado concentrado (predecible) o disperso (difícil de dominar). |

## Configuración (`config.json`)

```json
{
  "riot_id": "MarcoRubio#5570",
  "region": "euw",
  "focus_queue": "RANKED",
  "elo_bracket": "emerald_plus",
  "min_games_for_confidence": 10,
  "match_count": 200
}
```

`match_count` = cuántas partidas recientes por cola se piden a Riot **para descubrir
nuevas** en cada run (ventana de backfill). **El análisis NO se limita a esas**: usa
**todas las partidas que ya se han cacheado** en `.cache/matches/`, así que el dataset
**solo crece** — las partidas viejas nunca se descartan. `timeline_count` = cuántas (las
más recientes) descargan su *timeline* para el juego temprano. El **primer arranque tarda
~1-2 min**; los siguientes son rápidos (solo bajan lo nuevo).

> Métricas que dependen de recencia (forma reciente, juego temprano) usan ventanas
> recientes; las demás (champs, matchups, compañeros, items) usan todo el histórico. Si en
> el futuro quieres limitar a "tu yo actual" (p.ej. solo esta temporada), se puede añadir
> un filtro por antigüedad.

## El baseline de meta (`meta_cache.json`)

Los winrates de meta por campeón (de lolalytics, en tu elo) viven en `meta_cache.json`.
Activan la columna **ROI** y deciden el `role` usado para los builds. Refréscalo por
parche. Si no existe, el análisis sigue funcionando sin ROI ni builds.

```json
{ "patch": "16.12", "elo": "emerald_plus",
  "by_id": { "50": {"name":"Swain","role":"support","meta_win_rate":50.05,"tier":"B"} } }
```

## Arquitectura

```
app.py                      lanza la app web local (servidor + dashboard)
run.py                      reporte estático one-shot (sin servidor)
lol_analyzer/
  engine.py                 motor: baja partidas 1 vez, analiza cada cola, arma el payload JSON
  server.py                 servidor HTTP (stdlib) + API JSON (/api/data, /api/refresh)
  web/index.html            dashboard interactivo (SPA vanilla JS)
  http.py                   fetch (urllib) + caché de disco
  collectors/
    riot.py                 Riot API: cuenta, liga (LP), match-v5 (con caché de partidas)
    opgg.py                 fallback: tus stats por champ (RSC de op.gg)
    opgg_build.py           builds recomendados (runas + items, core + situacionales)
    ddragon.py              mapas id→nombre de champ/item (Data Dragon)
  analysis/
    matches.py              agrega match-v5 por champ + hábitos por partida (tilt/horario)
    matchups.py             matchups en línea (tu WR vs el enemigo) + inferencia de rol
    champions.py            Wilson, ROI, clasificación (main/lean/bench/sample)
    habits.py               perfil de hábitos + disciplina de pool
    recommend.py            sintetiza recomendaciones (incl. anti-tilt y matchups)
  store/db.py               SQLite (tracking histórico)
  report/render.py          reporte HTML estático (lo usa run.py)
```

## Limitaciones honestas

- La **dev key** de Riot caduca cada 24h (re-pégala al usarla otro día). Una personal key
  aprobada no caduca.
- El **baseline de meta** y los **builds** son snapshots; refréscalos por parche.
- Los benchmarks de hábitos son heurísticos (pool mixto de Emerald), no absolutos.
- `match_count` limita cuántas partidas se traen por cola; súbelo para más historial.
- Sin key, se usa op.gg (solo ranked, sin hábitos por partida ni LP en vivo).
- **No se usa (todavía) el endpoint *timeline*** de Riot: por eso no hay aún métricas de
  progresión en partida (oro/CS diff @15, "lane lead", si conviertes/regalas ventajas,
  tasa de remontada). Es el mayor dato pendiente; requiere descargar el timeline de cada
  partida (más llamadas) y parsearlo.
- **Matchups de meta (lolalytics/op.gg counters): no scrapeables.** La API de lolalytics
  rechaza las peticiones ("invalid end point") y op.gg no expone el WR de counters en su
  SSR. Por eso la comparación de matchups vs meta no está; en cambio sí tienes tus
  matchups personales (mejores datos) y la comparación de *builds* vs meta.
