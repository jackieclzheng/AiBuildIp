#!/usr/bin/env python3
"""
Send daily copywriting combos (朋友圈 + 小红书) via email.

Reads `project-copywriting-1101V3.5.md`, rotates through the entries, and
each run sends两个项目（即两条朋友圈文案 + 两条小红书文案）。
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
from typing import Dict, List, Sequence

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


def resolve_path(env_key: str, default: pathlib.Path) -> pathlib.Path:
    """Resolve a path from env override; support relative paths from repo root."""
    override = os.environ.get(env_key)
    if override:
        candidate = pathlib.Path(override)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate
    return default


PROJECT_COPY_PATH = resolve_path(
    "COPYWRITING_MARKDOWN_PATH", ROOT / "project-copywriting-2025-12-11.md"
)
STATE_PATH = resolve_path(
    "COPYWRITING_STATE_PATH", ROOT / ".copywriting_digest_state_v2"
)
ITEMS_PER_RUN = int(os.environ.get("COPYWRITING_ITEMS_PER_RUN", 2))


@dataclass
class CopywritingEntry:
    title: str
    pyq: str
    xhs: str


def load_config() -> Dict[str, str]:
    """Load SMTP configuration from environment variables with sensible defaults."""
    return {
        "host": os.environ.get("SMTP_HOST", DEFAULT_CONFIG["host"]),
        "port": int(os.environ.get("SMTP_PORT", DEFAULT_CONFIG["port"])),
        "username": os.environ.get("SMTP_USERNAME", DEFAULT_CONFIG["username"]),
        "password": os.environ.get("SMTP_PASSWORD", DEFAULT_CONFIG["password"]),
        "from_name": os.environ.get("FROM_NAME", DEFAULT_CONFIG["from_name"]),
        "recipient": os.environ.get("SMTP_RECIPIENT", DEFAULT_CONFIG["recipient"]),
        "subject_prefix": os.environ.get(
            "SUBJECT_PREFIX", DEFAULT_CONFIG["subject_prefix"]
        ),
    }


def load_entries(path: pathlib.Path) -> List[CopywritingEntry]:
    """Parse project copywriting file and return structured entries."""
    if not path.exists():
        raise FileNotFoundError(f"Copywriting file not found: {path}")

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"##\s*\d+\.\s*(?P<title>[^\n]+)\s*\n+"
        r"\*\*朋友圈文案\*\*\s*\n(?P<pyq>.*?)"
        r"\n\*\*小红书文案\*\*\s*\n(?P<xhs>.*?)(?=\n##|\Z)",
        re.DOTALL,
    )

    entries: List[CopywritingEntry] = []
    for match in pattern.finditer(text):
        title = match.group("title").strip()
        pyq = match.group("pyq").strip()
        xhs = match.group("xhs").strip()
        if title and pyq and xhs:
            entries.append(CopywritingEntry(title=title, pyq=pyq, xhs=xhs))

    if not entries:
        raise RuntimeError("No copywriting entries found in project file.")
    return entries


def load_state(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return 0


def save_state(path: pathlib.Path, value: int) -> None:
    path.write_text(str(value), encoding="utf-8")


def pick_entries(
    entries: Sequence[CopywritingEntry], count: int
) -> tuple[List[CopywritingEntry], int]:
    """Rotate through entries and return (`count` items, next_start_index)."""
    count = max(1, min(count, len(entries)))
    start_index = load_state(STATE_PATH) % len(entries)
    selected: List[CopywritingEntry] = []
    for offset in range(count):
        idx = (start_index + offset) % len(entries)
        selected.append(entries[idx])
    next_start = (start_index + count) % len(entries)
    return selected, next_start


def build_message(
    config: Dict[str, str],
    items: Sequence[CopywritingEntry],
    subject_prefix: str,
) -> email.message.EmailMessage:
    """Create the email message object."""
    subject_titles = "、".join(entry.title for entry in items)
    body_lines: List[str] = [
        f"今日推送 {len(items)} 组文案：",
        "",
    ]

    for entry in items:
        body_lines.append(f"## {entry.title}")
        body_lines.append("")
        body_lines.append("【朋友圈】")
        body_lines.append(entry.pyq.strip())
        body_lines.append("")
        body_lines.append("【小红书】")
        body_lines.append(entry.xhs.strip())
        body_lines.append("")

    body_text = "\n".join(body_lines).strip() + "\n"

    message = email.message.EmailMessage()
    message["From"] = f"{config['from_name']} <{config['username']}>"
    message["To"] = config["recipient"]
    message["Subject"] = f"{subject_prefix} - {subject_titles}"
    message.set_content(body_text)
    return message


def send_email(config: Dict[str, str], message: email.message.EmailMessage) -> None:
    """Send the email via SMTP over SSL."""
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as smtp:
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send rotating copywriting combos.")
    parser.add_argument("--count", type=int, help="Number of项目组合 to发送（默认2）.")
    parser.add_argument("--subject-prefix", help="Override default subject prefix.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印邮件内容，不真正发送（用于本地调试）。",
    )
    args = parser.parse_args()

    config = load_config()
    entries = load_entries(PROJECT_COPY_PATH)
    count = args.count if args.count is not None else ITEMS_PER_RUN
    selected, next_start = pick_entries(entries, count)
    subject_prefix = args.subject_prefix or config["subject_prefix"]

    message = build_message(config, selected, subject_prefix)
    if args.dry_run:
        print("=== DRY RUN: email body ===")
        print(message.get_content())
        return

    send_email(config, message)
    save_state(STATE_PATH, next_start)
    print(f"Copywriting email sent for：{', '.join(entry.title for entry in selected)}.")


if __name__ == "__main__":
    main()
