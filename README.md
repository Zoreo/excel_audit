# excel-auditor

**Git diff, risk analysis and verified Q&A for Excel financial and
operational models.** Terminal-first, with stored HTML/JSON reports served at
local URLs, a thin API, and a minimal demo web page.

## The problem this solves

If a spreadsheet drives real decisions in your business — a budget, a cash-flow
forecast, a pricing model, a loan book — you have three problems that grow
with every edit:

1. **Silent errors.** A formula overwritten with a hardcoded number, a total
   that stopped one row short, a SUM that includes itself, a cell nobody knows
   is driving the P&L. Excel doesn't warn you; the model keeps producing
   confident numbers that are quietly wrong.
2. **Version anxiety.** `model_v7_FINAL(2).xlsx` lands in your inbox. What
   actually changed since the version the board approved? Which changed cell
   reaches the numbers you present? Eyeballing two workbooks doesn't scale
   past a dozen cells, and Excel has no diff.
3. **Answers you can't stand behind.** "What's the total exposure over 500k?"
   Someone filters, sums, pastes the number into a deck. Was it the right
   column? The right filter? Nobody can reproduce how the number was made.

excel-auditor is a deterministic engine that treats a workbook the way an
auditor would: **audit** one version for structural risk, **diff** two
versions down to the cell with downstream-impact analysis, and answer
questions over the data with full **provenance** — every number traceable to
sheet, table, column, filter, and row count. When something is ambiguous it
asks you; when a question can't be answered safely it says so. It never
guesses, and no LLM ever touches a number.

Built for finance teams, accountants, auditors, and anyone doing diligence on
spreadsheets they didn't build — to *assist human reviewers*, not to replace
them.

Four workflows:

1. **Audit** one `.xlsx` workbook for structural risk.
2. **Compare** two versions: formula changes, structural changes, hidden
   content, external dependencies, downstream impact — unified into review items.
3. **Schema**: detect tables, header rows, column names and types (dates,
   currency, percentages, booleans, categoricals), totals and missing values.
4. **Query / Ask**: deterministic aggregations over detected tables — either
   fully structured (`query`) or constrained free text in English/Bulgarian
   (`ask`), always answered with full provenance and user confirmation when
   columns are ambiguous.

The engine is **fully deterministic** — no LLM is involved in detection or in
computing any number. The optional intent-parsing layer only maps wording to a
validated structured query (a rule-based EN/BG parser ships by default; an LLM
provider can be slotted in behind the same interface). Built to *assist human
reviewers*, not to claim a workbook is financially or mathematically correct.

## See it work in 60 seconds

```bash
.venv/bin/python scripts/demo_tour.py
```

The tour builds small workbooks reproducing classic silent-error situations
and shows the engine's behavior on each. Highlights from the actual output:

```
Q: "What is the total amount?"  ->  status: needs_confirmation
   choice 1: Amount (column B) (number)
   choice 2: Amount (column C) (number)
   with choice 1: 1,900   [column: Amount (B), status: verified]
   with choice 2: 19,000  [column: Amount (C), status: verified]

Q: "show rows where amount is over budget"  (no number to filter on)
   -> REFUSED: The question asks for a numeric threshold, but no number
      could be extracted from it.

   EA-CIR-001 at Scratch!D11: Circular reference      (=SUM(D1:D11) in D11)

Structural: Worksheet 'Inputs' appears to have been renamed to
            'Assumptions' (inferred from content similarity).
Cell edit:  Assumptions!A1 0.05 -> 0.08 [severity: medium]
   downstream impact: 8 downstream cells, sheets: Assumptions, Summary

Two audit runs byte-identical: True
workbook_id == sha256(file):   True
```

A bank export with two columns both named `Amount` gets a confirmation prompt
instead of a silent 10×-wrong "verified" answer. A threshold question with
nothing to filter on is refused instead of returning everything. A SUM that
includes its own cell is flagged. A renamed-then-edited sheet is matched by
content, the hidden edit surfaced **with its blast radius through a defined
name**, and the rename itself produces zero diff noise. And the same file
always produces the same bytes, addressed by its content hash.

`excel-auditor demo` additionally generates two full demo workbooks with ten
planted anomalies plus complete audit/comparison reports in `./demo_workbooks`.

## Why you can trust the output

These are engineering guarantees, each enforced by regression tests:

- **Ambiguity is never resolved silently.** Two columns sharing a header are
  physically distinct candidates; you choose, identified by column letter.
- **Refuse rather than be wrong.** A question that can't be mapped to a safe,
  fully-specified computation returns `cannot_answer` with the reason — never
  a plausible-looking number for a different question.
- **Every answer carries provenance**: workbook, sheet, table range, chosen
  columns, applied filters, rows included/excluded, and assumptions.
- **Reports are evidence.** Identical input produces byte-identical output;
  `workbook_id` is the file's SHA-256, so a report is verifiably tied to the
  exact file it describes. Inject `--generated-at` and diff reports directly.
- **Incomplete analysis is visible.** If an analysis rule fails, the report
  says so (`failed_rules` + a coverage warning) instead of looking clean.
- **Impact analysis sees through defined names and tables.** `=GrowthRate*2`
  and `=SUM(Table1[Amount])` carry real downstream-impact counts; anything
  genuinely unresolvable is marked *unknown* rather than reported as zero.
- **Your files stay yours.** Local-only processing, uploads deleted on every
  exit path (TTL sweep for abandoned flows), a purge that actually purges,
  and no external service ever sees workbook content.

## What it detects

**Single-workbook audit** (`audit`):

| Rule | What it flags |
|---|---|
| EA-PAT-001 | Formula overwritten with a hardcoded value inside a repeated range |
| EA-PAT-002 | Formula inconsistent with the surrounding pattern (incl. wrong-row copies, with shift inference) |
| EA-PAT-003 | Missing formula inside a repeated block (fully blank spacer rows/columns are recognized as layout and skipped) |
| EA-RNG-001 | Aggregation range that excludes an adjacent populated cell (stale totals) |
| EA-RNG-002 | Formulas referencing blank cells inside the used range |
| EA-RND-001 | Displayed figures that don't add up (cent-level rounding drift between a total and its rounded components, with the residue-carrying cells named) |
| EA-RND-002 | Excel's "Set precision as displayed" enabled (permanently rounds stored values on save) |
| EA-REF-001 | Broken references (`#REF!`) in formulas and named ranges |
| EA-ERR-001 | Error values (`#DIV/0!`, `#VALUE!`, …; `#N/A` reported at lower severity) |
| EA-VOL-001 | Volatile functions (`OFFSET`, `INDIRECT`, `NOW`, `TODAY`, `RAND`, `RANDBETWEEN`) |
| EA-HRD-001 | Hardcoded numeric literals inside formulas |
| EA-HID-001/002 | Hidden / very-hidden sheets; hidden rows & columns containing data |
| EA-EXT-001 | External workbook dependencies (workbook-level links **and** formula-level references, unified into one consistent count) |
| EA-OPQ-001..003 | Macros present, external data connections, protection (informational) |
| EA-CIR-001 | Circular references (cycle-safe graph traversal) |
| EA-CPX-001 | Unusually long formulas |

Every finding carries a stable rule id, severity (`info…critical`), a separate
confidence level (`low/medium/high`), the exact workbook location, evidence,
and a suggested review action. Severity ≠ confidence: severity is potential
business impact, confidence is how likely the finding is genuinely anomalous.
When one rule fires on 4+ cells of the same sheet at medium-or-lower severity,
the findings collapse into a single grouped finding (count + cell list) so the
report stays readable; high/critical findings always stay per-cell.

**Two-version comparison** (`compare`) additionally classifies every changed
cell as one of: `formula_changed`, `value_changed`, `formula_to_constant`,
`constant_to_formula`, `formula_added/removed`, `value_added/removed`,
`formatting_only` — plus structural changes (sheets added/removed/renamed/
reordered/visibility, named ranges, merged ranges, hidden rows/columns,
external links, macros). Formulas are compared **structurally**: `=B2*C2` in
D2 and `=B3*C3` in D3 normalize to the same relative pattern (`RC[-2]*RC[-1]`),
so copied rows don't drown the report in noise, while a genuinely divergent
formula stands out. Each impactful change is annotated with its downstream
dependents (direct, transitive, affected sheets, and whether it reaches
output-like cells such as Summary/P&L totals).

The primary output of a comparison is the **review items** list: each item
unifies the cell change and any audit findings at the same location under a
single reconciled severity/confidence, so one underlying problem is never
listed twice with two different severities. The reconciled severity is also
written back to the raw `cell_changes`, so every representation agrees.

**Risk level, not a score.** Reports carry a categorical risk level
(`minimal / low / elevated / high / critical`) with an explicit rule stated in
the report itself — the level is simply the highest severity present — plus
the drivers behind it ("5 high-severity review items…"). There is deliberately
no numeric score inviting false precision.

## Install & run

Requires Python ≥ 3.12.

```bash
cd excel-auditor
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### CLI

```bash
# generate demo workbooks + full comparison & audit reports in ./demo_workbooks
excel-auditor demo

excel-auditor audit workbook.xlsx
excel-auditor compare old.xlsx new.xlsx
excel-auditor schema sales.xlsx

# deterministic structured query
excel-auditor query sales.xlsx \
  --function sum --value-column Оборот \
  --filter-column Дата --filter-op year_equals --filter-value 2025

# constrained free-text question (EN + BG); asks for confirmation on ambiguity
excel-auditor ask sales.xlsx "Какъв е общият оборот за 2025?"
excel-auditor ask sales.xlsx "What was total revenue in 2025?" --choice 1 --no-input

excel-auditor serve            # API + stored-report URLs + demo web pages
```

Every analysis command stores JSON+HTML in the report store and prints both
the local file path and the `http://localhost:8000/reports/{id}` URL (live
once `serve` runs). Common flags: `--output-dir`, `--json-output`,
`--html-output`, `--open`, `--verbose`; `query`/`ask` add `--choice N`
(pre-answer a confirmation), `--no-input`, `--reference-date YYYY-MM-DD`.
Exit codes: 0 ok, 2 error/cannot-answer, 3 confirmation required.

### API

```bash
excel-auditor serve
# or: uvicorn --factory excel_auditor.api.app:create_app --reload
# or: docker compose up --build
```

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/audits` (multipart `file`) | Audit one workbook |
| `POST /api/v1/comparisons` (multipart `old_file`, `new_file`) | Compare two versions |
| `POST /api/v1/schema` (multipart `file`) | Table/column-type detection |
| `POST /api/v1/queries` (multipart `file` + `query` JSON or `question` text, optional `choices`) | Deterministic query; returns `needs_confirmation` + candidates on ambiguity |
| `GET /api/v1/jobs/{job_id}` | Job status + summary |
| `GET /api/v1/reports/{job_id}?format=json\|html` | Job-scoped report |
| `GET /reports/{report_id}?format=json\|html` | Stored report by public id |
| `GET /health` | Liveness |

A minimal server-rendered demo UI lives at `/` (audit, compare, ask — the ask
form walks through column confirmation). Processing is synchronous for
POC-sized files; results are stored by id so background workers can be added
without changing clients. Report ids are random hex — fine for local use;
production needs authentication (documented limitation).

### Tests & checks

```bash
.venv/bin/python -m pytest      # 311 tests
.venv/bin/ruff check src tests
.venv/bin/mypy src/excel_auditor
```

Test fixtures are *generated*, not binary blobs: `financial_model_v2.xlsx`
plants ten deliberate anomalies (hardcoded formula, wrong-row copy, shrunk
total range, hidden sheet, external reference, changed assumption,
formatting-only change, `#REF!`, volatile function, high-impact formula
change) and the suite asserts each is detected.

A dedicated messy-workbook suite covers realistic layouts: blank spacer rows,
several blocks per sheet, merged headers, horizontal formula copies, Cyrillic
(Bulgarian) sheet names, inserted and reordered rows, duplicated blocks,
intentionally hardcoded override cells, named-range formulas, and modern
functions (`IF`, `INDEX/MATCH`, `XLOOKUP`, `SUMIFS`) including structured
table references.

The query/ask suites use generated sales fixtures with Bulgarian, English and
transliterated headers, gross + net revenue columns (forcing confirmation),
currency number formats, blank values, subtotal rows (excluded from sums,
verified), forecast/actual variants and multiple date columns.

Adversarial suites added with schema v2 cover: golden byte-comparison of
JSON/HTML reports across subprocesses with different hash seeds; duplicate
column headers through resolution, frames, filters and group-by; threshold
phrasing (EN/BG, thousands separators, refusal cases); self-referencing and
name-routed circular formulas; defined-name/table resolution edge cases
(multi-area, constants, scope shadowing, `#REF!`); inferred sheet renames
(similarity thresholds, ambiguity, no-false-pairing); crashed-rule surfacing;
report-store collision/legacy-id behavior; the full web-ask upload lifecycle
(leak regressions, confirmation round-trip, TTL sweep); and cross-fix
interaction tests combining the above.

## Architecture

```
src/excel_auditor/
├── models/          # typed pydantic models: inventory, findings, changes,
│                    # reports, schema, queries (strict intent model)
├── parsing/         # zip-safe loader, tokenizer wrapper, A1 reference parser,
│                    # R1C1-style formula normalizer
├── analysis/
│   ├── workbook_inventory.py   # openpyxl -> typed inventory
│   ├── workbook_diff.py        # structural + cell-level comparison
│   ├── pattern_detection.py    # repeated-range inconsistency scanning
│   ├── dependency_graph.py     # cell graph, BFS impact, Tarjan cycles
│   ├── review.py               # unifies changes + findings into review items
│   ├── severity.py             # documented severity/confidence + risk level
│   ├── schema.py               # table/header/column-type detection
│   ├── resolution.py           # name normalization, BG/EN aliases, resolution
│   ├── query.py                # deterministic pandas execution + provenance
│   └── rules/                  # one independently-testable rule per concern
├── llm/             # IntentParser protocol; rule-based EN/BG parser; mock.
│                    # LLM providers plug in here and never touch numbers.
├── reporting/       # JSON + HTML (Jinja2, autoescaped) reports
├── api/             # FastAPI app (thin; delegates to services)
├── web/             # minimal server-rendered demo pages
├── storage/         # SQLite job store + file-based report store (ids -> URLs)
├── services.py      # audit_workbook / compare_workbooks
├── query_service.py # inspect_schema / answer_query (confirmation-aware)
├── demo.py          # demo workbook generator (also used by tests)
└── cli.py           # argparse CLI using the same services as the API
```

The core engine is independent of FastAPI, the CLI and any LLM SDK — it works
as a plain Python package. The risk-level rule is documented in
`analysis/severity.py` and repeated in every report so the assessment is
verifiable by hand. Every workflow follows: validated structured request →
deterministic engine → result with provenance → HTML/JSON report; wording is
the only place a language model may ever participate.

## Security & privacy

- Macros are **never executed**; only their presence is reported.
- External links are treated as untrusted text and never fetched.
- Zip-bomb defenses: decompressed-size cap, compression-ratio cap, entry-count
  cap, entry-path traversal checks, workbook-part verification.
- Uploads are streamed to an isolated per-request directory with randomized
  names and **deleted on every exit path, including errors** (verified by
  test). The one exception: the web ask flow's confirmation step parks the
  upload until the user confirms or the question fails, after which it is
  deleted; abandoned confirmations are swept by a TTL cleanup
  (`EXCEL_AUDITOR_WEB_UPLOAD_TTL_SECONDS`, default 1 hour) that runs at
  startup and on each ask submission. Client filenames are used for display
  only.
- Job metadata lives in a local SQLite database (`data/`); report bodies are
  stored **only** under `artifacts/reports/{report_id}.json|.html`. To purge a
  report, delete those two files — it then disappears from both
  `/api/v1/reports/{job_id}` and `/reports/{report_id}` (verified by test).
  Databases created before schema version 2 may still carry legacy
  `report_json`/`report_html` blob columns; they are tolerated and ignored —
  to purge a legacy report, also clear its blobs
  (`UPDATE jobs SET report_json = NULL, report_html = NULL WHERE id = ?;`
  then `VACUUM;`). No workbook content is sent to any external service, and
  cell contents are not logged.
- All workbook-derived content is HTML-escaped in reports (verified by test).

## Known limitations

- Formulas are analyzed structurally; the workbook is not recalculated. Query
  results use the values Excel last saved (openpyxl-generated files cache none
  for formula cells).
- Column insertions are not inferred — they appear as many shifted-formula
  changes (normalized-equal shifts are downgraded to `info`). Row
  insertions/removals *are* inferred and collapse into single structural
  changes (schema v3).
- `.xls`, Google Sheets, VBA analysis, and password-protected files are out of scope.
- External-reference detection is formula-text based; link *targets* are read
  from workbook metadata when available.
- Very large ranges in the dependency graph are truncated (configurable cap).
- Schema/table detection is heuristic (documented per report); tables without
  a recognizable header row are not queryable.
- The rule-based intent parser covers the supported question types in English
  and Bulgarian only; anything else is rejected with a clear limitation
  message rather than guessed at.
- Report URLs are unauthenticated random ids — local POC only.

## What's new — report schema v2 (2026-07)

An independent audit of the codebase was commissioned, its findings verified
and re-ranked, and every confirmed blocker remediated and regression-tested
(141 → 233 tests). The full paper trail lives in `docs/audits/`
(`ranked_report_findings.md`, `remediation_plan.md`, `remediation_progress.md`).
What changed, in user terms:

- **Deterministic reports.** `workbook_id` is now the file's full SHA-256
  (was a random uuid); structural changes emit in stable order; `generated_at`
  is injectable (`--generated-at`) — identical input now yields byte-identical
  reports. JSON carries `report_schema_version: "2"` so consumers can detect
  the id-format change.
- **Duplicate column headers are confirmed, not guessed** — previously the
  later column silently overwrote the earlier one and the answer came back
  `verified` from the wrong column.
- **Numeric-threshold questions filter or refuse** — previously "over 500"
  could be silently dropped and the unfiltered result returned as `verified`.
- **Self-referencing circular formulas are detected** (`=SUM(D1:D11)` in
  `D11`), including cycles routed through defined names.
- **Defined names and structured table references resolve into the dependency
  graph** — named inputs now show their true downstream impact instead of
  zero; unresolvable tokens are marked *unknown*, never mis-resolved.
- **Renamed-and-edited sheets are matched by content similarity** — the edits
  are reported (previously they vanished), the rename is labeled inferred, and
  pure renames no longer flood the diff with bogus formula changes.
- **Crashed analysis rules are visible in the report** (`failed_rules`,
  limitations, risk drivers, HTML warning) instead of the report looking
  clean.
- **Upload lifecycle hardened**: the web ask flow deletes the uploaded file on
  every exit path (errors included) except the confirmation round-trip, with
  a TTL sweep for abandoned flows; report bodies live in exactly one place so
  the documented purge really purges; report ids widened to 128-bit with
  no-overwrite guarantees.

See `HANDOFF.md` for the full engineering handoff (decisions, assumptions,
shortcuts, uncertain areas).

## What's new — report schema v3 (2026-07, milestone 3)

- **Row-insertion inference.** Inserted/removed rows are detected per sheet
  (deterministic `difflib` alignment over row signatures) and collapse into
  single `rows_inserted`/`rows_removed` structural changes instead of dozens
  of shifted value/formula changes. Genuinely edited cells on aligned rows
  still report normally at their new coordinates. Column insertions remain a
  known limitation. JSON carries `report_schema_version: "3"`.
- **Exact Excel Table metadata.** When a workbook contains real Excel Tables,
  their declared header/totals row counts override the heuristics (the schema
  note says "exact (from Excel Table metadata)"), totals rows are excluded
  from row counts, query sums, and structured-reference dependency ranges.
- **PDF export** via the optional `excel-auditor[pdf]` extra (WeasyPrint;
  macOS: `brew install pango`). `--pdf-output PATH` / `--pdf` on the CLI,
  `GET /reports/{id}?format=pdf` on the API. PDFs are excluded from the
  byte-determinism guarantee (embedded creation metadata); JSON/HTML remain
  the canonical evidence artifacts.
- **Integrations scaffolding.** An MCP server (`python -m
  excel_auditor.integrations.mcp_server`, stdio; optional `[mcp]` extra)
  exposes `audit_workbook` / `compare_workbooks` / `inspect_schema` /
  `ask_question` to any MCP-capable client. Microsoft Teams webhooks, both
  directions: an incoming-webhook card poster (`--notify-teams` on
  `audit`/`compare`) and an HMAC-validated `POST /integrations/teams`
  endpoint (`status <report_id>` / `help`), mounted only when
  `EXCEL_AUDITOR_TEAMS_ENABLED=1`. Caveat: Teams outgoing
  webhooks cannot receive file attachments — Q&A over uploaded workbooks in
  Teams requires a real Azure bot and is a later milestone.

## Roadmap candidates (next three)

1. ~~Row insertion inference~~ (shipped, v3) → column-insertion inference.
2. ~~PDF export of the HTML report~~ (shipped, v3) → Bulgarian localization
   of report strings.
3. Async processing with background workers + audit history per client.
