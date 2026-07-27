# Milestone 3.5 — Progress / Final State

Status: **complete and merged**. `feat/rounding-checks` merged into `main`
(2026-07-27). All §5 gates of `docs/plans/milestone-3.5-prompt.md` passed;
nothing was blocked.

## Final state

- **311 tests passing** (baseline 296 → 311; +15), ~5 s, ruff clean, mypy
  clean (75 source files, was 74).
- Two new rules: **EA-RND-001** "Displayed figures don't add up" and
  **EA-RND-002** "Precision as displayed is enabled", both severity MEDIUM /
  confidence HIGH, in the new self-contained `analysis/rules/rounding.py`
  (D15 decimals parser included). 19 registered rules total.
- No schema bump (D19): new rule ids and evidence keys are additive within
  report schema v3.
- Inventory now captures `wb.calculation.fullPrecision` into
  `WorkbookInventory.full_precision` (`bool | None`; absent stays `None` and
  never triggers EA-RND-002 — verified end-to-end with a real file, since
  openpyxl round-trips `fullPrecision=False` and defaults to `None`).
- **D18 shipped** (not deferred): `_cross_link_rounding` post-pass in
  `rules/base.py` (~30 lines, runs before grouping) adds
  `evidence["related_finding_rule_ids"]` both ways on same-coordinate
  EA-RND-001 × EA-PAT-001/EA-HRD-001 matches, plus
  `evidence["related_finding_note"] = "likely manual rounding adjustment —
  see EA-RND-001"` on the manual-fix side. Note: EA-HRD-001 findings are
  sheet-level (no coordinate), so in practice only EA-PAT-001 can match —
  same-coordinate-only is per D18, no fuzzy proximity.
- T2 shipped: demo v2 gained a "Фактури" sheet (anomaly 11 — three line
  items with sub-cent residue, hand-corrected total, drift −0.01 лв),
  `demo_tour.py` stop 7, README/HANDOFF/presentation updated, demo
  artifacts regenerated with pinned `--generated-at 2026-07-27T12:00:00Z`
  (gitignored, on disk).

## Commits

| Commit | Content |
|---|---|
| `ea6dca3` | T1: `rules/rounding.py` (D15 parser, EA-RND-001/002), inventory `full_precision`, D18 post-pass in `rules/base.py`, 15 tests |
| `1ace4e7` | merge `feat/rounding-checks` → `main` |
| `f6a9ad8` | T2: demo Фактури sheet, tour stop 7, docs pass, counts 296→311 |

## Gate results (§5)

| Gate | Result |
|---|---|
| Full suite | **311 passed** (296 → 311), 0 failed/skipped |
| ruff / mypy | clean / clean (75 files) |
| Determinism | existing golden tests green + new `test_report_with_rnd_findings_byte_identical_across_hash_seeds` (JSON+HTML byte-identical, PYTHONHASHSEED 0/42, asserts EA-RND-001 is actually in the report); demo artifacts regenerated pinned |
| Live check | `excel-auditor audit` on a drift fixture prints `[medium] EA-RND-001 Фактури!A4`; JSON evidence carries drift `-0.01`, currency `BGN`, displayed sums, 3 residue cells with stored vs displayed |
| Docs | README rule table +2 rows; HANDOFF (19 rules, fullPrecision); presentation slide 4 + FAQ; zero stale "296"/"16 rule" mentions (grep-verified) |

## Implementation decisions within work-order authority

1. **Hardcoded-total range inference + stored-agreement guard.** D16 defines
   the range only for SUM/SUBTOTAL totals; for hardcoded totals (acceptance
   criterion 1) the components are inferred as the contiguous numeric run
   directly above (then left of) the constant, capped at 200 cells. To keep
   this at zero false positives, a guard requires the stored figures to
   actually agree: `|Σ stored components − stored total| < 10^(−d_t)`.
   A random constant under a data column fails the guard; a hand-corrected
   total (off by sub-display residue only) passes. The guard applies to
   formula totals too, which also protects against stale cached SUM values
   and formulas like `=SUM(A1:A3)*2`.
2. **Criterion 5 vs D16 conflict.** The criterion's literal example has two
   components (`100.4 + 100.4 = 200.8`), but approved D16 requires ≥ 3
   populated components. D16 outranks the example: the test uses three
   `100.4` components (same `#,##0` zero-decimals format, same 1-whole-unit
   drift), and a companion test pins the two-component case to **no**
   finding. Flagging here rather than escalating since D15–D19 are approved
   and non-negotiable.
3. "Single-area range" is enforced as *exactly one* reference token in the
   total formula (conservative; multi-area or extra references skip).
4. Non-numeric populated cells anywhere in a SUM range → conservative skip
   (they can't carry parseable fixed decimals in a meaningful way).
5. Currency codes recognized for evidence: € → EUR, лв → BGN, £ → GBP,
   $ → USD (checked in that order so `[$€-…]` maps to EUR).

## Honest notes / skip conditions

EA-RND-001 deliberately skips (no finding) when: any populated component has
an unparseable/variable/percent/date/General format; the total format is
unparseable; fewer than 3 populated numeric components; any needed stored
value is missing (openpyxl-generated formulas have no cached values); stored
sum and stored total disagree by ≥ one display unit; |drift| < one display
unit of the total. Percent display scaling is out of scope this round (D15).
Rounding is `decimal.ROUND_HALF_UP` on `Decimal(str(value))` — Excel-style
ties-away-from-zero; a dedicated test pins the case where float `round()`
would flip the drift sign.

## Deferred / future candidates

- **Nothing from this milestone's scope was deferred** (D18 included).
- Future candidate noted per §4: VAT per-line vs per-invoice rounding-policy
  checking (a bigger feature), plus percent-format display scaling,
  AVERAGE/other aggregations, cross-sheet ranges.

## How a cold session resumes

Everything is on `main` (pushed; see final hash in git). Demo artifacts are
regenerable with `scripts/generate_demo_workbooks.py demo_workbooks` then
`excel-auditor audit|compare … --generated-at 2026-07-27T12:00:00Z` into
`demo_workbooks/`. The narrated demo is `.venv/bin/python
scripts/demo_tour.py` (stop 7 = the off-by-a-stotinka invoice). Quick live
repro: audit any workbook whose components store sub-display precision under
a hardcoded or SUM total.
