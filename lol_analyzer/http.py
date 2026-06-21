"""Tiny stdlib HTTP helper with browser-like headers, gzip handling, and a disk cache.

Kept dependency-free (urllib only) so the tool runs on a bare Python install.
"""
import gzip
import io
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _headers(accept, referer=None):
    h = {
        "User-Agent": _UA,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip",
    }
    if referer:
        h["Referer"] = referer
        h["Origin"] = "https://www.op.gg"
    return h


def get(url, accept="text/html,application/xhtml+xml", referer=None,
        cache_minutes=0, timeout=30):
    """Fetch a URL as text. Optionally serve/save a disk cache for `cache_minutes`."""
    cache_file = None
    if cache_minutes > 0:
        CACHE_DIR.mkdir(exist_ok=True)
        safe = "".join(c if c.isalnum() else "_" for c in url)[-150:]
        cache_file = CACHE_DIR / f"{safe}.txt"
        if cache_file.exists():
            age = (time.time() - cache_file.stat().st_mtime) / 60
            if age < cache_minutes:
                return cache_file.read_text(encoding="utf-8")

    req = urllib.request.Request(url, headers=_headers(accept, referer))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        text = raw.decode("utf-8", "replace")

    if cache_file is not None:
        cache_file.write_text(text, encoding="utf-8")
    return text


def get_json(url, **kwargs):
    return json.loads(get(url, accept="application/json, text/plain, */*", **kwargs))
