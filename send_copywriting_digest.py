#!/usr/bin/env python3
"""
Send the most recent PyQ copywriting entry via email.

Reads `pyq-copywriting.md`, grabs the latest `# YYYY-MM-DD` section (or a date
provided via --date), and emails it using the same SMTP credentials as the
other automation scripts.
"""
from __future__ import annotations

import argparse
import email.message
import os
import pathlib
import re
import smtplib
import ssl
from typing import Dict, List, Tuple

DEFAULT_CONFIG = {
    "host": "smtp.exmail.qq.com",
    "port": 465,
    "username": "jackie@minteche.com",
    "password": "zzgky2KYXtvQsDHV",
    "from_name": "Jackie Zheng",
    "recipient": "274175813@qq.com",
    "subject_prefix": "PyQ文案播报",
}

ROOT = pathlib.Path(__file__).resolve().parent
COPYWRITING_PATH = ROOT / "pyq-copywriting.md"


def load_config() -> Dict[str, str]:
    """Load SMTP configuration from environment variables with sensible defaults."""
    return {
        "host": os.environ.get("SMTP_HOST", DEFAULT_CONFIG["host"]),
        "port": int(os.environ.get("SMTP_PORT", DEFAULT_CONFIG["port"])),
        "username": os.environ.get("SMTP_USERNAME", DEFAULT_CONFIG["username"]),
        "password": os.environ.get("SMTP_PASSWORD", DEFAULT_CONFIG["password"]),
        "from_name": os.environ.get("FROM_NAME", DEFAULT_CONFIG["from_name"]),
        "recipient": os.environ.get("SMTP_RECIPIENT", DEFAULT_CONFIG["recipient"]),
        "subject_prefix": os.environ.get("SUBJECT_PREFIX", DEFAULT_CONFIG["subject_prefix"]),
    }


def load_entries(path: pathlib.Path) -> List[Tuple[str, str]]:
    """Parse the markdown file and return a list of (date, body) tuples."""
    if not path.exists():
        raise FileNotFoundError(f"Copywriting file not found: {path}")

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^#\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        raise RuntimeError("No dated sections found in pyq-copywriting.md")

    entries: List[Tuple[str, str]] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            entries.append((match.group(1), body))
    if not entries:
        raise RuntimeError("pyq-copywriting.md sections are empty.")
    return entries


def select_entry(entries: List[Tuple[str, str]], target_date: str | None) -> Tuple[str, str]:
    """Return the entry matching target_date or the most recent entry."""
    if target_date:
        for date, body in entries:
            if date == target_date:
                return date, body
        raise ValueError(f"Date {target_date} not found in pyq-copywriting.md")
    return entries[-1]


def build_message(config: Dict[str, str], date: str, body: str, subject_prefix: str) -> email.message.EmailMessage:
    """Create the email message object."""
    message = email.message.EmailMessage()
    message["From"] = f"{config['from_name']} <{config['username']}>"
    message["To"] = config["recipient"]
    message["Subject"] = f"{subject_prefix} - {date}"
    message.set_content(f"# {date}\n\n{body}")
    return message


def send_email(config: Dict[str, str], message: email.message.EmailMessage) -> None:
    """Send the email via SMTP over SSL."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as smtp:
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the latest PyQ copywriting email.")
    parser.add_argument("--date", help="Explicit date (YYYY-MM-DD) to send. Defaults to the latest entry.")
    parser.add_argument("--subject-prefix", help="Override the default subject prefix.")
    args = parser.parse_args()

    config = load_config()
    entries = load_entries(COPYWRITING_PATH)
    date, body = select_entry(entries, args.date)
    subject_prefix = args.subject_prefix or config["subject_prefix"]

    message = build_message(config, date, body, subject_prefix)
    send_email(config, message)
    print(f"Copywriting email sent for {date}.")


if __name__ == "__main__":
    main()
