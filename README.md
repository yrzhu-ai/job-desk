# Job Desk

**English** · [简体中文](README.zh-CN.md)

[![Latest release](https://img.shields.io/github/v/release/yrzhu-ai/job-desk?sort=semver)](https://github.com/yrzhu-ai/job-desk/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)](#requirements)

A small Windows desktop app for watching **Slurm jobs on Linux clusters**, with a
floating ball, an SSH terminal and a sticky-note planner. It manages any number of
accounts — no per-cluster configuration needed.

<!-- screenshots: put images in docs/ and reference them here -->

## Features

- **Any Linux account.** Add host / port / user / password. Slurm is discovered
  automatically (`/opt/slurm/bin`, `/sched/slurm/bin`, `module load slurm`, …);
  if a machine has no scheduler the app falls back to showing `top`.
- **Job board.** Running / Queued / Done / Failed columns, one tab per account,
  queue wait time for pending jobs, optional full table view.
- **Floating ball.** Big number = running / unfinished, small line = finished.
  Hover for a per-account breakdown.
- **Built-in terminal.** SSH shell with select-to-copy and right-click paste
  (MobaXterm-style), `bash` and `zsh` friendly.
- **Planner.** Sticky notes with today / this week / this month / this term views,
  due dates, importance, progress logs and subtasks.
- **Themes.** Four dark skins and four light skins.
- **Bilingual UI.** System / 中文 / English, switchable at runtime.
- **Auto-update.** Checks GitHub Releases once every 24 hours and shows the release
  notes before updating.

## Requirements

- Windows 10 or 11 (x64)
- Network access to the cluster over SSH
- The cluster needs `squeue` / `sacct` for job data; without them the app shows `top`

## Download

Grab the latest `jobdesk.exe` from **[Releases](https://github.com/yrzhu-ai/job-desk/releases/latest)**
and run it. There is nothing to install and Python is not required.

> Windows SmartScreen may warn about an unsigned binary. Click *More info → Run anyway*.
> The SHA-256 of every build is attached to its release.

## Usage

1. **Accounts** → add host, port, username and password. The password is encrypted
   with the Windows DPAPI key of the current user and never leaves the machine.
2. **Jobs** → the board fills in automatically; press *Refresh* for an immediate update.
3. **Ball** → collapses the window to a small always-on-top circle.
4. **Terminal** → open a shell for an account; select text to copy, right-click to paste.
5. **Planner** → write a sentence and let DeepSeek turn it into tasks (optional; needs an API key).

## Auto-update

`update_url.txt` points at this repository. On each check the app reads the **latest
release**:

| Release field | Used for |
|---|---|
| tag (e.g. `v1.0.17`) | version comparison |
| release notes | the "what changed" text in the dialog |
| `.exe` asset | the download (verified by size and SHA-256) |

You can also point it at your own JSON manifest — see the comments inside `update_url.txt`.

## Build from source

```bash
pip install -r requirements.txt
python app.py            # run
```

Package a single executable:

```bash
python build.py          # writes dist/作业看台.exe with a version resource
```

or just double-click `打包成exe.bat`. `build.py` reads `VERSION` from `app.py`,
generates `version_info.txt` and builds with UPX disabled.

## Windows may warn about this app

The executable is **not code-signed**, so Windows SmartScreen shows
*"Windows protected your PC"* the first time someone runs it:

> More info → **Run anyway**

Two things you can do to verify a download is genuine:

- Compare its SHA-256 with `jobdesk.exe.sha256` attached to the same release:
  `certutil -hashfile jobdesk.exe SHA256`
- Check the file's Properties → Details tab: it should show *Job Desk* and the
  matching version.

False-positive reports are welcome — open an issue and include the version.
Bitdefender/360/火绒 occasionally flag PyInstaller one-file builds heuristically;
UPX is already disabled to reduce that.

If you distribute this widely and want the warning gone, a code-signing
certificate is required (OV/EV certificate, or Microsoft Azure Trusted Signing).
That is a paid, identity-verified service; see
[Microsoft's signing docs](https://learn.microsoft.com/azure/trusted-signing/).

## Releasing

```bash
# 1. bump VERSION in app.py and commit
# 2. tag and push
git tag v1.0.17
git push origin main --tags
```

GitHub Actions then builds the exe, computes its SHA-256 and publishes a release
(see [`.github/workflows/release.yml`](.github/workflows/release.yml)).
Running the workflow manually only uploads a build artifact.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | main window, floating ball, update dialog |
| `jobs.py` | SSH queries to Slurm/`top`, output parsing |
| `plans.py` | sticky-note planner |
| `shellwin.py` | built-in terminal emulator |
| `store.py` | accounts, preferences, DPAPI-encrypted secrets |
| `theme.py` | skins and palettes |
| `i18n.py` | Chinese ↔ English UI |
| `updater.py` | check / download / self-replace |
| `winsecret.py` | Windows DPAPI wrapper |

## Contributing

Issues and pull requests are welcome. Please keep changes small and describe the
user-visible effect; screenshots help.

## License

[MIT](LICENSE) © 2026 yrzhu-ai

The pet animations under `pets/fish/` come from the
[dsh-pet](https://github.com/TuWeiZhi/dsh-pet) project (MIT code; its artwork is
free for non-commercial use). This app is free and does not charge for it.
