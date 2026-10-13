# LLM Wiki Log

## [2026-06-24] setup | Initial wiki skeleton

Created the project-local LLM Wiki structure with raw sources, maintained wiki pages, an index, and an append-only log.

## [2026-07-04] maintenance | Data update module page

Added `data-update-module.md` to document the local market data ingestion
architecture, source selection, update modes, DuckDB tables, and extension
points. Updated the wiki index to include the new page.

## [2026-07-27] maintenance | Session analysis report convention

Added a project-level requirement that every session ends with a shareable
Markdown analysis report. Created the first report under
`llm-wiki/wiki/session-reports/` and updated the wiki index.

## [2026-08-25] maintenance | Fork sync & upstream merge report

Synced local `main` to upstream (`99e84aba` after upstream force-push) and
merged upstream into `alphadev` with `-X theirs` (upstream-priority),
resolving 665 conflicts. Recorded the session report
`session-reports/2026-08-25-142315-fork-sync-merge.md`, updated the wiki
index, and noted the pending manual push and `agent/agent/` untracked-data
loss as follow-ups.

## [2026-10-13] maintenance | Sync main into alphadev

Merged `origin/main` (`c25fea2b`, 1240 commits since `99e84aba`) into
`alphadev` as `b023c1a3`, resolving two conflicts explicitly (no `-X`
strategy) and keeping a rollback branch `backup/alphadev-pre-sync-bd0956c7`.
While verifying, found and fixed four duplicate-declaration defects that the
2026-08-25 `-X theirs` merge had left in `frontend/src/pages/Agent.tsx`
(`loadGoalSnapshot`, `handleContinueGoal`), `frontend/src/pages/RunDetail.tsx`
(chart-symbol helpers) and `agent/src/providers/llm.py`
(`provider_diagnostics`), plus 17 duplicated entries in
`frontend/package-lock.json`. Recorded the session report
`session-reports/2026-10-13-142132-main-to-alphadev-sync.md` and updated the
wiki index. Push to `origin` remains a user decision.
