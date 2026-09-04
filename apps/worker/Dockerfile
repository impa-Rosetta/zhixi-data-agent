FROM python:3.12.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY apps ./apps
COPY packages ./packages
RUN pip install --no-cache-dir .
CMD ["celery", "-A", "apps.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h"]

