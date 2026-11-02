"""One collection pass: gather -> score -> merge -> alert -> write dashboard data."""
import os
from datetime import timedelta

from . import notify, scoring, sources
from .util import (DATA, STATE, ET, iso, load_json, load_yaml, market_session, now_et, now_utc,
                   parse_iso, save_json, watchlist)

FEED = DATA / "feed.json"
PRICES = DATA / "prices.json"
META = DATA / "meta.json"
ALERTS = STATE / "alerts.json"
SEEN = STATE / "seen.json"

KEEP_DAYS = 7
MAX_FEED = 900


def should_run(force: bool) -> bool:
    """Every 15 min while the market is open, every 30 min pre/after hours, hourly otherwise."""
    if force:
        return True
    slot = now_et().minute // 15
    return {"open": True, "pre": slot in (0, 2), "after": slot in (0, 2)}.get(market_session(), slot == 0)


def _similar(a: dict, b: dict) -> bool:
    wa, wb = scoring._words(a["title"]), scoring._words(b["title"])
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.45


def merge_into_feed(feed: list[dict], new: list[dict], rules: dict) -> list[dict]:
    """Attach new headlines to an existing story when they repeat it. Returns new stories."""
    cutoff = iso(now_utc() - timedelta(hours=36))
    recent = [f for f in feed if f["kind"] == "news" and f["tier"] != "muted" and f["first_seen"] >= cutoff]
    created = []
    for it in new:
        home = None
        if it["kind"] == "news" and it["tier"] != "muted":
            home = next((f for f in recent if f["ticker"] == it["ticker"] and _similar(f, it)), None)
        if home is None:
            feed.append(it)
            created.append(it)
            if it["kind"] == "news":
                recent.append(it)
            continue
        for o in it.get("outlets", [it.get("source", "")]):
            if o and o not in home.setdefault("outlets", []):
                home["outlets"].append(o)
        home.setdefault("merged_ids", []).extend([it["id"]] + it.get("merged_ids", []))
        b = rules["boosts"]
        base = max(home.get("base_score", home["score"]), it.get("base_score", it["score"]))
        bump = min(b["max_outlet_boost"], (len(home["outlets"]) - 1) * b["per_extra_outlet"])
        home["base_score"] = base
        home["score"] = min(100, base + bump)
        home["tier"] = scoring._tier(home["score"], rules)
    return created


def check_moves(wl: dict, prices: dict, feed: list[dict], alerts_state: dict, rules: dict) -> list[dict]:
    today = now_et().date().isoformat()
    day = alerts_state.setdefault("moves", {}).setdefault(today, {})
    step = float(rules["alerts"]["repeat_move_step"])
    out = []
    for tk, p in prices.items():
        if not p or p.get("basis") != "prev_close":
            continue
        chg, thr = p["change_pct"], wl[tk]["move_pct"]
        last = day.get(tk, 0.0)
        if abs(chg) < thr or (last and abs(chg) < last + step):
            continue
        day[tk] = abs(chg)
        why = sorted([f for f in feed if f["ticker"] == tk and f["kind"] != "move" and f["tier"] != "muted"
                      and f["first_seen"] >= iso(now_utc() - timedelta(hours=18))],
                     key=lambda f: (f["kind"] != "news", -f["score"]))
        title = f"{wl[tk]['name']} ({tk}) is {'up' if chg > 0 else 'down'} {abs(chg):.1f}% today at ${p['price']}"
        if why:
            title += f". Likely related: {why[0]['title']}"
        out.append({
            "id": sources.make_id("move", tk, today, f"{abs(chg):.0f}"),
            "ticker": tk, "kind": "move", "title": title, "url": why[0]["url"] if why else "",
            "source": "Price move", "published": iso(now_utc()), "change_pct": chg,
            "score": 76, "tier": "major", "category": "move", "reasons": [f"move ≥ {thr}%"],
        })
    return out


def in_quiet_hours(rules: dict) -> bool:
    a, b = rules["alerts"]["quiet_hours_et"]
    h = now_et().hour
    return h >= a or h < b if a > b else a <= h < b


def send_alerts(feed: list[dict], rules: dict) -> int:
    if in_quiet_hours(rules):
        return 0
    fresh = iso(now_utc() - timedelta(hours=12))
    pending = sorted([f for f in feed if f["tier"] == "major" and not f.get("alerted") and f["first_seen"] >= fresh],
                     key=lambda f: (-f["score"], f["first_seen"]))
    labels = {k: v["label"] for k, v in rules["categories"].items()} | {"sec": "SEC filing", "move": "Big move"}
    dash = os.environ.get("DASHBOARD_URL", "")
    window = iso(now_utc() - timedelta(hours=float(rules["alerts"].get("same_topic_hours", 3))))
    recent = {(f["ticker"], f.get("topic", f["category"])) for f in feed if f.get("alerted") and f["alerted"] >= window}
    sent = 0
    for it in pending:
        if sent >= int(rules["alerts"]["max_per_run"]):
            break
        key = (it["ticker"], it.get("topic", it["category"]))
        if key in recent:
            it["alerted"], it["alert_channels"] = iso(now_utc()), ["grouped"]  # same story already alerted
            continue
        recent.add(key)
        it["category_label"] = labels.get(it.get("topic", it["category"]), labels.get(it["category"], it["category"]))
        title, body = notify.format_alert(it)
        ok_w = notify.whatsapp(f"*{title}*\n{body}") if rules["alerts"]["whatsapp"] else False
        ok_p = notify.push(title, body, priority="high", tags="rotating_light", click=it.get("url") or dash) \
            if rules["alerts"]["push"] else False
        it["alerted"] = iso(now_utc()) if (ok_w or ok_p) else it.get("alerted")
        it["alert_channels"] = [c for c, ok in (("whatsapp", ok_w), ("push", ok_p)) if ok]
        sent += 1 if (ok_w or ok_p) else 0
    return sent


def run(force: bool = False) -> dict:
    if not should_run(force):
        print("Skipping this slot (schedule thins out outside market hours).")
        return {}
    rules, wl, lr = load_yaml("rules.yaml"), watchlist(), scoring.learned()
    feed = load_json(FEED, {"items": []})["items"]
    seen = load_json(SEEN, {})
    alerts_state = load_json(ALERTS, {})
    health = {"errors": [], "counts": {}}

    known = set(seen) | {f["id"] for f in feed} | {m for f in feed for m in f.get("merged_ids", [])}
    raw = []

    try:
        cik_map = sources.sec_cik_map()
    except Exception as e:
        cik_map = {}
        health["errors"].append(f"SEC ticker list: {e}"[:160])

    for tk, info in wl.items():
        news, errs = sources.news(tk, info)
        raw += news
        health["errors"] += [f"{tk} news: {e}" for e in errs]
        cik = info.get("cik") or cik_map.get(tk)
        if cik:
            try:
                raw += sources.sec_filings(tk, int(cik), rules)
            except Exception as e:
                health["errors"].append(f"{tk} SEC: {e}"[:160])

    new = [r for r in raw if r["id"] not in known]
    stamp = iso(now_utc())
    scored = []
    for r in new:
        s = scoring.score_filing(r, rules, lr) if r["kind"] == "filing" else scoring.score_news(r, rules, lr)
        s["first_seen"] = stamp
        s["group"] = wl[s["ticker"]]["group"]
        scored.append(s)
    scored = scoring.cluster(scored, rules)
    created = merge_into_feed(feed, scored, rules)

    session = market_session()
    prices = load_json(PRICES, {"quotes": {}})
    if session != "closed" or force or not prices["quotes"]:
        quotes = {}
        for tk, info in wl.items():
            if info["listed"]:
                quotes[tk] = sources.price(tk)
                if quotes[tk] is None:
                    health["errors"].append(f"{tk} price unavailable")
        prices = {"quotes": quotes, "updated": stamp, "session": session}
        if session in ("open", "after"):
            moves = check_moves(wl, quotes, feed, alerts_state, rules)
            for m in moves:
                m["first_seen"], m["group"] = stamp, wl[m["ticker"]]["group"]
            feed += [m for m in moves if m["id"] not in known]

    sent = send_alerts(feed, rules)

    cutoff = iso(now_utc() - timedelta(days=KEEP_DAYS))
    feed = sorted([f for f in feed if f["first_seen"] >= cutoff], key=lambda f: f["first_seen"], reverse=True)[:MAX_FEED]
    for r in raw:
        seen.setdefault(r["id"], stamp)
    seen = {k: v for k, v in seen.items() if v >= iso(now_utc() - timedelta(days=14))}
    for d in list(alerts_state.get("moves", {})):
        if d < (now_et().date() - timedelta(days=5)).isoformat():
            del alerts_state["moves"][d]

    health["counts"] = {"fetched": len(raw), "new_stories": len(created), "alerts_sent": sent}
    save_json(FEED, {"items": feed})
    save_json(PRICES, prices)
    save_json(SEEN, seen)
    save_json(ALERTS, alerts_state)
    save_json(META, {
        "updated": stamp, "session": session, "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "groups": {v["group"]: v["group_label"] for v in wl.values()},
        "watchlist": {k: {"name": v["name"], "group": v["group"], "listed": v["listed"]} for k, v in wl.items()},
        "health": health, "ai_summaries": bool(os.environ.get("ANTHROPIC_API_KEY")),
    })
    print(f"{session}: fetched {len(raw)}, new stories {len(created)}, alerts sent {sent}, "
          f"errors {len(health['errors'])}")
    return health
