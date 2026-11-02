"""Alert channels. Secrets come from environment variables (GitHub Secrets)."""
import os
import time
import urllib.parse
import urllib.request

from .util import http_get


def whatsapp(text: str) -> bool:
    """Free WhatsApp messages to your own number via CallMeBot."""
    phone, key = os.environ.get("WHATSAPP_PHONE"), os.environ.get("CALLMEBOT_APIKEY")
    if not (phone and key):
        return False
    url = "https://api.callmebot.com/whatsapp.php?" + urllib.parse.urlencode(
        {"phone": phone.lstrip("+"), "text": text[:1500], "apikey": key})
    try:
        http_get(url, timeout=30, retries=1)
        time.sleep(2)  # CallMeBot asks for gentle pacing
        return True
    except Exception as e:
        print(f"whatsapp failed: {e}")
        return False


def push(title: str, body: str, priority: str = "default", tags: str = "", click: str = "") -> bool:
    """Push notification via ntfy (free app for iPhone and Android)."""
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Priority": priority}
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click
    req = urllib.request.Request(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except Exception as e:
        print(f"push failed: {e}")
        return False


def format_alert(item: dict) -> tuple[str, str]:
    """(title, body) for one major item."""
    if item["kind"] == "move":
        title = f"{item['ticker']} {item['change_pct']:+.1f}% today"
    else:
        title = f"{item['ticker']}: {item.get('category_label', item['category'])}"
    body = item["title"]
    if item.get("source") and item["kind"] != "move":
        body += f"\n— {item['source']}"
        n = len(item.get("outlets", [])) - 1
        if n > 0:
            body += f" (+{n} more outlets)"
    if item.get("url"):
        body += f"\n{item['url']}"
    return title, body
