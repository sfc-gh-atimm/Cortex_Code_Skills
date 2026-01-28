# OLTP Discovery Template

| Customer Name | [CUSTOMER_NAME] |  |  |
| :---- | ----- | :---- | ----- |
| **Use Case Name** |  |  |  |
| **Use Case Link (in SFDC)** |  | \<link\> |  |
| **Opportunity Link (in SFDC)** |  | \<link\> |  |
| **Date** |  |  |  |
| **Account Executive**  |  |  |  |
| **Sales Engineer** |  |  |  |
| **Other Snowflake contributors (e.g. from AFE, APG, Professional Services)** |  |  |  |
| **Customer points of contact** |  |  |  |
| **Snowflake Account Names in Scope** |  |  |  |
| **What Snowflake Features are being considered?** |  | \<Postgres, Unistore, Interactive, Dynamic Tables, etc.\> |  |
| **Is the Customer a Postgres Expert?** |  |  |  |
| **Is workload migrating from Postgres?** |  |  |  |

# Opportunity Overview

## Use Case Summary

Place a short summary here. Full documentation should be at the SFDC Use Case link.

## Business Goal

1-2 sentences regarding the business goal or desired outcome.

## Solution-space

**Current Solution:** Currently using \<articulate current scenario\>

**Possible alternative solutions:** \<articulate what other options customer has\>

# Use Case Requirements & Technical details:

### Architecture diagram & description

Please provide if available.

### Overall Technical Requirements

Answers to these questions will assist the specialist team in recommending solution options:

| Data Volume / Size | \<data size on disk\> |
| :---- | :---- |
| **Row size range** | \<row counts for largest tables\> |
| **AVG operations per second** | \<system expected TPS\> |
| **PEAK operations per second** | \<system expected TPS\> |
| **P50 Latency Expectation** | \1-10ms, 10-50ms, \<100ms |
| **P99 Latency Expectation** | \1-10ms, 10-50ms, \<100ms |
| **Bulk Writes & Updates** | Hourly bulk updates, periodic row updates |
| **Are Primary Keys well defined?** |  |
| **Total Direct Cost** | ? |
| **Application Client** | \<JDBC/NodeJS, etc.\> |
| **Are there custom data types?** | \<details\> |
| **Is Elastic Compute important?** |  |
| **What ETL Tooling is in place?** | \<describe how data moves from OLTP to Snowflake today\> |
| **NOTES** | \<provide additional information you feel is helpful\> |

*Add additional requirements as needed*

### Workload Details

If some of the workload details are known, please place them here

| Query Name | SQL | Latency (current / expected) | Expected Throughput |
| :---- | :---- | :---- | :---- |
| *Example Query* |  |  |  |
