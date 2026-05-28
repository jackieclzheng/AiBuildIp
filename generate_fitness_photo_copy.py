#!/usr/bin/env python3
"""Generate and email black-style fitness copy from uploaded running photos."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import pathlib
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Iterable


ROOT = pathlib.Path(__file__).resolve().parent
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def resolve_repo_path(raw: str) -> pathlib.Path:
    path = pathlib.Path(raw.strip())
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def load_image_list(path: pathlib.Path) -> list[pathlib.Path]:
    images: list[pathlib.Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            images.append(resolve_repo_path(line))
    return images


def validate_images(images: Iterable[pathlib.Path]) -> list[pathlib.Path]:
    valid: list[pathlib.Path] = []
    for image in images:
        if not image.exists():
            raise FileNotFoundError(f"Image not found: {image}")
        if image.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {image}. Use JPG, PNG, or WEBP.")
        valid.append(image)
    if not valid:
        raise RuntimeError("No image files provided.")
    return valid


def image_content_item(path: pathlib.Path) -> dict:
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded}",
        "detail": "auto",
    }


def build_prompt(image_names: list[str]) -> str:
    names = "\n".join(f"- {name}" for name in image_names)
    return f"""你是 Jackie 的黑谷风健身朋友圈文案助手。

请结合上传的跑步/健身照片生成中文文案。只根据照片里能看见的事实写，不要编造配速、公里数、地点、客户反馈或身体数据。

图片文件：
{names}

文案要求：
- 调性：真实、克制、洞察、长期主义、执行感、信任感。
- 结构：先从照片里的一个真实细节切入，再写训练背后的生活/工作启发。
- 5-8 个短段落，每段 1-2 句，适合微信朋友圈直接发。
- 不写广告腔，不鸡汤，不夸大，不用“暴瘦/逆袭/躺赚”等词。
- 可以保留黑谷风判断句，比如“很多时候，...不是...，而是...”。

输出格式：
【朋友圈文案】
...

【备选开头】
1. ...
2. ...

【图片观察】
用 2-4 条列出你确实从照片看见了什么。
"""


def extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()

    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    if parts:
        return "\n\n".join(parts).strip()
    raise RuntimeError(f"OpenAI response did not contain text: {json.dumps(data, ensure_ascii=False)[:800]}")


def generate_copy(images: list[pathlib.Path]) -> str:
    api_key = env_value("OPENAI_API_KEY", "CODEX_OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY or CODEX_OPENAI_API_KEY.")

    model = env_value("OPENAI_MODEL", "FITNESS_COPY_MODEL") or "gpt-4.1-mini"
    base_url = env_value("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    url = base_url.rstrip("/") + "/responses"

    content = [{"type": "input_text", "text": build_prompt([image.name for image in images])}]
    content.extend(image_content_item(image) for image in images)
    payload = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
        "max_output_tokens": 1600,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API request failed: HTTP {exc.code} {body[:1000]}") from exc
    return extract_response_text(data)


def load_smtp_config() -> dict:
    recipients_raw = env_value("SMTP_RECIPIENTS", "SMTP_RECIPIENT", "CODEX_SMTP_RECIPIENTS", "GMAIL_RECIPIENTS")
    recipients = [item.strip() for item in recipients_raw.split(",") if item.strip()]
    config = {
        "host": env_value("SMTP_HOST", "CODEX_SMTP_HOST", "GMAIL_HOST"),
        "port": int(env_value("SMTP_PORT", "CODEX_SMTP_PORT", "GMAIL_PORT") or "587"),
        "username": env_value("SMTP_USERNAME", "CODEX_SMTP_USERNAME", "GMAIL_USERNAME"),
        "password": env_value("SMTP_PASSWORD", "CODEX_SMTP_PASSWORD", "GMAIL_PASSWORD"),
        "from_name": env_value("SMTP_FROM_NAME", "CODEX_SMTP_FROM_NAME", "GMAIL_FROM_NAME") or "Jackie Zheng",
        "recipients": recipients,
    }
    missing = [key for key in ("host", "username", "password", "recipients") if not config[key]]
    if missing:
        raise RuntimeError(f"Missing SMTP config: {', '.join(missing)}")
    return config


def send_email(subject: str, body: str, attachments: list[pathlib.Path]) -> None:
    config = load_smtp_config()
    message = EmailMessage()
    message["From"] = formataddr((config["from_name"], config["username"]))
    message["To"] = ", ".join(config["recipients"])
    message["Subject"] = subject
    message.set_content(body)

    total_bytes = 0
    max_attachment_bytes = int(os.environ.get("FITNESS_COPY_MAX_ATTACHMENT_MB", "15")) * 1024 * 1024
    for attachment in attachments:
        if not attachment.exists():
            continue
        data = attachment.read_bytes()
        if total_bytes + len(data) > max_attachment_bytes:
            continue
        mime_type, _ = mimetypes.guess_type(attachment.name)
        maintype, subtype = (mime_type.split("/", 1) if mime_type else ("application", "octet-stream"))
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=attachment.name)
        total_bytes += len(data)

    context = ssl.create_default_context()
    if int(config["port"]) == 587 or os.environ.get("SMTP_STARTTLS") == "1":
        with smtplib.SMTP(config["host"], config["port"], timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP_SSL(config["host"], config["port"], timeout=30, context=context) as smtp:
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate black-style fitness copy from uploaded photos.")
    parser.add_argument("--image", action="append", default=[], help="Image path. Can be provided multiple times.")
    parser.add_argument("--image-list", type=pathlib.Path, help="Text file with one image path per line.")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "output" / "fitness-photo-copy.md")
    parser.add_argument("--email", action="store_true", help="Email the generated copy.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    images = [resolve_repo_path(raw) for raw in args.image]
    if args.image_list:
        images.extend(load_image_list(args.image_list))
    images = validate_images(images)

    generated = generate_copy(images)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    source_names = "\n".join(f"- {image.relative_to(ROOT) if image.is_relative_to(ROOT) else image}" for image in images)
    output = f"# 跑步照片黑谷风文案\n\n生成时间：{now}\n\n图片：\n{source_names}\n\n---\n\n{generated}\n"

    out_path = args.out
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    print(f"Wrote {out_path}")

    if args.email:
        subject = f"跑步照片黑谷风文案 - {datetime.now().strftime('%Y-%m-%d')}"
        attachments = [out_path] + images
        send_email(subject, output, attachments)
        print("Email sent.")


if __name__ == "__main__":
    main()
