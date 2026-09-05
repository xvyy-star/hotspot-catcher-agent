FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple

COPY backend/requirements.txt /app/backend/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --index-url "$PIP_INDEX_URL" --retries 10 --timeout 120 -r /app/backend/requirements.txt

COPY backend /app/backend
COPY config /app/config
COPY migrations /app/migrations
COPY scripts/prepare_database.py /app/scripts/prepare_database.py
COPY alembic.ini /app/alembic.ini
COPY LICENSE THIRD_PARTY_NOTICES.md /app/

EXPOSE 8000

CMD ["sh", "-c", "python scripts/prepare_database.py && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir backend"]
