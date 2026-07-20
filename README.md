# Walmart End-to-End — S3 → Snowflake → Streamlit Pipeline

Runnable version of the pipeline described in `Walmart_End_to_End_Project_Brief.docx`:
raw CSVs → S3 → Snowflake (raw + dimensional model) → a Snowpark/Streamlit dashboard
covering the 10 required reports.

## Prerequisites

- AWS CLI v2, configured (`aws configure`) with permission to create an S3 bucket and
  (for the production path) an IAM role
- A Snowflake account with a role that can create databases/warehouses (e.g. SYSADMIN)
- The three source files: `department.csv`, `stores.csv`, `fact.csv`

## Run order

### Option A — one-shot Python script (recommended if you want a single command)

```bash
cd scripts
pip install -r requirements.txt
cp .env.example .env      # fill in your AWS + Snowflake values
python load_pipeline.py --csv-dir ~/Downloads   # folder with the 3 CSVs
```

This uploads the CSVs to S3, then connects to Snowflake and runs `01_database_schema_warehouse.sql`,
creates the stage (credentials or storage-integration, set via `STAGE_AUTH_MODE` in `.env`),
runs `03_raw_tables.sql`, `04_copy_into.sql`, `05_dimensional_model.sql`, and
`06_verification_queries.sql` in order — printing row counts and the verification output
as it goes. It executes the same `.sql` files described in Option B below, so the two
paths stay in sync; use `--skip-s3` to re-run just the Snowflake half, or `--skip-model`
to load raw tables only.

If you use `STAGE_AUTH_MODE=integration`, the IAM role in `SNOWFLAKE_INTEGRATION_ROLE_ARN`
must already exist with the S3 read policy from `aws/iam_policy_s3_access.json` attached —
the script only automates the circular trust-policy handshake (creating the Snowflake
integration, reading back its IAM user ARN/external ID, and patching the role's trust
policy), not the role's initial creation.

### Option B — run each step by hand

#### 1. Upload to S3

```bash
cd aws
./upload_to_s3.sh <bucket-name> <aws-region> <path-to-folder-with-the-3-csvs>
# example: ./upload_to_s3.sh walmart-e2e-jerry-2026 us-east-1 ~/Downloads
```

Creates the bucket if it doesn't exist (versioned, all public access blocked) and uploads
the three CSVs to `s3://<bucket>/raw/`.

#### 2. Connect Snowflake to that bucket

Pick one, in a Snowflake worksheet:

- **`snowflake/02a_stage_quickstart_credentials.sql`** — fastest path, stores your AWS
  access key on the stage object directly. Fine for a personal/learning project.
- **`snowflake/02b_stage_storage_integration.sql`** — production path, no AWS keys ever
  stored in Snowflake. More setup (a two-way handshake between AWS and Snowflake spelled
  out in the file's comments); uses `aws/iam_policy_s3_access.json` and
  `aws/iam_trust_policy_placeholder.json`.

Run `snowflake/01_database_schema_warehouse.sql` first either way.

#### 3. Load and model in Snowflake

Run in order:

```
snowflake/03_raw_tables.sql          -- landing tables, 1:1 with the CSVs
snowflake/04_copy_into.sql           -- COPY INTO from the stage
snowflake/05_dimensional_model.sql   -- Walmart_date_dim / _store_dim / _fact_table
snowflake/06_verification_queries.sql -- row-count and join-integrity checks
```

Expected row counts after step 3: `RAW.DEPARTMENT` 421,570 · `RAW.STORES` 45 ·
`RAW.FACT` 8,190 · `CORE.WALMART_DATE_DIM` 182 · `CORE.WALMART_STORE_DIM` (current) 3,331 ·
`CORE.WALMART_FACT_TABLE` 421,570.

### Deploy the dashboard (either option)

See `streamlit/README_deploy.md` — native Streamlit-in-Snowflake (recommended, no local
setup) or run locally with `streamlit run`.

## What's modeled where

| Layer | Object | Notes |
|---|---|---|
| Landing | `RAW.DEPARTMENT`, `RAW.STORES`, `RAW.FACT` | Untransformed, matches CSV columns |
| Dimension (SCD1) | `CORE.WALMART_DATE_DIM` | Upsert on Date_Id (YYYYMMDD) |
| Dimension (SCD2) | `CORE.WALMART_STORE_DIM` | Versioned on (Store_id, Dept_id); expire-then-insert MERGE pattern |
| Fact | `CORE.WALMART_FACT_TABLE` | Store/Dept/Date grain, joined to current store_dim version |
| Reporting | `streamlit/streamlit_app.py` | 10 tabs, one per required report, Snowpark-pushdown aggregations |

See section 7 ("Open Questions / Discrepancies") of the project brief for modeling
decisions worth confirming with whoever's grading/reviewing this — e.g. the SCD2 fact
join uses `IS_CURRENT = TRUE` rather than a date-range join, because this is a one-time
historical load with only one snapshot of store attributes (no real historical versions
to range-join against). That's called out again in `snowflake/05_dimensional_model.sql`.

## Re-running from scratch

All the `CREATE TABLE` statements use `IF NOT EXISTS` except the raw tables and fact
table load, which use `CREATE OR REPLACE` / `TRUNCATE` so re-running steps 3-5 is safe
and idempotent. `WALMART_STORE_DIM`'s SCD2 MERGE is also safe to re-run — with no
attribute changes in the source, the second run is a no-op.
