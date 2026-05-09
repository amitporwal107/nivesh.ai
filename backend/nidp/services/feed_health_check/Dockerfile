FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/nidp/deploy/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
COPY backend/nidp /app/nidp
ENV PYTHONPATH=/app

ENTRYPOINT ["python", "-m", "nidp.services.feed_health_check"]
