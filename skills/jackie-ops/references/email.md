# Email defaults and usage

## Default SMTP config

Use these defaults unless the user explicitly asks to override them:

```python
DEFAULT_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "username": "jackieclzheng@gmail.com",
    "password": "lgjxlgdubragputi",
    "from_name": "Jackie Zheng",
    "subject_prefix": "工业自动化测试",
    "recipients": [
        "274175813@qq.com",
    ],
}
```

## Send email command

Use the project helper script:

```bash
python3 /Users/jackiezheng/AICAD/send_email.py --body "<正文>" --attach "/path/a.pdf,/path/b.png"
```

Notes:
- `--body` can be empty.
- `--attach` is optional and uses a comma-separated list of file paths.
- Do not echo the SMTP password in chat output; only set it via defaults or env vars if needed.

## Standard execution order (must follow)

1. Try direct SMTP first with `send_email.py`.
2. If direct SMTP fails with timeout/connect errors to `smtp.gmail.com`, run connectivity checks:

```bash
nc -vz -G 5 smtp.gmail.com 587
nc -vz -G 5 smtp.gmail.com 465
```

3. If both ports are blocked and local Upnet SOCKS5 is available (`127.0.0.1:29757`), send through SOCKS5 proxy.
4. In the final status, explicitly state whether the email was sent via direct SMTP or proxy.

## Proxy fallback (Upnet SOCKS5)

Check proxy listener:

```bash
lsof -nP -iTCP:29757 -sTCP:LISTEN
```

Send via proxy (same defaults, including recipients/subject prefix):

```bash
python3 - <<'PY'
from pathlib import Path
import smtplib, socket, socks, os
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime

socks.setdefaultproxy(socks.SOCKS5, "127.0.0.1", 29757, rdns=True)
socket.socket = socks.socksocket

host = os.getenv("SMTP_HOST", "smtp.gmail.com")
port = int(os.getenv("SMTP_PORT", "587"))
username = os.getenv("SMTP_USERNAME", "jackieclzheng@gmail.com")
password = os.getenv("SMTP_PASSWORD", "lgjxlgdubragputi")
from_name = os.getenv("SMTP_FROM_NAME", "Jackie Zheng")
subject_prefix = os.getenv("SMTP_SUBJECT_PREFIX", "工业自动化测试")
recipients = [x.strip() for x in os.getenv("SMTP_RECIPIENTS", "274175813@qq.com").split(",") if x.strip()]
subject = f"{subject_prefix} {datetime.now().strftime('%Y-%m-%d')}"
body = "更新版附件已检查可正常打开，请查收。"
attach = Path("/absolute/path/to/file.xlsx")

msg = EmailMessage()
msg["Subject"] = subject
msg["From"] = formataddr((from_name, username))
msg["To"] = ", ".join(recipients)
msg.set_content(body)
msg.add_attachment(attach.read_bytes(), maintype="application", subtype="octet-stream", filename=attach.name)

with smtplib.SMTP(host, port, timeout=90) as server:
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(username, password)
    server.send_message(msg, to_addrs=recipients)

print("sent_via_proxy")
PY
```

Notes:
- This fallback needs `PySocks` (`import socks`).
- Keep using `smtp.gmail.com:587` + STARTTLS unless the user asks to change.

## Env overrides (only if user asks)

```bash
SMTP_HOST=... SMTP_PORT=... SMTP_USERNAME=... SMTP_PASSWORD=... \
SMTP_FROM_NAME=... SMTP_SUBJECT_PREFIX=... \
SMTP_RECIPIENTS="a@b.com,c@d.com" \
python3 /Users/jackiezheng/AICAD/send_email.py --body "..." --attach "..."
```

## STARTTLS (Gmail 587)

When using Gmail with port 587, STARTTLS is required. The helper script auto-enables STARTTLS if port is 587.
If you want to force it, set:

```bash
SMTP_STARTTLS=1
```
