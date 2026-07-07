"""disk_monitor — off-DB disk-space alarm for the NIDP VM(s).

Reads free space with shutil.disk_usage and alerts via nidp.shared.notify, with
NO database dependency — so it works exactly when the disk-full → Postgres-down
outage is happening. See service.py.
"""
