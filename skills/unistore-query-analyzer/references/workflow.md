# Hybrid Table Query Analyzer - Workflow Details

## High-Level Workflow

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
   - Query `SNOWHOUSE_IMPORT.<deployment>.JOB_ETL_JPS_V` to fetch:
     - Core timing metrics (total, compile, GS exec, XP exec)
     - Rows/bytes, HT flags, FDB / KV metrics
     - Plan cache fields (CACHEDPLANID, QUERY_PARAMETERIZED_HASH)
   - Optionally fetches **query history** for the parameterized hash

4. **Optional SnowVI Enrichment**
   - If `snowvi_path` is provided:
     - Load SnowVI JSON from the local filesystem
     - Extract hybrid index metadata, hot RSOs, operator timing
     - Extract KV / FDB timing and probe counts

5. **Deterministic Classification & Candidate Actions**
   - `bp_findings` (grade, errors, warnings, workload type)
   - `sql_findings` from static SQL analysis
   - `coverage` list for relevant Hybrid Tables
   - `history_context` / anomaly classification
   - `candidate_actions`: concrete recommendations

6. **AI-Based Explanation (LLM)**
   - Calls Snowflake Cortex to generate `next_steps_markdown`

7. **Structured JSON Output**
   - Returns analysis results as JSON

## Implementation Modules

| Module | Purpose |
|--------|---------|
| `ht_analyzer/analysis.py` | Orchestration |
| `ht_analyzer/analysis_shared.py` | Best-practice logic |
| `ht_analyzer/analysis_shared_sql.py` | SQL analysis + coverage |
| `ht_analyzer/snowvi_features.py` | SnowVI feature extraction |
| `ht_analyzer/snowhouse.py` | Snowhouse queries |
