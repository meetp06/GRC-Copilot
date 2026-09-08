#!/usr/bin/env bash
# Take the deployment down to nothing.
#
# TF_VAR_api_key is required to destroy as well as to apply: the variable has no
# default, so OpenTofu cannot even build a plan without it.
#
# Two permissions in docs/aws/deploy-policy.json exist only for this direction
# and were missing the first time it ran -- s3:DeleteObjectVersion and
# iam:ListInstanceProfilesForRole. See MISTAKES.md 49.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AWS_PROFILE="${AWS_PROFILE:-grc-copilot}"
export TF_VAR_api_key="$(grep '^GRC_API_KEY=' .env 2>/dev/null | cut -d= -f2- || echo unused-for-destroy)"

tofu -chdir=infra destroy -auto-approve

REMAINING="$(tofu -chdir=infra state list | wc -l | tr -d ' ')"
if [[ "$REMAINING" != "0" ]]; then
  echo "WARNING: $REMAINING resources still in state -- destroy did not finish" >&2
  tofu -chdir=infra state list >&2
  exit 1
fi

cat <<'EOF'

down. 0 resources.

The two KMS keys are in PendingDeletion for 7 days -- AWS's minimum -- and bill
$1/month each until then. Everything else stopped costing immediately.

  aws kms describe-key --key-id <id> --query KeyMetadata.DeletionDate
EOF
