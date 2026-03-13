#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/sync_github_email_secrets.sh \
    [--repo <owner/repo>] \
    [--host <smtp-host>] \
    [--port <smtp-port>] \
    [--username <smtp-username>] \
    [--password <smtp-password-or-app-password>] \
    [--from-name <from-name>] \
    [--recipients <mail1,mail2,...>] \
    [--subject-prefix <prefix>]

Example:
  # Run directly with built-in defaults:
  scripts/sync_github_email_secrets.sh

  # Or override specific values:
  scripts/sync_github_email_secrets.sh --recipients 'a@b.com,c@d.com'

Prerequisites:
  1) gh CLI installed
  2) gh auth login completed with repo admin permission
EOF
}

REPO="jackieclzheng/AiBuildIp"
SMTP_HOST_VALUE="smtp.gmail.com"
SMTP_PORT_VALUE="587"
SMTP_USERNAME_VALUE="jackieclzheng@gmail.com"
SMTP_PASSWORD_VALUE="lgjxlgdubragputi"
SMTP_FROM_NAME_VALUE="Jackie Zheng"
SMTP_RECIPIENTS_VALUE="274175813@qq.com"
SMTP_SUBJECT_PREFIX_VALUE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --host) SMTP_HOST_VALUE="${2:-}"; shift 2 ;;
    --port) SMTP_PORT_VALUE="${2:-}"; shift 2 ;;
    --username) SMTP_USERNAME_VALUE="${2:-}"; shift 2 ;;
    --password) SMTP_PASSWORD_VALUE="${2:-}"; shift 2 ;;
    --from-name) SMTP_FROM_NAME_VALUE="${2:-}"; shift 2 ;;
    --recipients) SMTP_RECIPIENTS_VALUE="${2:-}"; shift 2 ;;
    --subject-prefix) SMTP_SUBJECT_PREFIX_VALUE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$REPO" || -z "$SMTP_HOST_VALUE" || -z "$SMTP_PORT_VALUE" || -z "$SMTP_USERNAME_VALUE" || -z "$SMTP_FROM_NAME_VALUE" || -z "$SMTP_RECIPIENTS_VALUE" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if command -v gh >/dev/null 2>&1; then
  GH_BIN="gh"
elif [[ -x "$REPO_ROOT/.tools/gh/gh" ]]; then
  GH_BIN="$REPO_ROOT/.tools/gh/gh"
else
  echo "gh CLI not found. Install GitHub CLI or put binary at $REPO_ROOT/.tools/gh/gh." >&2
  exit 1
fi

# GitHub API access is flaky on this machine without the local SOCKS5 tunnel.
if [[ -z "${ALL_PROXY:-}" && -z "${HTTPS_PROXY:-}" && -z "${HTTP_PROXY:-}" ]] \
  && lsof -nP -iTCP:29757 -sTCP:LISTEN >/dev/null 2>&1; then
  export ALL_PROXY="socks5h://127.0.0.1:29757"
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  GH_TOKEN="$("$GH_BIN" auth token 2>/dev/null || true)"
  export GH_TOKEN
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GitHub token unavailable. Re-authenticate with: $GH_BIN auth login -h github.com" >&2
  exit 1
fi

set_secret() {
  local key="$1"
  local val="$2"
  local attempt=1
  local max_attempts=5
  local output=""
  local rc=0

  while (( attempt <= max_attempts )); do
    if output=$("$GH_BIN" secret set "$key" --repo "$REPO" --body "$val" 2>&1); then
      echo "updated: $key"
      return 0
    fi
    rc=$?
    if (( attempt == max_attempts )); then
      echo "$output" >&2
      echo "failed to update: $key" >&2
      return "$rc"
    fi
    echo "retrying: $key (attempt $attempt/$max_attempts failed)" >&2
    sleep "$attempt"
    attempt=$((attempt + 1))
  done
}

# Canonical SMTP keys used by scripts/workflows.
set_secret "SMTP_HOST" "$SMTP_HOST_VALUE"
set_secret "SMTP_PORT" "$SMTP_PORT_VALUE"
set_secret "SMTP_USERNAME" "$SMTP_USERNAME_VALUE"
set_secret "SMTP_PASSWORD" "$SMTP_PASSWORD_VALUE"
set_secret "SMTP_FROM_NAME" "$SMTP_FROM_NAME_VALUE"
set_secret "SMTP_RECIPIENTS" "$SMTP_RECIPIENTS_VALUE"

if [[ -n "$SMTP_SUBJECT_PREFIX_VALUE" ]]; then
  set_secret "SMTP_SUBJECT_PREFIX" "$SMTP_SUBJECT_PREFIX_VALUE"
fi

# Mirror to CODEX_* keys.
set_secret "CODEX_SMTP_HOST" "$SMTP_HOST_VALUE"
set_secret "CODEX_SMTP_PORT" "$SMTP_PORT_VALUE"
set_secret "CODEX_SMTP_USERNAME" "$SMTP_USERNAME_VALUE"
set_secret "CODEX_SMTP_PASSWORD" "$SMTP_PASSWORD_VALUE"
set_secret "CODEX_SMTP_FROM_NAME" "$SMTP_FROM_NAME_VALUE"
set_secret "CODEX_SMTP_RECIPIENTS" "$SMTP_RECIPIENTS_VALUE"
if [[ -n "$SMTP_SUBJECT_PREFIX_VALUE" ]]; then
  set_secret "CODEX_SMTP_SUBJECT_PREFIX" "$SMTP_SUBJECT_PREFIX_VALUE"
fi

# Mirror to GMAIL_* keys.
set_secret "GMAIL_HOST" "$SMTP_HOST_VALUE"
set_secret "GMAIL_PORT" "$SMTP_PORT_VALUE"
set_secret "GMAIL_USERNAME" "$SMTP_USERNAME_VALUE"
set_secret "GMAIL_PASSWORD" "$SMTP_PASSWORD_VALUE"
set_secret "GMAIL_FROM_NAME" "$SMTP_FROM_NAME_VALUE"
set_secret "GMAIL_RECIPIENTS" "$SMTP_RECIPIENTS_VALUE"
if [[ -n "$SMTP_SUBJECT_PREFIX_VALUE" ]]; then
  set_secret "GMAIL_SUBJECT_PREFIX" "$SMTP_SUBJECT_PREFIX_VALUE"
fi

echo "Done. GitHub Actions email secrets synced for $REPO."
