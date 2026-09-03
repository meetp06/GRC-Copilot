"""Run this FIRST. Confirms Bedrock access and lists the model IDs enabled in your account.

Model availability differs by account and region, so never hardcode a model ID from a
tutorial — get the real one from here and put it in .env.

    python scripts/check_bedrock.py
"""

import os

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

REGION = os.environ.get("AWS_REGION", "us-east-1")

# Cheapest-first for a dev loop. Update as prices change.
PREFERRED = [
    "amazon.nova-micro",
    "amazon.nova-lite",
    "anthropic.claude-3-5-haiku",
    "anthropic.claude-haiku",
]


def main() -> None:
    print(f"region: {REGION}\n")

    bedrock = boto3.client("bedrock", region_name=REGION)
    try:
        models = bedrock.list_foundation_models()["modelSummaries"]
    except ClientError as exc:
        print(f"FAILED to list models: {exc}")
        print(
            "\nCheck: (1) aws configure is set, (2) your IAM user has bedrock:ListFoundationModels"
        )
        raise SystemExit(1)

    text_models = [
        m
        for m in models
        if "TEXT" in m.get("outputModalities", [])
        and "ON_DEMAND" in m.get("inferenceTypesSupported", [])
    ]

    print(f"{len(text_models)} on-demand text models visible in this region.")
    print("\nCheapest candidates for your dev loop:\n")
    for prefix in PREFERRED:
        for m in text_models:
            if m["modelId"].startswith(prefix):
                print(f"  {m['modelId']}   ({m['providerName']} {m['modelName']})")

    print("\nAll on-demand text model IDs:")
    for m in sorted(text_models, key=lambda x: x["modelId"]):
        print(f"  {m['modelId']}")

    print(
        "\nNOTE: 'visible' is not 'enabled'. If a call fails with AccessDeniedException,\n"
        "enable the model in the Bedrock console under Model access, then retry.\n"
        "Put your chosen ID in .env as BEDROCK_MODEL_ID."
    )

    # Smoke test the configured model, if one is set.
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if model_id:
        print(f"\nSmoke-testing BEDROCK_MODEL_ID={model_id} ...")
        rt = boto3.client("bedrock-runtime", region_name=REGION)
        try:
            resp = rt.converse(
                modelId=model_id,
                messages=[
                    {"role": "user", "content": [{"text": "Reply with the word: ok"}]}
                ],
                inferenceConfig={"maxTokens": 10, "temperature": 0},
            )
            text = resp["output"]["message"]["content"][0]["text"]
            u = resp["usage"]
            print(
                f"  OK -> {text.strip()!r}  ({u['inputTokens']} in / {u['outputTokens']} out)"
            )
        except ClientError as exc:
            print(f"  FAILED: {exc}")


if __name__ == "__main__":
    main()
