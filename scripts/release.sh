#!/usr/bin/env bash
# scripts/release.sh — build sdist+wheel and upload to pypi.
# Prereqs: `pip install build twine` and PYPI_API_TOKEN env var.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ cleaning dist/"
rm -rf dist build ./*.egg-info

echo "→ running tests"
pytest -q

echo "→ running lint"
ruff check sense_use tests

echo "→ building sdist + wheel"
python -m build

echo "→ built artifacts:"
ls -lh dist/

echo "→ uploading to pypi"
if [ -z "${PYPI_API_TOKEN:-}" ]; then
  echo "  set PYPI_API_TOKEN to publish. Skipping upload."
  exit 0
fi
python -m twine upload -u __token__ -p "$PYPI_API_TOKEN" dist/*

echo "✅ done"
