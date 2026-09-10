FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY app.py .

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
