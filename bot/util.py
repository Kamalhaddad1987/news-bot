"""Shared helpers: HTTP, files, and the market clock."""
import json
import os
import time
import urllib.request
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
STATE = ROOT / "state"
DATA = ROOT / "docs" / "data"
ET = ZoneInfo("America/New_York")

# NYSE full-day holidays.
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}


def user_agent() -> str:
    # The SEC asks automated readers to identify themselves with a name and email.
    return os.environ.get("SEC_USER_AGENT", "").strip() or "news-bot (set SEC_USER_AGENT)"


def http_get(url: str, headers: dict | None = None, timeout: int = 20, retries: int = 2) -> bytes:
    h = {"User-Agent": user_agent(), "Accept": "*/*"}
    h.update(headers or {})
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # network errors, 429s, timeouts
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def load_yaml(name: str) -> dict:
    with open(CONFIG / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    tmp.replace(path)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_et() -> datetime:
    return now_utc().astimezone(ET)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def market_session(t: datetime | None = None) -> str:
    """'pre', 'open', 'after', or 'closed' (Eastern Time)."""
    t = (t or now_et()).astimezone(ET)
    if not is_trading_day(t.date()):
        return "closed"
    hm = t.hour * 60 + t.minute
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "pre"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "open"
    if 16 * 60 <= hm < 20 * 60:
        return "after"
    return "closed"


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def watchlist() -> dict:
    """ticker -> {name, group, group_label, listed, move_pct}"""
    wl = load_yaml("watchlist.yaml")
    default_move = float(wl.get("defaults", {}).get("move_pct", 5.0))
    out = {}
    for gkey, g in (wl.get("groups") or {}).items():
        gmove = float(g.get("move_pct", default_move))
        for tk, info in (g.get("tickers") or {}).items():
            info = info or {}
            out[tk.upper()] = {
                "name": info.get("name", tk),
                "group": gkey,
                "group_label": g.get("label", gkey),
                "listed": info.get("listed", True),
                "move_pct": float(info.get("move_pct", gmove)),
                "aliases": info.get("aliases") or [info.get("name", tk).split()[0]],
                "query": info.get("query"),
                "cik": info.get("cik"),
            }
    return out
