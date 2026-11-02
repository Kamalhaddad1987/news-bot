"""Optional: AI-written briefing narrative via the Claude API.

Turns on automatically when the ANTHROPIC_API_KEY secret exists. Without it,
briefings are still produced from the rules alone.
"""
import json
import os
import urllib.request

SYSTEM = (
    "You write short market news briefings for an individual investor who tracks "
    "tech and AI stocks. Use only the items provided; do not add facts. Group related "
    "stories, lead with what matters most, and explain in plain words why each matters. "
    "Never recommend buying or selling. Keep it under 180 words, no headings, "
    "at most 5 short bullet points."
)


def ai_summary(kind: str, items: list[dict], movers: list[dict]) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not (items or movers):
        return None
    lines = [f"- [{i['ticker']}] ({i['category']}, score {i['score']}) {i['title']} — {i.get('source','')}" for i in items]
    lines += [f"- [{m['ticker']}] moved {m['change_pct']:+.1f}%" for m in movers]
    body = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"),
        "max_tokens": 600,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Write the {kind} briefing from these items:\n" + "\n".join(lines)}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip() or None
    except Exception as e:
        print(f"AI summary skipped: {e}")
        return None
