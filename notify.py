"""Notifications: macOS (terminal-notifier with click-through, osascript fallback)
and phone push via ntfy.sh (tap opens the email thread)."""

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
HELPER_APP = PROJECT_DIR / "Email Triage.app"
PAYLOAD_FILE = PROJECT_DIR / ".notify_payload"


def _oneline(s: str) -> str:
    return " ".join((s or "").split())


def notify(title: str, subtitle: str, body: str, url: str | None = None):
    """macOS notification.

    With a URL: posted through the helper app ("Email Triage.app"), so clicking
    the notification relaunches the helper, which opens the email in the browser.
    (Clicking an older notification opens the most recent URL — helper keeps one.)
    Without a URL (or no helper app): plain osascript notification.
    """
    if url and HELPER_APP.exists():
        PAYLOAD_FILE.write_text(
            "\n".join([_oneline(title), _oneline(subtitle), _oneline(body), url])
        )
        subprocess.run(["open", "-a", str(HELPER_APP)], capture_output=True)
        time.sleep(2)  # let the helper consume the payload before the next one
        return
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)} subtitle {json.dumps(subtitle)} sound name \"Glass\""
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def push_phone(topic: str, title: str, body: str, url: str | None = None,
               priority: str = "default", tags: str = ""):
    """Push to the ntfy app on the phone. Tapping the notification opens `url`.

    Uses ntfy's JSON publish API — plain HTTP headers reject non-ASCII (emoji
    in titles broke them), JSON bodies are UTF-8 safe.
    """
    if not topic:
        return
    payload = {
        "topic": topic,
        "title": title,
        "message": body,
        "priority": {"low": 2, "default": 3, "high": 4, "max": 5}.get(priority, 3),
        "tags": [tags] if tags else [],
    }
    if url:
        payload["click"] = url
    req = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        # best-effort: never break the triage run, but leave a trace in the logs
        print(f"phone push failed: {exc}", file=sys.stderr)
