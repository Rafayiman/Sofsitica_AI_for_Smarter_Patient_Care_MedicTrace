FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
COPY eval/ /eval/
RUN python -m app.ingest.run_ingest --csv-dir demo_data/mimic-iv-clinical-database-demo-2.2
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
