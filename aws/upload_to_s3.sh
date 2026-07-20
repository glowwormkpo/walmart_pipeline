#!/usr/bin/env bash
# Uploads the three raw Walmart CSVs to S3 for Snowflake ingestion.
#
# Prereqs:
#   1. AWS CLI v2 installed and configured: `aws configure` (or use an AWS SSO profile)
#   2. Your IAM user/role needs: s3:CreateBucket, s3:PutObject, s3:PutBucketVersioning,
#      s3:GetBucketLocation on the target bucket
#
# Usage:
#   ./upload_to_s3.sh <bucket-name> <aws-region> <path-to-csv-folder>
#   Example: ./upload_to_s3.sh walmart-e2e-jerry-2026 us-east-1 ~/Downloads

set -euo pipefail

BUCKET_NAME="${1:?Usage: ./upload_to_s3.sh <bucket-name> <aws-region> <path-to-csv-folder>}"
REGION="${2:?Missing AWS region, e.g. us-east-1}"
CSV_DIR="${3:?Missing path to folder containing department.csv, stores.csv, fact.csv}"
PREFIX="raw"

echo "== Checking bucket $BUCKET_NAME in $REGION =="
if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "Bucket already exists, reusing it."
else
  echo "Creating bucket..."
  if [ "$REGION" = "us-east-1" ]; then
    # us-east-1 is the one region that rejects a LocationConstraint
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$BUCKET_NAME" \
    --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  echo "Bucket created with versioning on and all public access blocked."
fi

echo "== Uploading CSVs to s3://$BUCKET_NAME/$PREFIX/ =="
for f in department.csv stores.csv fact.csv; do
  if [ ! -f "$CSV_DIR/$f" ]; then
    echo "ERROR: $CSV_DIR/$f not found" >&2
    exit 1
  fi
  aws s3 cp "$CSV_DIR/$f" "s3://$BUCKET_NAME/$PREFIX/$f"
done

echo "== Done. Files at: =="
aws s3 ls "s3://$BUCKET_NAME/$PREFIX/"

echo
echo "Next: open snowflake/01_quickstart_credentials.sql (fast path) or"
echo "snowflake/01_storage_integration.sql (production path, no keys stored in Snowflake)."
