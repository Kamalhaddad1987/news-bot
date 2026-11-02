"""Turns raw items into scored, de-duplicated items with a tier."""
import re

from .util import STATE, load_json

STOP = set("the a an of to in on for and or is are as at by with from its it this that after over new says".split())


def learned() -> dict:
    """Adjustments built from your feedback (see feedback.py)."""
    return load_json(STATE / "learned.json", {
        "category_adjust": {}, "source_adjust": {}, "muted_sources": [], "noise_extra": [],
    })


def _tier(score: float, rules: dict) -> str:
    if score >= rules["tiers"]["major"]:
        return "major"
    if score >= rules["tiers"]["notable"]:
        return "notable"
    return "info"


def score_news(item: dict, rules: dict, lr: dict) -> dict:
    title, source = item["title"], item.get("source", "")
    muted_sources = [s.lower() for s in (rules.get("muted_sources") or []) + lr["muted_sources"]]
    if source.lower() in muted_sources:
        return {**item, "score": 0, "tier": "muted", "category": "muted", "reasons": [f"muted source: {source}"]}
    for pat in (rules.get("noise") or []) + lr["noise_extra"]:
        if re.search(pat, title, re.I):
            return {**item, "score": 0, "tier": "muted", "category": "noise", "reasons": [f"noise: {pat}"]}

    best_cat, best, reasons = "general", 20.0, []
    for key, cat in rules["categories"].items():
        if any(re.search(p, title, re.I) for p in cat["patterns"]):
            s = cat["score"] + lr["category_adjust"].get(key, 0)
            reasons.append(cat["label"])
            if s > best:
                best_cat, best = key, s

    if best_cat == "analyst" and re.search(r"upgrade|downgrade", title, re.I):
        if any(re.search(rf"\b{re.escape(b)}\b", title, re.I) for b in rules.get("major_analysts", [])):
            best = max(best, rules.get("major_analyst_score", 72))
            reasons.append("major bank")

    best += lr["source_adjust"].get(source, 0)
    best = max(0.0, min(100.0, best))
    return {**item, "score": round(best), "tier": _tier(best, rules), "category": best_cat, "reasons": reasons}


def score_filing(item: dict, rules: dict, lr: dict) -> dict:
    sec = rules["sec"]
    form = item["form"]
    base_form = "424B" if form.startswith("424B") else form
    s = float(sec["form_scores"].get(base_form, 30))
    reasons, topic = [form], "sec"
    for it in item.get("items", []):
        if it in sec["eight_k_items"]:
            val, label, *rest = sec["eight_k_items"][it]
            reasons.append(label)
            if float(val) > s:
                s, topic = float(val), (rest[0] if rest else "sec")
    s += rules["boosts"]["sec_filing"] + lr["category_adjust"].get("sec", 0)
    s = max(0.0, min(100.0, s))
    if len(reasons) > 1:
        item = {**item, "title": f"{item['ticker']} {form}: {', '.join(reasons[1:])}"}
    return {**item, "score": round(s), "tier": _tier(s, rules), "category": "sec", "topic": topic,
            "reasons": reasons}


def _words(title: str) -> set:
    return {w for w in re.findall(r"[a-z0-9$%.]+", title.lower()) if w not in STOP and len(w) > 2}


def cluster(items: list[dict], rules: dict) -> list[dict]:
    """Merge headlines about the same story (same ticker, similar words)."""
    out: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"]):
        if it["kind"] != "news" or it["tier"] == "muted":
            out.append(it)
            continue
        w = _words(it["title"])
        home = None
        for c in out:
            if c["kind"] == "news" and c["ticker"] == it["ticker"] and c["tier"] != "muted":
                cw = _words(c["title"])
                if w and cw and len(w & cw) / len(w | cw) >= 0.45:
                    home = c
                    break
        if home is None:
            out.append({**it, "outlets": [it.get("source", "")]})
            continue
        if it.get("source") and it["source"] not in home["outlets"]:
            home["outlets"].append(it["source"])
        home.setdefault("merged_ids", []).append(it["id"])
        if it["score"] > home["score"]:  # keep the clearest headline
            home.update({k: it[k] for k in ("title", "url", "source", "category", "reasons")})
            home["score"] = it["score"]
    b = rules["boosts"]
    for c in out:
        c["base_score"] = c["score"]
        extra = max(0, len(c.get("outlets", [])) - 1)
        if extra:
            c["score"] = min(100, c["score"] + min(b["max_outlet_boost"], extra * b["per_extra_outlet"]))
            c["tier"] = _tier(c["score"], rules)
    return out
