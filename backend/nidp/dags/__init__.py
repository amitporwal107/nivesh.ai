"""NIDP Airflow DAGs.

These DAGs are import-safe even without an Airflow install — the
`airflow` import is lazy. In a real Airflow deployment, mount this
directory into the dags/ folder of the Airflow scheduler.

DAG layout:
    nidp_market_eod          — bhavcopy + index_close + bulk + block (T+0 evening)
    nidp_delivery            — sec_bhavdata_full (T+1 morning)
    nidp_flows               — fii_dii (T+0 evening)
    nidp_corporate_actions   — CA + dividends (rolling, hourly)
    nidp_macro               — rbi_yields (daily evening)
    nidp_reference           — index_constituents + nse_calendar (weekly)
"""
