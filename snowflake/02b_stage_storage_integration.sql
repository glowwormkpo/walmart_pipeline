-- PRODUCTION PATH — no AWS keys stored in Snowflake, access controlled by an IAM role.
-- This is a two-way handshake between AWS and Snowflake, run in this order:
--
--   1. In AWS: create the IAM policy (aws/iam_policy_s3_access.json) and a role using
--      aws/iam_trust_policy_placeholder.json as a temporary trust policy (principal doesn't
--      matter yet — you'll overwrite it in step 4). Note the role's ARN.
--   2. Run STEP 1 below, substituting that role ARN and your bucket name.
--   3. Run STEP 2 below (DESC INTEGRATION) and copy STORAGE_AWS_IAM_USER_ARN and
--      STORAGE_AWS_EXTERNAL_ID from the output.
--   4. In AWS: edit the IAM role's trust policy, replacing the placeholders in
--      aws/iam_trust_policy_placeholder.json with those two values.
--   5. Run STEP 3 below to create the stage using the integration.

USE DATABASE WALMART_E2E;
USE SCHEMA RAW;

-- STEP 1
CREATE OR REPLACE STORAGE INTEGRATION WALMART_S3_INTEGRATION
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::REPLACE_ACCOUNT_ID:role/REPLACE_ROLE_NAME'
  STORAGE_ALLOWED_LOCATIONS = ('s3://REPLACE_BUCKET_NAME/raw/');

-- STEP 2 — copy STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID into the AWS trust policy
DESC INTEGRATION WALMART_S3_INTEGRATION;

-- STEP 3 — only run after the AWS trust policy has been updated
CREATE OR REPLACE FILE FORMAT WALMART_CSV_FORMAT
  TYPE = 'CSV'
  FIELD_DELIMITER = ','
  SKIP_HEADER = 1
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  NULL_IF = ('NA', 'null', '')
  EMPTY_FIELD_AS_NULL = TRUE
  DATE_FORMAT = 'YYYY-MM-DD'
  TRIM_SPACE = TRUE;

CREATE OR REPLACE STAGE WALMART_S3_STAGE
  URL = 's3://REPLACE_BUCKET_NAME/raw/'
  STORAGE_INTEGRATION = WALMART_S3_INTEGRATION
  FILE_FORMAT = WALMART_CSV_FORMAT;

-- Sanity check: should list department.csv, stores.csv, fact.csv
LIST @WALMART_S3_STAGE;
