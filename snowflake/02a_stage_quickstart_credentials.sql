-- QUICK START PATH — fastest way to get moving.
-- Stores your AWS access key directly on the stage object. Fine for a personal/learning
-- project; for anything shared or long-lived, use 02b_stage_storage_integration.sql instead
-- (no AWS keys ever stored in Snowflake).
--
-- Replace the placeholders below, then run this whole file.

USE DATABASE WALMART_E2E;
USE SCHEMA RAW;

CREATE OR REPLACE FILE FORMAT WALMART_CSV_FORMAT
  TYPE = 'CSV'
  FIELD_DELIMITER = ','
  SKIP_HEADER = 1
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  NULL_IF = ('NA', 'null', '')
  EMPTY_FIELD_AS_NULL = TRUE
  DATE_FORMAT = 'YYYY-MM-DD'
  TRIM_SPACE = TRUE
  COMMENT = 'Shared CSV format for the Walmart raw loads';

CREATE OR REPLACE STAGE WALMART_S3_STAGE
  URL = 's3://REPLACE_BUCKET_NAME/raw/'
  CREDENTIALS = (AWS_KEY_ID = 'REPLACE_AWS_ACCESS_KEY_ID' AWS_SECRET_KEY = 'REPLACE_AWS_SECRET_ACCESS_KEY')
  FILE_FORMAT = WALMART_CSV_FORMAT
  COMMENT = 'External stage pointing at the raw/ prefix of the Walmart S3 bucket';

-- Sanity check: should list department.csv, stores.csv, fact.csv
LIST @WALMART_S3_STAGE;
