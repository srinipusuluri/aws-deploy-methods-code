#!/usr/bin/env bash
# Usage: scripts/deploy.sh <level: 1-2|3|4|5|6|7> <stack-name> [extra --parameter-overrides k=v ...]
# Requires: AWS CLI + SAM CLI configured (aws configure / SSO). Builds, deploys, prints outputs.
set -euo pipefail
LEVEL="${1:?level (1-2,3,4,5,6,7)}"; STACK="${2:?stack name}"; shift 2
cd "$(dirname "$0")/../infrastructure"
python3 build_templates.py >/dev/null
T="level${LEVEL}.yaml"
sam validate --lint -t "$T"
sam build -t "$T" --use-container=false
sam deploy -t "$T" --stack-name "$STACK" --capabilities CAPABILITY_IAM --resolve-s3 \
  --parameter-overrides "$@"
aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Outputs' --output table
