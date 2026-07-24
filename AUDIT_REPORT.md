# Release-Candidate Audit — excel-auditor

- **Date:** 2026-07-24 · **Commit:** `460d866` (clean tree)
- **Method:** four independent audit agents (Excel domain correctness; code
  quality/security/performance; system design; adversarial black-box QA) ran in
  parallel without seeing each other's findings. The lead then re-verified every
  P1-level citation directly against the source and merged/adjudicated. All
  reproductions ran outside the repository; `git status` remained clean
  throughout.
- **Test suite:** 141 passed, 0 failed, ~1s. Black-box QA additionally ran ~20
  adversarial CLI scenarios (corrupted files, zip bombs, circular refs, unicode
  paths, a 100k-formula-cell workbook).

## Executive verdict

**Internal-test-ready.** Not yet customer-pilot-ready.

The architecture is genuinely good for a POC — clean engine/interface
separation, one model family driving JSON/HTML/API/storage, strong input
validation, solid XSS/zip-bomb/SQL/path-traversal defenses that adversarial
testing could not break, and honest self-documentation. Performance is fine at
POC scale (100k formula cells: audit 5.6s / 331 MB; compare 8.1s / 542 MB).

What blocks a customer pilot is a small, consistent cluster: **the
"deterministic reports" promise is currently false**, and several **headline
detection features fail silently** in exactly the cases the target market
(FP&A, valuation, audit) hits most — self-referencing circular formulas,
renamed-then-edited sheets, and impact analysis through named ranges. All have
small, local fixes. No P0s: the tool is safe to run.

## What currently works (verified)

- **Core detections:** formula changed, value changed, formula→constant (HIGH),
  added/removed sheets, exact renames, hidden and very-hidden sheets
  (severity-split), hidden rows/columns with data, external references (both
  formula-level and workbook-level, unified), `#REF!`/error-value cells with a
  sensible `#N/A` downgrade, macros/protection/connections flagged but never
  executed.
- **Formula normalization** (R1C1-relative with `$` anchors) is correct: copied
  ranges with mixed absolute/relative references produce no false pattern
  positives; quoted sheet names with escaped apostrophes resolve to real graph
  edges; whole-column refs are clamped and capped.
- **Robustness:** corrupted/truncated/renamed-CSV/zip-bomb inputs all fail with
  clean one-line errors and exit code 2; circular refs never hang (iterative
  Tarjan); float noise (`0.1+0.2` vs `0.3`) is tolerated; unicode/space/quote
  filenames work.
- **Security surfaces held under attack:** sheet-name/cell XSS is escaped
  (autoescape everywhere, no `|safe`), SQL is parameterized, report-ID regex
  blocks path traversal, upload scratch dirs are size-capped, randomized, and
  removed in `finally` on the API path, macros never executed.
- **Architecture:** import direction is clean (`models ← parsing ← analysis ←
  services ← {cli, api, web}`); no engine module imports FastAPI/Jinja/storage;
  the engine is fully testable without a server; HTML rendering only formats
  already-computed model data. The stated "thin interface layer" goal is met.
- **HTML output is already byte-deterministic** — proof the pipeline is one
  small step from keeping its determinism promise.

## P0 findings

None. Nothing is unsafe to run and no severe security/data failure was found.

## Verified P1 release blockers (fix before real customers)

### P1-1 — Reports are not deterministic (three proven causes)
`src/excel_auditor/analysis/workbook_inventory.py:242`,
`src/excel_auditor/services.py:64,79`,
`src/excel_auditor/analysis/workbook_diff.py:45`
- (a) `audit_workbook` never passes a `workbook_id`, so `uuid4().hex[:12]` lands
  in the report and in **every finding's location** — two audits of the same
  file never byte-match (proven: `7739efd10057` vs `86f2d2f7b299`).
- (b) `_match_sheets` iterates `old_names & new_names` (a set), so
  structural-change ordering varies with `PYTHONHASHSEED` (proven with three
  seeds producing three orderings).
- (c) `generated_at=datetime.now(UTC)` is embedded with no way to inject a
  fixed clock.
- **Fix:** derive `workbook_id` from a content hash (SHA-256 prefix); `sorted()`
  the set intersection; make the timestamp injectable or excludable.
  Independently proven by three agents. HTML output is already byte-identical,
  so this is the last gap. Trivial fixes; expensive later once customers store
  and diff reports.

### P1-2 — Sheet rename + any edit ⇒ all cell edits on that sheet vanish
`src/excel_auditor/analysis/workbook_diff.py:39-68`
- Rename inference requires a byte-identical content signature (`:60-63`).
  Rename "Inputs"→"Assumptions" and change one input value: report says
  `sheet_removed` + `sheet_added` and **zero cell changes** — the silently
  changed input, the product's core use case, is not surfaced anywhere. Proven.
- **Fix:** fuzzy rename matching (e.g. single removed+added pair, or >80%
  shared `(coordinate, formula)` entries) and run the normal cell diff on the
  matched pair.

### P1-3 — Self-referencing circular formulas are never detected
`src/excel_auditor/analysis/dependency_graph.py:113-114`
- The graph builder skips any edge where `referenced == dependent`, so `A1 =
  =A1+1` and `D11 = =SUM(D1:D11)` (a total including itself — the most common
  real-world circular reference) produce no EA-CIR-001 finding. The self-loop
  branch in `cycles()` (line 182) is unreachable dead code. Multi-cell cycles
  ARE caught. Proven by two agents independently.
- **Fix:** record self-edges in a dedicated set consulted by the circular rule
  (keeping them out of traversal if desired — traversal is already
  visited-set-safe).

### P1-4 — Named ranges and structured table references are invisible to impact analysis
`src/excel_auditor/analysis/dependency_graph.py:74-76`
- `parse_reference` returns `None` for defined names and `Table1[Col]`, and the
  builder just `continue`s. A key driver referenced via `=MyInput*2` reports
  `transitive_dependent_count = 0`, `touches_outputs = false`; severity
  escalation never triggers; name-routed cycles are invisible. FP&A models name
  exactly their most important cells, so impact reads a confident zero where it
  matters most. Proven. The inventory already parses `named_ranges.refers_to`
  and `tables.ref` — the resolution step just isn't wired in.
- **Fix:** pre-build `{NAME → parsed ref}` / `{TABLE[COL] → sub-range}` lookups
  and consult them when `parse_reference` fails; at minimum report "impact
  unknown — formula uses defined names" instead of 0.

### P1-5 — A crashed rule silently omits its whole detection category from a delivered report
`src/excel_auditor/analysis/rules/base.py:107-110`
- `run_all_rules` catches any rule exception, logs it (and logging is
  effectively unconfigured — see P2), and continues. The customer receives a
  clean-looking report indistinguishable from a genuinely clean run for that
  rule. Isolation is the right instinct; invisibility is not, for a product
  sold on audit trust. Mechanism proven; trigger requires a rule bug (which is
  the guard's own premise).
- **Fix:** collect failed rule IDs and surface them prominently in
  `AuditReport` (the `limitations`/`risk_drivers` plumbing already exists).

### P1-6 — Web "ask" flow retains customer workbooks indefinitely, contradicting the documented deletion guarantee
`src/excel_auditor/web/routes.py:123-189`
- The confirmation flow parks the uploaded workbook under
  `artifacts/uploads/{token}` with no TTL; abandoning the tab orphans it
  forever, and an unexpected exception between park and cleanup leaks it (no
  `try/finally`). README states uploads are "deleted immediately after
  processing (verified by test)" — the test covers only the API path. Two
  agents found this independently at P2; elevated to P1 because it is a broken
  written data-retention promise aimed at accounting/valuation customers.
- **Fix:** `try/finally` around the parked-file lifecycle plus a startup/
  periodic sweep of `web_upload_dir` entries older than ~1 hour (~6 lines).

### P1-7 — Public report IDs have 32 bits of entropy and collide by silent overwrite (hosted deployments)
`src/excel_auditor/storage/reports.py:23,42-46`
- `secrets.token_hex(4)` on unauthenticated `/reports/{id}` URLs: at 10k stored
  reports, harvesting some customer report costs ~430k guesses; a birthday
  collision (50% at ~77k reports) silently overwrites another customer's report
  (`write_text`, no existence check). Documented as local-POC-only, but
  published URLs ossify — the fix is 3 lines now and painful later.
- **Fix:** `token_hex(16)`, widen `_ID_RE`, create with `open(path, "x")` and
  retry on collision. Full auth stays a pre-hosting requirement.

### P1-8 — Every report is persisted twice, in two stores, under two different IDs
`src/excel_auditor/api/routes/audits.py:32,43-48`, `storage/database.py`,
`storage/reports.py`
- Full JSON+HTML go both into SQLite `jobs` blob columns and into
  `artifacts/reports/{id}.*`, retrievable via two endpoint families. Every
  future lifecycle operation (delete-my-data, schema migration, tenancy,
  retention) must be implemented twice and can silently diverge; confidential
  content is stored 2×. Proven. The single most expensive-to-undo decision in
  the repo.
- **Fix:** drop the blob columns; store only `report_id` in jobs and delegate.

## P2 improvements (important, non-blocking)

1. **False-positive cluster eroding reviewer trust** (all proven):
   - EA-PAT-002 flags ordinary subtotal rows as HIGH "inconsistent formula"
     (`analysis/pattern_detection.py:129-135`).
   - EA-RNG-001 flags every row of a correct running-total column
     (`=SUM($B$2:B{r})`) as HIGH (`rules/suspicious_ranges.py:40-100`).
   - EA-REF-001 fires HIGH on string literals containing "#REF!" — substring
     check on raw formula text (`rules/broken_references.py:22`); tokenize
     operand tokens instead.
   - Sheet rename ripple: every `=Inputs!A1` → `=Assumptions!A1` rewrite is a
     MEDIUM "Formula logic changed" even when the same report detected the
     rename (`workbook_diff.py:276-287`); thread the rename map into
     comparison.
2. **Silent false negatives with no telemetry** (proven): formulas referencing
   a nonexistent sheet (`=Missing!A1`) produce no finding
   (`dependency_graph.py:86-87`); 3-D references (`S1:S3!A1`) silently drop out
   of the graph (`reference_parser.py:74-77`); range truncation increments
   `truncated_ranges` but nothing ever reports it. Surface all three as
   findings or report limitations.
3. **Deleted sheet full of formulas rates MINIMAL** with empty `details` and no
   review item, while one hardcoded cell rates HIGH (proven). Populate details
   with formula counts and emit a review item scaled by content.
4. **Row/column insertion produces a positional wall of changes** plus boundary
   artifacts (documented in LIMITATIONS, but the advertised "shifted references"
   INFO demotion never fires for actual insertions — anchor-relative
   normalization changes offsets — and its explanation text is wrong for the
   case where it does fire). Detect per-sheet shift patterns; this is also the
   single most expensive-to-retrofit area, so decide direction early.
5. **OS-level errors leak raw stack traces (exit 1)**: unreadable input or
   unwritable `--json-output` bypass the `ExcelAuditorError` handler
   (`cli.py:540-544`), the latter after the report was already stored. Add
   `except OSError` → clean message, exit 2.
6. **Observability is near-zero**: `log_level` setting is dead code, ~3 log
   statements system-wide, no request IDs, no report↔run correlation. A bad
   report is undiagnosable after the fact (compounds P1-5).
7. **Stored reports are unversioned** in both stores; no
   `report_schema_version`, no stored metadata (kind/created_at), SQLite has no
   migration story. One-line envelope field now avoids a painful break later.
8. **No input-file content hash in reports** — for an audit product, disputes
   about which file produced a report are unresolvable. Add `sha256` to
   `WorkbookSummary`.
9. **Error taxonomy bypassed by half the system**: query subsystem uses stdlib
   `ValueError`/`LookupError` as control flow and converts arbitrary engine
   bugs into polite "cannot answer safely" answers, unlogged, with raw internal
   strings shown (`query_service.py:160-165`); `UnsupportedQuestionError` sits
   outside `ExcelAuditorError`.
10. **Job API is a facade**: everything is synchronous; `create_failed` is dead
    code, so failures leave no job trace; no timeout/cancellation; a few
    concurrent large uploads exhaust the shared threadpool including
    `/health`. For POC: bound work (cell-count cap) and record failures; real
    workers stay future.
11. **Performance hygiene**: each workbook is fully parsed twice per load and
    up to 4× per web "ask" request; `impact_for` runs a fresh BFS per changed
    cell (O(changes × edges), unmemoized). Fine at measured POC scale;
    memoize and reuse inventories when convenient.
12. **Docker compose loses all stored reports on rebuild** (only `./data` is
    volume-mounted; artifacts live in the container layer) while job rows keep
    advertising dead URLs. Mount `./artifacts` and set the env var.

## P3 (optional cleanup)

Encrypted/legacy-`.xls` files misdiagnosed as "not a zip archive" (detect CFB
magic and say so — LIMITATIONS already promises this message); EA-HRD-001 flags
`DATE(2026,7,24)` arguments; volatile-function list missing `RANDARRAY`/`CELL`/
`INFO`; `VALUE_ADDED`/`FORMULA_ADDED` excluded from impact enrichment;
`_trace_result` ignores configured `max_range_cells`; CLI: directory input says
"File does not exist", `./artifacts` silently created in cwd with a dead
`localhost:8000` URL when `serve` isn't running, `--output-dir` doesn't move the
SQLite DB; web layer imports `api.uploads` and leaks JSON errors into HTML form
flows; SQLite connections committed but never closed; `Settings` mixes engine
and server concerns (split only when the engine is packaged separately).

## Rejected / adjusted findings

- **NaN cell equality always-changed** — rejected as practically unreachable:
  `.xlsx` number cells cannot round-trip NaN through Excel/openpyxl in any
  normal flow. Speculative edge case, no action.
- **"Exception hygiene is genuinely good" vs "silent rule failure is a P1"** —
  two agents judged the same code (`rules/base.py`) oppositely. Adjudicated:
  per-rule isolation is correct and stays; the invisibility is the defect
  (P1-5).
- **O(changes × graph) impact recomputation as P2 scaling risk** — retained but
  demoted in urgency: adversarial QA measured 8.1s / 542 MB on a
  100k-formula-cell compare, so it does not bite at POC scale.
- **Query/ask/LLM subsystem as overengineering** — rejected as out-of-intent
  bloat (it is sanctioned by `next_step.md` and cleanly isolated), but
  recommend freezing its expansion until the core audit/compare wedge has
  customers.
- **32-bit ID exploitation** — the design defect is proven; active exploitation
  remains speculative and requires a hosted deployment. Severity kept P1 only
  because the fix is 3 lines and public URLs ossify.
- Various cosmetic CLI/message items were folded into P3 or dropped.

## Architectural strengths worth keeping

1. Clean, grep-verified import direction; engine has zero
   FastAPI/Jinja/storage/LLM imports — the "swap the interface" goal is real.
2. One pydantic model family (`AuditReport`/`WorkbookComparison`/…) drives
   JSON, HTML, API summaries, and storage; `engine_version` stamped everywhere.
3. Container validation (magic bytes, entry caps, decompression-ratio guard,
   traversal rejection) runs **before** openpyxl touches the file.
4. Deterministic-by-construction analysis internals (HTML already
   byte-identical), iterative Tarjan, visited-set BFS — no recursion bombs.
5. API upload lifecycle: streamed size cap, per-request random scratch dir,
   `finally` cleanup, sanitized display names — and it's tested.
6. LLM boundary done right: `Protocol` interface, schema-only input (never cell
   data), deterministic rule-based parser shipping by default, no number ever
   produced outside the deterministic pipeline.
7. Honest docs: HANDOFF.md's shortcuts section matches the code's actual
   behavior.
8. Substantive test suite (141 tests, real assertions, messy-workbook fixtures,
   an actual XSS test) — the gaps are specific (determinism, ordering,
   self-loops, web-ask cleanup), not systemic.

## Recommended fix order

1. **Determinism trio** (P1-1): `sorted()` in `_match_sheets`, content-hash
   `workbook_id`, injectable timestamp. Hours of work, unblocks the headline
   promise, enables golden-report testing for everything else.
2. **Self-loop circular detection** (P1-3): small, local, high-trust payoff.
3. **Failed-rule surfacing** (P1-5) + report `truncated_ranges` and
   unresolvable-sheet references (P2-2): makes reports honest about coverage.
4. **Named-range/table resolution in the graph** (P1-4) — or the interim
   "impact unknown" honesty marker if resolution slips.
5. **Rename handling** (P1-2 fuzzy match + P2-1 rename-aware formula
   comparison) — one coherent piece of work.
6. **Storage hardening** (P1-7 + P1-8 + P2-7): `token_hex(16)` + exclusive
   create; drop blob columns from jobs; add `report_schema_version`.
7. **Web-ask upload cleanup** (P1-6).
8. **False-positive cluster** (P2-1): EA-REF tokenized check, subtotal and
   running-total suppression.
9. **CLI OSError handling** (P2-5), log-level wiring (P2-6), docker artifacts
   mount (P2-12).

## Recommended tests

- Golden determinism test: run audit and compare twice (different
  `PYTHONHASHSEED` subprocesses), byte-compare JSON and HTML.
- Self-referencing cell (`=A1+1` in A1) and self-including SUM → EA-CIR-001.
- Rename + single cell edit → rename detected AND the cell change reported.
- Named-range and `Table1[Col]` precedent → nonzero downstream impact.
- Regression: subtotal row, running-total column, `"#REF!"` string literal,
  rename ripple → no HIGH/MEDIUM findings.
- Monkeypatched crashing rule → report carries a visible failed-rule warning.
- Web-ask: abandoned confirmation and mid-flow exception → no file left under
  `artifacts/uploads`.
- `chmod 000` input and unwritable `--json-output` → clean error, exit 2.
- `=Missing!A1` → a finding (once implemented).
- Report-store collision: pre-create the ID's file → save must not overwrite.

## Final verdict

**Internal-test-ready.** Safe to run, architecturally sound, well-tested at the
unit level, with security surfaces that held under adversarial testing — but
the determinism promise is currently false, three headline detections fail
silently in market-typical cases, and one documented data-retention guarantee
is not kept. The eight P1s are all small, local fixes (the largest is
named-range resolution); after them, and a pass on the false-positive cluster,
this is a credible customer-pilot candidate.
