FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt pypdf>=4.0 aiohttp>=3.9
COPY backend/nidp /app/nidp
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "nidp.services.document_parser"]
