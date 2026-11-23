"""Ask DeepSeek about the current job snapshot. Passwords are never included."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from jobs import Job, one_line, state_text


class AskError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirected POST would carry the Authorization header to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "接口地址不允许跳转。", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)
_MAX_REPLY = 2 * 1024 * 1024


def completions_url(base: str) -> str:
    text = (base or "").strip().rstrip("/")
    if not text.startswith("https://") or any(char.isspace() for char in text):
        raise AskError("接口地址需要以 https:// 开头。")
    if text.endswith("/chat/completions"):
        return text
    return text + "/chat/completions"


def snapshot_text(jobs: list[Job], account_errors: list[str], limit: int = 80) -> str:
    lines = list(account_errors)
    shown = jobs[:limit]
    for job in shown:
        place = one_line(job.place, 80)
        lines.append(
            "\t".join(
                [
                    job.account_label or job.account_id or "账号",
                    job.job_id,
                    job.name,
                    state_text(job.state),
                    f"已运行{job.elapsed or '-'}",
                    f"分区{job.partition or '-'}",
                    f"位置或原因{place or '-'}",
                    f"退出码{job.exit_code or '-'}",
                ]
            )
        )
    if len(jobs) > limit:
        lines.append(f"……还有 {len(jobs) - limit} 条没有放进这次提问。")
    return "\n".join(lines) if lines else "当前没有作业。"


def fast_model(model: str) -> str:
    name = (model or "").strip()
    if name in {"", "deepseek-chat", "deepseek-reasoner"}:
        return "deepseek-flash"
    return name


def _post(base: str, api_key: str, model: str, messages: list[dict], timeout: int = 45) -> str:
    key = (api_key or "").strip()
    if not key:
        raise AskError("还没有填写 API Key。")
    model_name = fast_model(model)
    if any(char.isspace() for char in model_name):
        raise AskError("模型名称不正确。")
    payload = {
        "model": model_name,
        "temperature": 0.3,
        "max_tokens": 1024,
        "thinking": {"type": "disabled"},
        "messages": messages,
    }
    request = urllib.request.Request(
        completions_url(base),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read(_MAX_REPLY + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code in {401, 403}:
            raise AskError("API Key 不正确，或没有权限。") from exc
        raise AskError(f"接口返回 {exc.code}：{one_line(detail, 180)}") from exc
    except urllib.error.URLError as exc:
        raise AskError(f"连不上接口：{one_line(str(exc.reason), 180)}") from exc
    except TimeoutError as exc:
        raise AskError("接口超时，请再试一次。") from exc
    except OSError as exc:
        raise AskError(f"连不上接口：{one_line(str(exc), 180)}") from exc
    if len(raw) > _MAX_REPLY:
        raise AskError("接口返回的内容太大。")
    raw = raw.decode("utf-8", "replace")
    try:
        data = json.loads(raw)
        message = data["choices"][0]["message"]
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AskError("接口没有返回文字。已要求快速回答，请再试一次。")
        return content.strip()
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise AskError("接口返回的内容无法读取。") from exc


def ask_deepseek(base: str, api_key: str, model: str, question: str, context: str, timeout: int = 60) -> str:
    prompt = (question or "").strip()
    if not prompt:
        raise AskError("先写一个问题。")
    return _post(
        base,
        api_key,
        model,
        [
            {
                "role": "system",
                "content": (
                    "你是集群作业助手。只根据用户给出的作业快照回答，用简体中文，尽量短。"
                    "说明哪些已完成、哪些还在进行、哪些报错，以及快照里能看到的原因。"
                    "不要编造快照里没有的作业号，也不要索要密码。"
                ),
            },
            {"role": "user", "content": f"{prompt}\n\n当前作业快照：\n{context}"},
        ],
        timeout,
    )


def task_instructions(today: str) -> str:
    day = (today or "").strip() or "今天"
    return (
        "你是任务管家。把用户写下的话拆成可以直接去做的任务。"
        "只返回一个 JSON 对象，不要解释，不要使用 markdown。"
        '{"tasks":[{"title":"动词开头，不超过24字","detail":"这一步具体怎么做，一两句","due":"YYYY-MM-DD","horizon":"今日或本周或本月或本学期"}]}'
        f"用户没有写日期时，due 写成 {day}。"
        "用户提到几件事就返回几条。每条 title 必须是一个能动手做的动作，detail 写清怎么做，不要空话。"
        "只写了一句，也要返回一条。禁止返回空的 tasks。不要发明用户没提到的事，也不要索要密码。"
    )


def organize_plans(base: str, api_key: str, model: str, narrative: str, today: str, timeout: int = 60) -> str:
    text = (narrative or "").strip()
    if not text:
        raise AskError("先写下要做的事。")
    if len(text) > 4000:
        raise AskError("这段话太长了，先拆开整理。")
    return _post(
        base,
        api_key,
        model,
        [
            {"role": "system", "content": task_instructions(today)},
            {"role": "user", "content": text},
        ],
        timeout,
    )


def _self_test() -> None:
    assert completions_url("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert completions_url("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1/chat/completions"
    try:
        completions_url("http://api.deepseek.com")
    except AskError:
        pass
    else:
        raise AssertionError("http should be rejected")
    job = Job("9", "flye", "FAILED", "00:01:00", "", "HPC", "", "", "bad node", "", "", "", "1:0", "sacct", account_label="账号1")
    text = snapshot_text([job], ["账号2 连接失败"])
    assert "flye" in text and "账号2" in text and "password" not in text.lower()
    assert fast_model("deepseek-chat") == "deepseek-flash"
    assert fast_model("deepseek-reasoner") == "deepseek-flash"
    assert fast_model("") == "deepseek-flash"
    instructions = task_instructions("2026-11-10")
    assert "可以直接去做" in instructions and "2026-11-10" in instructions
    print("ask self-test ok")


if __name__ == "__main__":
    _self_test()
