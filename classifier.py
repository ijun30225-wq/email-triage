"""Classify emails by shelling out to headless Claude Code (`claude -p`).

Uses the Claude Pro subscription — no API key needed.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

PROMPT_TEMPLATE = """You are an email triage assistant for Jun, a college student (ECE major at RPI).

Below is a JSON array of emails from one of Jun's inboxes. Classify each one:

- "promo": marketing, ads, sales, newsletters, job-board spam (Lensa etc.), social media
  notifications, automated no-reply mail nobody would ever respond to.
- "fyi": receipts, order/shipping confirmations, account alerts, school announcements,
  bills — worth knowing about but needs no reply.
- "needs_response": a real person or organization expecting a reply from Jun —
  professors, TAs, recruiters, coaches, administrators, friends, interview scheduling,
  anything with a question or action directed personally at Jun.

For every email output an object with:
- "id": copied from the input
- "category": one of the three strings above
- "important": true if Jun should see this promptly — bank/credit-card or fraud alerts,
  account security problems, recruiter or interview messages (e.g. Indeed), deadlines,
  anything time-sensitive personally directed at Jun. Otherwise false. Routine
  promos/newsletters are NEVER important.
- "summary": one plain sentence (max 20 words) saying who wants what
- "draft": ONLY for needs_response — a short, polite reply written in Jun's voice
  (friendly, concise, student-appropriate). Leave out anything you'd have to invent
  (dates, decisions); instead put [YOUR ANSWER] placeholders. For other categories use null.

Output ONLY a JSON array. No markdown fences, no commentary.

Emails:
{emails_json}"""


def _claude_path() -> str:
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")


def classify(emails: list[dict], model: str = "haiku") -> dict[str, dict]:
    """Return {message_id: {category, summary, draft}} for a batch of emails."""
    payload = [
        {k: e[k] for k in ("id", "from", "subject", "date", "snippet", "body")}
        for e in emails
    ]
    prompt = PROMPT_TEMPLATE.format(emails_json=json.dumps(payload, ensure_ascii=False))
    result = subprocess.run(
        [_claude_path(), "-p", prompt, "--model", model],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(PROJECT_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr[:500]}")

    match = re.search(r"\[.*\]", result.stdout, re.DOTALL)
    if not match:
        raise RuntimeError(f"No JSON array in claude output: {result.stdout[:500]}")
    items = json.loads(match.group(0))
    return {item["id"]: item for item in items if "id" in item}
