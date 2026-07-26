# Milestone 3 — Implementation Prompt (multi-worker execution)

You are the lead of a multi-worker terminal session implementing the next
milestone of **excel-auditor**. This document is the complete work order:
scope, approved decisions, worker split, file ownership, task specs with
acceptance criteria, and verification gates. Follow it the way the
remediation plan (`docs/audits/remediation_plan.md`) was followed — that
execution model worked; reuse it.

## 0. Baseline and ground rules

- **Baseline:** `main` @ `26ce270` — 233 tests pass (~3 s), `ruff check src
  tests` clean, `mypy src/excel_auditor` clean (69 files),
  `report_schema_version = "2"`.
- **Remote:** GitHub `https://github.com/Zoreo/excel_audit.git` (remote name
  is `main`). Do not push worker branches unless asked; the integration
  branch is pushed by the lead at the end.
- **Branches:** integration `milestone-3/integration`; workers
  `feat/row-insertion` (W-A), `feat/table-metadata` (W-B), `feat/pdf-export`
  (W-C), `feat/integrations` (W-D).
- **Worktrees:** create per-worker worktrees under the session scratchpad.
  ⚠️ The venv has an editable install pointing at the main checkout — inside
  any worktree ALWAYS run tests as
  `PYTHONPATH=<worktree>/src <repo>/.venv/bin/python -m pytest`, otherwise
  you silently test `main`'s code. This bit us last time.
- Every merge into the integration branch must leave the **full** suite
  green, ruff clean, mypy clean — not just the task's own tests.
- Nobody edits `tests/conftest.py`, `README.md`, `HANDOFF.md`,
  `docs/presentation.md`, or `demo_workbooks/` except the lead (wave 2). New
  fixtures go in the task's own test files.
- A worker that needs a file outside its ownership list stops and escalates
  to the lead. No speculative refactors, no drive-by cleanup.
- All tests run **offline** — no network calls anywhere (Teams/MCP tests use
  mocked transports / in-process calls).
- No secrets in the repo, ever. Integration credentials only via env vars,
  documented in `.env.example` with fake placeholder values.

## 1. Scope

Four work streams, in priority order:

1. **T11 — Row-insertion inference in the diff** (the top roadmap item; the
   biggest known source of review noise).
2. **T12 — Exact table metadata** (the follow-up flagged during the T4b
   remediation: capture Excel Table header/totals row counts so table
   resolution stops being heuristic when real metadata exists).
3. **T13 — PDF export** (roadmap item; buyers asked for reports they can
   file/email).
4. **T14 — Integration scaffolding: MCP server + Microsoft Teams webhooks**
   (deliberately minimal — "a port other systems can plug into", not a bot
   platform; see the reality check in §3/D11).

**Explicitly out of scope (do not build):** column-insertion inference,
Azure Bot Service registration, Teams file-upload handling, Slack/Viber
adapters, report translation to Bulgarian, hosted auth/accounts, any
query-subsystem restructuring, PDF pixel-perfection.

## 2. Waves

```
Wave 0 (lead, first commit on integration branch)
  P0  pyproject extras pre-added:  [pdf] -> weasyprint>=61 ;  [mcp] -> mcp>=1.0
      (single owner of pyproject.toml for the whole milestone = lead)
Wave 1 (parallel, disjoint files)
  T11  W-A  row-insertion inference + schema v3        ─┐
  T12  W-B  exact table metadata                        │ independent
  T13  W-C  PDF export                                  │ of each other
  T14  W-D  MCP server + Teams webhooks                ─┘
Wave 2 (lead, sequential)
  T15  docs reconciliation, demo artifact regeneration (schema v3),
       optional CLI notify wiring (T14b, only if time allows),
       adversarial sweep + final gates
```

## 3. Approved decisions (continue the D-numbering from remediation)

| # | Decision |
|---|---|
| **D7** | Row alignment uses per-row signatures + `difflib.SequenceMatcher` (stdlib, deterministic). A row signature = tuple over the sheet's used columns of (normalized formula if formula else a typed value marker). Alignment is applied per matched sheet pair **only when** the sheet has ≥ 5 data rows on both sides **and** the matcher's ratio ≥ 0.60; otherwise fall back to today's positional diff — byte-identical behavior for below-threshold sheets. **Rows only**; column alignment is deferred. |
| **D8** | Cells on inserted/removed rows are **not** emitted as individual cell changes. They are carried by new structural change types `ROWS_INSERTED` / `ROWS_REMOVED` (per contiguous run: sheet, start row, count, up to 5 sample cell previews). Aligned-but-shifted rows whose content is unchanged produce **zero** cell changes; genuinely edited aligned rows diff normally at their aligned coordinates. The audit of the new version still covers risks inside inserted rows — nothing is hidden, it is just not double-reported. |
| **D9** | `report_schema_version` → **"3"** (new structural types + suppression semantics + T12's additive fields). Exactly one bump, owned by W-A in `models/reports.py`; the lead verifies no second bump sneaks in. |
| **D10** | PDF via **WeasyPrint** behind the optional extra `excel-auditor[pdf]`. Core install must not require it: import lazily, and if missing raise a clean `ExcelAuditorError("PDF export requires: pip install 'excel-auditor[pdf]'")`. PDFs are **excluded from the byte-determinism guarantee** (embedded creation metadata); JSON/HTML remain the canonical evidence artifacts — say so in the report footer and HANDOFF. macOS system deps: `brew install pango`; tests must `pytest.importorskip("weasyprint")` so the suite stays green without it. |
| **D11** | Teams MVP = **webhooks only**, both directions, zero Microsoft registration needed to develop or test: (a) an *incoming-webhook poster* — given a report ref + summary, POST an Adaptive Card (risk level, drivers, link) to `EXCEL_AUDITOR_TEAMS_INCOMING_WEBHOOK_URL`; (b) an *outgoing-webhook endpoint* `POST /integrations/teams` that validates the HMAC-SHA256 `Authorization` header against `EXCEL_AUDITOR_TEAMS_HMAC_SECRET` and supports exactly two commands parsed from the mention text: `status <report_id>` (card with that report's stored summary) and `help`. Reality check to encode in docs: outgoing webhooks **cannot receive file attachments** — Q&A-over-Teams on uploaded workbooks requires a real Azure bot and is explicitly a later milestone. |
| **D12** | MCP server via the official Python `mcp` SDK (FastMCP), **stdio transport**, runnable as `python -m excel_auditor.integrations.mcp_server`. Tools: `audit_workbook(path)`, `compare_workbooks(old_path, new_path)`, `inspect_schema(path)`, `ask_question(path, question, choices?)` — thin wrappers over `services.py`/`query_service.py` returning compact JSON (status/risk level/key counts + report file paths and URLs). Paths are local-filesystem paths (local-server POC; remote upload handling is a later milestone). Tools must never bypass the confirmation flow: ambiguity returns the candidates, the caller re-invokes with `choices`. |
| **D13** | All integration code lives in a new package `src/excel_auditor/integrations/` and contains **zero analysis logic** — services calls only. The Teams router is mounted into the FastAPI app only when `EXCEL_AUDITOR_TEAMS_ENABLED=1`; with the flag off, the app is byte-for-byte unaffected. |
| **D14** | T12 precedence rule: when an Excel `Table` object covers a detected block, its `headerRowCount` / `totalsRowCount` (coerce `None` → 0; openpyxl defaults `headerRowCount=1, totalsRowCount=None`) **override** the heuristic header/totals detection for that block, and the table note says "exact (from Excel Table metadata)" vs the existing heuristic notes. The dependency graph's structured-reference resolution (`Table1[Col]`) excludes totals rows from the data range. Non-Table blocks keep today's heuristics untouched. |

## 4. Worker groups and file ownership

One owner per file per wave. Paths relative to `src/excel_auditor/` (source)
and `tests/` (tests).

| Worker | Task | Owns (source) | Owns (tests) |
|---|---|---|---|
| **W-A diff** | T11 | `analysis/workbook_diff.py`, `analysis/review.py`, `models/comparison.py`, `models/enums.py` (new StructuralChangeType members only), `models/reports.py` (version constant only) | `unit/test_row_insertion.py` (new), `unit/test_workbook_diff.py`, `unit/test_messy_workbooks.py` (upgrade `test_inserted_row`), `integration/test_determinism.py` (intentional golden updates) |
| **W-B inventory/schema** | T12 | `analysis/workbook_inventory.py`, `models/workbook.py` (TableInfo fields), `analysis/schema.py`, `analysis/dependency_graph.py` (structured-ref totals leg only) | `unit/test_table_metadata.py` (new), `unit/test_schema_detection.py`, `unit/test_dependency_graph.py` |
| **W-C reporting** | T13 | `reporting/pdf_report.py` (new), `reporting/templates/base.html.j2` (print CSS only), `storage/reports.py` (pdf path), `api/routes/public_reports.py` (`format=pdf`), `cli.py` (`--pdf-output` flags), `errors.py` (only if a new error type is needed) | `unit/test_pdf_report.py` (new), `unit/test_report_store.py`, `integration/test_api.py` (pdf param cases) |
| **W-D integrations** | T14 | `integrations/` (new: `__init__.py`, `teams.py`, `cards.py`, `mcp_server.py`), `api/app.py` (conditional mount only), `config.py` (Teams/MCP settings), `.env.example` | `integration/test_teams_webhook.py` (new), `unit/test_mcp_tools.py` (new) |
| **Lead** | P0, T15 | `pyproject.toml`, `README.md`, `HANDOFF.md`, `docs/presentation.md`, `demo_workbooks/*`, `scripts/*` | full-suite gates, cross-feature sweep |

Deconfliction notes:

- `models/enums.py` is W-A's **only** for adding the two enum members —
  nothing else in that file moves.
- W-C does **not** touch report models: the PDF is a store/render concern
  (`ReportRef` gains `pdf_path: Path | None`), not a schema field.
- `api/app.py` belongs to W-D; W-C's API surface is entirely inside
  `public_reports.py`.
- T14b (optional `--notify-teams` CLI flag) would collide with W-C on
  `cli.py`, so it is **wave 2, lead-executed, optional** — skip without guilt.

## 5. Task specifications

### T11 — Row-insertion inference *(W-A, wave 1)*

- **Objective:** implement D7/D8 in `_diff` flow of `workbook_diff.py`:
  build row signatures over each matched sheet pair, align with
  `SequenceMatcher`, emit `ROWS_INSERTED`/`ROWS_REMOVED` structural changes
  for insert/delete opcodes, diff `equal`/`replace` regions at aligned
  coordinates, and fall back wholesale to the current positional diff when
  the D7 gate fails. Bump `report_schema_version` to `"3"`.
- **Interplay warnings:** alignment runs *after* sheet matching and applies
  to inferred-rename pairs too — do not touch the D3 rename thresholds.
  Total-range formulas that grow (`SUM(D2:D11)` → `SUM(D2:D12)`) remain a
  normal `formula_changed` at the total's aligned position. Review items
  (`analysis/review.py`) must count the new structural types in summaries
  but need no per-cell entries for suppressed adds.
- **Acceptance criteria:**
  - 10-month vs 11-month model (one row inserted mid-table): exactly one
    `ROWS_INSERTED` (correct row + count), the total-range
    `formula_changed`, **zero** `value_added`/`formula_added` flood from the
    shifted rows; review items reflect the collapse.
  - Insert + edit: one inserted row **plus** the genuinely edited aligned
    cell reported at its new coordinate with correct old/new values.
  - Row deleted: symmetrical `ROWS_REMOVED` with sample previews.
  - Below-gate sheet (4 data rows) or dissimilar sheets (ratio < 0.60):
    output byte-identical to today's behavior.
  - Two runs across `PYTHONHASHSEED` values: byte-identical reports
    (determinism suite updated intentionally for schema v3, then green).
  - `unit/test_messy_workbooks.py::test_inserted_row` strengthened from
    "no false positives" to asserting the collapse.
- **Must not modify:** `analysis/schema.py`, `workbook_inventory.py`,
  `dependency_graph.py`, `storage/*`, `api/*`, `cli.py`, `reporting/*`.

### T12 — Exact table metadata *(W-B, wave 1)*

- **Objective:** capture `headerRowCount`/`totalsRowCount` from openpyxl
  `Table` objects into `TableInfo` (`models/workbook.py`,
  `workbook_inventory.py`); apply D14 precedence in `analysis/schema.py`
  (exact override + note); exclude totals rows from structured-reference
  data ranges in `dependency_graph.py`.
- **Acceptance criteria:**
  - A workbook with a real Excel Table (`totalsRowCount=1`): schema table
    shows the exact header/totals split, the totals row is excluded from
    `row_count` and from query sums, and the note says "exact".
  - `=SUM(SalesTbl[Amount])` dependency edges stop before the totals row.
  - Table with `totalsRowCount=None` behaves as totals=0 (no crash).
  - Plain non-Table blocks: schema output unchanged vs baseline (regression
    tests untouched and green).
- **Must not modify:** `workbook_diff.py`, `analysis/review.py`,
  `models/comparison.py`, `models/reports.py`, `analysis/query.py`,
  `resolution.py` (escalate if resolution seems to need awareness — it
  shouldn't; it consumes `TableSchema`, which W-B already shapes upstream).

### T13 — PDF export *(W-C, wave 1)*

- **Objective:** `reporting/pdf_report.py` with `render_pdf(html: str) ->
  bytes` implementing D10 (lazy import, clean error); print CSS block in
  `base.html.j2` (`@media print`: A4, sane page breaks before `h2`,
  no-scroll tables); `ReportStore.save(..., report_pdf: bytes | None)`
  writing `{id}.pdf`; `GET /reports/{id}?format=pdf`
  (`application/pdf`, 404 when absent); CLI `--pdf-output PATH` +
  `--pdf`-into-store flag on `audit`/`compare`/`schema`/`query`/`ask`.
- **Acceptance criteria:**
  - With the extra installed: audit produces a valid PDF (starts with
    `%PDF-`, non-trivial size) at the explicit path and in the store;
    `?format=pdf` serves it; store `load` path validation covers `.pdf`.
  - Without the extra: CLI prints the actionable install hint (exit 2), API
    returns 422 with the same message, HTML/JSON flows completely
    unaffected.
  - Determinism suite untouched and green (PDF exempt per D10 — assert the
    exemption is documented in the report footer text, not silently).
  - Suite passes on a machine **without** weasyprint (importorskip).
- **Must not modify:** `models/*`, `services.py`, `query_service.py`,
  `api/app.py`, `integrations/*`.

### T14 — MCP server + Teams webhooks *(W-D, wave 1)*

- **Objective:** implement D11/D12/D13.
  - `integrations/cards.py`: pure function building the Adaptive Card dict
    from (kind, risk level, drivers, url) — unit-testable, no I/O.
  - `integrations/teams.py`: `post_report_card(settings, ref, summary)`
    using a pluggable transport (injected callable wrapping
    `urllib.request`/httpx — tests inject a recorder, never hit the
    network); FastAPI router with `POST /integrations/teams` doing
    constant-time HMAC validation → command parse (`status <id>`, `help`)
    → card response; unknown command → help card; bad/missing HMAC → 401.
  - `integrations/mcp_server.py`: FastMCP with the four D12 tools; each tool
    validates the path exists, calls the service, persists reports via
    `ReportStore`, returns the compact JSON. `ask_question` surfaces
    `needs_confirmation` candidates verbatim.
  - `config.py`: `teams_enabled`, `teams_hmac_secret`,
    `teams_incoming_webhook_url` (+ `.env.example` entries with fake
    values); `api/app.py` mounts the router only when enabled.
- **Acceptance criteria:**
  - App with flag off: OpenAPI route list identical to baseline.
  - Valid HMAC + `status <existing id>` → 200 card containing risk level and
    report URL; invalid HMAC → 401; unknown id → polite "not found" card.
  - Card poster sends exactly one POST to the configured URL (recorded by
    the fake transport) with a schema-valid Adaptive Card payload.
  - MCP: in-process tool invocation of `audit_workbook` on a demo file
    returns risk level + an existing report path; `ask_question` on the
    dual-revenue fixture returns candidates, then the answer when `choices=[1]`.
  - Zero network access in tests; `mcp` import guarded so the core suite
    passes without the extra (importorskip in its tests).
- **Must not modify:** `services.py`, `query_service.py`, `storage/reports.py`
  (consume its public API only), `cli.py`, `reporting/*`.

### T15 — Lead wave 2

1. Re-run everything (order: full suite → ruff → mypy → determinism suite →
   live CLI E2E on demo workbooks → MCP smoke → Teams endpoint smoke with
   flag on/off).
2. Regenerate `demo_workbooks/` artifacts with a pinned `--generated-at`
   (schema v3). Optionally extend `scripts/demo_tour.py` with a sixth stop
   ("row inserted → one structural change, not forty value changes") — it's
   the best sales artifact for T11.
3. Docs pass: README (roadmap: mark row-insertion + PDF delivered, add
   integrations note + Teams file-upload caveat), HANDOFF (schema v3,
   PDF determinism exemption, integrations section, test count), presentation
   FAQ ("Does it integrate with what we use?" answer gets the MCP/webhook
   reality), `.env.example` sanity.
4. Cross-feature fixtures: inserted row **+** determinism byte-compare;
   Excel-Table totals row **+** `ask` sum (no double count); PDF of a
   comparison containing `ROWS_INSERTED`.
5. Optional T14b (only if everything above is green): `--notify-teams` flag
   on `audit`/`compare` calling `post_report_card`; skip freely.

## 6. Final verification gates (lead, before merging to main)

| Gate | Requirement |
|---|---|
| Full suite | all green (expected ≈ 233 + new; record the number) |
| ruff / mypy | clean / clean |
| Determinism | JSON+HTML byte-identical across `PYTHONHASHSEED` runs; PDF documented-exempt |
| Schema version | exactly one bump to `"3"`; demo artifacts carry it |
| Flag-off parity | Teams disabled ⇒ route list byte-identical to baseline |
| Offline | `pytest` passes with network disabled |
| Docs | README/HANDOFF/presentation consistent with shipped behavior; no stale counts (this went stale last time — check explicitly) |

Deliver at the end: an updated `docs/audits/`-style progress file
(`docs/plans/milestone-3-progress.md`) recording state, commits per task,
gate results, and anything deferred — written so the next session can resume
cold.
