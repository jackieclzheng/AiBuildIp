#!/usr/bin/env python3
"""
Daily copywriting generator.

Reads the template for a specific date, appends a markdown section with 10 items
to pyq-copywriting.md, and optionally emails the content via SMTP.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from email.message import EmailMessage
from pathlib import Path
import smtplib
import ssl
from typing import Any, Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append daily copywriting content to pyq-copywriting.md."
    )
    parser.add_argument(
        "--date",
        help="Date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--templates-dir",
        default="templates",
        help="Directory that stores JSON templates keyed by date.",
    )
    parser.add_argument(
        "--output",
        default="pyq-copywriting.md",
        help="Markdown file to append the generated content to.",
    )
    parser.add_argument(
        "--email-config",
        default="email_config.json",
        help="Optional SMTP JSON config used to send the generated copy via email.",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Skip sending email even if configuration is present.",
    )
    return parser.parse_args()


def resolve_date(date_str: Optional[str]) -> dt.date:
    if date_str:
        try:
            return dt.datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(f"Invalid --date value '{date_str}': {exc}") from exc
    return dt.date.today()


def load_template(template_dir: Path, target_date: dt.date) -> Dict[str, Any]:
    template_path = template_dir / f"{target_date.isoformat()}.json"
    if not template_path.exists():
        raise SystemExit(
            f"Template not found: {template_path}. "
            "Create it with an 'entries' array (10 items)."
        )
    try:
        with template_path.open(encoding="utf-8") as fh:
            template = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Template JSON error in {template_path}: {exc}") from exc

    entries = template.get("entries")
    if not isinstance(entries, list) or len(entries) != 10:
        raise SystemExit(
            f"Template {template_path} must contain an 'entries' list with 10 items."
        )
    if any(not isinstance(item, str) or not item.strip() for item in entries):
        raise SystemExit(
            f"Template {template_path} contains empty or non-string entries."
        )
    return template


def section_exists(output_path: Path, header: str) -> bool:
    if not output_path.exists():
        return False
    existing = output_path.read_text(encoding="utf-8")
    return header in existing


def append_markdown(output_path: Path, header: str, entries: List[str]) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    lines = [header, ""]
    lines.extend(f"{index}. {entry}" for index, entry in enumerate(entries, start=1))
    lines.append("")
    block = "\n".join(lines)

    with output_path.open("a", encoding="utf-8") as fh:
        if existing:
            if existing.endswith("\n\n"):
                separator = ""
            elif existing.endswith("\n"):
                separator = "\n"
            else:
                separator = "\n\n"
            fh.write(separator)
        fh.write(block)
        if not block.endswith("\n"):
            fh.write("\n")
    return block


def load_email_config(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            config = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Email config JSON error in {path}: {exc}") from exc
    required_fields = ["smtp_server", "from_addr", "to_addrs"]
    for field in required_fields:
        if field not in config:
            raise SystemExit(f"Email config {path} missing required field '{field}'.")
    to_addrs = config["to_addrs"]
    if isinstance(to_addrs, str):
        config["to_addrs"] = [addr.strip() for addr in to_addrs.split(",") if addr]
    if not config["to_addrs"]:
        raise SystemExit(f"Email config {path} must specify at least one recipient.")
    return config


def send_email(
    config: Dict[str, Any],
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["from_addr"]
    message["To"] = ", ".join(config["to_addrs"])
    message.set_content(body)

    smtp_server = config["smtp_server"]
    smtp_port = int(config.get("smtp_port", 587))
    username = config.get("username") or config.get("from_addr")
    password = config.get("password")

    if not password:
        raise SystemExit(
            "Email config is missing 'password'. Use an app password/token."
        )

    use_ssl = bool(config.get("use_ssl", False))
    use_tls = bool(config.get("use_tls", not use_ssl))

    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
            if username:
                server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)
            if username:
                server.login(username, password)
            server.send_message(message)


def main() -> None:
    args = parse_args()
    target_date = resolve_date(args.date)
    header = f"# {target_date.isoformat()}"

    templates_dir = Path(args.templates_dir)
    template = load_template(templates_dir, target_date)
    entries = [entry.strip() for entry in template["entries"]]

    output_path = Path(args.output)
    if section_exists(output_path, header):
        print(f"[skip] Section '{header}' already exists in {output_path}.")
        return

    block = append_markdown(output_path, header, entries)
    print(f"[ok] Appended section for {target_date.isoformat()} to {output_path}.")

    if args.skip_email:
        print("[info] Email sending skipped by flag.")
        return

    email_config_path = Path(args.email_config)
    config = load_email_config(email_config_path)
    if not config:
        print(f"[info] Email config {email_config_path} not found; skipping email.")
        return

    subject = template.get(
        "email_subject", f"{target_date.isoformat()} 朋友圈文案"
    )
    intro = template.get("email_intro")
    body_sections = [header]
    if intro:
        body_sections.extend([intro.strip(), ""])
    body_sections.append(block)
    email_body = "\n".join(body_sections)

    send_email(config, subject, email_body)
    print("[ok] Email sent.")


if __name__ == "__main__":
    main()
