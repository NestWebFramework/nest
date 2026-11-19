#!/bin/sh
# The container's entry: migrate, then serve; or run any nest command against the app.
#   serve            nest db upgrade, then nest serve: gunicorn's master and its workers
#                    (NEST_WORKERS, NEST_THREADS, NEST_TIMEOUT, NEST_MAX_REQUESTS; the
#                    application's serve: section gives the rest)
#   nest ARGS...     a nest command (nest check /src/app, nest backup /src/app ...)
#   anything else    run as given
set -eu
APP=/src/app
case "${1:-serve}" in
  serve)
    nest db upgrade "$APP"
    exec nest serve "$APP" --host 0.0.0.0 --port "${PORT:-8000}"
    ;;
  nest) shift; exec nest "$@" ;;
  *) exec "$@" ;;
esac
