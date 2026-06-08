# History

## 2026-06-08

Follow-up correction: moved both phone crawler morning windows from 09:00 to 08:00.

- ZOL now schedules at 08:07-12:07 Beijing time and accepts manual `auto` / `morning` dispatch from 08:00.
- PConline now schedules at 08:17-12:17 Beijing time and accepts manual `auto` / `morning` dispatch from 08:00.
- Workflow expectation checks now assert the 08:00 morning start and matching 8:00-12:30 text.

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
