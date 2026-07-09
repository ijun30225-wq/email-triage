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

Context about Jun: he attends RPI (committed — not transferring, so admissions and
transfer marketing from other universities is junk to him). He is not job-hunting via
job boards; automated "job match" blasts are noise. Real humans contacting him
personally (professors, coaches, an actual recruiter writing to HIM) matter.

Below is a JSON array of emails from one of Jun's inboxes. Classify each one:

- "promo": marketing, ads, sales, newsletters; ALL job-board blasts and automated
  "job match" / "you are invited to apply" emails (Indeed, Jobright, Lensa,
  ZipRecruiter, etc.); university admissions/transfer marketing; loan and tuition
  marketing (e.g. Sallie Mae offers); social media notifications; automated
  no-reply mail nobody would ever respond to.
- "fyi": receipts, order/shipping/payment confirmations, one-time verification or
  security codes (OTP), sign-in alerts, account notices, school announcements,
  bills — worth knowing about but needs no reply.
- "needs_response": a REAL PERSON (or an organization writing to Jun specifically)
  expecting a reply — professors, TAs, coaches, administrators, friends, a recruiter
  or employer who personally contacted Jun, interview scheduling. An automated job
  match is NEVER needs_response, even if it says "you are invited to apply".

For every email output an object with:
- "id": copied from the input
- "category": one of the three strings above
- "important": true ONLY if missing it promptly would cost Jun money, account access,
  or a commitment he already has:
    * fraud, unauthorized-charge, or account-compromise alerts
    * problems with a payment or an account he holds
    * a real human writing to Jun about something time-sensitive (interview
      scheduling, a professor's deadline)
    * hard deadlines for programs Jun is ALREADY enrolled in or has applied to
  NEVER important: one-time verification/security codes (only useful the second they
  arrive — by digest time they're dead); job-board matches and career newsletters;
  university or loan marketing; routine sign-in notifications. When unsure, false.
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
