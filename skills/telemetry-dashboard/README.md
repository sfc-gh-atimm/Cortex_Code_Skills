# Telemetry Dashboard Skill

Query skill telemetry from the shared `AFE.PUBLIC_APP_STATE.APP_EVENTS` table with enriched user and customer data.

## Features
- Usage metrics for 1, 7, 14, and 30 day windows
- Daily activity breakdown
- **User email lookup** via HR.WORKDAY_BASIC.SFDC_WORKDAY_USER_VW
- **Customer Salesforce account tracking**
- Action type analysis
- Recent errors

## Usage
Invoke with phrases like:
- "Show skill telemetry"
- "Telemetry dashboard"
- "How many times has the HT analyzer been used?"
- "Who is using the skills?"
- "What customers have been analyzed?"

## Prerequisites
- `Snowhouse_PAT` connection configured
- Access to `AFE.PUBLIC_APP_STATE` schema
- Access to `HR.WORKDAY_BASIC` schema (for user emails)
