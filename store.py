"""Account list and preferences. Passwords are DPAPI blobs, not plain text."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from winsecret import SecretError, protect, unprotect


def _valid_day(text: str) -> bool:
    if not text:
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _fill_plan_seq(raw: list) -> bool:
    """Give older notes smaller numbers. Later notes keep a larger number."""
    next_seq = 1
    missing = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        seq = item.get("seq")
        if isinstance(seq, int) and seq > 0:
            next_seq = max(next_seq, seq + 1)
        else:
            missing.append(item)
    if not missing:
        return False
    missing.sort(key=lambda item: (str(item.get("created") or ""), str(item.get("id") or "")))
    for item in missing:
        item["seq"] = next_seq
        next_seq += 1
    return True


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "LinuxJobDesk"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def users_path() -> Path:
    return data_dir() / "users.json"


def _read_users() -> dict:
    path = users_path()
    empty = {"last": "", "users": []}
    if not path.exists():
        return empty
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(raw, dict):
        return empty
    raw.setdefault("last", "")
    if not isinstance(raw.get("users"), list):
        raw["users"] = []
    return raw


def _write_users(data: dict) -> None:
    users_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def user_folder(user_id: str) -> Path:
    folder = data_dir() / "users" / user_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def last_user_name() -> str:
    return str(_read_users().get("last") or "")


def legacy_waiting() -> bool:
    data = _read_users()
    if data["users"]:
        return False
    return (data_dir() / "config.json").exists()


def _password_hash(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return digest.hex()


def _check_login(name: str, password: str) -> str | None:
    name = (name or "").strip()
    if not name or any(char in name for char in "\\/") or len(name) > 32:
        return "用户名请用 1 到 32 个字符，不要带斜杠。"
    if len(password or "") < 4:
        return "密码至少 4 位。"
    if len(password) > 128:
        return "密码太长了。"
    return None


def register_user(name: str, password: str) -> str:
    problem = _check_login(name, password)
    if problem:
        raise ValueError(problem)
    name = name.strip()
    data = _read_users()
    if any(item.get("name") == name for item in data["users"]):
        raise ValueError("这个用户名已经有了。")
    user_id = uuid.uuid4().hex
    folder = user_folder(user_id)
    if not data["users"]:
        root = data_dir()
        for filename in ("config.json", "known_hosts"):
            source = root / filename
            target = folder / filename
            if source.exists() and not target.exists():
                try:
                    shutil.move(str(source), str(target))
                except OSError:
                    pass
    salt = os.urandom(16)
    data["users"].append({"id": user_id, "name": name, "salt": salt.hex(), "hash": _password_hash(password, salt)})
    data["last"] = name
    _write_users(data)
    return user_id


def check_user(name: str, password: str) -> str:
    name = (name or "").strip()
    data = _read_users()
    for item in data["users"]:
        if item.get("name") != name:
            continue
        try:
            salt = bytes.fromhex(str(item.get("salt") or ""))
        except ValueError:
            return ""
        expect = str(item.get("hash") or "")
        if hmac.compare_digest(_password_hash(password or "", salt), expect):
            data["last"] = name
            _write_users(data)
            return str(item.get("id") or "")
        return ""
    return ""


class Store:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder or data_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "config.json"
        self.data = self._load()

    def known_hosts_path(self) -> Path:
        return self.folder / "known_hosts"

    def _load(self) -> dict:
        default = {
            "accounts": [],
            "history_days": 3,
            "always_on_top": False,
            "geometry": "1180x720",
            "view_mode": "brief",
            "account_tab": "all",
            "api_base": "https://api.deepseek.com",
            "api_model": "deepseek-flash",
            "api_secret": "",
            "job_buckets": {},
            "later_keys": [],
            "ball_pos": [],
            "plans": [],
            "plan_remind_minutes": 30,
            "plan_remind_at": 0,
            "show_done_plans": False,
            "job_notes": {},
            "day_notes": {},
            "hide_done_jobs": False,
            "hide_bad_jobs": False,
            "skin": "night",
            "shell_theme": "mist",
            "dismissed_jobs": [],
            "font_family": "Microsoft YaHei UI",
            "font_size": 10,
            "plan_view": "notes",
            "update_last_check": 0,
            "update_skipped": "",
            "language": "auto",
        }
        if not self.path.exists():
            return default
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            broken = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(broken)
            except OSError:
                pass
            return default
        if not isinstance(raw, dict):
            return default
        for key, value in default.items():
            raw.setdefault(key, value)
        if not isinstance(raw["accounts"], list):
            raw["accounts"] = []
        return raw

    def save(self) -> None:
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def accounts(self) -> list[dict]:
        return list(self.data["accounts"])

    def history_days(self) -> int:
        try:
            days = int(self.data.get("history_days", 3))
        except (TypeError, ValueError):
            days = 3
        return min(30, max(1, days))

    def set_history_days(self, days: int) -> None:
        self.data["history_days"] = min(30, max(1, int(days)))
        self.save()

    def has_secret(self, account_id: str) -> bool:
        account = self._find(account_id)
        return bool(account and account.get("secret"))

    def password(self, account_id: str) -> str:
        account = self._find(account_id)
        if not account:
            return ""
        token = account.get("secret") or ""
        if not token:
            return ""
        try:
            raw = unprotect(base64.b64decode(token))
        except SecretError:
            raise
        except Exception as exc:
            raise SecretError("读不出已保存的密码，请在账号里重新填写。") from exc
        return raw.decode("utf-8")

    def upsert(self, fields: dict, password: str | None) -> str:
        account_id = (fields.get("id") or "").strip()
        found = self._find(account_id) if account_id else None
        if found is None:
            found = {"id": uuid.uuid4().hex}
            self.data["accounts"].append(found)
        found["label"] = fields["label"].strip() or fields["username"].strip()
        found["host"] = fields["host"].strip()
        found["port"] = int(fields["port"])
        found["username"] = fields["username"].strip()
        found["extra_path"] = (fields.get("extra_path") or "").strip()
        if password:
            found["secret"] = base64.b64encode(protect(password.encode("utf-8"))).decode("ascii")
        self.save()
        return found["id"]

    def delete(self, account_id: str) -> None:
        self.data["accounts"] = [
            account for account in self.data["accounts"] if account.get("id") != account_id
        ]
        self.save()

    def ensure_presets(self, presets: list[dict]) -> int:
        existing = {
            (account.get("username"), account.get("host"), int(account.get("port") or 0))
            for account in self.data["accounts"]
        }
        added = 0
        for item in presets:
            key = (item["username"], item["host"], int(item["port"]))
            if key in existing:
                continue
            self.data["accounts"].append(
                {
                    "id": uuid.uuid4().hex,
                    "label": item["label"],
                    "host": item["host"],
                    "port": int(item["port"]),
                    "username": item["username"],
                    "extra_path": item.get("extra_path") or "/sched/slurm/bin",
                }
            )
            existing.add(key)
            added += 1
        if added:
            self.save()
        return added

    def view_mode(self) -> str:
        mode = self.data.get("view_mode") or "brief"
        return mode if mode in {"brief", "full"} else "brief"

    def set_view_mode(self, mode: str) -> None:
        if mode not in {"brief", "full"}:
            return
        self.data["view_mode"] = mode
        self.save()

    def api_base(self) -> str:
        return (self.data.get("api_base") or "https://api.deepseek.com").strip()

    def api_model(self) -> str:
        model = (self.data.get("api_model") or "deepseek-flash").strip()
        if model in {"deepseek-chat", "deepseek-reasoner"}:
            return "deepseek-flash"
        return model or "deepseek-flash"

    def has_api_key(self) -> bool:
        return bool(self.data.get("api_secret"))

    def api_key(self) -> str:
        token = self.data.get("api_secret") or ""
        if not token:
            return ""
        try:
            raw = unprotect(base64.b64decode(token))
        except SecretError:
            raise
        except Exception as exc:
            raise SecretError("读不出已保存的 API Key，请重新填写。") from exc
        return raw.decode("utf-8")

    def set_api(self, base: str, model: str, key: str | None, clear_key: bool = False) -> None:
        self.data["api_base"] = (base or "https://api.deepseek.com").strip()
        self.data["api_model"] = (model or "deepseek-flash").strip()
        if clear_key:
            self.data["api_secret"] = ""
        elif key:
            self.data["api_secret"] = base64.b64encode(protect(key.encode("utf-8"))).decode("ascii")
        self.save()

    def job_buckets(self) -> dict[str, str]:
        raw = self.data.get("job_buckets")
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}

    def set_job_buckets(self, buckets: dict[str, str]) -> None:
        self.data["job_buckets"] = buckets
        self.save()

    def later_keys(self) -> list[str]:
        raw = self.data.get("later_keys")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if item]

    def set_later_keys(self, keys: list[str]) -> None:
        self.data["later_keys"] = keys[:200]
        self.save()

    def plans(self) -> list[dict]:
        raw = self.data.get("plans")
        if not isinstance(raw, list):
            return []
        if _fill_plan_seq(raw):
            self.save()
        return [item for item in raw if isinstance(item, dict) and item.get("id") and item.get("title")]

    def plan_remind_minutes(self) -> int:
        try:
            minutes = int(self.data.get("plan_remind_minutes", 30))
        except (TypeError, ValueError):
            minutes = 30
        return minutes if minutes in {0, 15, 30, 60, 120} else 30

    def set_plan_remind_minutes(self, minutes: int) -> None:
        self.data["plan_remind_minutes"] = minutes if int(minutes) in {0, 15, 30, 60, 120} else 30
        self.save()

    def plan_remind_at(self) -> float:
        try:
            return float(self.data.get("plan_remind_at") or 0)
        except (TypeError, ValueError):
            return 0

    def touch_plan_remind(self) -> None:
        self.data["plan_remind_at"] = time.time()
        self.save()

    def show_done_plans(self) -> bool:
        return bool(self.data.get("show_done_plans"))

    def set_show_done_plans(self, shown: bool) -> None:
        self.data["show_done_plans"] = bool(shown)
        self.save()

    def _prune_plans(self, plans: list[dict]) -> list[dict]:
        """Keep every note still in use, and only drop old parked ones.

        Slicing the list head used to throw away the newest notes once the list
        reached the cap, so a new note could vanish right after it was saved.
        """
        limit = 300
        if len(plans) <= limit:
            return plans
        in_use = {
            str(item.get("id"))
            for item in plans
            if not item.get("trashed") and (item.get("status") or "todo") != "done"
        }
        parked = [item for item in plans if str(item.get("id")) not in in_use]
        room = max(0, limit - len(in_use))
        keep = in_use | {str(item.get("id")) for item in (parked[-room:] if room else [])}
        return [item for item in plans if str(item.get("id")) in keep]

    def upsert_plan(self, fields: dict) -> str:
        plans = [dict(item) for item in self.plans()]
        now = datetime.now().isoformat(timespec="minutes")
        plan_id = str(fields.get("id") or "")
        found = next((item for item in plans if item.get("id") == plan_id), None)
        fresh = found is None
        if found is None:
            found = {"id": uuid.uuid4().hex, "created": now, "log": []}
            plans.append(found)
        title = str(fields.get("title") or "").strip()
        if not title:
            raise ValueError("先写任务标题。")
        found["title"] = title[:80]
        horizon = str(fields.get("horizon") or "week")
        found["horizon"] = horizon if horizon in {"today", "week", "month", "term"} else "week"
        status = str(fields.get("status") or found.get("status") or "todo")
        found["status"] = status if status in {"todo", "doing", "done", "paused"} else "todo"
        if "importance" in fields:
            rank = str(fields.get("importance") or "normal")
            found["importance"] = rank if rank in {"normal", "high", "urgent"} else "normal"
        elif "importance" not in found:
            found["importance"] = "normal"
        if fresh:
            ranks = [int(item["z"]) for item in plans if isinstance(item.get("z"), int)]
            found["z"] = (max(ranks) + 1) if ranks else 1
            seqs = [int(item["seq"]) for item in plans if isinstance(item.get("seq"), int)]
            found["seq"] = (max(seqs) + 1) if seqs else 1
        if "detail" in fields:
            found["detail"] = str(fields.get("detail") or "")[:2000]
        if "due" in fields:
            due = str(fields.get("due") or "").strip()
            found["due"] = due if _valid_day(due) else ""
        elif "due" not in found:
            found["due"] = ""
        found["updated"] = now
        log = list(found.get("log") or [])
        progress = str(fields.get("progress") or "").strip()
        if progress:
            log.append({"at": now, "text": progress[:500]})
        found["log"] = [item for item in log if isinstance(item, dict) and item.get("text")][-40:]
        self.data["plans"] = self._prune_plans(plans)
        self.save()
        return found["id"]

    def text_family(self) -> str:
        from theme import TEXT_CHOICES

        allowed = {item[0] for item in TEXT_CHOICES}
        name = str(self.data.get("font_family") or "Microsoft YaHei UI")
        return name if name in allowed else "Microsoft YaHei UI"

    def text_size(self) -> int:
        try:
            size = int(self.data.get("font_size") or 10)
        except (TypeError, ValueError):
            size = 10
        return min(16, max(9, size))

    def set_text_style(self, family: str, size: int) -> None:
        from theme import TEXT_CHOICES

        allowed = {item[0] for item in TEXT_CHOICES}
        self.data["font_family"] = family if family in allowed else "Microsoft YaHei UI"
        self.data["font_size"] = min(16, max(9, int(size)))
        self.save()

    def stack_plan(self, plan_id: str, how: str) -> None:
        plans = self.plans()
        if not plans:
            return
        for index, item in enumerate(plans):
            if not isinstance(item.get("z"), int):
                item["z"] = index + 1
        ordered = sorted(plans, key=lambda item: int(item.get("z") or 0))
        index = next((pos for pos, item in enumerate(ordered) if item.get("id") == plan_id), None)
        if index is None:
            return
        if how == "up" and index < len(ordered) - 1:
            ordered[index]["z"], ordered[index + 1]["z"] = ordered[index + 1]["z"], ordered[index]["z"]
        elif how == "down" and index > 0:
            ordered[index]["z"], ordered[index - 1]["z"] = ordered[index - 1]["z"], ordered[index]["z"]
        elif how == "top":
            ordered[index]["z"] = max(int(item.get("z") or 0) for item in ordered) + 1
        elif how == "bottom":
            ordered[index]["z"] = min(int(item.get("z") or 0) for item in ordered) - 1
        else:
            return
        self.save()

    def place_plan(self, plan_id: str, x: int, y: int, w: int, h: int) -> None:
        for item in self.plans():
            if item.get("id") != plan_id:
                continue
            item["x"] = max(0, int(x))
            item["y"] = max(0, int(y))
            item["w"] = max(200, min(980, int(w)))
            item["h"] = max(110, min(640, int(h)))
            self.save()
            return

    def add_plans(self, items: list[dict]) -> int:
        added = 0
        for item in items:
            if not str(item.get("title") or "").strip():
                continue
            self.upsert_plan(item)
            added += 1
        return added

    def skin(self) -> str:
        from theme import SKINS

        name = str(self.data.get("skin") or "night")
        return name if name in SKINS else "night"

    def set_skin(self, name: str) -> None:
        from theme import SKINS

        if name not in SKINS:
            return
        self.data["skin"] = name
        self.save()

    def shell_theme(self) -> str:
        from shellwin import SHELL_THEMES

        name = str(self.data.get("shell_theme") or "mist")
        return name if name in SHELL_THEMES else "mist"

    def set_shell_theme(self, name: str) -> None:
        from shellwin import SHELL_THEMES

        if name not in SHELL_THEMES:
            return
        self.data["shell_theme"] = name
        self.save()

    def dismissed_jobs(self) -> set[str]:
        raw = self.data.get("dismissed_jobs")
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if item}

    def dismiss_job(self, key: str) -> None:
        raw = self.data.get("dismissed_jobs")
        keys = [str(item) for item in raw if item] if isinstance(raw, list) else []
        if key and key not in keys:
            keys.append(key)
        self.data["dismissed_jobs"] = keys[-5000:]
        self.save()

    def set_plan_importance(self, plan_id: str, importance: str) -> None:
        if importance not in {"normal", "high", "urgent"}:
            return
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") == plan_id:
                item["importance"] = importance
                item["updated"] = now
        self.data["plans"] = self.plans()
        self.save()

    def set_plan_status(self, plan_id: str, status: str) -> None:
        if status not in {"todo", "doing", "done", "paused"}:
            return
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") == plan_id:
                item["status"] = status
                item["updated"] = now
        self.data["plans"] = self.plans()
        self.save()

    def set_plan_when(self, plan_id: str, due: str, horizon: str) -> None:
        if horizon not in {"today", "week", "month", "term"} or not _valid_day(due):
            return
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") == plan_id:
                item["due"] = due
                item["horizon"] = horizon
                item["updated"] = now
        self.data["plans"] = self.plans()
        self.save()

    def job_note(self, account_id: str, job_id: str) -> str:
        raw = self.data.get("job_notes")
        if not isinstance(raw, dict):
            return ""
        return str(raw.get(self._note_key(account_id, job_id)) or "")

    def set_job_note(self, account_id: str, job_id: str, text: str) -> None:
        raw = self.data.get("job_notes")
        notes = dict(raw) if isinstance(raw, dict) else {}
        key = self._note_key(account_id, job_id)
        body = (text or "").strip()
        if body:
            notes[key] = body[:2000]
        else:
            notes.pop(key, None)
        if len(notes) > 500:
            notes = dict(list(notes.items())[-500:])
        self.data["job_notes"] = notes
        self.save()

    def day_note(self, day: str) -> str:
        raw = self.data.get("day_notes")
        if not isinstance(raw, dict):
            return ""
        return str(raw.get(day) or "")

    def set_day_note(self, day: str, text: str) -> None:
        if not _valid_day(day):
            return
        raw = self.data.get("day_notes")
        notes = dict(raw) if isinstance(raw, dict) else {}
        body = (text or "").strip()
        if body:
            notes[day] = body[:4000]
        else:
            notes.pop(day, None)
        if len(notes) > 400:
            notes = dict(list(notes.items())[-400:])
        self.data["day_notes"] = notes
        self.save()

    def _note_key(self, account_id: str, job_id: str) -> str:
        return f"{account_id}|{job_id}"

    def plan_view(self) -> str:
        return "list" if self.data.get("plan_view") == "list" else "notes"

    def set_plan_view(self, mode: str) -> None:
        self.data["plan_view"] = "list" if mode == "list" else "notes"
        self.save()

    def update_last_check(self) -> float:
        try:
            return float(self.data.get("update_last_check") or 0)
        except (TypeError, ValueError):
            return 0.0

    def touch_update_check(self) -> None:
        self.data["update_last_check"] = time.time()
        self.save()

    def update_skipped(self) -> str:
        return str(self.data.get("update_skipped") or "")

    def set_update_skipped(self, version: str) -> None:
        self.data["update_skipped"] = str(version or "")
        self.save()

    def language(self) -> str:
        choice = str(self.data.get("language") or "auto")
        return choice if choice in {"auto", "zh", "en"} else "auto"

    def set_language(self, choice: str) -> None:
        self.data["language"] = choice if choice in {"auto", "zh", "en"} else "auto"
        self.save()

    def set_plan_nodes(self, plan_id: str, title: str, nodes: list[dict]) -> None:
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") != plan_id:
                continue
            name = (title or "").strip()
            if not name:
                raise ValueError("先写任务标题。")
            item["title"] = name[:80]
            cleaned = []
            used: set[str] = set()
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                text = str(node.get("text") or "").strip()
                if not text:
                    continue
                node_id = str(node.get("id") or "") or uuid.uuid4().hex[:8]
                if node_id in used:
                    node_id = uuid.uuid4().hex[:8]
                used.add(node_id)
                cleaned.append(
                    {
                        "id": node_id,
                        "text": text[:500],
                        "at": str(node.get("at") or now),
                        "done": bool(node.get("done")),
                        "parent": str(node.get("parent") or ""),
                    }
                )
            known = {row["id"] for row in cleaned}
            for row in cleaned:
                if row["parent"] not in known:
                    row["parent"] = ""
            item["log"] = cleaned[-40:]
            item["updated"] = now
            self.data["plans"] = self.plans()
            self.save()
            return

    def set_node_done(self, plan_id: str, node_id: str, done: bool) -> None:
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") != plan_id:
                continue
            log = [row for row in (item.get("log") or []) if isinstance(row, dict)]
            found = False
            for index, row in enumerate(log):
                current = str(row.get("id") or f"n{index}")
                if current == node_id:
                    row["id"] = current
                    row["done"] = bool(done)
                    found = True
                    break
            if not found and node_id == "detail":
                text = str(item.get("detail") or "").strip()
                if text:
                    log.append({"id": "detail", "text": text[:500], "at": now, "done": bool(done), "parent": ""})
                    found = True
            if not found:
                return
            item["log"] = log
            item["updated"] = now
            self.data["plans"] = self.plans()
            self.save()
            return

    def trash_plan(self, plan_id: str) -> None:
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") == plan_id:
                item["trashed"] = True
                item["updated"] = now
        self.data["plans"] = self.plans()
        self.save()

    def restore_plan(self, plan_id: str) -> None:
        now = datetime.now().isoformat(timespec="minutes")
        for item in self.plans():
            if item.get("id") == plan_id:
                item["trashed"] = False
                item["updated"] = now
        self.data["plans"] = self.plans()
        self.save()

    def delete_plan(self, plan_id: str) -> None:
        self.data["plans"] = [item for item in self.plans() if item.get("id") != plan_id]
        self.save()

    def _find(self, account_id: str) -> dict | None:
        for account in self.data["accounts"]:
            if account.get("id") == account_id:
                return account
        return None
