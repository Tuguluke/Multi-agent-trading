#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_pipeline.sh  —  Manually invoke the full pipeline on AWS
#
# Usage:
#   ./scripts/run_pipeline.sh            # ingest + agents
#   ./scripts/run_pipeline.sh ingest     # data ingestion only
#   ./scripts/run_pipeline.sh agents     # agents only
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
MODE="${1:-full}"

run_ingest() {
  echo "==> Invoking data ingestion Lambda..."
  aws lambda invoke \
    --function-name energy-trading-data-ingestion \
    --region "$REGION" \
    --log-type Tail \
    --no-cli-pager \
    /tmp/ingest_out.json \
    | python3 -c "import sys,json,base64; r=json.load(sys.stdin); print(base64.b64decode(r.get('LogResult','')).decode())" 2>/dev/null || true
  echo "Response:"
  cat /tmp/ingest_out.json | python3 -m json.tool
}

run_agents() {
  echo ""
  echo "==> Invoking agent pipeline Lambda..."
  aws lambda invoke \
    --function-name energy-trading-agent-trigger \
    --region "$REGION" \
    --payload '{"Records":[]}' \
    --log-type Tail \
    --no-cli-pager \
    /tmp/agent_out.json \
    | python3 -c "import sys,json,base64; r=json.load(sys.stdin); print(base64.b64decode(r.get('LogResult','')).decode())" 2>/dev/null || true
  echo "Response:"
  cat /tmp/agent_out.json | python3 -m json.tool
}

case "$MODE" in
  ingest) run_ingest ;;
  agents) run_agents ;;
  full)   run_ingest; run_agents ;;
  *)
    echo "Usage: $0 [full|ingest|agents]"
    exit 1
    ;;
esac

echo ""
echo "Done. Check CloudWatch logs:"
echo "  https://$REGION.console.aws.amazon.com/cloudwatch/home#logsV2:log-groups"
