"""Daily feed health check job.

Runs as a scheduled Cloud Run job. Queries nidp.job_log and reports
feeds that have NO recent COMPLETED runs.
"""
