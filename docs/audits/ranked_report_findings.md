# Verified Release-Blocking Findings — excel-auditor

- **Date:** 2026-07-24 · **Commit:** `460d866` (clean tree)
- **Scope:** independent verification of `AUDIT_REPORT.md`. Every P0/P1 claim was
  reproduced or refuted against the source (live reproductions, not code reading
  alone), severities re-adjudicated, proposed fixes checked for root-cause fit
  and regression risk, and an adversarial sweep run for issues the audit missed.
- **Baseline re-verified:** 141 tests passed (~0.9 s). No repository files were
  modified during verification; all repro scripts ran from an external scratchpad.
- **Verdict on the original audit:** all eight P1 mechanisms are real and were
  reproduced; no false positives among them. One supporting detail was wrong
  (EXCEL-005), one finding was understated (SECURITY-001), one is
  borderline-exaggerated (SECURITY-002, downgraded to conditional), and the
  audit missed two P1-grade silent-wrong-answer bugs in the query/ask subsystem
  (QA-001, QA-002). "No P0s" is confirmed: nothing is unsafe to run.

Identifier scheme: `EXCEL-*` engine/analysis correctness · `QA-*` query/ask
subsystem · `SECURITY-*` data retention/access · `ARCH-*` storage architecture.
Original audit IDs are cross-referenced as (P1-n).

---

## 1. Confirmed blockers

### QA-001 — Duplicate column headers: answer computed from the wrong column, returned as `verified` (NEW)
`src/excel_auditor/analysis/resolution.py:197-205`, `src/excel_auditor/analysis/query.py:68-75,273`

Two compounding defects. `_dedupe` keys candidate matches on column *name*, so
two physically distinct columns sharing a header collapse into a single
"resolved" match and the `needs_confirmation` machinery — which exists for
exactly this case — never fires. `load_table_frame` then builds the DataFrame
keyed by name, so the later column silently overwrites the earlier one:
computation reads the *last* physical column while resolution provenance
reports the *first*.

- **Proven:** headers `Category | Amount | Amount` (sums 60 vs 6000); "what is
  the total amount" → **6000.0, status `verified`**, empty provenance warnings,
  no candidates. Same failure via structured `--value-column Amount`.
- **Why blocking:** violates the documented "ambiguity is never resolved
  silently" guarantee with a plausibly 100×-wrong number. Duplicate headers are
  routine in ERP/bank exports. Also affects filter and group-by column lookup.
- **Fix:** dedupe on physical position `(sheet, table_ref, column_index)`, not
  name; make same-name multi-column matches return `needs_confirmation`; build
  frames positionally.
- **Regression risk of fix:** low; ensure single-column workbooks still resolve
  without a confirmation prompt.

### QA-002 — Numeric thresholds silently dropped; unfiltered results returned as `verified` (NEW)
`src/excel_auditor/llm/rule_parser.py:173` (with `_NUMBER_RE` at `:27`)

The list-rows branch extracts the threshold with
`_NUMBER_RE.search(norm.replace(" ", ""))`. Stripping all spaces glues the
number to the preceding word ("…amountover500") and the regex's `(?<![\w.])`
lookbehind can then never match, so the threshold is essentially never
extracted. The query proceeds as an unfiltered `LIST_ROWS`.

- **Proven:** "show rows where amount over 500" against amounts
  100/200/700/900 → parses to `list_rows`, `filters=[]`, answers with **all
  four rows, status `verified`**. Aggregate phrasings ("how many … over 500")
  never build a threshold filter on any path and return the unfiltered count as
  `verified`. Regex root cause proven directly.
- **Why blocking:** a dedicated, keyword-advertised feature (`_EXCEED_KEYWORDS`,
  "List rows with a numeric threshold") silently answers a different question
  than asked — the exact failure the product's "refuse rather than be wrong"
  pitch forbids. Zero test coverage.
- **Fix:** extract the number from the original (space-preserving) normalized
  text; if a threshold keyword matched but no number/column filter could be
  built, refuse (`cannot_answer`) instead of running unfiltered.
- **Regression risk of fix:** low; keep Bulgarian keyword paths covered.

### EXCEL-001 — Sheet rename + any edit ⇒ all cell edits on that sheet vanish (P1-2)
`src/excel_auditor/analysis/workbook_diff.py:39-68` (exact-signature requirement at `:60-63`)

- **Proven:** rename "Inputs"→"Assumptions" plus one value edit → report shows
  `sheet_removed` + `sheet_added` and **zero cell changes**; control
  (rename-only) is correctly detected as `sheet_renamed`.
- **Fix (with required correction):** fuzzy rename matching is the right
  direction **but** the proposed "single removed+added pair" heuristic would
  mis-pair genuinely different sheets (delete `Q1`, add `Q2`), converting clean
  removed/added semantics into a wall of bogus cell diffs. Require a
  content-similarity threshold (e.g. >80% shared `(coordinate, formula)`
  entries), label the rename as *inferred*, then run the normal cell diff on
  the matched pair.

### EXCEL-002 — Self-referencing circular formulas never detected (P1-3)
`src/excel_auditor/analysis/dependency_graph.py:113-114` (dead branch at `:182`)

- **Proven:** `A1 = =A1+1` and `D11 = =SUM(D1:D11)` produce no EA-CIR-001; a
  two-cell cycle in the same workbook IS detected. The self-loop branch in
  `cycles()` is unreachable because self-edges are never recorded.
- **Fix:** record self-edges in a dedicated set consulted by the circular rule
  (root cause addressed). **Note:** if self-edges stay out of traversal,
  `impact_for`'s `is_circular` must also consult the self-edge set or it stays
  `false` for self-loops.

### EXCEL-003 — Named ranges and structured table references invisible to impact analysis (P1-4)
`src/excel_auditor/analysis/dependency_graph.py:74-76`

- **Proven:** input referenced via `=MyInput*2` → `transitive_dependent_count = 0`,
  severity stays `low`; identical model with a direct reference →
  `transitive = 2` and normal escalation. Severity escalation
  (`analysis/severity.py:63-66`) therefore never triggers for name-routed
  drivers. The inventory already parses `named_ranges.refers_to` and
  `tables.ref` (verified), so resolution is wiring, not new parsing.
- **Framing correction:** HANDOFF.md:173-175 already documents the
  structured-table part as a known limitation; the named-range zero-impact
  behavior is the undocumented, market-critical part.
- **Fix (with required correction):** name/table → range lookups address the
  root cause, but a naive implementation must handle multi-area `refers_to`,
  constant-valued names (`="0.05"`), sheet-scoped name shadowing, and `#REF!`
  names — mis-resolution would be worse than the current zero. The interim
  "impact unknown — formula uses defined names" marker is the safe first step
  if full resolution slips.

### EXCEL-004 — Reports are not deterministic (P1-1)
`src/excel_auditor/analysis/workbook_inventory.py:242`, `src/excel_auditor/services.py:64,79`, `src/excel_auditor/analysis/workbook_diff.py:45`

- **Proven:** (a) two audits of the same file produce different `workbook_id`s
  (uuid4), embedded in the report and in every finding location; (b) three
  distinct structural-change orderings observed across four `PYTHONHASHSEED`
  values (`old_names & new_names` set iteration); (c) `generated_at` embedded
  with no injection point. HTML output verified byte-identical already, as the
  audit claimed.
- **Additionally verified complete:** a suspected fourth source (Tarjan
  iterating set-valued adjacency → cycle-finding order) was tested across five
  seeds and **refuted** — component discovery order is
  dict-insertion-deterministic and members are sorted in the rule.
- **Severity note:** (a)+(b) are the substance; (c) is ordinary report metadata
  and the minor leg.
- **Fix:** content-hash (SHA-256 prefix) `workbook_id`; `sorted()` the set
  intersection; injectable/excludable timestamp. No regressions; the content
  hash also delivers the audit's P2-8 file-hash item for free.

### EXCEL-005 — A crashed rule leaves no trace in the delivered report (P1-5)
`src/excel_auditor/analysis/rules/base.py:107-110`

- **Proven:** with a monkeypatched crashing rule, the delivered report reads
  `risk_level: minimal`, "no findings above info severity" — indistinguishable
  from a genuinely clean run.
- **Detail corrected:** the original audit's "logging is effectively
  unconfigured" is wrong. The CLI calls `logging.basicConfig(INFO)`
  (`cli.py:535-537`), and even unconfigured, Python's last-resort handler
  prints the `logger.exception` traceback to stderr. The precise defect: the
  *report artifact* — the deliverable customers keep — carries no trace, and
  API consumers never see the server's stderr.
- **Fix:** collect failed rule IDs and surface them in
  `AuditReport`/`WorkbookComparison` (the `limitations`/`risk_drivers`
  plumbing exists). Per-rule isolation stays.

### SECURITY-001 — Web "ask" flow retains customer workbooks, contradicting the documented deletion guarantee (P1-6, broader than originally reported)
`src/excel_auditor/web/routes.py:123-189`

- **Proven (broader than the audit stated):** uploading an *invalid* file to
  `/ask` returns 422 and permanently leaks the parked workbook under
  `artifacts/uploads/{token}` — reproduced live via TestClient. So the leak
  covers: (1) any pre-parse failure (undocumented), (2) any exception during
  `answer_query` (undocumented), and (3) abandoned confirmation flows
  (disclosed in HANDOFF.md:141-142 but contradicted by README:212-213's
  unqualified "deleted immediately after processing (verified by test)"). The
  deletion test covers only the API `data/uploads` path (verified:
  `tests/integration/test_api.py:96-101`).
- **Fix (with required correction):** the proposed plain `try/finally` **would
  break the confirmation flow** — the parked file must survive the
  `NEEDS_CONFIRMATION` return. Correct shape: delete on every exit path
  *except* needs-confirmation, plus a startup/periodic TTL sweep of
  `web_upload_dir` (~1 h), which also covers abandonment and crash leaks.

### ARCH-001 — Dual persistence of reports; documented purge instruction is ineffective (P1-8, strengthened)
`src/excel_auditor/api/routes/audits.py:32,43-48`, `storage/database.py`, `storage/reports.py`, served via `api/routes/jobs.py:43-48` and `api/routes/public_reports.py`

- **Proven:** full JSON+HTML stored in SQLite `jobs` blob columns *and* under
  `artifacts/reports/{id}.*`, retrievable through two endpoint families.
- **Strengthened beyond the original audit:** this breaks a documented promise
  *today* — README:215-217 instructs "delete rows/file to purge", but doing so
  leaves the report live at its public `/reports/{report_id}` URL. Data
  deletion, not just architecture debt.
- **Fix (with required correction):** drop the blob columns and delegate — but
  the jobs report endpoints must be rewired to the report store (the
  `report_id` is already in the job summary, so wiring exists), and existing
  DBs need a migration story (`CREATE TABLE IF NOT EXISTS` will not remove the
  old columns).

---

## 2. Downgraded findings

### SECURITY-002 — 32-bit public report IDs, silent collision overwrite (was P1-7 → conditional: P2 local, P1 if hosted)
`src/excel_auditor/storage/reports.py:23,42-46`

- **Mechanism confirmed:** `secrets.token_hex(4)` (32 bits), unconditional
  `write_text` with no existence check; the ~430k-guess (10k stored reports)
  and ~77k-report birthday arithmetic checks out.
- **Why downgraded:** exploitation requires a hosted deployment the
  documentation explicitly rules out, and overwrite collisions need report
  volumes far beyond any pilot. Not release-blocking for the documented
  local-only deployment; becomes P1 the moment anything is hosted.
- **Keep the fix anyway** (3 lines): `token_hex(16)`, exclusive create
  (`open(path, "x")`) with retry. **Regression note:** widening `_ID_RE` to
  32-hex only would 404 every previously stored 8-hex report — accept both
  lengths or migrate.

### EXCEL-004(c) — embedded `generated_at` timestamp (sub-item of P1-1)

Retained inside EXCEL-004 but noted as the minor leg: embedded generation
timestamps are ordinary report metadata across the industry. It matters only
for byte-level golden testing and report diffing; the uuid and set-ordering
legs are the real determinism defects.

---

## 3. Rejected findings

No original P1 finding was rejected as a false positive — all eight mechanisms
reproduced. The following *claims* were rejected or corrected during
verification:

1. **"Logging is effectively unconfigured" (inside P1-5)** — rejected. The CLI
   configures `basicConfig` (`cli.py:535`); Python's last-resort handler prints
   ERROR-level records to stderr even without configuration. The finding stands
   on the corrected basis (report-artifact silence), not this claim.
2. **Suspected fourth determinism source (verifier's own hypothesis)** —
   Tarjan's iteration over set-valued adjacency was suspected to make
   EA-CIR-001 finding order seed-dependent with multiple cycles. Tested across
   five hash seeds: order is stable (dict-insertion component discovery, sorted
   members). Rejected; the audit's three causes stand as the demonstrated set.
3. **Original audit's own rejections re-affirmed:** NaN cell-equality
   (practically unreachable via Excel/openpyxl round-trip) and the
   query-subsystem-as-bloat claim — no evidence found contradicting either
   adjudication. Spot-checked P2 gradings (EA-REF-001 `"#REF!"` substring false
   positive, `=Missing!A1` silence, severity-escalation caps) verified at the
   assigned severity; none warrant promotion to P1.

---

## 4. Newly discovered findings

| ID | Grade | Summary |
|----|-------|---------|
| QA-001 | **P1** | Duplicate column headers → wrong column aggregated, `verified`, no confirmation prompt (full entry in §1). |
| QA-002 | **P1** | Numeric threshold questions silently answered unfiltered as `verified` (full entry in §1). |
| QA-003 | P2 | Schema-valid query with a filter missing `value` reaches `float(None)` → `TypeError`, escaping the `(LookupError, ValueError)` guard: HTTP 500 on `POST /api/v1/queries`, unhandled traceback on the CLI path (`analysis/query.py:148,131`, `query_service.py:160`). Proven. |
| (folded into ARCH-001) | — | README purge instruction ineffective while the artifacts copy stays public. |
| (folded into SECURITY-001) | — | `/ask` leaks the parked upload on *any* pre-parse failure (422), not only abandonment/mid-flow exceptions. |

Sweep coverage note: templates/XSS (autoescape everywhere, no `|safe`, no
workbook-derived URLs), upload/path handling, SQL parameterization, parser
loading, formula-normalization INFO-demotion soundness, and severity
reconciliation were re-examined and found sound.

---

## 5. Recommended implementation order

1. **EXCEL-004** — determinism trio (`sorted()` intersection, content-hash
   `workbook_id`, injectable timestamp). Hours of work; unblocks byte-level
   golden-report testing that guards every subsequent fix.
2. **QA-002** — threshold extraction + refuse-when-unfiltered. Small parser
   fix; stops `verified` wrong answers immediately.
3. **QA-001** — position-keyed resolution dedupe + positional frame build +
   `needs_confirmation` on same-name columns. (Fix QA-003's `float(None)`
   guard in the same pass — same files.)
4. **EXCEL-002** — self-edge set + circular rule (+ `is_circular` consult).
   Small, local, high trust payoff.
5. **EXCEL-005** — failed-rule surfacing in the report (pair with the original
   audit's P2-2 truncation/unresolvable-sheet reporting if convenient).
6. **EXCEL-003** — ship the "impact unknown" honesty marker first; full
   name/table resolution as a follow-up with the edge cases listed in §1.
7. **EXCEL-001** — fuzzy rename matching with similarity threshold, plus the
   original audit's rename-aware formula comparison (P2-1 ripple item) as one
   coherent piece of work.
8. **ARCH-001 + SECURITY-002** — storage hardening in one pass: drop blob
   columns, rewire jobs endpoints to the report store, `token_hex(16)` +
   exclusive create with legacy-ID compatibility, add `report_schema_version`
   (original P2-7).
9. **SECURITY-001** — web-ask lifecycle: delete on all paths except
   needs-confirmation + TTL sweep; correct README:212-214 wording in the same
   change.

---

## 6. Regression tests required per fix

**EXCEL-004 (determinism)**
- Golden test: audit and compare the same fixture twice in subprocesses with
  different `PYTHONHASHSEED`; byte-compare JSON (timestamp injected/excluded)
  and HTML.
- Same content → same `workbook_id`; changed content → changed `workbook_id`.
- Multi-sheet visibility/merged/hidden structural changes emit in sorted order.

**QA-002 (threshold)**
- "show rows where amount over 500" → only qualifying rows; provenance carries
  the filter.
- "how many customers have amount over 500" → filtered count or explicit
  `cannot_answer` — never the unfiltered count.
- "exceeds", "above", "more than", and Bulgarian keyword variants; thousands
  separators ("over 10 000").
- Threshold keyword present but no extractable number → refusal, not an
  unfiltered `verified` answer.

**QA-001 (duplicate headers)**
- Two same-named columns with different data → `needs_confirmation` listing
  both physical columns; after a choice, the sum matches the chosen column.
- Frame built from `Category|Amount|Amount` preserves both columns (no
  overwrite); filter and group-by lookups hit the chosen physical column.
- Single unambiguous column still resolves without a prompt (no regression).
- QA-003 guard: filter missing `value` → clean `cannot_answer`/422, never 500.

**EXCEL-002 (self-loops)**
- `A1 = =A1+1` → EA-CIR-001; `D11 = =SUM(D1:D11)` → EA-CIR-001.
- Existing multi-cell cycle detection unchanged; `impact_for` on a self-loop
  cell reports `is_circular = true`; traversal still terminates.

**EXCEL-005 (failed-rule surfacing)**
- Monkeypatched crashing rule → report carries a visible failed-rule warning
  and risk drivers mention incomplete coverage; other rules' findings intact.
- Clean run → no failed-rule warning (no false alarm).

**EXCEL-003 (named ranges/tables)**
- Named-range precedent (`=MyInput*2`) → nonzero downstream impact and severity
  escalation parity with the direct-reference control.
- `Table1[Col]` precedent → dependents resolved to the column sub-range.
- Multi-area `refers_to`, constant-valued name (`="0.05"`), sheet-scoped name
  shadowing a global, `#REF!` name → no crash, no mis-resolution (skip or mark
  unknown).
- Interim marker (if shipped first): defined-name formula → "impact unknown"
  marker present, never `transitive = 0` with full confidence.

**EXCEL-001 (rename matching)**
- Rename + single cell edit → `sheet_renamed` (inferred) AND the cell change
  reported.
- Removed `Q1` + added `Q2` with genuinely different content → stays
  removed/added (no false rename pairing).
- Two removed + two added similar sheets → ambiguity handled (no arbitrary
  pairing); byte-identical rename still detected as before.

**ARCH-001 + SECURITY-002 (storage)**
- Job report endpoints serve identical content after blob columns are dropped;
  deleting the artifacts files makes the report irretrievable from *both*
  endpoint families (purge instruction actually purges).
- Existing DB with legacy blob columns still opens (migration).
- Pre-create the ID's file → save must not overwrite (exclusive create + retry).
- Legacy 8-hex report IDs remain loadable; new IDs are 32-hex.

**SECURITY-001 (web-ask lifecycle)**
- Invalid/corrupt upload to `/ask` → error page AND nothing left under
  `artifacts/uploads` (regression for the proven 422 leak).
- Mid-flow exception during `answer_query` → no file left behind.
- `NEEDS_CONFIRMATION` → parked file survives; completing the confirmation
  answers correctly and then deletes it.
- Abandoned confirmation → TTL sweep removes the directory; a parked file
  younger than the TTL is not swept mid-flow.

---

*Verification artifacts (repro scripts) live outside the repository in the
session scratchpad. No source files were modified.*
