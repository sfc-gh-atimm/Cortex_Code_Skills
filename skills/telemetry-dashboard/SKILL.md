---
name: telemetry-dashboard
description: "Query skill telemetry from AFE.PUBLIC_APP_STATE.APP_EVENTS for the past 1, 7, 14, and 30 days. Includes user email lookup and customer Salesforce account tracking. Use when checking skill usage, adoption metrics, or debugging telemetry."
---

# Skill Telemetry Dashboard

## Overview
This skill queries the shared telemetry table `AFE.PUBLIC_APP_STATE.APP_EVENTS` to provide usage metrics for all skills logging to this table. It generates reports for 1, 7, 14, and 30 day time windows, enriched with user email addresses and customer Salesforce account information.

## Prerequisites
- Snowhouse connection configured (`Snowhouse` recommended for non-interactive auth)
- Access to `AFE.PUBLIC_APP_STATE.APP_EVENTS` table
- Access to `HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW` for employee email lookup

## When to Invoke
Use this skill when:
- "Show me skill telemetry"
- "How many times has the HT analyzer been used?"
- "Show skill usage for the past week"
- "Telemetry dashboard" or "skill metrics"
- "Who is using the skills?"
- "Show me telemetry for the past 30 days"
- "What customers have been analyzed?"
- "Show user emails for telemetry"

## Workflow

### Step 1: Run Core Telemetry Queries
Execute the following batched query to get all metrics in one call:

```bash
snow sql -c Snowhouse -q "
-- Summary by App (All Time Windows)
WITH time_windows AS (
    SELECT 
        APP_NAME,
        COUNT(*) as total_events,
        SUM(CASE WHEN EVENT_TS >= DATEADD(day, -1, CURRENT_TIMESTAMP()) THEN 1 ELSE 0 END) as last_1d,
        SUM(CASE WHEN EVENT_TS >= DATEADD(day, -7, CURRENT_TIMESTAMP()) THEN 1 ELSE 0 END) as last_7d,
        SUM(CASE WHEN EVENT_TS >= DATEADD(day, -14, CURRENT_TIMESTAMP()) THEN 1 ELSE 0 END) as last_14d,
        SUM(CASE WHEN EVENT_TS >= DATEADD(day, -30, CURRENT_TIMESTAMP()) THEN 1 ELSE 0 END) as last_30d,
        SUM(CASE WHEN SUCCESS = TRUE THEN 1 ELSE 0 END) as success_count,
        SUM(CASE WHEN SUCCESS = FALSE THEN 1 ELSE 0 END) as error_count,
        ROUND(AVG(DURATION_MS), 0) as avg_duration_ms,
        MIN(EVENT_TS) as first_event,
        MAX(EVENT_TS) as last_event
    FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
    GROUP BY APP_NAME
)
SELECT * FROM time_windows ORDER BY last_30d DESC;

-- Daily breakdown (last 14 days)
SELECT 
    DATE_TRUNC('day', EVENT_TS)::DATE as day,
    APP_NAME,
    COUNT(*) as events,
    SUM(CASE WHEN SUCCESS THEN 1 ELSE 0 END) as successes,
    SUM(CASE WHEN NOT SUCCESS THEN 1 ELSE 0 END) as errors
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE EVENT_TS >= DATEADD(day, -14, CURRENT_TIMESTAMP())
GROUP BY day, APP_NAME
ORDER BY day DESC, events DESC;

-- Action type breakdown (last 30 days)
SELECT 
    APP_NAME,
    ACTION_TYPE,
    COUNT(*) as count,
    SUM(CASE WHEN SUCCESS THEN 1 ELSE 0 END) as successes,
    SUM(CASE WHEN NOT SUCCESS THEN 1 ELSE 0 END) as errors,
    ROUND(AVG(DURATION_MS), 0) as avg_duration_ms
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE EVENT_TS >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY APP_NAME, ACTION_TYPE
ORDER BY APP_NAME, count DESC;

-- Recent errors (last 7 days)
SELECT 
    EVENT_TS,
    APP_NAME,
    USER_NAME,
    ACTION_TYPE,
    LEFT(ERROR_MESSAGE, 100) as error_preview
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE SUCCESS = FALSE 
  AND EVENT_TS >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY EVENT_TS DESC
LIMIT 10;
"
```

### Step 2: Get User Details with Email Addresses
The telemetry table stores either:
- **USER_NAME**: The Snowflake login (service account for Streamlit apps, actual user for CLI/skills)
- **VIEWER_EMAIL**: The actual user's login name (populated by Streamlit apps)

To get actual user emails, we need a two-step join:
1. **Snowhouse USER_ETL_V**: Maps LOGIN_NAME → EMAIL (first.last@snowflake.com format)
2. **HR SFDC_WORKDAY_USER_VW**: Maps EMAIL → employee details (name, title, department)

**Note:** Some user emails in Snowhouse are masked (`*********`) due to data masking policies. For those users, manual HR lookup is required.

```bash
snow sql -c Snowhouse -q "
-- Top users with email addresses (last 30 days)
WITH telemetry_users AS (
    SELECT 
        COALESCE(VIEWER_EMAIL, USER_NAME) as actual_user,
        COUNT(*) as total_events,
        COUNT(DISTINCT APP_NAME) as apps_used,
        LISTAGG(DISTINCT APP_NAME, ', ') WITHIN GROUP (ORDER BY APP_NAME) as app_list
    FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
    WHERE EVENT_TS >= DATEADD(day, -30, CURRENT_TIMESTAMP())
    GROUP BY actual_user
),
user_emails AS (
    -- Get login → email mapping from Snowhouse (emails are first.last@snowflake.com)
    -- Filter out masked emails (shown as *********)
    SELECT LOGIN_NAME, MAX(EMAIL) as EMAIL
    FROM SNOWHOUSE_IMPORT.PROD.USER_ETL_V
    WHERE EMAIL IS NOT NULL 
      AND EMAIL LIKE '%@snowflake.com'
      AND EMAIL NOT LIKE '*%'
    GROUP BY LOGIN_NAME
),
hr_lookup AS (
    SELECT PRIMARY_WORK_EMAIL, LEGAL_NAME_FIRST_NAME, LEGAL_NAME_LAST_NAME, 
           BUSINESS_TITLE, DEPARTMENT
    FROM HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW
)
SELECT DISTINCT
    t.actual_user as USER_LOGIN,
    COALESCE(u.EMAIL, '(masked - see manual lookup)') as EMAIL,
    h.LEGAL_NAME_FIRST_NAME as FIRST_NAME,
    h.LEGAL_NAME_LAST_NAME as LAST_NAME,
    h.BUSINESS_TITLE as TITLE,
    h.DEPARTMENT,
    t.total_events,
    t.apps_used,
    t.app_list
FROM telemetry_users t
LEFT JOIN user_emails u ON UPPER(t.actual_user) = UPPER(u.LOGIN_NAME)
LEFT JOIN hr_lookup h ON LOWER(u.EMAIL) = LOWER(h.PRIMARY_WORK_EMAIL)
WHERE t.actual_user NOT LIKE 'STPLAT%'  -- Exclude service accounts
ORDER BY t.total_events DESC
LIMIT 20;
"
```

### Step 2b: Manual Lookup for Masked Users
For users showing "(masked)", look up by last name in HR:

```bash
snow sql -c Snowhouse -q "
SELECT PRIMARY_WORK_EMAIL, LEGAL_NAME_FIRST_NAME, LEGAL_NAME_LAST_NAME, 
       BUSINESS_TITLE, DEPARTMENT
FROM HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW
WHERE PRIMARY_WORK_EMAIL ILIKE '%<LAST_NAME>%'
LIMIT 10"
```

Example: For login `SPINISETTI`, search `%pinisetti%` to find `srikanth.pinisetti@snowflake.com`.

### Step 3: Get Customer Salesforce Account Details
Extract customer information from telemetry events:

```bash
snow sql -c Snowhouse -q "
-- Customer accounts analyzed (last 30 days)
SELECT 
    SALESFORCE_ACCOUNT_NAME as customer_name,
    SALESFORCE_ACCOUNT_ID as sf_account_id,
    SNOWFLAKE_ACCOUNT_ID as sf_account_id_alt,
    DEPLOYMENT,
    COUNT(*) as analysis_count,
    COUNT(DISTINCT COALESCE(VIEWER_EMAIL, USER_NAME)) as unique_analysts,
    LISTAGG(DISTINCT APP_NAME, ', ') WITHIN GROUP (ORDER BY APP_NAME) as apps_used,
    MIN(EVENT_TS) as first_analysis,
    MAX(EVENT_TS) as last_analysis
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE EVENT_TS >= DATEADD(day, -30, CURRENT_TIMESTAMP())
  AND (SALESFORCE_ACCOUNT_NAME IS NOT NULL OR SNOWFLAKE_ACCOUNT_ID IS NOT NULL)
GROUP BY 
    SALESFORCE_ACCOUNT_NAME,
    SALESFORCE_ACCOUNT_ID,
    SNOWFLAKE_ACCOUNT_ID,
    DEPLOYMENT
ORDER BY analysis_count DESC;

-- Detailed customer event log (last 7 days)
SELECT 
    EVENT_TS,
    APP_NAME,
    COALESCE(VIEWER_EMAIL, USER_NAME) as analyst,
    SALESFORCE_ACCOUNT_NAME as customer,
    SNOWFLAKE_ACCOUNT_ID,
    DEPLOYMENT,
    ACTION_TYPE,
    ACTION_CONTEXT:recommendation::VARCHAR as recommendation,
    ACTION_CONTEXT:query_uuid::VARCHAR as query_uuid,
    SUCCESS
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE EVENT_TS >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND (SALESFORCE_ACCOUNT_NAME IS NOT NULL OR SNOWFLAKE_ACCOUNT_ID IS NOT NULL)
ORDER BY EVENT_TS DESC
LIMIT 50;
"
```

### Step 4: Generate Report
Format the results into a markdown report:

```markdown
# Skill Telemetry Dashboard
**Generated:** [timestamp]

---

## Usage Summary by App

| App Name | 1 Day | 7 Days | 14 Days | 30 Days | Total | Success Rate |
|----------|-------|--------|---------|---------|-------|--------------|
| [app]    | [n]   | [n]    | [n]     | [n]     | [n]   | [%]          |

---

## Top Users (Last 30 Days)

| User | Email | Name | Title | Department | Events | Apps |
|------|-------|------|-------|------------|--------|------|
| ...  | ...   | ...  | ...   | ...        | ...    | ...  |

---

## Customer Accounts Analyzed (Last 30 Days)

| Customer | SF Account ID | Deployment | Analyses | Analysts | Apps Used |
|----------|---------------|------------|----------|----------|-----------|
| ...      | ...           | ...        | ...      | ...      | ...       |

---

## Daily Activity (Last 14 Days)

| Date | App | Events | Successes | Errors |
|------|-----|--------|-----------|--------|
| ...  | ... | ...    | ...       | ...    |

---

## Recent Errors (Last 7 Days)

| Time | App | User | Action | Error |
|------|-----|------|--------|-------|
| ...  | ... | ...  | ...    | ...   |
```

---

## Data Sources

### Telemetry Table: `AFE.PUBLIC_APP_STATE.APP_EVENTS`

| Column | Type | Description |
|--------|------|-------------|
| EVENT_ID | VARCHAR | Unique event ID (UUID) |
| EVENT_TS | TIMESTAMP_LTZ | Event timestamp |
| APP_NAME | VARCHAR | Skill/app name |
| APP_VERSION | VARCHAR | Version string |
| USER_NAME | VARCHAR | Snowflake user (service account for Streamlit) |
| ROLE_NAME | VARCHAR | Role used |
| SNOWFLAKE_ACCOUNT | VARCHAR | Account running the skill |
| SALESFORCE_ACCOUNT_ID | VARCHAR | Customer SF account ID |
| SALESFORCE_ACCOUNT_NAME | VARCHAR | Customer name |
| SNOWFLAKE_ACCOUNT_ID | VARCHAR | Customer Snowflake account ID |
| DEPLOYMENT | VARCHAR | Snowflake deployment |
| ACTION_TYPE | VARCHAR | Event type (RUN_ANALYSIS, ERROR, etc.) |
| ACTION_CONTEXT | VARIANT | JSON context data (query_uuid, recommendation, etc.) |
| SUCCESS | BOOLEAN | Success flag |
| ERROR_MESSAGE | VARCHAR | Error details if failed |
| DURATION_MS | NUMBER | Execution duration |
| VIEWER_EMAIL | VARCHAR | Actual user login (for Streamlit apps) |

### User Email Lookup: `SNOWHOUSE_IMPORT.PROD.USER_ETL_V`

| Column | Type | Description |
|--------|------|-------------|
| LOGIN_NAME | VARCHAR | Snowflake login (e.g., `ATIMM`) |
| EMAIL | VARCHAR | Email address (e.g., `adam.timm@snowflake.com`) |
| NAME | VARCHAR | Display name |
| DEPLOYMENT | VARCHAR | Deployment where user exists |

**Note:** Email format is `first.last@snowflake.com`, NOT `login@snowflake.com`

### Employee Directory: `HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW`

| Column | Type | Description |
|--------|------|-------------|
| PRIMARY_WORK_EMAIL | VARCHAR | Employee email (e.g., `adam.timm@snowflake.com`) |
| LEGAL_NAME_FIRST_NAME | VARCHAR | First name |
| LEGAL_NAME_LAST_NAME | VARCHAR | Last name |
| BUSINESS_TITLE | VARCHAR | Job title |
| DEPARTMENT | VARCHAR | Department name |
| MANAGER_NAME | VARCHAR | Manager's name |
| EMPLOYEE_ID | VARCHAR | Workday employee ID |
| ACTIVE_STATUS | BOOLEAN | Active employee flag |

---

## Quick Queries

### Check specific app usage:
```bash
snow sql -c Snowhouse -q "
SELECT EVENT_TS, COALESCE(VIEWER_EMAIL, USER_NAME) as user, ACTION_TYPE, SUCCESS, DURATION_MS
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE APP_NAME = '<APP_NAME>'
ORDER BY EVENT_TS DESC
LIMIT 20"
```

### Check specific user activity:
```bash
snow sql -c Snowhouse -q "
SELECT EVENT_TS, APP_NAME, ACTION_TYPE, SALESFORCE_ACCOUNT_NAME, SUCCESS
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE COALESCE(VIEWER_EMAIL, USER_NAME) = '<USER_LOGIN>'
ORDER BY EVENT_TS DESC
LIMIT 20"
```

### Find user email by login:
```bash
snow sql -c Snowhouse -q "
SELECT PRIMARY_WORK_EMAIL, LEGAL_NAME_FIRST_NAME, LEGAL_NAME_LAST_NAME, 
       BUSINESS_TITLE, DEPARTMENT
FROM HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW
WHERE UPPER(PRIMARY_WORK_EMAIL) LIKE UPPER('%<LOGIN>%')
LIMIT 5"
```

### Get customer analysis history:
```bash
snow sql -c Snowhouse -q "
SELECT EVENT_TS, APP_NAME, COALESCE(VIEWER_EMAIL, USER_NAME) as analyst,
       ACTION_TYPE, ACTION_CONTEXT
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE SALESFORCE_ACCOUNT_NAME ILIKE '%<CUSTOMER_NAME>%'
ORDER BY EVENT_TS DESC
LIMIT 20"
```

### Get error details:
```bash
snow sql -c Snowhouse -q "
SELECT EVENT_TS, APP_NAME, ACTION_TYPE, ERROR_MESSAGE, ACTION_CONTEXT
FROM AFE.PUBLIC_APP_STATE.APP_EVENTS
WHERE SUCCESS = FALSE
ORDER BY EVENT_TS DESC
LIMIT 10"
```

---

## Notes

### User Identification
- **Streamlit apps** log the service account as `USER_NAME` (e.g., `STPLATSTREAMLIT...`) and the actual user in `VIEWER_EMAIL`
- **CLI/Skills** log the actual user as `USER_NAME`
- Use `COALESCE(VIEWER_EMAIL, USER_NAME)` to get the actual user in all cases
- **Email format is `first.last@snowflake.com`** (NOT `login@snowflake.com`)
- To resolve login → email, join with `SNOWHOUSE_IMPORT.PROD.USER_ETL_V` on `LOGIN_NAME`

### Customer Tracking
- Apps should log `SALESFORCE_ACCOUNT_NAME` and `SNOWFLAKE_ACCOUNT_ID` when analyzing customer data
- `ACTION_CONTEXT` may contain additional details like `query_uuid`, `recommendation`, `session_id`
