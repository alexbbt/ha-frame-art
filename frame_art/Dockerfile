ARG BUILD_FROM=ghcr.io/home-assistant/base:3.21
# hadolint ignore=DL3006
FROM ${BUILD_FROM}

# Unpinned so the base image's Alpine release stays the source of truth.
# hadolint ignore=DL3018
RUN apk add --no-cache \
    python3 \
    libheif-tools

WORKDIR /opt/frame_art

COPY config.yaml /opt/frame_art/config.yaml
COPY frame_art /opt/frame_art/frame_art
COPY run.sh /run.sh

RUN chmod a+x /run.sh

ARG BUILD_ARCH
ARG BUILD_DATE
ARG BUILD_DESCRIPTION
ARG BUILD_NAME
ARG BUILD_REF
ARG BUILD_REPOSITORY
ARG BUILD_VERSION

ENV ADDON_VERSION=${BUILD_VERSION}

LABEL \
  io.hass.name="${BUILD_NAME}" \
  io.hass.description="${BUILD_DESCRIPTION}" \
  io.hass.arch="${BUILD_ARCH}" \
  io.hass.type="app" \
  io.hass.version="${BUILD_VERSION}" \
  org.opencontainers.image.title="${BUILD_NAME}" \
  org.opencontainers.image.description="${BUILD_DESCRIPTION}" \
  org.opencontainers.image.source="https://github.com/${BUILD_REPOSITORY}" \
  org.opencontainers.image.documentation="https://github.com/${BUILD_REPOSITORY}/blob/main/README.md" \
  org.opencontainers.image.revision="${BUILD_REF}" \
  org.opencontainers.image.version="${BUILD_VERSION}" \
  org.opencontainers.image.created="${BUILD_DATE}" \
  org.opencontainers.image.licenses="MIT"

CMD ["/run.sh"]
