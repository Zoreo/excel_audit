# Milestone 3.5 — Rounding-Drift Reconciliation (single-worker execution)

You are implementing one small, high-value feature in **excel-auditor**:
detecting **cent-level rounding drift** — the accountant's classic "the
displayed figures don't add up to the displayed total" problem that today
forces manual hunting and hand-typed corrections.

This is a deliberately tiny milestone: one worker (W-A) + lead gates. Follow
the same discipline as `docs/plans/milestone-3-prompt.md` (ownership,
escalate-don't-improvise, auto-merge on green, mandatory wrap-up).

## 0. Baseline and ground rules

- **Baseline:** `main` @ `66cce80` — 296 tests green, ruff clean, mypy clean,
  report schema v3. Verify before branching.
- **Branch:** `feat/rounding-checks`; merge to `main` and push when all §5
  gates pass (approved auto-merge policy). Remote is named `main`.
- Worktree caveat as always: run tests with `PYTHONPATH=<worktree>/src`.
- No edits to `tests/conftest.py`, `README.md`, `HANDOFF.md`,
  `docs/presentation.md`, `demo_workbooks/` by the worker — lead only.
- All engine work stays deterministic; tests offline; no new dependencies
  (the stdlib `decimal` module is the whole toolbox).

## 1. The domain problem (context for the implementer)

Excel stores full precision but displays rounded values. Components store
`12.344 / 10.333 / 8.328` and display `12.34 / 10.33 / 8.33`; `SUM` works on
stored values → `31.005`, displayed `31.01`; the displayed components add to
`31.00`. The printed document is off by one cent. Accountants "fix" this by
overwriting totals or adding `+0.01` fudges — which our existing rules
(EA-PAT-001, EA-HRD-001) flag as risks without understanding why. This
milestone detects the drift itself, names the cells carrying sub-display
residue, and cross-references the manual fixes.

## 2. Approved decisions (continue numbering after milestone 3's D14)

| # | Decision |
|---|---|
| **D15** | **Display decimals come from the number format.** A private helper in the new rule module parses fixed decimal places from `number_format`: `"#,##0.00"` → 2, `"0.000"` → 3, `"#,##0"` → 0, `"#,##0.00 €"` / `'#,##0.00 "лв"'` → 2 (ignore quoted literals and currency symbols; use the first format section, before any `;`). `General`, text, date and **percent** formats return `None` and the cell does not participate (percent display scaling is out of scope this round). |
| **D16** | **EA-RND-001 "Displayed figures don't add up".** Applies to `SUM`/`SUBTOTAL` totals over a single-area, same-sheet range (reuse the parsing approach of `rules/suspicious_ranges.py`) when: the total cell has fixed display decimals `d_t`; the range has ≥ 3 populated numeric components; **every** populated component has parseable fixed decimals (else skip — conservative, no false positives); and stored values exist for all participants (total = formula **with cached value** or a hardcoded constant; components = constants or cached formula values — if any needed value is missing, skip silently, no finding). Computation: `displayed_components = Σ round(value_i, d_i)`; `displayed_total = round(total_value, d_t)`; `drift = displayed_components − displayed_total`. Flag when `|drift| ≥ 10^(−d_t)` (≥ 1 displayed unit — one cent at 2dp, one лв at 0dp). **Rounding must match Excel display rounding: ties away from zero** — use `decimal.Decimal(str(value)).quantize(..., rounding=decimal.ROUND_HALF_UP)`; never round floats with `round()` (banker's rounding — wrong). Severity **MEDIUM**, confidence **HIGH** (it is arithmetic on the file's own stored values). Evidence: drift amount (+ currency code when the column has one), displayed-components sum, displayed total, and up to 10 residue-carrying cells (`|stored − round(stored, d_i)| > 1e-9`) with stored vs displayed values. Suggested action: apply a consistent `ROUND()` policy on the components or document the adjustment. |
| **D17** | **No standalone "hidden precision" rule** — flagging every cell with sub-display residue would be pure noise (any division produces residue). Residue cells appear only inside EA-RND-001 evidence. Instead, **EA-RND-002 "Precision as displayed is enabled"**: when the workbook's calculation properties have `fullPrecision="0"` (Excel's *Set precision as displayed*), emit one workbook-level finding — severity MEDIUM, confidence HIGH (the setting permanently destroys stored precision on save). Requires capturing the flag at inventory time (see T1 files). |
| **D18** | **Cross-reference the manual fixes (small, bounded).** After all rules run, a post-pass in `rules/base.run_all_rules` adds `evidence["related_finding_rule_ids"]` to any EA-RND-001 finding whose total cell coordinate also carries an EA-PAT-001 or EA-HRD-001 finding (and vice versa), with a one-line note "likely manual rounding adjustment — see EA-RND-001". Same-coordinate matches only; no fuzzy proximity. If this exceeds ~30 lines of code, ship EA-RND-001/002 without it and record the deferral. |
| **D19** | **No `report_schema_version` bump.** Findings are an open list; new rule ids and evidence keys are additive within schema v3. |

## 3. Task specification

### T1 — EA-RND rules *(W-A)*

- **New:** `analysis/rules/rounding.py` — self-contained: the D15 decimals
  helper, EA-RND-001, EA-RND-002. Register in `rules/base.py` (import line
  only, matching the existing pattern).
- **Inventory support:** `models/workbook.py` gains
  `full_precision: bool | None = None` on `WorkbookInventory`;
  `analysis/workbook_inventory.py` populates it from
  `wb.calculation.fullPrecision` (defensive `getattr`, absent → `None`,
  and `None` must NOT trigger EA-RND-002 — only an explicit `False`).
- **Tests:** `tests/unit/test_rounding_rules.py` (new file). Rules operate on
  `AuditContext`, so cached-formula-total cases may build
  `SheetInventory`/`CellRecord` models directly in the test (no file
  needed); constant-total cases use `make_workbook`-style real files.
- **Must not modify:** `analysis/schema.py`, `analysis/query.py`,
  `workbook_diff.py`, `resolution.py`, `reporting/*`, `api/*`, `cli.py`,
  any existing rule file, `models/reports.py`.

**Acceptance criteria (all must have tests):**

1. Components stored `12.344, 10.333, 8.328` all formatted `#,##0.00`,
   hardcoded total `31.005` formatted `#,##0.00`: displayed components sum
   to `31.00`, displayed total is `31.01` (31.005 half-up) → EA-RND-001
   fires with `|drift| = 0.01`; evidence lists the three residue cells with
   stored vs displayed values. Pick a sign convention for `drift`
   (spec: `displayed_components − displayed_total`, here `−0.01`), assert it
   in the test, and keep the evidence wording consistent with it.
2. Same components but total formula `=SUM(...)` with cached value `31.005`
   (inventory built in-test) → same finding.
3. Clean control: components `12.34, 10.33, 8.33` (exact 2dp), total `31.00`
   → **no** finding.
4. Half-away-from-zero: a case where `round()` (banker's) and Excel-style
   HALF_UP disagree (e.g. component `2.345` → displays `2.35`, not `2.34`)
   asserting the Decimal path is used.
5. Zero-decimals format (`#,##0`): whole-лв components `100.4, 100.4` with
   total `200.8` → displayed 100+100=200 vs total 201 → flagged with drift
   of 1 unit.
6. Mixed/unparseable formats in the range (one component `General`) → no
   finding (conservative skip).
7. Formula total with **no cached value** (plain openpyxl-generated file) →
   no finding, no crash.
8. Percent-formatted range → skipped entirely.
9. EA-RND-002: inventory with `full_precision=False` → workbook-level
   finding; `True` and `None` → none.
10. D18 (if implemented): a hardcoded total that both drifts and sits in a
    formula pattern → EA-RND-001 and EA-PAT-001 each carry the cross-link.
11. Determinism: the audit report containing EA-RND findings is
    byte-identical across two runs with different `PYTHONHASHSEED`.
12. Full baseline suite still green.

### T2 — Demo + docs *(lead, after T1 merges; recommended, skippable)*

- Add a small "Фактури" rounding-drift sheet to the demo generator
  (`demo.py`) — 3 line items with sub-cent residue + hardcoded corrected
  total — so the flagship demo shows the finding. This intentionally changes
  the determinism goldens and demo artifacts: regenerate both, pinned
  `--generated-at`.
- Optional sixth `scripts/demo_tour.py` stop: "the invoice that's off by a
  cent — found, explained, with the guilty cells named".
- Docs pass: README rule table (+ EA-RND row), HANDOFF (new rules +
  full-precision capture), presentation slide 4 bullet ("cent-level rounding
  drift in totals") and, if natural, one FAQ line. Test counts re-synced —
  they have gone stale twice before; check explicitly.

## 4. What NOT to build (scope guard)

- No standalone residue-cell rule (D17 rationale).
- No percent-format handling, no AVERAGE/other aggregations, no cross-sheet
  ranges, no VAT-specific logic (per-line vs per-invoice policy checking is
  a future, bigger feature — note it in the wrap-up as a candidate).
- No config/env knobs for thresholds; constants live in the rule module.
- No query-engine `reconcile` operation.
- No new dependencies.

## 5. Gates (lead, before merge)

| Gate | Requirement |
|---|---|
| Full suite | green (record before → after counts) |
| ruff / mypy | clean / clean |
| Determinism | JSON+HTML byte-identical across `PYTHONHASHSEED` runs (incl. regenerated goldens if T2 ran) |
| Live check | `excel-auditor audit` on a drift fixture prints the EA-RND-001 finding with drift amount and residue cells |
| Docs | README/HANDOFF/presentation consistent; no stale counts |

## 6. Wrap-up (mandatory)

Same shape as milestone 3 §7: write
`docs/plans/milestone-3.5-progress.md` (state, commits, gate results,
deferrals — D18 status explicitly), push, and end with a chat report:
what was built, exact demo command for the new finding, honest notes
(e.g. skip conditions), and the pushed commit hash.
