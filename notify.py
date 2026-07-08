"""Notifications: macOS (terminal-notifier with click-through, osascript fallback)
and phone push via ntfy.sh (tap opens the email thread)."""

import json
import subprocess
import sys
import urllib.request


def notify(title: str, subtitle: str, body: str, url: str | None = None):
    """macOS notification via osascript.

    Note: osascript notifications can't carry a click action, so `url` is unused
    here — phone pushes (push_phone) carry the tap-to-open link instead.
    terminal-notifier supported click-through but renders nothing on recent macOS.
    """
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)} subtitle {json.dumps(subtitle)} sound name \"Glass\""
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def push_phone(topic: str, title: str, body: str, url: str | None = None,
               priority: str = "default", tags: str = "email"):
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
