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

## [2026-10-22] maintenance | Sync upstream v0.1.18 into alphadev

Merged `upstream/main` (`11cff3f3`, v0.1.18, force-pushed, 438 commits since
merge base `026deaa97a`) into `alphadev` as `7d7f074a`, resolving 52 conflicted
files / 101 hunks with a plain merge and no `-X` strategy; rollback branch
`backup/alphadev-presync-66060c59`. `alphadev` is now 542 ahead / 0 behind
upstream. Restored two test files that had unexplained working-tree deletions.

The merge's important finding: `agent/api_server.py` reported **no conflict**
but was semantically broken. Upstream had split the 1474-line monolith into a
345-line assembler plus 32 `src/api/*_routes.py` modules; git combined it into
1427 lines that kept the fork's inline routes while taking upstream's import
line, which dropped `Depends` and made the module unimportable. The file now
takes the upstream assembler verbatim, and the fork-local analytics/ranking
endpoints (`0e3714de`) moved to a new `src/api/analytics_routes.py` with
`register_analytics_routes(app, require_auth)`, re-exporting
`_connect_ranking_db` for the existing test seam.

Verification: 3886 Python files parse; no conflict markers; no duplicate
top-level TS declarations; 111 routes with 0 duplicate registrations; 870 tests
passing. Remaining local failures (16 claude-cli, 10 channels, 1 registry) were
diagnosed as environment-only — Windows cannot execute the extension-less fake
CLI, and `nh3` / `slack_sdk` / optional loader deps are absent from the venv.
Pushed `alphadev` to `origin` (`b889d112..bb6c9637`) after pinning the GitHub
account for GCM — two stored accounts made it prompt and block past the command
timeout. Recorded the session report
`session-reports/2026-10-22-115326-fork-sync-upstream-v0-1-18.md` and updated the
wiki index.
