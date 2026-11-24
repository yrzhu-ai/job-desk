"""GitHub device flow: print a code for the user, then store the token for gh."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

CLIENT_ID = "178c6fc778ccc68e1d6a"  # GitHub CLI OAuth app
SCOPE = "repo workflow read:org gist"
DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"

tmp = os.environ.get("TEMP") or "."
code_file = os.path.join(tmp, "gh_device.json")
token_file = os.path.join(tmp, "gh_token.txt")


def post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json", "User-Agent": "LinuxJobDesk-setup"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def main() -> int:
    start = post(DEVICE_URL, {"client_id": CLIENT_ID, "scope": SCOPE})
    user_code = start.get("user_code", "")
    verify = start.get("verification_uri", "https://github.com/login/device")
    device_code = start.get("device_code", "")
    interval = int(start.get("interval", 5))
    with open(code_file, "w", encoding="utf-8") as handle:
        json.dump({"user_code": user_code, "verification_uri": verify, "device_code": device_code}, handle)
    print("CODE", user_code, verify, flush=True)
    if not device_code:
        print("no device code", start, flush=True)
        return 1

    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(interval)
        try:
            answer = post(
                TOKEN_URL,
                {
                    "client_id": CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except Exception as exc:
            print("poll error", exc, flush=True)
            continue
        error = answer.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 2
            continue
        token = answer.get("access_token")
        if token:
            with open(token_file, "w", encoding="utf-8") as handle:
                handle.write(token)
            try:
                os.chmod(token_file, 0o600)
            except OSError:
                pass
            print("AUTHORIZED", flush=True)
            return 0
        print("FAILED", error, answer.get("error_description", ""), flush=True)
        return 1
    print("TIMEOUT", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
