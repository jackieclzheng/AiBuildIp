#!/usr/bin/env python3
"""Watch Colab background VRT regen and notify by email on completion."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, "/Users/jackiezheng/AIBuildIP/GPTSoVIS")
from colab.direct_colab_deploy import ColabRunner  # noqa: E402


DEFAULT_BASE_URL = "http://127.0.0.1:18791"
DEFAULT_TARGET_ID = "114C8B4C06B83724166D689104B3F44E"
DEFAULT_RUN_ROOT = pathlib.Path("/Users/jackiezheng/AIBuildIP/GPTSoVIS/colab/.browser_runs")
DEFAULT_LOG_FILE = pathlib.Path("/Users/jackiezheng/AIBuildIP/GPTSoVIS/colab/watch_colab_bg_and_notify.log")
DONE_FLAG = pathlib.Path("/Users/jackiezheng/AIBuildIP/GPTSoVIS/colab/.notify_state/colab_step4_done.flag")
MAIL_SCRIPT = "/Users/jackiezheng/AICAD/send_email.py"


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_log(log_file: pathlib.Path, msg: str) -> None:
    line = f"[{now()}] {msg}"
    print(line, flush=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def send_email_direct(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", MAIL_SCRIPT, "--body", body],
        text=True,
        capture_output=True,
        check=False,
    )


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def proxy_listener_exists(port: int = 29757) -> bool:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def send_email_proxy(body: str) -> subprocess.CompletedProcess[str]:
    py = r"""
import smtplib, socket, os
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime
try:
    import socks
except Exception:
    raise SystemExit(2)

socks.setdefaultproxy(socks.SOCKS5, "127.0.0.1", 29757, rdns=True)
socket.socket = socks.socksocket

host = os.getenv("SMTP_HOST", "smtp.gmail.com")
port = int(os.getenv("SMTP_PORT", "587"))
username = os.getenv("SMTP_USERNAME", "jackieclzheng@gmail.com")
password = os.getenv("SMTP_PASSWORD", "lgjxlgdubragputi")
from_name = os.getenv("SMTP_FROM_NAME", "Jackie Zheng")
subject_prefix = os.getenv("SMTP_SUBJECT_PREFIX", "工业自动化测试")
recipients = [x.strip() for x in os.getenv("SMTP_RECIPIENTS", "274175813@qq.com").split(",") if x.strip()]
body = os.environ.get("MAIL_BODY", "")

msg = EmailMessage()
msg["Subject"] = f"{subject_prefix} {datetime.now().strftime('%Y-%m-%d')}"
msg["From"] = formataddr((from_name, username))
msg["To"] = ", ".join(recipients)
msg.set_content(body)

with smtplib.SMTP(host, port, timeout=90) as server:
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(username, password)
    server.send_message(msg, to_addrs=recipients)
print("sent_via_proxy")
"""
    env = os.environ.copy()
    env["MAIL_BODY"] = body
    return subprocess.run(
        ["python3", "-c", py],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def notify_once(log_file: pathlib.Path, body: str, dry_run: bool) -> bool:
    if dry_run:
        append_log(log_file, f"[dry-run] mail body:\n{body}")
        return True

    direct = send_email_direct(body)
    if direct.returncode == 0:
        append_log(log_file, "email sent via direct SMTP")
        return True
    append_log(log_file, f"direct SMTP failed rc={direct.returncode}")
    if direct.stdout.strip():
        append_log(log_file, f"direct stdout: {direct.stdout.strip()[:300]}")
    if direct.stderr.strip():
        append_log(log_file, f"direct stderr: {direct.stderr.strip()[:300]}")

    p587 = tcp_probe("smtp.gmail.com", 587)
    p465 = tcp_probe("smtp.gmail.com", 465)
    if (not p587 and not p465) and proxy_listener_exists(29757):
        proxy = send_email_proxy(body)
        if proxy.returncode == 0:
            append_log(log_file, "email sent via SOCKS5 proxy")
            return True
        append_log(log_file, f"proxy SMTP failed rc={proxy.returncode}")
        if proxy.stdout.strip():
            append_log(log_file, f"proxy stdout: {proxy.stdout.strip()[:300]}")
        if proxy.stderr.strip():
            append_log(log_file, f"proxy stderr: {proxy.stderr.strip()[:300]}")

    return False


def parse_status(text: str) -> dict[str, object]:
    running_m = re.search(r"RUNNING=(\d+)", text)
    out_m = re.search(r"OUT_EXISTS=(\d+)", text)
    status_all = re.findall(r"STEP4_BG_STATUS\s+(\d+)", text)
    progress = re.findall(r"(?:landmark Det|Lip Synthesis)::\s+(\d+)%", text)

    return {
        "running": int(running_m.group(1)) if running_m else None,
        "out_exists": int(out_m.group(1)) if out_m else None,
        "step_status": int(status_all[-1]) if status_all else None,
        "progress": progress[-1] if progress else None,
    }


def monitor_once(runner: ColabRunner, step_name: str) -> str:
    code = r"""%%bash
set -euo pipefail
RUNNING=0
if pgrep -af "/content/run_step4_bg.sh|inference.py --face base0211" >/dev/null 2>&1; then
  RUNNING=1
fi
echo RUNNING=$RUNNING
OUT=/content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4
if [[ -f "$OUT" ]]; then
  echo OUT_EXISTS=1
  ls -lh "$OUT"
else
  echo OUT_EXISTS=0
fi
LOG=/content/step4_bg.log
if [[ -f "$LOG" ]]; then
  echo LOG_EXISTS=1
  tail -n 140 "$LOG"
else
  echo LOG_EXISTS=0
fi
"""
    runner.run_step(step_name, code, 900)
    tail_path = runner.run_dir / f"{step_name}.tail.txt"
    return tail_path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Colab bg task and send completion mail.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--target-id", default=DEFAULT_TARGET_ID)
    parser.add_argument("--interval-sec", type=int, default=120)
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--log-file", default=str(DEFAULT_LOG_FILE))
    parser.add_argument("--dry-run-mail", action="store_true")
    args = parser.parse_args()

    run_root = pathlib.Path(args.run_root).expanduser().resolve()
    run_dir = run_root / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "_watchbg")
    log_file = pathlib.Path(args.log_file).expanduser().resolve()

    runner = ColabRunner(args.base_url, args.target_id, run_dir)
    append_log(log_file, f"watch start run_dir={run_dir}")

    deadline = time.time() + int(args.max_hours * 3600)
    idx = 0
    while time.time() < deadline:
        idx += 1
        step_name = f"watch_bg_{idx}_{int(time.time())}"
        try:
            runner.ensure_runtime_connected(timeout_sec=240)
            tail = monitor_once(runner, step_name=step_name)
            st = parse_status(tail)
            append_log(
                log_file,
                f"poll#{idx} running={st['running']} out={st['out_exists']} "
                f"status={st['step_status']} progress={st['progress']}",
            )

            if st["step_status"] is not None:
                ok = int(st["step_status"]) == 0 and int(st["out_exists"] or 0) == 1
                result = "成功" if ok else "失败"
                body = (
                    "Colab 视频重生成状态提醒：\n"
                    f"- 结果：{result}\n"
                    f"- 时间：{now()}\n"
                    f"- step4_status：{st['step_status']}\n"
                    f"- out_exists：{st['out_exists']}\n"
                    f"- 进度：{st['progress'] or 'N/A'}\n"
                    "- 输出路径：/content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4\n"
                )
                if notify_once(log_file, body, dry_run=args.dry_run_mail):
                    DONE_FLAG.parent.mkdir(parents=True, exist_ok=True)
                    DONE_FLAG.write_text(f"{now()} status={st['step_status']} out={st['out_exists']}\n", encoding="utf-8")
                return 0 if ok else 2
        except Exception as exc:  # noqa: BLE001
            append_log(log_file, f"poll#{idx} exception: {exc}")

        time.sleep(max(15, args.interval_sec))

    append_log(log_file, "watch timeout")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
