"""Notifications: macOS (terminal-notifier with click-through, osascript fallback)
and phone push via ntfy.sh (tap opens the email thread)."""

import json
import shutil
import subprocess
import urllib.request


def notify(title: str, subtitle: str, body: str, url: str | None = None):
    """macOS notification. If terminal-notifier is installed, clicking opens `url`."""
    tn = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    if shutil.which(tn) or shutil.os.path.exists(tn):
        cmd = [tn, "-title", title, "-subtitle", subtitle, "-message", body,
               "-sound", "Glass", "-group", "email-triage-" + (url or title)]
        if url:
            cmd += ["-open", url]
        subprocess.run(cmd, capture_output=True)
        return
    # Fallback: plain notification, no click action
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)} subtitle {json.dumps(subtitle)} sound name \"Glass\""
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def push_phone(topic: str, title: str, body: str, url: str | None = None,
               priority: str = "default", tags: str = "email"):
    """Push to the ntfy app on the phone. Tapping the notification opens `url`."""
    if not topic:
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}", data=body.encode(), method="POST"
    )
    req.add_header("Title", title)
    req.add_header("Priority", priority)
    req.add_header("Tags", tags)
    if url:
        req.add_header("Click", url)
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # phone push is best-effort; never break the triage run
