# Deploying, and taking it down again

```
build the package ─▶ tofu apply ─▶ upload the index ─▶ smoke test
                                                    ↘ tofu destroy when done
```

## Once, in the console

Attach `deploy-policy.json` in this directory as a **managed** policy on the `grc-copilot`
IAM user. Managed, not inline: inline policies cap at 2048 non-whitespace characters and this
is about 2400.

```
IAM ─▶ Policies ─▶ Create policy ─▶ JSON ─▶ paste ─▶ name: grc-copilot-deploy
    ↘ Users ─▶ grc-copilot ─▶ Add permissions ─▶ Attach policies directly
```

The IAM console's validator rejects `apigateway:TagResource` as non-existent. AWS enforces it
anyway — the failed apply names it explicitly. Save past the warning.

**Detach this policy when you are not deploying.** It is a deployment credential, not a
runtime one.

## Deploy

```bash
export AWS_PROFILE=grc-copilot AWS_REGION=us-east-1

# 1. Build the Lambda package. Excludes dagster, pdfplumber and mcp -- ingestion
#    and developer tooling, not the request path. 111 MB against a 250 MB limit.
bash scripts/build_lambda.sh

# 2. Create everything. The key goes to Secrets Manager, never to an environment
#    variable, and never into terraform.tfstate as plaintext you might commit.
export TF_VAR_api_key="$(grep '^GRC_API_KEY=' .env | cut -d= -f2-)"
tofu -chdir=infra apply

# 3. Upload the index and the ontology. The bucket denies unencrypted writes, so
#    --sse is required rather than optional.
BUCKET=$(tofu -chdir=infra output -raw documents_bucket)
KMS=$(aws kms describe-key --key-id alias/grc-copilot-dev --query KeyMetadata.Arn --output text)
for f in real.npy real.json; do
  aws s3 cp "data/index/$f" "s3://$BUCKET/index/$f" --sse aws:kms --sse-kms-key-id "$KMS"
done
aws s3 cp data/ontology/ontology.sqlite "s3://$BUCKET/ontology/ontology.sqlite" \
  --sse aws:kms --sse-kms-key-id "$KMS"

# 4. Confirm it works
URL=$(tofu -chdir=infra output -raw api_url)
curl -s "$URL/health"
```

A code change needs steps 1 and 2 only. An index rebuild needs step 3 only — the index is
downloaded at runtime rather than bundled, so a corpus change does not require a redeploy.

## Use it

```bash
KEY=$(grep '^GRC_API_KEY=' .env | cut -d= -f2-)

curl "$URL/health"                                    # no key needed
curl "$URL/gaps"                -H "X-API-Key: $KEY"
curl "$URL/controls/AC-02"      -H "X-API-Key: $KEY"
curl -X POST "$URL/questionnaires" -H "X-API-Key: $KEY" -F "file=@questions.csv"
curl "$URL/questionnaires/{job}/answers" -H "X-API-Key: $KEY"
curl "$URL/reviews"             -H "X-API-Key: $KEY"
curl -X POST "$URL/reviews/{job}/{question}/approve" -H "X-API-Key: $KEY" -d '{}'
```

## Or just run the scripts

```bash
scripts/up.sh      # package, apply, upload the index, smoke test  (~5 min)
scripts/down.sh    # destroy, and verify the state is actually empty
```

`up.sh` refuses to deploy when `GRC_API_KEY` is missing or empty. `require_api_key` treats an
unset key as "open", which is correct for local development and catastrophic on a public URL:
the API would come up, work perfectly, and be readable by anyone who found it.

`down.sh` checks `tofu state list` afterwards and exits non-zero if anything survived. A
destroy that half-works reports success and leaves resources billing -- which is what happened
the first time (`MISTAKES.md` 49).

## Take it down

```bash
export AWS_PROFILE=grc-copilot
export TF_VAR_api_key="$(grep '^GRC_API_KEY=' .env | cut -d= -f2-)"   # no default, so destroy needs it too
tofu -chdir=infra destroy
```

Two permissions exist in `deploy-policy.json` only for this direction, and both were missing
the first time it ran: `s3:DeleteObjectVersion`, because `force_destroy` on a versioned bucket
deletes every object version rather than every object, and `iam:ListInstanceProfilesForRole`,
because the SDK checks a role for instance profiles before deleting it.

The two KMS keys do not disappear. They enter `PendingDeletion` for 7 days -- AWS's minimum --
and bill $1/month each until then. Everything else stops costing immediately.

**Do this when you have finished demonstrating it.** Idle cost is about $2.40/month, almost
entirely the two KMS keys — everything else is $0 when nothing runs, but the keys bill whether
or not anyone calls the API.

The KMS keys enter a 7-day deletion window rather than disappearing, and continue to bill
during it. That is deliberate: it is the window in which a mistaken destroy can be undone.

Confirm nothing is left:

```bash
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values=grc-copilot
```

Every resource is tagged, so one filter finds anything `destroy` missed.

## If a deploy fails

The error names the action and the resource. Read the **resource** first — MISTAKES entries 5,
9 and 42 are all an AWS denial whose message led with an action that was already allowed.

Logs:

```bash
aws logs tail /aws/lambda/grc-copilot-dev-api --since 5m --format short
```
