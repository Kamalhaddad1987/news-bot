# Market wire: your tech & AI news bot

Watches 23 companies across Big Tech, AI chips, AI software, Tesla & SpaceX,
AI energy, and quantum computing. It runs free on GitHub and gives you:

- **A live dashboard** that refreshes through the day, ranked by importance
- **Three briefings** on trading days: ~8:30 AM, ~12:30 PM, ~4:30 PM Eastern
- **WhatsApp + push alerts** for major events only
- **Feedback buttons** that tune what counts as important

"Real-time" here means within about 15–20 minutes: GitHub's free scheduler
checks every 15 minutes and can run late when it's busy.

---

## One-time setup (about 30 minutes)

### 1. Create the repository
1. Sign up at github.com (free) if you don't have an account.
2. Create a new repository named `news-bot`. Make it **Public**. Free GitHub
   Pages and unlimited free automation minutes need a public repo. The
   dashboard only shows public news; your phone number and keys stay hidden
   in Secrets (step 3).
3. Upload every file from this folder, **including the hidden `.github`
   folder**. Easiest: GitHub Desktop, or drag the folder into the
   "uploading an existing file" page. Check afterwards that
   `.github/workflows/` contains three `.yml` files.

### 2. Get your alert channels
**WhatsApp (CallMeBot, free):** follow the instructions at
callmebot.com → "Free API WhatsApp". You add their number to your contacts,
send the permission message, and they reply with your personal API key.

**Push notifications (ntfy, free):** install the **ntfy** app (iPhone or
Android). Tap + and subscribe to a topic name only you would know, like
`marketwire-7f3k9q2x`. Anyone who knows the name can read it, so make it
random.

### 3. Add your secrets
Repository → **Settings → Secrets and variables → Actions**.

Under **Secrets**, add:

| Name | Value |
|---|---|
| `SEC_USER_AGENT` | Your name and email, e.g. `Jane Smith jane@example.com` (the SEC requires this) |
| `WHATSAPP_PHONE` | Your number with country code, digits only, e.g. `12145550100` |
| `CALLMEBOT_APIKEY` | The key CallMeBot sent you |
| `NTFY_TOPIC` | Your ntfy topic name |
| `ANTHROPIC_API_KEY` | Optional. Adds AI-written briefing summaries (see below) |

Under **Variables**, add `DASHBOARD_URL` = `https://YOUR-USERNAME.github.io/news-bot/`

### 4. Turn things on
1. **Settings → Actions → General → Workflow permissions:** choose
   **Read and write permissions**, then Save.
2. **Settings → Pages:** Source = **Deploy from a branch**, Branch = `main`,
   folder = `/docs`. Save. Your dashboard appears at the URL above within a
   few minutes.
3. **Actions tab:** if asked, click to enable workflows. Open
   **Collect news → Run workflow**. In about a minute the dashboard fills up.
4. Test a briefing: **Briefings → Run workflow → morning**. Your phone should
   get a push notification.

From then on it runs by itself.

---

## AI-written briefings (optional)

Without an API key, briefings are built from the rules: top stories by group,
movers, and filings. With `ANTHROPIC_API_KEY` set, each briefing also gets a
short plain-English summary written by Claude (model set in
`bot/summarize.py`). API usage is billed through the Claude Console, separate
from a Claude chat subscription; Max and Team plans include monthly API
credits. Create a key at platform.claude.com.

---

## Tuning it (the 2-month feedback loop)

**On the dashboard:** every story has 👍, 👎, Mute source and Comment.
Each opens a pre-filled GitHub issue; submit it and the bot applies it
within a minute, replies with what changed, and closes the issue.
- 👍 / 👎 nudge that topic and that outlet up or down
- Mute source hides that outlet for good
- Comments are logged in `state/feedback_log.jsonl`

Only issues **you** open are applied, so strangers can't tune your bot.

**With Claude:** paste or upload `state/feedback_log.jsonl` and
`config/rules.yaml` into a chat and say what you want changed. Claude edits
the rules; you upload the new file.

**By hand:**
- `config/watchlist.yaml`: companies, groups, big-move thresholds
  (5% default, 4% for AI energy and quantum)
- `config/rules.yaml`: topic scores, noise filters, what counts as major,
  alert limits, quiet hours (no alerts 11 PM–6 AM ET), briefing times

---

## What's in here

```
bot/collect.py     gathers news, filings and prices; scores; sends alerts
bot/sources.py     SEC EDGAR, Google News and Yahoo RSS, price quotes
bot/scoring.py     topic detection, noise filter, duplicate-story merging
bot/briefing.py    morning / midday / close briefings
bot/feedback.py    applies your dashboard votes
bot/notify.py      WhatsApp (CallMeBot) and push (ntfy)
docs/index.html    the dashboard (GitHub Pages)
docs/data/         what the dashboard reads (written by the bot)
state/             memory between runs, plus your feedback log
tests/             offline test: python -m tests.test_offline
```

## If something stops

- **No updates:** Actions tab → check the latest run for a red ✗ and open it.
  GitHub sometimes pauses schedules on quiet repos; re-enable from the
  workflow page.
- **"Source issues" on the dashboard:** hover it to see which feed failed.
  Free sources occasionally rate-limit; the next run usually recovers.
- **No WhatsApp:** CallMeBot is a small free service with no guarantees.
  Push notifications keep working as the backup.

This bot summarizes public news. It is not investment advice.
