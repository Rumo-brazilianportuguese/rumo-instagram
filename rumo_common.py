"""Shared helpers for the Rumo Instagram kit."""
import html
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

# Windows consoles and pipes default to cp1252, which cannot print ✅ or →.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "posts.json"
CACHE_DIR = ROOT / "cache"
PREVIEW_DIR = ROOT / "preview"
FAILED_FILE = ROOT / "FAILED.txt"

# The live site. Tests point this at a local copy.
SITE = os.environ.get("RUMO_SITE", "https://rumopt.com").rstrip("/")
UA = {"User-Agent": "RumoInstagramKit/1.0 (+https://rumopt.com)"}

LEVEL_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}
TARGET_POSTS = 60


def norm(s: str) -> str:
    """The one normalisation used for extraction AND for checking."""
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def say(msg: str) -> None:
    print(msg, flush=True)


def fail(test: str, what: str, todo: str, code: int = 2) -> None:
    text = (
        f"STOPPED AT: {test}\n\n"
        f"WHAT HAPPENED:\n{what}\n\n"
        f"WHAT TO DO:\n{todo}\n"
    )
    FAILED_FILE.write_text(text, encoding="utf-8")
    say("\n" + text)
    sys.exit(code)


def clear_failed() -> None:
    if FAILED_FILE.exists():
        FAILED_FILE.unlink()


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"version": 1, "posts": [], "log": []}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(20):   # Windows: a virus scanner or a reader may hold the file a moment
        try:
            os.replace(tmp, STATE_FILE)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.3)


def site_url(loc: str) -> str:
    """Map a sitemap <loc> onto SITE, so tests can serve a local copy."""
    return SITE + urlparse(loc).path


def http_get(url: str, tries: int = 4):
    import requests

    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=30, allow_redirects=True)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # network hiccup
            last = repr(e)
        if i < tries - 1:
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Could not download {url}: {last}")
