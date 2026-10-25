#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

export FRAME_ART_HOST
FRAME_ART_HOST="$(bashio::config 'host')"
export FRAME_ART_PORT
FRAME_ART_PORT="$(bashio::config 'port')"
export FRAME_ART_TOKEN
FRAME_ART_TOKEN="$(bashio::config 'token')"
export FRAME_ART_MINUTES
FRAME_ART_MINUTES="$(bashio::config 'slideshow_minutes')"
export FRAME_ART_DATA="/data"
export PORT="${INGRESS_PORT:-8391}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="/opt/frame_art"

bashio::log.info "Frame Art listening on ${PORT}"
cd /opt/frame_art
exec python3 -m frame_art
