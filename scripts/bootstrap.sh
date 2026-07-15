#!/usr/bin/env sh
set -eu

expected_uv_version="uv 0.11.28"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install uv 0.11.28, then rerun this script." >&2
  exit 1
fi

actual_uv_version="$(uv --version)"
if [ "$actual_uv_version" != "$expected_uv_version" ]; then
  echo "Expected $expected_uv_version but found $actual_uv_version." >&2
  exit 1
fi

uv sync --frozen
