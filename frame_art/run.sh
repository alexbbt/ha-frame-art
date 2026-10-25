#!/usr/bin/with-contenv bashio
# shellcheck shell=bash
set -euo pipefail

export FRAME_ART_INBOX
FRAME_ART_INBOX="$(bashio::config 'inbox')"
export FRAME_ART_UPLOADED
FRAME_ART_UPLOADED="$(bashio::config 'uploaded')"
export PORT="${INGRESS_PORT:-8391}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="/opt/frame_art"

bashio::log.info "Frame Art listening on ${PORT}"
cd /opt/frame_art
exec python3 -m frame_art
