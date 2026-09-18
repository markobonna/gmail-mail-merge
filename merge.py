#!/usr/bin/env python3
"""
Personal Gmail mail merge — runs on your machine, sends as you.

Default mode is dry-run (prints what would be sent, sends nothing).
OAuth scope is gmail.send only.

Setup: see README.md
"""

from __future__ import annotations

import argparse
import base64
import csv
import sys
import time
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Send-only. No Drive, no Sheets, no inbox read.
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

ROOT = Path(__file__).resolve().parent
DEFAULT_CREDENTIALS = ROOT / "credentials.json"
DEFAULT_TOKEN = ROOT / "token.json"
DEFAULT_CSV = ROOT / "recipients.csv"
DEFAULT_TEMPLATE = ROOT / "template.txt"
DEFAULT_LOG = ROOT / "sent_log.csv"


def load_template(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    subject = ""
    body_lines: list[str] = []
    lines = text.splitlines()
    i = 0
    if lines and lines[0].upper().startswith("SUBJECT:"):
        subject = lines[0].split(":", 1)[1].strip()
        i = 1
        if i < len(lines) and lines[i].strip() == "":
            i += 1
    body_lines = lines[i:]
    body = "\n".join(body_lines).strip() + "\n"
    if not subject:
        raise SystemExit(f"template missing SUBJECT: line at top of {path}")
    return subject, body


def load_recipients(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"empty CSV: {path}")
        fields = {h.strip(): h for h in reader.fieldnames if h}
        # Accept common header variants
        first_key = None
        email_key = None
        for name, raw in fields.items():
            n = name.lower().replace("_", " ")
            if n in ("first name", "firstname", "first"):
                first_key = raw
            if n == "email":
                email_key = raw
        if not email_key:
            raise SystemExit(
                f"CSV must have an Email column. Found: {list(reader.fieldnames)}"
            )
        if not first_key:
            raise SystemExit(
                f"CSV must have a First Name column. Found: {list(reader.fieldnames)}"
            )
        rows = []
        for row in reader:
            email = (row.get(email_key) or "").strip()
            first = (row.get(first_key) or "").strip() or "there"
            if not email or "@" not in email:
                continue
            rows.append({"First Name": first, "Email": email})
        return rows


def already_sent(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    sent: set[str] = set()
    with log_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            e = (row.get("Email") or "").strip().lower()
            if e:
                sent.add(e)
    return sent


def append_log(log_path: Path, email: str, first: str, status: str, detail: str = "") -> None:
    new_file = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Email", "First Name", "status", "detail", "ts"])
        if new_file:
            w.writeheader()
        w.writerow(
            {
                "Email": email,
                "First Name": first,
                "status": status,
                "detail": detail,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )


def render(template: str, row: dict[str, str]) -> str:
    out = template
    for key, value in row.items():
        out = out.replace("{" + key + "}", value)
        # also allow {{First Name}} style if someone pastes YAMM markers
        out = out.replace("{{" + key + "}}", value)
    return out


def get_gmail_service(credentials_path: Path, token_path: Path):
    if not credentials_path.exists():
        raise SystemExit(
            f"Missing {credentials_path.name}. Download OAuth Desktop client JSON "
            f"from Google Cloud and save it as {credentials_path}."
        )
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def build_raw_message(to_email: str, subject: str, body: str, from_email: str | None) -> str:
    msg = EmailMessage()
    msg["To"] = to_email
    msg["Subject"] = subject
    if from_email:
        msg["From"] = from_email
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Personal Gmail mail merge (dry-run by default)")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Recipients CSV")
    p.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="Email template")
    p.add_argument("--credentials", type=Path, default=DEFAULT_CREDENTIALS)
    p.add_argument("--token", type=Path, default=DEFAULT_TOKEN)
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument(
        "--from",
        dest="from_email",
        default=None,
        help="Optional From address (defaults to authenticated account)",
    )
    p.add_argument(
        "--test-to",
        default=None,
        help="Redirect every message to this address (pair with --limit 1)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process first N recipients",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between real sends (default 2)",
    )
    p.add_argument(
        "--send",
        action="store_true",
        help="Actually send. Without this flag, dry-run only.",
    )
    p.add_argument(
        "--skip-sent",
        action="store_true",
        default=True,
        help="Skip emails already in sent_log.csv (default on)",
    )
    p.add_argument(
        "--no-skip-sent",
        action="store_false",
        dest="skip_sent",
        help="Do not skip emails already logged as sent",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    subject_tmpl, body_tmpl = load_template(args.template)
    recipients = load_recipients(args.csv)
    if args.limit is not None:
        recipients = recipients[: args.limit]

    sent = already_sent(args.log) if args.skip_sent else set()
    to_process = []
    for row in recipients:
        if row["Email"].lower() in sent:
            continue
        to_process.append(row)

    mode = "SEND" if args.send else "DRY-RUN"
    print(f"Mode: {mode}")
    print(f"Recipients in CSV (after limit): {len(recipients)}")
    print(f"Already sent (skipped): {len(recipients) - len(to_process)}")
    print(f"Will process: {len(to_process)}")
    if args.test_to:
        print(f"Test redirect: all mail To → {args.test_to}")
    print()

    service = None
    if args.send:
        service = get_gmail_service(args.credentials, args.token)

    # If --test-to without --send, still show one personalized preview using first row
    if args.test_to and not args.send and to_process:
        row = to_process[0]
        subject = render(subject_tmpl, row)
        body = render(body_tmpl, row)
        print("--- PREVIEW (first recipient name, test To) ---")
        print(f"To: {args.test_to}")
        print(f"Subject: {subject}")
        print(body)
        print("--- end preview ---")
        return 0

    for idx, row in enumerate(to_process, start=1):
        subject = render(subject_tmpl, row)
        body = render(body_tmpl, row)
        to_email = args.test_to or row["Email"]

        print(f"[{idx}/{len(to_process)}] {row['First Name']} <{row['Email']}>")
        if args.test_to:
            print(f"    redirect To: {to_email}")
        print(f"    Subject: {subject}")

        if not args.send:
            if idx == 1:
                print("    --- body preview ---")
                print(textwrap_indent(body))
                print("    --- end body ---")
            continue

        assert service is not None
        raw = build_raw_message(to_email, subject, body, args.from_email)
        try:
            result = (
                service.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )
            mid = result.get("id", "")
            # Don't log test redirects — the real recipient never got it.
            if not args.test_to:
                append_log(args.log, row["Email"], row["First Name"], "sent", mid)
            print(f"    sent id={mid}")
        except HttpError as e:
            if not args.test_to:
                append_log(args.log, row["Email"], row["First Name"], "error", str(e))
            print(f"    ERROR: {e}", file=sys.stderr)
        if idx < len(to_process) and args.delay > 0:
            time.sleep(args.delay)

    if not args.send:
        print()
        print("Dry-run only. To send for real:")
        print("  python merge.py --send")
        print("Safer first:")
        print("  python merge.py --send --test-to you@example.com --limit 1")
    return 0


def textwrap_indent(s: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line if line else prefix.rstrip() for line in s.splitlines())


if __name__ == "__main__":
    raise SystemExit(main())
