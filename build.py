"""Build the Windows exe with version metadata.

Used by 打包成exe.bat and by the GitHub Actions workflow, so both produce the
same binary: version resource filled in, UPX disabled (UPX-packed exes trip more
antivirus heuristics), and the icon/update url bundled.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
NAME = "作业看台"


def app_version() -> str:
    text = APP.read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("找不到 app.py 里的 VERSION")
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
        StringStruct('InternalName', 'jobdesk'),
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
    version = app_version()
    version_file = write_version_file(version)
    print(f"building {NAME} {version}")
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
    return subprocess.call(command, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
