#!/bin/sh
# The container's entry: migrate, then serve; or run any nest command against the app.
#   serve            nest db upgrade, then nest run (the default)
#   nest ARGS...     a nest command (nest check /src/app, nest backup /src/app ...)
#   anything else    run as given
set -eu
APP=/src/app
case "${1:-serve}" in
  serve)
    nest db upgrade "$APP"
    exec nest run "$APP" --host 0.0.0.0 --port "${PORT:-8000}" \
      --workers "${NEST_WORKERS:-1}" --log-level "${NEST_LOG_LEVEL:-info}"
    ;;
  nest) shift; exec nest "$@" ;;
  *) exec "$@" ;;
esac
