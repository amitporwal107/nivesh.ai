# BSE-only thin shim around the shared corporate_announcements package.
# See corporate_announcements_nse/Dockerfile for the pattern rationale.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NIDP_METRICS_PORT=9116

WORKDIR /app

COPY backend/nidp/deploy/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY backend/nidp /app/nidp

ENV PYTHONPATH=/app

EXPOSE 9116

ENTRYPOINT ["python", "-m", "nidp.services.corporate_announcements", "--source", "bse", "--metrics"]
