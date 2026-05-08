FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8081

WORKDIR /app

COPY backend/nidp/deploy/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY backend/nidp /app/nidp

ENV PYTHONPATH=/app

EXPOSE 8081

ENTRYPOINT ["python", "-m", "nidp.services.daas_api"]
