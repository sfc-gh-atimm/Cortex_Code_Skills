# Health Scoring Guide

## Overview

This guide defines the thresholds for calculating health scores (0-100) for each OLTP product. Scores are categorized as:

| Score Range | Status | Color |
|-------------|--------|-------|
| 80-100 | HEALTHY | Green |
| 50-79 | WARNING | Yellow |
| 0-49 | CRITICAL | Red |

---

## Hybrid Tables Health Score

**Total: 100 points**

### Latency Score (40 points)

| P50 Latency | Points | Assessment |
|-------------|--------|------------|
| < 10ms | 40 | Optimal - meeting HT design target |
| 10-50ms | 30 | Good - acceptable performance |
| 50-100ms | 20 | Warning - investigate slow queries |
| 100-500ms | 10 | Poor - likely workload misfit or index issues |
| > 500ms | 0 | Critical - immediate action required |

### Optimal Query Percentage (30 points)

Optimal = queries completing in < 10ms

| Optimal Query % | Points | Assessment |
|-----------------|--------|------------|
| > 80% | 30 | Excellent - workload well-suited for HT |
| 60-80% | 20 | Good - some optimization opportunities |
| 40-60% | 10 | Warning - review query patterns |
| < 40% | 0 | Critical - workload may not suit HT |

### FDB Health (30 points)

| FDB Timeout Rate | Points | Assessment |
|------------------|--------|------------|
| < 0.01% | 30 | Healthy - no FDB issues |
| 0.01-0.1% | 20 | Monitor - occasional timeouts |
| 0.1-1% | 10 | Warning - FDB pressure |
| > 1% | 0 | Critical - contact support |

---

## Interactive Analytics Health Score

**Total: 100 points**

### Sub-Second Query Percentage (50 points)

| Sub-Second % | Points | Assessment |
|--------------|--------|------------|
| > 95% | 50 | Excellent - meeting IA goals |
| 80-95% | 40 | Good - minor optimization possible |
| 60-80% | 25 | Warning - review slow queries |
| 40-60% | 10 | Poor - significant issues |
| < 40% | 0 | Critical - IA not delivering value |

### Compilation Efficiency (30 points)

Fast compile = < 100ms

| Fast Compile % | Points | Assessment |
|----------------|--------|------------|
| > 80% | 30 | Excellent - efficient query compilation |
| 60-80% | 20 | Good - some complex queries |
| 40-60% | 10 | Warning - high compilation overhead |
| < 40% | 0 | Critical - review query complexity |

### Error Rate (20 points)

| Error Rate | Points | Assessment |
|------------|--------|------------|
| < 0.1% | 20 | Healthy |
| 0.1-0.5% | 15 | Minor issues |
| 0.5-1% | 10 | Warning |
| > 1% | 0 | Critical |

---

## Snowflake Postgres Health Score

**Total: 100 points**

### Latency Distribution (50 points)

Sub-100ms queries percentage

| Sub-100ms % | Points | Assessment |
|-------------|--------|------------|
| > 80% | 50 | Excellent - fast OLTP performance |
| 60-80% | 35 | Good - acceptable for most workloads |
| 40-60% | 20 | Warning - latency concerns |
| < 40% | 0 | Critical - significant latency issues |

### Throughput Stability (30 points)

Based on coefficient of variation (CV) of daily query counts

| CV | Points | Assessment |
|----|--------|------------|
| < 0.2 | 30 | Stable - consistent workload |
| 0.2-0.5 | 20 | Moderate variation |
| 0.5-1.0 | 10 | High variation |
| > 1.0 | 0 | Very unstable - investigate |

### Error Rate (20 points)

| Error Rate | Points | Assessment |
|------------|--------|------------|
| < 0.1% | 20 | Healthy |
| 0.1-0.5% | 15 | Minor issues |
| 0.5-1% | 10 | Warning |
| > 1% | 0 | Critical |

---

## Overall Account Health Score

The overall OLTP health score is calculated as:

```
Overall = (HT_Score * HT_Weight + IA_Score * IA_Weight + PG_Score * PG_Weight) / Total_Weight
```

Where weights are based on query volume:
- Weight = 1 if product is not in use
- Weight = log10(query_count) if product is in use

If only one product is in use, that product's score becomes the overall score.

---

## Trend Analysis

### Latency Trend Scoring

| Week-over-Week Change | Assessment | Action |
|-----------------------|------------|--------|
| Improved > 20% | Positive | None |
| Stable (-20% to +20%) | Normal | Monitor |
| Degraded 20-50% | Warning | Investigate |
| Degraded > 50% | Critical | Immediate action |

### Volume Trend Scoring

| Week-over-Week Change | Assessment |
|-----------------------|------------|
| Growth > 50% | High adoption |
| Growth 10-50% | Growing usage |
| Stable (-10% to +10%) | Steady state |
| Decline > 10% | Investigate drop |
