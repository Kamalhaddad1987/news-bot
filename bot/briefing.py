"""Morning, midday, and close briefings."""
import os
from datetime import datetime, timedelta

from . import notify
from .summarize import ai_summary
from .util import (DATA, ET, STATE, iso, is_trading_day, load_json, load_yaml, now_et,
                   previous_trading_day, save_json, watchlist)

BRIEFS = DATA / "briefings.json"
DONE = STATE / "briefs_done.json"
TITLES = {"morning": "Morning brief", "midday": "Midday brief", "close": "Closing brief"}


def _at(d, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ET)


def due(kind: str, rules: dict) -> bool:
    """True if now is in this briefing's window and it hasn't gone out today.
    The workflow fires twice (summer and winter UTC times); this keeps exactly one."""
    t = now_et()
    if not is_trading_day(t.date()):
        return False
    target = _at(t.date(), rules["briefings"][kind])
    done = load_json(DONE, {})
    return target - timedelta(minutes=20) <= t <= target + timedelta(minutes=75) \
        and done.get(kind) != t.date().isoformat()


def window_start(kind: str, rules: dict) -> datetime:
    t = now_et()
    b = rules["briefings"]
    if kind == "morning":
        return _at(previous_trading_day(t.date()), b["close"])
    return _at(t.date(), b["morning"] if kind == "midday" else b["midday"])


def build(kind: str, force: bool = False) -> dict | None:
    rules, wl = load_yaml("rules.yaml"), watchlist()
    if not force and not due(kind, rules):
        print(f"{kind} brief not due now.")
        return None
    since = iso(window_start(kind, rules))
    feed = load_json(DATA / "feed.json", {"items": []})["items"]
    quotes = load_json(DATA / "prices.json", {"quotes": {}})["quotes"]

    pool = [f for f in feed if f["first_seen"] >= since and f["tier"] != "muted" and f["kind"] != "move"]
    top = sorted(pool, key=lambda f: -f["score"])[: int(rules["briefings"]["top_stories"])]
    movers = sorted([{"ticker": k, **v} for k, v in quotes.items() if v and abs(v["change_pct"]) >= 2],
                    key=lambda m: -abs(m["change_pct"]))
    filings = [f for f in pool if f["kind"] == "filing" and f["score"] >= rules["tiers"]["notable"]]

    by_group: dict[str, list] = {}
    for it in top:
        by_group.setdefault(wl[it["ticker"]]["group_label"], []).append(
            {k: it.get(k) for k in ("id", "ticker", "title", "url", "source", "score", "tier", "category")})

    brief = {
        "id": f"{now_et().date().isoformat()}-{kind}",
        "kind": kind, "title": TITLES[kind], "created": iso(now_et()), "since": since,
        "summary": ai_summary(TITLES[kind].lower(), top, movers[:6]),
        "groups": by_group,
        "movers": [{"ticker": m["ticker"], "change_pct": m["change_pct"], "price": m["price"]} for m in movers[:8]],
        "filings": [{"ticker": f["ticker"], "title": f["title"], "url": f["url"]} for f in filings[:6]],
        "counts": {"stories": len(pool), "major": sum(f["tier"] == "major" for f in pool)},
    }
    briefs = [b for b in load_json(BRIEFS, {"briefings": []})["briefings"] if b["id"] != brief["id"]]
    save_json(BRIEFS, {"briefings": ([brief] + briefs)[:30]})
    done = load_json(DONE, {})
    done[kind] = now_et().date().isoformat()
    save_json(DONE, done)

    if rules["alerts"].get("push"):
        lines = [f"{t['ticker']}: {t['title']}" for t in top[:3]]
        if movers:
            lines.append("Movers: " + ", ".join(f"{m['ticker']} {m['change_pct']:+.1f}%" for m in movers[:4]))
        dash = os.environ.get("DASHBOARD_URL", "")
        notify.push(f"{TITLES[kind]}: {brief['counts']['stories']} stories, {brief['counts']['major']} major",
                    "\n".join(lines) or "Quiet session so far.", tags="newspaper",
                    click=f"{dash}#briefing" if dash else "")
    print(f"{kind} brief saved: {len(top)} stories, {len(movers)} movers")
    return brief
