"""
Walmart End-to-End -- Sales Dashboard
Snowpark + Streamlit app covering the 10 required reports from the project brief.

Uses Streamlit's built-in chart functions (bar_chart/line_chart/scatter_chart) rather
than Plotly, so it runs with zero extra package installs -- no External Access
Integration needed in Streamlit-in-Snowflake.

Deploy natively in Snowsight (Streamlit apps/Workspaces) using this file, or run locally
for development:

    pip install streamlit snowflake-snowpark-python pandas
    streamlit run streamlit_app.py

Local runs read connection params from .streamlit/secrets.toml (see README_deploy.md).
"""

import streamlit as st
from snowflake.snowpark import Session
from snowflake.snowpark.context import get_active_session
from snowflake.snowpark.functions import col, month, year, sum as sf_sum

st.set_page_config(page_title="Walmart End-to-End Dashboard", layout="wide")


@st.cache_resource
def get_session() -> Session:
    """Native Streamlit-in-Snowflake provides an active session for free. When running
    locally (`streamlit run`), fall back to building one from .streamlit/secrets.toml."""
    try:
        return get_active_session()
    except Exception:
        return Session.builder.configs(st.secrets["snowflake"]).create()


session = get_session()
FACT = "WALMART_E2E.CORE.WALMART_FACT_TABLE"
DATE_DIM = "WALMART_E2E.CORE.WALMART_DATE_DIM"
STORE_DIM = "WALMART_E2E.CORE.WALMART_STORE_DIM"


@st.cache_resource
def base_df():
    """Joined fact + both dimensions. Stays as a lazy Snowpark DataFrame -- nothing is
    pulled into pandas until a chart aggregates and calls .to_pandas().

    WALMART_FACT_TABLE and WALMART_STORE_DIM both have their own DEPT_ID and STORE_SIZE
    columns. Snowpark can raise SnowparkSQLAmbiguousJoinException on later chained
    operations (group_by/sort by name) if those overlapping columns are still present
    anywhere in the join lineage -- even after an explicit .select(). Trimming each
    source to only the columns it uniquely contributes, before joining, avoids that:
    the join keys (DATE_ID, STORE_DIM_KEY) are merged via the string-name join form
    (which de-duplicates them), and there are no other name collisions left."""
    fact = session.table(FACT).select(
        "STORE_ID", "DEPT_ID", "DATE_ID", "STORE_DIM_KEY",
        "STORE_WEEKLY_SALES", "FUEL_PRICE", "STORE_TEMPERATURE",
        "CPI", "UNEMPLOYMENT",
        "MARKDOWN1", "MARKDOWN2", "MARKDOWN3", "MARKDOWN4", "MARKDOWN5",
    )
    dd = session.table(DATE_DIM).select("DATE_ID", "DATE", "ISHOLIDAY")
    sd = (
        session.table(STORE_DIM)
        .filter(col("IS_CURRENT"))
        .select("STORE_DIM_KEY", "STORE_TYPE", "STORE_SIZE")
    )
    joined = fact.join(dd, "DATE_ID", "left").join(sd, "STORE_DIM_KEY", "left")
    return joined.select(
        col("STORE_ID"),
        col("DEPT_ID"),
        col("DATE"),
        year(col("DATE")).alias("YEAR"),
        month(col("DATE")).alias("MONTH"),
        col("ISHOLIDAY"),
        col("STORE_TYPE"),
        col("STORE_SIZE"),
        col("STORE_WEEKLY_SALES"),
        col("FUEL_PRICE"),
        col("STORE_TEMPERATURE"),
        col("CPI"),
        col("UNEMPLOYMENT"),
        col("MARKDOWN1"),
        col("MARKDOWN2"),
        col("MARKDOWN3"),
        col("MARKDOWN4"),
        col("MARKDOWN5"),
    )


bdf = base_df()

# ---------------------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------------------
st.sidebar.header("Filters")

years = [r["YEAR"] for r in bdf.select("YEAR").distinct().sort("YEAR").collect()]
types = [r["STORE_TYPE"] for r in bdf.select("STORE_TYPE").distinct().sort("STORE_TYPE").collect()]

sel_years = st.sidebar.multiselect("Year", years, default=years)
sel_types = st.sidebar.multiselect("Store Type", types, default=types)

fdf = bdf.filter(col("YEAR").in_(sel_years) & col("STORE_TYPE").in_(sel_types))

st.title("Walmart End-to-End -- Sales Dashboard")
st.caption("Source: Walmart_fact_table joined to Walmart_date_dim and Walmart_store_dim")

kpi = fdf.select(sf_sum("STORE_WEEKLY_SALES").alias("TOTAL_SALES")).to_pandas()
total_sales = kpi["TOTAL_SALES"].iloc[0] if not kpi.empty and kpi["TOTAL_SALES"].iloc[0] else 0
st.metric("Total Weekly Sales (filtered)", f"${total_sales:,.0f}")

tab_labels = [
    "1. Dept-wise sales",
    "2. Sales by year/month/date",
    "3. Sales by CPI",
    "4. Markdown by year & store",
    "5. Sales by store type & month",
    "6. Sales by store size",
    "7. Sales by store & holiday",
    "8. Sales by temperature & year",
    "9. Sales by store type",
    "10. Fuel price by year",
]
tabs = st.tabs(tab_labels)

# 1. Department-wise weekly sales -----------------------------------------------------
with tabs[0]:
    st.subheader("Top 20 Departments by Weekly Sales")
    df = (
        fdf.group_by("DEPT_ID")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .sort(col("WEEKLY_SALES").desc())
        .limit(20)
        .to_pandas()
    )
    df["DEPT_ID"] = df["DEPT_ID"].astype(str)
    st.bar_chart(df, x="DEPT_ID", y="WEEKLY_SALES")

# 2. Weekly sales by year, month, and date ---------------------------------------------
with tabs[1]:
    st.subheader("Weekly Sales Over Time")
    df = (
        fdf.group_by("DATE")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .sort("DATE")
        .to_pandas()
    )
    st.line_chart(df, x="DATE", y="WEEKLY_SALES")

    st.subheader("Weekly Sales by Month and Year")
    df_month = (
        fdf.group_by("YEAR", "MONTH")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .sort("YEAR", "MONTH")
        .to_pandas()
    )
    df_month["YEAR"] = df_month["YEAR"].astype(str)
    pivot = df_month.pivot(index="MONTH", columns="YEAR", values="WEEKLY_SALES")
    st.bar_chart(pivot)

# 3. Weekly sales by CPI ----------------------------------------------------------------
with tabs[2]:
    st.subheader("Weekly Sales vs. CPI")
    sales_by_date = fdf.group_by("DATE").agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
    cpi_by_date = fdf.group_by("DATE").agg({"CPI": "avg"}).to_df("DATE", "AVG_CPI")
    df = sales_by_date.join(cpi_by_date, "DATE").to_pandas().sort_values("AVG_CPI")
    st.scatter_chart(df, x="AVG_CPI", y="WEEKLY_SALES")

# 4. Markdown sales by year and store ----------------------------------------------------
with tabs[3]:
    st.subheader("Markdown Sales by Year and Store (top 15 stores by total markdown)")
    md_expr = col("MARKDOWN1") + col("MARKDOWN2") + col("MARKDOWN3") + col("MARKDOWN4") + col("MARKDOWN5")
    df = (
        fdf.with_column("TOTAL_MARKDOWN", md_expr)
        .group_by("YEAR", "STORE_ID")
        .agg(sf_sum("TOTAL_MARKDOWN").alias("TOTAL_MARKDOWN"))
        .to_pandas()
    )
    df["YEAR"] = df["YEAR"].astype(str)
    top_stores = df.groupby("STORE_ID")["TOTAL_MARKDOWN"].sum().nlargest(15).index
    df = df[df["STORE_ID"].isin(top_stores)]
    df["STORE_ID"] = df["STORE_ID"].astype(str)
    pivot = df.pivot(index="STORE_ID", columns="YEAR", values="TOTAL_MARKDOWN")
    st.bar_chart(pivot)

# 5. Weekly sales by store type and month ------------------------------------------------
with tabs[4]:
    st.subheader("Weekly Sales by Store Type and Month")
    df = (
        fdf.group_by("STORE_TYPE", "MONTH")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .sort("MONTH")
        .to_pandas()
    )
    pivot = df.pivot(index="MONTH", columns="STORE_TYPE", values="WEEKLY_SALES")
    st.line_chart(pivot)

# 6. Weekly sales by store size -----------------------------------------------------------
with tabs[5]:
    st.subheader("Weekly Sales by Store Size")
    df = (
        fdf.group_by("STORE_ID", "STORE_SIZE")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .to_pandas()
    )
    st.scatter_chart(df, x="STORE_SIZE", y="WEEKLY_SALES")

# 7. Weekly sales by store and holiday -----------------------------------------------------
with tabs[6]:
    st.subheader("Weekly Sales by Store and Holiday")
    df = (
        fdf.group_by("STORE_ID", "ISHOLIDAY")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .to_pandas()
    )
    df["ISHOLIDAY"] = df["ISHOLIDAY"].map({True: "Holiday", False: "Non-Holiday"})
    df["STORE_ID"] = df["STORE_ID"].astype(str)
    pivot = df.pivot(index="STORE_ID", columns="ISHOLIDAY", values="WEEKLY_SALES")
    st.bar_chart(pivot)

# 8. Weekly sales by temperature and year --------------------------------------------------
with tabs[7]:
    st.subheader("Weekly Sales by Temperature and Year")
    sales_by_date = fdf.group_by("DATE", "YEAR").agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
    temp_by_date = fdf.group_by("DATE").agg({"STORE_TEMPERATURE": "avg"}).to_df("DATE", "AVG_TEMP")
    df = sales_by_date.join(temp_by_date, "DATE").to_pandas()
    df["YEAR"] = df["YEAR"].astype(str)
    st.scatter_chart(df, x="AVG_TEMP", y="WEEKLY_SALES", color="YEAR")

# 9. Weekly sales by store type --------------------------------------------------------------
with tabs[8]:
    st.subheader("Weekly Sales Share by Store Type")
    df = (
        fdf.group_by("STORE_TYPE")
        .agg(sf_sum("STORE_WEEKLY_SALES").alias("WEEKLY_SALES"))
        .sort("STORE_TYPE")
        .to_pandas()
    )
    st.bar_chart(df, x="STORE_TYPE", y="WEEKLY_SALES")
    df["SHARE_%"] = (df["WEEKLY_SALES"] / df["WEEKLY_SALES"].sum() * 100).round(1)
    st.dataframe(df, use_container_width=True, hide_index=True)

# 10. Fuel price by year -----------------------------------------------------------------------
with tabs[9]:
    st.subheader("Average Fuel Price by Year")
    df = fdf.group_by("YEAR").agg({"FUEL_PRICE": "avg"}).to_df("YEAR", "AVG_FUEL_PRICE").to_pandas()
    df["YEAR"] = df["YEAR"].astype(str)
    st.bar_chart(df, x="YEAR", y="AVG_FUEL_PRICE")
