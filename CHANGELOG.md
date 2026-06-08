# Changelog

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
