# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.16]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.16
[1.0.15]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.15
[1.0.14]: https://github.com/yrzhu-ai/job-desk/releases/tag/v1.0.14
