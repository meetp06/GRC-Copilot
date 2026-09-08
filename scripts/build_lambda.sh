#!/usr/bin/env bash
# Build the Lambda deployment package.
#
#   requirements ─▶ pip install (linux wheels) ─▶ trim ─▶ build/lambda/
#
# Only the request path. dagster, pdfplumber and mcp are ingestion and developer
# tooling: measured at 79 MB with them excluded against 111 MB with them, and
# Lambda's limit is 250 MB unzipped. Excluding them is also the right
# architecture -- the ingestion pipeline has no business in a request path.
#
# --platform manylinux2014_x86_64 matters: numpy and pydantic-core ship compiled
# wheels, and a macOS wheel installed into a Lambda package fails at import with
# an error that does not mention the platform.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/lambda"

rm -rf "$BUILD"
mkdir -p "$BUILD"

echo "installing request-path dependencies for linux/x86_64..."
grep -vE '^(dagster|dagster-webserver|pdfplumber|mcp|pytest|pre-commit|ruff)' \
  "$ROOT/requirements.txt" | grep -vE '^\s*#|^\s*$' > /tmp/lambda-requirements.txt
echo "mangum>=0.19.0" >> /tmp/lambda-requirements.txt

pip install \
  --target "$BUILD" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  --upgrade \
  -r /tmp/lambda-requirements.txt >/dev/null

echo "copying source..."
mkdir -p "$BUILD/src"
for pkg in api graph rag ontology aws agent; do
  cp -R "$ROOT/src/$pkg" "$BUILD/src/"
done
cp "$ROOT/src/__init__.py" "$BUILD/src/"
cp "$BUILD/src/api/lambda_handler.py" "$BUILD/lambda_handler.py"

echo "trimming..."
# boto3 and botocore are already in the Lambda runtime. Shipping them again
# costs ~23 MB of package for an identical library.
rm -rf "$BUILD"/boto3* "$BUILD"/botocore*
# Test suites, type stubs and compiled caches inside installed packages.
find "$BUILD" -type d \( -name tests -o -name test -o -name __pycache__ \) -prune -exec rm -rf {} + 2>/dev/null || true
find "$BUILD" -type f \( -name '*.pyc' -o -name '*.pyi' -o -name '*.md' \) -delete 2>/dev/null || true
rm -rf "$BUILD"/*.dist-info/RECORD

SIZE=$(du -sm "$BUILD" | cut -f1)
echo "package: ${SIZE} MB unzipped (Lambda limit 250 MB)"
if [ "$SIZE" -gt 240 ]; then
  echo "too close to the limit -- move something to a layer or a container image" >&2
  exit 1
fi
