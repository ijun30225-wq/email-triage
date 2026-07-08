#!/usr/bin/env python3
"""Multi-account AI email triage.

Commands:
  auth               Authorize a new Gmail account (opens browser). Repeat per account.
  accounts           List authorized accounts.
  run                Triage every authorized account once.
  vipcheck           Quick watch-list-only scan (no AI). Runs hourly via launchd.
  important          Show important emails from the last 7 days, all accounts.
  install-schedule   Install launchd jobs (full triage 8:00/18:00, VIP check hourly).
"""

import datetime
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import gmail_client as gm
from classifier import classify
from notify import notify, push_phone

PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_DIR / "config.json"
LOG_FILE = PROJECT_DIR / "logs" / "digest.log"
LAUNCHD_LABEL = "com.jun.email-triage"

CATEGORY_LABEL = {
    "needs_response": "Triage/Needs Response",
    "fyi": "Triage/FYI",
    "promo": "Triage/Promo",
}


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text())


def cmd_auth():
    email = gm.authorize_new_account()
    print(f"Authorized: {email}")
    print("Run `triage.py auth` again to add another account.")


def cmd_accounts():
    accounts = gm.list_accounts()
    if not accounts:
        print("No accounts authorized yet. Run: triage.py auth")
    for a in accounts:
        print(f"  {a}")


def _thread_url(account_email: str, msg_id: str) -> str:
    """Deep link to one message, in the right Gmail account, on any device."""
    return f"https://mail.google.com/mail/?authuser={account_email}#all/{msg_id}"


def _vip_match(email_info: dict, vip_senders: list[str]) -> bool:
    sender = email_info["from"].lower()  # from-header only; subjects are too noisy
    return any(s.lower() in sender for s in vip_senders)


def triage_account(email_addr: str, config: dict) -> dict:
    """Triage one account. Returns a per-account digest dict."""
    display = config.get("account_names", {}).get(email_addr, email_addr)
    vip_senders = config.get("vip_senders", [])
    service = gm.get_service(email_addr)
    labels = gm.ensure_labels(service)
    emails = gm.fetch_untriaged(
        service, labels, config.get("lookback_days", 3), config.get("max_emails_per_account", 25)
    )
    digest = {"account": display, "email": email_addr,
              "counts": {"needs_response": 0, "fyi": 0, "promo": 0},
              "needs_response": [], "important": [], "drafted": 0}
    if not emails:
        return digest

    results = classify(emails, config.get("model", "haiku"))
    for e in emails:
        r = results.get(e["id"])
        if r is None or r.get("category") not in CATEGORY_LABEL:
            continue  # not marked processed -> retried next run
        cat = r["category"]
        # A watch-list sender's marketing blast is still marketing.
        important = (cat != "promo" and _vip_match(e, vip_senders)) or bool(r.get("important"))
        star = cat == "needs_response" or important
        add = [labels[CATEGORY_LABEL[cat]], labels["Triage/Processed"]]
        if important:
            add.append(labels["Triage/Important"])
        gm.apply_triage(service, e["id"], add, star=star)
        digest["counts"][cat] += 1
        item = {"id": e["id"], "subject": e["subject"], "from": e["from"],
                "summary": r.get("summary", "")}
        if important:
            digest["important"].append(item)
        if cat == "needs_response":
            digest["needs_response"].append(item)
            if r.get("draft"):
                gm.create_reply_draft(service, e, r["draft"])
                digest["drafted"] += 1
    return digest


def cmd_run():
    config = load_config()
    accounts = gm.list_accounts()
    if not accounts:
        raise SystemExit("No accounts authorized. Run: triage.py auth")

    digests = []
    for email_addr in accounts:
        try:
            digests.append(triage_account(email_addr, config))
        except Exception as exc:  # one bad account shouldn't kill the run
            digests.append({"account": email_addr, "error": str(exc)})

    # --- log ---
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a") as f:
        f.write(f"\n=== {stamp} ===\n")
        for d in digests:
            if "error" in d:
                f.write(f"[{d['account']}] ERROR: {d['error']}\n")
                continue
            c = d["counts"]
            f.write(f"[{d['account']}] response:{c['needs_response']} "
                    f"fyi:{c['fyi']} promo:{c['promo']} drafts:{d['drafted']}\n")
            for item in d.get("important", []):
                f.write(f"  ! IMPORTANT: {item['summary']} ({item['subject']})\n")
            for item in d["needs_response"]:
                f.write(f"  * {item['summary']} ({item['subject']})\n")

    # --- notify: one clickable notification per flagged email (Mac + phone) ---
    topic = config.get("ntfy_topic", "")
    flagged = []  # (account_email, display, item, is_important) — deduped by message id
    seen = set()
    for d in digests:
        for i in d.get("important", []):
            if i["id"] not in seen:
                seen.add(i["id"])
                flagged.append((d["email"], d["account"], i, True))
        for i in d.get("needs_response", []):
            if i["id"] not in seen:
                seen.add(i["id"])
                flagged.append((d["email"], d["account"], i, False))

    MAX_PINGS = 5
    for account_email, display, item, imp in flagged[:MAX_PINGS]:
        url = _thread_url(account_email, item["id"])
        icon = "⚠️" if imp else "✉️"
        title = f"{icon} [{display}] {item['subject'][:60]}"
        notify(title, "Tap to open in Gmail", item["summary"], url=url)
        push_phone(topic, title, item["summary"], url=url,
                   priority="high" if imp else "default",
                   tags="warning" if imp else "email")
    if len(flagged) > MAX_PINGS:
        more = len(flagged) - MAX_PINGS
        notify("Email Triage", f"+{more} more flagged", "Run `triage.py important` to see all")
        push_phone(topic, "Email Triage", f"+{more} more flagged emails", priority="default")

    total_needs = sum(len(d.get("needs_response", [])) for d in digests)
    total_drafts = sum(d.get("drafted", 0) for d in digests)
    errors = [d["account"] for d in digests if "error" in d]
    if errors:
        notify("Email Triage", "Run finished with errors", ", ".join(errors))
    elif not flagged:
        notify("Email Triage", "Inbox clear", "Nothing needs a response.")
    print(f"Done. {total_needs} need response, {total_drafts} drafts created. Log: {LOG_FILE}")


def cmd_vipcheck():
    """Cheap hourly pass: ping on new mail from VIP senders. No AI call."""
    config = load_config()
    vip_senders = config.get("vip_senders", [])
    if not vip_senders:
        return
    topic = config.get("ntfy_topic", "")
    hits = 0
    for email_addr in gm.list_accounts():
        display = config.get("account_names", {}).get(email_addr, email_addr)
        try:
            service = gm.get_service(email_addr)
            labels = gm.ensure_labels(service)
            for m in gm.fetch_vip_hits(service, labels, vip_senders,
                                       config.get("lookback_days", 3)):
                gm.apply_triage(service, m["id"], [labels["Triage/Important"]], star=True)
                hits += 1
                if hits <= 5:
                    url = _thread_url(email_addr, m["id"])
                    title = f"⚠️ [{display}] {m['subject'][:60]}"
                    notify(title, "Tap to open in Gmail", m["snippet"][:120], url=url)
                    push_phone(topic, title, m["snippet"][:120], url=url,
                               priority="high", tags="warning")
        except Exception as exc:
            print(f"[{email_addr}] vipcheck error: {exc}", file=sys.stderr)
    print(f"VIP check: {hits} new hit(s).")


def cmd_important():
    """Print important emails from the last 7 days across all accounts."""
    config = load_config()
    found = 0
    for email_addr in gm.list_accounts():
        display = config.get("account_names", {}).get(email_addr, email_addr)
        service = gm.get_service(email_addr)
        resp = (
            service.users()
            .messages()
            .list(userId="me", q="label:triage-important newer_than:7d", maxResults=20)
            .execute()
        )
        refs = resp.get("messages", [])
        if not refs:
            continue
        print(f"\n[{display}]")
        for ref in refs:
            m = (
                service.users()
                .messages()
                .get(userId="me", id=ref["id"], format="metadata",
                     metadataHeaders=["From", "Subject", "Date"])
                .execute()
            )
            h = {x["name"].lower(): x["value"] for x in m["payload"].get("headers", [])}
            print(f"  {h.get('date', '')[:16]:<18} {h.get('from', '')[:38]:<40} {h.get('subject', '')}")
            found += 1
    if not found:
        print("No important emails in the last 7 days. 🎉")


def _install_job(label: str, args: list[str], schedule_key: str, schedule_value):
    plist = {
        "Label": label,
        "ProgramArguments": [sys.executable, str(PROJECT_DIR / "triage.py"), *args],
        "WorkingDirectory": str(PROJECT_DIR),
        schedule_key: schedule_value,
        "StandardOutPath": str(PROJECT_DIR / "logs" / f"{label}.out.log"),
        "StandardErrorPath": str(PROJECT_DIR / "logs" / f"{label}.err.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin:"
                    + str(Path.home() / ".local" / "bin"),
        },
    }
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    with plist_path.open("wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"Installed: {plist_path}")


def cmd_install_schedule():
    _install_job(LAUNCHD_LABEL, ["run"], "StartCalendarInterval",
                 [{"Hour": 8, "Minute": 0}, {"Hour": 18, "Minute": 0}])
    _install_job(f"{LAUNCHD_LABEL}.vip", ["vipcheck"], "StartInterval", 3600)
    print("Full triage daily at 08:00 & 18:00; VIP watch-list check hourly.")


COMMANDS = {
    "auth": cmd_auth,
    "accounts": cmd_accounts,
    "run": cmd_run,
    "vipcheck": cmd_vipcheck,
    "important": cmd_important,
    "install-schedule": cmd_install_schedule,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(1)
    COMMANDS[sys.argv[1]]()
