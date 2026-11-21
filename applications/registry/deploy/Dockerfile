# syntax=docker/dockerfile:1.7
#
# The Nest registry (registry.nest-framework.org) as one image, built from Nest's repository:
#
#   docker build -f applications/registry/deploy/Dockerfile -t nest-registry .
#
# The workspace's uv.lock fixes every version; the packages are installed as packages (not
# editable), so the image holds no source tree to drift from. It runs `nest serve` (gunicorn's
# master and its workers) after `nest db upgrade`, on port 8000; its data (the SQLite database,
# the uploaded files, the settings) is in /data: mount a volume there. With PostgreSQL and
# S3/MinIO chosen in the environment (registry.env.example), /data keeps only the settings.

ARG PYTHON=3.13

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:${PYTHON}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src/nest
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:${PYTHON}-slim
RUN groupadd --system --gid 10001 nest \
 && useradd --system --uid 10001 --gid nest --home-dir /data --no-create-home nest \
 && mkdir -p /data && chown nest:nest /data
COPY --from=build /src/nest/.venv /src/nest/.venv
COPY --from=build /src/nest/applications/registry /src/nest/applications/registry
COPY --chmod=0755 deploy/entrypoint.sh /usr/local/bin/nest-entrypoint
ENV PATH=/src/nest/.venv/bin:$PATH \
    NEST_APP=/src/nest/applications/registry \
    NEST_APP_WORKSPACE=/data \
    NEST_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER nest
WORKDIR /src/nest/applications/registry
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"
ENTRYPOINT ["nest-entrypoint"]
CMD ["serve"]
