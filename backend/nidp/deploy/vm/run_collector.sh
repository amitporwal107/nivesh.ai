#!/usr/bin/env bash
# run_collector.sh — wrapper for container_health_collector.py.
#
# Sources the NIDP env file (for NIDP_POSTGRES_URL) and execs the collector.
# Designed to be called from cron so no credentials are embedded in crontab.
#
# Usage (prod):
#   /opt/nidp/repo/backend/nidp/deploy/vm/run_collector.sh
#
# Usage (staging, nidp-staging must be in docker group):
#   NIDP_HOME=/opt/nidp-staging \
#   PYTHON=/opt/nidp-staging/venv/bin/python \
#   SCRIPT=/opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/container_health_collector.py \
#     /opt/nidp/dev-repo/nivesh.ai/backend/nidp/deploy/vm/run_collector.sh

set -uo pipefail

NIDP_HOME="${NIDP_HOME:-/opt/nidp}"
PYTHON="${PYTHON:-$NIDP_HOME/venv/bin/python}"
SCRIPT="${SCRIPT:-/opt/nidp/repo/backend/nidp/deploy/vm/container_health_collector.py}"

# Source the env file for NIDP_POSTGRES_URL and friends
# shellcheck disable=SC1091
set -a
source "$NIDP_HOME/nidp.env"
set +a

exec "$PYTHON" "$SCRIPT"
