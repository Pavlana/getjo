#!/bin/sh
# Scheduled entry point (launchd): load env vars from .env, then run the radar once.
# launchd starts with an empty environment and no shell profile, so everything is explicit here.
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
exec .venv/bin/python -m jobs.radar
