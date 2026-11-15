FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
# One worker: research jobs are tracked in memory. Threads handle concurrency.
CMD gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:$PORT finn.app:app
