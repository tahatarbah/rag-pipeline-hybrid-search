FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data/docs ./data/docs
COPY data/demo ./data/demo
COPY data/docs ./seed-docs
COPY data/demo ./seed-demo
COPY tests ./tests

EXPOSE 8765
VOLUME ["/app/data"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
