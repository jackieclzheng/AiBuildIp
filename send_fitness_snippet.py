#!/usr/bin/env python3
"""
Send a poetic fitness snippet email, rotating sequentially or by explicit index override.
"""
from __future__ import annotations

import argparse
import email.message
import os
import pathlib
import re
import smtplib
import ssl
from typing import List, Tuple

DEFAULT_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "jackieclzheng@gmail.com",
    "password": "lgjxlgdubragputi",
    "from_name": "Jackie Zheng",
    "recipients": ["274175813@qq.com"],
}

ROOT = pathlib.Path(__file__).resolve().parent


def env_value(*candidates: str) -> str:
    for key in candidates:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def resolve_path(env_key: str, default: pathlib.Path) -> pathlib.Path:
    """Resolve a path from env override; accept relative paths from repo root."""
    override = os.environ.get(env_key)
    if override:
        candidate = pathlib.Path(override)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        return candidate
    return default


MARKDOWN_PATH = resolve_path("FITNESS_MARKDOWN_PATH", ROOT / "training_philosophy.md")
STATE_PATH = resolve_path("FITNESS_STATE_PATH", ROOT / ".training_philosophy_state")


def parse_recipients(value: str | None, fallback: List[str]) -> List[str]:
    if value:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if items:
            return items
    return fallback


def load_config() -> dict:
    recipients = parse_recipients(
        env_value("SMTP_RECIPIENTS", "SMTP_RECIPIENT", "CODEX_SMTP_RECIPIENTS", "CODEX_SMTP_RECIPIENT", "GMAIL_RECIPIENTS", "GMAIL_RECIPIENT"),
        DEFAULT_CONFIG["recipients"],
    )
    return {
        "host": env_value("SMTP_HOST", "CODEX_SMTP_HOST", "GMAIL_HOST") or DEFAULT_CONFIG["host"],
        "port": int(env_value("SMTP_PORT", "CODEX_SMTP_PORT", "GMAIL_PORT") or DEFAULT_CONFIG["port"]),
        "username": env_value("SMTP_USERNAME", "CODEX_SMTP_USERNAME", "GMAIL_USERNAME") or DEFAULT_CONFIG["username"],
        "password": env_value("SMTP_PASSWORD", "CODEX_SMTP_PASSWORD", "GMAIL_PASSWORD") or DEFAULT_CONFIG["password"],
        "from_name": env_value("SMTP_FROM_NAME", "CODEX_SMTP_FROM_NAME", "GMAIL_FROM_NAME") or DEFAULT_CONFIG["from_name"],
        "recipients": recipients,
    }


def load_sections(path: pathlib.Path) -> List[Tuple[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Markdown file not found: {path}")

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?P<heading>##\s*[^\n]+)\s*\n(?P<body>.*?)(?=\n##\s*[^\n]+|\Z)",
        re.DOTALL,
    )
    sections: List[Tuple[str, str]] = []
    for match in pattern.finditer(text):
        heading = match.group("heading").strip()
        body = match.group("body").strip()
        if heading and body:
            sections.append((heading, body))
    if not sections:
        raise RuntimeError(f"No sections found in markdown file: {path}")
    return sections


def pick_next_section(sections: List[Tuple[str, str]], state_path: pathlib.Path) -> Tuple[int, Tuple[str, str]]:
    last_index = -1
    if state_path.exists():
        try:
            last_index = int(state_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            last_index = -1
    next_index = (last_index + 1) % len(sections)
    return next_index, sections[next_index]


def build_message(config: dict, subject_suffix: str, heading: str, body: str) -> email.message.EmailMessage:
    message = email.message.EmailMessage()
    message["From"] = f"{config['from_name']} <{config['username']}>"
    message["To"] = ", ".join(config["recipients"])
    message["Subject"] = f"健身文案日更 - {subject_suffix}"
    message.set_content(f"{heading}\n\n{body}")
    return message


def send_email(config: dict, message: email.message.EmailMessage) -> None:
    context = ssl.create_default_context()
    use_starttls = os.environ.get("SMTP_STARTTLS") == "1" or int(config["port"]) == 587
    if use_starttls:
        with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(config["host"], config["port"], context=context, timeout=20) as smtp:
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send poetic fitness snippet email.")
    parser.add_argument(
        "--index",
        type=int,
        help="Override sequential rotation with a 0-based section index.",
    )
    args = parser.parse_args()

    config = load_config()
    sections = load_sections(MARKDOWN_PATH)

    if args.index is not None:
        index = args.index % len(sections)
        heading, body = sections[index]
    else:
        index, (heading, body) = pick_next_section(sections, STATE_PATH)

    subject_suffix = heading.replace("##", "").strip()
    message = build_message(config, subject_suffix, heading, body)
    send_email(config, message)

    if args.index is None:
        STATE_PATH.write_text(str(index), encoding="utf-8")

    print(f"Fitness email sent for {heading}.")


if __name__ == "__main__":
    main()
