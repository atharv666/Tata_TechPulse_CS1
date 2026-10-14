FROM python:3.11-slim

WORKDIR /service

COPY backend /service/backend
COPY worker /service/worker

RUN pip install --no-cache-dir -r /service/backend/requirements.txt

# The shared application package lives in backend/; the worker entry point lives in worker/.
# Both directories must be importable from the container's working directory.
ENV PYTHONPATH=/service/backend:/service/worker \
    PYTHONUNBUFFERED=1

# Fail the image build (not the first container start) if the entry point cannot be imported.
RUN python -c "import worker_runner.main"

CMD ["python", "-m", "worker_runner.main"]
