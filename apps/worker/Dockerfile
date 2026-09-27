FROM python:3.12.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 XDG_CACHE_HOME=/tmp/zhixi-cache
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::https::Timeout=30 install \
        -y --no-install-recommends fonts-noto-cjk libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN mkdir apps packages && touch apps/__init__.py packages/__init__.py \
    && python -m pip install --no-cache-dir --upgrade "pip>=26.2" \
    && pip install --no-cache-dir .
RUN groupadd --system zhixi && useradd --system --gid zhixi --home-dir /app zhixi
RUN mkdir -p /tmp/zhixi-cache && chown zhixi:zhixi /tmp/zhixi-cache && chmod 700 /tmp/zhixi-cache
COPY --chown=zhixi:zhixi apps ./apps
COPY --chown=zhixi:zhixi packages ./packages
COPY --chown=zhixi:zhixi evaluations ./evaluations
USER zhixi
CMD ["celery", "-A", "apps.worker.celery_app:celery_app", "worker", "--loglevel=INFO", "--hostname=worker@%h", "--concurrency=2"]
