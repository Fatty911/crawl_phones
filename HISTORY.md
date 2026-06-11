# History

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
