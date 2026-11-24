"""Push the working tree and publish a release through the GitHub REST API.

Needed on this machine because github.com is unreachable while api.github.com works.

Usage:
    python tools/api_release.py --tag v1.0.20 --notes-file CHANGELOG.snippet.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = "yrzhu-ai"
REPO = "job-desk"
API = "https://api.github.com"
SKIP_DIRS = {".git", "__pycache__", "build", "dist", ".venv", "venv", "_assets"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def token() -> str:
    value = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if value:
        return value.strip()
    path = Path.home() / "AppData" / "Local" / "Temp" / "gh_token.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def call(method: str, url: str, payload: dict | None = None, raw: bytes | None = None, headers: dict | None = None):
    data = raw
    merged = {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "job-desk-release",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        merged["Content-Type"] = "application/json"
    if headers:
        merged.update(headers)
    request = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url} -> {exc.code}: {exc.read()[:400]!r}") from exc


def collect_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix in SKIP_SUFFIX:
            continue
        files.append(path)
    return files


def push_tree() -> str:
    ref = call("GET", f"{API}/repos/{OWNER}/{REPO}/git/ref/heads/main")
    parent = ref["object"]["sha"]
    commit = call("GET", f"{API}/repos/{OWNER}/{REPO}/git/commits/{parent}")
    base_tree = commit["tree"]["sha"]

    files = collect_files()
    print(f"uploading {len(files)} files ...")
    entries = []
    for index, path in enumerate(files, 1):
        rel = path.relative_to(ROOT).as_posix()
        blob = call(
            "POST",
            f"{API}/repos/{OWNER}/{REPO}/git/blobs",
            {"content": base64.b64encode(path.read_bytes()).decode("ascii"), "encoding": "base64"},
        )
        entries.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if index % 20 == 0:
            print(f"  {index}/{len(files)}")
    tree = call("POST", f"{API}/repos/{OWNER}/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    new_commit = call(
        "POST",
        f"{API}/repos/{OWNER}/{REPO}/git/commits",
        {
            "message": "1.0.20：桌宠悬浮球（106 个动作）、分类设置、代理支持、背景图契合度",
            "tree": tree["sha"],
            "parents": [parent],
        },
    )
    call("PATCH", f"{API}/repos/{OWNER}/{REPO}/git/refs/heads/main", {"sha": new_commit["sha"]})
    print("main ->", new_commit["sha"][:10])
    return new_commit["sha"]


def ensure_tag(tag: str, sha: str) -> None:
    try:
        call("POST", f"{API}/repos/{OWNER}/{REPO}/git/refs", {"ref": f"refs/tags/{tag}", "sha": sha})
        print("tag created", tag)
    except SystemExit:
        call("PATCH", f"{API}/repos/{OWNER}/{REPO}/git/refs/tags/{tag}", {"sha": sha, "force": True})
        print("tag moved", tag)


def publish(tag: str, notes: str) -> None:
    release = call(
        "POST",
        f"{API}/repos/{OWNER}/{REPO}/releases",
        {"tag_name": tag, "name": tag.lstrip("v"), "body": notes, "draft": False, "prerelease": False},
    )
    print("release", release["html_url"])
    for asset in (ROOT / "dist" / "jobdesk.exe", ROOT / "dist" / "jobdesk.exe.sha256"):
        if not asset.is_file():
            continue
        upload = release["upload_url"].split("{")[0] + f"?name={asset.name}"
        call(
            "POST",
            upload,
            raw=asset.read_bytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        print("uploaded", asset.name, f"{asset.stat().st_size / 1024 / 1024:.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--skip-push", action="store_true")
    parser.add_argument("--skip-release", action="store_true")
    parser.add_argument("--skip-assets", action="store_true")
    args = parser.parse_args()
    if not token():
        raise SystemExit("no GitHub token found")
    sha = None
    if not args.skip_push:
        sha = push_tree()
    if not args.skip_release:
        if sha:
            ensure_tag(args.tag, sha)
        publish(args.tag, args.notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
