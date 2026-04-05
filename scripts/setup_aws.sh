#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup_aws.sh  —  One-time AWS setup for the Energy Trading Desk
#
# Usage:
#   chmod +x scripts/setup_aws.sh
#   ./scripts/setup_aws.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"

# ── Find CDK — works whether installed globally or only via npx ──────────────
if command -v cdk &>/dev/null; then
  CDK="cdk"
elif command -v npx &>/dev/null; then
  CDK="npx cdk"
else
  # macOS: npm global bin is usually here
  NPM_BIN="$(npm root -g 2>/dev/null)/../.bin"
  if [ -f "$NPM_BIN/cdk" ]; then
    CDK="$NPM_BIN/cdk"
  else
    echo "ERROR: CDK not found. Run: npm install -g aws-cdk"
    exit 1
  fi
fi
echo "Using CDK: $CDK"

# ── Load .env — set -a exports every variable automatically ──────────────────
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in your keys."
  exit 1
fi

set -a                  # auto-export all variables
# shellcheck disable=SC1091
source .env
set +a

echo ""
echo "==> [1/3] Storing API keys in SSM Parameter Store (free tier)..."

put_param() {
  local name="$1"
  local value="$2"
  # Skip placeholders or empty values
  if [ -z "$value" ] || [[ "$value" == your_* ]] || [[ "$value" == *_here ]]; then
    echo "    SKIP $name (placeholder or empty)"
    return
  fi
  aws ssm put-parameter \
    --region "$REGION" \
    --name "$name" \
    --value "$value" \
    --type "String" \
    --overwrite \
    --no-cli-pager \
    --output text \
    --query "Version" 2>&1 | xargs -I{} echo "    OK   $name (version {})" || \
    echo "    WARN $name (put-parameter failed — check IAM permissions)"
}

put_param "/energy-trading/groq-api-keys"  "${GROQ_API_KEYS:-}"
put_param "/energy-trading/eia-api-key"    "${EIA_API_KEY:-}"
put_param "/energy-trading/newsapi-key"    "${NEWSAPI_KEY:-}"
put_param "/energy-trading/fred-api-key"   "${FRED_API_KEY:-}"

echo ""
echo "==> [2/3] Bootstrapping CDK (safe to run multiple times)..."
cd infrastructure
pip install -r requirements.txt --quiet

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=true
$CDK bootstrap "aws://$ACCOUNT/$REGION" --region "$REGION"

echo ""
echo "==> [3/3] Deploying all stacks..."
echo "    Note: first deploy takes 10-15 min (Lambda bundling uses Docker)"
$CDK deploy --all \
  --require-approval never \
  --region "$REGION" \
  --outputs-file ../cdk-outputs.json

cd ..

echo ""
echo "✓ Done! Stack outputs written to cdk-outputs.json"
echo ""
echo "Run the full pipeline:"
echo "  ./scripts/run_pipeline.sh"
echo ""
echo "Or run via Step Functions (visual graph):"
STATE_MACHINE_ARN=$(python3 -c "
import json, sys
try:
    data = json.load(open('cdk-outputs.json'))
    for stack in data.values():
        if 'StateMachineArn' in stack:
            print(stack['StateMachineArn'])
            break
except: pass
" 2>/dev/null || echo "<StateMachineArn from cdk-outputs.json>")
echo "  aws stepfunctions start-sync-execution \\"
echo "    --state-machine-arn $STATE_MACHINE_ARN \\"
echo "    --input '{}' --region $REGION"
