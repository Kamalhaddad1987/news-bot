"""Collectors for SEC filings, news headlines, and prices. All free sources."""
import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET_XML
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .util import STATE, http_get, iso, load_json, now_utc, save_json

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- SEC EDGAR
def sec_cik_map() -> dict:
    """ticker -> CIK, cached for a week."""
    cache = load_json(STATE / "sec_tickers.json", {})
    if cache.get("fetched") and now_utc().timestamp() - cache["fetched"] < 7 * 86400:
        return cache["map"]
    raw = json.loads(http_get(SEC_TICKERS_URL))
    m = {row["ticker"].upper(): int(row["cik_str"]) for row in raw.values()}
    save_json(STATE / "sec_tickers.json", {"fetched": now_utc().timestamp(), "map": m})
    return m


def sec_filings(ticker: str, cik: int, rules: dict, days: int = 3) -> list[dict]:
    url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
    data = json.loads(http_get(url))
    recent = data.get("filings", {}).get("recent", {})
    cutoff = now_utc() - timedelta(days=days)
    form_scores = rules["sec"]["form_scores"]
    out = []
    for i, form in enumerate(recent.get("form", [])):
        accepted = recent["acceptanceDateTime"][i]  # e.g. 2026-10-28T16:05:12.000Z
        try:
            t = datetime.strptime(accepted[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if t < cutoff:
            break  # newest first
        base = "424B" if form.startswith("424B") else form
        if base not in form_scores:
            continue
        acc = recent["accessionNumber"][i]
        doc = recent["primaryDocument"][i]
        items = (recent.get("items") or [""] * (i + 1))[i] or ""
        out.append({
            "id": make_id("sec", acc),
            "ticker": ticker,
            "kind": "filing",
            "form": form,
            "items": [x.strip() for x in items.split(",") if x.strip()],
            "title": f"{ticker} filed {form}" + (f" (items {items})" if items else ""),
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}",
            "source": "SEC EDGAR",
            "published": iso(t),
        })
    return out


# --------------------------------------------------------------------- News
def _parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET_XML.fromstring(xml_bytes)
    rows = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if not source and " - " in title:  # Google News appends " - Publisher"
            title, source = title.rsplit(" - ", 1)
        elif source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        try:
            t = parsedate_to_datetime(pub) if pub else now_utc()
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            t = now_utc()
        rows.append({"title": title.strip(), "url": link, "source": source, "published": t})
    return rows


def _mentions(title: str, ticker: str, aliases: list[str]) -> bool:
    if re.search(rf"\b{re.escape(ticker)}\b", title):  # tickers: case-sensitive
        return True
    return any(re.search(rf"\b{re.escape(a)}\b", title, re.I) for a in aliases)


def news(ticker: str, info: dict, hours: int = 48) -> tuple[list[dict], list[str]]:
    q = info.get("query") or " OR ".join(f'"{a}"' for a in info["aliases"])
    feeds = [
        "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"({q}) when:2d", "hl": "en-US", "gl": "US", "ceid": "US:en"}),
    ]
    if info.get("listed", True):
        feeds.append(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    cutoff = now_utc() - timedelta(hours=hours)
    out, errors = [], []
    for url in feeds:
        try:
            rows = _parse_rss(http_get(url, headers={"User-Agent": "Mozilla/5.0 news-bot"}))
        except Exception as e:
            errors.append(str(e)[:120])
            continue
        for r in rows:
            if r["published"] < cutoff or not r["title"]:
                continue
            if not _mentions(r["title"], ticker, info["aliases"]):
                continue
            out.append({
                "id": make_id("news", ticker, re.sub(r"\W+", " ", r["title"].lower()).strip()),
                "ticker": ticker,
                "kind": "news",
                "title": r["title"],
                "url": r["url"],
                "source": r["source"] or "News",
                "published": iso(r["published"]),
            })
        time.sleep(0.4)
    return out, errors


# ------------------------------------------------------------------- Prices
def price(ticker: str) -> dict | None:
    """Last price vs previous close. Yahoo chart JSON first, Stooq as backup."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=5m"
        meta = json.loads(http_get(url, headers={"User-Agent": "Mozilla/5.0 news-bot"}))["chart"]["result"][0]["meta"]
        p, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
        if p and prev:
            return {"price": round(p, 2), "prev_close": round(prev, 2),
                    "change_pct": round((p / prev - 1) * 100, 2), "basis": "prev_close"}
    except Exception:
        pass
    try:
        url = f"https://stooq.com/q/l/?s={ticker.lower()}.us&f=sd2t2ohlc&h&e=csv"
        lines = http_get(url).decode().strip().splitlines()
        cols = dict(zip(lines[0].lower().split(","), lines[1].split(",")))
        o, c = float(cols["open"]), float(cols["close"])
        return {"price": round(c, 2), "prev_close": None,
                "change_pct": round((c / o - 1) * 100, 2), "basis": "open"}
    except Exception:
        return None
