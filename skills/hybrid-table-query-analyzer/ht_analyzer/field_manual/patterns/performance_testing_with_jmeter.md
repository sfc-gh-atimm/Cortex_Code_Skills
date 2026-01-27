# Hybrid Tables Performance Testing with JMeter

This guide describes how to design and run realistic performance tests for Hybrid Tables using **Apache JMeter**, and how to interpret the results in Snowflake.

---

## 1. Goals of Performance Testing

When testing Hybrid Tables with JMeter, your objectives should be:

* Validate that the architecture and schema can meet **target latency** (e.g., p50/p95/p99) and **throughput (QPS/TPS)** for the real application workload, not just single-query benchmarks.

* Compare architectures (Hybrid Tables vs. standard tables / external DBs) in a **like‑for‑like** way:
  * Same schema tuned for each engine's best practices (don't blindly copy legacy schema).
  * Same network topology and region.
  * Same or equivalent warehouse sizing and configuration.

* Identify whether bottlenecks are in:
  * Client (JMeter VM, network).
  * Cloud Services (compilation, routing).
  * Warehouse.
  * Hybrid Table storage (throttling/quota).

---

## 2. Environment & Topology

### 2.1 Where to Run JMeter

* Run JMeter on a **VM in the same cloud region** as the Snowflake account under test. Cross-region or cross-ocean traffic will completely distort latency results.

* Avoid laptops for serious tests:
  * Browser/AV/background processes consume CPU/RAM.
  * Network path is rarely representative of production.

* **Advanced option:** Run JMeter **inside Snowpark Container Services (SPCS)**:
  * Co-locates the client near Snowflake with predictable resources.
  * Avoids laptop and VPN issues.
  * Recommended pattern: JMeter container images, compute pool (XS), stages for tests/results.

### 2.2 Snowflake Configuration

* Use a **dedicated warehouse** for perf testing so other workloads don't skew measurements.

* Start with **XS warehouses**:
  * Most HT workloads don't need larger sizes for point operations.
  * For higher load, scale **out** (multi‑cluster) rather than up (bigger size).

* Ensure you're actually testing **Hybrid Tables**:
  * Double‑check `CREATE HYBRID TABLE` was used (easy to forget!).
  * For bulk load tests, prefer CTAS when you can; it uses faster paths but doesn't support FKs today.

* Check **Hybrid Table quotas** if you push high throughput:
  * Identify and avoid throttling; request quota increases or isolated quotas for POCs as needed.

---

## 3. Workload Design

### 3.1 Represent Real Application Behavior

* Choose a **representative mix of queries**:
  * Hot path reads (e.g., point lookups by PK).
  * Representative writes (INSERT/UPDATE/DELETE) if applicable.
  * Any small-range queries the API will actually run.

* Define **realistic scale goals**:
  * Target p50 / p95 / p99 latency (e.g., `<100 ms` for point lookups, `<500 ms` for small batches).
  * Target QPS/TPS ranges (e.g., 100–1000+ TPS).

* Use **prepared statements / bound variables** in the SQL issued by JMeter:
  * Avoid string concatenation of literals; you want plan cache reuse.

### 3.2 Warmup & Duration

* Tests should run **long enough** to:
  * Warm up compilation, caches, and Hybrid Table storage.
  * Exercise steady-state behavior.

**Recommended protocol:**

* Run tests for **≥ 15 minutes**.
* **Discard the first ~5 minutes** as warmup.
* Analyze metrics from minutes 6+ only.

This better reflects real operational workloads, which run continuously and rarely operate in "cold start" mode.

---

## 4. JMeter Setup

### 4.1 JMeter Test Plan Structure

Typical test plan elements:

* **Thread Group**:
  * Number of users/threads (maps loosely to client concurrency).
  * Ramp-up period (how quickly to add load).
  * Loop count or duration (use Duration for time-bound tests).

* **JDBC Connection Configuration** (or Snowflake driver config):
  * Snowflake account/region.
  * Warehouse, database, schema, role.
  * Connection pool size sufficient to avoid client-side saturation.

* **Sampler(s)**:
  * SQL requests for different query types (e.g., `SELECT by PK`, `INSERT`, `UPDATE`).
  * Use variable bindings for parameters if possible.

* **Listeners**:
  * "View Results in Table" during dev.
  * CSV/JSON file reporter for production runs.
  * Avoid heavy GUI listeners for large runs; prefer non-GUI and file output.

### 4.2 Example CLI Execution

From the JMeter toolkit pattern:

```bash
#!/bin/bash
TEST=TPC_MD0101_01
END=.jmx
EpochTime=$(date +%s)
DateTime=$(date +%F_%H%M)
UNDER=_
OUT_NAME=$DateTime$UNDER$TEST
JMETER=JMETER
NOHUP=NOHUP

jmeter -n -t 01_JMX/$TEST$END \
       -l 03_RESULTS/$OUT_NAME.csv \
       -f -e -o 04_OUTPUT/$OUT_NAME \
       > 02_LOGS/$OUT_NAME.log &

mv nohup.out 02_LOGS/$OUT_NAME$UNDER$NOHUP.log && touch nohup.out
mv jmeter.log 02_LOGS/$OUT_NAME$UNDER$JMETER.log && touch jmeter.log
```

* `-n`: non-GUI mode.
* `-t`: test plan.
* `-l`: results CSV.
* `-o`: HTML report output directory.

### 4.3 Critical: Tag Your JMeter Queries

**Set a QUERY_TAG for all JMeter queries** so you can filter them in Snowflake query history:

```sql
-- In your JDBC connection string or JMeter setup
ALTER SESSION SET QUERY_TAG = 'ht_jmeter_perf';
```

Or in your JMeter JDBC Config:

```
Connection URL: jdbc:snowflake://<account>.snowflakecomputing.com/?warehouse=PERF_TEST_WH&db=TESTDB&schema=PUBLIC&query_tag=ht_jmeter_perf
```

This makes it trivial to filter for your test queries in AGGREGATE_QUERY_HISTORY.

---

## 5. Measuring Results

You should always compare **client-side metrics** with **Snowflake-side metrics**.

### 5.1 Client-Side (JMeter)

* Use JMeter reports/CSV to get:
  * Per-sample latency.
  * Aggregate stats (avg, p90, p95, p99).
  * Throughput over time.

* Confirm the **client machine is not the bottleneck**:
  * CPU and memory headroom on the VM.
  * No obvious GC / thread starvation.

### 5.2 Snowflake-Side (Aggregate Query History)

For Hybrid Tables, **short-running queries often don't appear in `QUERY_HISTORY`**. Use `AGGREGATE_QUERY_HISTORY` instead:

* Filter by:
  * Warehouse used for the test.
  * Time window of the experiment.
  * Query tags (if you set them in JMeter).
  * Parameterized query hash(es) for each query type.

* Focus on:
  * p50 / p90 / p99 latency (per query hash).
  * Query counts vs. JMeter counts (sanity check).
  * Throttling indicators for Hybrid Tables (request quotas).

**Pitfalls to avoid:**

* Relying on `QUERY_HISTORY` for HT performance: it is biased toward long-running outliers (e.g., >~500ms).
* Inspecting only **avg** or **max** latency rather than percentile distributions.

---

## 6. Interpreting Bottlenecks

Think top‑down: **Client → Cloud Services → Warehouse → Hybrid Table Storage**.

### 6.1 Client / Network

Indicators:

* Large gap between JMeter-measured latency and Snowflake latency (AQH).
* CPU saturation or high GC on the JMeter VM.

Mitigations:

* Move JMeter to a better-sized VM and/or co-locate in-region.
* Consider SPCS-based JMeter when appropriate.

### 6.2 Cloud Services (Compilation / Routing)

Indicators:

* High compilation time in AQH.
* Inconsistent routing to HT fast-path clusters.

Mitigations:

* Use **bound variables** to enable plan cache reuse.
* Simplify queries and avoid patterns that defeat plan caching.
* Run warmup and long enough duration to amortize compilation cost.

### 6.3 Warehouse Execution

Indicators:

* Long execution times per AQH.
* Warehouse hit concurrency limits (queue times, autoscaling symptoms).

Mitigations:

* Use a dedicated warehouse for the test.
* Increase multi-cluster count (scale out).
* Revisit query patterns (e.g., avoid analytic workloads on HT).

### 6.4 Hybrid Table Storage

Indicators:

* Long execution time **plus** Hybrid Table request throttling metrics in AQH.
* SnowVI showing storage throttling.

Mitigations:

* Request a **quota increase** or isolated quota for the POC database.
* Reduce unnecessary I/O (e.g., avoid scanning HT for analytics).
* Optimize schema and indexes, ensure queries are sargable.

---

## 7. Quick-Start Assets & Examples

* **Unistore POC Guide** (`go/ht-poc-guide`):
  * Best practices and performance testing guidance for Hybrid Tables, including JMeter-based tests.

* **Hybrid Tables JMeter Performance Testing Quickstart**:
  * Public quickstart that walks through setting up JMeter for HT perf testing.

* **JMeter + Python Performance Toolkit**:
  * POC Performance Testing Toolkit v2 – JMeter: reusable harness, directory structure, bash scripts, and Tableau workbook examples.

* **Running JMeter in SPCS**:
  * Internal guide on running JMeter inside Snowpark Container Services for realistic test environments.

* **Internal HT YCSB Atomics / Benchmarks**:
  * Reference for internal load and latency targets (YCSB-based JMeter workloads used at release gates).

---

## 8. Common Anti‑Patterns to Watch For

* Single-query "smoke tests" in Snowsight and then extrapolating to high‑QPS workloads.
* Comparing HT vs. standard tables using **legacy schemas** without:
  * HT‑appropriate PK and secondary indexes.
  * Representative workload mixes (point vs. scan).

* Running JMeter from:
  * A laptop thousands of miles away.
  * A VM with insufficient CPU/RAM.

* Very short test runs without warmup.

* Evaluating HT using *purely analytic* workloads that are better suited to standard tables, dynamic tables, or MVs.

---

**Last Updated:** 2025-12-06  
**Contributor:** AFE / SE Field Manual (Hybrid Tables + JMeter)  
**Field Validated:** Yes

