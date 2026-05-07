# BSE-only thin shim around the shared corporate_announcements package.
# See corporate_announcements_nse/Dockerfile for the pattern rationale.
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/nidp /app/nidp
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "nidp.services.corporate_announcements", "--source", "bse"]
