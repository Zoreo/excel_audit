# excel-auditor

**Git diff, risk analysis and verified Q&A for Excel financial and
operational models.** Terminal-first, with stored HTML/JSON reports served at
local URLs, a thin API, and a minimal demo web page.

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

## What it detects

**Single-workbook audit** (`audit`):

| Rule | What it flags |
|---|---|
| EA-PAT-001 | Formula overwritten with a hardcoded value inside a repeated range |
| EA-PAT-002 | Formula inconsistent with the surrounding pattern (incl. wrong-row copies, with shift inference) |
| EA-PAT-003 | Missing formula inside a repeated block (fully blank spacer rows/columns are recognized as layout and skipped) |
| EA-RNG-001 | Aggregation range that excludes an adjacent populated cell (stale totals) |
| EA-RNG-002 | Formulas referencing blank cells inside the used range |
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
.venv/bin/python -m pytest      # 141 tests
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
  names and **deleted immediately after processing** (verified by test).
  Client filenames are used for display only.
- Reports are stored in a local SQLite database (`data/`); delete rows/file to
  purge. No workbook content is sent to any external service, and cell
  contents are not logged.
- All workbook-derived content is HTML-escaped in reports (verified by test).

## Known limitations

- Formulas are analyzed structurally; the workbook is not recalculated. Query
  results use the values Excel last saved (openpyxl-generated files cache none
  for formula cells).
- Row/column insertions are not inferred — they appear as many shifted-formula
  changes (normalized-equal shifts are downgraded to `info`).
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

See `HANDOFF.md` for the full engineering handoff (decisions, assumptions,
shortcuts, uncertain areas).

## Roadmap candidates (next three)

1. Row/column insertion inference so shifted blocks collapse into one change.
2. PDF export of the HTML report + Bulgarian localization of report strings.
3. Async processing with background workers + audit history per client.
