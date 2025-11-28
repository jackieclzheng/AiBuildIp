#!/usr/bin/env python3
"""
Daily digest sender for hot-topic ideas.

Supports the original Markdown copywriting source, the legacy
`AI_Knowledge_Paid_Courses_Chinese.csv` list, and the newer
`爆款短视频选题_100.csv` rotation with平台/标题/推荐理由/关键词字段，或 `pyq-hot-topics-rotation.md` 的朋友圈/小红书文案格式。
"""
from __future__ import annotations

import argparse
import csv
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
    "subject_prefix": "爆款选题播报",
    "items_per_run": 3,
}

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_TOPIC_FILE = "pyq-hot-topics-rotation.md"
SOURCE_PATH_STRING = os.environ.get("HOT_TOPICS_SOURCE") or os.environ.get("HOT_TOPICS_MARKDOWN")
if SOURCE_PATH_STRING:
    copy_candidate = pathlib.Path(SOURCE_PATH_STRING)
    if not copy_candidate.is_absolute():
        COPY_PATH = ROOT / copy_candidate
    else:
        COPY_PATH = copy_candidate
else:
    COPY_PATH = ROOT / DEFAULT_TOPIC_FILE
STATE_PATH = ROOT / f".hot_topics_digest_state_{COPY_PATH.stem}"
INITIAL_START_INDEX = int(os.environ.get("HOT_TOPICS_START_INDEX", "0"))


@dataclass
class TopicEntry:
    title: str
    pyq: str | None = None
    xhs: str | None = None
    platform: str | None = None
    reason: str | None = None
    keywords: str | None = None


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


def parse_markdown(path: pathlib.Path) -> List[TopicEntry]:
    if not path.exists():
        raise FileNotFoundError(f"Topic copywriting file not found: {path}")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"##\s*\d+\.?\s*(?P<title>[^\n]+)\s*\n+"
        r"\*\*朋友圈文案\*\*.*?\n(?P<pyq>.*?)(?=\n\*\*小红书文案\*\*)"
        r"\n\*\*小红书文案\*\*.*?\n(?P<xhs>.*?)(?=\n##|\Z)",
        re.DOTALL,
    )
    entries: List[TopicEntry] = []
    for match in pattern.finditer(text):
        title = match.group("title").strip()
        pyq = match.group("pyq").strip()
        xhs = match.group("xhs").strip()
        if title and pyq and xhs:
            entries.append(TopicEntry(title=title, pyq=pyq, xhs=xhs))
    if not entries:
        raise RuntimeError("No entries parsed from topic markdown.")
    return entries


def parse_csv(path: pathlib.Path) -> List[TopicEntry]:
    if not path.exists():
        raise FileNotFoundError(f"Topic CSV file not found: {path}")
    entries: List[TopicEntry] = []
    rows: List[List[str]] = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for row in reader:
            normalized = [col.strip().lstrip("\ufeff") for col in row]
            if not any(normalized):
                continue
            rows.append(normalized)
    if not rows:
        raise RuntimeError(f"No topic titles parsed from CSV: {path}")

    header = rows[0]
    header_set = set(header)
    has_detailed_columns = {"视频标题", "推荐理由"} <= header_set

    if has_detailed_columns:
        idx_title = header.index("视频标题")
        idx_platform = header.index("平台") if "平台" in header_set else None
        idx_reason = header.index("推荐理由") if "推荐理由" in header_set else None
        idx_keywords = header.index("关键词") if "关键词" in header_set else None
        for row in rows[1:]:
            if idx_title >= len(row):
                continue
            title = row[idx_title].strip()
            if not title or title == "视频标题":
                continue
            platform = row[idx_platform].strip() if idx_platform is not None and idx_platform < len(row) else ""
            reason = row[idx_reason].strip() if idx_reason is not None and idx_reason < len(row) else ""
            keywords = row[idx_keywords].strip() if idx_keywords is not None and idx_keywords < len(row) else ""
            entries.append(
                TopicEntry(
                    title=title,
                    platform=platform or None,
                    reason=reason or None,
                    keywords=keywords or None,
                )
            )
    else:
        start_idx = 1 if header and header[0] in {"AI课程选题", "平台"} else 0
        for row in rows[start_idx:]:
            title = row[0].strip() if row else ""
            if not title:
                continue
            entries.append(TopicEntry(title=title))
    if not entries:
        raise RuntimeError(f"No topic titles parsed from CSV: {path}")
    return entries


def load_entries(path: pathlib.Path) -> List[TopicEntry]:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return parse_markdown(path)
    if suffix == ".csv":
        return parse_csv(path)
    raise ValueError(f"Unsupported topic file type: {path}")


def load_state(path: pathlib.Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return INITIAL_START_INDEX


def produce_batch(entries: Sequence[TopicEntry], count: int) -> Tuple[List[TopicEntry], int]:
    total = len(entries)
    count = max(1, min(count, total))
    start = load_state(STATE_PATH) % total
    batch: List[TopicEntry] = []
    for offset in range(count):
        idx = (start + offset) % total
        batch.append(entries[idx])
    next_start = (start + count) % total
    return batch, next_start


def build_message(config: Dict[str, str], batch: Sequence[TopicEntry], subject_prefix: str) -> email.message.EmailMessage:
    subject_titles = "、".join(entry.title for entry in batch)
    has_copywriting = any((entry.pyq or entry.xhs) for entry in batch)
    body_lines: List[str] = [
        f"今日爆款选题（共 {len(batch)} 组）：",
        "",
    ]
    if not has_copywriting:
        for idx, entry in enumerate(batch, start=1):
            platform_prefix = f"[{entry.platform}] " if entry.platform else ""
            body_lines.append(f"{idx}. {platform_prefix}{entry.title}")
            if entry.reason:
                body_lines.append(f"推荐理由：{entry.reason}")
            if entry.keywords:
                body_lines.append(f"关键词：{entry.keywords}")
            body_lines.append("")
    else:
        for entry in batch:
            body_lines.append(f"## {entry.title}")
            body_lines.append("")
            if entry.platform:
                body_lines.append(f"【平台】{entry.platform}")
                body_lines.append("")
            if entry.reason:
                body_lines.append("【推荐理由】")
                body_lines.append(entry.reason)
                body_lines.append("")
            if entry.keywords:
                body_lines.append(f"【关键词】{entry.keywords}")
                body_lines.append("")
            if entry.pyq:
                body_lines.append("【朋友圈】")
                body_lines.append(entry.pyq)
                body_lines.append("")
            if entry.xhs:
                body_lines.append("【小红书】")
                body_lines.append(entry.xhs)
                body_lines.append("")
            if not entry.pyq and not entry.xhs and not (entry.reason or entry.platform or entry.keywords):
                body_lines.append("（本条仅包含标题，请根据需求扩展文案）")
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
    parser = argparse.ArgumentParser(description="Send rotating hot-topic copywriting digest.")
    parser.add_argument("--count", type=int, help="Number of topic entries per email (default 3).")
    parser.add_argument("--subject-prefix", help="Override email subject prefix.")
    parser.add_argument("--dry-run", action="store_true", help="Print email body without sending.")
    args = parser.parse_args()

    config = load_config()
    entries = load_entries(COPY_PATH)
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
        print(f"Hot-topic email sent for：{', '.join(entry.title for entry in batch)}.")


if __name__ == "__main__":
    main()
