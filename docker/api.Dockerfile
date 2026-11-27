# syntax=docker/dockerfile:1
FROM python:3.15-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS build
COPY pyproject.toml README.md ./
COPY shared ./shared
COPY engine ./engine
COPY modules ./modules
COPY integrations ./integrations
COPY workers ./workers
COPY apps/api ./apps/api
RUN pip install --prefix=/install ".[ai]"

FROM base AS runtime
RUN groupadd --system atlas && useradd --system --gid atlas --home /app --shell /usr/sbin/nologin atlas
COPY --from=build /install /usr/local
COPY --chown=atlas:atlas shared ./shared
COPY --chown=atlas:atlas engine ./engine
COPY --chown=atlas:atlas modules ./modules
COPY --chown=atlas:atlas integrations ./integrations
COPY --chown=atlas:atlas workers ./workers
COPY --chown=atlas:atlas apps/api ./apps/api
ENV PYTHONPATH=/app:/app/apps/api
USER atlas
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["uvicorn", "atlas_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
