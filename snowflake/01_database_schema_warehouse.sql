-- Run as a role with CREATE DATABASE / CREATE WAREHOUSE privilege (e.g. SYSADMIN).
-- Sets up the containers everything else in this project lands in.

CREATE WAREHOUSE IF NOT EXISTS WALMART_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Warehouse for Walmart End-to-End project';

CREATE DATABASE IF NOT EXISTS WALMART_E2E
  COMMENT = 'Walmart End-to-End project: raw + modeled data';

CREATE SCHEMA IF NOT EXISTS WALMART_E2E.RAW
  COMMENT = 'Landing zone tables loaded 1:1 from the S3 CSVs';

CREATE SCHEMA IF NOT EXISTS WALMART_E2E.CORE
  COMMENT = 'Dimensional model: Walmart_date_dim, Walmart_store_dim, Walmart_fact_table';

USE WAREHOUSE WALMART_WH;
USE DATABASE WALMART_E2E;
USE SCHEMA RAW;
