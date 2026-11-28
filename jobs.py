"""Read Slurm jobs over SSH. Without Slurm, the same connection reads top."""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import shlex
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import paramiko

import i18n

logging.getLogger("paramiko").setLevel(logging.WARNING)

_KEYS_LOCK = threading.Lock()
_PATH_OK = re.compile(r"[A-Za-z0-9_./:-]+")
_SQUEUE_FIELDS = ["%i", "%j", "%T", "%M", "%l", "%P", "%C", "%m", "%R", "%V", "%S", "%Z"]
_SQUEUE_FIELDS_MIN = ["%i", "%j", "%T", "%M", "%l", "%P", "%C", "%m", "%R", "%V", "%S"]
_JOB_ID = re.compile(r"[0-9]+(_\[[0-9,%-]+\]|_[0-9]+)?")
_SACCT_FIELDS = [
    "JobID",
    "JobName",
    "State",
    "Elapsed",
    "Timelimit",
    "Partition",
    "AllocCPUS",
    "ReqMem",
    "NodeList",
    "Submit",
    "Start",
    "End",
    "ExitCode",
]

STATE_ZH = {
    "RUNNING": "运行中",
    "PENDING": "排队中",
    "COMPLETED": "已完成",
    "FAILED": "失败",
    "CANCELLED": "已取消",
    "TIMEOUT": "超时",
    "NODE_FAIL": "节点失败",
    "OUT_OF_MEMORY": "内存不足",
    "PREEMPTED": "被抢占",
    "SUSPENDED": "已暂停",
    "COMPLETING": "结束中",
    "CONFIGURING": "准备中",
    "REQUEUED": "重新排队",
    "DEADLINE": "超过截止",
    "BOOT_FAIL": "启动失败",
    "REVOKED": "已撤销",
    "SPECIAL_EXIT": "特殊退出",
    "STOPPED": "已停止",
    "SIGNALING": "发送信号",
    "STAGE_OUT": "写出中",
    "RESIZING": "调整中",
}
STATE_EN = {
    "RUNNING": "Running",
    "PENDING": "Queued",
    "COMPLETED": "Done",
    "FAILED": "Failed",
    "CANCELLED": "Cancelled",
    "TIMEOUT": "Timeout",
    "NODE_FAIL": "Node fail",
    "OUT_OF_MEMORY": "Out of memory",
    "PREEMPTED": "Preempted",
    "SUSPENDED": "Suspended",
    "COMPLETING": "Completing",
    "CONFIGURING": "Configuring",
    "REQUEUED": "Requeued",
    "DEADLINE": "Deadline",
    "BOOT_FAIL": "Boot fail",
    "REVOKED": "Revoked",
    "SPECIAL_EXIT": "Special exit",
    "STOPPED": "Stopped",
    "SIGNALING": "Signaling",
    "STAGE_OUT": "Staging out",
    "RESIZING": "Resizing",
}
RUNNING_STATES = {"RUNNING", "COMPLETING", "CONFIGURING", "SIGNALING", "STAGE_OUT", "RESIZING"}
WAITING_STATES = {"PENDING", "SUSPENDED", "REQUEUED", "STOPPED"}
DONE_STATES = {"COMPLETED"}
BAD_STATES = {
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "DEADLINE",
    "BOOT_FAIL",
    "REVOKED",
    "SPECIAL_EXIT",
}

_SCRIPT = """export LC_ALL=C
@@PATH@@
if ! command -v squeue >/dev/null 2>&1; then
  for d in /sched/slurm/bin /opt/slurm/bin /usr/local/slurm/bin /opt/ohpc/pub/bin /cm/shared/apps/slurm/current/bin /usr/local/bin /usr/bin; do
    if [ -x "$d/squeue" ]; then PATH="$d:$PATH"; export PATH; break; fi
  done
fi
if ! command -v squeue >/dev/null 2>&1; then
  for f in /etc/profile.d/modules.sh /etc/profile.d/lmod.sh /usr/share/Modules/init/bash; do
    if [ -r "$f" ]; then . "$f" >/dev/null 2>&1 || true; fi
  done
  if command -v module >/dev/null 2>&1; then
    module load slurm >/dev/null 2>&1 || module load slurm/latest >/dev/null 2>&1 || true
  fi
fi
echo __BEGIN__
USER_NAME="${USER:-$(id -un)}"
echo __PROC__
ps -u "$USER_NAME" -o pid=,ppid=,stat=,etime=,pcpu=,pmem=,args= 2>/dev/null
echo __META__
for f in "$HOME"/.jobdesk/jobs/*.meta; do
  [ -r "$f" ] || continue
  echo "@@FILE@@ $f"
  cat "$f" 2>/dev/null
done
if ! command -v squeue >/dev/null 2>&1; then
  echo __MISSING_SQUEUE__
  echo __TOP__
  if command -v top >/dev/null 2>&1; then
    top -b -n 1 2>&1 | head -n 40
  else
    echo "找不到 top"
  fi
  echo __TOP_END__
  echo __END__
  exit 0
fi
echo __SQUEUE__
exec 3>&1
USER_NAME="${USER:-$(id -un)}"
squeue_err=$(squeue -u "$USER_NAME" -h --format='@@FORMAT@@' 2>&1 1>&3)
squeue_rc=$?
if [ "$squeue_rc" -ne 0 ]; then
  echo __SQUEUE_MIN__
  squeue_err=$(squeue -u "$USER_NAME" -h --format='@@FORMAT_MIN@@' 2>&1 1>&3)
  squeue_rc=$?
fi
printf '%s\\n' "__SQUEUE_RC__${squeue_rc}"
if [ -n "$squeue_err" ]; then
  echo __SQUEUE_ERR_BEGIN__
  printf '%s\\n' "$squeue_err"
  echo __SQUEUE_ERR_END__
fi
echo __SACCT__
if ! command -v sacct >/dev/null 2>&1; then
  echo __MISSING_SACCT__
  echo __END__
  exit 0
fi
sacct_err=$(sacct -u "$USER_NAME" -S "now-@@DAYS@@days" -n -X -P --format=@@SACCT@@ 2>&1 1>&3)
sacct_rc=$?
if [ "$sacct_rc" -ne 0 ]; then
  sacct_err=$(sacct -u "$USER_NAME" -n -X -P --format=@@SACCT@@ 2>&1 1>&3)
  sacct_rc=$?
fi
printf '%s\\n' "__SACCT_RC__${sacct_rc}"
if [ -n "$sacct_err" ]; then
  echo __SACCT_ERR_BEGIN__
  printf '%s\\n' "$sacct_err"
  echo __SACCT_ERR_END__
fi
echo __END__
exit 0
"""

_TOP_SCRIPT = """export LC_ALL=C
echo __BEGIN__
echo __TOP__
if command -v top >/dev/null 2>&1; then
  top -b -n 1 2>&1 | head -n 40
else
  echo "找不到 top"
fi
echo __TOP_END__
echo __END__
exit 0
"""


@dataclass
class Job:
    job_id: str
    name: str
    state: str
    elapsed: str
    timelimit: str
    partition: str
    cpus: str
    memory: str
    place: str
    submit: str
    start: str
    end: str
    exit_code: str
    source: str
    workdir: str = ""
    account_id: str = ""
    account_label: str = ""
    username: str = ""
    host: str = ""
    port: int = 22


@dataclass
class AccountResult:
    label: str
    username: str
    host: str
    port: int
    jobs: list[Job] = field(default_factory=list)
    error: str = ""
    notice: str = ""
    fingerprint: str = ""
    top_text: str = ""
    account_id: str = ""


@dataclass
class Parsed:
    missing_squeue: bool = False
    missing_sacct: bool = False
    squeue_min: bool = False
    squeue_jobs: list[Job] = field(default_factory=list)
    sacct_jobs: list[Job] = field(default_factory=list)
    squeue_rc: int | None = None
    sacct_rc: int | None = None
    squeue_err: str = ""
    sacct_err: str = ""
    top_text: str = ""
    proc_text: str = ""


class _RememberKey(paramiko.MissingHostKeyPolicy):
    def __init__(self) -> None:
        self.added: list[tuple[str, str, paramiko.PKey]] = []

    def missing_host_key(self, client, hostname, key):
        client.get_host_keys().add(hostname, key.get_name(), key)
        self.added.append((hostname, key.get_name(), key))


def base_state(state: str) -> str:
    token = (state or "").strip().split(" ", 1)[0]
    return token.rstrip("+")


def state_text(state: str) -> str:
    raw = (state or "").strip()
    if not raw:
        return i18n.tr("未知")
    base = base_state(raw)
    table = STATE_EN if i18n.language.english else STATE_ZH
    zh = table.get(base)
    if not zh:
        return raw
    rest = raw[len(base):].strip(" +") if raw.startswith(base) else ""
    return f"{zh} {rest}".strip()


def kind(state: str) -> str:
    base = base_state(state)
    if base in RUNNING_STATES:
        return "run"
    if base in WAITING_STATES:
        return "wait"
    if base in DONE_STATES:
        return "done"
    if base in BAD_STATES:
        return "bad"
    return "other"


def job_key(job: Job) -> str:
    return f"{job.account_id}:{job.job_id}"


def job_bucket(job: Job) -> str:
    return kind(job.state)


def finished_since(previous: dict[str, str], jobs: list[Job]) -> list[Job]:
    """Jobs that were running or queued last time and have now finished.

    An empty previous snapshot is the baseline: historical finished jobs
    are not treated as new.
    """
    if not previous:
        return []
    busy = {"active", "run", "wait", "other"}
    found = []
    for job in jobs:
        if previous.get(job_key(job)) in busy and job_bucket(job) in {"done", "bad"}:
            found.append(job)
    return found


def next_buckets(previous: dict[str, str], jobs: list[Job], limit: int = 2000) -> dict[str, str]:
    updated = dict(previous)
    for job in jobs:
        updated[job_key(job)] = job_bucket(job)
    if len(updated) <= limit:
        return updated
    current = {job_key(job) for job in jobs}
    kept = {key: value for key, value in updated.items() if key in current or value in {"active", "run", "wait", "other"}}
    if len(kept) > limit:
        kept = dict(list(kept.items())[-limit:])
    return kept


def elapsed_seconds(text: str) -> int:
    raw = (text or "").strip()
    if not raw or raw.upper() in {"UNLIMITED", "INVALID", "UNKNOWN", "N/A", "NONE"}:
        return -1
    try:
        days = 0
        clock = raw
        if "-" in clock:
            day_text, clock = clock.split("-", 1)
            days = int(day_text)
        parts = [int(part) for part in clock.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        hours, minutes, seconds = parts[-3:]
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    except ValueError:
        return -1


def duration_text(seconds: int) -> str:
    """Short duration for the queue wait."""
    if seconds is None or seconds < 0:
        return ""
    english = i18n.language.english
    if seconds < 60:
        return f"{seconds}s" if english else f"{seconds}秒"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m" if english else f"{minutes}分"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if english:
            return f"{hours}h{minutes}m" if minutes else f"{hours}h"
        return f"{hours}小时{minutes}分" if minutes else f"{hours}小时"
    days, hours = divmod(hours, 24)
    if english:
        return f"{days}d{hours}h" if hours else f"{days}d"
    return f"{days}天{hours}小时" if hours else f"{days}天"


def queue_seconds(job: "Job") -> int:
    """How long a pending job has been waiting, counted from its submit time."""
    if kind(job.state) != "wait":
        return -1
    text = (job.submit or "").strip()
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", text)
    if not match:
        return -1
    try:
        when = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6) or 0),
        )
    except ValueError:
        return -1
    seconds = int((datetime.now() - when).total_seconds())
    if seconds < 0 or seconds > 60 * 86400:
        return -1
    return seconds


def queue_text(job: "Job") -> str:
    return duration_text(queue_seconds(job))


def short_time(value: str) -> str:
    text = (value or "").strip()
    if text.lower() in {"", "unknown", "n/a", "none", "invalid"}:
        return ""
    text = text.replace("T", " ")
    match = re.match(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})", text)
    if match:
        return f"{match.group(2)}-{match.group(3)} {match.group(4)}:{match.group(5)}"
    return text


def one_line(text: str, limit: int = 240) -> str:
    flat = " ".join((text or "").split())
    if len(flat) > limit:
        return flat[:limit] + "…"
    return flat


def build_script(extra_path: str, days: int) -> tuple[str, str]:
    notice = ""
    path = (extra_path or "").strip()
    if path and _PATH_OK.fullmatch(path) is None:
        notice = "附加 PATH 含有空格或特殊符号，这次没有使用。"
        path = ""
    days = max(1, min(30, int(days)))
    path_line = f'export PATH="{path}:$PATH"' if path else ""
    script = (
        _SCRIPT.replace("@@PATH@@", path_line)
        .replace("@@DAYS@@", str(days))
        .replace("@@FORMAT@@", "\x1f".join(_SQUEUE_FIELDS))
        .replace("@@FORMAT_MIN@@", "\x1f".join(_SQUEUE_FIELDS_MIN))
        .replace("@@SACCT@@", ",".join(_SACCT_FIELDS))
    )
    return script, notice


def parse_query(text: str) -> Parsed:
    parsed = Parsed(missing_squeue="__MISSING_SQUEUE__" in text, missing_sacct="__MISSING_SACCT__" in text)
    parsed.squeue_min = "__SQUEUE_MIN__" in text
    parsed.squeue_rc = _marked_int(text, "__SQUEUE_RC__")
    parsed.sacct_rc = _marked_int(text, "__SACCT_RC__")
    parsed.squeue_err = _marked_block(text, "__SQUEUE_ERR_BEGIN__", "__SQUEUE_ERR_END__")
    parsed.sacct_err = _marked_block(text, "__SACCT_ERR_BEGIN__", "__SACCT_ERR_END__")
    parsed.top_text = _between(text, "__TOP__", ["__TOP_END__", "__END__"]).strip()[:8000]
    if "__PROC__" in text:
        parsed.proc_text = "__PROC__\n" + _between(text, "__PROC__", ["__END__"]).strip()
    squeue_body = _between(text, "__SQUEUE__", ["__SQUEUE_RC__", "__SACCT__", "__END__"])
    sacct_body = _between(text, "__SACCT__", ["__SACCT_RC__", "__MISSING_SACCT__", "__SACCT_ERR_BEGIN__", "__END__"])
    width = len(_SQUEUE_FIELDS_MIN) if parsed.squeue_min else len(_SQUEUE_FIELDS)
    for line in squeue_body.splitlines():
        fields = _split_fields(line, width, "\x1f")
        if fields and fields[0]:
            parsed.squeue_jobs.append(_job_from_squeue(fields, with_workdir=not parsed.squeue_min))
    for line in sacct_body.splitlines():
        fields = _split_fields(line, len(_SACCT_FIELDS), "|")
        if not fields or not fields[0] or "." in fields[0]:
            continue
        parsed.sacct_jobs.append(_job_from_sacct(fields))
    return parsed


def interpret(parsed: Parsed) -> tuple[list[Job], str, str]:
    if parsed.missing_squeue:
        jobs = parse_proc(parsed.proc_text) if parsed.proc_text else []
        if jobs:
            return jobs, "", "这台机器没有作业系统，按进程显示（作业号就是 PID）。"
        if parsed.top_text:
            return [], "", "这台机器没有作业系统，已改看 top。"
        return [], "找不到 squeue。这台机器可能不是 Slurm，或附加 PATH 不对。", ""
    if parsed.squeue_rc not in (None, 0) and not parsed.squeue_jobs:
        message = one_line(parsed.squeue_err) or f"squeue 退出码 {parsed.squeue_rc}"
        return [], f"读取队列失败：{message}", ""
    notices = []
    if parsed.squeue_err.strip():
        notices.append(one_line(parsed.squeue_err, 180))
    if parsed.missing_sacct:
        notices.append("没有 sacct，已结束的作业不会出现。")
    elif parsed.sacct_rc not in (None, 0):
        message = one_line(parsed.sacct_err, 180) or f"退出码 {parsed.sacct_rc}"
        notices.append(f"已结束作业没读到：{message}")
    merged = merge_jobs(parsed.squeue_jobs, parsed.sacct_jobs)
    if parsed.proc_text:
        proc_jobs = parse_proc(parsed.proc_text)
        known = {job.job_id for job in merged}
        extra = [job for job in proc_jobs if job.job_id not in known]
        if extra:
            merged.extend(extra)
            notices.append(f"另有 {len(extra)} 个进程任务（nohup）。")
    return merged, "", " ".join(notices)

def merge_jobs(squeue_jobs: list[Job], sacct_jobs: list[Job]) -> list[Job]:
    packed = [job.job_id.split("_[", 1)[0] + "_" for job in squeue_jobs if "_[" in job.job_id]
    kept: list[Job] = []
    for job in sacct_jobs:
        if any(re.fullmatch(re.escape(prefix) + r"\d+", job.job_id) for prefix in packed):
            continue
        kept.append(job)
    by_id = {job.job_id: job for job in kept}
    for job in squeue_jobs:
        old = by_id.get(job.job_id)
        if old is not None:
            job.submit = job.submit or old.submit
            job.start = job.start or old.start
            job.end = old.end
            job.exit_code = old.exit_code
            job.timelimit = job.timelimit or old.timelimit
            job.cpus = job.cpus or old.cpus
            job.memory = job.memory or old.memory
        by_id[job.job_id] = job
    return list(by_id.values())


def _account_result(account: dict) -> AccountResult:
    label = (account.get("label") or account.get("username") or "账号").strip()
    username = (account.get("username") or "").strip()
    host = (account.get("host") or "").strip()
    try:
        port = int(account.get("port") or 22)
    except (TypeError, ValueError):
        port = 22
    return AccountResult(label=label, username=username, host=host, port=port, account_id=str(account.get("id") or ""))


def _open_client(result: AccountResult, password: str, known_hosts: Path) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    policy = _RememberKey()
    client.set_missing_host_key_policy(policy)
    try:
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        if not known_hosts.exists():
            known_hosts.write_text("", encoding="utf-8")
        client.load_host_keys(str(known_hosts))
        # paramiko turns a non-default port into "[host]:port" for both the lookup and
        # the missing-key callback (client.py), so one entry per (host, port) is kept.
        client.connect(
            hostname=result.host,
            port=result.port,
            username=result.username,
            password=password,
            timeout=15,
            banner_timeout=25,
            auth_timeout=25,
            look_for_keys=False,
            allow_agent=False,
        )
        return client
    finally:
        _merge_new_keys(known_hosts, policy.added)


def _run_account_script(account: dict, password: str, known_hosts: Path, script: str) -> tuple[AccountResult, str, str]:
    result = _account_result(account)
    if not password:
        result.error = "还没有填写密码。"
        return result, "", ""
    if not result.host or not result.username:
        result.error = "主机或用户名是空的。"
        return result, "", ""
    output = ""
    error = ""
    client = None
    try:
        client = _open_client(result, password, known_hosts)
        result.fingerprint = _fingerprint(client)
        _code, output, error = _run_script(client, script)
    except Exception as exc:
        result.error = explain_connect_error(exc)
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return result, output, error


def cd_command(workdir: str) -> str:
    path = (workdir or "").strip()
    if not path.startswith("/") or any(char in path for char in "\n\r\x00"):
        return ""
    return "cd -- " + shlex.quote(path) + "\n"


def lookup_workdir(client: paramiko.SSHClient, job_id: str) -> str:
    if _JOB_ID.fullmatch(job_id or "") is None:
        return ""
    _stdin, stdout, _stderr = client.exec_command("squeue -h -j " + shlex.quote(job_id) + " -o %Z", timeout=20)
    stdout.channel.settimeout(20)
    raw = stdout.read().decode("utf-8", "replace")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    path = lines[-1]
    if path.lower() in {"n/a", "none", "unknown"} or not path.startswith("/"):
        return ""
    if any(char in path for char in "\n\r\x00"):
        return ""
    return path


def connect_account(account: dict, password: str, known_hosts: Path) -> paramiko.SSHClient:
    result = _account_result(account)
    if not password:
        raise OSError("还没有填写密码。")
    if not result.host or not result.username:
        raise OSError("主机或用户名是空的。")
    return _open_client(result, password, known_hosts)


_PROC_SCRIPT = """export LC_ALL=C
USER_NAME="${USER:-$(id -un)}"
echo __BEGIN__
echo __PROC__
ps -u "$USER_NAME" -o pid=,stat=,etime=,pcpu=,pmem=,args= 2>/dev/null
echo __META__
for f in "$HOME"/.jobdesk/jobs/*.meta; do
  [ -r "$f" ] || continue
  echo "@@FILE@@ $f"
  cat "$f" 2>/dev/null
done
echo __END__
"""

_NOISE = (
    "bash", "zsh", "sh", "ssh", "sshd", "sftp-server", "ps", "top", "htop", "vim", "vi", "nano",
    "tmux", "screen", "less", "more", "tail", "watch", "grep", "awk", "sed", "cat", "ls", "man",
    "jobdesk", "sleep",
)


def _etime_seconds(text: str) -> int:
    """Parse ps etime: SS, MM:SS, HH:MM:SS or D-HH:MM:SS."""
    value = (text or "").strip()
    if not value:
        return 0
    days = 0
    if "-" in value:
        head, value = value.split("-", 1)
        try:
            days = int(head)
        except ValueError:
            days = 0
    parts = value.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0
    if len(numbers) == 3:
        return days * 86400 + numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    if len(numbers) == 2:
        return days * 86400 + numbers[0] * 60 + numbers[1]
    if len(numbers) == 1:
        return days * 86400 + numbers[0]
    return 0


def _is_noise(command: str) -> bool:
    text = command.strip()
    if not text:
        return True
    if text.startswith("bash --noprofile --norc -s"):
        return True
    first = text.split()[0].split("/")[-1]
    if first in _NOISE:
        return True
    return False


def build_proc_script(keyword: str = "") -> str:
    return _PROC_SCRIPT


def parse_proc(text: str) -> list[Job]:
    """Turn `ps` output plus jd metadata into jobs (running + finished)."""
    section = "proc"
    jobs: list[Job] = []
    seen: set[str] = set()
    meta: dict[str, dict] = {}
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line == "__PROC__":
            section = "proc"
            continue
        if line == "__META__":
            section = "meta"
            continue
        if line == "__END__":
            break
        if section == "proc":
            parts = line.split(None, 6)
            if len(parts) < 7:
                continue
            pid, ppid, stat, etime, pcpu, pmem, command = parts
            if _is_noise(command) or stat.startswith("Z"):
                continue
            if _etime_seconds(etime) < 60:
                continue
            seen.add(pid)
            jobs.append(
                Job(
                    job_id=pid,
                    name=one_line(command, 80),
                    state="RUNNING",
                    elapsed=etime,
                    timelimit="",
                    partition="进程",
                    cpus="-",
                    memory=f"{pmem}%",
                    place=ppid,
                    submit="",
                    start="",
                    end="",
                    exit_code="",
                    source="process",
                    workdir="",
                )
            )
        elif section == "meta":
            if line.startswith("@@FILE@@ "):
                if current:
                    meta[current.get("pid", "")] = current
                current = {}
                continue
            if current is None:
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                current[key.strip()] = value.strip()
    if current:
        meta[current.get("pid", "")] = current

    slurm_pids = {
        job.job_id
        for job in jobs
        if any(word in job.name.lower() for word in ("slurm", "srun", "sbatch", "squeue"))
    }
    jobs = [
        job
        for job in jobs
        if job.partition != "进程"
        or (job.place not in slurm_pids and not any(word in job.name.lower() for word in ("slurm", "srun", "sbatch")))
    ]

    for pid, info in meta.items():
        if not pid or pid in seen:
            continue
        try:
            start = int(info.get("start") or 0)
            end = int(info.get("end") or 0)
            code = int(info.get("code") or -1)
        except ValueError:
            continue
        if end <= 0:
            continue
        seconds = max(0, end - start)
        jobs.append(
            Job(
                job_id=pid,
                name=one_line(info.get("cmd") or "jd 任务", 80),
                state="COMPLETED" if code == 0 else "FAILED",
                elapsed=duration_text(seconds),
                timelimit="",
                partition="进程",
                cpus="-",
                memory="-",
                place="-",
                submit="",
                start="",
                end="",
                exit_code=str(code),
                source="process",
                workdir="",
            )
        )
    return jobs


def query_process(account: dict, password: str, known_hosts: Path) -> AccountResult:
    keyword = str(account.get("proc_filter") or "").strip().lower()
    result, output, error = _run_account_script(account, password, known_hosts, build_proc_script(keyword))
    if result.error:
        return result
    if "__BEGIN__" not in output:
        result.error = "远程命令没有跑起来。" + (f" {one_line(error or output)}" if error or output else "")
        return result
    jobs = parse_proc(output)
    if keyword:
        words = [word.strip() for word in keyword.split(",") if word.strip()]
        jobs = [job for job in jobs if any(word in job.name.lower() for word in words)]
    for job in jobs:
        job.account_id = str(account.get("id") or "")
        job.account_label = result.label
        job.username = result.username
        job.host = result.host
        job.port = result.port
    result.jobs = jobs
    if not keyword:
        result.notice = "进程模式：显示该用户全部进程（已过滤 shell 等噪音）。"
    return result


JD_SCRIPT = """#!/usr/bin/env bash
# jd - Job Desk 包装器：记录退出码，让桌面端能区分「跑完」和「跑挂」。
# 用法: jd run python train.py --epochs 100
set -u
if [ "${1:-}" = "run" ]; then shift; fi
if [ "$#" -eq 0 ]; then echo "用法: jd run <命令> [参数...]" >&2; exit 2; fi
DIR="$HOME/.jobdesk/jobs"; mkdir -p "$DIR"
START=$(date +%s)
"$@" &
CHILD=$!
FILE="$DIR/$CHILD.meta"
printf 'pid=%s\\nstart=%s\\nend=0\\ncode=-1\\ncmd=%s\\n' "$CHILD" "$START" "$*" > "$FILE"
wait "$CHILD"
CODE=$?
printf 'pid=%s\\nstart=%s\\nend=%s\\ncode=%s\\ncmd=%s\\n' "$CHILD" "$START" "$(date +%s)" "$CODE" "$*" > "$FILE"
exit "$CODE"
"""


def install_jd(account: dict, password: str, known_hosts: Path) -> str:
    """Upload the jd wrapper to ~/.local/bin/jd on the server."""
    client = connect_account(account, password, known_hosts)
    try:
        sftp = client.open_sftp()
        try:
            script = "mkdir -p \"$HOME/.local/bin\" && cat > \"$HOME/.local/bin/jd\" && chmod +x \"$HOME/.local/bin/jd\" && echo __JD_OK__"
            _stdin, stdout, stderr = client.exec_command(f"bash -c {shlex.quote(script)}", timeout=30)
            _stdin.write(JD_SCRIPT)
            _stdin.channel.shutdown_write()
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
        finally:
            sftp.close()
    finally:
        client.close()
    if "__JD_OK__" not in out:
        raise RuntimeError(one_line(err or out) or "上传失败")
    return "$HOME/.local/bin/jd"


def query_account(account: dict, password: str, history_days: int, known_hosts: Path) -> AccountResult:
    if str(account.get("scheduler") or "slurm") == "process":
        return query_process(account, password, known_hosts)
    script, path_notice = build_script(str(account.get("extra_path") or ""), history_days)
    result, output, error = _run_account_script(account, password, known_hosts, script)
    if result.error:
        return result
    if "__BEGIN__" not in output:
        extra = one_line(error or output)
        result.error = "远程命令没有跑起来。" + (f" {extra}" if extra else "")
        return result
    parsed = parse_query(output)
    jobs, error_text, notice = interpret(parsed)
    result.top_text = parsed.top_text
    for job in jobs:
        job.account_id = str(account.get("id") or "")
        job.account_label = result.label
        job.username = result.username
        job.host = result.host
        job.port = result.port
    result.jobs = jobs
    result.error = error_text
    notes = [part for part in (path_notice, notice) if part]
    result.notice = " ".join(notes)
    return result


def query_top(account: dict, password: str, known_hosts: Path) -> AccountResult:
    result, output, error = _run_account_script(account, password, known_hosts, _TOP_SCRIPT)
    if result.error:
        return result
    if "__BEGIN__" not in output:
        extra = one_line(error or output)
        result.error = "top 没有跑起来。" + (f" {extra}" if extra else "")
        return result
    result.top_text = parse_query(output).top_text or "top 没有输出。"
    return result


def explain_connect_error(exc: Exception) -> str:
    if isinstance(exc, paramiko.AuthenticationException):
        return "账号或密码不对，或这台机器不允许用密码登录。"
    if isinstance(exc, paramiko.BadHostKeyException):
        return "主机密钥和上次不一致。请打开「账号」，点「清除此主机旧密钥」后再试。如果这不是你平时连的那台机器，不要继续。"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "连接或读取超时。请检查主机、端口和网络。"
    if isinstance(exc, socket.gaierror):
        return "无法解析这个主机名。"
    text = one_line(str(exc))
    if isinstance(exc, paramiko.SSHException):
        return f"SSH 失败：{text}" if text else "SSH 失败。"
    if isinstance(exc, OSError):
        return f"连不上：{text}" if text else "连不上这台机器。"
    return f"连接失败：{text}" if text else "连接失败。"


def forget_host_key(known_hosts: Path, host: str, port: int) -> int:
    host = (host or "").strip()
    names = {host, f"[{host}]:{int(port)}"}
    if not host or not known_hosts.exists():
        return 0
    with _KEYS_LOCK:
        keys = paramiko.HostKeys()
        keys.load(str(known_hosts))
        removed = 0
        for name in list(keys.keys()):
            if name not in names:
                continue
            for _ in range(8):
                try:
                    del keys[name]
                    removed += 1
                except KeyError:
                    break
        _save_keys(keys, known_hosts)
    return removed


def _run_script(client: paramiko.SSHClient, script: str) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command("bash --noprofile --norc -s", timeout=60, get_pty=False)
    stdin.write(script)
    stdin.flush()
    stdin.channel.shutdown_write()
    stdout.channel.settimeout(60)
    try:
        out_bytes = stdout.read()
        err_bytes = stderr.read()
        code = stdout.channel.recv_exit_status()
    except socket.timeout as exc:
        raise TimeoutError("读取作业状态超时") from exc
    return code, out_bytes.decode("utf-8", "replace"), err_bytes.decode("utf-8", "replace")


def _fingerprint(client: paramiko.SSHClient) -> str:
    transport = client.get_transport()
    if transport is None:
        return ""
    key = transport.get_remote_server_key()
    raw = key.asbytes() if hasattr(key, "asbytes") else base64.b64decode(key.get_base64())
    digest = base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii").rstrip("=")
    return "SHA256:" + digest


def _merge_new_keys(path: Path, added: list[tuple[str, str, paramiko.PKey]]) -> None:
    if not added:
        return
    with _KEYS_LOCK:
        keys = paramiko.HostKeys()
        if path.exists() and path.stat().st_size:
            keys.load(str(path))
        for hostname, keytype, key in added:
            keys.add(hostname, keytype, key)
        _save_keys(keys, path)


def _save_keys(keys: paramiko.HostKeys, path: Path) -> None:
    temporary = path.with_suffix(".tmp")
    keys.save(str(temporary))
    temporary.replace(path)


def _between(text: str, start: str, ends: list[str]) -> str:
    begin = text.find(start)
    if begin < 0:
        return ""
    begin += len(start)
    if text[begin:begin + 1] == "\n":
        begin += 1
    positions = [text.find(marker, begin) for marker in ends]
    positions = [pos for pos in positions if pos >= 0]
    end = min(positions) if positions else len(text)
    return text[begin:end]


def _marked_int(text: str, marker: str) -> int | None:
    match = re.search(re.escape(marker) + r"(-?\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def _marked_block(text: str, start: str, end: str) -> str:
    match = re.search(re.escape(start) + r"\n?(.*?)" + re.escape(end), text, re.S)
    return match.group(1).strip() if match else ""


def _split_fields(line: str, count: int, separator: str) -> list[str] | None:
    text = line.strip("\r\n")
    if not text or text.startswith("__"):
        return None
    parts = text.split(separator)
    if separator == "|" and parts and parts[-1] == "" and len(parts) > count:
        parts = parts[:-1]
    if len(parts) < count:
        return None
    if len(parts) > count:
        extra = len(parts) - count
        name = separator.join(parts[1:2 + extra])
        parts = [parts[0], name, *parts[2 + extra:]]
    return parts[:count]


def _blank(value: str) -> str:
    text = (value or "").strip()
    if text.lower() in {"none", "n/a", "unknown", "null", "invalid"}:
        return ""
    return text


def _job_from_squeue(fields: list[str], with_workdir: bool = True) -> Job:
    workdir = ""
    if with_workdir and len(fields) > 11:
        workdir = _blank(fields[11]) if fields[11].strip().startswith("/") else ""
    return Job(
        job_id=fields[0].strip(),
        name=fields[1].strip(),
        state=fields[2].strip(),
        elapsed=_blank(fields[3]),
        timelimit=_blank(fields[4]),
        partition=fields[5].strip(),
        cpus=fields[6].strip(),
        memory=fields[7].strip(),
        place=_blank(fields[8]),
        submit=_blank(fields[9]),
        start=_blank(fields[10]),
        end="",
        exit_code="",
        source="squeue",
        workdir=workdir,
    )


def _job_from_sacct(fields: list[str]) -> Job:
    return Job(
        job_id=fields[0].strip(),
        name=fields[1].strip(),
        state=fields[2].strip(),
        elapsed=_blank(fields[3]),
        timelimit=_blank(fields[4]),
        partition=fields[5].strip(),
        cpus=fields[6].strip(),
        memory=fields[7].strip(),
        place=_blank(fields[8]),
        submit=_blank(fields[9]),
        start=_blank(fields[10]),
        end=_blank(fields[11]),
        exit_code=_blank(fields[12]),
        source="sacct",
    )


def _self_test() -> None:
    sample = "\n".join(
        [
            "__BEGIN__",
            "__SQUEUE__",
            "\x1f".join(
                [
                    "1001",
                    "job_a",
                    "RUNNING",
                    "1:02:03",
                    "1-00:00:00",
                    "HPC-HT",
                    "32",
                    "500G",
                    "node1",
                    "2026-11-10T08:00:00",
                    "2026-11-10T08:01:00",
                    "/data/job_a",
                ]
            ),
            "\x1f".join(
                [
                    "2000_[1-2]",
                    "arr",
                    "PENDING",
                    "0:00",
                    "2:00:00",
                    "HPC-HT",
                    "4",
                    "8G",
                    "Resources",
                    "2026-11-10T09:00:00",
                    "N/A",
                    "N/A",
                ]
            ),
            "__SQUEUE_RC__0",
            "__SACCT__",
            "|".join(
                [
                    "1001",
                    "job_a",
                    "RUNNING",
                    "01:02:03",
                    "1-00:00:00",
                    "HPC-HT",
                    "32",
                    "500G",
                    "node1",
                    "2026-11-10T08:00:00",
                    "2026-11-10T08:01:00",
                    "Unknown",
                    "0:0",
                ]
            ),
            "|".join(
                [
                    "1002",
                    "done",
                    "COMPLETED",
                    "00:30:00",
                    "01:00:00",
                    "HPC-HT",
                    "8",
                    "16G",
                    "node2",
                    "2026-11-09T01:00:00",
                    "2026-11-09T01:00:05",
                    "2026-11-09T01:30:05",
                    "0:0",
                ]
            ),
            "|".join(
                [
                    "1003",
                    "a",
                    "b name",
                    "FAILED",
                    "00:01:00",
                    "01:00:00",
                    "HPC-HT",
                    "1",
                    "1G",
                    "None",
                    "2026-11-09T02:00:00",
                    "2026-11-09T02:00:01",
                    "2026-11-09T02:01:01",
                    "1:0",
                ]
            ),
            "|".join(
                [
                    "2000_1",
                    "arr",
                    "PENDING",
                    "00:00:00",
                    "02:00:00",
                    "HPC-HT",
                    "4",
                    "8G",
                    "None",
                    "2026-11-10T09:00:00",
                    "Unknown",
                    "Unknown",
                    "0:0",
                ]
            ),
            "__SACCT_RC__0",
            "__END__",
        ]
    )
    jobs, error, notice = interpret(parse_query(sample))
    assert error == "" and notice == "", (error, notice)
    by_id = {job.job_id: job for job in jobs}
    assert set(by_id) == {"1001", "1002", "1003", "2000_[1-2]"}, set(by_id)
    assert by_id["1001"].place == "node1"
    assert by_id["1001"].source == "squeue"
    assert by_id["1001"].workdir == "/data/job_a"
    assert cd_command("/data/a b") == "cd -- '/data/a b'\n"
    assert cd_command("relative") == ""
    assert cd_command("/tmp/a\nb") == ""
    assert by_id["1001"].end == ""
    assert by_id["1003"].name == "a|b name"
    assert by_id["1003"].place == ""
    assert state_text("CANCELLED by 9") == "已取消 by 9"
    assert elapsed_seconds("1-02:03:04") == 86400 + 2 * 3600 + 3 * 60 + 4
    assert short_time("2026-11-10T08:01:00") == "11-10 08:01"
    empty, missing_error, _missing_notice = interpret(parse_query("__BEGIN__\n__MISSING_SQUEUE__\n"))
    assert empty == [] and "squeue" in missing_error
    topped = parse_query("__BEGIN__\n__MISSING_SQUEUE__\n__TOP__\nPID USER\n__TOP_END__\n__END__\n")
    top_jobs, top_error, top_notice = interpret(topped)
    assert top_jobs == [] and top_error == "" and "top" in top_notice and "PID USER" in topped.top_text
    script, path_notice = build_script("/sched/slurm/bin", 3)
    assert "/sched/slurm/bin" in script and "squeue" in script and "sacct" in script
    assert "sbatch" not in script and "scancel" not in script
    bad_script, bad_notice = build_script("/tmp;rm -rf /", 3)
    assert "/tmp" not in bad_script and "rm -rf" not in bad_script and bad_notice
    assert "printf '%s\\n' \"__SQUEUE_RC__${squeue_rc}\"" in script
    assert "sbatch" not in bad_script and "scancel" not in bad_script
    running = Job("1", "run", "RUNNING", "", "", "", "", "", "", "", "", "", "", "squeue", account_id="a")
    done = Job("1", "run", "COMPLETED", "", "", "", "", "", "", "", "", "", "", "sacct", account_id="a")
    assert finished_since({}, [done]) == []
    assert [item.job_id for item in finished_since({"a:1": "active"}, [done])] == ["1"]
    assert finished_since({"a:1": "done"}, [done]) == []
    assert finished_since({"a:1": "active"}, [running]) == []
    failed = Job("1", "run", "FAILED", "", "", "", "", "", "", "", "", "", "", "sacct", account_id="a")
    assert [item.job_id for item in finished_since({"a:1": "run"}, [done])] == ["1"]
    assert [item.job_id for item in finished_since({"a:1": "wait"}, [failed])] == ["1"]
    assert next_buckets({"a:1": "active"}, [done])["a:1"] == "done"
    result = _account_result({"id": "abc", "label": "L", "username": "u", "host": "h", "port": 22})
    assert result.account_id == "abc" and result.port == 22
    assert duration_text(45) == "45秒"
    assert duration_text(90) == "1分"
    assert duration_text(3700) == "1小时1分"
    assert duration_text(90000) == "1天1小时"
    waiting = Job("7", "q", "PENDING", "", "", "", "", "", "", datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "", "", "", "squeue", account_id="a")
    assert queue_seconds(waiting) >= 0
    assert queue_text(waiting).endswith(("秒", "分"))
    assert queue_text(done) == ""
    assert "/opt/slurm/bin" in script and "now-3days" in script
    minimal = "\n".join(
        [
            "__BEGIN__",
            "__SQUEUE__",
            "__SQUEUE_MIN__",
            "\x1f".join(
                [
                    "7",
                    "minjob",
                    "RUNNING",
                    "0:10",
                    "1:00:00",
                    "HPC",
                    "2",
                    "4G",
                    "node9",
                    "2026-11-10T08:00:00",
                    "2026-11-10T08:00:05",
                ]
            ),
            "__SQUEUE_RC__0",
            "__SACCT__",
            "__MISSING_SACCT__",
            "__END__",
        ]
    )
    mini = parse_query(minimal)
    assert mini.squeue_min and len(mini.squeue_jobs) == 1, mini.squeue_jobs
    assert mini.squeue_jobs[0].workdir == "" and mini.squeue_jobs[0].job_id == "7"
    print("jobs self-test ok", len(jobs))


if __name__ == "__main__":
    _self_test()
