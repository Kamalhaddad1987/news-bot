"""Applies your dashboard feedback.

Dashboard buttons open a pre-filled GitHub issue titled "[feedback] ...". This
script reads those issues (only ones you opened), adjusts state/learned.json,
logs every comment to state/feedback_log.jsonl, then closes the issue.
"""
import json
import os
import re
import urllib.request

from .util import DATA, STATE, iso, load_json, now_utc, save_json

API = "https://api.github.com"
CAPS = {"category": (-25, 15), "source": (-30, 10)}


def _gh(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json", "User-Agent": "news-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read()
        return json.loads(txt) if txt else {}


def _field(body: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.*)$", body or "", re.M | re.I)
    return m.group(1).strip() if m else ""


def _bump(d: dict, key: str, delta: int, cap: tuple) -> int:
    d[key] = max(cap[0], min(cap[1], d.get(key, 0) + delta))
    return d[key]


def apply(vote: str, item: dict | None, comment: str, lr: dict) -> str:
    if not item:
        return "Saved your comment (no item attached)."
    cat, src = item.get("category", "general"), item.get("source", "")
    if vote == "up":
        c = _bump(lr["category_adjust"], cat, 2, CAPS["category"])
        s = _bump(lr["source_adjust"], src, 1, CAPS["source"]) if src else 0
        return f"Boosted '{cat}' ({c:+d}) and source '{src}' ({s:+d})."
    if vote == "down":
        c = _bump(lr["category_adjust"], cat, -2, CAPS["category"])
        s = _bump(lr["source_adjust"], src, -2, CAPS["source"]) if src else 0
        return f"Lowered '{cat}' ({c:+d}) and source '{src}' ({s:+d})."
    if vote == "mute-source" and src:
        if src not in lr["muted_sources"]:
            lr["muted_sources"].append(src)
        return f"Muted source '{src}'."
    return "Saved your comment."


def run() -> int:
    repo, owner = os.environ["GITHUB_REPOSITORY"], os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    feed = {f["id"]: f for f in load_json(DATA / "feed.json", {"items": []})["items"]}
    lr = load_json(STATE / "learned.json", {"category_adjust": {}, "source_adjust": {},
                                            "muted_sources": [], "noise_extra": []})
    issues = _gh("GET", f"/repos/{repo}/issues?state=open&per_page=50")
    done = 0
    for iss in issues:
        if "pull_request" in iss or not iss["title"].lower().startswith("[feedback]"):
            continue
        if owner and iss["user"]["login"].lower() != owner.lower():
            continue  # public repo: only the owner can tune the bot
        body = iss.get("body") or ""
        vote, item_id, comment = _field(body, "vote").lower(), _field(body, "item"), _field(body, "comment")
        item = feed.get(item_id)
        result = apply(vote, item, comment, lr)
        with open(STATE / "feedback_log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": iso(now_utc()), "vote": vote, "item": item_id,
                                "ticker": (item or {}).get("ticker"), "title": (item or {}).get("title"),
                                "category": (item or {}).get("category"), "source": (item or {}).get("source"),
                                "comment": comment, "result": result}, ensure_ascii=False) + "\n")
        _gh("POST", f"/repos/{repo}/issues/{iss['number']}/comments", {"body": f"Applied: {result}"})
        _gh("PATCH", f"/repos/{repo}/issues/{iss['number']}", {"state": "closed"})
        done += 1
    save_json(STATE / "learned.json", lr)
    print(f"Processed {done} feedback item(s).")
    return done
