## 2026-07-05

### Fixed
- mihomo 代理未就绪问题（超时 15s→30s）
- 被墙的 health-check URL 替换为 baidu.com
- 代理连通性测试增加重试

### Changed
- 206 个数据文件从根目录移入 `data/`，所有引用路径已更新
- 上游同步工作流新增

# Changelog

## 2026-06-15

- Reworked the Pages UI into a data-driven advanced phone selector with generated field conditions, clickable facet values, numeric range filters, and IME-safe text input.
- Removed the source quick filter from the UI because published rows are now meant to represent merged/cross-verified phone records.
- Added local filter-history snapshots plus optional GitHub private Gist sync for cross-device history reuse.
- Changed `merge_phones.py` to consolidate matching ZOL/PConline models into one verified row with `验证状态` and `交叉验证差异` metadata.
- Hardened crawler artifacts so empty ZOL/PConline JSON files are not uploaded or used to trigger merge analysis, and merge publishing now skips empty recent artifacts while searching for the latest valid source data.

## 2026-06-11

- Configured cron-job.org jobs for the phone crawler external trigger at Beijing 08:30 and 13:30.
- Hardened progress syncing by switching to explicit fetch/rebase/push steps and printing sanitized Git failure logs.
- Made cron-job.org configuration retry transient API/network failures.
- Made optional Root-info artifact downloads silent in release and Pages jobs to avoid false red annotations.

## 2026-06-10

- Replaced unreliable crawler `schedule` triggers with a cron-job.org `repository_dispatch` entry workflow at Beijing 08:30 and 13:30.
- Extended the afternoon crawl window to Beijing 13:00-22:00 for both ZOL and PConline.
- Added shared runtime budgeting so each run stops before the earlier of the current crawl window cutoff or the GitHub Actions six-hour limit.
- Added a cron-job.org upsert script and workflow expectation checks for the external trigger path.

## 2026-06-09

- Increased both phone crawler schedules to 15-minute backup triggers inside the Beijing morning and afternoon crawl windows, following the crawl_cars reliability pattern.
- Staggered PConline trigger minutes behind ZOL so the two crawler workflows do not always start in the same minute.
- Tightened workflow expectation checks to assert the required backup cron expressions.

## 2026-06-08

- Added the GitHub Pages CNAME file for `phones.jiucai.eu.org`.
- Added an independent GitHub Pages deployment workflow, matching the crawl_cars Pages publishing pattern.
- Moved the phone crawler morning window from 09:00 to 08:00 in both schedule cron and runtime guards.
- Added PConline processed/skipped phone caching so old iPhone entries and no-year records are not fetched again on resume.
- Treated crawler exit code 10 as a resumable progress checkpoint in both ZOL and PConline workflows.
- Added workflow runtime clamping so step1 leaves a commit buffer before the GitHub Actions six-hour limit.
- Enforced the configured crawl windows for scheduled and manual dispatch runs.
- Added robust progress rebase/push helpers and static CI checks for Python, YAML, shell, and workflow guardrails.
- Made merge-and-deploy search recent successful crawler runs until it finds a matching data artifact.
