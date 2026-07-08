# Email Triage

Multi-account AI email triage agent for macOS. Twice a day it reads every authorized
Gmail inbox, classifies each email with Claude (**Needs Response / FYI / Promo**),
labels and stars them in Gmail, pre-writes reply drafts, and sends a macOS
notification digest. An hourly watch-list check pings immediately when mail arrives
from senders you care about (bank, recruiters, …).

Runs headless Claude Code (`claude -p`) on a Claude Pro subscription — **no API key,
no API costs**.

## Architecture

```
launchd
  ├─ 08:00 & 18:00 ─ triage.py run       full triage
  │    ├─ Gmail API ─ account 1..N       (one OAuth token per account)
  │    ├─ claude -p ─ classify + summarize + draft replies
  │    ├─ Gmail API ─ apply Triage/* labels, star, create drafts
  │    └─ osascript ─ notification digest
  └─ hourly ──────── triage.py vipcheck  watch-list scan (no AI, instant ⚠️ ping)
```

## Labels it manages

| Label | Meaning |
|---|---|
| `Triage/Needs Response` | A real person expects a reply — starred, and a **reply draft is waiting in your Drafts folder** |
| `Triage/Important` | Watch-list sender or urgent (fraud/security alerts, interviews, deadlines) — starred + ⚠️ notification |
| `Triage/FYI` | Receipts, confirmations, alerts — worth knowing, no reply needed |
| `Triage/Promo` | Marketing / newsletters / job-board spam |
| `Triage/Processed` | Hidden bookkeeping label so nothing is triaged twice |

## Setup

### 1. Install

```sh
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp config.example.json config.json   # then edit to taste
```

Requires [Claude Code](https://claude.com/claude-code) installed and logged in
(Pro subscription or better).

### 2. Google Cloud (once, ~5 minutes)

1. [console.cloud.google.com](https://console.cloud.google.com) → create a project.
2. **APIs & Services → Library** → enable **Gmail API**.
3. **OAuth consent screen** → External → add scope `.../auth/gmail.modify` →
   add every Gmail address you'll triage as a **Test user**.
4. **Credentials → Create Credentials → OAuth client ID → Desktop app** →
   download the JSON as `credentials.json` in this folder.

### 3. Authorize accounts & schedule

```sh
./venv/bin/python triage.py auth      # repeat once per Gmail account
./venv/bin/python triage.py run                # first manual pass
./venv/bin/python triage.py install-schedule   # locks in the automation
```

## Daily usage

You mostly do nothing — it runs itself. When it has something for you, each flagged
email gets its **own notification** (⚠️ important / ✉️ needs response) — **clicking or
tapping it opens that exact thread in Gmail**, in the right account. Max 5 per run,
with a "+N more" rollup beyond that.

### Notifications on your phone

Uses [ntfy](https://ntfy.sh) — free, no account:

1. Install the **ntfy** app (App Store / Play Store).
2. In the app: **+ Subscribe to topic** → enter the value of `ntfy_topic` from your
   `config.json` (pick a long random name — anyone who knows the topic can see the
   pings, so treat it like a password).
3. Done — important-email pushes arrive with tap-through to the Gmail thread.

Mac notifications use `terminal-notifier` (`brew install terminal-notifier`) for
click-through; without it they fall back to plain non-clickable notifications.

### Checking important emails

| Where | How |
|---|---|
| **Gmail (web or phone app)** | The `Triage/Important` label appears in Gmail's sidebar on every device — tap it. Labels + stars sync everywhere, so your phone's Gmail app shows the same triage. |
| **Starred view** | Anything needing attention is starred — Gmail's ⭐ Starred view is your action list. |
| **Terminal** | `./venv/bin/python triage.py important` — lists the last 7 days of important mail across all accounts. |
| **Log** | `logs/digest.log` — every run's summary, including one-line AI summaries of each item. |

### Replying

Open the email → your **Drafts** folder already has a reply written in your voice,
with `[YOUR ANSWER]` placeholders for anything the AI couldn't know. Edit, fill in,
send.

### Commands

```sh
./venv/bin/python triage.py auth               # add another Gmail account
./venv/bin/python triage.py accounts           # list authorized accounts
./venv/bin/python triage.py run                # full triage now
./venv/bin/python triage.py vipcheck           # watch-list scan now
./venv/bin/python triage.py important          # show recent important mail
./venv/bin/python triage.py install-schedule   # (re)install the launchd jobs
```

## Config (`config.json`)

| Key | Meaning |
|---|---|
| `model` | Claude model for classification (`haiku` = lightest on usage limits) |
| `lookback_days` | How far back each run scans |
| `max_emails_per_account` | Cap per run |
| `account_names` | Nicknames shown in digests/notifications |
| `vip_senders` | Watch-list — domain or address substrings matched against the From header (e.g. `capitalone.com`). Checked hourly. |

## Notes

- Classification failures leave emails untouched — they're retried next run.
- Marketing from a watch-list sender is still filed as Promo (no false ⚠️ pings).
- One school/work account behind a locked-down Microsoft 365 tenant? Forwarding is
  usually blocked; browser-automation of Outlook web is the workaround (planned).
- Secrets (`credentials.json`, OAuth tokens, personal `config.json`) are gitignored.
