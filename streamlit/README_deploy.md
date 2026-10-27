# Deploying the dashboard

## Option A — Streamlit in Snowflake via a Workspace (what this project actually uses)

Recent Snowsight creates a git-backed **Workspace** rather than a single-file app —
`snowflake.yml`, `pyproject.toml`, and `.streamlit/config.toml` in this folder are that
Workspace's project files, copied from what was actually deployed.

1. In Snowsight: **Projects → Streamlit → + Streamlit App** (this creates a Workspace
   with `snowflake.yml` / `pyproject.toml` / `streamlit_app.py`).
2. Add `query_warehouse: WALMART_WH` to `snowflake.yml` (see this repo's copy for the
   exact field) — the format doesn't set warehouse/database by itself.
3. Replace the generated `streamlit_app.py` with this repo's version (select all,
   delete, paste).
4. Leave `pyproject.toml`'s `dependencies` as just `["streamlit[snowflake]"]` — the app
   deliberately avoids Plotly and any other PyPI package so it never needs an External
   Access Integration. If you add a package that isn't part of that extra, Snowsight
   will try to fetch it from PyPI at deploy time and fail with a DNS/connection error
   unless an admin has configured an External Access Integration for outbound access.
5. Click **Deploy** (not just the split-screen **Run** preview — in testing, **Run**
   served a stale cached copy even after saving; **Deploy** picked up the changes).
   The deployed app opens in a new tab.

If your Snowsight account instead shows the older single-page "Streamlit App" editor
with a **Packages** panel (no separate Workspace/git files), the same file replacement
in step 3 still applies — just add packages via that panel instead of `pyproject.toml`.

## Option B — Run locally against your Snowflake account

```bash
pip install streamlit snowflake-snowpark-python pandas
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in your values
streamlit run streamlit_app.py
```

Either way, the app expects `WALMART_E2E.CORE.WALMART_FACT_TABLE`,
`WALMART_DATE_DIM`, and `WALMART_STORE_DIM` to already exist — run the `snowflake/`
scripts (01 through 05), or `scripts/load_pipeline.py`, first.
