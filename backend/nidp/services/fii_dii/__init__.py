"""nidp-fii-dii — NSE FII/DII daily flows.

Source:    https://archives.nseindia.com/content/fo/fii_stats_{YYYYMMDD}.xls
Cadence:   Daily T+0 ~18:30 IST
Output:    nidp.fii_dii_flows  +  Kafka topic nidp.fii_dii.v1

NOTE: NSE serves an XLS (BIFF) file; depending on day they sometimes
ship XLSX or HTML. Parser auto-detects format and degrades to
NotImplementedError on layouts we haven't seen yet — failure is loud
rather than silent (PRD §14).
"""

# Side-effect: register validation rules
from . import validators  # noqa: F401
