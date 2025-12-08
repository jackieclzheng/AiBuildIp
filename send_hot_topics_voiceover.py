#!/usr/bin/env python3
"""
Send one or more voiceover entries from hot-topics-voiceover.md via email.

Each run rotates through the entries in the Markdown file, sending a small batch
per email and persisting the next start index to a local state file.
"""
from __future__ import annotations

import argparse
import email.message
import os
import pathlib
import re
import smtplib
import ssl
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

DEFAULT_CONFIG = {
    "host": "smtp.exmail.qq.com",
    "port": 465,
    "username": "jackie@minteche.com",
    "password": "zzgky2KYXtvQsDHV",
    "from_name": "Jackie Zheng",
    "recipient": "274175813@qq.com",
    "subject_prefix": "AI 口播脚本",
    "items_per_run": 1,
}

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "ai-paid-hot-topics" / "hot-topics-voiceover.md"

SOURCE_PATH_STRING = os.environ.get("HOT_TOPICS_SOURCE") or os.environ.get("HOT_TOPICS_MARKDOWN")
if SOURCE_PATH_STRING:
    copy_candidate = pathlib.Path(SOURCE_PATH_STRING)
    COPY_PATH = copy_candidate if copy_candidate.is_absolute() else ROOT / copy_candidate
else:
    COPY_PATH = DEFAULT_SOURCE
STATE_PATH = ROOT / f".hot_topics_voiceover_state_{COPY_PATH.stem}"
INITIAL_START_INDEX = int(os.environ.get("HOT_TOPICS_START_INDEX", "0"))


@dataclass
class VoiceoverEntry:
    title: str
    script: str


def load_config() -> Dict[str, str]:
    return {
        "host": os.environ.get("SMTP_HOST", DEFAULT_CONFIG["host"]),
        "port": int(os.environ.get("SMTP_PORT", DEFAULT_CONFIG["port"])),
        "username": os.environ.get("SMTP_USERNAME", DEFAULT_CONFIG["username"]),
        "password": os.environ.get("SMTP_PASSWORD", DEFAULT_CONFIG["password"]),
        "from_name": os.environ.get("FROM_NAME", DEFAULT_CONFIG["from_name"]),
        "recipient": os.environ.get("SMTP_RECIPIENT", DEFAULT_CONFIG["recipient"]),
        "subject_prefix": os.environ.get("SUBJECT_PREFIX", DEFAULT_CONFIG["subject_prefix"]),
    }


def parse_voiceovers(path: pathlib.Path) -> List[VoiceoverEntry]:
    if not path.exists():
        raise FileNotFoundError(f"Voiceover markdown not found: {path}")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^###\s*\d+\)\s*(?P<title>[^\n]+)\n- 口播脚本：(?P<script>.*?)(?=\n###|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    entries: List[VoiceoverEntry] = []
    for match in pattern.finditer(text):
        title = match.group("title").strip()
        script = match.group("script").strip()
        if title and script:
            entries.append(VoiceoverEntry(title=title, script=script))
    if not entries:
        raise RuntimeError("No voiceover entries parsed from markdown.")
    return entries


def load_state(path: pathlib.Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return INITIAL_START_INDEX


def produce_batch(entries: Sequence[VoiceoverEntry], count: int) -> Tuple[List[VoiceoverEntry], int]:
    total = len(entries)
    count = max(1, min(count, total))
    start = load_state(STATE_PATH) % total
    batch: List[VoiceoverEntry] = []
    for offset in range(count):
        idx = (start + offset) % total
        batch.append(entries[idx])
    next_start = (start + count) % total
    return batch, next_start


def build_message(config: Dict[str, str], batch: Sequence[VoiceoverEntry], subject_prefix: str) -> email.message.EmailMessage:
    subject_titles = "、".join(entry.title for entry in batch)
    body_lines: List[str] = []
    for idx, entry in enumerate(batch, start=1):
        body_lines.append(f"{idx}. {entry.title}")
        body_lines.append("")
        body_lines.append(entry.script)
        body_lines.append("")
    body = "\n".join(body_lines).strip() + "\n"

    message = email.message.EmailMessage()
    message["From"] = f"{config['from_name']} <{config['username']}>"
    message["To"] = config["recipient"]
    message["Subject"] = f"{subject_prefix} - {subject_titles}"
    message.set_content(body)
    return message


def send_email(config: Dict[str, str], message: email.message.EmailMessage) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as smtp:
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send rotating hot-topics voiceover entries.")
    parser.add_argument("--count", type=int, help="Number of voiceover entries per email (default 1).")
    parser.add_argument("--subject-prefix", help="Override email subject prefix.")
    parser.add_argument("--dry-run", action="store_true", help="Print email body without sending.")
    args = parser.parse_args()

    config = load_config()
    entries = parse_voiceovers(COPY_PATH)
    default_count = int(os.environ.get("HOT_TOPICS_ITEMS_PER_RUN", DEFAULT_CONFIG["items_per_run"]))
    batch_count = args.count if args.count is not None else default_count
    batch, next_state = produce_batch(entries, batch_count)
    subject_prefix = args.subject_prefix or config["subject_prefix"]

    message = build_message(config, batch, subject_prefix)
    if args.dry_run:
        print("=== DRY RUN ===")
        print(message.get_content())
    else:
        send_email(config, message)
        STATE_PATH.write_text(str(next_state), encoding="utf-8")
        print(f"Voiceover email sent for：{', '.join(entry.title for entry in batch)}.")


if __name__ == "__main__":
    main()
