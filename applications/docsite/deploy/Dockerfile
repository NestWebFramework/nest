# syntax=docker/dockerfile:1.7
#
# nest-framework.org (the docsite) as one image, built from Nest's repository:
#
#   docker build -f applications/docsite/deploy/Dockerfile -t nest-docsite .
#
# It carries Nest's packages (all of them: the reference pages are made from every
# installed package's manifest), the docsite application and the documentation (docs/):
# the documentation an image serves is the documentation of the code it was built from.
# Its workspace (/data: the search index, the SEO fields, the settings) is mounted from the
# host, as every Nest site's: `nest-site` runs it (deploy/site.conf.example).

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
# the commits this image is built from (nest-images gives them): shown in every footer
ARG NEST_REVISION=""
ENV NEST_REVISION=${NEST_REVISION}
RUN groupadd --system --gid 10001 nest \
 && useradd --system --uid 10001 --gid nest --home-dir /data --no-create-home nest \
 && mkdir -p /data && chown nest:nest /data
COPY --from=build /src/nest/.venv /src/nest/.venv
COPY --from=build /src/nest/applications/docsite /src/nest/applications/docsite
COPY --from=build /src/nest/docs /src/nest/docs
COPY --chmod=0755 deploy/entrypoint.sh /usr/local/bin/nest-entrypoint
ENV PATH=/src/nest/.venv/bin:$PATH \
    NEST_APP=/src/nest/applications/docsite \
    NEST_APP_WORKSPACE=/data \
    NEST_ENV=production \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER nest
WORKDIR /src/nest/applications/docsite
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"
ENTRYPOINT ["nest-entrypoint"]
CMD ["serve"]
