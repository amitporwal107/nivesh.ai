# NSE-only thin shim around the shared corporate_announcements package.
# Two Cloud Run jobs (nse + bse) share the same Python code; the source
# is pinned at the ENTRYPOINT so Cloud Scheduler can fire each job
# independently without needing to pass arguments.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NIDP_METRICS_PORT=9115

WORKDIR /app

COPY backend/nidp/deploy/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY backend/nidp /app/nidp

ENV PYTHONPATH=/app

EXPOSE 9115

ENTRYPOINT ["python", "-m", "nidp.services.corporate_announcements", "--source", "nse", "--metrics"]
