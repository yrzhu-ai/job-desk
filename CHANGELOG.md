# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.20] - 2026-11-24

### Added
- **Desktop pet in the floating ball.** The ball now plays the 106 animations of the
  dsh-pet character (640x360 VP9-alpha video decoded with PyAV), keeps playing after
  each clip and never repeats the same one twice in a row.
- Ball menu: 打开 / 互动 / 随机动作 (toggle) / 动作列表… / 显示数字 / 立即刷新 / 退出.
  The action list opens next to the ball and is searchable.
- Single click plays a reaction, double click opens the main window.
- "悬浮球" and "鱼的大小" options in Settings (fish or numbers only; 96/120/160).
- Progress bar (running / queued / done / failed) is still available as a strip below
  the pet, or as the whole ball when the pet is turned off.

### Changed
- Update checks now use the Windows proxy, with an optional manual proxy in Settings.
- Settings became a tabbed window (外观 / 网络与更新 / DeepSeek / 账号) and every rarely
  used button moved into it; the toolbar keeps only the frequent actions.
- Custom background image with Windows-style fit modes (fill / fit / stretch / tile /
  center / span) on the planner board and the ball.

## [1.0.19] - 2026-11-23

### Added
- Optional **GitHub token** in Settings. The anonymous GitHub API quota is 60 requests
  per hour per IP, which shared networks can exhaust; a token raises it to 5000/hour.
  The token is encrypted with DPAPI and only sent to `api.github.com`.

### Changed
- The settings window is now titled "设置 / Settings" and keeps both the DeepSeek key
  and the GitHub token.

## [1.0.18] - 2026-11-23

### Added
- Bilingual interface is now complete for dynamic text too: tab titles, filter counts,
  table headers, job/planner context menus, update dialogs, skin names, planner labels,
  date headings and reminder options.
- The executable carries version metadata: Properties → Details shows the product,
  version and author.

### Changed
- The toolbar is split into two rows (filters + Later on top, search + range + timers
  below) so nothing is squeezed out; the "Later" button stays visible in both languages.
- Removed the "Hide done / Hide failed" checkboxes from the toolbar.
- Versioning: beta builds use `x.y.z-beta.N` and are never offered to stable users;
  stable releases always win over a beta of the same number.

### Fixed
- Table headers stayed Chinese after a refresh.
- Job and planner context menus were never translated.
- The update check button reverted to Chinese after a manual check.

### Build
- `build.py` now builds the exe for both local use and CI, with a version resource and
  UPX disabled, which lowers antivirus false positives.

## [1.0.17] - 2026-11-23

### Changed
- Repository housekeeping: added the MIT license, split the README into English and
  Chinese versions, added this changelog, and set the repository description/topics.
- Releases are now produced by GitHub Actions on tag push.

## [1.0.16] - 2026-11-23

### Changed
- Removed the in-window title block (version and user name stay in the window title bar).
- The toolbar now wraps onto extra lines on narrow windows instead of overlapping,
  which matters for the longer English labels.

### Fixed
- Translated the remaining dynamic text: tab titles, filter counts, planner badge,
  "later" counter, last/next refresh timers and the per-account status lines.

## [1.0.15] - 2026-11-23

### Added
- Bilingual interface (System / 中文 / English), switchable at runtime and remembered.
  Buttons, columns, states and queue durations follow the selected language.

### Changed
- Update check now runs once every **24 hours** (was 6).

## [1.0.14] - 2026-11-23

First public release.

### Added
- Multiple Linux accounts over SSH, with automatic Slurm discovery and a `top` fallback.
- Job board with Running / Queued / Done / Failed, queue wait time and per-account tabs.
- Floating ball showing running/unfinished and finished jobs.
- Built-in terminal with select-to-copy and right-click paste.
- Sticky-note planner with day/week/month/term views, due dates and progress logs.
- Eight skins (four dark, four light).
- Automatic updates from GitHub Releases with SHA-256 verification.
- GitHub Actions workflow that builds and publishes a release on tag push.

[1.0.19]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.19
[1.0.18]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.18
[1.0.17]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.17
[1.0.16]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.16
[1.0.15]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.15
[1.0.14]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.14
