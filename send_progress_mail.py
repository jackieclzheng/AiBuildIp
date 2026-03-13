#!/usr/bin/env python3
"""Send periodic progress emails.

Two modes:
- loop (default): every `--interval` seconds, read `--status-file` and send a progress email.
- one-shot: use --final-success or --final-failure to send a single completion email.

Update `DEFAULT_CONFIG` carefully; it contains sensitive credentials provided by the user.
"""

import argparse
import os
import smtplib
import ssl
import time
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path


DEFAULT_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "jackieclzheng@gmail.com",
    "password": "lgjxlgdubragputi",
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


def send_mail(subject: str, body: str, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((cfg["from_name"], cfg["username"]))
    msg["To"] = ", ".join(cfg["recipients"])
    msg["Subject"] = subject

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


def read_status(status_file: Path) -> str:
    if status_file.exists():
        try:
            return status_file.read_text(encoding="utf-8").strip() or "(status file is empty)"
        except Exception as exc:  # noqa: BLE001
            return f"(failed to read status file: {exc})"
    return "(status file not found)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send periodic progress emails")
    parser.add_argument("--interval", type=int, default=600, help="Seconds between progress emails (loop mode)")
    parser.add_argument("--status-file", type=Path, default=Path("progress_status.txt"), help="Path to status file to include in email body")
    parser.add_argument("--max-iters", type=int, default=None, help="Optional maximum number of progress emails before stopping")
    parser.add_argument("--final-success", metavar="MSG", help="Send one success email with this message and exit")
    parser.add_argument("--final-failure", metavar="MSG", help="Send one failure email with this message and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    # One-shot modes
    if args.final_success is not None:
        send_mail(f"{load_config()['subject_prefix']} 完成", args.final_success)
        return
    if args.final_failure is not None:
        send_mail(f"{load_config()['subject_prefix']} 失败告警", args.final_failure)
        return

    # Loop mode
    iterations = 0
    while True:
        status_text = read_status(args.status_file)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"时间: {now}\n状态文件: {args.status_file}\n\n当前进度:\n{status_text}\n"
        send_mail(f"{load_config()['subject_prefix']} 进度更新", body)
        iterations += 1
        if args.max_iters is not None and iterations >= args.max_iters:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
