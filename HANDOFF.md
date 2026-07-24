# Engineering Handoff — excel-auditor POC

Status: **working, reviewable**. 141 tests passing, ruff clean, mypy clean
(69 source files), application exercised live (CLI + server) before handoff.

## 1. What was implemented

**Core engine (deterministic, no LLM anywhere in detection or math):**

- Safe workbook loading: zip-bomb/path-traversal defenses, macro & data-connection
  detection (macros never executed), dual-pass openpyxl load (formulas + cached values).
- Typed workbook inventory (sheets, cells, formulas, normalized formulas, styles,
  merged ranges, hidden rows/cols, named ranges, unified external-link targets).
- Formula normalization to relative R1C1 form so copied formulas compare structurally.
- Single-workbook audit: 16 rules (hidden content, external dependencies, broken
  refs, error values, volatile functions, hardcoded literals, pattern anomalies,
  suspicious total ranges, circular refs, long formulas, opaque content). Stable
  rule ids, severity + separate confidence, evidence, suggested action; repeated
  low/medium findings grouped per (rule, sheet).
- Two-version comparison: 9 cell-change categories + 14 structural change types,
  rename inference, formatting-only detection, downstream impact per change
  (dependency graph: cross-sheet + range edges, BFS, iterative Tarjan for cycles),
  and **review items** — one deduplicated item per issue with reconciled severity
  (e.g. `formula_added` containing `#REF!` inherits the HIGH broken-reference severity).
- Transparent categorical risk level (highest severity present + drivers) — no
  opaque numeric score.
- Schema detection: contiguous-block table finding, header (and two-row header)
  detection, column typing (date/currency/percentage/boolean/categorical/text/
  identifier-ish), currency inference from number formats, total/subtotal-row
  detection, missing counts, samples, hidden-content warnings.
- Deterministic query engine (pandas): sum/count/distinct/average/min/max/median,
  filters (incl. year_equals, before/after, contains, thresholds), group-by
  (incl. by-month on date columns), period comparison, next-deadline /
  due-within / overdue. Every result carries full provenance (rows included,
  blanks excluded, subtotal rows excluded, filters, assumptions, warnings).
- Column resolution: normalization (case/punctuation/whitespace), Bulgarian↔Latin
  transliteration, canonical EN/BG alias vocabulary, concept families
  (gross vs net revenue, date vs due-date). Ambiguity is surfaced for user
  confirmation — never silently resolved. Statuses: verified /
  review_recommended / needs_confirmation / cannot_answer_safely.
- Intent parsing behind a Protocol: rule-based EN/BG parser (aggregations,
  filters, grouping, period comparison, deadlines, inspection, audit, trace;
  rejects open-ended questions), mock parser for tests. LLM provider slot
  exists but is deliberately not bundled.

**Interfaces (all thin; zero analysis logic inside):**

- CLI: `audit`, `compare`, `schema`, `query`, `ask`, `demo`, `serve` with
  `--output-dir/--json-output/--html-output/--open/--verbose/--choice/
  --no-input/--reference-date`. Interactive `Select [1-N]` confirmation loop;
  exit codes 0/2/3.
- Report store: `artifacts/reports/{random-id}.{json,html}` served at
  `{base_url}/reports/{id}`; CLI prints URL + path for every run.
- FastAPI: audits, comparisons, schema, queries (structured JSON or free-text
  + `choices`), jobs, job reports, public stored reports, health.
- Minimal server-rendered pages: `/`, `/audit`, `/compare`, `/ask`
  (ask walks the confirmation flow via a parked-upload token).
- HTML reports (Jinja2, autoescaped — verified by test): audit, comparison
  (review items), schema, query-with-provenance. JSON mirrors of everything.

## 2. Repository structure

```
excel-auditor/
├── pyproject.toml / Dockerfile / docker-compose.yml / .env.example
├── README.md / HANDOFF.md
├── src/excel_auditor/
│   ├── config.py            # env-driven Settings (dirs, limits, base_url)
│   ├── errors.py            # domain exceptions
│   ├── services.py          # audit_workbook / compare_workbooks
│   ├── query_service.py     # inspect_schema / answer_query (confirmations)
│   ├── demo.py              # demo model generator (10 planted anomalies)
│   ├── cli.py               # terminal interface
│   ├── models/              # pydantic models incl. schema.py, query.py
│   ├── parsing/             # loader, tokenizer, reference parser, normalizer
│   ├── analysis/            # inventory, diff, patterns, graph, severity,
│   │   └── rules/           #   review items, schema, resolution, query engine
│   ├── llm/                 # IntentParser protocol, rule & mock parsers
│   ├── reporting/           # json_report, html_report + templates/
│   ├── api/                 # FastAPI app, routes/, schemas/, upload handling
│   ├── web/                 # server-rendered demo pages
│   └── storage/             # sqlite job store + file report store
├── scripts/generate_demo_workbooks.py
└── tests/                   # 141 tests: unit/ + integration/ + conftest fixtures
```

## 3. Install / run / test

```bash
cd excel-auditor
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Python >= 3.12

.venv/bin/excel-auditor demo                  # end-to-end sample
.venv/bin/excel-auditor audit demo_workbooks/financial_model_v2.xlsx
.venv/bin/excel-auditor compare demo_workbooks/financial_model_v1.xlsx demo_workbooks/financial_model_v2.xlsx
.venv/bin/excel-auditor schema <sales.xlsx>
.venv/bin/excel-auditor query <sales.xlsx> --function sum --value-column Оборот \
    --filter-column Дата --filter-op year_equals --filter-value 2025
.venv/bin/excel-auditor ask <sales.xlsx> "Какъв е общият оборот за 2025?"
.venv/bin/excel-auditor serve                 # http://localhost:8000

.venv/bin/python -m pytest                    # 141 tests
.venv/bin/ruff check src tests
.venv/bin/mypy src/excel_auditor
```

Docker: `docker compose up --build` (API on :8000, data volume mounted).

## 4. Architectural decisions

- **Three layers** (engine / reporting / interfaces); interfaces only translate
  requests into service calls. Engine has no FastAPI/CLI/LLM imports.
- **Deterministic checks do the analysis**; the LLM slot is parsing/wording only.
  A rule-based parser ships so the whole product works with no API key.
- **pandas** for query execution (explicitly sanctioned; small POC tables).
- **stdlib sqlite3** for the flat jobs table instead of SQLAlchemy — one table
  didn't justify the dependency; swap is contained to `storage/`.
- **openpyxl tokenizer** reused rather than writing a formula parser; normalizer
  builds on it. Unparseable formulas degrade to "opaque", never crash.
- **Severity ≠ confidence** everywhere; risk level = highest severity present,
  rule printed in every report (no fake precision).
- **Review items** are the single source of truth in comparisons; raw
  cell_changes/findings stay in JSON but are severity-reconciled to match.
- Report ids are random hex file pairs on disk; no database coupling for reports.

## 5. Assumptions

- Query numbers come from cell values Excel last saved (cached formula results
  are trusted; the engine does not recalculate).
- One header row (two detected heuristically) directly above data; tables are
  contiguous row blocks separated by fully blank rows.
- Rows whose first text cell starts with total-like keywords (total/общо/итого/
  всичко/сума…) are totals and excluded from queries (recorded in provenance).
- `[n]`-style external markers index into the workbook's external-link table.
- Excel sheet/defined names are case-insensitive; matching honors that.
- Deadline queries default to `date.today()` unless `--reference-date` given.

## 6. Shortcuts / temporary solutions

- Sync request handling; "job" records are written already-completed.
- Web ask flow parks the upload under `artifacts/uploads/{token}` between
  confirmation steps; deleted on every exit path (errors included) except the
  needs-confirmation return, and abandoned tokens are GC'd by a TTL sweep
  (default 1 h) at startup and on each ask submission.
- Currency detection is symbol-sniffing on number formats (€/лв/$/£ → code).
- Grouping supports single-token dimensions (`by region`, `по региони`);
  multi-word dimensions aren't parsed.
- `ask` with an audit-type question reuses the audit command wholesale.
- Vocabulary includes hand-picked Bulgarian inflections (оборота/оборотът…)
  rather than real lemmatization.
- `--hosted` flag from the spec was skipped (no remote hosting exists yet);
  URLs always use `EXCEL_AUDITOR_BASE_URL`.
- Report store lookups are filesystem reads; no index, no TTL/cleanup.

## 7. Unsupported Excel features

- `.xls` (legacy BIFF), password-protected/encrypted files, Google Sheets.
- VBA logic (presence detected only), pivot tables, charts-as-dependencies,
  Power Query / data-model connections (presence flagged only).
- Array-formula spill semantics, `.xlsm` macro analysis, R1C1-authored formulas,
  external links resolved through the filesystem (never followed).
- Row/column insertion inference in diffs (shifted blocks appear as many
  changes; structurally-identical shifts are downgraded to info).
- Shared-formula edge cases depend on how the source app saved the file.

## 8. Known bugs / uncertain areas

- Schema header heuristic can misclassify text-heavy data blocks (e.g. a block
  whose first data row is also mostly text); notes/warnings flag low confidence
  but review is advised on unusual layouts.
- Column typing needs ≥70% type agreement; very mixed columns fall back to text.
- `concepts_in_text` matches whole words after normalization — heavily inflected
  Bulgarian phrasing outside the vocabulary won't match (question is then
  rejected as unsupported rather than answered wrongly).
- Defined names and structured table references (`MyInput`, `Table1[Col]`,
  `Table1[]`) are resolved into dependency-graph edges, including multi-area
  names, sheet-scoped shadowing, and totals-row exclusion. Genuinely
  unresolvable tokens (unknown/`#REF!`/formula-valued names, item specifiers
  like `Tbl[[#All],[Col]]`) build no edges and instead set the
  `has_unresolved_names` impact marker (JSON reports only; HTML does not
  render the marker yet), which caps confidence so a possibly-understated
  impact is never reported as a confident zero. Table resolution assumes
  Excel's default single header row (the inventory does not record
  `headerRowCount`/`totalsRowCount`).
- Formatting-only detection compares a compact style signature (number format,
  bold/italic/underline, fill); exotic style changes outside it are invisible.
- Grouped month keys sort lexicographically (fine for YYYY-MM).
- `pandas` FutureWarnings may appear on future pandas majors; pinned `>=2.2`.

## 9. Core analysis logic — file map

| Concern | File |
|---|---|
| Safe container validation & load | `src/excel_auditor/parsing/workbook_loader.py` |
| Reference parsing (A1, sheets, external) | `src/excel_auditor/parsing/reference_parser.py` |
| Formula normalization (R1C1-relative) | `src/excel_auditor/parsing/formula_normalizer.py` |
| Inventory building | `src/excel_auditor/analysis/workbook_inventory.py` |
| Diff (structural + cell) | `src/excel_auditor/analysis/workbook_diff.py` |
| Repeated-pattern anomalies | `src/excel_auditor/analysis/pattern_detection.py` |
| Dependency graph & impact | `src/excel_auditor/analysis/dependency_graph.py` |
| Audit rules | `src/excel_auditor/analysis/rules/*.py` |
| Severity / risk level | `src/excel_auditor/analysis/severity.py` |
| Review-item unification | `src/excel_auditor/analysis/review.py` |
| Schema detection | `src/excel_auditor/analysis/schema.py` |
| Name/alias resolution | `src/excel_auditor/analysis/resolution.py` |
| Deterministic query execution | `src/excel_auditor/analysis/query.py` |
| Query orchestration + confirmations | `src/excel_auditor/query_service.py` |
| Audit/compare services | `src/excel_auditor/services.py` |
