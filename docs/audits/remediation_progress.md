# Remediation Progress — where we left off

- **Last updated:** 2026-07-24
- **State:** ALL remediation work is implemented, verified, and integrated on
  `remediation/verified-findings` @ `3200f21`. **Stopped at the final safety
  gate: waiting for approval to merge into `main`.** Nothing has been merged
  to `main`, pushed, or deleted.
- **Companion docs:** `docs/audits/ranked_report_findings.md` (verified audit,
  source of truth) · `docs/audits/remediation_plan.md` (approved plan +
  decisions D1–D6).

## Verification snapshot (integration branch @ 3200f21)

| Gate | Result |
|---|---|
| Full test suite | **233 passed** (baseline was 141; 92 tests added), 0 failures, ~2.7 s |
| `ruff check src tests` | clean (baseline was clean) |
| `mypy src` | clean, 69 files (baseline was clean) |
| `ruff format --check` | NOT a gate — `main` already fails it on 32 files; no reformatting done |
| CLI E2E (`audit`, `compare`, `ask` on fresh demo workbooks) | pass |
| Determinism | audit + compare byte-identical (JSON and HTML) across repeated runs with different `PYTHONHASHSEED`, in tests and live CLI |
| JSON/HTML consistency | risk level, rule ids, coverage warnings consistent; `workbook_id` = sha256 of file; compare keeps `"old"`/`"new"` |
| Post-T5+T7 storage/report re-run | 42 tests pass |
| Cross-fix interaction tests | 3/3 pass (`tests/integration/test_cross_fixes.py`) |

## Finding status (all confirmed findings)

| Finding | Status | Fix commit |
|---|---|---|
| QA-001 duplicate headers → wrong column as `verified` (P1) | Fixed | `fa6a893` |
| QA-002 thresholds silently dropped (P1) | Fixed | `dbf432f` |
| QA-003 `float(None)` → 500 (P2) | Fixed | `fa6a893` |
| EXCEL-001 rename+edit loses cell diffs (P1, + P2-1 rider) | Fixed | `7885bd2` |
| EXCEL-002 self-loops undetected (P1) | Fixed | `9f32f8c` |
| EXCEL-003 names/tables invisible to impact (P1) | Fixed — FULL resolution per D1 | `9f32f8c` + `610c174` |
| EXCEL-004 non-deterministic reports (P1, + P2-8 free) | Fixed | `fe01cad` |
| EXCEL-005 crashed rule invisible (P1) | Fixed | `8b1f34d` |
| SECURITY-001 `/ask` retains uploads (P1) | Fixed | `ef93194` |
| ARCH-001 dual persistence / broken purge (P1) | Fixed | `ba7e9be` |
| SECURITY-002 32-bit report ids (P2) | Fixed | `ba7e9be` |
| P2-7 `report_schema_version` | Fixed (`"2"`, per D6) | `8b1f34d` |
| P2-2 truncation surfacing | **Deferred** (approved decision — do not implement) | — |

Lead commits: `e99768c` + `276d719` (cross-fix tests), `7f6422b` (T9 docs:
README security/purge sections, HANDOFF ask-flow + name-resolution entries),
`6f4d334` + `3200f21` (lint/mypy fixes for issues worker commits introduced).

## Branch / worktree layout

Worktrees live under the session scratchpad
(`/private/tmp/claude-501/-Users-georgi-dev-micro-saas-exp-excel-auditor/dd981ef2-f859-4816-88f7-dcab2c59aea6/scratchpad/worktrees/`)
— see `git worktree list`. All preserved for inspection; none deleted.

| Branch | Worktree | Head | Content |
|---|---|---|---|
| `main` | main checkout | `64a9dda` | baseline + audit docs + approved plan (untouched since) |
| `remediation/verified-findings` | `integration/` | `3200f21` | everything integrated (the merge candidate) |
| `fix/excel-correctness` (W-A) | `wa/` | `7885bd2` | T1, T7, T8 — fully integrated |
| `fix/query-correctness` (W-B) | `wb/` | `dbf432f` | T2, T3 — fully integrated |
| `fix/dependency-analysis` (W-C) | `wc/` | `610c174` | T4, T4b — fully integrated |
| `fix/security-storage` (W-D) | `wd/` | `ef93194` | T5, T6 — fully integrated |

Diff vs `main`: **42 files changed, +2,707 / −210**; 24 commits.

## Environment caveat (matters for any re-run)

The project venv (`.venv/`) has an **editable install pointing at the main
checkout's `src`**. Running tests inside any worktree MUST override it:

    cd <worktree> && PYTHONPATH=<worktree>/src \
      /Users/georgi/dev/micro_saas_exp/excel-auditor/.venv/bin/python -m pytest

Without the override you silently test `main`'s code, not the worktree's.

## Remaining steps (in order)

1. **AWAITING APPROVAL:** merge `remediation/verified-findings` into `main`
   (fast-forward is not possible; use a merge commit). Everything below waits
   on this.
2. Regenerate the **untracked** demo report artifacts in the main checkout
   (`demo_workbooks/audit_v2.json|html`, `comparison.json|html`) — they were
   never committed, so they could not be "regenerated and committed" during
   T10; they still carry old uuid ids and schema v1. After merge:
   `excel-auditor audit demo_workbooks/financial_model_v2.xlsx --json-output … --html-output …`
   and the equivalent `compare` (add `--generated-at` for reproducible bytes).
   Decide whether to start tracking them.
3. Optional cleanup once merged: delete the four `fix/*` branches and remove
   the scratchpad worktrees (`git worktree remove …`). Scratchpad worktrees
   vanish with the session anyway; run `git worktree prune` afterwards.

## Known limitations / accepted risks (carried into the final report)

- Table resolution assumes one header row + heuristic totals-row detection
  (inventory lacks `headerRowCount`/`totalsRowCount`). Optional follow-up:
  capture both in `workbook_inventory.py`.
- `DependencyImpact.has_unresolved_names` marker is JSON-only; HTML templates
  do not render it (rare condition post-T4b; documented in HANDOFF).
- `dependency_graph.py` imports the private `_split_sheet_prefix` from
  `parsing/reference_parser.py` — a rename there breaks loudly, not silently.
- Rename inference uses raw formula text: rename + mass row-insertion may fall
  below the 0.80 similarity bar and stay removed/added (consistent with the
  pre-existing documented insertion limitation). The rename mapper skips 3-D
  references (`Sheet1:Sheet3!A1`) — over-reports, never silent.
- Legacy SQLite DBs keep old report blobs until manually purged (documented in
  README and `storage/database.py`).
- API consumers: `workbook_id` format changed (uuid → 64-hex sha256) and two
  additive JSON fields appeared; signaled by `report_schema_version: "2"`.
