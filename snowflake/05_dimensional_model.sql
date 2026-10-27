-- Builds the three tables specified in the requirements doc from the RAW schema.
-- Run 01-04 first. Run this file's sections in order: date_dim, then store_dim, then fact_table
-- (fact_table looks up surrogate keys from both dimensions).

USE DATABASE WALMART_E2E;
USE SCHEMA CORE;
USE WAREHOUSE WALMART_WH;

----------------------------------------------------------------------------------------------
-- 1. WALMART_DATE_DIM — SCD Type 1 (upsert), per requirements doc
----------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS WALMART_DATE_DIM (
  DATE_ID      NUMBER PRIMARY KEY,   -- YYYYMMDD, e.g. 20100205
  DATE         DATE,
  ISHOLIDAY    BOOLEAN,
  INSERT_DATE  TIMESTAMP_NTZ,
  UPDATE_DATE  TIMESTAMP_NTZ
);

MERGE INTO WALMART_DATE_DIM T
USING (
  -- department.csv and fact.csv agree on IsHoliday for every overlapping row (verified during
  -- profiling), so a simple MAX() is a safe tie-breaker for dates that only appear in one source.
  SELECT
    TO_NUMBER(TO_CHAR(DATE, 'YYYYMMDD')) AS DATE_ID,
    DATE,
    MAX(ISHOLIDAY) AS ISHOLIDAY
  FROM (
    SELECT DATE, ISHOLIDAY FROM RAW.DEPARTMENT
    UNION ALL
    SELECT DATE, ISHOLIDAY FROM RAW.FACT
  )
  GROUP BY DATE
) S
ON T.DATE_ID = S.DATE_ID
WHEN MATCHED AND (T.ISHOLIDAY IS DISTINCT FROM S.ISHOLIDAY) THEN
  UPDATE SET T.ISHOLIDAY = S.ISHOLIDAY, T.UPDATE_DATE = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (DATE_ID, DATE, ISHOLIDAY, INSERT_DATE, UPDATE_DATE)
  VALUES (S.DATE_ID, S.DATE, S.ISHOLIDAY, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());

----------------------------------------------------------------------------------------------
-- 2. WALMART_STORE_DIM — SCD Type 2, per requirements doc
--    Grain: (Store_id, Dept_id). stores.csv has no Dept column, so the Store-Dept combinations
--    come from department.csv, joined to stores.csv for Type/Size (see brief section 4).
----------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS WALMART_STORE_DIM (
  STORE_DIM_KEY   NUMBER AUTOINCREMENT PRIMARY KEY,  -- surrogate key, used by the fact table
  STORE_ID        NUMBER,
  DEPT_ID         NUMBER,
  STORE_TYPE      VARCHAR(1),
  STORE_SIZE      NUMBER,
  INSERT_DATE     TIMESTAMP_NTZ,
  UPDATE_DATE     TIMESTAMP_NTZ,
  VRSN_START_DATE TIMESTAMP_NTZ,
  VRSN_END_DATE   TIMESTAMP_NTZ,
  IS_CURRENT      BOOLEAN
);

CREATE OR REPLACE TEMPORARY TABLE STORE_DIM_SRC AS
SELECT DISTINCT
  D.STORE AS STORE_ID,
  D.DEPT  AS DEPT_ID,
  S.TYPE  AS STORE_TYPE,
  S.SIZE  AS STORE_SIZE
FROM RAW.DEPARTMENT D
JOIN RAW.STORES S ON D.STORE = S.STORE;

-- Step 1: expire current versions whose attributes changed
UPDATE WALMART_STORE_DIM T
SET VRSN_END_DATE = CURRENT_TIMESTAMP(),
    IS_CURRENT = FALSE,
    UPDATE_DATE = CURRENT_TIMESTAMP()
FROM STORE_DIM_SRC S
WHERE T.STORE_ID = S.STORE_ID
  AND T.DEPT_ID = S.DEPT_ID
  AND T.IS_CURRENT = TRUE
  AND (T.STORE_TYPE IS DISTINCT FROM S.STORE_TYPE OR T.STORE_SIZE IS DISTINCT FROM S.STORE_SIZE);

-- Step 2: insert brand-new keys and new versions of changed keys (the changed ones no longer
-- have an IS_CURRENT=TRUE row after step 1, so this single INSERT covers both cases)
INSERT INTO WALMART_STORE_DIM
  (STORE_ID, DEPT_ID, STORE_TYPE, STORE_SIZE, INSERT_DATE, UPDATE_DATE, VRSN_START_DATE, VRSN_END_DATE, IS_CURRENT)
SELECT
  S.STORE_ID, S.DEPT_ID, S.STORE_TYPE, S.STORE_SIZE,
  CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(), '9999-12-31'::TIMESTAMP_NTZ, TRUE
FROM STORE_DIM_SRC S
LEFT JOIN WALMART_STORE_DIM T
  ON T.STORE_ID = S.STORE_ID AND T.DEPT_ID = S.DEPT_ID AND T.IS_CURRENT = TRUE
WHERE T.STORE_ID IS NULL;

----------------------------------------------------------------------------------------------
-- 3. WALMART_FACT_TABLE  --  grain: one row per (Store_id, Dept_id, Date_id)
--
--    Holds ONLY department-grain measures (weekly sales). Store-level measures such as
--    markdowns, fuel price, temperature, CPI and unemployment are recorded once per
--    store per week, so they do NOT belong on this table: copying them onto every
--    department row repeats each value ~65x, and any SUM() over them overstates the
--    total (the original version of this table did exactly that: markdowns were
--    overstated ~57x on the dashboard). They live in WALMART_STORE_CONDITIONS_FACT below.
--
--    NOTE on the SCD2 join: a true point-in-time join would match each fact row to the store_dim
--    version effective on that row's Date. This dataset only has one snapshot of stores.csv
--    (no historical Type/Size), so every row's Date predates today's VRSN_START_DATE (set at
--    load time) -- a date-range join would match nothing. We join on IS_CURRENT = TRUE instead,
--    which is correct for this one-time historical load. If you later run incremental loads
--    where store_dim actually accumulates dated versions, switch this to a
--    "Date BETWEEN VRSN_START_DATE AND VRSN_END_DATE" join.
----------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE WALMART_FACT_TABLE (
  STORE_ID            NUMBER,
  DEPT_ID             NUMBER,
  DATE_ID             NUMBER,
  STORE_DIM_KEY       NUMBER,
  STORE_WEEKLY_SALES  FLOAT,
  VRSN_START_DATE     TIMESTAMP_NTZ,
  VRSN_END_DATE       TIMESTAMP_NTZ,
  INSERT_DATE         TIMESTAMP_NTZ,
  UPDATE_DATE         TIMESTAMP_NTZ
);

INSERT INTO WALMART_FACT_TABLE
SELECT
  D.STORE AS STORE_ID,
  D.DEPT AS DEPT_ID,
  TO_NUMBER(TO_CHAR(D.DATE, 'YYYYMMDD')) AS DATE_ID,
  SD.STORE_DIM_KEY,
  D.WEEKLY_SALES AS STORE_WEEKLY_SALES,
  SD.VRSN_START_DATE,
  SD.VRSN_END_DATE,
  CURRENT_TIMESTAMP() AS INSERT_DATE,
  CURRENT_TIMESTAMP() AS UPDATE_DATE
FROM RAW.DEPARTMENT D
LEFT JOIN WALMART_STORE_DIM SD
  ON SD.STORE_ID = D.STORE AND SD.DEPT_ID = D.DEPT AND SD.IS_CURRENT = TRUE;

-- Expect 421,570 rows (matches department.csv row count 1:1)
SELECT COUNT(*) FROM WALMART_FACT_TABLE;

----------------------------------------------------------------------------------------------
-- 4. WALMART_STORE_CONDITIONS_FACT  --  grain: one row per (Store_id, Date_id)
--    Store-level measures from fact.csv, loaded 1:1 (no join to department rows, so nothing
--    can fan out). TOTAL_MARKDOWN treats a missing markdown as 0 on purpose: adding the five
--    columns with a plain "+" returns NULL if ANY one is NULL, which silently drops rows from
--    the total (about 18% of the markdown dollars in this dataset).
----------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE WALMART_STORE_CONDITIONS_FACT (
  STORE_ID           NUMBER,
  DATE_ID            NUMBER,
  STORE_TEMPERATURE  FLOAT,
  FUEL_PRICE         FLOAT,
  CPI                FLOAT,
  UNEMPLOYMENT       FLOAT,
  MARKDOWN1          FLOAT,
  MARKDOWN2          FLOAT,
  MARKDOWN3          FLOAT,
  MARKDOWN4          FLOAT,
  MARKDOWN5          FLOAT,
  TOTAL_MARKDOWN     FLOAT,
  INSERT_DATE        TIMESTAMP_NTZ,
  UPDATE_DATE        TIMESTAMP_NTZ
);

INSERT INTO WALMART_STORE_CONDITIONS_FACT
SELECT
  F.STORE AS STORE_ID,
  TO_NUMBER(TO_CHAR(F.DATE, 'YYYYMMDD')) AS DATE_ID,
  F.TEMPERATURE, F.FUEL_PRICE, F.CPI, F.UNEMPLOYMENT,
  F.MARKDOWN1, F.MARKDOWN2, F.MARKDOWN3, F.MARKDOWN4, F.MARKDOWN5,
  COALESCE(F.MARKDOWN1,0) + COALESCE(F.MARKDOWN2,0) + COALESCE(F.MARKDOWN3,0)
    + COALESCE(F.MARKDOWN4,0) + COALESCE(F.MARKDOWN5,0) AS TOTAL_MARKDOWN,
  CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
FROM RAW.FACT F;

-- Expect 8,190 rows (matches fact.csv row count 1:1)
SELECT COUNT(*) FROM WALMART_STORE_CONDITIONS_FACT;
