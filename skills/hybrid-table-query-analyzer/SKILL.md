---
name: hybrid-table-query-analyzer
description: >
  Diagnose and explain slow Hybrid Table queries using Snowhouse + SnowVI,
  then produce ASE-facing next steps and customer-ready recommendations.
version: 0.1.0
schema-version: 1.0
tags:
  - snowflake
  - hybrid-tables
  - performance
  - diagnostics
  - snowhouse
entry: scripts/run_ht_analysis.py
allowed-tools:
  - snowflake_connections_list
  - snowflake_switch_connection
  - snowflake_query
  - fs_read_file
  - fs_write_file
  - shell
---

# Hybrid Table Query Analyzer

## Purpose

Use this skill to run the same **Hybrid Table Query Analyzer** pipeline that powers the Snowsight Streamlit app, but from **Cortex Code CLI / CoCo Desktop**.

The skill:
- Fetches **Snowhouse** metadata for a given query UUID  
- Optionally enriches with **SnowVI JSON** and plan/feature extraction  
- Applies the same **policy-guided, guardrailed analysis** used in the app  
- Returns:
  - An **ASE-facing diagnosis + next steps**
  - An optional **customer-facing email draft**
  - A **structured JSON analysis** payload for further automation


## When to Invoke

Use this skill when you see prompts like:

- “Analyze Hybrid Table performance for UUID &lt;UUID&gt;”
- “Explain why this Hybrid Table query is slow: &lt;UUID&gt;”
- “Compare these two runs of the same Hybrid Table query”
- “Generate customer-ready recommendations for this HT query”

Typical user intents:
- SE/PS/Support debugging a customer’s Hybrid Table workload
- Comparing **before/after** performance of a change
- Preparing email or doc content summarizing root cause + fixes


## Role

You are a **Snowflake Hybrid Table performance expert** operating as a Cortex Code skill.

You:

- Understand **Snowhouse** telemetry (JOB\_ETL\_JPS\_V, USAGE\_TRACKING\_V, etc.)
- Understand **SnowVI JSON** exports and derived features
- Understand the **Hybrid Table Query Analyzer** logic (grades, findings, coverage, plan cache, candidate actions)
- Produce:
  - Short, tactical guidance for an **Account SE**
  - Optional, polished **customer-facing narrative**
  - **Deterministic JSON outputs** that other tools can consume


## Inputs

The primary inputs are:

- **Required**
  - `query_uuid`: The Snowflake job UUID for the query to analyze  
    - If omitted, and `snowvi_path` is provided, the skill will attempt to infer `query_uuid` from the SnowVI JSON.

- **Optional**
  - `deployment`: Snowflake deployment (e.g. `azeastus2prod`); if omitted, resolve via Snowhouse as the app does
  - `snowvi_path`: Local path to a SnowVI JSON export for this query (if available)
  - `comparison_uuid`: A second UUID to compare against (before/after analysis)
  - `include_history_table`: Include query history table + timeline chart in output
  - `disable_telemetry`: Disable telemetry logging (enabled by default)
  - `symptom`: Optional symptom category (e.g. `latency_spikes`, `timeouts`, `quota_issues`)
  - `symptom_description`: Free-text description of what the customer is seeing


## High-Level Workflow

At a high level, the skill should follow this workflow:

1. **Connection & Environment Detection**
   - Confirm required Snowflake connections exist:
     - A **Snowhouse** connection (for telemetry)
     - Optionally, a **customer account** connection, if needed
   - If missing, guide the user to:
     - Run `snow connection add`
     - Use `Snowhouse` as the inference/telemetry connection

2. **Parameter Collection & Validation**
   - Ask the user for:
     - `query_uuid` (optional if `snowvi_path` provided)
     - Optional `deployment`, `snowvi_path`, `comparison_uuid`, `symptom`, `symptom_description`
   - If `query_uuid` is not provided, attempt to infer it from SnowVI JSON.
   - Validate basic UUID shape and that required values are non-empty.

3. **Metadata Fetch (Snowhouse)**
   - Call into a local Python script (`scripts/run_ht_analysis.py`) or module that:
     - Resolves deployment for the UUID (using the same tiered JOB\_ETL / USAGE views as the app)
     - Queries `SNOWHOUSE_IMPORT.&lt;deployment&gt;.JOB_ETL_JPS_V` (or union view) to fetch:
       - Core timing metrics (total, compile, GS exec, XP exec)
       - Rows/bytes, HT flags, FDB / KV metrics
       - Plan cache fields (CACHEDPLANID, PLANCACHE\_ORIGINAL\_JOB\_UUID, QUERY\_PARAMETERIZED\_HASH)
     - Optionally fetches **query history** for the parameterized hash and derives “always slow” vs “anomaly” context

4. **Optional SnowVI Enrichment**
   - If `snowvi_path` is provided:
     - Load SnowVI JSON from the local filesystem
     - Extract:
       - Hybrid index metadata and coverage
       - Hot RSOs and operator timing
       - Join-explosion indicators
       - KV / FDB timing and probe counts
       - UDF/UDTF usage and bulk-load patterns
     - Merge these into the same feature structures used by the Snowsight app.

5. **Deterministic Classification & Candidate Actions (Code Side)**
   - **Implemented in this skill** (deterministic, no LLMs):
     - `bp_findings` (grade, errors, warnings, workload type, bulk flags, etc.)
     - `sql_findings` from static SQL analysis
     - `coverage` list for relevant Hybrid Tables
     - `history_context` / anomaly classification
     - `candidate_actions`: a list of **allowed** concrete recommendations with:
       - `id`, `kind`, `ddl_sql`, `estimated_impact`, `risk_level`
   - Implementation modules:
     - `ht_analyzer/analysis.py` (orchestration)
     - `ht_analyzer/analysis_shared.py` (best‑practice logic)
     - `ht_analyzer/analysis_shared_sql.py` (SQL analysis + coverage + plan hints)

6. **AI-Based Explanation (LLM)**
   - Calls Snowflake Cortex via `ht_analyzer.llm` to generate:
     - `next_steps_markdown` (ASE-facing steps)
     - `customer_email_markdown` (optional email body)

7. **Structured JSON Output (Actual)**
   - The Python script returns JSON with this shape:

```jsonc
{
  "status": "ok",
  "schema_version": "1.0",
  "analysis_mode": "single|compare",
  "query_uuid": "string",
  "comparison_uuid": "string | null",
  "deployment": "string",
  "customer_info": {
    "name": "string | null",
    "account_id": "string | null",
    "deployment": "string"
  },
  "best_practices_summary": {
    "grade": "A–F | null",
    "score": "number | null",
    "workload_type": "string | null",
    "errors": 0,
    "warnings": 0,
    "passed": 0
  },
  "summary_markdown": "string",
  "analysis": { /* includes bp_findings, sql_findings, coverage, history_context */ },
  "history_table": [ /* optional: daily stats if include_history_table */ ],
  "history_chart_markdown": "string | null",
  "candidate_actions": [ /* allowed actions */ ],
  "next_steps_markdown": "string",
  "customer_email_markdown": "string | null"
}
```

## Error & Status Contract

All outputs include a `status` field:

- `status: "ok"` for success
- `status: "error"` for failures

Errors also include:

```json
{
  "status": "error",
  "schema_version": "1.0",
  "error_code": "INVALID_UUID | INVALID_COMPARISON_MODE | ANALYSIS_ERROR | CORTEX_ERROR",
  "error_message": "string",
  "details": { "optional": "object" }
}
```

Include `schema_version` in both success and error payloads so downstream systems can evolve safely.

8. **User-Facing Formatting**
   - This skill returns JSON to the caller. Rendering is handled by the client.


## Tools & Capabilities

The skill is allowed to use:

- **Snowflake-related tools**
  - `snowflake_connections_list`
  - `snowflake_switch_connection`
  - `snowflake_query`
- **Filesystem tools**
  - `fs_read_file` / equivalent to load SnowVI JSON
  - `fs_write_file` to persist JSON outputs or markdown reports
- **Shell / Python**
  - `shell` or python helpers to invoke:
    - `python scripts/run_ht_analysis.py --uuid &lt;UUID&gt; [...]`

> **Implementation Note (for Cursor / devs):**  
> The heavy lifting should live in `scripts/run_ht_analysis.py` (or a small package under `ht_analyzer/`). The skill itself should be mostly orchestration + prompt construction, not core logic.


## Output Format

The skill emits JSON only; clients can render `summary_markdown` and LLM outputs.


## Example Conversations

**Example 1 – Single UUID**

> _User_:  
> “Analyze Hybrid Table performance for UUID `01234567-89ab-cdef-0123-456789abcdef` and give me next steps for the SE.”

Skill behavior:

1. Ask for deployment and/or attempt to auto-detect via Snowhouse.  
2. Fetch metadata and run full analysis.  
3. Return ASE-facing next steps + summary.


**Example 2 – With SnowVI JSON**

> _User_:  
> “Use SnowVI export at `./snowvi/query-ht-1234.json` to do a deep analysis for UUID `0123abcd...`. I want a customer-facing email too.”

Skill behavior:

1. Load SnowVI JSON from the path.  
2. Enrich features and coverage.  
3. Run analysis + email generation.  
4. Return ASE summary + customer email markdown.


**Example 3 – Before/After Comparison**

> _User_:  
> “Compare UUID `0123-old` vs `0123-new` and explain why the new run is faster.”

Skill behavior:

1. Fetch metadata for both UUIDs.  
2. Optionally load and compare SnowVI JSONs if provided.  
3. Use the same pre-classified pair-comparison logic (`classify_run_pair`) as the app.  
4. Return a side-by-side summary and an AI explanation of what changed.


## Implementation Notes (for Cursor / Developers)

- Reuse as much code as possible from the existing **Hybrid Table Query Analyzer** Streamlit app:
  - Metadata fetch + deployment resolution
  - SnowVI feature extraction and classification
  - Plan cache / history context
  - `ANALYSIS_SCHEMA` and `candidate_actions` construction
  - “LLM as ranker/explainer” constraints
- Keep the LLM-facing prompts **very close** to what the app uses to minimize behavior drift.
- Ensure the Python module can be run both:
  - From Cortex Code (via this skill), and
  - In tests / notebooks, so you can validate outputs independently of the skill.