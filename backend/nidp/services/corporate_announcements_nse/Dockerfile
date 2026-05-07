# NSE-only thin shim around the shared corporate_announcements package.
# Two Cloud Run jobs (nse + bse) share the same Python code; the source
# is pinned at the ENTRYPOINT so Cloud Scheduler can fire each job
# independently without needing to pass arguments.
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/nidp /app/nidp
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "nidp.services.corporate_announcements", "--source", "nse"]
