FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

# Tools needed by Home Assistant, native Python dependencies, and local
# development helpers. Installing these at image-build time keeps attach
# operations fast and avoids requiring sudo from the setup script.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        automake \
        ffmpeg \
        libtool \
        libturbojpeg0 \
        nodejs \
        npm \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
