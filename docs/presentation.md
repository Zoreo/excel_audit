# excel-auditor — Pitch Presentation (working draft)

> **How to use this document.** Each `##` section is one slide. Speaker notes
> are in blockquotes like this one — don't put them on the slide. Anything
> marked **[TO FILL]** is a placeholder we must NOT present as fact until we
> have real data behind it. Appendix A is not for pitching — it's the
> plain-language explanation of how the product actually works, for us.

---

## 1. Title

**excel-auditor**
*Намерете грешката, преди тя да намери вас.*
(Find the error before it finds you.)

Deterministic audit, version-diff and verified Q&A for Excel workbooks.

> One-liner if someone asks "so what is it": *"Git diff and risk analysis for
> Excel — plus a question-answering mode that can prove where every number
> came from."*

---

## 2. The problem

If a spreadsheet drives real decisions — a budget, a cash-flow forecast, a
loan book, a client's annual accounts — three things go wrong all the time:

1. **Silent errors.** A formula overwritten with a hardcoded number. A total
   that stops one row short. A SUM that includes itself. Excel doesn't warn;
   the model keeps producing confident, wrong numbers.
2. **Version anxiety.** `model_v7_FINAL(2).xlsx` arrives. What changed since
   the version the client approved? Which change reaches the bottom line?
   There is no built-in, readable diff for workbooks.
3. **Numbers nobody can stand behind.** "Какъв е оборотът за 2025?" Someone
   filters, sums, pastes into a deck. Right column? Right rows? Was the
   subtotal double-counted? Nobody can reproduce how the number was made.

> Optional real-world hooks (all public, well documented — verify the exact
> citation before using): JPMorgan's 2012 "London Whale" VaR spreadsheet
> (manual copy-paste in the model contributed to ~$6B in losses),
> Reinhart–Rogoff's Excel range error in a paper that shaped austerity
> policy, Public Health England losing ~16,000 COVID case records to an XLS
> row limit in 2020. Academic research on spreadsheet quality (R. Panko)
> consistently finds errors in a large share of operational spreadsheets —
> **[TO FILL: pick one citation and verify it]**.

---

## 3. Who it's for

**Beachhead: Bulgaria — people professionally responsible for other people's
numbers.**

| Segment | Their moment of pain |
|---|---|
| Счетоводни къщи (accounting firms) | Client sends a "fixed" workbook; what changed and is it safe to file? |
| Audit & consulting teams | Reviewing a client model under deadline; need findings with evidence, not vibes |
| CFO / FP&A teams | Board pack numbers come from a model 5 people edit |
| Valuation / M&A advisers | Someone else's model must be trusted enough to price a deal |
| Grant consultants | EU-funding budgets get re-edited endlessly and re-checked manually |

Why Bulgaria first: no local product does professional Excel-model auditing;
the tool already reads Bulgarian sheets, columns and questions natively
(Cyrillic, transliteration, BG vocabulary) — that's not a checkbox foreign
tools can add overnight.

> If asked "why not everyone with Excel": we sell to people whose *liability*
> is other people's spreadsheets. They feel the pain weekly and can justify
> paying.

---

## 4. What we have today

A **working product** (POC stage, local-first), not a slide-deck idea:

- **Audit** one workbook → risk report: hardcoded formula overrides, totals
  that miss rows, cent-level rounding drift in totals (the printed figures
  that don't add up — with the guilty cells named), broken references
  (`#REF!`), circular references (including self-including SUMs), hidden
  sheets/rows/columns, external file dependencies, volatile functions, error
  cells — 19 rules, each finding with location, evidence and a suggested
  action.
- **Compare** two versions → what changed (formulas, values, structure,
  formatting-only), unified into **review items** with one reconciled
  severity, plus the downstream blast radius of every change.
- **Schema** → what tables/columns a workbook actually contains (types,
  currencies, totals rows, missing values).
- **Ask** → constrained questions in **Bulgarian or English** ("Какъв е
  общият оборот за 2025?") answered deterministically, with the full
  calculation recipe attached — or a clarifying question when the workbook is
  ambiguous.

Interfaces: terminal CLI, HTML/JSON reports at shareable local URLs, REST
API, minimal web demo pages. 311 automated tests. Runs entirely on our
machine — **client files never leave it**.

---

## 5. How it works (30-second version)

```
 workbook.xlsx
      │
      ▼
 1. READ SAFELY      file is validated and parsed; macros are never executed
      │
      ▼
 2. UNDERSTAND       every cell, formula, hidden object and dependency is
      │              mapped into a typed model of the workbook
      ▼
 3. ANALYZE          deterministic rules + a dependency graph find risks and
      │              trace which outputs each problem reaches
      ▼
 4. REPORT           HTML + JSON with evidence, severity, and provenance —
                     the same input always produces byte-identical output
```

**No AI decides anything about your numbers.** Every number in every report
comes from rule-based, repeatable computation. (Where language models *could*
help later — phrasing questions — they are architecturally locked out of the
math. See slide 7.)

---

## 6. What makes it different — five trust guarantees

*(These are demoable live in ~60 seconds: `python scripts/demo_tour.py`)*

1. **Ambiguity is confirmed, never guessed.** Two columns named "Amount"?
   It asks which one — because the two answers were 1,900 vs 19,000.
2. **It filters correctly — or refuses.** "Rows over 500" applies the
   filter and shows it in the answer; "rows over budget" (no number) is
   *refused*, never silently answered.
3. **Nothing fails silently.** If an analysis rule crashes, the report says
   coverage was incomplete instead of quietly looking clean.
4. **Renames don't hide edits.** Rename a sheet *and* change an assumption —
   it detects the rename by content and still surfaces the edit, with its
   downstream impact through named ranges.
5. **Reports are evidence.** Byte-identical on re-run; every report carries a
   SHA-256 fingerprint proving *which* file it describes. Re-audit months
   later and diff the reports with zero noise.

---

## 7. Where AI fits (and where it never will)

```
your question ──► language layer ──► STRUCTURED QUERY ──► deterministic engine ──► number + provenance
                 (rule-based today,   (validated, typed)     (pandas / openpyxl,      (rows counted, blanks
                  LLM optional later)                         no AI involved)          excluded, filter shown)
```

- Today the language layer is a **rule-based parser** (EN + BG) — the product
  works with **no AI, no API keys, no data sent anywhere**.
- If we later plug in an LLM for more natural phrasing, it can only produce
  the structured query above. It **cannot** compute, pick between ambiguous
  columns, or invent values — the architecture forbids it, not a policy.

> This slide is the answer to "is this another ChatGPT wrapper?" — no:
> ChatGPT-style tools *generate* answers; we *compute* them and show the work.

---

## 8. The alternatives, honestly

| Alternative | Where it falls short |
|---|---|
| **Manual review / four-eyes** | Thorough reviewers exist — but re-checking a whole model on every version doesn't scale, and attention fades exactly when deadlines hit. How long it takes genuinely varies by model size — **we don't quote fake hour-savings; we'll measure real ones in pilots [TO FILL]**. |
| **Microsoft Spreadsheet Compare / Inquire** | Ships only with certain Office editions; raw cell-diff lists with no severity, no risk rules, no downstream impact, no Q&A, effectively unknown to most SMB accountants here. |
| **PerfectXL (NL) and similar** | Validates the category. English-only workflows, priced for enterprise, no Bulgarian language/локализация, no verified Q&A layer. |
| **Asking ChatGPT / Copilot** | Uploads client financials to a third party, and produces plausible answers with no provenance — the exact failure mode our clients are liable for. |
| **Do nothing** | The status quo: errors are found by the client, the auditor, or the tax authority — the three most expensive reviewers available. |

> Tone for this slide: respectful of manual review (our buyers ARE the manual
> reviewers — we make them faster and safer, we don't replace them).

---

## 9. Traction & numbers — [TO FILL — do not present without real data]

What we will measure with each pilot client and put here:

- **[TO FILL]** workbooks audited / compared per month
- **[TO FILL]** findings per workbook that the reviewer *confirmed as real*
  (our precision, honestly measured)
- **[TO FILL]** minutes from "workbook received" → "review-ready report",
  vs. the client's own baseline for the same model (measured, not estimated)
- **[TO FILL]** one concrete saved-error story per client, in their words
  ("caught a hardcoded override that would have misstated Q3 by X")
- **[TO FILL]** testimonial + logo permission

> Until this slide has data, we pitch the *demo*, not statistics. The
> demo is strong enough to carry the meeting.

---

## 10. Privacy & security (the accountant's first question)

- Runs **locally** — client workbooks never leave the machine; no cloud, no
  third-party AI services touching file contents.
- Macros are **never executed**; malicious/oversized files are rejected
  (zip-bomb and path-traversal defenses).
- Uploads are deleted immediately after processing; stored reports can be
  purged and purging **actually removes them everywhere** (verified by test).
- Reports don't log cell contents; HTML output is escaped against injection.
- Honest boundary: today's report links are unauthenticated local URLs — a
  hosted multi-client version needs accounts and access control (roadmap).

---

## 11. What it does NOT do (say this before they ask)

- Does **not** recalculate Excel — it trusts the values Excel last saved and
  analyzes structure; it will not "prove the model is mathematically right".
- Does **not** analyze VBA macro logic (their presence is flagged).
- Does **not** read `.xls` (legacy), password-protected files, Google Sheets.
- Does **not** answer open-ended questions ("is this business healthy?") —
  by design it refuses what it cannot verify.
- Row/column insertions show up as many small changes rather than one
  "row inserted" event (known limitation, on the roadmap).

> Leading with limits builds more trust with this audience than any feature
> list. Our reports print their own limitations on every page for the same
> reason.

---

## 12. Roadmap (near → far)

1. **Now:** pilot with 3–5 firms; measure the numbers for slide 9.
   Shipped since this deck was drafted: PDF export, row-insertion
   collapsing (one structural change instead of dozens of shifted-cell
   changes), exact Excel Table metadata, an MCP server, and Teams
   webhook cards (summary posts + `status <id>` queries).
2. **Next:** reports in Bulgarian, hosted version with accounts for
   multi-client firms.
3. **Later:** full Microsoft Teams/Slack delivery ("drop a workbook in the
   channel, get the report" — needs a registered Azure bot; webhooks can't
   receive files), scheduled re-audits, per-client column mappings that
   remember each client's terminology.

---

## 13. Business model — [TO FILL — decide before first pricing conversation]

Options on the table (pick after pilot feedback):

- Per-seat monthly for firms (reviewer licenses)
- Per-workbook / per-report credits for occasional users
- Pilot structure: **free or symbolic for 4–6 weeks in exchange for
  measurable before/after data and a case study** ← recommended opener

---

## 14. The ask

For the businesses in the room:

1. **One pilot.** Give us your messiest real model (under NDA, processed
   locally) and one hour of a reviewer's time.
2. We run audit + compare + ask on it **in front of you**.
3. You tell us which findings were real and what the report must look like
   for you to pay for it.

Contact: **[TO FILL: name, phone, email]**

---

## 15. FAQ — the questions that will come up (and our answers)

> Use this as Q&A prep and/or a leave-behind page. Answers are written to be
> spoken aloud: short, plain, honest. Don't over-answer — stop when the
> question is answered.

### How it answers

**Q: How does it know which column I'm asking about?**
Three steps. First it reads the workbook's structure — which tables exist,
which columns hold dates, money, text. Then it matches your words against a
bilingual vocabulary: "оборот", "turnover", "revenue", even "oborot" in Latin
letters all map to the same concept. And the crucial part: if more than one
column plausibly matches — say the sheet has both *Оборот* and *Нетен
оборот* — **it stops and asks you which one**, instead of guessing. Silent
guessing is exactly the failure we built this against.

**Q: What if there are two columns with the same name?**
It notices, tells you "Amount (column B)" vs "Amount (column C)", and asks.
In our demo workbook those two columns sum to 1,900 vs 19,000 — a tool that
guessed would be 10× wrong while looking confident.

**Q: What happens when it can't answer?**
It says so — the answer status is literally "cannot answer safely", with the
reason. It refuses open-ended questions ("is this business healthy?"),
questions about data it can't find, and questions where a filter can't be
built precisely. A refusal is a feature: it's what makes the answers it
*does* give worth trusting.

**Q: Does it understand Bulgarian?**
Yes — Cyrillic sheet names, Bulgarian column headers, transliterated Latin
headers, and questions asked in Bulgarian. That's native behavior, tested,
not a translation layer.

**Q: My invoice total is off by one stotinka — can it find why?**
Yes, that exact case. Excel stores more precision than it displays, so the
printed line items can add to 4,456.00 while the total prints 4,456.01. The
audit computes both displayed sums, reports the drift, and names the cells
carrying the hidden sub-cent precision — instead of you re-adding the column
by hand.

### Trust & accuracy

**Q: How confident are you that this doesn't produce nonsense answers?**
Because it doesn't *generate* answers — it *computes* them. There's no AI in
the calculation path: your question becomes a structured query, and the
number comes from deterministic arithmetic over the actual cells. Every
answer ships with its recipe — which sheet, which column, which rows were
included, which were excluded and why. You can check any answer by hand in a
minute. And when it isn't sure, it asks or refuses; it never bluffs.

**Q: So it's never wrong?**
It can be — in two honest ways. The *audit* findings are risk flags, not
verdicts: a flagged cell can turn out intentional, which is why every finding
carries a separate confidence level and a suggested action, and a human
reviewer stays in charge. And the *answers* are computed from the values
Excel last saved — if the workbook itself was saved mid-edit with stale
values, the tool reports what's in the file. What it will not do is invent
data or silently pick between ambiguous options.

**Q: Is this ChatGPT under the hood?**
No. Today there is **no AI model in the product at all** — the language
understanding is rule-based, and everything after it is ordinary computation.
If we later add an LLM to understand more phrasings, the architecture only
lets it translate wording into a structured query — it can never touch the
math, choose columns, or see results before they're computed.

**Q: Two people ask the same question — do they get the same answer?**
Yes, byte-for-byte. Same file + same question ⇒ identical output, today or in
six months. Reports carry a cryptographic fingerprint of the exact file they
describe, so there's never a "which version was this run on?" argument.

**Q: Why should we trust a product this young?**
Don't trust it — test it. That's the pilot: your real workbook, our tool, in
front of you, and you judge every finding. The engineering behind that offer:
311 automated tests, a third-party-style audit of the codebase with every
confirmed finding fixed (paper trail included), and reports designed as
evidence — deterministic, fingerprinted, with limitations printed on every
page.

### Security & data

**Q: Where does our data go?**
Nowhere. Processing is local — the workbook is analyzed on the machine the
tool runs on, no cloud service, no external AI, no telemetry. Nothing about
your files is used to "train" anything. It even runs with the network cable
unplugged.

**Q: Where will the service live?**
Today: on your hardware — a laptop or an office server, installed via Docker
or plain Python; for pilots we can bring it and run it in your office. A
hosted version (so your team just opens a browser) is on the roadmap and will
live on EU infrastructure with proper accounts and access control — we won't
host client financials before that layer exists.

**Q: How is it secure?**
Files are validated before parsing (malformed/oversized/zip-bomb files are
rejected), macros are never executed, uploads are deleted immediately after
processing, and deleting a stored report actually removes it everywhere —
that's verified by automated tests, not by promise. Today's report links are
local URLs meant for one machine; multi-user access control comes with the
hosted version, and we'll say that plainly rather than pretend.

**Q: What about GDPR?**
The strongest answer available: your data never leaves your control, because
processing is local and there are no third-party processors involved. You
remain the data controller with nothing new to disclose. When the hosted
version arrives, it ships with the formal paperwork (DPA, retention policy);
until then there's simply no data transfer to regulate.

### Practical

**Q: Does it change our files?**
Never. It's strictly read-only — it produces reports *about* the workbook and
never writes into it. It also never "auto-fixes" anything: it flags, you
decide.

**Q: What files does it support?**
Modern Excel: `.xlsx` and `.xlsm` (macros flagged, not executed). Not yet:
old `.xls`, password-protected files, Google Sheets. Size limits are
configurable; typical financial models are well within them.

**Q: Our spreadsheets are… not tidy. Will it cope?**
That's the test we want. It's built for real-world mess — Cyrillic names,
merged headers, spacer rows, multiple tables per sheet, subtotal rows (which
it excludes from sums so nothing is double-counted). When a sheet is too
unstructured to read reliably, it says so instead of producing a shaky
answer — and the `schema` report shows you exactly what it did and didn't
recognize.

**Q: What do we need to install? What does our IT need to approve?**
One machine with Docker (or Python 3.12) — no internet access required, no
accounts, no data leaves the building. IT reviews a local, open-inspectable
install rather than a cloud vendor.

**Q: Does it integrate with what we use?**
Today: a command-line tool, shareable HTML/JSON reports (plus PDF for
filing/emailing), a REST API your systems can call, an MCP server so
AI assistants and MCP-capable tools can run audits and ask questions
directly, and Microsoft Teams webhooks — audit summaries posted as cards
into a channel, and a `status <report id>` command answered from the
channel. Honest caveat: Teams webhooks cannot receive file attachments, so
"drop a workbook in the channel, get the report" needs a registered Azure
bot — that and Slack delivery are roadmap, not shipped. The JSON reports
are versioned so integrations don't break silently.

### Commercial

**Q: What does it cost?**
Honest answer: pricing is decided after pilots. The pilot itself is free or
symbolic in exchange for measurable before/after data and a case study. You
get value either way; we get the numbers for slide 9.

**Q: Who else is using it?**
You'd be among the first — that's leverage, not a weakness: pilot clients get
direct influence over what the reports look like and founder-level support.
**[TO FILL: replace this answer the moment the first pilot converts.]**

---
---

# Appendix A — What is actually happening under the hood

*(Internal — the honest technical explanation, written to be readable. File
paths refer to `src/excel_auditor/`.)*

## A1. The audit pipeline, step by step

**Step 1 — Safe loading** (`parsing/workbook_loader.py`)
An `.xlsx` file is really a ZIP of XML files. Before parsing we check: is it
actually a zip, does it decompress to a sane size (zip-bomb defense), do the
entry paths stay inside the archive (traversal defense), does it contain
macros (`vbaProject.bin` — we *flag* macros, never run them). Then the file
is opened twice with `openpyxl`: once for formulas + formatting, once for the
values Excel last calculated.

**Step 2 — Inventory** (`analysis/workbook_inventory.py`)
Everything gets converted into our own typed data model: every populated cell
(value, formula, format), every sheet's visibility, hidden rows/columns,
merged ranges, named ranges, external links. From here on we never touch
openpyxl again — all analysis works on this model. The workbook also gets a
**SHA-256 fingerprint** (a cryptographic hash of the file's bytes) used as
its ID — same file ⇒ same ID, any change ⇒ different ID.

**Step 3 — Formula normalization** (`parsing/formula_normalizer.py`)
The key trick that makes everything else work. `=B2*C2` in row 2 and
`=B3*C3` in row 3 are *textually* different but *structurally* identical —
both mean "two cells to my left, times one cell to my left". We rewrite every
formula into that relative form (`RC[-2]*RC[-1]`). Now:
- copied formulas compare as **equal** → no noise in diffs;
- a cell that *breaks* the pattern sticks out → real signal.
That's exactly how the engine catches "D7 was overwritten with 2600": D2–D13
all normalize to the same pattern, D7 suddenly doesn't.

**Step 4 — Rules** (`analysis/rules/`, 16 files)
Each rule is a small, independent check over the inventory: hidden sheets
with data, `#REF!` anywhere, volatile functions like `TODAY()`, hardcoded
numbers inside formulas, totals whose range stops just short of a populated
cell, etc. Every finding carries: a stable rule ID (e.g. `EA-PAT-001`),
**severity** (how bad if true) and — separately — **confidence** (how sure we
are it's really a problem), the exact cell, the evidence, and a suggested
action. If a rule ever crashes, the report *says so* (`failed_rules`) instead
of pretending coverage was complete.

**Step 5 — Dependency graph** (`analysis/dependency_graph.py`)
We read every formula's references and build a directed graph: an arrow from
each referenced cell to the formula that uses it — including through named
ranges (`GrowthRate`) and table references. "Downstream impact" is just
following the arrows: change `Assumptions!B3` and the graph tells you it
reaches 8 cells across P&L and Summary. Cycles in the graph = circular
references, including the sneaky self-including SUM (`D11 = SUM(D1:D11)`).

**Step 6 — Review items & risk level** (`analysis/review.py`,
`analysis/severity.py`)
When comparing versions, one underlying problem used to show up twice (as a
"cell change" and as an "audit finding") with different severities. Review
items merge them: one item per problem, worst severity wins, written back
everywhere so the JSON, HTML and CLI can never disagree. The overall risk
level is deliberately dumb-and-transparent: **the highest severity present**
("HIGH — because 5 high-severity items"), never an opaque "score 71/100".

**Step 7 — Reports** (`reporting/`)
The same analysis result renders to JSON (for machines) and HTML (for
humans), both carrying the fingerprint, the schema version (`"2"`), findings,
provenance and a printed list of the tool's own limitations. Reports are
**byte-identical across re-runs** — diff two report files and any difference
is a real difference in the workbook, not randomness in our tool.

## A2. The "ask" pipeline (how a question becomes a number)

Question: *"Какъв е общият оборот за 2025?"*

1. **Schema detection** (`analysis/schema.py`) — find the tables: contiguous
   blocks with a header row; infer each column's type from its values and
   number formats (dates, currency-with-`€`/`лв`, booleans, categories);
   detect "Общо" rows so totals are never double-counted.
2. **Intent parsing** (`llm/rule_parser.py`) — keyword rules (not AI) turn
   the wording into a validated, typed query object:
   ```json
   {"operation": "aggregate", "function": "sum",
    "requested_metric": "revenue",
    "filters": [{"column": "__date__", "operator": "year_equals", "value": 2025}]}
   ```
   Unsupported questions ("find fraud") are rejected right here.
3. **Column resolution** (`analysis/resolution.py`) — "оборот" is matched
   against a bilingual vocabulary (revenue = revenue/turnover/оборот/oborot…).
   Crucially, if the sheet has both **Оборот** and **Нетен оборот**, both
   match the concept — so the tool *stops and asks you* instead of picking.
   Same for duplicate column names (matched by physical position, not name).
4. **Deterministic execution** (`analysis/query.py`) — the chosen column and
   filters run through pandas: filter to year 2025, drop the 2 blank cells,
   skip the subtotal row, sum. Pure arithmetic, reproducible forever.
5. **Provenance** — the answer ships with its recipe: workbook, sheet, table
   range, chosen column, filter, rows included/excluded and why, currency,
   every assumption made. That block is what makes the number *defensible*.

## A3. Five terms that appear everywhere

| Term | Plain meaning |
|---|---|
| **Deterministic** | Same input ⇒ exactly the same output, every time. No randomness, no AI judgment calls. This is what makes reports usable as evidence. |
| **Provenance** | The attached "how this number was made" recipe — enough to reproduce it by hand. |
| **Severity vs confidence** | Severity = how much damage if real. Confidence = how sure the detector is. A hidden sheet: low severity, high confidence. A total possibly missing a row: high severity, medium confidence. |
| **Review item** | One reviewable problem, after merging the raw change and any findings at the same cell under a single severity. |
| **Schema v2** | The version stamp inside every report JSON, so client integrations know which field layout they're reading. |

## A4. Where the code lives (if you want to read one file per concept)

- Catching overwritten formulas → `analysis/pattern_detection.py`
- Version diff → `analysis/workbook_diff.py`
- Blast radius / circular refs → `analysis/dependency_graph.py`
- The 16 audit rules → `analysis/rules/`
- Table & type detection → `analysis/schema.py`
- BG/EN column matching → `analysis/resolution.py`
- The actual math for "ask" → `analysis/query.py`
- Question wording → structured query → `llm/rule_parser.py`
- Orchestration → `services.py` (audit/compare), `query_service.py` (ask)

---

# Appendix B — Pitch-structure checklist (why the deck looks like this)

Standard pitch decks (YC/Sequoia-style) contain: problem, solution, product
demo, market/audience, competition, "why now", traction, business model,
team, ask. Mapping to ours:

| Standard element | Our slide | Note |
|---|---|---|
| Problem | 2 | ✔ |
| Solution / product | 4–6 | ✔ demo-led |
| Why now / differentiation | 6–7 | trust guarantees + AI positioning |
| Market / audience | 3 | Bulgaria beachhead; **no invented TAM numbers** |
| Competition | 8 | honest, includes "do nothing" |
| Traction | 9 | placeholders only — *never* fake this slide |
| Business model | 13 | TBD until pilot feedback |
| Team | — | add when pitching investors; customers care less |
| Ask | 14 | customer version = pilot, not money |
| Q&A prep / objection handling | 15 | doubles as a leave-behind FAQ page |

This is a **customer pitch** (goal: pilots), not an investor pitch. For an
investor version later, add: team slide, market sizing with real sources,
pricing, and the traction numbers from slide 9.
