"""Local web app: a tiny stdlib HTTP server that serves an interactive dashboard
and a JSON API. No external dependencies, runs on 127.0.0.1 only (your machine).
"""
import json
import secrets
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import json as _json
from urllib.parse import urlparse, parse_qs

from . import engine
from .collectors import riot
from .analysis import matches as matchlib

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
_state = {"payload": None, "cfg": None, "key": None, "lock": threading.Lock(),
          "error": None, "loading": False, "puuid": None, "champ_map": None}


def _auto_refresh_loop(minutes):
    while True:
        time.sleep(minutes * 60)
        _gather()  # gather only downloads NEW matches (the rest are cached)


def _gather():
    with _state["lock"]:
        _state["loading"] = True
        try:
            ds = engine.gather(_state["cfg"], _state["key"])
            _state["payload"] = engine.build_payload(ds)
            _state["puuid"] = ds["puuid"]
            _state["champ_map"] = ds["champ_map"]
            _state["rank_map"] = ds.get("rank_map", {})
            _state["pair_index"] = ds.get("pair_index", {})
            _state["error"] = None
        except riot.RiotError as e:
            _state["error"] = str(e)
        except Exception as e:  # don't kill the server on a transient fetch error
            _state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _state["loading"] = False


def _token():
    return ((_state.get("cfg") or {}).get("access_token") or "").strip()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        tok = _token()
        if not tok:
            return True  # no token configured (e.g. localhost-only use)
        q = parse_qs(urlparse(self.path).query)
        if (q.get("token") or [""])[0] == tok:
            return True
        for part in self.headers.get("Cookie", "").split(";"):
            if part.strip() == f"rc_token={tok}":
                return True
        return False

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            if not self._authed():
                self._send(401, "<body style='font:16px system-ui;background:#0d1117;color:#c9d1d9;"
                           "padding:40px'><h2>Acceso restringido</h2><p>Añade tu token a la URL: "
                           "<code>?token=TU_TOKEN</code></p></body>", "text/html; charset=utf-8")
                return
            headers = {}
            q = parse_qs(urlparse(self.path).query)
            if _token() and (q.get("token") or [""])[0] == _token():
                headers["Set-Cookie"] = f"rc_token={_token()}; Max-Age=2592000; SameSite=Lax; Path=/"
            self._send(200, (WEB / "index.html").read_text(encoding="utf-8"),
                       "text/html; charset=utf-8", headers)
            return
        if not self._authed():
            self._send(401, json.dumps({"error": "token requerido"}))
            return
        if path == "/api/data":
            if _state["error"]:
                self._send(503, json.dumps({"error": _state["error"]}))
            elif _state["payload"] is None:
                self._send(202, json.dumps({"status": "loading"}))
            else:
                self._send(200, json.dumps(_state["payload"], ensure_ascii=False))
        elif path == "/api/match":
            qs = parse_qs(urlparse(self.path).query)
            mid = (qs.get("id") or [""])[0]
            cf = riot.MATCH_CACHE / f"{mid}.json"
            if not mid:
                self._send(400, json.dumps({"error": "falta id de partida"}))
            elif _state.get("puuid") is None:
                self._send(503, json.dumps({"error": "datos aún cargando, espera unos segundos"}))
            elif not cf.exists():
                self._send(404, json.dumps({"error": f"la partida {mid} no está en caché"}))
            else:
                try:
                    match = _json.loads(cf.read_text(encoding="utf-8"))
                    detail = matchlib.match_detail(match, _state["puuid"], _state["champ_map"],
                                                   _state.get("rank_map"), _state.get("pair_index"))
                    self._send(200, json.dumps(detail, ensure_ascii=False))
                except Exception as e:
                    self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))
        elif path == "/api/live":
            if _state.get("puuid") is None:
                self._send(503, json.dumps({"error": "datos aún cargando"}))
            else:
                try:
                    client = riot.RiotClient(_state["key"], _state["cfg"]["region"])
                    data = engine.live_game(client, _state["puuid"], _state["champ_map"],
                                            _state.get("pair_index") or {})
                    self._send(200, json.dumps(data, ensure_ascii=False))
                except riot.RiotError as e:
                    self._send(502, json.dumps({"error": str(e)}))
                except Exception as e:
                    self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._authed():
            self._send(401, json.dumps({"error": "token requerido"}))
            return
        if self.path.split("?", 1)[0] == "/api/refresh":
            _gather()
            if _state["error"]:
                self._send(503, json.dumps({"error": _state["error"]}))
            else:
                self._send(200, json.dumps(_state["payload"], ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args):
        pass  # keep the console clean


def serve(cfg, key, port=8770, open_browser=True):
    if not key:
        print("La app web necesita la Riot API key (riot_key.txt o RIOT_API_KEY).")
        return
    host = cfg.get("host", "127.0.0.1") or "127.0.0.1"
    lan = host not in ("127.0.0.1", "localhost")
    # When exposed on the LAN, never run without a token: auto-generate one if missing.
    if lan and not (cfg.get("access_token") or "").strip():
        cfg["access_token"] = secrets.token_urlsafe(6)
    _state["cfg"], _state["key"] = cfg, key
    token = _token()
    suffix = f"?token={token}" if token else ""

    # Bind the port immediately, then load data in the background so the page is
    # reachable right away (it shows a loading state and polls /api/data).
    httpd = ThreadingHTTPServer((host, port), Handler)
    local_url = f"http://127.0.0.1:{port}/{suffix}"
    print(f"\n  >> App en {local_url}  (Ctrl+C para parar)")
    if lan:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"  >> Desde tu móvil (misma WiFi): http://{lan_ip}:{port}/{suffix}")
        except Exception:
            print(f"  >> Desde tu móvil: http://<IP-de-tu-PC>:{port}/{suffix}")
        print(f"  >> Token de acceso: {token}")
    print()
    threading.Thread(target=_gather, daemon=True).start()
    mins = cfg.get("auto_refresh_minutes", 10)
    if mins:
        threading.Thread(target=_auto_refresh_loop, args=(mins,), daemon=True).start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(local_url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nApp detenida.")
        httpd.shutdown()
