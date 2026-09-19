FROM python:3.12.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
RUN mkdir apps packages && touch apps/__init__.py packages/__init__.py \
    && python -m pip install --no-cache-dir --upgrade "pip>=26.2" \
    && pip install --no-cache-dir .
RUN groupadd --system zhixi && useradd --system --gid zhixi --home-dir /app zhixi
COPY --chown=zhixi:zhixi apps ./apps
COPY --chown=zhixi:zhixi packages ./packages
USER zhixi
CMD ["celery", "-A", "apps.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h", "--concurrency=2"]