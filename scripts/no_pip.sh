#!/usr/bin/env bash
set -euo pipefail

# Fail if pip is used in docs/scripts/CI
if rg -n "pip install|python -m pip|pip3 install" .; then
  echo "❌ pip usage detected. Use uv sync / uv add / uv run instead."
  exit 1
fi

echo "✅ No pip usage detected."