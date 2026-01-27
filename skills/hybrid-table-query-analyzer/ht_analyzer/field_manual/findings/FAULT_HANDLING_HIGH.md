
# Fault Handling (Retries, Idempotency, and Exception Patterns)

## What This Means

Unanticipated transient faults (e.g., connection hiccups, brief lock contention, intermittent service errors) cause otherwise healthy operations to fail if not handled explicitly. “Fault handling” means classifying errors, retrying only the right ones with backoff, and making operations idempotent so repeats don’t corrupt data.

---

## Why This Hurts Performance

- Unhandled transient failures trigger orchestration re-runs and user retries, multiplying load, queue time, and compile overhead for the same work.  

- Blind, aggressive retries amplify lock contention and can cascade into systemic slowdowns and more failures.  

- Non-idempotent steps (e.g., naked INSERTs) during retries create duplicates or conflicts, causing extra scans, merges, or cleanup work.

---

## Real-World Context

**Field Experience:**
- **Internal Bench/Scheduler (Eng usage)**: Frequent transaction contention errors were mitigated by adding exponential backoff on a specific error code check in client logic; the workflow stopped “fatally failing” on spikes and self-recovered when the lock cleared.

- **Connectivity/Driver Layer**: Application code used connector exception attributes (errno/sqlstate) to selectively retry transient connectivity issues (e.g., SQLSTATE 08001), improving job resilience without over-retrying non-retryable errors.

**Common Pattern:**
- Spiky concurrent writers or DDL cause short-lived contention; network or service blips appear sporadically; without targeted retries and idempotency, jobs fail noisily, and “shotgun” re-runs degrade throughput and inflate cost.

---

## How to Fix It

### Step 1: Classify retryable vs. non-retryable
- Retryable examples: short-lived connection/transport failures (e.g., SQLSTATE 08001), brief lock/transaction contention, intermittent internal incidents. Handle with limited retries and backoff. 

- Non-retryable examples: syntax/compilation errors, missing privileges/objects, deterministic data integrity violations. Fail fast and surface actionable diagnostics.

In Snowflake Scripting, use the EXCEPTION block and inspect built-in variables (SQLSTATE, SQLCODE, SQLERRM) to decide next actions. The CONTINUE handler lets the block proceed after handling and logging.

### Step 2: Add targeted retries in application code (recommended)
Python example with exponential backoff using connector errno/sqlstate:

```python
import time
import snowflake.connector
from snowflake.connector.errors import ProgrammingError, OperationalError

RETRYABLE_SQLSTATES = {"08001"}  # connection-related, transient
RETRYABLE_ERRNOS = {625}         # example: contention code from field thread

max_retries = 3
attempt = 0

while True:
    try:
        with snowflake.connector.connect(...) as conn:
            with conn.cursor() as cur:
                cur.execute("/* your DML/DDL */")
        break  # success
    except (OperationalError, ProgrammingError) as e:
        sqlstate = getattr(e, "sqlstate", None)
        errno = getattr(e, "errno", None)

        if (sqlstate in RETRYABLE_SQLSTATES) or (errno in RETRYABLE_ERRNOS):
            if attempt < max_retries:
                sleep_s = 0.5 * (2 ** attempt)
                time.sleep(sleep_s)
                attempt += 1
                continue
        raise  # non-retryable or retries exhausted
```

Rationale: Python connector exceptions expose `errno` and `sqlstate`, enabling programmatic handling without brittle message parsing.

### Step 3: Make operations idempotent
- Use MERGE instead of blind INSERT to upsert safely.

```sql
MERGE INTO tgt t
USING src s
ON t.id = s.id
WHEN MATCHED THEN UPDATE SET col_a = s.col_a, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (id, col_a, created_at) VALUES (s.id, s.col_a, CURRENT_TIMESTAMP());
```

- Prefer IF [NOT] EXISTS to avoid hard failures on create/drop:

```sql
CREATE TABLE IF NOT EXISTS demo (id NUMBER, col_a STRING);

DROP TABLE IF EXISTS demo_backup;
```

- For COPY INTO, choose ON_ERROR and VALIDATION_MODE deliberately to isolate and remediate bad records without killing the entire load:

```sql
COPY INTO tgt FROM @mystage/files/
FILE_FORMAT = (TYPE = CSV)
ON_ERROR = 'CONTINUE';  -- or 'SKIP_FILE_...'/‘ABORT_STATEMENT’ based on policy
```

### Step 4: Use Snowflake Scripting handlers to fence and log faults
Pattern: capture statement errors into an error table and continue, so a single bad row won’t abort the whole batch.

```sql
CREATE OR REPLACE TABLE error_log (
  ts TIMESTAMP_NTZ,
  sqlstate STRING,
  sqlcode NUMBER,
  sqlerrm STRING,
  context VARIANT
);

-- Example: process loop with a CONTINUE handler
BEGIN
  FOR rec IN (SELECT * FROM src) DO
    BEGIN
      INSERT INTO tgt (id, v) VALUES (rec.id, rec.v);
    EXCEPTION
      WHEN STATEMENT_ERROR CONTINUE THEN
        INSERT INTO error_log
        VALUES (CURRENT_TIMESTAMP(), SQLSTATE, SQLCODE, SQLERRM, OBJECT_CONSTRUCT('id', rec.id));
    END;
  END FOR;
END;
```

Why this works: Snowflake Scripting EXCEPTION handlers can reference built-in diagnostics; the CONTINUE handler resumes at the next statement, enabling per-row fault tolerance instead of aborting the whole procedure.

### Step 5: Validation
- Count retry-prone failures by SQLSTATE and code:

#### 🔒 For Internal Use (Snowhouse/AFE)

```sql
-- Internal: Count retry-prone failures
-- Replace {{DEPLOYMENT}} with the actual deployment (e.g., va3, aws_us_west_2)
SELECT
  ERROR_CODE,
  ERROR_MESSAGE,
  COUNT(*) AS occurrences
FROM SNOWHOUSE_IMPORT.{{DEPLOYMENT}}.JOB_ETL_V
WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NOT NULL
GROUP BY 1, 2
ORDER BY occurrences DESC;
```

#### 👤 For Customer Use

```sql
-- Customer: Count retry-prone failures
-- Note: ACCOUNT_USAGE has 45min-3hr latency
SELECT
  ERROR_CODE,
  ERROR_MESSAGE,
  COUNT(*) AS occurrences
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE START_TIME >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND ERROR_CODE IS NOT NULL
GROUP BY 1, 2
ORDER BY occurrences DESC;
```

- Verify that error_log remains small and that overall job success rate is higher after changes.

---

## Expected Improvement

- **Reliability**: Transient-failure jobs self-recover with 1–3 bounded retries; fewer “all-or-nothing” batch aborts.

- **Throughput**: Less cascade retry pressure and fewer duplicates/conflicts from non-idempotent writes; steadier pipelines under load.

- **Ops Load**: Fewer manual re-runs and ad-hoc cleanup due to controlled retries and error fencing.

**Confidence:** Medium, based on internal field usage and connector behavior guarantees (errno/sqlstate) plus GA exception handling semantics.

---

## When NOT to Apply This Fix

⚠️ **Don't use this fix if:**
- The error is deterministic and non-transient (e.g., privilege error, missing object, syntax/compile error) — fail fast and fix root cause, don’t retry.

- The operation is not idempotent and side effects cannot be made safe; retried actions could corrupt state.

✅ **Do consider alternatives if:**
- Replace INSERT with MERGE/UPSERT to achieve idempotency for safe retries.

- Split mixed responsibilities: isolate fault-prone steps into their own procedure/task with local handlers and compensating actions.

---

## Related Findings

See also:
- `findings/transaction_contention.md` - Patterns and mitigations for hot locks/contention (e.g., queueing, smaller batches, indexing)

- `patterns/resilient_loading.md` - COPY/ingest strategies (staging, ON_ERROR, dead-letter queues)

- `patterns/scripting_exception_handling.md` - Deeper examples of EXCEPTION/CONTINUE usage

---

## Additional Resources

- Snowflake Scripting: Handling exceptions (built-in diagnostics, handlers, examples) — https://docs.snowflake.com/en/developer-guide/snowflake-scripting/exceptions

- CONTINUE handler usage guide (behavior and examples)

- Python connector: exceptions and query status (errno/sqlstate exposure for programmatic handling) — https://github.com/snowflakedb/snowflake-connector-python

- Example of contention/backoff handling shared in engineering thread (error 625 sample)

---

**Last updated:** 2025-12-12  
**Contributor:** Adam Timm (Solution Engineering)  
**Field Validated:** Yes


---

## Sources

- [Thread between Matt, Shin, Lesley, and 4 others](https://slack.com/archives/C05FMUED18W/p1737738725469889)
- [connection.py](https://github.com/snowflakedb/snowflake-connector-python/blob/main/src/snowflake/connector/connection.py)
- [Rod, Danny, Ethan, and 4 others](https://slack.com/archives/C2P82R51B/p1765217052684629)
- [Exception handler can't access variables declared in BEGIN..END block](https://snowforce.lightning.force.com/lightning/r/KnowledgeArticle/kA9Do0000004COhKAM/view)
- [CONTINUE handler usage guide](https://docs.google.com/document/d/12M8RJnZoMzwq-UIYLivwa68UNzNgM0xs4jOIzro02gg)
- [Anton](https://slack.com/archives/C08S9HZB66A/p1761117280403229)
