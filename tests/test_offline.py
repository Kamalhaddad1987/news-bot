"""Offline test: fake headlines, filings and prices; no network needed.
Run from the repo root:  python -m tests.test_offline
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import bot.util as util

tmp = Path(tempfile.mkdtemp())
(tmp / "state").mkdir()
(tmp / "docs" / "data").mkdir(parents=True)
for mod_attr in ("STATE", "DATA"):
    setattr(util, mod_attr, tmp / ("state" if mod_attr == "STATE" else "docs/data"))

from bot import briefing, collect, feedback, scoring, sources  # noqa: E402

for m in (collect, briefing, scoring, feedback):
    for name in ("STATE", "DATA"):
        if hasattr(m, name):
            setattr(m, name, getattr(util, name))
collect.FEED, collect.PRICES, collect.META = util.DATA / "feed.json", util.DATA / "prices.json", util.DATA / "meta.json"
collect.ALERTS, collect.SEEN = util.STATE / "alerts.json", util.STATE / "seen.json"
briefing.BRIEFS, briefing.DONE = util.DATA / "briefings.json", util.STATE / "briefs_done.json"

NOW = util.iso(util.now_utc())
HEADLINES = {
    "GOOGL": [
        ("Alphabet stock plunges 13% after earnings miss as search growth slows", "CNBC"),
        ("Alphabet shares plunge 13% after earnings miss, search growth slows", "Reuters"),
        ("Google stock plunges after earnings miss on slowing search growth", "Bloomberg"),
        ("Levi & Korsinsky reminds Alphabet investors of lead plaintiff deadline", "PR Newswire"),
        ("Is Alphabet a better buy than Microsoft right now?", "Motley Fool"),
        ("Wells Fargo cuts Alphabet price target to $371", "Investing.com"),
        ("Alphabet in talks to join Golden Dome defense program", "Bloomberg"),
    ],
    "NVDA": [("Goldman Sachs downgrades Nvidia to neutral on AI spending worries", "Barron's")],
    "IONQ": [("IonQ unveils new 256-qubit system", "Business Wire")],
    "ANT":  [("Anthropic sets terms for Nasdaq IPO under ticker ANT", "Reuters")],
}


def fake_news(tk, info, hours=48):
    rows = []
    for title, src in HEADLINES.get(tk, []):
        if sources._mentions(title, tk, info["aliases"]):
            rows.append({"id": sources.make_id("news", tk, title.lower()), "ticker": tk, "kind": "news",
                         "title": title, "url": "https://example.com/" + sources.make_id(title),
                         "source": src, "published": NOW})
    return rows, []


def fake_filings(tk, cik, rules, days=3):
    if tk != "GOOGL":
        return []
    return [{"id": "sec1", "ticker": tk, "kind": "filing", "form": "8-K", "items": ["2.02", "9.01"],
             "title": "GOOGL filed 8-K", "url": "https://www.sec.gov/x", "source": "SEC EDGAR", "published": NOW}]


def fake_price(tk):
    chg = {"GOOGL": -12.6, "IONQ": 4.4, "NVDA": -2.1}.get(tk, 0.3)
    return {"price": 100 + chg, "prev_close": 100.0, "change_pct": chg, "basis": "prev_close"}


sent = []
with mock.patch.object(sources, "sec_cik_map", return_value={"GOOGL": 1652044}), \
     mock.patch.object(sources, "news", side_effect=fake_news), \
     mock.patch.object(sources, "sec_filings", side_effect=fake_filings), \
     mock.patch.object(sources, "price", side_effect=fake_price), \
     mock.patch.object(collect, "market_session", return_value="open"), \
     mock.patch.object(collect, "in_quiet_hours", return_value=False), \
     mock.patch("bot.notify.whatsapp", side_effect=lambda t: sent.append(("whatsapp", t)) or True), \
     mock.patch("bot.notify.push", side_effect=lambda *a, **k: sent.append(("push", a[0])) or True):
    collect.run(force=True)
    collect.run(force=True)  # second pass must not duplicate or re-alert

    feed = util.load_json(collect.FEED, {})["items"]
    print("\nFEED (score, tier, ticker, title, outlets)")
    for f in sorted(feed, key=lambda f: -f["score"]):
        print(f"  {f['score']:>3} {f['tier']:<8} {f['ticker']:<5} {f['title'][:70]:<70} {len(f.get('outlets', [])) or ''}")
    print("\nALERTS SENT")
    for ch, t in sent:
        print(f"  {ch}: {t.splitlines()[0][:90]}")

    b = briefing.build("close", force=True)
    print("\nBRIEFING groups:", {k: len(v) for k, v in b["groups"].items()}, "movers:", b["movers"][:3])

    tiers = {f["title"][:30]: f["tier"] for f in feed}
    assert sum(1 for f in feed if f["kind"] == "news" and "plunge" in f["title"]) == 1, "story should be merged"
    assert any(f["tier"] == "muted" and "Levi" in f["title"] for f in feed), "law-firm spam should be muted"
    assert any(f["tier"] == "muted" and "better buy" in f["title"] for f in feed), "listicle should be muted"
    assert any(f["kind"] == "move" and f["ticker"] == "IONQ" for f in feed), "IONQ 4.4% should trip the 4% rule"
    assert not any(f["kind"] == "move" and f["ticker"] == "NVDA" for f in feed), "NVDA -2.1% is below 5%"
    assert any(f["kind"] == "filing" and f["tier"] == "major" for f in feed), "earnings 8-K should be major"
    first_alerts = len([s for s in sent if s[0] == "whatsapp"])

    lr = {"category_adjust": {}, "source_adjust": {}, "muted_sources": [], "noise_extra": []}
    target = next(f for f in feed if "Wells Fargo" in f["title"])
    print("\nFEEDBACK:", feedback.apply("down", target, "", lr), feedback.apply("mute-source", target, "", lr))

print(f"\nAll checks passed. WhatsApp alerts sent: {first_alerts}")
import os
if os.environ.get("KEEP_PREVIEW"):
    shutil.copytree(util.DATA, os.environ["KEEP_PREVIEW"], dirs_exist_ok=True)
shutil.rmtree(tmp)
