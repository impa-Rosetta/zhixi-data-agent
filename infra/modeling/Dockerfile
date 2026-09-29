FROM python:3.12.10-slim@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ZHIXI_MODEL_EXECUTOR=isolated-v1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
COPY infra/modeling/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --no-deps -r requirements.txt \
    && pip check \
    && groupadd -g 10001 modeling \
    && useradd -u 10001 -g modeling --no-create-home modeling
COPY packages/__init__.py /app/packages/__init__.py
COPY packages/modeling /app/packages/modeling
USER 10001:10001
ENTRYPOINT ["python", "-m", "packages.modeling.executor"]
