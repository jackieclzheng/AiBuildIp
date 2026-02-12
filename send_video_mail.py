#!/usr/bin/env python3
"""
Send a generated video to the target mailbox.

Usage:
  python3 send_video_mail.py --file outputs/output_vrt.mp4 \
    --subject "AI 付费口播稿 完成" \
    --body "本次生成的视频已附加。"
"""

import argparse
import os
import mimetypes
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

DEFAULT_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "jackieclzheng@gmail.com",
    "password": "dboqsjeqkovbqbvv",
    "from_name": "Jackie Zheng",
    "recipients": ["274175813@qq.com"],
    "subject_prefix": "AI 付费口播稿",
}


def parse_recipients(value: str | None, fallback: list[str]) -> list[str]:
    if value:
        items = [item.strip() for item in value.split(",") if item.strip()]
        if items:
            return items
    return fallback


def load_config() -> dict:
    recipients = parse_recipients(
        os.environ.get("SMTP_RECIPIENTS") or os.environ.get("SMTP_RECIPIENT"),
        DEFAULT_CONFIG["recipients"],
    )
    return {
        "host": os.environ.get("SMTP_HOST", DEFAULT_CONFIG["host"]),
        "port": int(os.environ.get("SMTP_PORT", DEFAULT_CONFIG["port"])),
        "username": os.environ.get("SMTP_USERNAME", DEFAULT_CONFIG["username"]),
        "password": os.environ.get("SMTP_PASSWORD", DEFAULT_CONFIG["password"]),
        "from_name": os.environ.get("SMTP_FROM_NAME")
        or os.environ.get("FROM_NAME", DEFAULT_CONFIG["from_name"]),
        "recipients": recipients,
        "subject_prefix": os.environ.get("SMTP_SUBJECT_PREFIX")
        or os.environ.get("SUBJECT_PREFIX", DEFAULT_CONFIG["subject_prefix"]),
    }


def send_video(file_path: Path, subject: str, body: str, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    if not file_path.exists():
        raise FileNotFoundError(f"file not found: {file_path}")

    msg = MIMEMultipart()
    msg["From"] = formataddr((cfg["from_name"], cfg["username"]))
    msg["To"] = ", ".join(cfg["recipients"])
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain", "utf-8"))

    mime_type, _ = mimetypes.guess_type(file_path.name)
    maintype, subtype = (mime_type.split("/", 1) if mime_type else ("application", "octet-stream"))

    with file_path.open("rb") as f:
        part = MIMEApplication(f.read(), _subtype=subtype)
        part.add_header("Content-Disposition", "attachment", filename=file_path.name)
        msg.attach(part)

    context = ssl.create_default_context()
    use_starttls = os.environ.get("SMTP_STARTTLS") == "1" or int(cfg["port"]) == 587
    if use_starttls:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["username"], cfg["recipients"], msg.as_string())
    else:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context) as server:
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["username"], cfg["recipients"], msg.as_string())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send generated video via email.")
    parser.add_argument("--file", required=True, type=Path, help="Path to video file to send.")
    parser.add_argument("--subject", default=None, help="Email subject. Defaults to prefix + filename.")
    parser.add_argument("--body", default="本次生成的视频已附加。", help="Email body text.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    subject = args.subject or f"{load_config()['subject_prefix']} - {args.file.name}"
    send_video(args.file, subject, args.body)


if __name__ == "__main__":
    main()
