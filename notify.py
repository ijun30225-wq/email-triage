"""macOS notifications via osascript."""

import json
import subprocess


def notify(title: str, subtitle: str, body: str):
    # json.dumps produces valid AppleScript double-quoted strings
    script = (
        f"display notification {json.dumps(body)} "
        f"with title {json.dumps(title)} subtitle {json.dumps(subtitle)} sound name \"Glass\""
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)
