"""Push job notifications to a group robot (WeCom / DingTalk / Feishu)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


def _payload(url: str, text: str) -> dict:
    if "feishu" in url or "larksuite" in url:
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "text", "text": {"content": text}}


def send(webhook: str, text: str) -> None:
    """POST one text message to a group robot webhook (or PushPlus / ServerChan)."""
    url = (webhook or "").strip()
    if url.lower().startswith("wecom:"):
        _send_wecom_app(url.split(":", 1)[1], text)
        return
    if url.lower().startswith("pushplus:"):
        _send_pushplus(url.split(":", 1)[1].strip(), text)
        return
    if url.lower().startswith("serverchan:"):
        _send_serverchan(url.split(":", 1)[1].strip(), text)
        return
    if "sctapi.ftqq.com" in url:
        _send_serverchan_url(url, text)
        return
    if not url.startswith("https://"):
        raise ValueError("webhook 需要以 https:// 开头")
    body = json.dumps(_payload(url, text), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "LinuxJobDesk"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except Exception as exc:
        raise RuntimeError(f"发送失败：{exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    code = data.get("errcode", data.get("code", 0))
    if code not in (0, "0", None):
        raise RuntimeError(f"机器人返回 {code}：{data.get('errmsg') or data.get('msg') or raw[:120]}")


def _post_json(url: str, payload: dict) -> str:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "LinuxJobDesk"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", "replace")


def _send_wecom_app(spec: str, text: str) -> None:
    """Send an app message to yourself: wecom:corpId:agentId:secret[:userId]"""
    parts = spec.split(":")
    if len(parts) < 3:
        raise ValueError("格式：wecom:企业ID:应用AgentId:Secret[:成员账号]")
    corp, agent, secret = parts[0].strip(), parts[1].strip(), parts[2].strip()
    user = parts[3].strip() if len(parts) > 3 and parts[3].strip() else "@all"
    token_url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
        + urllib.parse.urlencode({"corpid": corp, "corpsecret": secret})
    )
    raw = urllib.request.urlopen(token_url, timeout=15).read().decode("utf-8", "replace")
    data = json.loads(raw)
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"取 access_token 失败：{data.get('errmsg') or raw[:120]}")
    payload = {"touser": user, "msgtype": "text", "agentid": int(agent), "text": {"content": text}}
    send_url = "https://qyapi.weixin.qq.com/cgi-bin/message/send?" + urllib.parse.urlencode({"access_token": token})
    body = _post_json(send_url, payload)
    result = json.loads(body)
    if result.get("errcode") not in (0, "0", None):
        raise RuntimeError(f"企业微信返回 {result.get('errcode')}：{result.get('errmsg')}")


def _send_pushplus(token: str, text: str) -> None:
    if not token:
        raise ValueError("PushPlus 需要写成 pushplus:你的token")
    raw = _post_json("https://www.pushplus.plus/send", {"token": token, "title": "作业看台", "content": text, "template": "txt"})
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if data.get("code") not in (200, "200", None):
        raise RuntimeError(f"PushPlus 返回 {data.get('code')}：{data.get('msg')}")


def _send_serverchan(key: str, text: str) -> None:
    if not key:
        raise ValueError("Server酱 需要写成 serverchan:你的SendKey")
    _send_serverchan_url(f"https://sctapi.ftqq.com/{key}.send", text)


def _send_serverchan_url(url: str, text: str) -> None:
    payload = {"title": "作业看台", "desp": text}
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "LinuxJobDesk"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if data.get("code") not in (0, "0", None):
        raise RuntimeError(f"Server酱 返回 {data.get('code')}：{data.get('message') or data.get('info')}")
