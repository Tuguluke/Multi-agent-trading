# Multi-Agent Energy Trading Desk

A production-grade MLOps system that runs a pipeline of specialized AI agents to analyze the energy market (WTI crude, natural gas, electricity, energy equities) and generate trading signals. Built entirely on AWS with a Streamlit dashboard.

## Architecture

```
Manual trigger (CLI or Streamlit)
    │
    ▼
Step Functions state machine
    │
    ├─► Lambda: Data Ingestion
    │       EIA · yfinance · FRED · NewsAPI · Reddit
    │       └─► S3 (raw snapshots) + DynamoDB (MarketSnapshots)
    │
    ├─► Lambda: MarketDataAgent      (LLM summary of current prices)
    │
    ├─► Lambda: TechnicalAnalyst  ─┐  (run in parallel)
    ├─► Lambda: SentimentAgent    ─┘
    │
    ├─► Lambda: RiskManager          (position sizing, exposure checks)
    │
    └─► Lambda: PortfolioManager     (weighted aggregation → final signal)
            └─► DynamoDB (AgentSignals) + SNS (strong signals)

LLM providers: Groq (cloud) · Ollama (local) · Amazon Bedrock (AWS-native)
Observability:  CloudWatch metrics + X-Ray distributed tracing
Analytics:      Athena SQL queries over S3 via Glue Data Catalog
```

## AWS Services Used

| Service | Role |
|---------|------|
| **Lambda** | Each pipeline step runs as a serverless function |
| **Step Functions** | Orchestrates the agent pipeline as a visual state machine |
| **DynamoDB** | Stores market snapshots, agent signals, LLM benchmark logs |
| **S3** | Raw market data, pipeline run summaries |
| **SQS + SNS** | Inter-agent messaging; signal notifications |
| **Athena + Glue** | SQL analytics over S3 — query market data without loading it |
| **CloudWatch** | Custom metrics (agent latency, LLM calls, throttles) + dashboard |
| **X-Ray** | Distributed tracing across the full Lambda pipeline |
| **Bedrock** | AWS-native LLM inference (Llama 3, Mistral, Titan) |
| **SSM Parameter Store** | Secure storage for API keys (free tier) |
| **EventBridge** | Available for scheduled runs if needed |

**Estimated cost with $120 AWS credit: ~$2–3/month** (Lambda + DynamoDB + S3 are free tier; Bedrock charges per token at tiny scale).

---

## Prerequisites

### 1. Install tools

```bash
# AWS CLI
brew install awscli          # macOS
# or: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html

# Node.js (required by CDK)
brew install node

# AWS CDK
npm install -g aws-cdk

# Python 3.12+
brew install python@3.12

# Docker (required for CDK Lambda bundling)
# Download Docker Desktop from https://www.docker.com/products/docker-desktop/
```

### 2. Configure AWS credentials

```bash
aws configure
```

Enter when prompted:
- **AWS Access Key ID** — from IAM → Users → Security credentials → Create access key
- **AWS Secret Access Key** — shown once at creation time
- **Default region** — `us-east-1`
- **Default output format** — `json`

Verify it works:
```bash
aws sts get-caller-identity
# Should print your account ID and ARN
```

### 3. Bedrock (optional — for AWS-native LLM)

Bedrock models are automatically enabled on first invocation — no manual activation needed. Just set `LLM_PROVIDER=bedrock` and invoke. Anthropic models (Claude) may require submitting a brief use case form on first use.

---

## API Keys

You need at least a Groq key. All others are free to obtain.

| Key | Where to get it | Required? |
|-----|----------------|-----------|
| `GROQ_API_KEYS` | [console.groq.com](https://console.groq.com) | **Yes** |
| `EIA_API_KEY` | [eia.gov/opendata](https://www.eia.gov/opendata/register.php) | Recommended |
| `FRED_API_KEY` | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) | Recommended |
| `NEWSAPI_KEY` | [newsapi.org](https://newsapi.org/register) | Optional |
| `REDDIT_CLIENT_ID/SECRET` | [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) | Optional |

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
# Edit .env with your keys
```

---

## Local Development

Run the full stack locally with Docker + LocalStack (simulates AWS services):

```bash
docker-compose up
```

This starts:
- **Streamlit dashboard** at `http://localhost:8501`
- **LocalStack** at `http://localhost:4566` — local S3, DynamoDB, SQS, SSM

Or run without Docker (uses real AWS or gracefully skips AWS calls):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run the full pipeline once
python main.py full

# Run just data ingestion
python main.py ingest

# Launch the dashboard
streamlit run app.py
```

### Run the LLM benchmark

Compares Groq models vs local Ollama across 4 energy prompts:

```bash
# Make sure Ollama is running: ollama serve
python benchmark.py
# Outputs: benchmark_results.json + benchmark_charts.png
```

---

## AWS Deployment

### Step 1 — Deploy (one command)

Make sure Docker is running (needed for Lambda bundling), then:

```bash
chmod +x scripts/setup_aws.sh
./scripts/setup_aws.sh
```

This script does three things:
1. **Stores your API keys in SSM Parameter Store** (free, secure)
2. **Bootstraps CDK** in your account/region
3. **Deploys all 6 stacks** via `cdk deploy --all`

Deployment takes about 5–10 minutes. Stack outputs are saved to `cdk-outputs.json`.

### What gets deployed

```
EnergyTradingStorage    →  S3 bucket + 4 DynamoDB tables
EnergyTradingMessaging  →  SQS queues + SNS topic
EnergyTradingCompute    →  2 Lambda functions (ingest + agent trigger)
EnergyTradingPipeline   →  Step Functions state machine
EnergyTradingAnalytics  →  Athena workgroup + Glue crawlers
EnergyTradingMonitoring →  CloudWatch dashboard + alarms
```

### Step 2 — Run the pipeline

```bash
# Full pipeline: ingest data → run all agents
./scripts/run_pipeline.sh

# Or run steps individually
./scripts/run_pipeline.sh ingest    # fetch market data only
./scripts/run_pipeline.sh agents    # run LLM agents only
```

Or run via Step Functions (recommended — gives visual execution graph):

```bash
# Get the state machine ARN from cdk-outputs.json, then:
aws stepfunctions start-sync-execution \
  --state-machine-arn <arn from cdk-outputs.json> \
  --input '{}' \
  --region us-east-1
```

### Step 3 — View results

| What | Where |
|------|-------|
| **Pipeline execution graph** | AWS Console → Step Functions → `energy-trading-agent-pipeline` |
| **CloudWatch dashboard** | AWS Console → CloudWatch → Dashboards → `EnergyTradingDesk` |
| **Distributed traces** | AWS Console → X-Ray → Service Map |
| **SQL analytics** | AWS Console → Athena → Query editor (workgroup: `energy-trading`) |
| **Raw data** | AWS Console → S3 → `energy-trading-data-<account>` |
| **Agent signals** | AWS Console → DynamoDB → `dev-AgentSignals` |
| **Streamlit dashboard** | Run `streamlit run app.py` locally (reads from live DynamoDB) |

---

## SQL Analytics with Athena

After running the pipeline, update the Glue catalog first:

```bash
aws glue start-crawler --name energy-trading-market-snapshots --region us-east-1
aws glue start-crawler --name energy-trading-agent-signals --region us-east-1
# Wait ~1 minute for crawlers to finish, then query in Athena
```

Example queries (paste into Athena query editor, workgroup: `energy-trading`):

```sql
-- Latest agent signals
SELECT date, agent_name, direction, strength, confidence
FROM energy_trading.agent_signals
ORDER BY date DESC
LIMIT 20;

-- LLM benchmark: average latency and cost by model
SELECT model_name,
       ROUND(AVG(total_ms), 0)   AS avg_latency_ms,
       ROUND(AVG(cost_usd), 6)   AS avg_cost_usd
FROM energy_trading.llm_benchmarks
GROUP BY model_name
ORDER BY avg_latency_ms;

-- Signal direction distribution over time
SELECT date,
       SUM(CASE WHEN direction = 'BULLISH' THEN 1 ELSE 0 END)  AS bullish,
       SUM(CASE WHEN direction = 'BEARISH' THEN 1 ELSE 0 END)  AS bearish
FROM energy_trading.agent_signals
GROUP BY date
ORDER BY date DESC;
```

---

## Switch LLM Provider

Edit `.env` or the Lambda environment variable `LLM_PROVIDER`:

```bash
# Groq (default — fastest, free tier)
LLM_PROVIDER=groq
GROQ_MODEL=llama-3.3-70b-versatile

# Amazon Bedrock (AWS-native — good for demos)
LLM_PROVIDER=bedrock
BEDROCK_MODEL=meta.llama3-8b-instruct-v1:0

# Ollama (local — no API cost, needs Ollama running)
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:14b
```

To redeploy with a different provider:
```bash
cd infrastructure
cdk deploy EnergyTradingCompute EnergyTradingPipeline --require-approval never
```

---

## Tear Down

To delete all AWS resources and stop incurring any charges:

```bash
cd infrastructure
cdk destroy --all
```

This removes all stacks. S3 and DynamoDB tables are set to `RETAIN` so your data is not deleted — remove them manually from the console if needed.

---

## Project Structure

```
├── agents/                  # Specialized LLM agents
│   ├── base_agent.py        # Abstract base: call_llm(), log_signal()
│   ├── market_data_agent.py # Fetches + summarizes current prices
│   ├── technical_analyst.py # RSI, MACD, Bollinger → signal
│   ├── sentiment_agent.py   # News + Reddit → sentiment score
│   ├── risk_manager.py      # Position sizing, exposure limits
│   ├── portfolio_manager.py # Weighted aggregation → final recommendation
│   └── orchestrator.py      # Runs agents sequentially (local mode)
│
├── llm/
│   ├── groq_client.py       # Round-robin key rotation, retry on 429
│   ├── ollama_client.py     # Local Ollama inference
│   ├── bedrock_client.py    # Amazon Bedrock (Llama, Mistral, Titan)
│   ├── llm_router.py        # Routes to correct provider
│   └── benchmarker.py       # Times every call: TTFT, tokens/sec, cost
│
├── data/
│   ├── eia_client.py        # US energy prices + inventories
│   ├── yfinance_client.py   # Energy equities (XOM, CVX, XLE, USO)
│   ├── fred_client.py       # Macro: WTI trend, CPI energy
│   ├── news_client.py       # NewsAPI headlines
│   ├── reddit_client.py     # r/energy, r/oil sentiment
│   └── schemas.py           # Pydantic models for all domain objects
│
├── aws/
│   ├── s3_client.py         # Upload/download market data
│   ├── dynamodb_client.py   # Read/write signals + benchmarks
│   ├── sqs_client.py        # Inter-agent messaging
│   └── cloudwatch_client.py # Custom metrics emission
│
├── infrastructure/          # AWS CDK (Python)
│   ├── app.py               # CDK entry point — wires all stacks
│   └── stacks/
│       ├── storage_stack.py       # S3 + DynamoDB
│       ├── messaging_stack.py     # SQS + SNS
│       ├── compute_stack.py       # Lambda functions
│       ├── stepfunctions_stack.py # Agent pipeline state machine
│       ├── analytics_stack.py     # Athena + Glue
│       └── monitoring_stack.py    # CloudWatch dashboard + alarms
│
├── lambdas/
│   ├── data_ingestion/      # EventBridge/manual → fetch all data sources
│   ├── agent_trigger/       # SQS consumer → run orchestrator
│   └── agent_step/          # Step Functions task → run single agent
│
├── scripts/
│   ├── setup_aws.sh         # One-time deploy: SSM keys + cdk deploy --all
│   └── run_pipeline.sh      # Manual pipeline invocation
│
├── app.py                   # Streamlit dashboard (6 tabs)
├── main.py                  # CLI: python main.py full|ingest|pipeline
├── benchmark.py             # LLM speed/cost benchmark (Groq vs Ollama)
├── config.py                # Centralised config (.env locally, SSM on AWS)
├── docker-compose.yml       # Local dev with LocalStack
└── requirements.txt
```

---

## Troubleshooting

**`cdk deploy` fails with "Docker daemon not running"**
→ Start Docker Desktop before deploying. CDK uses Docker to bundle Lambda dependencies.

**Lambda function times out**
→ The agents call external APIs (EIA, FRED, Groq) which can be slow. Timeouts are set to 5–10 min. Check CloudWatch Logs for the specific Lambda: `aws logs tail /aws/lambda/energy-trading-data-ingestion --follow`

**Groq 429 rate limit errors**
→ Add more keys to `GROQ_API_KEYS` (comma-separated). Free tier allows 1 key per account; create additional accounts or add a delay between agent steps.

**Athena "table not found" error**
→ Run the Glue crawlers first: `aws glue start-crawler --name energy-trading-market-snapshots`

**Bedrock "Access denied" error**
→ Models are auto-enabled on first invocation. If you still get this error, check your IAM role has `bedrock:InvokeModel` permission (the CDK role already includes it). For Claude models specifically, you may need to accept Anthropic's terms on first use in the Bedrock playground.

**`aws configure` credentials not found in Lambda**
→ The Lambda IAM role handles permissions automatically — you do not need AWS credentials inside the Lambda code. This error only appears locally. Make sure `ENVIRONMENT=local` in `.env` when running locally.
