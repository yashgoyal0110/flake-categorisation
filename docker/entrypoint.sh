#!/usr/bin/env bash
# Refresh in the background, serve in the foreground.
#
# No cron and no scheduler process. One loop in a subshell is enough for something that needs to
# run hourly, and it keeps the container to a single concern.
set -euo pipefail

DB="${FLAKE_DB:-/data/flakes.db}"
REPO="${FLAKE_REPO:-containers/podman}"
WORKFLOW="${FLAKE_WORKFLOW:-ci.yml}"
RUNS="${FLAKE_RUNS:-40}"
BACKEND="${FLAKE_BACKEND:-heuristic}"
INTERVAL="${FLAKE_INTERVAL:-3600}"

refresh() {
  if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "no GITHUB_TOKEN, loading sample data instead"
    flaketriage --db "$DB" demo
    return
  fi
  echo "refreshing from $REPO"
  flaketriage --db "$DB" ingest "$REPO" --workflow "$WORKFLOW" --runs "$RUNS" || \
    echo "ingest failed, keeping what is already stored"
  flaketriage --db "$DB" classify --backend "$BACKEND" || \
    echo "classify failed, flakes are stored and can be classified later"
}

refresh

(
  while true; do
    sleep "$INTERVAL"
    refresh
  done
) &

# 0.0.0.0 because this is inside a container. Put a reverse proxy in front of it: the dashboard is
# read-only but it has no authentication.
exec flaketriage --db "$DB" serve --host 0.0.0.0 --port 8000
