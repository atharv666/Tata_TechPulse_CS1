FROM python:3.11-slim

WORKDIR /service

COPY backend /service/backend
COPY worker /service/worker

RUN pip install --no-cache-dir -r /service/backend/requirements.txt

ENV PYTHONPATH=/service/backend

CMD ["python", "-m", "worker_runner.main"]
