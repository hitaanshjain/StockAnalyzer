import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pandas as pd
import requests
from dotenv import load_dotenv
from matplotlib.backends.backend_pdf import PdfPages

from mongo_store import get_mongo_store

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SCREENING_FEATHER = BASE_DIR / "screening_output" / "final_screening_union.feather"
CHART_MANIFEST_CSV = BASE_DIR / "screening_output" / "chart_manifest.csv"
AGENTS_DATA_PACKAGE_DIR = BASE_DIR / "agents_data_package"
OUTPUT_ROOT = BASE_DIR / "output" / "agent_runs"

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

ANALYST_SYSTEM_PROMPT = """You are a stock analyst evaluating one ticker.

Decide if this is a REAL but INCOMPLETE repricing opportunity. The stock price has most likely increased a reasonable degree already, because this is a momentum strategy. 
Your goal is to figure out if the underlying fundamental catalyst is so large the the recent move still is not enough to price it in yet.  
Start from attached package files. 
Feel free to use web research, but also remember you already have some preliminary info uplaoded. 
If something is uncertain, use web search.
Be blunt, evidence-based, and decision-oriented. If financial models/valuation is necessary, do it.

Return exactly:
1) Executive Verdict (rating + stage + confidence)
2) What Changed
3) Why It Matters Economically
4) Evidence It Is Real (hard vs soft)
5) What Is Already Priced In
6) Remaining Uncertainty
7) Bull/Base/Bear (returns + probabilities summing to 100%)
8) Repricing vs Mean Reversion Probabilities
9) Disconfirming Signals (3-5)
10) Final Recommendation

End with:
FINAL_JSON:
{
  "ticker": "...",
  "rating": "Reject | Watchlist | Research Deeper | Buy Candidate",
  "repricing_stage": "Early | Middle | Late | Unclear",
  "confidence": "Low | Medium | High",
  "prob_upward_repricing": 0,
  "prob_mean_reversion": 0,
  "bull_case_return_pct": 0,
  "bull_case_prob": 0,
  "base_case_return_pct": 0,
  "base_case_prob": 0,
  "bear_case_return_pct": 0,
  "bear_case_prob": 0,
  "expected_return_pct": 0,
  "top_disconfirming_signals": ["", "", ""]
}
"""
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run per-ticker analyst agents.")
    parser.add_argument(
        "--start-rank",
        type=int,
        default=1,
        help="Starting screener rank to analyze.",
    )
    parser.add_argument(
        "--end-rank",
        type=int,
        default=5,
        help="Ending screener rank to analyze.",
    )
    parser.add_argument("--max-workers", type=int, default=2, help="Concurrent per-ticker agent calls.")
    parser.add_argument("--model", type=str, default=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))
    parser.add_argument("--reasoning-effort", type=str, default="low", choices=["low", "medium", "high"])
    parser.add_argument(
        "--web-tool-type",
        type=str,
        default=os.getenv("OPENAI_WEB_TOOL_TYPE", "web_search_preview"),
        help="Responses web search tool type.",
    )
    parser.add_argument("--run-id", type=str, default=None, help="Optional run id override.")
    parser.add_argument("--user-id", type=str, default="local-user", help="Application user id for session storage.")
    parser.add_argument("--user-email", type=str, default="", help="Optional user email for session storage.")
    parser.add_argument(
        "--include-feather",
        action="store_true",
        help="Include .feather files in uploaded package files (off by default).",
    )
    parser.add_argument(
        "--max-sec-html-files",
        type=int,
        default=4,
        help="Maximum number of SEC filing HTML files to include per ticker.",
    )
    parser.add_argument(
        "--max-file-size-mb",
        type=float,
        default=1.5,
        help="Skip files larger than this size in MB to reduce context overflows.",
    )
    parser.add_argument(
        "--skip-tickers",
        type=str,
        default="",
        help="Comma-separated tickers to exclude (e.g., CMTV,ALMS,THM,HYMC,ASA).",
    )
    return parser.parse_args()

def get_api_key() -> str:
    """Get API key from env; error if missing."""
    key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
    if not key:
        raise RuntimeError("Missing OPENAI_API_KEY (or OPENAI_KEY).")
    return key


def build_run_dirs(run_id: Optional[str]) -> Dict[str, Path]:
    """Create run folders and return their paths."""
    run_name = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    root = OUTPUT_ROOT / run_name
    per_stock, charts, uploaded = root/"per_stock", root/"charts", root/"uploaded_file_manifest"
    for d in (root, per_stock, charts, uploaded):
        d.mkdir(parents=True, exist_ok=True)
    return {"root": root, "per_stock": per_stock, "charts": charts, "uploaded": uploaded}

def resolve_rank_bounds(total_count: int, start_rank: int, end_rank: int, label: str) -> tuple[int, int]:
    # Fail fast when there is no ranked universe to slice.
    if total_count <= 0:
        raise ValueError(f"No screened stocks are available for {label}.")

    # Clamp the starting rank to at least 1 and log if user input was adjusted.
    normalized_start = max(1, int(start_rank))
    if normalized_start != int(start_rank):
        print(f"{label}: adjusted start rank from {start_rank} to {normalized_start}.")

    # Reject requests that start beyond the available number of screened rows.
    if normalized_start > total_count:
        raise ValueError(
            f"{label}: start rank {normalized_start} exceeds available screened stocks ({total_count})."
        )

    # Ensure the end rank is not before the start rank, then cap it to the dataset size.
    normalized_end = max(normalized_start, int(end_rank))
    if normalized_end > total_count:
        print(f"{label}: adjusted end rank from {normalized_end} to {total_count}.")
        normalized_end = total_count

    # Return a safe inclusive rank window for downstream filtering.
    return normalized_start, normalized_end


def load_ranked_tickers(
    path: Path,
    start_rank: int,
    end_rank: int,
    skip_tickers: Optional[set] = None,
) -> List[Dict[str, object]]:
    # The screening output is the source of truth for which tickers can be analyzed.
    if not path.exists():
        raise FileNotFoundError(f"Missing screening feather: {path}")

    # Load the feather file into a DataFrame for ranking and filtering.
    df = pd.read_feather(path)
    if "Ticker" not in df.columns:
        raise ValueError("Expected `Ticker` column in final_screening_union.feather.")

    # Prefer the richer combined score when present; otherwise fall back to technical score.
    if "combined_score" in df.columns:
        df = df.sort_values("combined_score", ascending=False, kind="stable")
    elif "technical_score" in df.columns:
        df = df.sort_values("technical_score", ascending=False, kind="stable")

    # Standardize ticker symbols and remove duplicates before assigning ranks.
    df = df.dropna(subset=["Ticker"]).copy()
    df["Ticker"] = df["Ticker"].astype(str).str.upper()
    df = df.drop_duplicates(subset=["Ticker"]).reset_index(drop=True)
    df["screen_rank"] = range(1, len(df) + 1)

    # Keep only the requested inclusive rank window.
    start_rank, end_rank = resolve_rank_bounds(len(df), start_rank, end_rank, label="Analysis range")
    df = df[(df["screen_rank"] >= start_rank) & (df["screen_rank"] <= end_rank)].copy()

    # Optionally remove user-specified tickers from the analysis batch.
    if skip_tickers:
        df = df[~df["Ticker"].isin(skip_tickers)].copy()
    if df.empty:
        raise ValueError("No tickers found in screening feather.")

    # Convert the filtered DataFrame into plain dicts for downstream processing.
    return df.to_dict(orient="records")


def list_ticker_package_files(
    ticker: str,
    include_feather: bool,
    max_sec_html_files: int,
    max_file_size_mb: float,
) -> List[Path]:
    # Each ticker gets its own package directory containing the data sent to the analyst agent.
    root = AGENTS_DATA_PACKAGE_DIR / ticker
    if not root.exists():
        raise FileNotFoundError(f"Missing ticker package directory: {root}")

    # Start with the core files that are most useful for the analysis prompt.
    candidates = [
        root / "screening_snapshot.json",
        root / "price_history.csv",
        root / "price_history.feather",
        root / "package_meta.json",
        root / "yahoo" / "fast_info.json",
        root / "yahoo" / "info_selected.json",
        root / "yahoo" / "financials.csv",
        root / "yahoo" / "balance_sheet.csv",
        root / "yahoo" / "cashflow.csv",
        root / "yahoo" / "quarterly_financials.csv",
        root / "yahoo" / "quarterly_balance_sheet.csv",
        root / "yahoo" / "quarterly_cashflow.csv",
        root / "sec" / "selected_filings.csv",
    ]
    files = [p for p in candidates if p.exists()]

    # Add a limited number of raw SEC filing HTML files, which can be helpful but bulky.
    sec_html = sorted((root / "sec" / "filings_html").glob("*.htm"))
    sec_html.extend(sorted((root / "sec" / "filings_html").glob("*.html")))
    if max_sec_html_files >= 0:
        sec_html = sec_html[:max_sec_html_files]
    files.extend(sec_html)

    # Feather files are optional because they can add size without always helping the model.
    if not include_feather:
        files = [p for p in files if p.suffix.lower() != ".feather"]

    # Apply a size cap so oversized artifacts do not bloat uploads or exceed context budgets.
    if max_file_size_mb > 0:
        max_bytes = int(max_file_size_mb * 1024 * 1024)
        files = [p for p in files if p.stat().st_size <= max_bytes]

    # Return only files that actually exist and satisfy the inclusion rules.
    return files


def http_post_json(
    session: requests.Session,
    url: str,
    headers: dict,
    payload: dict,
    timeout: int = 300,
    retries: int = 3,
) -> dict:
    # Keep track of the last exception so the final error message is informative.
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # Submit the request and treat HTTP error responses as retryable failures.
            resp = session.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code >= 400:
                raise RuntimeError(f"{resp.status_code} {resp.text}")
            return resp.json()
        except Exception as exc:
            last_err = exc
            msg = str(exc)

            # Back off more aggressively when the API reports rate limiting.
            if "429" in msg or "rate_limit_exceeded" in msg:
                m = re.search(r"Please try again in ([0-9.]+)s", msg)
                wait_sec = float(m.group(1)) + 1.5 if m else (4.0 * attempt)
                time.sleep(wait_sec)
                continue

            # For other transient failures, do a simpler linear backoff before retrying.
            if attempt < retries:
                time.sleep(2 * attempt)

    # Surface the most recent failure after all retry attempts are exhausted.
    raise RuntimeError(f"POST failed after {retries} attempts: {last_err}")