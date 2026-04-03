"""
LLM Benchmark — Energy Trading Desk
Compares Groq cloud models vs local Ollama models across:
  - Latency (TTFT, total, tokens/sec)
  - Response quality on energy market prompts
  - Cost estimates

Usage:
    python benchmark.py              # full benchmark
    python benchmark.py --quick      # 1 prompt per model (fast)
    python benchmark.py --report     # show last saved results
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import requests
from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

RESULTS_PATH = Path("benchmark_results.json")
CHART_PATH   = Path("benchmark_charts.png")

GROQ_KEYS = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Groq models to benchmark (skip speech/classification models)
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "moonshotai/kimi-k2-instruct",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
    "groq/compound",
    "allam-2-7b",
]

# Ollama models to benchmark
OLLAMA_MODELS = [
    "qwen2.5:14b",
    "qwen2.5-coder:14b",
    "gemma3:latest",
    "mistral:latest",
]

# Groq pricing (USD per 1M tokens) — update as pricing changes
GROQ_PRICING: dict[str, dict] = {
    "llama-3.3-70b-versatile":               {"input": 0.59,  "output": 0.79},
    "llama-3.1-8b-instant":                  {"input": 0.05,  "output": 0.08},
    "meta-llama/llama-4-scout-17b-16e-instruct": {"input": 0.11, "output": 0.34},
    "qwen/qwen3-32b":                         {"input": 0.29,  "output": 0.59},
    "moonshotai/kimi-k2-instruct":            {"input": 1.00,  "output": 1.00},
    "openai/gpt-oss-20b":                    {"input": 0.20,  "output": 0.20},
    "openai/gpt-oss-120b":                   {"input": 0.90,  "output": 0.90},
    "groq/compound-mini":                    {"input": 0.10,  "output": 0.10},
    "groq/compound":                          {"input": 0.50,  "output": 0.50},
    "allam-2-7b":                             {"input": 0.05,  "output": 0.05},
}

# Energy-market benchmark prompts (varied complexity)
PROMPTS = [
    {
        "id": "market_brief",
        "label": "Market Brief",
        "system": "You are a senior energy market analyst. Be concise and data-driven.",
        "user": (
            "WTI crude is at $72/bbl, down 3% this week. US crude inventories rose by 4.2 Mmbbl. "
            "OPEC+ maintained production cuts. Give a 3-bullet market brief and a directional signal "
            "(BULLISH/BEARISH/NEUTRAL) with confidence %."
        ),
    },
    {
        "id": "technical_analysis",
        "label": "Technical Analysis",
        "system": "You are a technical analyst specializing in energy commodities.",
        "user": (
            "XLE ETF: close=$59.1, RSI=44.2 (neutral), MACD histogram=-0.18 (bearish), "
            "price below 20-day MA=$61.4, Bollinger Band Low=$57.2. "
            "Interpret these indicators and recommend: BUY / SELL / HOLD with stop-loss level."
        ),
    },
    {
        "id": "risk_assessment",
        "label": "Risk Assessment",
        "system": "You are a risk manager for an energy trading fund.",
        "user": (
            "Portfolio: XLE 18%, XOM 12%, USO 8%. Annualized volatility: XLE=28%, XOM=22%, USO=35%. "
            "Max drawdown limit is 15%. Assess current risk posture and recommend position adjustments "
            "in 3 bullet points."
        ),
    },
    {
        "id": "sentiment_synthesis",
        "label": "Sentiment Synthesis",
        "system": "You are a quantitative analyst synthesizing market sentiment for energy markets.",
        "user": (
            "Reddit energy sentiment: 42% bullish, 38% bearish, 20% neutral (150 posts). "
            "Top headlines: 'OPEC+ signals output cut extension', 'US shale production hits record high', "
            "'China energy demand disappoints'. Synthesize into a net sentiment score (-1 to +1) "
            "and explain key drivers."
        ),
    },
]

# ── Groq benchmark ────────────────────────────────────────────────────────────

def benchmark_groq(model: str, prompt: dict, key_index: int = 0) -> dict | None:
    if not GROQ_KEYS:
        print("  [skip] No Groq API keys configured")
        return None
    client = Groq(api_key=GROQ_KEYS[key_index % len(GROQ_KEYS)])
    try:
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user",   "content": prompt["user"]},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        total_ms = (time.perf_counter() - t0) * 1000
        text = response.choices[0].message.content or ""
        usage = response.usage
        p_tok = usage.prompt_tokens if usage else 0
        c_tok = usage.completion_tokens if usage else 0
        pricing = GROQ_PRICING.get(model, {"input": 0, "output": 0})
        cost = (p_tok * pricing["input"] + c_tok * pricing["output"]) / 1_000_000
        return {
            "provider": "groq",
            "model": model,
            "prompt_id": prompt["id"],
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_ms": round(total_ms, 1),
            "tokens_per_sec": round(c_tok / (total_ms / 1000), 1) if total_ms > 0 else 0,
            "cost_usd": round(cost, 8),
            "response_preview": text[:120],
            "ok": True,
        }
    except Exception as e:
        return {"provider": "groq", "model": model, "prompt_id": prompt["id"],
                "error": str(e)[:120], "ok": False,
                "total_ms": 0, "tokens_per_sec": 0, "cost_usd": 0,
                "prompt_tokens": 0, "completion_tokens": 0}


# ── Ollama benchmark ──────────────────────────────────────────────────────────

def benchmark_ollama(model: str, prompt: dict) -> dict | None:
    try:
        t0 = time.perf_counter()
        resp = requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user",   "content": prompt["user"]},
                ],
                "options": {"temperature": 0.1, "num_predict": 512},
                "stream": False,
            },
            timeout=180,
        )
        resp.raise_for_status()
        total_ms = (time.perf_counter() - t0) * 1000
        data = resp.json()
        text = data["message"]["content"]
        p_tok = data.get("prompt_eval_count", 0)
        c_tok = data.get("eval_count", 0)
        eval_ns = data.get("eval_duration", 1)
        tps = round(c_tok / (eval_ns / 1e9), 1) if eval_ns > 0 else 0
        return {
            "provider": "ollama",
            "model": model,
            "prompt_id": prompt["id"],
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_ms": round(total_ms, 1),
            "tokens_per_sec": tps,
            "cost_usd": 0.0,  # local = free
            "response_preview": text[:120],
            "ok": True,
        }
    except Exception as e:
        return {"provider": "ollama", "model": model, "prompt_id": prompt["id"],
                "error": str(e)[:120], "ok": False,
                "total_ms": 0, "tokens_per_sec": 0, "cost_usd": 0,
                "prompt_tokens": 0, "completion_tokens": 0}


# ── Runner ────────────────────────────────────────────────────────────────────

def run_benchmark(quick: bool = False) -> list[dict]:
    prompts = PROMPTS[:1] if quick else PROMPTS
    results = []
    total = (len(GROQ_MODELS) + len(OLLAMA_MODELS)) * len(prompts)
    done = 0

    print(f"\n{'='*60}")
    print(f"  LLM Benchmark — Energy Trading Desk")
    print(f"  {len(GROQ_MODELS)} Groq models + {len(OLLAMA_MODELS)} Ollama models")
    print(f"  {len(prompts)} prompt(s) × {len(GROQ_MODELS)+len(OLLAMA_MODELS)} models = {total} calls")
    print(f"{'='*60}\n")

    # Groq models
    for i, model in enumerate(GROQ_MODELS):
        short = model.split("/")[-1][:30]
        for prompt in prompts:
            done += 1
            print(f"  [{done}/{total}] groq/{short} — {prompt['label']} ...", end=" ", flush=True)
            r = benchmark_groq(model, prompt, key_index=i)
            if r:
                results.append(r)
                if r["ok"]:
                    print(f"✓ {r['total_ms']:.0f}ms  {r['tokens_per_sec']:.0f}t/s")
                else:
                    print(f"✗ {r.get('error','err')[:50]}")
            time.sleep(0.3)  # rate limit buffer

    # Ollama models
    for model in OLLAMA_MODELS:
        for prompt in prompts:
            done += 1
            print(f"  [{done}/{total}] ollama/{model} — {prompt['label']} ...", end=" ", flush=True)
            r = benchmark_ollama(model, prompt)
            if r:
                results.append(r)
                if r["ok"]:
                    print(f"✓ {r['total_ms']:.0f}ms  {r['tokens_per_sec']:.0f}t/s  (local/free)")
                else:
                    print(f"✗ {r.get('error','err')[:50]}")

    return results


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse(results: list[dict]) -> dict:
    ok = [r for r in results if r.get("ok")]
    stats: dict[str, dict] = {}

    for r in ok:
        key = f"{r['provider']}/{r['model']}"
        if key not in stats:
            stats[key] = {
                "provider": r["provider"],
                "model": r["model"],
                "label": r["model"].split("/")[-1][:25],
                "total_ms": [],
                "tokens_per_sec": [],
                "cost_usd": [],
                "prompt_tokens": [],
                "completion_tokens": [],
            }
        stats[key]["total_ms"].append(r["total_ms"])
        stats[key]["tokens_per_sec"].append(r["tokens_per_sec"])
        stats[key]["cost_usd"].append(r["cost_usd"])
        stats[key]["prompt_tokens"].append(r["prompt_tokens"])
        stats[key]["completion_tokens"].append(r["completion_tokens"])

    summary = {}
    for key, s in stats.items():
        tms = s["total_ms"]
        tps = s["tokens_per_sec"]
        summary[key] = {
            "provider": s["provider"],
            "model": s["model"],
            "label": s["label"],
            "calls": len(tms),
            "avg_ms": round(statistics.mean(tms), 1),
            "median_ms": round(statistics.median(tms), 1),
            "p95_ms": round(sorted(tms)[int(len(tms) * 0.95)] if len(tms) > 1 else tms[-1], 1),
            "min_ms": round(min(tms), 1),
            "max_ms": round(max(tms), 1),
            "avg_tps": round(statistics.mean(tps), 1),
            "std_tps": round(statistics.stdev(tps) if len(tps) > 1 else 0, 1),
            "max_tps": round(max(tps), 1),
            "std_ms": round(statistics.stdev(tms) if len(tms) > 1 else 0, 1),
            "total_cost_usd": round(sum(s["cost_usd"]), 8),
            "cost_per_1k_calls": round(sum(s["cost_usd"]) / max(len(tms), 1) * 1000, 4),
            "avg_completion_tokens": round(statistics.mean(s["completion_tokens"]), 1),
        }

    return summary


def print_table(summary: dict) -> None:
    rows = sorted(summary.values(), key=lambda x: x["avg_ms"])
    print(f"\n{'='*110}")
    print(f"  {'Model':<32} {'Provider':<8} {'Avg ms':>7} {'Med ms':>7} {'p95 ms':>7} "
          f"{'Avg t/s':>8} {'Max t/s':>8} {'$/1k calls':>11}")
    print(f"  {'-'*32} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*8} {'-'*11}")
    for r in rows:
        cost_str = f"${r['cost_per_1k_calls']:.4f}" if r["cost_per_1k_calls"] > 0 else "FREE"
        provider_icon = "☁" if r["provider"] == "groq" else "🖥"
        print(
            f"  {r['label']:<32} {provider_icon+r['provider']:<8} "
            f"{r['avg_ms']:>7.0f} {r['median_ms']:>7.0f} {r['p95_ms']:>7.0f} "
            f"{r['avg_tps']:>8.1f} {r['max_tps']:>8.1f} {cost_str:>11}"
        )
    print(f"{'='*110}\n")

    # Winners
    fastest = min(summary.values(), key=lambda x: x["avg_ms"])
    highest_tps = max(summary.values(), key=lambda x: x["avg_tps"])
    cheapest_cloud = min(
        (v for v in summary.values() if v["provider"] == "groq"),
        key=lambda x: x["cost_per_1k_calls"],
        default=None,
    )
    print("  🏆 Fastest overall:      ", fastest["model"])
    print("  🚀 Highest throughput:   ", highest_tps["model"], f"({highest_tps['avg_tps']:.0f} t/s)")
    if cheapest_cloud:
        print("  💰 Cheapest cloud model: ", cheapest_cloud["model"],
              f"(${cheapest_cloud['cost_per_1k_calls']:.4f}/1k calls)")
    print()


# ── Charts ────────────────────────────────────────────────────────────────────

PROVIDER_COLORS = {"groq": "#d62728", "ollama": "#1f77b4"}
STYLE = {
    "bg":       "#fafafa",
    "panel":    "#ffffff",
    "grid":     "#e0e0e0",
    "text":     "#1a1a1a",
    "subtext":  "#555555",
    "border":   "#cccccc",
}


def _stat_label(vals: list[float]) -> str:
    """μ ± σ  (CV=x%)"""
    if not vals:
        return ""
    mu = statistics.mean(vals)
    sigma = statistics.stdev(vals) if len(vals) > 1 else 0.0
    cv = (sigma / mu * 100) if mu else 0
    return f"μ={mu:.0f}  σ={sigma:.0f}  CV={cv:.1f}%"


def _efficiency_score(r: dict) -> float:
    """Composite score: tokens/sec per dollar (free = use 1/ms as proxy)."""
    if r["cost_per_1k_calls"] > 0:
        return r["avg_tps"] / r["cost_per_1k_calls"]
    # Local: value = tps / (latency_s) as a free-tier proxy
    return r["avg_tps"] * 1000 / max(r["avg_ms"], 1)


def make_charts(results: list[dict], summary: dict) -> None:
    ok = [r for r in results if r.get("ok")]
    rows_lat = sorted(summary.values(), key=lambda x: x["avg_ms"])
    model_keys = [f"{r['provider']}/{r['model']}" for r in rows_lat]

    fig, axes = plt.subplots(1, 2, figsize=(16, 7), facecolor=STYLE["bg"])
    fig.subplots_adjust(left=0.10, right=0.97, top=0.91, bottom=0.07, wspace=0.36)

    def _style(ax, title, xlabel=""):
        ax.set_facecolor(STYLE["panel"])
        ax.set_title(title, fontsize=10, fontweight="bold", color=STYLE["text"], pad=6)
        ax.set_xlabel(xlabel, fontsize=8.5, color=STYLE["subtext"])
        ax.tick_params(colors=STYLE["text"], labelsize=8)
        ax.grid(True, color=STYLE["grid"], linewidth=0.6, zorder=0, axis="x")
        for spine in ax.spines.values():
            spine.set_edgecolor(STYLE["border"])

    # ── Panel A: Latency μ ± σ, horizontal bars, log scale ───────────────────
    ax = axes[0]
    y   = range(len(rows_lat))
    mu  = [r["avg_ms"]        for r in rows_lat]
    sig = [r.get("std_ms", 0) for r in rows_lat]
    cv  = [r.get("std_ms", 0) / max(r["avg_ms"], 1) * 100 for r in rows_lat]
    clr = [PROVIDER_COLORS[r["provider"]] for r in rows_lat]

    ax.barh(y, mu, xerr=sig, color=clr, alpha=0.78, height=0.58,
            error_kw=dict(ecolor="#333", capsize=3, linewidth=1.0), zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels([r["label"] for r in rows_lat], fontsize=8)
    ax.invert_yaxis()
    ax.set_xscale("log")

    for i, r in enumerate(rows_lat):
        s = r.get("std_ms", 0)
        ax.text(r["avg_ms"] * 1.15 + s, i,
                f"μ={r['avg_ms']:.0f}  σ={s:.0f}  CV={cv[i]:.0f}%",
                va="center", fontsize=6.8, color=STYLE["subtext"])

    _style(ax, "Latency  μ ± σ  (log scale)", "Mean Latency (ms)")

    # ── Panel B: Box plot — IQR + whiskers, log scale ────────────────────────
    ax = axes[1]
    box_data, box_colors, box_labels = [], [], []
    for key, row in zip(model_keys, rows_lat):
        vals = [r["total_ms"] for r in ok if f"{r['provider']}/{r['model']}" == key]
        if vals:
            box_data.append(vals)
            box_colors.append(PROVIDER_COLORS[row["provider"]])
            box_labels.append(row["label"][:18])

    if box_data:
        bp = ax.boxplot(
            box_data, vert=False, patch_artist=True, notch=False,
            medianprops=dict(color="#111", linewidth=2.0),
            whiskerprops=dict(linewidth=1.0, linestyle="--"),
            capprops=dict(linewidth=1.3),
            flierprops=dict(marker="x", markersize=4, color="#999", alpha=0.6),
            widths=0.55,
        )
        for patch, c in zip(bp["boxes"], box_colors):
            patch.set_facecolor(c)
            patch.set_alpha(0.58)
        ax.set_yticks(range(1, len(box_labels) + 1))
        ax.set_yticklabels(box_labels, fontsize=8)
        ax.set_xscale("log")

        for i, (vals, row) in enumerate(zip(box_data, rows_lat), 1):
            sv  = sorted(vals)
            p50 = statistics.median(sv)
            p25 = sv[max(0, int(len(sv) * 0.25) - 1)]
            p75 = sv[min(len(sv) - 1, int(len(sv) * 0.75))]
            ax.text(p50 * 1.08, i - 0.36,
                    f"p50={p50:.0f}  IQR={p75-p25:.0f}",
                    fontsize=6.5, color=STYLE["subtext"], va="top")

    _style(ax, "Latency Distribution  [IQR · 1.5× whiskers]", "Total Latency (ms)")

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_patches = [
        mpatches.Patch(color=PROVIDER_COLORS["groq"],   label="Groq (cloud)"),
        mpatches.Patch(color=PROVIDER_COLORS["ollama"], label="Ollama (local · M2 Pro 32 GB)"),
    ]
    fig.legend(handles=legend_patches, loc="upper center", ncol=2,
               facecolor=STYLE["panel"], edgecolor=STYLE["border"],
               fontsize=9, framealpha=0.9, bbox_to_anchor=(0.5, 0.99))

    fig.suptitle("LLM Latency Benchmark  ·  Groq vs Ollama  ·  n = 56 calls",
                 fontsize=11, color=STYLE["subtext"], y=1.04)

    plt.savefig(CHART_PATH, dpi=150, bbox_inches="tight", facecolor=STYLE["bg"])
    print(f"  Charts saved -> {CHART_PATH}")
    plt.show()


# ── Save / load results ───────────────────────────────────────────────────────

def save_results(results: list[dict], summary: dict) -> None:
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": _system_info(),
        "raw_results": results,
        "summary": summary,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    print(f"  Results saved → {RESULTS_PATH}")


def _system_info() -> dict:
    import platform
    info = {"platform": platform.platform(), "python": platform.python_version()}
    try:
        import subprocess
        cpu = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
        info["cpu"] = cpu
    except Exception:
        info["cpu"] = "unknown"
    try:
        import subprocess
        mem = subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], text=True
        ).strip()
        info["ram_gb"] = round(int(mem) / 1024**3, 1)
    except Exception:
        info["ram_gb"] = "unknown"
    return info


def show_report() -> None:
    if not RESULTS_PATH.exists():
        print("No results file found. Run benchmark first.")
        return
    data = json.loads(RESULTS_PATH.read_text())
    print(f"\nBenchmark run: {data['timestamp']}")
    print(f"System: {data['system'].get('cpu','?')} | {data['system'].get('ram_gb','?')} GB RAM")
    print_table(data["summary"])


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM Benchmark — Energy Trading Desk")
    parser.add_argument("--quick",  action="store_true", help="1 prompt per model (fast)")
    parser.add_argument("--report", action="store_true", help="Show last saved results")
    parser.add_argument("--no-charts", action="store_true", help="Skip chart generation")
    args = parser.parse_args()

    if args.report:
        show_report()
        sys.exit(0)

    results = run_benchmark(quick=args.quick)
    summary = analyse(results)

    print_table(summary)
    save_results(results, summary)

    if not args.no_charts and results:
        print("\nGenerating charts...")
        try:
            make_charts(results, summary)
        except Exception as e:
            print(f"  Chart generation failed: {e}")

    print("\nDone. Run `python benchmark.py --report` to see results again.")
