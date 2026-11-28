"""Look up a newer build and replace the running program."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from store import data_dir

_API_TOKEN = ""
_MANUAL_PROXY = ""


def set_token(token: str) -> None:
    """Optional GitHub token: raises the API quota from 60/h to 5000/h."""
    global _API_TOKEN
    _API_TOKEN = str(token or "").strip()


def set_proxy(proxy: str) -> None:
    """Optional proxy used when Windows' own proxy setting is off."""
    global _MANUAL_PROXY
    _MANUAL_PROXY = str(proxy or "").strip()


class UpdateError(Exception):
    pass


class UpdateOffer:
    def __init__(self, version: str, url: str, notes: str, sha256: str = "", size: int = 0) -> None:
        self.version = version
        self.url = url
        self.notes = notes
        self.sha256 = sha256
        self.size = size


def _core(text: str) -> str:
    return str(text or "").strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]


def is_beta(version: str) -> bool:
    raw = str(version or "").strip().lstrip("vV")
    return "-" in raw or "+" in raw


def parse_version(text: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in _core(text).split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str) -> bool:
    left = parse_version(remote)
    right = parse_version(local)
    width = max(len(left), len(right))
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    if left != right:
        return left > right
    # Same number: a beta is older than the stable release of that number.
    return is_beta(local) and not is_beta(remote)


def _url_in(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        text = line.strip()
        if text and not text.startswith("#"):
            return text
    return ""


def update_url() -> str:
    found = []
    if getattr(sys, "frozen", False):
        found.append(Path(sys.executable).with_name("update_url.txt"))
    found.append(data_dir() / "update_url.txt")
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    found.append(base / "update_url.txt")
    for path in found:
        text = _url_in(path)
        if text:
            return text
    return ""


def save_update_url(url: str) -> None:
    path = data_dir() / "update_url.txt"
    path.write_text(url.strip() + "\n", encoding="utf-8")


_GITHUB_PREFIXES = ("https://github.com/", "http://github.com/", "https://www.github.com/")


def parse_source(text: str) -> tuple[str, str]:
    """Turn the configured address into ("github", "owner/repo") or ("json", url)."""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    low = raw.lower()
    if low.startswith("github:"):
        repo = raw.split(":", 1)[1].strip().strip("/")
        return ("github", repo) if repo else ("", "")
    for prefix in _GITHUB_PREFIXES:
        if low.startswith(prefix):
            rest = raw[len(prefix):].strip().strip("/")
            if rest.endswith(".git"):
                rest = rest[:-4]
            parts = [part for part in rest.split("/") if part]
            if len(parts) >= 2:
                return "github", f"{parts[0]}/{parts[1]}"
            return "", ""
    return "json", raw


def _system_proxy() -> str:
    """Read the Windows "Internet Settings" proxy so downloads work behind one."""
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            enabled = int(winreg.QueryValueEx(key, "ProxyEnable")[0] or 0)
            if not enabled:
                return ""
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0] or "").strip()
    except Exception:
        return ""
    if not server:
        return ""
    if "=" in server:
        parts = {}
        for piece in server.split(";"):
            if "=" in piece:
                name, value = piece.split("=", 1)
                parts[name.strip().lower()] = value.strip()
        server = parts.get("https") or parts.get("http") or ""
    if not server:
        return ""
    return server if "://" in server else "http://" + server


def _open(request, timeout: int):
    proxy = _MANUAL_PROXY or _system_proxy()
    handlers = []
    if proxy:
        if "://" not in proxy:
            proxy = "http://" + proxy
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _https_json(url: str, limit: int, headers: dict | None = None, missing_ok: bool = False) -> dict:
    if not url.startswith("https://"):
        raise UpdateError("更新地址需要以 https:// 开头。")
    merged = {"User-Agent": "LinuxJobDesk"}
    if _API_TOKEN and "api.github.com" in url:
        merged["Authorization"] = f"Bearer {_API_TOKEN}"
    if headers:
        merged.update(headers)
    request = urllib.request.Request(url, headers=merged)
    try:
        with _open(request, 12) as response:
            final = str(response.geturl() or "")
            if not final.startswith("https://"):
                raise UpdateError("更新地址跳到了不安全的链接。")
            raw = response.read(limit + 1)
    except UpdateError:
        raise
    except urllib.error.HTTPError as exc:
        if missing_ok and exc.code == 404:
            return {}
        if exc.code == 403:
            raise UpdateError("GitHub 接口暂时限流，过一会儿再试（不影响使用）。") from exc
        raise UpdateError(f"更新地址返回了 {exc.code}。") from exc
    except Exception as exc:
        raise UpdateError(f"没有连上更新地址：{exc}") from exc
    if len(raw) > limit:
        raise UpdateError("更新清单太大。")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("更新清单不是一份 json。") from exc
    if not isinstance(data, dict):
        raise UpdateError("更新清单格式不对。")
    return data


def _github_offer(repo: str, local_version: str) -> UpdateOffer | None:
    """Read the newest GitHub release: tag = version, body = notes, .exe asset = download."""
    if "/" not in repo:
        raise UpdateError("GitHub 仓库要写成 owner/repo，例如 https://github.com/me/jobdesk。")
    owner, name = repo.split("/", 1)
    api = f"https://api.github.com/repos/{owner.strip()}/{name.strip()}/releases/latest"
    data = _https_json(
        api,
        600_000,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        missing_ok=True,
    )
    if not data:
        return None
    version = str(data.get("tag_name") or "").strip().lstrip("vV")
    notes = str(data.get("body") or "").strip()
    if not version:
        raise UpdateError("这个发行版没有 tag，无法比较版本。")
    if data.get("prerelease"):
        return None
    best = None
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name") or "")
        if not asset_name.lower().endswith(".exe"):
            continue
        score = 2 if asset_name == "作业看台.exe" else 1 if "作业看台" in asset_name else 0
        if best is None or score > best[0]:
            best = (score, asset)
    if best is None:
        raise UpdateError("这个发行版里没有 .exe 文件。")
    asset = best[1]
    package = str(asset.get("browser_download_url") or "").strip()
    if not package.startswith("https://"):
        raise UpdateError("发行版里的下载地址不是 https。")
    digest = str(asset.get("digest") or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:]
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
        digest = ""
    try:
        size = int(asset.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not is_newer(version, local_version):
        return None
    return UpdateOffer(version, package, notes, digest, size)


def _json_offer(url: str, local_version: str) -> UpdateOffer | None:
    data = _https_json(url, 200_000)
    version = str(data.get("version") or "").strip()
    package = str(data.get("url") or "").strip()
    notes = str(data.get("notes") or "").strip()
    if not version or not package:
        raise UpdateError("更新清单里需要 version 和 url。")
    if not package.startswith("https://"):
        raise UpdateError("新版本的下载地址需要以 https:// 开头。")
    digest = str(data.get("sha256") or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest[7:].strip()
    if digest and (len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)):
        raise UpdateError("更新清单里的 sha256 不是 64 位十六进制。")
    try:
        size = int(data.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if not is_newer(version, local_version):
        return None
    return UpdateOffer(version, package, notes, digest, size)


def look_for_update(local_version: str) -> UpdateOffer | None:
    kind, value = parse_source(update_url())
    if not kind:
        raise UpdateError("还没有更新地址。填 GitHub 仓库地址或一份 json 清单都可以。")
    if kind == "github":
        return _github_offer(value, local_version)
    return _json_offer(value, local_version)


def _check_blob(blob: bytes, sha256: str, size: int) -> None:
    """Reject anything that is not the exact build the manifest describes."""
    if len(blob) < 200_000 or not blob.startswith(b"MZ"):
        raise UpdateError("下载到的文件不像这个程序。")
    if size and len(blob) != size:
        raise UpdateError("下载到的文件大小和清单对不上，已放弃更新。")
    if sha256 and hashlib.sha256(blob).hexdigest() != sha256:
        raise UpdateError("下载到的文件和清单里的 sha256 对不上，已放弃更新。")


def download_release(url: str, sha256: str = "", size: int = 0, progress=None, limit: int = 400 * 1024 * 1024) -> Path:
    if not url.startswith("https://"):
        raise UpdateError("新版本的下载地址需要以 https:// 开头。")
    folder = data_dir() / "update"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "作业看台-new.exe"
    request = urllib.request.Request(url, headers={"User-Agent": "LinuxJobDesk"})
    try:
        with _open(request, 120) as response:
            final = str(response.geturl() or "")
            if not final.startswith("https://"):
                raise UpdateError("下载地址跳到了不安全的链接。")
            try:
                total = int(response.headers.get("Content-Length") or size or 0)
            except (TypeError, ValueError):
                total = size or 0
            done = 0
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > limit:
                        raise UpdateError("下载到的文件太大。")
                    handle.write(chunk)
                    if progress is not None:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError(f"下载没有完成：{exc}") from exc
    blob = target.read_bytes()
    _check_blob(blob, sha256, size)
    return target


def launch_swap(downloaded: Path, pid: int) -> None:
    if not getattr(sys, "frozen", False):
        raise UpdateError("现在是从源码打开的，不能替换这个程序。请打开桌面上的作业看台.exe。")
    destination = Path(sys.executable)
    script = Path(os.environ.get("TEMP") or str(data_dir())) / "linuxjobdesk-update.bat"
    new_size = downloaded.stat().st_size if downloaded.exists() else 0
    lines = [
        "@echo off",
        "setlocal",
        f'set "SRC={downloaded}"',
        f'set "DST={destination}"',
        "set /a N=0",
        ":wait",
        f'tasklist /FI "PID eq {int(pid)}" 2>nul | find "{int(pid)}" >nul',
        "if not errorlevel 1 goto stillrunning",
        "goto copy",
        ":stillrunning",
        "timeout /t 1 /nobreak >nul",
        "set /a N+=1",
        "if %N% LSS 60 goto wait",
        ":copy",
        'copy /y "%SRC%" "%DST%" >nul 2>&1',
        "if errorlevel 1 goto retry",
        'for %%A in ("%SRC%") do set "SRCSZ=%%~zA"',
        'for %%A in ("%DST%") do set "DSTSZ=%%~zA"',
        'if not "%SRCSZ%"=="%DSTSZ%" goto retry',
        "goto done",
        ":retry",
        "timeout /t 1 /nobreak >nul",
        "set /a N+=1",
        "if %N% LSS 120 goto copy",
        "rem could not overwrite: run the downloaded copy directly",
        'start "" "%SRC%"',
        "goto end",
        ":done",
        'start "" "%DST%"',
        'del /f /q "%SRC%" >nul 2>&1',
        ":end",
        'del /f /q "%~f0" >nul 2>&1',
        "",
    ]
    script.write_text("\r\n".join(lines), encoding="mbcs", errors="replace")
    flags = 0x08000000 | 0x00000008
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/min", str(script)],
        creationflags=flags,
        close_fds=True,
    )


def _self_test() -> None:
    assert parse_version("v1.0.10") == (1, 0, 10)
    assert parse_version("1.0.18-beta.1") == (1, 0, 18)
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.1")
    assert not is_newer("1.0.0", "1.0.0")
    assert is_newer("1.0.18", "1.0.18-beta.1")
    assert not is_newer("1.0.18-beta.1", "1.0.18")
    assert is_newer("1.0.18-beta.2", "1.0.17")
    try:
        _https_json("http://example.com/update.json", 100)
    except UpdateError as exc:
        assert "https" in str(exc)
    else:
        raise AssertionError("http should be rejected")
    blob = b"MZ" + b"\0" * 200_000
    good = hashlib.sha256(blob).hexdigest()
    _check_blob(blob, good, len(blob))
    _check_blob(blob, "", 0)
    for digest, size in ((("0" * 64), 0), (good, len(blob) + 1)):
        try:
            _check_blob(blob, digest, size)
        except UpdateError:
            pass
        else:
            raise AssertionError("tampered download should be rejected")
    try:
        _check_blob(b"nope" * 100, "", 0)
    except UpdateError:
        pass
    else:
        raise AssertionError("tiny file should be rejected")
    assert parse_source("https://github.com/me/jobdesk") == ("github", "me/jobdesk")
    assert parse_source("https://github.com/me/jobdesk.git") == ("github", "me/jobdesk")
    assert parse_source("github:me/jobdesk") == ("github", "me/jobdesk")
    assert parse_source("https://example.com/update.json") == ("json", "https://example.com/update.json")
    assert parse_source("") == ("", "")
    assert parse_source("https://github.com/only-owner") == ("", "")
    print("updater self-test ok")


if __name__ == "__main__":
    _self_test()
