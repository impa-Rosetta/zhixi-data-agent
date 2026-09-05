FROM python:3.12.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY apps ./apps
COPY packages ./packages
RUN pip install --no-cache-dir .
RUN groupadd --system zhixi && useradd --system --gid zhixi --home-dir /app zhixi \
    && chown -R zhixi:zhixi /app
USER zhixi
CMD ["celery", "-A", "apps.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h", "--concurrency=2"]
