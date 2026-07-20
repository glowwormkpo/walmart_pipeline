USE DATABASE WALMART_E2E;
USE WAREHOUSE WALMART_WH;

-- Row counts should match the profiled source files
SELECT 'RAW.DEPARTMENT' AS T, COUNT(*) AS N FROM RAW.DEPARTMENT      -- expect 421570
UNION ALL SELECT 'RAW.STORES', COUNT(*) FROM RAW.STORES              -- expect 45
UNION ALL SELECT 'RAW.FACT', COUNT(*) FROM RAW.FACT                  -- expect 8190
UNION ALL SELECT 'CORE.WALMART_DATE_DIM', COUNT(*) FROM CORE.WALMART_DATE_DIM      -- expect 182
UNION ALL SELECT 'CORE.WALMART_STORE_DIM (current)', COUNT(*) FROM CORE.WALMART_STORE_DIM WHERE IS_CURRENT   -- expect 3331
UNION ALL SELECT 'CORE.WALMART_FACT_TABLE', COUNT(*) FROM CORE.WALMART_FACT_TABLE;  -- expect 421570

-- Fact rows that failed to find a matching store_dim version (should be 0)
SELECT COUNT(*) AS UNMATCHED_STORE_DIM
FROM CORE.WALMART_FACT_TABLE
WHERE STORE_DIM_KEY IS NULL;

-- Fact rows with no matching fact.csv economic data (expected: some — fact.csv only has
-- 8,190 Store+Date combos vs. department.csv's finer Store+Dept+Date grain, so this is a
-- fan-out join, not a gap)
SELECT COUNT(*) AS ROWS_MISSING_ECONOMIC_DATA
FROM CORE.WALMART_FACT_TABLE
WHERE FUEL_PRICE IS NULL;

-- Quick top-line check: total weekly sales should be ~$6,737,218,987
SELECT ROUND(SUM(STORE_WEEKLY_SALES), 2) AS TOTAL_WEEKLY_SALES FROM CORE.WALMART_FACT_TABLE;
