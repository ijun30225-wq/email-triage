"""Gmail API client: auth, fetching, labeling, and draft creation for one account."""

import base64
import re
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

PROJECT_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = PROJECT_DIR / "credentials.json"
TOKENS_DIR = PROJECT_DIR / "tokens"

# Label name -> (background, text) from Gmail's allowed palette
TRIAGE_LABELS = {
    "Triage/Needs Response": ("#fb4c2f", "#ffffff"),
    "Triage/Important": ("#ffad47", "#ffffff"),
    "Triage/FYI": ("#4a86e8", "#ffffff"),
    "Triage/Promo": ("#999999", "#ffffff"),
    "Triage/Processed": ("#16a766", "#ffffff"),
}


def authorize_new_account() -> str:
    """Run the interactive OAuth flow in a browser; save the token by email."""
    if not CREDENTIALS_FILE.exists():
        raise SystemExit(
            "Missing credentials.json — download the OAuth client file from "
            "Google Cloud Console and place it at " + str(CREDENTIALS_FILE)
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)
    service = build("gmail", "v1", credentials=creds)
    email = service.users().getProfile(userId="me").execute()["emailAddress"]
    TOKENS_DIR.mkdir(exist_ok=True)
    (TOKENS_DIR / f"{email}.json").write_text(creds.to_json())
    return email


def list_accounts() -> list[str]:
    """Accounts are defined by which token files exist."""
    return sorted(p.stem for p in TOKENS_DIR.glob("*.json"))


def get_service(email: str):
    token_file = TOKENS_DIR / f"{email}.json"
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def ensure_labels(service) -> dict[str, str]:
    """Create the Triage/* labels if missing; return name -> label id."""
    existing = {
        lbl["name"]: lbl["id"]
        for lbl in service.users().labels().list(userId="me").execute().get("labels", [])
    }
    ids = {}
    for name, (bg, fg) in TRIAGE_LABELS.items():
        if name in existing:
            ids[name] = existing[name]
            continue
        body = {
            "name": name,
            "color": {"backgroundColor": bg, "textColor": fg},
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        if name == "Triage/Processed":
            body["labelListVisibility"] = "labelHide"
        created = service.users().labels().create(userId="me", body=body).execute()
        ids[name] = created["id"]
    return ids


def _extract_text(payload) -> str:
    """Pull readable text out of a message payload, preferring text/plain."""
    mime = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode(errors="replace")
    for part in payload.get("parts") or []:
        text = _extract_text(part)
        if text:
            return text
    if mime == "text/html" and data:
        html = base64.urlsafe_b64decode(data).decode(errors="replace")
        return re.sub(r"<[^>]+>", " ", html)
    return ""


def fetch_untriaged(service, label_ids: dict[str, str], lookback_days: int, limit: int) -> list[dict]:
    """Inbox messages from the last N days that we haven't processed yet."""
    resp = (
        service.users()
        .messages()
        .list(userId="me", q=f"in:inbox newer_than:{lookback_days}d", maxResults=limit)
        .execute()
    )
    processed_id = label_ids["Triage/Processed"]
    emails = []
    for ref in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        if processed_id in msg.get("labelIds", []):
            continue
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        emails.append(
            {
                "id": msg["id"],
                "thread_id": msg["threadId"],
                "from": headers.get("from", ""),
                "reply_to": headers.get("reply-to", headers.get("from", "")),
                "subject": headers.get("subject", "(no subject)"),
                "date": headers.get("date", ""),
                "message_id_header": headers.get("message-id", ""),
                "snippet": msg.get("snippet", ""),
                "body": _extract_text(msg["payload"])[:1500],
            }
        )
    return emails


def fetch_vip_hits(service, label_ids: dict[str, str], vip_senders: list[str], lookback_days: int) -> list[dict]:
    """Unlabeled inbox mail from VIP senders — cheap metadata-only check, no AI."""
    # Only space-free tokens (domains/addresses) are safe in a Gmail query;
    # multi-word entries are handled by the from-header match in triage.py.
    tokens = [s for s in vip_senders if " " not in s]
    if not tokens:
        return []
    froms = " ".join(f"from:{s}" for s in tokens)
    query = f"in:inbox newer_than:{lookback_days}d {{{froms}}}"
    resp = service.users().messages().list(userId="me", q=query, maxResults=20).execute()
    important_id = label_ids["Triage/Important"]
    hits = []
    for ref in resp.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=ref["id"], format="metadata",
                 metadataHeaders=["From", "Subject"])
            .execute()
        )
        if important_id in msg.get("labelIds", []):
            continue  # already pinged
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        hits.append(
            {
                "id": msg["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", "(no subject)"),
                "snippet": msg.get("snippet", ""),
            }
        )
    return hits


def apply_triage(service, msg_id: str, add_label_ids: list[str], star: bool = False):
    body = {"addLabelIds": add_label_ids + (["STARRED"] if star else []), "removeLabelIds": []}
    service.users().messages().modify(userId="me", id=msg_id, body=body).execute()


def create_reply_draft(service, email_info: dict, draft_text: str):
    msg = EmailMessage()
    msg["To"] = email_info["reply_to"]
    subject = email_info["subject"]
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if email_info["message_id_header"]:
        msg["In-Reply-To"] = email_info["message_id_header"]
        msg["References"] = email_info["message_id_header"]
    msg.set_content(draft_text)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": email_info["thread_id"]}},
    ).execute()
