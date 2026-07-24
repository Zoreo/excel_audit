# Remediation Plan — excel-auditor

- **Date:** 2026-07-24 · **Baseline commit:** `460d866` (141 tests pass, ~0.9 s)
- **Source of truth:** `docs/audits/ranked_report_findings.md` (verified audit)
- **Status:** APPROVED 2026-07-24 with decisions D1–D6 (see §4); implementation in progress
- **Branches:** integration `remediation/verified-findings`; workers `fix/excel-correctness` (W-A), `fix/query-correctness` (W-B), `fix/dependency-analysis` (W-C), `fix/security-storage` (W-D)

## 0. Scope decision

**In scope:** all 8 confirmed P1s (QA-001, QA-002, EXCEL-001…005, SECURITY-001,
ARCH-001) plus four justified P2s:

| P2 item | Justification |
|---|---|
| QA-003 (`float(None)` → 500) | Same files and same pass as QA-001; proven crash. |
| SECURITY-002 (32-bit report IDs) | 3-line fix, folded into the ARCH-001 storage pass per the audit's own recommendation. |
| P2-7 (`report_schema_version`) | Required anyway: EXCEL-004 changes `workbook_id` semantics, so consumers need a version signal. |
| P2-1 (rename-aware formula comparison) | The audit explicitly calls it "one coherent piece of work" with EXCEL-001. |

**Explicitly out of scope** (no speculative work): EA-REF-001 `"#REF!"`
substring false positive, `=Missing!A1` silence, severity-escalation caps, NaN
cell equality, any query-subsystem restructuring, P2-2 truncation surfacing
(optional rider on T7 only if it falls out of the same plumbing — otherwise
deferred).

**Code-inspection confirmations** (each finding verified against source before
assignment): `_dedupe` keys on `(sheet_name, ref, column.name)` at
`resolution.py:201`; name-keyed frame build at `query.py:74`; space-stripped
`_NUMBER_RE.search` at `rule_parser.py:173`; exact-signature-only rename
inference at `workbook_diff.py:60-63`; unsorted `old_names & new_names` at
`workbook_diff.py:45`; self-edge skip at `dependency_graph.py:113-114` with
dead branch at `:182`; swallow-and-log at `rules/base.py:107-110`; `uuid4` id
and uninjectable `datetime.now(UTC)` in `services.py:79,161`; `token_hex(4)` +
unconditional `write_text` + 8-hex `_ID_RE` in `storage/reports.py`; blob
columns in `storage/database.py:22-23` served by `api/routes/jobs.py:43-48`;
`/ask` leak paths in `web/routes.py:141-164` (upload parked at `:143` before
any guarded region; `inspect_schema`/`answer_query` un-`finally`'d).

## 1. Findings in dependency order

```
Wave 1 (parallel, disjoint files)
  T1  EXCEL-004  determinism                        ─┐
  T2  QA-001 + QA-003  resolution/dedupe/frame      │ independent
  T3  QA-002  threshold parsing                     │ of each other
  T4  EXCEL-002 + EXCEL-003(marker)  dep graph      │
  T5  ARCH-001 + SECURITY-002  storage              │
  T6  SECURITY-001  web-ask lifecycle              ─┘
Wave 2 (sequential on the Excel-Core chain)
  T7  EXCEL-005 + P2-7   (needs T1: services.py, golden harness)
  T8  EXCEL-001 + P2-1   (needs T1: same file workbook_diff.py, golden harness)
  T4b EXCEL-003 full name/table resolution          (gated on Decision D1)
Wave 3
  T9  Docs reconciliation (README/HANDOFF)          (needs T4, T5, T6)
  T10 Adversarial sweep + demo artifact regen       (needs everything)
```

T1 goes first inside its worker because the byte-level golden-report harness
it unblocks is the regression guard for T7 and T8, and because T1 and T8 both
edit `workbook_diff.py`.

## 2. Worker groups and file ownership

Four workers, one lead. **Concurrency rules:** a file has exactly one owner
per wave; nobody edits `tests/conftest.py` (new fixtures go in the task's own
test files); new tests go in new files unless the existing test file is
single-owner below. Paths are relative to `src/excel_auditor/` for source and
`tests/` for tests.

| Worker | Tasks | Owns (source) | Owns (tests) |
|---|---|---|---|
| **W-A Excel correctness & diff** | T1 → T7 → T8 | `analysis/workbook_inventory.py`, `services.py`, `analysis/workbook_diff.py`, `analysis/rules/base.py`, `models/reports.py`, `models/comparison.py`, `reporting/json_report.py`, `reporting/html_report.py`, `cli.py` | `integration/test_determinism.py` (new), `unit/test_workbook_diff.py`, `unit/test_failed_rules.py` (new), `unit/test_reports.py` |
| **W-B Query/ask correctness** | T2, T3 | T2: `analysis/resolution.py`, `analysis/query.py`, `query_service.py` · T3: `llm/rule_parser.py` | T2: `unit/test_resolution.py`, `unit/test_query_engine.py`, `unit/test_ask.py` · T3: `unit/test_threshold_parsing.py` (new) |
| **W-C Dependency analysis** | T4 (+T4b) | `analysis/dependency_graph.py`, `analysis/rules/circular_references.py`, `models/dependency.py`, `analysis/severity.py` | `unit/test_dependency_graph.py`, `unit/test_rules.py`, `unit/test_named_range_impact.py` (new) |
| **W-D Security & storage** | T5, T6 | T5: `storage/database.py`, `storage/repositories.py`, `storage/reports.py`, `api/routes/{audits,comparisons,jobs}.py`, `api/schemas.py` · T6: `web/routes.py`, `config.py`, `api/app.py` | T5: `unit/test_report_store.py`, `integration/test_api.py` · T6: `integration/test_web_ask.py` (new) |
| **Lead** | T9, T10 | `README.md`, `HANDOFF.md`, `demo_workbooks/*`, `scripts/generate_demo_workbooks.py` | full-suite + adversarial sweep |

Notable deconfliction choices:

- `README.md` is touched by both ARCH-001 (purge instructions, :215-217) and
  SECURITY-001 (deletion guarantee, :212-214) on adjacent lines — so **no
  worker edits README**; the lead does one docs pass (T9).
- `models/reports.py` is needed by both EXCEL-005 and `report_schema_version`
  — both live in T7, so the storage worker never touches models.
- `api/app.py` belongs to T6 (TTL sweep wiring) only; T5 rewires route
  handlers, not app state.
- T2 and T3 interact behaviorally (the parser builds the filters the engine
  resolves) but their files are disjoint; T3 must not add cases to
  `test_ask.py` (T2 owns it).

## 3. Task specifications

### T1 — EXCEL-004: deterministic reports *(W-A, wave 1)*

- **Finding IDs:** EXCEL-004 (P1-1).
- **Objective:** (a) `workbook_id` = full SHA-256 content digest instead of
  `uuid4` (`workbook_inventory.py:242`, per D2); (b) `sorted()` on the set
  intersection at `workbook_diff.py:45` (this line only — no other diff
  logic); (c) injectable `generated_at` in `audit_workbook` /
  `compare_workbooks` (`services.py:79,161`) with a JSON-exclusion/injection
  option in `reporting/json_report.py` and a CLI passthrough in `cli.py`.
- **Expected files:** `workbook_inventory.py`, `services.py`,
  `workbook_diff.py` (line 45), `reporting/json_report.py`, `cli.py`,
  `tests/integration/test_determinism.py`, `tests/unit/test_workbook_diff.py`.
- **Must not modify:** `resolution.py`, `query*.py`, `rule_parser.py`,
  `dependency_graph.py`, `storage/*`, `web/*`, `api/*`, `models/*`,
  `conftest.py`, README.
- **Acceptance criteria:** two subprocess runs with different
  `PYTHONHASHSEED` produce byte-identical JSON (timestamp injected) and HTML;
  same content → same `workbook_id`, changed content → changed id; compare
  path (`workbook_id="old"/"new"`) unaffected; all 141 baseline tests green.
- **Tests that must pass:** golden byte-compare across `PYTHONHASHSEED`
  values; content-hash stability/change pair; multi-sheet
  visibility/merged/hidden structural changes emit in sorted order.
- **Dependencies:** none. **Blocks:** T7, T8.

### T2 — QA-001 + QA-003: duplicate-header resolution and filter-value guard *(W-B, wave 1)*

- **Finding IDs:** QA-001 (P1, new), QA-003 (P2, new).
- **Objective:** key `_dedupe` on physical position (sheet, table ref,
  **column index/letter**) instead of name (`resolution.py:197-205`);
  same-name multi-column matches → `needs_confirmation`; build DataFrames
  positionally in `load_table_frame` (`query.py:68-75`) so duplicate headers
  don't overwrite, and route filter/group-by lookups through the chosen
  physical column. Same pass: guard `float(flt.value)` when `value is None`
  (`query.py:130,148`) → clean `cannot_answer`/422, never an unhandled
  `TypeError` (`query_service.py:160` path).
- **Expected files:** `resolution.py`, `query.py`, `query_service.py`,
  `tests/unit/test_resolution.py`, `tests/unit/test_query_engine.py`,
  `tests/unit/test_ask.py`.
- **Must not modify:** `rule_parser.py` (T3's file); `models/query.py` unless
  a positional-column field is unavoidable (escalate to lead if so); anything
  in W-A/W-C/W-D ownership.
- **Acceptance criteria:** `Category|Amount|Amount` fixture →
  `needs_confirmation` listing both physical columns; after a choice, the sum
  matches the chosen column (60 vs 6000 case); single-column workbooks resolve
  with no prompt; filter missing `value` → no 500 on `POST /api/v1/queries`,
  no traceback on the CLI path.
- **Tests that must pass:** audit §6 QA-001 block verbatim (duplicate-header
  confirmation, positional frame preservation, filter/group-by on chosen
  column, single-column no-regression) plus the QA-003 guard case.
- **Dependencies:** none.

### T3 — QA-002: threshold extraction, refuse-when-unfiltered *(W-B, wave 1)*

- **Finding IDs:** QA-002 (P1, new).
- **Objective:** extract the number from space-preserving normalized text
  (`rule_parser.py:173`, `_NUMBER_RE:27`); when an `_EXCEED_KEYWORDS` term
  matched but no threshold filter could be built (no number, or no metric
  column — note the existing `and metric` guard at `:181` silently drops the
  filter too), raise `UnsupportedQuestionError` / produce `cannot_answer`
  instead of running an unfiltered `LIST_ROWS`; cover aggregate phrasings
  ("how many … over 500") so they either build the filter or refuse.
- **Expected files:** `rule_parser.py`,
  `tests/unit/test_threshold_parsing.py` (new).
- **Must not modify:** `resolution.py`, `query.py`, `query_service.py`,
  `tests/unit/test_ask.py` (all T2-owned).
- **Acceptance criteria:** "show rows where amount over 500" returns only
  qualifying rows with the filter in provenance; threshold keyword + no
  extractable number → refusal, never an unfiltered `verified` answer.
- **Tests that must pass:** audit §6 QA-002 block: exceeds/above/more-than +
  Bulgarian variants ("над", "повече от"), thousands separators
  ("over 10 000"), the refusal case, and filtered-vs-unfiltered count.
- **Dependencies:** none. Coordination: T2 and T3 merge independently; T10
  adds a combined duplicate-header + threshold fixture.

### T4 — EXCEL-002 + EXCEL-003 (interim marker): dependency-graph honesty *(W-C, wave 1)*

- **Finding IDs:** EXCEL-002 (P1-3), EXCEL-003 (P1-4, interim marker leg).
- **Objective:** record self-references in a dedicated `self_loops: set[Key]`
  on `DependencyGraph` (populated where `dependency_graph.py:113-114`
  currently skips them), consulted by `cycles()` (replacing the dead branch at
  `:182`) and by `impact_for` so `is_circular` is true for self-loops —
  self-edges stay out of traversal so BFS still terminates. For EXCEL-003:
  when a formula contains defined-name/structured-table tokens that resolve to
  nothing, mark the impact as unknown (new field on `DependencyImpact`, e.g.
  `has_unresolved_names`) instead of a confident `transitive = 0`;
  `severity.py` treats unknown-impact as "do not claim low with high
  confidence".
- **Expected files:** `dependency_graph.py`, `rules/circular_references.py`,
  `models/dependency.py`, `severity.py`, `tests/unit/test_dependency_graph.py`,
  `tests/unit/test_rules.py`, `tests/unit/test_named_range_impact.py` (new).
- **Must not modify:** `rules/base.py`, `services.py`, `reporting/*` (W-A
  owns; if the marker needs HTML rendering, hand a note to W-A for T7).
- **Acceptance criteria:** `=A1+1` in A1 and `=SUM(D1:D11)` in D11 both
  produce EA-CIR-001; existing two-cell cycle detection unchanged;
  `impact_for` on a self-loop reports `is_circular=true`; defined-name
  formulas never report `transitive = 0` with full confidence.
- **Tests that must pass:** audit §6 EXCEL-002 block + the interim-marker case
  from the EXCEL-003 block.
- **Dependencies:** none. **Blocks:** T4b.

### T4b — EXCEL-003 full name/table resolution *(W-C, wave 2, approved by D1)*

- **Finding IDs:** EXCEL-003 (P1-4, full-resolution leg).
- **Objective:** resolve `named_ranges.refers_to` and `tables.ref` (already
  parsed in the inventory) to concrete ranges during graph build, handling:
  multi-area `refers_to`, constant-valued names (`="0.05"`), sheet-scoped name
  shadowing of globals, `#REF!` names — skip-or-mark-unknown on every edge
  case, never mis-resolve.
- **Files/tests:** same ownership as T4.
- **Acceptance criteria / tests:** audit §6 EXCEL-003 block (named-range
  escalation parity with the direct-reference control, `Table1[Col]`
  sub-range resolution, all four edge cases no-crash/no-mis-resolution).
- **Dependencies:** T4, Decision D1.

### T5 — ARCH-001 + SECURITY-002: storage hardening *(W-D, wave 1)*

- **Finding IDs:** ARCH-001 (P1-8), SECURITY-002 (P1-7 → conditional P2),
  P2-8 (file hash, delivered free by T1's content-hash id).
- **Objective:** single source of truth for report bodies. Stop writing
  `report_json`/`report_html` blobs (`database.py:22-23`, `repositories.py`,
  `api/routes/audits.py:43-48`, `comparisons.py`); rewire
  `GET /api/v1/reports/{job_id}` (`jobs.py:30-48`) to load from the
  `ReportStore` via the `report_id` already in the job summary; provide the
  migration story per Decision D4. Same pass: `token_hex(16)` + exclusive
  create (`open(path, "x")` with collision retry) in
  `storage/reports.py:42-46`; `_ID_RE` accepts both 8-hex (legacy) and 32-hex
  ids.
- **Expected files:** `storage/database.py`, `storage/repositories.py`,
  `storage/reports.py`, `api/routes/audits.py`, `api/routes/comparisons.py`,
  `api/routes/jobs.py`, `api/schemas.py` (if the job schema drops blob
  fields), `tests/unit/test_report_store.py`, `tests/integration/test_api.py`.
- **Must not modify:** `models/reports.py` / `models/comparison.py` (T7 owns
  `report_schema_version`), `web/routes.py`, `api/app.py`, `config.py`
  (T6-owned), README (lead-owned).
- **Acceptance criteria:** job report endpoints serve identical content
  post-change; deleting the artifacts files makes the report irretrievable
  from **both** endpoint families (purge actually purges); existing DBs with
  legacy blob columns still open; a pre-created id file is never overwritten;
  legacy 8-hex reports still load.
- **Tests that must pass:** audit §6 ARCH-001 + SECURITY-002 block verbatim.
- **Dependencies:** none. Coordinates with T9 (README purge wording).

### T6 — SECURITY-001: web-ask upload lifecycle *(W-D, wave 1)*

- **Finding IDs:** SECURITY-001 (P1-6, broadened).
- **Objective:** in `web/routes.py:123-189`, guarantee the parked upload under
  `web_upload_dir/{token}` is deleted on **every** exit path — including the
  currently unguarded `inspect_schema` (pre-parse 422 leak), `answer_query`
  exceptions, and `cannot_answer` — **except** the `NEEDS_CONFIRMATION`
  return, which must keep the parked file for the follow-up POST. Add a TTL
  sweep of `web_upload_dir` (Decision D5) wired in `api/app.py` startup, TTL
  configurable in `config.py`; the sweep also covers crash/abandonment
  leftovers. **Not** a plain `try/finally` — the audit is explicit that that
  shape breaks the confirmation flow.
- **Expected files:** `web/routes.py`, `config.py`, `api/app.py`,
  `tests/integration/test_web_ask.py` (new).
- **Must not modify:** `query_service.py` (T2-owned), `storage/*`,
  `api/routes/*` (T5-owned), README (lead-owned).
- **Acceptance criteria:** invalid/corrupt upload → error page and nothing
  left under `artifacts/uploads`; mid-flow exception → nothing left;
  confirmation flow works end-to-end and deletes on completion; a parked file
  younger than the TTL is never swept mid-flow.
- **Tests that must pass:** audit §6 SECURITY-001 block verbatim.
- **Dependencies:** none. **Blocks:** T9.

### T7 — EXCEL-005 + P2-7: failed-rule surfacing and schema version *(W-A, wave 2, after T1)*

- **Finding IDs:** EXCEL-005 (P1-5), P2-7; optional rider P2-2.
- **Objective:** `run_all_rules` (`rules/base.py:103-113`) collects failed
  rule ids and returns them alongside findings; `services.py` surfaces them in
  `AuditReport`/`WorkbookComparison` via `limitations`/`risk_drivers` plus an
  explicit `failed_rules` field so a crashed rule is visible in the delivered
  artifact; per-rule isolation stays. Add `report_schema_version` to both
  report envelopes and renderers (initial value `"2"`, per D6). Render both in
  HTML and JSON. The P2-2 truncation rider is deferred and must NOT be
  implemented (approved decision).
- **Expected files:** `rules/base.py`, `services.py`, `models/reports.py`,
  `models/comparison.py`, `reporting/json_report.py`,
  `reporting/html_report.py`, `tests/unit/test_failed_rules.py` (new),
  `tests/unit/test_reports.py`.
- **Must not modify:** `dependency_graph.py`, `rules/circular_references.py`,
  `tests/unit/test_rules.py` (W-C-owned), `storage/*`.
- **Acceptance criteria:** monkeypatched crashing rule → report visibly warns
  and risk drivers mention incomplete coverage, other rules' findings intact;
  clean run → no warning; version field present in both report kinds; golden
  determinism tests from T1 updated intentionally (version field is a
  deliberate schema change), still byte-stable across seeds.
- **Tests that must pass:** audit §6 EXCEL-005 block; T1's determinism suite.
- **Dependencies:** T1 (shared `services.py`, golden harness). Coordinates
  with T5 (report bodies now served only from the store — re-run T5's
  integration tests after merge).

### T8 — EXCEL-001 + P2-1: inferred sheet-rename matching *(W-A, wave 2, after T1)*

- **Finding IDs:** EXCEL-001 (P1-2), P2-1.
- **Objective:** extend `_match_sheets` (`workbook_diff.py:39-68`) beyond
  exact-signature matching: pair a removed+added sheet only under the D3
  criteria (similarity = shared `(coordinate, formula)` entries ÷ larger
  formula-entry count; ≥ 0.80, ≥ 5 comparable formula cells, unique best
  candidate, margin ≥ 0.10 over second-best), label the rename *inferred* (vs today's
  "identical content"), then run the normal cell diff on the matched pair so
  the edits appear. Genuinely different sheets (`Q1`→`Q2`) must stay
  removed/added; ambiguous multi-candidate cases must not pair arbitrarily.
  P2-1: make formula comparison rename-aware so `=Inputs!B2` vs
  `=Assumptions!B2` on a matched pair isn't reported as a logic change.
- **Expected files:** `workbook_diff.py`, `tests/unit/test_workbook_diff.py`
  (possibly a formula-normalizer touchpoint for P2-1 — escalate to lead if it
  grows beyond `workbook_diff.py`).
- **Must not modify:** `services.py` beyond what T7 left; `models/*` except a
  `details` key on `StructuralChange` (already a free-form dict — no schema
  change).
- **Acceptance criteria:** rename + one cell edit → `sheet_renamed` (inferred)
  **and** the cell change reported; `Q1`/`Q2` stays removed/added;
  two-removed/two-added similar sheets handled without arbitrary pairing;
  byte-identical rename detection unchanged; determinism golden tests still
  pass.
- **Tests that must pass:** audit §6 EXCEL-001 block verbatim; T1's
  determinism suite.
- **Dependencies:** T1, Decision D3.

### T9 — Docs reconciliation *(lead, wave 3)*

- **Finding IDs:** doc legs of SECURITY-001, ARCH-001, EXCEL-003.
- **Objective:** one README/HANDOFF pass: correct README:212-214 (deletion
  guarantee now true — state the TTL and the needs-confirmation exception),
  README:215-217 (purge instruction now actually purges), update
  HANDOFF:141-142 and :173-175 (named-range limitation now marked/resolved per
  T4/T4b outcome).
- **Files:** `README.md`, `HANDOFF.md`.
- **Dependencies:** T4, T5, T6.

### T10 — Adversarial sweep and artifact regeneration *(lead, wave 3)*

- **Objective:** full suite green; cross-fix interaction fixtures (duplicate
  headers **+** threshold query; inferred rename **+** determinism
  byte-compare; self-loop **+** failed-rule run); regenerate
  `demo_workbooks/*.json|html` via `scripts/generate_demo_workbooks.py` since
  the content-hash `workbook_id` and the schema-version field change committed
  artifacts; confirm the 141-test baseline grew only by intended additions.
- **Dependencies:** all of the above.

## 4. Approved architectural decisions (lead, 2026-07-24)

| # | Decision |
|---|---|
| **D1** | Implement **both** T4 and T4b in this round. EXCEL-003 is a confirmed P1 and must not remain only partially mitigated. |
| **D2** | Injectable `generated_at` service parameter defaulting to current UTC time, plus a CLI passthrough. `workbook_id` = **full SHA-256 digest**. Keep `"old"`/`"new"` identifiers unchanged on the comparison path. |
| **D3** | Reuse `SHEET_RENAMED` with `details.inferred=true`. Similarity = shared `(coordinate, formula)` entries ÷ the larger formula-entry count. Require: similarity ≥ 0.80, at least five comparable formula cells, a unique best candidate, and a margin ≥ 0.10 over the second-best candidate; otherwise leave the sheets as removed + added. |
| **D4** | Stop writing report blobs to the database; tolerate and ignore legacy blob columns; document the legacy purge process. |
| **D5** | Configurable 1-hour upload TTL. Sweep at application startup and opportunistically on `/ask` submissions. No background thread. |
| **D6** | Initial `report_schema_version` = `"2"`. |

P2-2 (truncation surfacing) remains deferred — the optional T7 rider is **not**
to be implemented.

## 5. Global execution rules

- Baseline before any task: 141 tests pass (~0.9 s). Every task must leave
  the **full** suite green, not just its own tests.
- No worker edits `tests/conftest.py`, `README.md`, `HANDOFF.md`, or
  `demo_workbooks/`.
- Wave-2 tasks start only after their blocking wave-1 task has merged; W-A's
  three tasks are strictly sequential within the one worker.
- Any worker that needs a file outside its ownership list stops and escalates
  to the lead instead of editing it.
- No speculative refactors or unrelated cleanup anywhere.
