# Next Implementation Task: CLI, Thin API, and Deterministic Spreadsheet Queries

Continue from the current Excel auditor POC.

The existing system already supports:

* auditing one workbook;
* comparing two workbook versions;
* detecting formula risks;
* identifying hardcoded formula replacements;
* finding hidden content and external references;
* tracing basic downstream impact;
* generating JSON and HTML reports.

The next milestone is to turn the existing analysis engine into a usable terminal-first product with a thin API and a constrained spreadsheet question workflow.

Do not build a frontend-heavy application.

The primary interfaces for this milestone are:

1. terminal CLI;
2. generated HTML reports;
3. minimal FastAPI endpoints;
4. an optional basic server-rendered upload page.

The core analysis logic must remain independent of the CLI, API and future chatbot integrations.

---

# Product architecture

Organize the product into three clear layers.

## 1. Analysis engine

This layer performs all deterministic spreadsheet work.

Core public functions should resemble:

```python
audit_workbook()
compare_workbooks()
trace_dependencies()
inspect_workbook()
resolve_table()
resolve_columns()
query_table()
```

The analysis engine must not depend on FastAPI, terminal input, HTML templates or LLM provider SDKs.

## 2. Report layer

This layer converts structured results into:

* JSON;
* human-readable HTML;
* temporary or persistent report URLs;
* eventually PDF, but PDF is not required in this milestone.

## 3. Interfaces

Interfaces should only translate user requests into calls to the core engine.

Initial interfaces:

* CLI;
* thin FastAPI service;
* minimal upload webpage.

Future interfaces:

* Microsoft Teams;
* Slack;
* scheduled jobs;
* external API clients.

Do not duplicate spreadsheet analysis logic inside any interface.

---

# CLI requirements

Implement or improve the following commands:

```bash
excel-auditor audit model.xlsx
excel-auditor compare old.xlsx new.xlsx
excel-auditor schema model.xlsx
excel-auditor ask model.xlsx "What was total revenue in 2025?"
excel-auditor serve
```

Each analysis command should:

1. validate the input file;
2. process the workbook;
3. save structured JSON;
4. generate a clean HTML report;
5. print a concise terminal summary;
6. print the report path or URL;
7. optionally open the HTML report in the default browser.

Add CLI flags such as:

```bash
--output-dir
--json-output
--html-output
--open
--no-open
--hosted
--verbose
```

Reasonable defaults are acceptable.

---

# CLI workflow A: audit

Command:

```bash
excel-auditor audit financial_model.xlsx
```

The command should return:

* formula risks;
* hidden sheets, rows and columns;
* external workbook references;
* broken references;
* suspicious totals and ranges;
* formula-pattern inconsistencies;
* formulas replaced by constants;
* volatile formulas;
* dependency impact;
* clean HTML report;
* structured JSON report.

Example terminal output:

```text
Workbook audit complete.

Review priority: High

4 high-priority findings
1 broken reference
1 formula-pattern inconsistency
1 formula overwritten by a constant
1 suspicious total range

Report:
http://localhost:8000/reports/7f93a2
```

Avoid printing all findings directly in the terminal.

---

# CLI workflow B: compare

Command:

```bash
excel-auditor compare financial_model_v1.xlsx financial_model_v2.xlsx
```

The command should return:

* structural changes;
* added and removed worksheets;
* formula changes;
* formulas replaced by constants;
* constant-value changes;
* formatting-only changes;
* hidden-content changes;
* external-reference changes;
* downstream impact;
* high-priority review items;
* clean HTML report;
* structured JSON report.

Example terminal output:

```text
Comparison complete.

4 high-priority review items
1 formula replaced by a constant
1 broken reference
2 changes affecting summary outputs

Report:
http://localhost:8000/reports/7f93a2
```

The report should reconcile raw workbook changes with audit findings.

For example, a newly added formula containing `#REF!` must inherit the high severity of the broken-reference finding rather than remain a low-severity formula addition.

---

# CLI workflow C: inspect schema

Command:

```bash
excel-auditor schema sales.xlsx
```

The schema inspection should identify:

* worksheet names;
* likely tables;
* probable header rows;
* column names;
* normalized column names;
* inferred column types;
* date columns;
* numeric columns;
* percentage columns;
* currency formatting;
* likely identifier columns;
* likely subtotal and total rows;
* missing-value counts;
* sample values;
* merged or multi-row headers;
* hidden sheets, rows and columns.

Example output:

```text
Workbook schema detected.

Sheet: Sales
Table: A3:F387
Rows: 384

Columns:
- Дата: date
- Клиент: text
- Оборот: currency
- Нетен оборот: currency
- Регион: categorical
- Платено: boolean

Schema report:
http://localhost:8000/reports/4aa981
```

The full schema should also be available as JSON.

---

# Deterministic query engine

Do not create a separate implementation for every user-facing question.

The user-facing capabilities may include:

```python
list_sheets()
inspect_schema()
find_columns()
filter_rows()
aggregate()
group_by()
compare_periods()
find_minimum()
find_maximum()
calculate_sum()
calculate_average()
find_deadlines()
compare_workbooks()
audit_formulas()
trace_dependencies()
```

Internally, collapse them into a smaller set of reusable primitives:

```python
inspect_workbook()
resolve_table()
resolve_columns()
query_table()
compare_workbooks()
audit_workbook()
trace_dependencies()
```

The main general-purpose function should be:

```python
query_table()
```

It should accept a validated structured query.

Example:

```json
{
  "operation": "aggregate",
  "function": "sum",
  "sheet": "Sales",
  "table": "A3:F387",
  "value_column": "Оборот",
  "filters": [
    {
      "column": "Дата",
      "operator": "year_equals",
      "value": 2025
    }
  ],
  "group_by": []
}
```

This single engine should support:

* sum;
* count;
* distinct count;
* average;
* minimum;
* maximum;
* median;
* filtering;
* grouped aggregation;
* percentage change;
* period comparison;
* date and deadline lookup.

Use DuckDB, Polars or pandas for deterministic execution.

Do not allow an LLM to calculate numerical answers.

---

# CLI workflow D: constrained question

Command:

```bash
excel-auditor ask sales.xlsx "What was total revenue in 2025?"
```

Required flow:

```text
User question
    ↓
Intent and operation extraction
    ↓
Workbook schema inspection
    ↓
Candidate table and column resolution
    ↓
Ambiguity validation
    ↓
User confirmation when required
    ↓
Deterministic Python/DuckDB execution
    ↓
Result with full provenance
    ↓
HTML and JSON report
```

The LLM, if used, may only:

* interpret the user’s wording;
* map the request to a supported structured operation;
* rank possible column and table candidates;
* phrase the final deterministic result.

The LLM must not:

* perform arithmetic;
* silently choose ambiguous columns;
* invent missing values;
* answer unsupported questions;
* return a number without provenance.

---

# Column resolution

The system must not assume exact English column names.

For example, the concept `revenue` may appear as:

```text
Revenue
Rev
Sales
Turnover
Оборот
Нетен оборот
Приходи
Oborot
```

Use the following resolution hierarchy:

```text
Approved client mapping
        ↓
Exact normalized name match
        ↓
Known multilingual aliases
        ↓
Schema and datatype compatibility
        ↓
LLM candidate ranking
        ↓
User confirmation
```

Normalize column names by:

* lowercasing;
* trimming whitespace;
* removing punctuation;
* collapsing repeated spaces;
* handling Bulgarian and Latin transliteration;
* expanding known abbreviations where safe.

Create a basic canonical vocabulary.

Example:

```yaml
revenue:
  aliases:
    - revenue
    - rev
    - turnover
    - sales
    - оборот
    - oborot
    - приходи

net_revenue:
  aliases:
    - net revenue
    - net sales
    - нетен оборот
    - чисти приходи

date:
  aliases:
    - date
    - дата
    - invoice date
    - transaction date
    - period
```

Do not treat aliases as proof of equivalence when multiple plausible columns exist.

---

# Ambiguity handling

Ask the user for confirmation when:

* multiple plausible value columns exist;
* both actual and forecast values exist;
* both gross and net values exist;
* multiple date fields exist;
* multiple sheets contain matching columns;
* currencies differ;
* several candidate tables exist;
* subtotal rows may cause double counting;
* merged headers are ambiguous;
* the system cannot safely identify the intended data.

Example terminal interaction:

```text
I found two possible revenue fields:

1. Sales → Оборот
2. Sales → Нетен оборот

Select [1/2]:
```

After selection, execute the deterministic query.

Do not use fake numerical confidence percentages.

Use statuses such as:

* verified;
* review recommended;
* cannot answer safely.

---

# Query result provenance

Every numerical result must include:

* workbook filename;
* sheet name;
* table or cell range;
* selected value column;
* selected date column;
* operation;
* filters;
* grouping;
* rows included;
* rows excluded;
* missing values;
* currency or unit;
* assumptions;
* warnings.

Example terminal output:

```text
Total revenue for 2025: €628,400

Status: Verified

Calculated using:
- Workbook: sales.xlsx
- Sheet: Sales
- Table: A3:F387
- Value column: Оборот
- Date column: Дата
- Operation: SUM
- Filter: year(Дата) = 2025
- Rows included: 384
- Blank values excluded: 2
- Currency: EUR

Report:
http://localhost:8000/reports/71bd90
```

The same calculation parameters must be stored in JSON so the result can be reproduced.

---

# Supported question types

For this milestone, support only questions that can be mapped to the following deterministic operations.

## Workbook inspection

Examples:

```text
What sheets are in this workbook?
Which sheets are hidden?
What columns are available?
Which columns contain dates?
Which sheets contain formulas?
```

## Aggregations

Examples:

```text
What was total revenue in 2025?
What is the average invoice value?
How many unique customers are there?
What is the minimum monthly margin?
What is the maximum expense?
```

## Filtering

Examples:

```text
How many invoices are overdue?
Show rows where revenue exceeds €10,000.
How many contracts expire before December 31, 2026?
```

## Grouping

Examples:

```text
Show revenue by month.
Show sales by region.
What is the average margin by product?
```

## Period comparison

Examples:

```text
Compare revenue in 2024 and 2025.
How much did expenses increase year over year?
Which month had the largest decline?
```

## Deadline lookup

Examples:

```text
What is the next contract deadline?
Which invoices are due this week?
How many contracts expire within 30 days?
```

## Workbook analysis

Examples:

```text
Audit this workbook.
Compare these two workbook versions.
Which changes affect the Summary sheet?
Trace dependencies from Revenue Forecast!D7.
```

Unsupported or open-ended requests should return a clear limitation.

Examples to reject initially:

```text
Tell me everything interesting about this company.
Explain why the business is failing.
Forecast the next five years.
Find fraud.
Decide whether this investment is good.
```

---

# Structured intent model

Create a strict typed model for parsed user intent.

Example:

```python
class SpreadsheetQuery(BaseModel):
    action: QueryAction
    operation: QueryOperation | None
    function: AggregateFunction | None
    requested_metric: str | None
    requested_dimensions: list[str]
    filters: list[QueryFilter]
    group_by: list[str]
    period_comparison: PeriodComparison | None
    source_sheet_hint: str | None
    requires_confirmation: bool = False
```

Suggested actions:

```python
class QueryAction(str, Enum):
    INSPECT_WORKBOOK = "inspect_workbook"
    QUERY_TABLE = "query_table"
    AUDIT_WORKBOOK = "audit_workbook"
    COMPARE_WORKBOOKS = "compare_workbooks"
    TRACE_DEPENDENCIES = "trace_dependencies"
```

Suggested aggregate functions:

```python
class AggregateFunction(str, Enum):
    SUM = "sum"
    COUNT = "count"
    DISTINCT_COUNT = "distinct_count"
    AVERAGE = "average"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    MEDIAN = "median"
```

Reject any parsed request that does not validate against the expected schema.

---

# Thin FastAPI service

Add a minimal FastAPI server.

Required endpoints:

```text
POST /api/v1/audits
POST /api/v1/comparisons
POST /api/v1/schema
POST /api/v1/queries
GET  /api/v1/jobs/{job_id}
GET  /reports/{report_id}
GET  /health
```

The API should call the same application services as the CLI.

Do not reimplement logic in route handlers.

Suggested request flow:

```text
Route
  ↓
Validate input
  ↓
Call application service
  ↓
Store JSON result
  ↓
Generate HTML report
  ↓
Return job/result metadata
```

Synchronous processing is acceptable for small POC files.

Keep interfaces ready for future background-job support.

---

# Minimal website

Do not build React or a dashboard.

Use server-rendered HTML.

The initial website may contain only:

```text
Audit one workbook
Compare two workbook versions
Ask a verified question
Open an existing report
```

Suggested pages:

```text
GET /
GET /audit
GET /compare
GET /ask
GET /reports/{report_id}
```

The forms should call the same API or application services.

The website exists only to make demonstrations easier.

Do not add:

* billing;
* user accounts;
* organization settings;
* dashboards;
* elaborate navigation;
* frontend state management;
* analytics;
* notifications.

---

# Report storage and URLs

Create a report store abstraction.

For local development, store reports under something like:

```text
artifacts/
├── reports/
│   ├── 7f93a2.html
│   └── 7f93a2.json
└── uploads/
```

A generated report should be accessible through:

```text
http://localhost:8000/reports/7f93a2
```

Report identifiers should be random and unguessable enough for local POC usage.

Document that production deployments will require authentication and stronger access controls.

---

# Report improvements

Before expanding functionality, fix the current report weaknesses.

## Reconcile severity

Final issue severity should combine:

* raw change type;
* audit findings at the same location;
* formula-pattern inconsistency;
* downstream impact;
* output-sheet impact;
* external-reference risk.

Example:

```text
formula_added + contains #REF!
```

must become a high-priority issue.

## Unify duplicate findings

Do not show the same underlying issue as several disconnected items.

Create a unified review item.

Example:

```text
Revenue Forecast!D7

Change:
Formula replaced by constant

Audit finding:
Breaks surrounding copied-formula pattern

Impact:
19 downstream cells across 4 worksheets

Severity:
High

Confidence:
High
```

## Group repeated low-value findings

Instead of twelve separate hardcoded-literal findings, show:

```text
The literal 0.9 appears in 12 formulas across Cash Flow!B2:B13.
```

## Fix external-link counts

Distinguish:

* registered workbook external links;
* formula-level external workbook references.

Do not show `0 external links` while also reporting an external reference.

## Replace opaque risk scores

Prefer:

```text
Review priority: High
```

with explicit drivers.

If a numeric score remains, document its calculation in the report.

---

# Suggested project structure

Adjust the repository toward a structure similar to:

```text
src/excel_auditor/
├── analysis/
│   ├── audit.py
│   ├── compare.py
│   ├── dependency.py
│   ├── schema.py
│   ├── query.py
│   └── resolution.py
├── application/
│   ├── audit_service.py
│   ├── comparison_service.py
│   ├── schema_service.py
│   ├── query_service.py
│   └── report_service.py
├── models/
│   ├── audit.py
│   ├── comparison.py
│   ├── query.py
│   ├── schema.py
│   └── report.py
├── reporting/
│   ├── html.py
│   ├── json.py
│   └── templates/
├── llm/
│   ├── interface.py
│   ├── intent_parser.py
│   └── mock_parser.py
├── cli/
│   ├── app.py
│   └── commands/
├── api/
│   ├── app.py
│   ├── routes/
│   └── schemas/
├── web/
│   ├── routes.py
│   └── templates/
└── storage/
    ├── reports.py
    └── uploads.py
```

The LLM layer must be replaceable and optional.

Provide a deterministic or mocked intent parser for tests.

---

# LLM interface

Create an abstraction such as:

```python
class IntentParser(Protocol):
    def parse(
        self,
        question: str,
        schema: WorkbookSchema,
    ) -> SpreadsheetQuery:
        ...
```

Do not couple core application code to one model provider.

The parser should receive only the information required for intent resolution:

* sheet names;
* table names;
* column names;
* inferred types;
* small sanitized value samples where necessary.

Do not send entire raw workbooks to an LLM.

For the POC, it is acceptable to support:

* one real provider behind configuration;
* one rule-based parser;
* one mock parser for tests.

---

# Testing requirements

Add tests for:

* schema detection;
* Bulgarian and English column aliases;
* ambiguous column resolution;
* exact-match resolution;
* type-compatible resolution;
* rejection of unsafe ambiguity;
* sum queries;
* average queries;
* min/max queries;
* grouping;
* period filtering;
* date parsing;
* deadline lookup;
* missing-value handling;
* subtotal exclusion;
* provenance generation;
* JSON serialization;
* CLI commands;
* API endpoints;
* report generation;
* formula audit and comparison regressions.

Generate realistic fixtures with:

* English headers;
* Bulgarian headers;
* transliterated headers;
* both gross and net revenue;
* forecast and actual columns;
* multiple date fields;
* subtotals;
* blank rows;
* merged headers;
* hidden sheets;
* multiple tables on one sheet.

---

# First implementation slice

Implement the milestone incrementally.

## Step 1

Refactor the existing audit and comparison execution into application services that are independent of the CLI and API.

## Step 2

Improve CLI output and report URL generation for:

```bash
excel-auditor audit
excel-auditor compare
```

## Step 3

Implement:

```bash
excel-auditor schema workbook.xlsx
```

with HTML and JSON output.

## Step 4

Implement deterministic structured queries directly, without free-text parsing.

Example:

```bash
excel-auditor query sales.xlsx \
  --sheet Sales \
  --function sum \
  --value-column Оборот \
  --filter-column Дата \
  --filter-op year_equals \
  --filter-value 2025
```

## Step 5

Add:

```bash
excel-auditor ask sales.xlsx "What was total revenue in 2025?"
```

The free-text command should resolve into the same validated structured query used in Step 4.

## Step 6

Add ambiguity confirmation in the terminal.

## Step 7

Add provenance-rich HTML and JSON query reports.

## Step 8

Add the thin FastAPI endpoints.

## Step 9

Add the minimal server-rendered upload and query pages.

Do not begin Teams integration in this milestone.

---

# Acceptance criteria

The milestone is complete when all of the following work.

## Audit

```bash
excel-auditor audit financial_model_v2.xlsx
```

Produces:

* correct terminal summary;
* JSON report;
* HTML report;
* accessible report URL.

## Compare

```bash
excel-auditor compare financial_model_v1.xlsx financial_model_v2.xlsx
```

Produces:

* unified high-priority review items;
* reconciled severity;
* formula diffs;
* dependency impact;
* JSON report;
* HTML report;
* accessible report URL.

## Schema

```bash
excel-auditor schema sales_bg.xlsx
```

Correctly detects:

* `Дата` as a date field;
* `Оборот` and `Нетен оборот` as numeric currency fields;
* candidate tables and ranges.

## Structured query

```bash
excel-auditor query sales_bg.xlsx \
  --function sum \
  --value-column Оборот \
  --filter-column Дата \
  --filter-op year_equals \
  --filter-value 2025
```

Returns a deterministic result with provenance.

## Free-text query

```bash
excel-auditor ask sales_bg.xlsx "Какъв е общият оборот за 2025?"
```

Maps to the same deterministic query.

If both `Оборот` and `Нетен оборот` exist, it must ask for confirmation.

## API

The API supports audit, compare, schema and query workflows without duplicating business logic.

## Web

The minimal webpage allows:

* one-workbook audit;
* two-workbook comparison;
* constrained question submission;
* opening generated reports.

---

# Non-goals

Do not implement yet:

* Microsoft Teams integration;
* Slack integration;
* Viber integration;
* user accounts;
* organizations;
* billing;
* subscriptions;
* enterprise permissions;
* long-term workbook history;
* semantic mappings saved per client;
* scheduled reports;
* unrestricted spreadsheet chat;
* advanced forecasting;
* fraud detection;
* generic AI insights;
* polished frontend design;
* React or Next.js;
* microservices;
* Kubernetes;
* production compliance claims.

---

# Final engineering rule

All workflows must follow this structure:

```text
User instruction
        ↓
Validated structured request
        ↓
Deterministic spreadsheet engine
        ↓
Structured result with provenance
        ↓
HTML/JSON report
        ↓
Optional natural-language wording
```

Never use:

```text
Raw workbook
        ↓
LLM guesses the answer
        ↓
Unverified numerical response
```

The spreadsheet engine is the source of truth.

The LLM is only an instruction parser and wording layer.

Begin by inspecting the current repository and identifying which existing audit and comparison components can be preserved without modification.
