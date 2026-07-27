# Milestone 3 — Progress / Final State

Status: **complete and merged**. `milestone-3/integration` merged into `main`
and pushed as **`2e25893`** (2026-07-27). All §6 gates of
`docs/plans/milestone-3-prompt.md` passed; nothing was blocked.

## Final state

- **296 tests passing** (baseline 233 → 296; +63), ~4 s, ruff clean,
  mypy clean (74 source files, was 69).
- `report_schema_version = "3"` — exactly one bump, in
  `models/reports.py` (`REPORT_SCHEMA_VERSION`), referenced by both report
  models.
- Fresh `demo_workbooks/` artifacts on disk (gitignored, not committed):
  schema v3, pinned `--generated-at 2026-07-27T12:00:00Z`, comparison
  carries a live `rows_inserted` (start_row=7, count=2).
- Optional extras shipped: `excel-auditor[pdf]` (weasyprint>=61, macOS needs
  `brew install pango`) and `excel-auditor[mcp]` (mcp>=1.0). Core install
  requires neither; suite passes without them (importorskip).
- Optional T14b (`--notify-teams` on `audit`/`compare`) WAS built (everything
  else was green first, per the doc).

## Execution model

Same as the remediation: lead session + four parallel wave-1 workers in
worktrees (`feat/row-insertion`, `feat/table-metadata`, `feat/pdf-export`,
`feat/integrations`), each tested with `PYTHONPATH=<worktree>/src` (the
editable-install gotcha), merged sequentially into `milestone-3/integration`
with the FULL suite + ruff + mypy green after every merge, then a lead wave 2.

## Commits per task (as merged)

| Task | Worker | Commits | Content |
|---|---|---|---|
| P0 | lead | `2b0e7b1` | `[pdf]` / `[mcp]` extras in pyproject.toml |
| T11 | W-A | `9d0664e`, `144552b` | row signatures + SequenceMatcher alignment in `workbook_diff.py`, `ROWS_INSERTED`/`ROWS_REMOVED` enum members, schema v3, 13 new tests |
| T12 | W-B | `f8e58bb` | `TableInfo.header_row_count`/`totals_row_count`, D14 precedence in `schema.py`, totals-aware structured refs in `dependency_graph.py`, 9 new tests |
| T13 | W-C | `4e3ff3d` | `reporting/pdf_report.py`, print CSS + determinism-exemption footer, `ReportStore` pdf support, `?format=pdf`, CLI `--pdf-output`/`--pdf`, 20 new tests |
| T14 | W-D | `69b7736`, `8cc40b3` | `integrations/` package: Adaptive Cards, HMAC-validated `POST /integrations/teams`, incoming-webhook poster, FastMCP server (4 tools), config flags, `.env.example`, 19 new tests |
| T15+T14b | lead | `83071b3`, `6340de3` | docs reconciliation (README/HANDOFF/presentation), demo tour stop 6 (row-collapse), `--notify-teams` + 2 tests, stale-count fixes |
| merge | lead | `2e25893` | integration → main |

## Gate results

| Gate | Result |
|---|---|
| Full suite | **296 passed** (233 → 296), 0 failed/skipped on this machine |
| ruff / mypy | clean / clean (74 files) |
| Determinism | `tests/integration/test_determinism.py` green under `PYTHONHASHSEED` 0, 1, 42 (fixture now includes a row-inserted sheet so `rows_inserted` is byte-compared); PDF documented-exempt in the report footer, asserted by test |
| Schema version | exactly one bump to `"3"` (verified by grep); regenerated demo artifacts carry it |
| Flag-off parity | OpenAPI route list byte-identical to the pre-milestone baseline with Teams disabled |
| Offline | full suite green with `socket.connect` monkey-blocked via an injected pytest plugin |
| Docs | README / HANDOFF / presentation reconciled; three stale "233 tests" mentions found and fixed during the gate check |

## Lead decisions taken during execution (within work-order authority)

1. `tests/unit/test_reports.py` asserts the schema version but was in nobody's
   ownership list — its version assertions were assigned to W-A (entailed by
   D9; no collision).
2. W-C added three lines of static footer text to `base.html.j2` beyond
   "print CSS only" — required by its own acceptance criterion (the
   determinism exemption must be documented in the footer). Accepted.
3. `services.py` `LIMITATIONS` still said row insertions are not inferred;
   reworded in wave 2 to columns-only (flagged by W-A; no test depended on
   the string; demo artifacts regenerated afterwards).

## Behavior notes / intentional semantics

- **Pure row reorders fall back** to the positional diff (a swap reads as two
  `value_changed`, as before). Rationale: signature multisets identical ⇒
  nothing net-inserted; also preserves the pre-existing `test_reordered_rows`.
- The demo model's planted change #9 (two appended Summary rows) now collapses
  into one `rows_inserted` (start 7, count 2); the volatile/external-ref risks
  inside those rows still surface via the new-version audit (D8: "nothing is
  hidden, just not double-reported").
- `GET /reports/{id}?format=pdf` renders on demand from stored HTML when no
  `.pdf` was stored (side-effect free); 404 is for unknown reports, 422 for a
  missing `[pdf]` extra.
- Teams `status <unknown id>` returns HTTP 200 with a polite not-found card
  (a non-200 would render as a webhook error in the channel).
- MCP `ask_question` preserves the confirmation flow verbatim: ambiguity
  returns candidates; the caller re-invokes with `choices`.

## Deferred / known-imperfect (honest list)

- **Column-insertion inference** — explicitly out of scope; still surfaces as
  many shifted-formula changes (README/HANDOFF say so).
- **Mixed reorder** (a row moved *and* other rows inserted in one diff):
  the moved row reports as a remove+insert pair rather than value changes.
  Deterministic and defensible; only the pure-reorder case falls back.
- **`headerRowCount=0` tables**: openpyxl does not round-trip that attribute
  through a saved file, so the edge is tested by patching the loaded
  inventory; such tables refuse named-column resolution and keep the
  unknown-impact marker.
- **PDF byte-determinism**: exempt by design (D10); embedded creation
  metadata varies. JSON/HTML remain canonical evidence.
- **Teams file upload / Q&A over uploaded workbooks**: impossible via
  outgoing webhooks; requires a registered Azure bot — later milestone.
- Bulgarian report localization, Slack/Viber, hosted auth: untouched, as
  scoped.

## How a cold session resumes

Everything is on `main` @ `2e25893` (pushed). Worker branches and
`milestone-3/integration` exist locally only; all fully merged. Demo
artifacts are regenerable with:
`.venv/bin/python scripts/generate_demo_workbooks.py demo_workbooks` then
`excel-auditor audit|compare ... --generated-at 2026-07-27T12:00:00Z
--json-output/--html-output` into `demo_workbooks/`. The narrated demo is
`.venv/bin/python scripts/demo_tour.py` (stop 6 = the T11 row-collapse).
