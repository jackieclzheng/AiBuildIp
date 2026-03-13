#!/usr/bin/env bash
set -euo pipefail

# Watch Google Drive for a target file, then send email notification once.
# Default target:
#   gdrive:GPTSoVIS/vrt-autodl-rootfs.tar
#
# Usage:
#   bash colab/notify_when_rootfs_uploaded.sh
#   CHECK_INTERVAL=180 bash colab/notify_when_rootfs_uploaded.sh

RCLONE_BIN="${RCLONE_BIN:-/Users/jackiezheng/bin/rclone}"
RCLONE_CONFIG="${RCLONE_CONFIG:-/Users/jackiezheng/.config/rclone/rclone.conf}"
REMOTE_DIR="${REMOTE_DIR:-gdrive:GPTSoVIS}"
TARGET_FILE="${TARGET_FILE:-vrt-autodl-rootfs.tar}"
CHECK_INTERVAL="${CHECK_INTERVAL:-180}"

PROJECT_ROOT="/Users/jackiezheng/AIBuildIP/GPTSoVIS"
MAIL_BIN="/usr/bin/python3 /Users/jackiezheng/AICAD/send_email.py"
STATE_DIR="${PROJECT_ROOT}/colab/.notify_state"
DONE_FLAG="${STATE_DIR}/rootfs_upload_notified.done"
LOCK_FILE="${STATE_DIR}/rootfs_upload_notified.lock"
LOG_FILE="${PROJECT_ROOT}/colab/notify_when_rootfs_uploaded.log"

COLAB_NOTEBOOK_LINK="https://colab.research.google.com/drive/1W-0emBTiopunpjfbgPUqKdQbwi3u3FP8"

mkdir -p "${STATE_DIR}"
touch "${LOG_FILE}"

if [[ -f "${DONE_FLAG}" ]]; then
  echo "[$(date '+%F %T')] already notified, exit." | tee -a "${LOG_FILE}"
  exit 0
fi

if [[ -f "${LOCK_FILE}" ]]; then
  old_pid="$(cat "${LOCK_FILE}" 2>/dev/null || true)"
  if [[ -n "${old_pid}" ]] && ps -p "${old_pid}" >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] watcher already running pid=${old_pid}, exit." | tee -a "${LOG_FILE}"
    exit 0
  fi
fi
echo "$$" > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:29758}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:29758}"
export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:29758}"

send_direct_mail() {
  local body="$1"
  /usr/bin/python3 /Users/jackiezheng/AICAD/send_email.py --body "${body}"
}

send_proxy_mail() {
  local body="$1"
  /usr/bin/python3 - <<PY
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

msg = EmailMessage()
msg["Subject"] = f"{subject_prefix} {datetime.now().strftime('%Y-%m-%d')}"
msg["From"] = formataddr((from_name, username))
msg["To"] = ", ".join(recipients)
msg.set_content("""${body}""")

with smtplib.SMTP(host, port, timeout=90) as server:
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(username, password)
    server.send_message(msg, to_addrs=recipients)
print("sent_via_proxy")
PY
}

notify_mail() {
  local now body
  now="$(date '+%F %T %Z')"
  body="上传完成提醒：
- 文件：${REMOTE_DIR}/${TARGET_FILE}
- 检测时间：${now}
- Colab入口：${COLAB_NOTEBOOK_LINK}

请直接打开 Colab 链接开始部署。"

  if send_direct_mail "${body}" >> "${LOG_FILE}" 2>&1; then
    echo "[$(date '+%F %T')] mail sent via direct SMTP." | tee -a "${LOG_FILE}"
    return 0
  fi

  echo "[$(date '+%F %T')] direct SMTP failed, checking ports..." | tee -a "${LOG_FILE}"
  local ok587=0 ok465=0
  nc -vz -G 5 smtp.gmail.com 587 >/dev/null 2>&1 || ok587=1
  nc -vz -G 5 smtp.gmail.com 465 >/dev/null 2>&1 || ok465=1
  if [[ "${ok587}" -eq 1 && "${ok465}" -eq 1 ]] && lsof -nP -iTCP:29757 -sTCP:LISTEN >/dev/null 2>&1; then
    if send_proxy_mail "${body}" >> "${LOG_FILE}" 2>&1; then
      echo "[$(date '+%F %T')] mail sent via SOCKS5 proxy." | tee -a "${LOG_FILE}"
      return 0
    fi
  fi
  return 1
}

echo "[$(date '+%F %T')] start watcher: ${REMOTE_DIR}/${TARGET_FILE}" | tee -a "${LOG_FILE}"

while true; do
  if "${RCLONE_BIN}" lsf "${REMOTE_DIR}" --config "${RCLONE_CONFIG}" --contimeout 10s --timeout 60s \
      | grep -Fxq "${TARGET_FILE}"; then
    echo "[$(date '+%F %T')] target found, sending email..." | tee -a "${LOG_FILE}"
    if notify_mail; then
      touch "${DONE_FLAG}"
      echo "[$(date '+%F %T')] done flag written: ${DONE_FLAG}" | tee -a "${LOG_FILE}"
      exit 0
    else
      echo "[$(date '+%F %T')] mail failed, will retry in ${CHECK_INTERVAL}s." | tee -a "${LOG_FILE}"
    fi
  else
    echo "[$(date '+%F %T')] not ready, retry in ${CHECK_INTERVAL}s." >> "${LOG_FILE}"
  fi
  sleep "${CHECK_INTERVAL}"
done
