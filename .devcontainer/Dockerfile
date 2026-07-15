# syntax=docker/dockerfile:1

FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN python -c "import sys; assert sys.version_info[:2] == (3, 11)" \
    && test "$(uv --version)" = "uv 0.11.28"
