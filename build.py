"""Build the Windows exe with version metadata.

Used by 打包成exe.bat and by the GitHub Actions workflow, so both produce the
same binary: version resource filled in, UPX disabled (UPX-packed exes trip more
antivirus heuristics), and the icon/update url bundled.

The PyInstaller name is ASCII on purpose: CI runs on a cp1252 console, and a
Chinese --name makes PyInstaller print paths it cannot encode.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
NAME = "jobdesk"
DISPLAY = "作业看台"


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def app_version() -> str:
    text = APP.read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("cannot find VERSION in app.py")
    return match.group(1)


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(piece) for piece in version.split("-")[0].split(".") if piece.isdigit()][:3]
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2], 0)


def write_version_file(version: str) -> Path:
    a, b, c, d = version_tuple(version)
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, {d}),
    prodvers=({a}, {b}, {c}, {d}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', 'yrzhu-ai'),
        StringStruct('FileDescription', 'Job Desk - Linux/Slurm job monitor'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{NAME}'),
        StringStruct('LegalCopyright', 'MIT License, https://github.com/yrzhu-ai/job-desk'),
        StringStruct('OriginalFilename', '{NAME}.exe'),
        StringStruct('ProductName', 'Job Desk'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path = ROOT / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    _utf8_console()
    version = app_version()
    version_file = write_version_file(version)
    print(f"building Job Desk {version}")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        "--onefile",
        "--noupx",
        "--name",
        NAME,
        "--icon",
        "quill.ico",
        "--version-file",
        str(version_file),
        "--add-data",
        "quill.ico;.",
        "--add-data",
        "update_url.txt;.",
        "--clean",
        "app.py",
    ]
    code = subprocess.call(command, cwd=str(ROOT))
    built = ROOT / "dist" / f"{NAME}.exe"
    if code == 0 and built.exists():
        alias = ROOT / "dist" / f"{DISPLAY}.exe"
        try:
            shutil.copy2(built, alias)
            print(f"built {built}")
            print(f"copy  {alias}")
        except OSError as exc:
            print(f"copy failed: {exc}")
    return code


if __name__ == "__main__":
    sys.exit(main())
