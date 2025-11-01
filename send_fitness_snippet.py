#!/usr/bin/env python3
"""
Send a poetic fitness snippet email using sequential rotation through fitness-poetic.md.
"""
from __future__ import annotations

import email.message
import pathlib
import re
import smtplib
import ssl
from typing import List, Tuple

CONFIG = {
    "host": "smtp.exmail.qq.com",
    "port": 465,
    "username": "jackie@minteche.com",
    "password": "zzgky2KYXtvQsDHV",
    "from_name": "Jackie Zheng",
    "recipient": "274175813@qq.com",
}

ROOT = pathlib.Path(__file__).resolve().parent
MARKDOWN_PATH = ROOT / "fitness-poetic.md"
STATE_PATH = ROOT / ".fitness_snippet_state"


def load_sections(path: pathlib.Path) -> List[Tuple[str, str]]:
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
        raise RuntimeError("No sections found in fitness-poetic.md.")
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


def build_message(subject_suffix: str, heading: str, body: str) -> email.message.EmailMessage:
    message = email.message.EmailMessage()
    message["From"] = f"{CONFIG['from_name']} <{CONFIG['username']}>"
    message["To"] = CONFIG["recipient"]
    message["Subject"] = f"健身文案日更 - {subject_suffix}"
    message.set_content(f"{heading}\n\n{body}")
    return message


def send_email(message: email.message.EmailMessage) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(CONFIG["host"], CONFIG["port"], context=context, timeout=20) as smtp:
        smtp.login(CONFIG["username"], CONFIG["password"])
        smtp.send_message(message)


def main() -> None:
    sections = load_sections(MARKDOWN_PATH)
    next_index, (heading, body) = pick_next_section(sections, STATE_PATH)
    subject_suffix = heading.replace("##", "").strip()
    message = build_message(subject_suffix, heading, body)
    send_email(message)
    STATE_PATH.write_text(str(next_index), encoding="utf-8")
    print(f"Fitness email sent for {heading}.")


if __name__ == "__main__":
    main()
