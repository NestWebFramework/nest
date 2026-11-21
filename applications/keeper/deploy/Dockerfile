# syntax=docker/dockerfile:1.7
#
# The keeper (one person's, on a domain of theirs) as one image, built from Nest's repository:
#
#   docker build -f applications/keeper/deploy/Dockerfile -t nest-keeper .
#
# It carries Nest's packages (the keeper's Packages page lists them) and the keeper
# application. Its workspace (/data: the watched sites, their checks, the actions' log, its
# accounts and settings) is mounted from the host, as every Nest site's: `nest-site` runs
# it (deploy/site.conf.example). It reaches the sites at their public addresses, and the
# host helper (nest-host) at the Docker bridge's address.

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
COPY --from=build /src/nest/applications/keeper /src/nest/applications/keeper
COPY --chmod=0755 deploy/entrypoint.sh /usr/local/bin/nest-entrypoint
ENV PATH=/src/nest/.venv/bin:$PATH \
    NEST_APP=/src/nest/applications/keeper \
    NEST_APP_WORKSPACE=/data \
    NEST_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER nest
WORKDIR /src/nest/applications/keeper
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"
ENTRYPOINT ["nest-entrypoint"]
CMD ["serve"]
