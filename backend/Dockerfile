# Build context is the repository root (so agents/ and prompts/ can be included later).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY backend/pyproject.toml backend/pyproject.toml
RUN pip install --no-cache-dir -e ./backend

COPY backend/ backend/
COPY agents/ agents/

ENV PYTHONPATH=/srv/backend:/srv
WORKDIR /srv/backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
