-- Landing tables — column names/types match the source CSVs 1:1 (verified against the
-- actual files: department.csv 421,570 rows, stores.csv 45 rows, fact.csv 8,190 rows).

USE DATABASE WALMART_E2E;
USE SCHEMA RAW;

CREATE OR REPLACE TABLE DEPARTMENT (
  STORE         NUMBER,
  DEPT          NUMBER,
  DATE          DATE,
  WEEKLY_SALES  FLOAT,
  ISHOLIDAY     BOOLEAN
);

CREATE OR REPLACE TABLE STORES (
  STORE NUMBER,
  TYPE  VARCHAR(1),
  SIZE  NUMBER
);

CREATE OR REPLACE TABLE FACT (
  STORE         NUMBER,
  DATE          DATE,
  TEMPERATURE   FLOAT,
  FUEL_PRICE    FLOAT,
  MARKDOWN1     FLOAT,
  MARKDOWN2     FLOAT,
  MARKDOWN3     FLOAT,
  MARKDOWN4     FLOAT,
  MARKDOWN5     FLOAT,
  CPI           FLOAT,
  UNEMPLOYMENT  FLOAT,
  ISHOLIDAY     BOOLEAN
);
