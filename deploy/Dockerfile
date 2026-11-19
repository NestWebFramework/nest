# syntax=docker/dockerfile:1.7
#
# One image for any Nest application that lives in its own repository beside Nest.
# Built from the application's folder, with Nest given as a second context:
#
#   docker build -f ../nest/deploy/Dockerfile --build-context nest=../nest -t morlaca .
#
# (an application's deploy/compose.yml does the same). The application's uv.lock fixes
# every version; Nest's packages are installed from /src/nest, where its pyproject's
# path sources (../nest) point. The workspace is /data: mount a volume there.

ARG PYTHON=3.13

FROM ghcr.io/astral-sh/uv:0.13.8 AS uv

FROM python:${PYTHON}-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=nest . /src/nest
COPY . /src/app
WORKDIR /src/app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:${PYTHON}-slim
RUN groupadd --system --gid 10001 nest \
 && useradd --system --uid 10001 --gid nest --home-dir /data --no-create-home nest \
 && mkdir -p /data && chown nest:nest /data
COPY --from=build --chown=root:root /src /src
COPY --chmod=0755 --from=nest deploy/entrypoint.sh /usr/local/bin/nest-entrypoint
ENV PATH=/src/app/.venv/bin:$PATH \
    NEST_APP_WORKSPACE=/data \
    NEST_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER nest
WORKDIR /src/app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"
ENTRYPOINT ["nest-entrypoint"]
CMD ["serve"]
