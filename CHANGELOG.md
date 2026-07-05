## 2026-07-06

### Changed
- 根目录 7 个 Python 脚本全部移入 `scripts/`（crawl_zol/crawl_pconline/merge_phones/search_root_info/ai_verify_root_status/proxy_manager/generate_clash_config）
- `custom_scripts/` 合并入 `scripts/`（7 个文件），删除 `custom_scripts/` 目录
- `zol/` 和 `pconline/` 目录移入 `crawl_state/`（合并为 `crawl_state/zol/` + `crawl_state/pconline/`）
- 所有 workflow（crawl-zol/crawl-pconline/merge-and-deploy/ci）路径引用同步更新
- `validate_syntax.py`/`validate_workflow_expectations.py` 路径引用同步更新
- `.gitignore` 规则同步更新（zol/json/ → crawl_state/zol/json/ 等）
- 根目录从 22 个文件降至 10 个（仅 README/AGENTS/CHANGELOG/requirements.txt + 4 个目录）

### Fixed
- 根目录数据文件再次堆积（workflow 产出仍在根目录）——彻底修复
- 爬虫脚本 `crawl_zol.py`/`crawl_pconline.py` 输出路径改为 `data/` 子目录（`data_dir` 变量）
- 爬虫 workflow `crawl-zol.yml`/`crawl-pconline.yml` 中 validate DATA_FILE、git commit 检查、artifact upload path 全部加上 `data/` 前缀
- `.gitignore` 不再忽略 `data/` 目录（之前 `data/*.json` `data/*.csv` 全屏蔽导致 data/ 文件无法追踪）
- `find_latest()` 函数优先在 `data_dir` 里找，保留递归搜索作为兜底

### Changed
- 根目录从 218 个文件降至 19 个（仅代码、配置、目录）；197 个数据文件归入 `data/`

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
## 2026-07-06

### 爬虫根目录数据文件彻底归整

- **问题**：高峰期爬虫运行后 GitHub 仓库根目录再次堆积 197 个 json/csv 数据文件（共 218 个根文件）
- **根因**：`.gitignore` 第29-32行 `data/` `data/*.json` `data/*.csv` 把整个 data/ 目录屏蔽，之前 `git mv` 操作把数据移到 data/ 但被 ignore 无法追踪；同时爬虫脚本 `crawl_zol.py`/`crawl_pconline.py` 的 `working_dir` 仍是根目录，每次爬虫运行后生成 `zol_phones_$DATE.json` 文件放在根目录
- **修复**：
  1. `.gitignore`：删除 `data/`、`data/*.json`、`data/*.csv`、`!data/.gitkeep`；改为只忽略 `data/tmp/`
  2. `crawl_zol.py`：新增 `data_dir = os.path.join(working_dir, 'data')`，`output_file` 和 `csv_file` 改用 `data_dir`；`find_latest()` 优先在 `data_dir` 搜索
  3. `crawl_pconline.py`：同上修改
  4. `crawl-zol.yml`/`crawl-pconline.yml`：`DATA_FILE="data/..._phones_$TODAY.json"`，commit check `[ -f "data/..._phones_$(date +%Y%m%d).json" ]`，artifacts path 加 `data/` 前缀
- **验证**：`python3 -m py_compile` 三个 .py 文件全部 OK；根目录剩 19 个文件（全为代码/配置/目录）；`git mv` 197 个数据文件到 `data/` 全部成功 staged
- **影响范围**：5 个源文件改动 + 200 个文件移动

## 2026-07-05 — 代理修复 + 数据目录整理

### 代理连通性修复（与 crawl_cars 同步）
- `custom_scripts/setup_proxy_runtime.py`: mihomo 超时 15s→30s，失败时打印日志
- `custom_scripts/generate_clash_config.py`: health-check URL → `baidu.com`
- 代理连通性测试增加重试 + `trust_env=False`

### 数据文件目录整理
- 206个 JSON/CSV 数据文件从根目录移入 `data/`
- `merge-and-deploy.yml`、`deploy-pages.yml`、`merge_phones.py` 所有引用路径更新
- `.gitignore` 添加 `data/*.json`、`data/*.csv`
- 根目录文件数：220→14

### 上游同步工作流
- 新增 `sync-upstream.yml`

# History

## 2026-06-15

Reworked the phone Pages selector and merge output:

- The old UI exposed a `数据来源` quick filter, which let users split the published data back into one crawler source even though the intended page is a combined selector backed by ZOL + PConline.
- `merge_phones.py` now consolidates matching model names into one record and marks rows as `双源一致`, `双源差异`, or `单源`; conflicting double-source values are preserved in `交叉验证差异`.
- `docs/phones/app.js` now builds advanced filter rows from the actual dataset columns instead of hardcoding every possible condition in code.
- The table-header filter row was removed because re-rendering the header on every input caused focus loss after typing one character; filter inputs now debounce updates and respect Chinese IME composition events.
- The Pages UI now supports clickable facet values, numeric range filters, local filter-history snapshots, and optional GitHub private Gist sync for cross-device history reuse without hardcoding a repository or Gist token into client code.
- Verified with `node --check docs/phones/app.js`, `python -m py_compile merge_phones.py`, `python custom_scripts\validate_syntax.py`, an in-memory merge test, and browser checks on desktop/mobile local preview.

Follow-up review of commit `2c68258` for empty PConline merge data:

- The commit correctly reset incremental crawler pagination to start from page 1, so new phones are not missed after a half-month crawl has already completed.
- That was not sufficient by itself because an incremental run with no new local JSON files could still generate `pconline_phones_YYYYMMDD.json` as `[]`, mark the crawler complete, upload the empty artifact, and cause merge analysis to skip PConline.
- `merge-and-deploy.yml` now downloads crawler artifacts into a temporary directory, checks JSON row counts before accepting them, skips empty or tiny artifacts, and keeps searching older successful runs for valid source data.
- `crawl-zol.yml` and `crawl-pconline.yml` now validate generated JSON before summary/upload/merge-dispatch, remove empty output files, and only upload or trigger merge when there is real data.

## 2026-06-11

Reviewed recent workflow runs and hardened failing paths:

- Latest phone merge run failed in Pages deployment with an authentication error, while optional `phone-root-info-*` download also produced a noisy artifact warning.
- ZOL's previous long run reached the normal time limit and exited with code 10, but progress syncing failed after repeated hidden `pull --rebase` errors.
- `custom_scripts/git_sync_progress.sh` now uses explicit fetch/rebase/push steps and prints sanitized Git failure logs so future sync failures have actionable causes.
- `merge-and-deploy.yml` now downloads optional Root-info artifacts via `gh run download` and continues quietly when the optional artifact does not exist.
- `custom_scripts/configure_cron_job_org.py` now retries transient cron-job.org API/network failures.
- cron-job.org jobs were created/updated for `Fatty911/crawl_phones` at Asia/Shanghai 08:30 and 13:30.

## 2026-06-10

Switched phone crawler triggering from GitHub cron schedules to cron-job.org:

- Removed unreliable `schedule` triggers from `crawl-zol.yml` and `crawl-pconline.yml`.
- Added `crawl-trigger.yml` as the external `repository_dispatch` entrypoint; it accepts `trigger-crawl` and starts both phone crawler workflows by default.
- Unified crawl windows to Beijing 08:00-12:30 and 13:00-22:00.
- Added `custom_scripts/crawl_budget.py` so each long step clamps `RUN_TIME` to the earlier of the current window cutoff or the GitHub Actions six-hour cutoff, leaving progress commit buffer.
- Added `custom_scripts/configure_cron_job_org.py` to create or update cron-job.org jobs at Asia/Shanghai 08:30 and 13:30.

## 2026-06-09

Fixed missed phone crawler schedule windows by applying the `crawl_cars` backup-trigger pattern:

- GitHub CLI showed the latest scheduled phone runs on 2026-06-09 started at 16:39 and 16:41 Beijing time and skipped because they were outside the 13:00-16:00 afternoon window.
- `crawl_cars` uses dense backup cron expressions inside the allowed windows instead of relying on one hourly trigger.
- ZOL now schedules at 08:07/08:22/08:37/08:52 through 11:52, and at 13:07/13:22/13:37/13:52 through 15:52.
- PConline now schedules at 08:17/08:32/08:47/08:57 through 11:57, and at 13:17/13:32/13:47/13:57 through 15:57.
- `custom_scripts/validate_workflow_expectations.py` now fails CI if these backup cron expressions are removed.

## 2026-06-08

Configured GitHub Pages domain:

- GitHub Pages API already had `phones.jiucai.eu.org` as the custom domain.
- Added `docs/phones/CNAME` so the Pages artifact keeps `phones.jiucai.eu.org` after workflow deployments.
- Added `.github/workflows/deploy-pages.yml` so docs/CNAME changes can deploy the site shell without waiting for a full data merge.
- DNS check showed `cars.jiucai.eu.org` has a CNAME to `fatty911.github.io`, while `phones.jiucai.eu.org` still needs the Cloudflare DNS record changed to the same target.

Follow-up correction: moved both phone crawler morning windows from 09:00 to 08:00.

- ZOL now schedules at 08:07-12:07 Beijing time and accepts manual `auto` / `morning` dispatch from 08:00.
- PConline now schedules at 08:17-12:17 Beijing time and accepts manual `auto` / `morning` dispatch from 08:00.
- Workflow expectation checks now assert the 08:00 morning start and matching 8:00-12:30 text.

Follow-up diagnosis for repeated iPhone crawling:

- Runs before `209d27e` exited with code 10 but the workflow treated that as failure, so `pconline/progress.json` stayed empty on `main`.
- PConline previously cached only saved recent phones; old iPhones and no-year/series-like entries were skipped without recording their IDs.
- `crawl_pconline.py` now records `processed_phones` and `skipped_phones`, advances `current_page` after each completed page, and advances `current_brand_index` after a brand is exhausted.

Compared `crawl_phones` with `crawl_cars` commits after `crawl_phones` commit `8ae14f0`.

Relevant `crawl_cars` learnings applied here:

- Long crawler runs must budget against the whole GitHub Actions job, not only the script's `--time-limit`.
- Script exit code `10` means progress was saved and the run should commit that progress, not fail the workflow.
- Manual dispatch should obey the same crawl windows as scheduled runs.
- Merge jobs should not assume the latest successful crawler run has data artifacts, because progress-only runs can succeed without publishing data.

Fixes made:

- Reworked `crawl-zol.yml` and `crawl-pconline.yml` to clamp runtime, commit progress on exit code 10, and use robust rebase/push syncing.
- Removed the undefined `steps.check_done.outputs.done` dependency from the ZOL workflow.
- Added `custom_scripts/git_sync_progress.sh`, `merge_progress_json.py`, `validate_syntax.py`, and `validate_workflow_expectations.py`.
- Added CI so syntax and workflow guardrails are checked on push.
