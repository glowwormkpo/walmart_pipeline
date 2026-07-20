#!/usr/bin/env python3
"""
Walmart End-to-End -- one-shot loader.

Uploads department.csv, stores.csv, fact.csv to S3, then connects to Snowflake and runs
the setup, stage, raw-table, COPY INTO, and dimensional-model SQL in order. Reuses the
.sql files in ../snowflake/ as the single source of truth -- this script is orchestration,
not a second copy of the SQL logic.

Setup:
    pip install -r requirements.txt
    cp .env.example .env   # fill in your AWS + Snowflake values

Usage:
    python load_pipeline.py --csv-dir ~/Downloads
    python load_pipeline.py --csv-dir ~/Downloads --skip-s3       # data's already in S3
    python load_pipeline.py --csv-dir ~/Downloads --skip-model    # load raw only, skip dims
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
import snowflake.connector
from botocore.exceptions import ClientError
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
SNOWFLAKE_SQL_DIR = SCRIPT_DIR.parent / "snowflake"


def log(msg: str) -> None:
    print(f"[walmart-e2e] {msg}", flush=True)


def load_config() -> dict:
    load_dotenv(SCRIPT_DIR / ".env")
    required = [
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "S3_BUCKET",
        "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE",
    ]
    cfg = {k: os.environ.get(k) for k in required}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        sys.exit(f"Missing required .env values: {', '.join(missing)}")
    cfg["STAGE_AUTH_MODE"] = os.environ.get("STAGE_AUTH_MODE", "credentials")
    cfg["SNOWFLAKE_INTEGRATION_ROLE_ARN"] = os.environ.get("SNOWFLAKE_INTEGRATION_ROLE_ARN")
    if cfg["STAGE_AUTH_MODE"] == "integration" and not cfg["SNOWFLAKE_INTEGRATION_ROLE_ARN"]:
        sys.exit("STAGE_AUTH_MODE=integration requires SNOWFLAKE_INTEGRATION_ROLE_ARN in .env")
    return cfg


# --------------------------------------------------------------------------------------
# Step 1: S3
# --------------------------------------------------------------------------------------
def upload_to_s3(cfg: dict, csv_dir: Path) -> None:
    s3 = boto3.client(
        "s3",
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
        region_name=cfg["AWS_REGION"],
    )
    bucket = cfg["S3_BUCKET"]

    try:
        s3.head_bucket(Bucket=bucket)
        log(f"Bucket s3://{bucket} already exists, reusing it.")
    except ClientError:
        log(f"Creating bucket s3://{bucket} in {cfg['AWS_REGION']}...")
        if cfg["AWS_REGION"] == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": cfg["AWS_REGION"]},
            )
        s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            },
        )
        log("Bucket created (versioned, all public access blocked).")

    for fname in ("department.csv", "stores.csv", "fact.csv"):
        src = csv_dir / fname
        if not src.exists():
            sys.exit(f"ERROR: {src} not found")
        key = f"raw/{fname}"
        log(f"Uploading {src} -> s3://{bucket}/{key}")
        s3.upload_file(str(src), bucket, key)

    log("S3 upload complete.")


# --------------------------------------------------------------------------------------
# Step 2: Snowflake
# --------------------------------------------------------------------------------------
def get_snowflake_connection(cfg: dict):
    return snowflake.connector.connect(
        account=cfg["SNOWFLAKE_ACCOUNT"],
        user=cfg["SNOWFLAKE_USER"],
        password=cfg["SNOWFLAKE_PASSWORD"],
        role=cfg["SNOWFLAKE_ROLE"],
        warehouse=cfg["SNOWFLAKE_WAREHOUSE"],
    )


def run_sql_file(conn, path: Path, label: str) -> None:
    log(f"Running {label} ({path.name})...")
    sql_text = path.read_text()
    for stmt_cur in conn.execute_string(sql_text):
        if stmt_cur.description:  # SELECT-like statement -- show results
            cols = [c[0] for c in stmt_cur.description]
            rows = stmt_cur.fetchall()
            print("  " + " | ".join(cols))
            for row in rows:
                print("  " + " | ".join(str(v) for v in row))
        elif stmt_cur.rowcount is not None and stmt_cur.rowcount >= 0:
            log(f"  -> {stmt_cur.rowcount} rows affected")


def create_stage_credentials(cur, cfg: dict) -> None:
    log("Creating stage (quick-start: AWS credentials on the stage object)...")
    cur.execute("USE DATABASE " + cfg["SNOWFLAKE_DATABASE"])
    cur.execute("USE SCHEMA RAW")
    cur.execute("""
        CREATE OR REPLACE FILE FORMAT WALMART_CSV_FORMAT
          TYPE = 'CSV'
          FIELD_DELIMITER = ','
          SKIP_HEADER = 1
          FIELD_OPTIONALLY_ENCLOSED_BY = '"'
          NULL_IF = ('NA', 'null', '')
          EMPTY_FIELD_AS_NULL = TRUE
          DATE_FORMAT = 'YYYY-MM-DD'
          TRIM_SPACE = TRUE
    """)
    cur.execute(f"""
        CREATE OR REPLACE STAGE WALMART_S3_STAGE
          URL = 's3://{cfg["S3_BUCKET"]}/raw/'
          CREDENTIALS = (AWS_KEY_ID = '{cfg["AWS_ACCESS_KEY_ID"]}' AWS_SECRET_KEY = '{cfg["AWS_SECRET_ACCESS_KEY"]}')
          FILE_FORMAT = WALMART_CSV_FORMAT
    """)


def create_stage_integration(cur, cfg: dict) -> None:
    """Automates the AWS<->Snowflake trust-policy handshake: creates the storage
    integration, reads back the IAM user ARN + external ID Snowflake generated, and
    patches the existing IAM role's trust policy via boto3. The IAM role and its S3
    read policy (aws/iam_policy_s3_access.json) must already exist -- this only wires
    up the trust relationship."""
    log("Creating stage (production: storage integration, no AWS keys stored)...")
    cur.execute("USE DATABASE " + cfg["SNOWFLAKE_DATABASE"])
    cur.execute("USE SCHEMA RAW")
    role_arn = cfg["SNOWFLAKE_INTEGRATION_ROLE_ARN"]
    bucket = cfg["S3_BUCKET"]

    cur.execute(f"""
        CREATE OR REPLACE STORAGE INTEGRATION WALMART_S3_INTEGRATION
          TYPE = EXTERNAL_STAGE
          STORAGE_PROVIDER = 'S3'
          ENABLED = TRUE
          STORAGE_AWS_ROLE_ARN = '{role_arn}'
          STORAGE_ALLOWED_LOCATIONS = ('s3://{bucket}/raw/')
    """)
    cur.execute("DESC INTEGRATION WALMART_S3_INTEGRATION")
    desc = {row[0]: row[2] for row in cur.fetchall()}  # property -> value
    iam_user_arn = desc["STORAGE_AWS_IAM_USER_ARN"]
    external_id = desc["STORAGE_AWS_EXTERNAL_ID"]
    log(f"  Snowflake IAM user: {iam_user_arn}")
    log(f"  External ID: {external_id}")

    role_name = role_arn.split("/", 1)[1]
    iam = boto3.client(
        "iam",
        aws_access_key_id=cfg["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=cfg["AWS_SECRET_ACCESS_KEY"],
    )
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": iam_user_arn},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
        }],
    }
    log(f"  Updating trust policy on IAM role {role_name}...")
    iam.update_assume_role_policy(RoleName=role_name, PolicyDocument=json.dumps(trust_policy))

    cur.execute("""
        CREATE OR REPLACE FILE FORMAT WALMART_CSV_FORMAT
          TYPE = 'CSV'
          FIELD_DELIMITER = ','
          SKIP_HEADER = 1
          FIELD_OPTIONALLY_ENCLOSED_BY = '"'
          NULL_IF = ('NA', 'null', '')
          EMPTY_FIELD_AS_NULL = TRUE
          DATE_FORMAT = 'YYYY-MM-DD'
          TRIM_SPACE = TRUE
    """)
    cur.execute(f"""
        CREATE OR REPLACE STAGE WALMART_S3_STAGE
          URL = 's3://{bucket}/raw/'
          STORAGE_INTEGRATION = WALMART_S3_INTEGRATION
          FILE_FORMAT = WALMART_CSV_FORMAT
    """)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Walmart CSVs into S3 and Snowflake.")
    parser.add_argument("--csv-dir", required=True, type=Path,
                         help="Folder containing department.csv, stores.csv, fact.csv")
    parser.add_argument("--skip-s3", action="store_true", help="Skip the S3 upload step")
    parser.add_argument("--skip-model", action="store_true",
                         help="Load raw tables only, skip building the dimensional model")
    args = parser.parse_args()

    cfg = load_config()

    if not args.skip_s3:
        upload_to_s3(cfg, args.csv_dir)
    else:
        log("Skipping S3 upload (--skip-s3).")

    log(f"Connecting to Snowflake account {cfg['SNOWFLAKE_ACCOUNT']}...")
    conn = get_snowflake_connection(cfg)
    try:
        cur = conn.cursor()
        run_sql_file(conn, SNOWFLAKE_SQL_DIR / "01_database_schema_warehouse.sql", "warehouse/database/schema setup")

        if cfg["STAGE_AUTH_MODE"] == "integration":
            create_stage_integration(cur, cfg)
        else:
            create_stage_credentials(cur, cfg)
        cur.execute("LIST @WALMART_S3_STAGE")
        staged_files = [row[0] for row in cur.fetchall()]
        log(f"Files visible on stage: {staged_files}")
        if len(staged_files) < 3:
            log("WARNING: expected 3 files on the stage -- check the S3 upload step.")

        run_sql_file(conn, SNOWFLAKE_SQL_DIR / "03_raw_tables.sql", "raw table DDL")
        run_sql_file(conn, SNOWFLAKE_SQL_DIR / "04_copy_into.sql", "COPY INTO (raw load)")

        if not args.skip_model:
            run_sql_file(conn, SNOWFLAKE_SQL_DIR / "05_dimensional_model.sql", "dimensional model build")
            run_sql_file(conn, SNOWFLAKE_SQL_DIR / "06_verification_queries.sql", "verification queries")
        else:
            log("Skipping dimensional model build (--skip-model).")

        log("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

