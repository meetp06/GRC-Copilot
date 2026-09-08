#!/usr/bin/env bash
# Bring the deployment up, from nothing to a working URL.
#
#   build package ─▶ tofu apply ─▶ upload index + ontology ─▶ smoke test
#
# Four steps rather than one because the index lives in S3, not in the Lambda
# package: rebuilding the corpus should not require redeploying the function.
# That is also why `down.sh` deletes it -- see the note there.
#
# Everything here is idempotent. Running it against a live stack rebuilds the
# package, applies no-op changes, re-uploads the index and re-checks health.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AWS_PROFILE="${AWS_PROFILE:-grc-copilot}"

# --- refuse to deploy an unauthenticated API --------------------------------
#
# `require_api_key` treats an unset key as "open", which is right for local
# development and catastrophic on a public URL. The API would come up, work
# perfectly, and be readable by anyone who found it. Fail here instead.
if [[ ! -f .env ]]; then
  echo "no .env -- refusing to deploy without an API key" >&2
  exit 1
fi

TF_VAR_api_key="$(grep '^GRC_API_KEY=' .env | cut -d= -f2- || true)"
if [[ -z "$TF_VAR_api_key" ]]; then
  echo "GRC_API_KEY is empty or missing from .env -- refusing to deploy an open API" >&2
  echo "generate one without printing it:" >&2
  echo "  python3 -c \"import secrets,pathlib,re; p=pathlib.Path('.env'); p.write_text(re.sub(r'^GRC_API_KEY=.*\$', 'GRC_API_KEY='+secrets.token_urlsafe(32), p.read_text(), flags=re.M))\"" >&2
  exit 1
fi
export TF_VAR_api_key

# --- 1. package -------------------------------------------------------------
echo "==> building the Lambda package"
bash scripts/build_lambda.sh

# --- 2. infrastructure ------------------------------------------------------
echo "==> applying infrastructure"
tofu -chdir=infra apply -auto-approve

BUCKET="$(tofu -chdir=infra output -raw documents_bucket)"
URL="$(tofu -chdir=infra output -raw api_url)"

# --- 3. index and ontology --------------------------------------------------
#
# --sse is required, not optional: the bucket policy denies any PutObject that
# is not aws:kms encrypted, so an upload without it fails with AccessDenied and
# nothing about the message says "encryption".
echo "==> uploading the index and ontology"
KMS="$(aws kms describe-key --key-id alias/grc-copilot-dev --query KeyMetadata.Arn --output text)"
for f in data/index/real.npy data/index/real.json; do
  aws s3 cp "$f" "s3://$BUCKET/index/" --sse aws:kms --sse-kms-key-id "$KMS"
done
aws s3 cp data/ontology/ontology.sqlite "s3://$BUCKET/ontology/" \
  --sse aws:kms --sse-kms-key-id "$KMS"

# --- 4. prove it ------------------------------------------------------------
#
# /health rather than a bare 200 on "/": it reports whether the index actually
# loaded, which is the thing step 3 can silently get wrong.
echo "==> smoke test"
curl -sf "${URL%/}/health" && echo

cat <<EOF

up.

  UI      ${URL%/}/ui
  docs    ${URL%/}/docs

Idle cost is roughly \$2.40/month, almost all of it two KMS keys.
Run scripts/down.sh when you are finished.
EOF
