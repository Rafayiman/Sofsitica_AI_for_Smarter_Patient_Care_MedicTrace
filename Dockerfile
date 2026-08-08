FROM python:3.13-slim
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
