#!/usr/bin/env python3
"""Resume Colab VRT workflow and watch until notification email is sent.

Flow:
1) Probe current Colab runtime state.
2) Restore env in background if missing.
3) Ensure base video exists.
4) Run regen in background and poll until done.
5) Send completion/failure email (direct SMTP, proxy fallback).
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.parse
from typing import Optional

sys.path.insert(0, "/Users/jackiezheng/AIBuildIP/GPTSoVIS")
from colab.direct_colab_deploy import (  # noqa: E402
    ColabRunner,
    http_get_json,
    http_post_json,
    refresh_and_get_drive_access_token,
)


DEFAULT_BASE_URL = "http://127.0.0.1:18791"
DEFAULT_RUN_ROOT = pathlib.Path("/Users/jackiezheng/AIBuildIP/GPTSoVIS/colab/.browser_runs")
MAIL_SCRIPT = "/Users/jackiezheng/AICAD/send_email.py"
OUT_FILE = "/content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4"
DRIVE_OUTPUT_DIR = "/content/drive/MyDrive/GPTSoVIS/outputs"
DRIVE_REMOTE_PREFIX = "GPTSoVIS/outputs"
LOCAL_OUTPUT_DIR = pathlib.Path("/Users/jackiezheng/AIBuildIP/GPTSoVIS/colab/downloaded_outputs")
RCLONE_CONFIG = pathlib.Path("/Users/jackiezheng/.config/rclone/rclone.conf")
ROOTFS_LINK = "https://drive.google.com/open?id=1C0xuCy85d5aT8FCSYzilQWJqcR5k7W4m"
ROOTFS_FILE_ID = "1C0xuCy85d5aT8FCSYzilQWJqcR5k7W4m"
ROOTFS_EXPECT_BYTES = 20170823680
COLAB_NEW_URL = "https://colab.research.google.com/"
THIS_DIR = pathlib.Path(__file__).resolve().parent
LOCAL_RESTORE_SCRIPT = THIS_DIR / "restore_vrt_env_from_tar.sh"
LOCAL_REGEN_SCRIPT = THIS_DIR / "replace_base_and_regen.sh"


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def parse_authuser(url: str) -> Optional[int]:
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query or "")
        if "authuser" in q and q["authuser"]:
            return int(q["authuser"][0])
    except Exception:
        return None
    return None


def is_notebook_tab(tab: dict) -> bool:
    url = (tab.get("url") or "").lower()
    if not url.startswith("https://colab.research.google.com/"):
        return False
    if (tab.get("type") or "").lower() != "page":
        return False
    if "rotatecookiespage" in url or "googleusercontent" in url:
        return False
    return True


def tab_score(tab: dict) -> int:
    url = (tab.get("url") or "").lower()
    title = (tab.get("title") or "").lower()
    score = 0
    if "/drive/" in url:
        score += 45
    if "/github/" in url:
        score += 30
    if "/notebooks/" in url:
        score += 30
    if ".ipynb" in url:
        score += 25
    if ".ipynb" in title or "untitled" in title:
        score += 15
    if "google colab" not in title:
        score += 5
    return score


def resolve_account_authuser(pool_file: pathlib.Path, account_id: str) -> Optional[int]:
    if not account_id:
        return None
    try:
        raw = pool_file.expanduser().read_text(encoding="utf-8")
        obj = json.loads(raw)
    except Exception:
        return None
    for a in obj.get("accounts", []) or []:
        if str(a.get("id", "")).strip() == account_id and bool(a.get("enabled", True)):
            return int(a.get("authuser", 0))
    return None


def choose_target_id(
    base_url: str,
    preferred: Optional[str],
    account_id: str = "",
    account_pool: str = "",
    auto_open: bool = True,
) -> str:
    data = http_get_json(f"{base_url.rstrip('/')}/tabs", timeout=30)
    tabs = data.get("tabs") or []

    candidates = []
    pool_auth = resolve_account_authuser(pathlib.Path(account_pool), account_id) if account_pool else None

    for tab in tabs:
        if not is_notebook_tab(tab):
            continue
        tid = tab.get("targetId")
        if not tid:
            continue
        url = str(tab.get("url") or "")
        candidates.append(
            {
                "target": tid,
                "authuser": parse_authuser(url),
                "score": tab_score(tab),
                "title": tab.get("title") or "",
                "url": url,
            }
        )

    if preferred:
        for c in candidates:
            if c["target"] == preferred:
                return str(preferred)

    if pool_auth is not None:
        auth_candidates = [c for c in candidates if c["authuser"] == pool_auth]
        if auth_candidates:
            candidates = auth_candidates

    if not candidates:
        if auto_open:
            obj = http_post_json(
                f"{base_url.rstrip('/')}/tabs/open",
                {"url": COLAB_NEW_URL},
                timeout=30,
            )
            if "error" in obj:
                raise RuntimeError(obj["error"])
            new_target = str(obj.get("targetId") or obj.get("target") or "")
            if not new_target:
                raise RuntimeError(f"/tabs/open did not return targetId: {obj}")
            try:
                # Try focusing this new tab if the browser profile supports it.
                http_post_json(
                    f"{base_url.rstrip('/')}/tabs/focus",
                    {"targetId": new_target},
                    timeout=20,
                )
            except Exception:
                pass
            log(f"auto-opened new Colab tab target={new_target}")
            return new_target
        raise RuntimeError("No Colab notebook tab found in /tabs.")

    best = max(candidates, key=lambda c: c["score"])
    if best.get("target"):
        log(f"auto target selected: {best['target']} | {best.get('title')} | score={best['score']}")
        return str(best["target"])

    raise RuntimeError("No Colab notebook tab found in /tabs.")


def run_step_text(
    runner: ColabRunner,
    name: str,
    code: str,
    timeout_sec: int = 900,
    log_preview: bool = True,
    persist_artifacts: bool = True,
    allow_interrupted: bool = True,
) -> str:
    runner.log(f"start {name}")
    if persist_artifacts:
        (runner.run_dir / f"{name}.code.sh").write_text(code, encoding="utf-8")

    start_state = runner.read_cell_tail()
    start_exec = start_state.get("execCount")

    runner.set_focused_cell_code(code)
    runner.run_focused_cell()

    deadline = time.time() + timeout_sec
    last_preview = ""
    stable_polls = 0
    final_all_tail = ""

    while time.time() < deadline:
        state = runner.read_cell_tail()
        tail = state.get("tail") or ""
        all_tail = state.get("allTail") or ""
        status = state.get("status") or ""
        exec_count = state.get("execCount")
        final_all_tail = all_tail

        preview = (tail or all_tail)[-500:].replace("\n", "\\n")
        if preview != last_preview:
            if log_preview:
                runner.log(f"progress exec={exec_count} status={status} tail={preview}")
            else:
                runner.log(f"progress exec={exec_count} status={status} tail=<hidden>")
            last_preview = preview
            stable_polls = 0
        else:
            stable_polls += 1

        exec_advanced = (
            start_exec is None
            or exec_count is None
            or exec_count != start_exec
        )
        interrupted = (
            "Process is interrupted." in tail
            or "Process is interrupted." in all_tail
            or "Process is terminated." in tail
            or "Process is terminated." in all_tail
        )
        if allow_interrupted and interrupted and stable_polls >= 1:
            out = all_tail if all_tail.strip() else tail
            if persist_artifacts:
                (runner.run_dir / f"{name}.tail.txt").write_text(out, encoding="utf-8")
            runner.log(f"done {name} (interrupted)")
            return out
        if exec_advanced and not runner._status_running(status) and stable_polls >= 2:
            out = all_tail if all_tail.strip() else tail
            if persist_artifacts:
                (runner.run_dir / f"{name}.tail.txt").write_text(out, encoding="utf-8")
            runner.log(f"done {name}")
            return out

        time.sleep(2)

    last_state = runner.read_cell_tail()
    last_tail = last_state.get("tail") or ""
    out = last_tail if last_tail.strip() else (final_all_tail or "")
    if persist_artifacts:
        (runner.run_dir / f"{name}.tail.txt").write_text(out, encoding="utf-8")
    raise TimeoutError(f"cell timeout: {name}")


def parse_probe(tail: str) -> dict[str, int]:
    vals: dict[str, int] = {}

    def last_int(pat: str) -> int:
        hits = re.findall(pat, tail, flags=re.MULTILINE)
        return int(hits[-1]) if hits else 0

    for key in [
        "HAS_ROOTFS",
        "ROOTFS_BYTES",
        "HAS_BASE",
        "HAS_RESTORE_SH",
        "HAS_REGEN_SH",
        "HAS_ENV_PY",
        "HAS_OUT",
    ]:
        vals[key] = last_int(rf"^{key}=(\d+)$")
    return vals


def probe_state(runner: ColabRunner, name: str) -> dict[str, int]:
    code = r"""%%bash
set -euo pipefail
echo PROBE_START
[[ -f /content/vrt-autodl-rootfs.tar ]] && echo HAS_ROOTFS=1 || echo HAS_ROOTFS=0
if [[ -f /content/vrt-autodl-rootfs.tar ]]; then
  ROOTFS_BYTES=$(stat -c%s /content/vrt-autodl-rootfs.tar 2>/dev/null || stat -f%z /content/vrt-autodl-rootfs.tar 2>/dev/null || echo 0)
  echo ROOTFS_BYTES=$ROOTFS_BYTES
else
  echo ROOTFS_BYTES=0
fi
[[ -f /content/base0211.mp4 ]] && echo HAS_BASE=1 || echo HAS_BASE=0
[[ -x /content/restore_vrt_env_from_tar.sh ]] && echo HAS_RESTORE_SH=1 || echo HAS_RESTORE_SH=0
[[ -x /content/replace_base_and_regen.sh ]] && echo HAS_REGEN_SH=1 || echo HAS_REGEN_SH=0
[[ -x /content/vrt_autodl_clone/root/miniconda3/envs/video_retalking/bin/python ]] && echo HAS_ENV_PY=1 || echo HAS_ENV_PY=0
[[ -f /content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4 ]] && echo HAS_OUT=1 || echo HAS_OUT=0
"""
    keys = [
        "HAS_ROOTFS",
        "ROOTFS_BYTES",
        "HAS_BASE",
        "HAS_RESTORE_SH",
        "HAS_REGEN_SH",
        "HAS_ENV_PY",
        "HAS_OUT",
    ]
    last_tail = ""
    for attempt in range(1, 6):
        tail = run_step_text(runner, f"{name}_try{attempt}", code, timeout_sec=900)
        last_tail = tail
        vals = parse_probe(tail)
        complete = all(
            re.search(rf"^{k}=(\d+)$", tail, flags=re.MULTILINE) is not None for k in keys
        )
        if complete:
            log(f"probe: {vals}")
            return vals
        log(f"probe incomplete/interrupted (attempt {attempt}/5), retrying...")
        time.sleep(2)

    vals = parse_probe(last_tail)
    log(f"probe fallback (incomplete): {vals}")
    return vals


def probe_gpu_state(runner: ColabRunner, name: str) -> dict[str, Optional[str | int]]:
    code = r"""%%bash
set +e
echo GPU_PROBE_START
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L 2>/dev/null | sed -n '1,4p' || true
else
  echo NVIDIA_SMI_MISSING=1
fi
python3 - <<'PY'
import os
try:
    import torch
    print("TORCH_CUDA_AVAILABLE=%d" % (1 if torch.cuda.is_available() else 0))
    if torch.cuda.is_available():
        print("TORCH_CUDA_DEVICE=%s" % torch.cuda.get_device_name(0))
except Exception as exc:  # noqa: BLE001
    print("TORCH_IMPORT_ERR=%s" % exc.__class__.__name__)
    print("TORCH_IMPORT_MSG=%s" % str(exc).replace("\n", " "))
PY
if nvidia-smi -L 2>/dev/null | grep -q '^GPU 0:'; then
  echo NVIDIA_GPU_PRESENT=1
else
  echo NVIDIA_GPU_PRESENT=0
fi
"""
    tail = run_step_text(runner, name, code, timeout_sec=900)
    cuda_hits = re.findall(r"^TORCH_CUDA_AVAILABLE=(\d+)$", tail, flags=re.MULTILINE)
    nvidia_hits = re.findall(r"^NVIDIA_GPU_PRESENT=(\d+)$", tail, flags=re.MULTILINE)
    dev_hits = re.findall(r"^TORCH_CUDA_DEVICE=(.+)$", tail, flags=re.MULTILINE)
    cuda_ok = int(cuda_hits[-1]) if cuda_hits else 0
    nvidia_ok = int(nvidia_hits[-1]) if nvidia_hits else 0
    return {
        "cuda_available": cuda_ok,
        "nvidia_gpu": nvidia_ok,
        "ready": 1 if (cuda_ok == 1 or nvidia_ok == 1) else 0,
        "device": dev_hits[-1].strip() if dev_hits else None,
    }


def ensure_support_scripts(runner: ColabRunner, name: str) -> None:
    restore_b64 = ""
    regen_b64 = ""
    if LOCAL_RESTORE_SCRIPT.exists():
        restore_b64 = base64.b64encode(LOCAL_RESTORE_SCRIPT.read_bytes()).decode("ascii")
    if LOCAL_REGEN_SCRIPT.exists():
        regen_b64 = base64.b64encode(LOCAL_REGEN_SCRIPT.read_bytes()).decode("ascii")

    code = f"""%%bash
set -euo pipefail
pip -q install gdown >/dev/null 2>&1 || true
python3 - <<'PY'
import base64
from pathlib import Path
payloads = [
    ("{restore_b64}", "/content/restore_vrt_env_from_tar.sh"),
    ("{regen_b64}", "/content/replace_base_and_regen.sh"),
]
for blob, out in payloads:
    if not blob:
        continue
    p = Path(out)
    p.write_bytes(base64.b64decode(blob.encode("ascii")))
    p.chmod(0o755)
print("LOCAL_SCRIPT_SYNC=1")
PY
if [[ ! -x /content/restore_vrt_env_from_tar.sh ]]; then
  gdown --fuzzy "https://drive.google.com/open?id=1yiwstSPdSo3Q2pQJV61iqvXxsIWwhiLQ" -O /content/restore_vrt_env_from_tar.sh
fi
if [[ ! -x /content/replace_base_and_regen.sh ]]; then
  gdown --fuzzy "https://drive.google.com/open?id=1HB3mIY8XLKAiLmQyASZi_xlTtvCPPnOq" -O /content/replace_base_and_regen.sh
fi
chmod +x /content/restore_vrt_env_from_tar.sh /content/replace_base_and_regen.sh
ls -lh /content/restore_vrt_env_from_tar.sh /content/replace_base_and_regen.sh
"""
    run_step_text(runner, name, code, timeout_sec=1800)


def ensure_base_video(runner: ColabRunner, name: str) -> None:
    code = r"""%%bash
set -euo pipefail
if [[ ! -f /content/base0211.mp4 ]]; then
  pip -q install gdown >/dev/null 2>&1 || true
  gdown --fuzzy "https://drive.google.com/open?id=1KXZ2lkmVC8a6RXMRsgwyogusXeUdLwdk" -O /content/base0211.mp4
fi
ls -lh /content/base0211.mp4
"""
    run_step_text(runner, name, code, timeout_sec=3600)


def ensure_rootfs_tar(runner: ColabRunner, name: str) -> None:
    access_token = refresh_and_get_drive_access_token()
    code = f"""%%bash
set -euo pipefail
out=/content/vrt-autodl-rootfs.tar
exp={ROOTFS_EXPECT_BYTES}
cur=0
need_download=0
if [[ -f "$out" ]]; then
  cur=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out" 2>/dev/null || echo 0)
fi
if [[ "$cur" -lt "$exp" ]]; then
  # Keep partial file and resume from current offset.
  echo ROOTFS_PARTIAL cur="$cur" expect="$exp"
  need_download=1
elif [[ -f "$out" ]]; then
  # Size alone is insufficient; verify archive structure to catch truncated/corrupted tar.
  if tar -tf "$out" >/dev/null 2>&1; then
    echo ROOTFS_TAR_OK=1
  else
    echo ROOTFS_TAR_BROKEN=1
    # Full-sized but structurally broken file: restart download from scratch.
    rm -f "$out" || true
    need_download=1
  fi
fi
if [[ "$need_download" -eq 1 ]]; then
  python3 -m pip -q install --upgrade requests >/dev/null 2>&1 || true
  python3 - <<'PY'
import os
import re
import time
import requests

token = {access_token!r}
file_id = "{ROOTFS_FILE_ID}"
url = f"https://www.googleapis.com/drive/v3/files/{{file_id}}?alt=media&acknowledgeAbuse=true"
out = "/content/vrt-autodl-rootfs.tar"
exp = {ROOTFS_EXPECT_BYTES}

ok = False
last_err = ""
for attempt in range(1, 31):
    cur = os.path.getsize(out) if os.path.exists(out) else 0
    if cur >= exp:
        ok = True
        break
    headers = {{
        "Authorization": f"Bearer {{token}}",
        "Accept-Encoding": "identity",
    }}
    if cur > 0:
        headers["Range"] = f"bytes={{cur}}-"
    try:
        with requests.get(url, headers=headers, stream=True, timeout=(30, 120)) as r:
            print(
                "ATTEMPT", attempt,
                "CUR_BYTES", cur,
                "HTTP_STATUS", r.status_code,
                "CL", r.headers.get("Content-Length"),
                "CR", r.headers.get("Content-Range"),
            )
            if r.status_code not in (200, 206):
                body = (r.text or "")[:320].replace("\\n", " ")
                last_err = f"status={{r.status_code}} body={{body}}"
                raise RuntimeError(last_err)
            mode = "wb"
            if cur > 0 and r.status_code == 206:
                cr = r.headers.get("Content-Range") or ""
                m = re.match(r"bytes\\s+(\\d+)-\\d+/\\d+", cr)
                if m and int(m.group(1)) == cur:
                    mode = "ab"
                else:
                    print("RANGE_MISMATCH_RESTART=1", "CR", cr, "CUR", cur)
            elif cur > 0:
                print("RANGE_IGNORED_RESTART=1")
            total = cur if mode == "ab" else 0
            last_report_gb = int(total / (1024**3))
            with open(out, mode) as f:
                for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    total += len(chunk)
                    cur_gb = int(total / (1024**3))
                    if cur_gb > last_report_gb:
                        last_report_gb = cur_gb
                        print("DOWNLOADED_GB", round(total / (1024**3), 2))
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        print("ATTEMPT_ERR", attempt, last_err)
        if attempt < 30:
            time.sleep(min(30, attempt * 2))

got = os.path.getsize(out) if os.path.exists(out) else 0
if got >= exp:
    ok = True

print("DONE_BYTES", got)
if (not ok) or got < exp:
    raise SystemExit(f"ROOTFS_TRUNCATED got={{got}} expect={{exp}}")
PY
fi
tar -tf "$out" >/dev/null
ls -lh "$out"
"""
    run_step_text(
        runner,
        name,
        code,
        timeout_sec=21600,
        log_preview=True,
        persist_artifacts=True,
        allow_interrupted=False,
    )


def start_restore_bg(runner: ColabRunner, name: str) -> None:
    code = r"""%%bash
set -euo pipefail
if pgrep -af '/content/run_restore_bg.sh|restore_vrt_env_from_tar.sh' >/dev/null 2>&1; then
  echo RESTORE_ALREADY_RUNNING=1
  pgrep -af '/content/run_restore_bg.sh|restore_vrt_env_from_tar.sh' || true
  exit 0
fi
cat >/content/run_restore_bg.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
status=0
bash /content/restore_vrt_env_from_tar.sh \
  --tar /content/vrt-autodl-rootfs.tar \
  --workdir /content/vrt_autodl_clone \
  --skip-demo || status=$?
echo STEP2_BG_STATUS $status
exit $status
SH
chmod +x /content/run_restore_bg.sh
nohup bash /content/run_restore_bg.sh >/content/step2_bg.log 2>&1 &
echo STEP2_BG_PID=$!
sleep 2
pgrep -af '/content/run_restore_bg.sh|restore_vrt_env_from_tar.sh' || true
"""
    run_step_text(runner, name, code, timeout_sec=900)


def poll_restore_bg(runner: ColabRunner, name: str) -> dict[str, Optional[int]]:
    code = r"""%%bash
set -euo pipefail
RUNNING=0
if pgrep -af '/content/run_restore_bg.sh|restore_vrt_env_from_tar.sh' >/dev/null 2>&1; then
  RUNNING=1
fi
echo RUNNING=$RUNNING
[[ -x /content/vrt_autodl_clone/root/miniconda3/envs/video_retalking/bin/python ]] && echo ENV_PY=1 || echo ENV_PY=0
if [[ -f /content/step2_bg.log ]]; then
  tail -n 120 /content/step2_bg.log
else
  echo RESTORE_LOG_MISSING=1
fi
"""
    tail = run_step_text(runner, name, code, timeout_sec=900)
    running_hits = re.findall(r"^RUNNING=(\d+)$", tail, flags=re.MULTILINE)
    env_py_hits = re.findall(r"^ENV_PY=(\d+)$", tail, flags=re.MULTILINE)
    status_hits = re.findall(r"STEP2_BG_STATUS\s+(\d+)", tail)
    return {
        "running": int(running_hits[-1]) if running_hits else None,
        "env_py": int(env_py_hits[-1]) if env_py_hits else None,
        "status": int(status_hits[-1]) if status_hits else None,
    }


def start_step4_bg(runner: ColabRunner, name: str) -> None:
    code = r"""%%bash
set -euo pipefail
if pgrep -af "/content/run_step4_bg.sh|inference.py --face base0211" >/dev/null 2>&1; then
  echo STEP4_ALREADY_RUNNING=1
  pgrep -af "/content/run_step4_bg.sh|inference.py --face base0211" || true
  exit 0
fi
cat >/content/run_step4_bg.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
WORKDIR=/content/vrt_autodl_clone
PROJ="$WORKDIR/root/autodl-tmp/video-retalking"
ENV_DIR="$WORKDIR/root/miniconda3/envs/video_retalking"
PY_BIN="$ENV_DIR/bin/python"
OUT="$PROJ/outputs/output_vrt_base0211.mp4"
BASE_SRC=/content/base0211.mp4
BASE_RUN=$BASE_SRC
STATUS=0

if [[ ! -x "$PY_BIN" ]]; then
  echo "[err] missing python: $PY_BIN"
  echo STEP4_BG_STATUS 2
  exit 2
fi
if [[ ! -f "$BASE_SRC" ]]; then
  echo "[err] missing base video $BASE_SRC"
  echo STEP4_BG_STATUS 3
  exit 3
fi

WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$BASE_SRC" 2>/dev/null | tr -d '\r' || true)
BASE_RUN=/content/base0211_lowmem.mp4
VF="fps=12"
if [[ "${WIDTH:-0}" =~ ^[0-9]+$ ]] && [[ "$WIDTH" -gt 640 ]]; then
  VF="fps=12,scale=640:-2"
fi
ffmpeg -loglevel error -y -i "$BASE_SRC" -vf "$VF" -an -c:v libx264 -preset veryfast -crf 20 "$BASE_RUN" || BASE_RUN="$BASE_SRC"

BASE_NAME=$(basename "$BASE_RUN")
VOICE_FILE="$PROJ/voice.wav"
if [[ ! -f "$VOICE_FILE" ]]; then
  echo "[err] missing audio: $VOICE_FILE"
  echo STEP4_BG_STATUS 4
  exit 4
fi
cp -f "$BASE_RUN" "$PROJ/$(basename "$BASE_RUN")"

/content/replace_base_and_regen.sh \
  --workdir "$WORKDIR" \
  --base "$BASE_RUN" \
  --audio "$VOICE_FILE" \
  --outfile "$OUT" || STATUS=$?

if [[ -f "$OUT" ]]; then
  ls -lh "$OUT"
else
  echo "[warn] output missing: $OUT"
fi
echo STEP4_BG_STATUS $STATUS
exit $STATUS
SH
chmod +x /content/run_step4_bg.sh
nohup bash /content/run_step4_bg.sh >/content/step4_bg.log 2>&1 &
echo STEP4_BG_PID=$!
sleep 2
pgrep -af "/content/run_step4_bg.sh|inference.py --face base0211" || true
"""
    run_step_text(runner, name, code, timeout_sec=900)


def poll_step4_bg(runner: ColabRunner, name: str) -> dict[str, Optional[int | str]]:
    code = r"""%%bash
set -euo pipefail
RUNNING=0
if pgrep -af "/content/run_step4_bg.sh|inference.py --face base0211" >/dev/null 2>&1; then
  RUNNING=1
fi
echo RUNNING=$RUNNING
if [[ -f /content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4 ]]; then
  echo OUT_EXISTS=1
  ls -lh /content/vrt_autodl_clone/root/autodl-tmp/video-retalking/outputs/output_vrt_base0211.mp4
else
  echo OUT_EXISTS=0
fi
if [[ -f /content/step4_bg.log ]]; then
  tail -n 140 /content/step4_bg.log
else
  echo STEP4_LOG_MISSING=1
fi
"""
    tail = run_step_text(runner, name, code, timeout_sec=900)
    running_hits = re.findall(r"RUNNING=(\d+)", tail)
    out_hits = re.findall(r"OUT_EXISTS=(\d+)", tail)
    status_hits = re.findall(r"STEP4_BG_STATUS\s+(\d+)", tail)
    progress_hits = re.findall(r"(?:landmark Det|Lip Synthesis)::\s+(\d+)%", tail)
    return {
        "running": int(running_hits[-1]) if running_hits else None,
        "out_exists": int(out_hits[-1]) if out_hits else None,
        "status": int(status_hits[-1]) if status_hits else None,
        "progress": progress_hits[-1] if progress_hits else None,
    }


def save_output_to_drive(
    runner: ColabRunner,
    name: str,
    drive_filename: str,
) -> dict[str, Optional[str | int]]:
    code = f"""%%bash
set -euo pipefail
OUT="{OUT_FILE}"
DRIVE_DIR="{DRIVE_OUTPUT_DIR}"
DRIVE_TARGET="$DRIVE_DIR/{drive_filename}"
if [[ -d /content/drive/MyDrive ]]; then
  echo DRIVE_MOUNTED=1
  mkdir -p "$DRIVE_DIR"
  cp -f "$OUT" "$DRIVE_TARGET"
  sync || true
  if [[ -f "$DRIVE_TARGET" ]]; then
    echo DRIVE_SAVED=1
    echo "DRIVE_PATH=$DRIVE_TARGET"
    ls -lh "$DRIVE_TARGET"
  else
    echo DRIVE_SAVED=0
  fi
else
  echo DRIVE_MOUNTED=0
  echo DRIVE_SAVED=0
fi
"""
    tail = run_step_text(runner, name, code, timeout_sec=900)
    mounted_hits = re.findall(r"DRIVE_MOUNTED=(\d+)", tail)
    saved_hits = re.findall(r"DRIVE_SAVED=(\d+)", tail)
    path_hits = re.findall(r"DRIVE_PATH=(.+)", tail)
    return {
        "mounted": int(mounted_hits[-1]) if mounted_hits else None,
        "saved": int(saved_hits[-1]) if saved_hits else None,
        "drive_path": path_hits[-1].strip() if path_hits else None,
    }


def ensure_drive_mount(runner: ColabRunner, name: str, retries: int = 4) -> None:
    code = r"""%%python
import os
from pathlib import Path

from google.colab import drive

for attempt in range(1, 5):
    if Path('/content/drive/MyDrive').exists():
        print(f"DRIVE_MOUNTED_NOW=1 attempt={attempt}")
        break
    print(f"MOUNT_ATTEMPT={attempt}")
    try:
        if attempt > 1:
            drive.mount('/content/drive', force_remount=True)
        else:
            drive.mount('/content/drive')
        if Path('/content/drive/MyDrive').exists():
            print(f"DRIVE_MOUNTED_NOW=1 attempt={attempt}")
            break
        print("DRIVE_MOUNTED_NOW=0")
    except Exception as exc:  # noqa: BLE001
        print("DRIVE_MOUNT_ERROR", type(exc).__name__, str(exc).replace('\n', ' '))
"""
    mounted = False
    for attempt in range(max(1, retries)):
        runner.maybe_handle_oauth_tabs()
        runner.maybe_handle_drive_dialog()
        tail = run_step_text(runner, name, code, timeout_sec=1200, log_preview=True)
        if "DRIVE_MOUNTED_NOW=1" in tail:
            log(f"drive mount success (attempt {attempt + 1})")
            mounted = True
            break
        time.sleep(3)

    if not mounted:
        raise RuntimeError("Drive mount failed in Colab after retries.")


def find_rclone_bin() -> str:
    candidates = [
        "/Users/jackiezheng/bin/rclone",
        "rclone",
    ]
    for c in candidates:
        proc = subprocess.run(["bash", "-lc", f"command -v {c}"], capture_output=True, text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    raise RuntimeError("rclone not found (expected /Users/jackiezheng/bin/rclone or PATH rclone).")


def detect_http_proxy_url(port: int = 29758) -> Optional[str]:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return f"http://127.0.0.1:{port}"
    return None


def rclone_download_from_drive(
    remote_name: str,
    remote_rel: str,
    local_file: pathlib.Path,
) -> tuple[bool, str]:
    rclone_bin = find_rclone_bin()
    if not RCLONE_CONFIG.exists():
        return False, f"rclone config missing: {RCLONE_CONFIG}"

    local_file.parent.mkdir(parents=True, exist_ok=True)
    remote_full = f"{remote_name}:{remote_rel}"
    cmd = [
        rclone_bin, "copyto", remote_full, str(local_file),
        "--config", str(RCLONE_CONFIG),
        "--retries", "3",
        "--low-level-retries", "3",
        "--contimeout", "10s",
        "--timeout", "120s",
        "--stats-one-line",
    ]

    direct = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if direct.returncode == 0 and local_file.exists() and local_file.stat().st_size > 0:
        return True, "direct rclone"

    proxy_url = detect_http_proxy_url(29758)
    if not proxy_url:
        err = (direct.stderr or direct.stdout or "").strip().replace("\n", " ")
        return False, f"direct failed rc={direct.returncode}: {err[:220]}"

    env = os.environ.copy()
    env["HTTPS_PROXY"] = proxy_url
    env["HTTP_PROXY"] = proxy_url
    env["ALL_PROXY"] = proxy_url
    via_proxy = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if via_proxy.returncode == 0 and local_file.exists() and local_file.stat().st_size > 0:
        return True, "rclone via HTTP proxy"

    err = (via_proxy.stderr or via_proxy.stdout or "").strip().replace("\n", " ")
    return False, f"proxy failed rc={via_proxy.returncode}: {err[:220]}"


def resolve_drive_remote_from_pool(pool_file: pathlib.Path, account_id: str) -> str:
    p = pool_file.expanduser().resolve()
    if not p.exists():
        raise RuntimeError(f"account pool file not found: {p}")
    obj = json.loads(p.read_text(encoding="utf-8"))
    accounts = obj.get("accounts") or []
    for a in accounts:
        if str(a.get("id", "")).strip() == account_id:
            if not bool(a.get("enabled", True)):
                raise RuntimeError(f"account is disabled in pool: {account_id}")
            remote = str(a.get("drive_remote", "")).strip()
            if not remote:
                raise RuntimeError(f"drive_remote missing for account: {account_id}")
            return remote
    raise RuntimeError(f"account not found in pool: {account_id}")


def send_email_direct(
    body: str,
    attachments: Optional[list[pathlib.Path]] = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["python3", MAIL_SCRIPT, "--body", body]
    if attachments:
        cmd += ["--attach", ",".join(str(p) for p in attachments)]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
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
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def send_email_proxy(
    body: str,
    attachments: Optional[list[pathlib.Path]] = None,
) -> subprocess.CompletedProcess[str]:
    py = r"""
import os
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
import socks

socks.setdefaultproxy(socks.SOCKS5, "127.0.0.1", 29757, rdns=True)
socket.socket = socks.socksocket

host = os.getenv("SMTP_HOST", "smtp.gmail.com")
port = int(os.getenv("SMTP_PORT", "587"))
username = os.getenv("SMTP_USERNAME", "jackieclzheng@gmail.com")
password = os.getenv("SMTP_PASSWORD", "lgjxlgdubragputi")
from_name = os.getenv("SMTP_FROM_NAME", "Jackie Zheng")
subject_prefix = os.getenv("SMTP_SUBJECT_PREFIX", "工业自动化测试")
recipients = [x.strip() for x in os.getenv("SMTP_RECIPIENTS", "274175813@qq.com").split(",") if x.strip()]
body = os.environ["MAIL_BODY"]

msg = EmailMessage()
msg["Subject"] = f"{subject_prefix} {datetime.now().strftime('%Y-%m-%d')}"
msg["From"] = formataddr((from_name, username))
msg["To"] = ", ".join(recipients)
msg.set_content(body)

attach_csv = os.environ.get("MAIL_ATTACH", "").strip()
if attach_csv:
    for raw in attach_csv.split(","):
        p = Path(raw.strip())
        if not p.exists():
            raise FileNotFoundError(f"Attachment not found: {p}")
        msg.add_attachment(
            p.read_bytes(),
            maintype="application",
            subtype="octet-stream",
            filename=p.name,
        )

with smtplib.SMTP(host, port, timeout=90) as s:
    s.ehlo()
    s.starttls()
    s.ehlo()
    s.login(username, password)
    s.send_message(msg, to_addrs=recipients)
print("sent_via_proxy")
"""
    env = os.environ.copy()
    env["MAIL_BODY"] = body
    env["MAIL_ATTACH"] = ",".join(str(p) for p in (attachments or []))
    return subprocess.run(
        ["python3", "-c", py],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def send_email_with_fallback(
    body: str,
    attachments: Optional[list[pathlib.Path]] = None,
) -> tuple[bool, str]:
    direct = send_email_direct(body, attachments=attachments)
    if direct.returncode == 0:
        return True, "direct SMTP"

    p587 = tcp_probe("smtp.gmail.com", 587)
    p465 = tcp_probe("smtp.gmail.com", 465)
    if (not p587 and not p465) and proxy_listener_exists(29757):
        proxy = send_email_proxy(body, attachments=attachments)
        if proxy.returncode == 0:
            return True, "SMTP via SOCKS5 proxy"
        return False, f"proxy failed rc={proxy.returncode}"

    err = (direct.stderr or direct.stdout or "").strip().replace("\n", " ")
    return False, f"direct failed rc={direct.returncode}: {err[:220]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume Colab VRT run and notify by email.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--target-id", default="")
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--poll-sec", type=int, default=90)
    parser.add_argument("--max-hours", type=float, default=12.0)
    parser.add_argument("--drive-remote", default="gdrive", help="rclone remote name for Google Drive download step")
    parser.add_argument("--account-id", default="", help="Google account id defined in account pool (optional)")
    parser.add_argument("--account-pool", default="~/.codex/google-account-pool.json", help="Account pool JSON path")
    parser.add_argument("--allow-cpu", action="store_true", help="Allow running without GPU in Colab runtime")
    args = parser.parse_args()

    run_root = pathlib.Path(args.run_root).expanduser().resolve()
    run_dir = run_root / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "_resume_mail")
    run_dir.mkdir(parents=True, exist_ok=True)

    target_id = args.target_id or None
    deadline = time.time() + int(args.max_hours * 3600)
    while time.time() < deadline:
        try:
            target_id = choose_target_id(
                args.base_url,
                target_id,
                account_id=args.account_id,
                account_pool=args.account_pool,
                auto_open=True,
            )
            break
        except RuntimeError as exc:
            if "No Colab notebook tab found in /tabs." not in str(exc):
                raise
            if time.time() >= deadline:
                raise
            log(f"waiting for Colab notebook tab... retry in 30s ({str(exc)})")
            time.sleep(30)
            # Clear preferred target to auto-select a fresh tab if previous ID disappears.
            target_id = None
    if not target_id:
        raise RuntimeError("No Colab notebook tab found before timeout.")
    runner = ColabRunner(args.base_url, target_id, run_dir)

    if args.account_id:
        args.drive_remote = resolve_drive_remote_from_pool(pathlib.Path(args.account_pool), args.account_id)

    log(f"run_dir={run_dir}")
    log(f"target_id={target_id}")
    log(f"drive_remote={args.drive_remote}")
    step_idx = 0

    def step_name(prefix: str) -> str:
        nonlocal step_idx
        step_idx += 1
        return f"{prefix}_{step_idx}_{int(time.time())}"

    try:
        runner.ensure_runtime_connected(timeout_sec=300)
        st = probe_state(runner, step_name("probe"))

        log("validating rootfs tar (size+presence), download if needed...")
        for ensure_try in range(1, 41):
            runner.ensure_runtime_connected(timeout_sec=240)
            ensure_rootfs_tar(runner, step_name("ensure_rootfs"))
            st = probe_state(runner, step_name("probe_after_rootfs"))
            rootfs_ok = (
                int(st.get("HAS_ROOTFS", 0)) == 1
                and int(st.get("ROOTFS_BYTES", 0)) >= ROOTFS_EXPECT_BYTES
            )
            if rootfs_ok:
                break
            log(
                f"rootfs invalid after validation attempt {ensure_try}/40 "
                f"(has={st.get('HAS_ROOTFS', 0)} bytes={st.get('ROOTFS_BYTES', 0)}); "
                "runtime likely reset, retrying..."
            )
            if ensure_try < 40:
                time.sleep(3)
        rootfs_ok = (
            int(st.get("HAS_ROOTFS", 0)) == 1
            and int(st.get("ROOTFS_BYTES", 0)) >= ROOTFS_EXPECT_BYTES
        )
        if not rootfs_ok:
            raise RuntimeError(
                "invalid /content/vrt-autodl-rootfs.tar after validation "
                f"(has={st.get('HAS_ROOTFS', 0)} bytes={st.get('ROOTFS_BYTES', 0)})."
            )

        log("sync support scripts from local workspace...")
        ensure_support_scripts(runner, step_name("ensure_scripts"))

        if not st["HAS_ENV_PY"]:
            log("env python missing; start restore in background...")
            restore_attempt = 0
            max_restore_retries = 3
            start_restore_bg(runner, step_name("start_restore_bg"))
            restore_stalled_polls = 0
            while time.time() < deadline:
                runner.ensure_runtime_connected(timeout_sec=240)
                p = poll_restore_bg(runner, step_name("poll_restore_bg"))
                log(
                    f"restore poll: running={p['running']} env_py={p['env_py']} "
                    f"status={p['status']}"
                )
                if p["status"] is not None:
                    status = int(p["status"])
                    if status != 0:
                        if status == 127 and restore_attempt < max_restore_retries:
                            # A reset during background execution can lose /content scripts.
                            # Recreate support scripts and retry restore once more.
                            restore_attempt += 1
                            log(
                                f"restore returned STEP2_BG_STATUS={status}; "
                                "retrying restore after replenishing scripts"
                            )
                            ensure_support_scripts(
                                runner,
                                step_name("ensure_scripts_retry_restore"),
                            )
                            start_restore_bg(runner, step_name(f"restart_restore_bg_attempt{restore_attempt}"))
                            time.sleep(20)
                            continue
                        raise RuntimeError(f"restore failed with STEP2_BG_STATUS={status}")
                    break
                if p["running"] == 0 and p["env_py"] == 1:
                    break
                if p["running"] == 0 and p["env_py"] == 0 and p["status"] is None:
                    restore_stalled_polls += 1
                    if restore_stalled_polls >= 2:
                        log("restore appears stalled; restarting restore background task...")
                        start_restore_bg(runner, step_name("restart_restore_bg"))
                        restore_stalled_polls = 0
                else:
                    restore_stalled_polls = 0
                time.sleep(max(20, args.poll_sec))
            else:
                raise TimeoutError("restore timeout")

        # Re-probe after restore
        st = probe_state(runner, step_name("probe_after_restore"))
        if not st["HAS_ENV_PY"]:
            raise RuntimeError("env python still missing after restore.")

        if not st["HAS_BASE"]:
            log("base video missing; downloading base0211.mp4...")
            ensure_base_video(runner, step_name("ensure_base"))

        # Start step4 bg only when output does not already exist.
        st = probe_state(runner, step_name("probe_before_step4"))
        if not st["HAS_OUT"]:
            gpu = probe_gpu_state(runner, step_name("gpu_probe_before_step4"))
            log(
                "gpu probe: "
                f"cuda_available={gpu['cuda_available']} "
                f"nvidia_gpu={gpu['nvidia_gpu']} "
                f"device={gpu['device']}"
            )
            if int(gpu["ready"] or 0) != 1 and not args.allow_cpu:
                raise RuntimeError(
                    "GPU unavailable in current Colab runtime; abort before step4 "
                    "(pass --allow-cpu to override)."
                )
            log("start step4 regen in background...")
            start_step4_bg(runner, step_name("start_step4_bg"))

        step4_stalled_polls = 0
        step4_attempt = 0
        max_step4_retries = 2
        while time.time() < deadline:
            runner.ensure_runtime_connected(timeout_sec=240)
            p = poll_step4_bg(runner, step_name("poll_step4_bg"))
            log(
                f"step4 poll: running={p['running']} out={p['out_exists']} "
                f"status={p['status']} progress={p['progress']}"
            )
            if p["status"] is not None:
                status_code = int(p["status"])
                if status_code != 0:
                    if step4_attempt < max_step4_retries:
                        step4_attempt += 1
                        log(f"step4 failed with STEP4_BG_STATUS={status_code}; retrying ({step4_attempt}/{max_step4_retries})")
                        ensure_support_scripts(runner, step_name("ensure_scripts_step4_retry"))
                        start_step4_bg(runner, step_name("restart_step4_bg"))
                        step4_stalled_polls = 0
                        continue
                    raise RuntimeError(f"step4 failed with STEP4_BG_STATUS={status_code}")
                out_exists = int(p["out_exists"]) if p["out_exists"] is not None else 0
                if out_exists != 1:
                    # Fallback probe because cell-output snippets can truncate OUT_EXISTS line.
                    step4_probe = probe_state(runner, step_name("probe_after_step4_done"))
                    out_exists = int(step4_probe["HAS_OUT"])
                if out_exists != 1:
                    raise RuntimeError("step4 status=0 but output file missing.")
                break
            if p["out_exists"] == 1:
                break
            step_active = (
                p["progress"] is not None
                or p["running"] == 1
            )
            if p["status"] is None and not step_active:
                step4_stalled_polls += 1
                if step4_stalled_polls >= 2:
                    log("step4 appears stalled; restarting step4 background task...")
                    start_step4_bg(runner, step_name("restart_step4_bg"))
                    step4_stalled_polls = 0
            else:
                step4_stalled_polls = 0
            time.sleep(max(20, args.poll_sec))
        else:
            raise TimeoutError("step4 timeout")

        final = probe_state(runner, step_name("final_probe"))
        if final["HAS_OUT"] != 1:
            raise RuntimeError("final probe: output file still missing.")

        ensure_drive_mount(runner, step_name("ensure_drive_mount"), retries=4)

        # Save artifact to Drive first (required), then pull a local copy for mail attachment.
        out_name = f"output_vrt_base0211_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        drive_state = save_output_to_drive(runner, step_name("save_output_to_drive"), out_name)
        if int(drive_state.get("mounted") or 0) != 1:
            raise RuntimeError("Drive not mounted in Colab; cannot persist output to MyDrive.")
        if int(drive_state.get("saved") or 0) != 1:
            raise RuntimeError("Failed to save output video into Google Drive.")
        drive_remote_rel = f"{DRIVE_REMOTE_PREFIX}/{out_name}"
        local_out = (LOCAL_OUTPUT_DIR / out_name).resolve()
        ok_dl, dl_channel = rclone_download_from_drive(args.drive_remote, drive_remote_rel, local_out)
        if not ok_dl:
            raise RuntimeError(f"download from Drive failed: {dl_channel}")

        body = (
            "Colab GPU video regeneration completed successfully.\n"
            f"- Time: {now()}\n"
            f"- Target: {target_id}\n"
            f"- Output: {OUT_FILE}\n"
            f"- DrivePath: {drive_state.get('drive_path')}\n"
            f"- DriveRemote: {args.drive_remote}:{drive_remote_rel}\n"
            f"- LocalFile: {local_out}\n"
            f"- Download: {dl_channel}\n"
            f"- RunDir: {run_dir}\n"
        )
        ok, channel = send_email_with_fallback(body, attachments=[local_out])
        if not ok:
            raise RuntimeError(f"email send failed: {channel}")
        log(f"email sent via {channel}")
        return 0

    except Exception as exc:  # noqa: BLE001
        msg = (
            "Colab GPU video regeneration failed.\n"
            f"- Time: {now()}\n"
            f"- Target: {target_id}\n"
            f"- Error: {exc}\n"
            f"- RunDir: {run_dir}\n"
        )
        ok, channel = send_email_with_fallback(msg)
        if ok:
            log(f"failure email sent via {channel}")
        else:
            log(f"failure email send also failed: {channel}")
        log(f"fatal: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
