#!/usr/bin/env bash
# Called by the API artifact build from the workspace root.
set -euo pipefail
cd "$(dirname "$0")/.."
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt --output-file .bot-requirements.txt > /dev/null
# Do not rely on development .pythonlibs (excluded from deployment images).
# Use locked wheels in a dedicated directory, not a virtual environment.
uv pip sync --target .bot-runtime --require-hashes .bot-requirements.txt
pnpm --filter @workspace/api-server run build
python scripts/supervise_services.py --check
