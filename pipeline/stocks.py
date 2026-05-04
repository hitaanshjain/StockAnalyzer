import io
import json
import math
import os
import re
import shutil
import threading
import time
import warnings
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import pandas as pd
import requests
from dotenv import load_dotenv



warnings.filterwarnings("ignore")  # suppress noisy deprecation warnings
load_dotenv()  # pull in .env vars so we don't have to hardcode credentials


@dataclass
class PipelineConfig:
    # This is basically the script's control panel. Most of the "why did it do that?"
    # questions trace back to one of these thresholds or cache TTLs.
    universe_history_years: int = 3
    universe_min_market_cap: float = 100e6   # $100M floor to skip micro-caps
    universe_max_market_cap: float = 50e9   # $50B ceiling — true small/mid only
    screen_max_market_cap: float = 10e9
    lookback_months: int = 8               # how far back we look at price history
    min_return_pct: float = 30.0           # must be up at least 30% over lookback
    min_trading_days: int = 80
    min_last_price: float = 1.0            # filter out penny stocks
    min_recent_r2: float = 0.85            # trend must be fairly linear
    weight_r2_ratio: float = 0.50
    weight_slope_ratio: float = 0.30
    weight_tnr_ratio: float = 0.20
    ratio_clip_min: float = 0.05
    ratio_clip_max: float = 10.0
    meta_chunk_size: int = 150             # batch size for metadata fetches
    meta_sleep_sec: float = 0.05
    meta_max_workers: int = 4
    metadata_refresh_days: int = 7         # re-download metadata once a week
    download_chunk_size: int = 100
    price_sleep_sec: float = 0.02
    insider_lookback_days: int = 60        # look at last 2 months of insider filings
    insider_score_threshold: float = 25.0
    insider_max_workers: int = 8
    insider_timeout_sec: int = 12
    min_insider_coverage_ratio: float = 0.95
    package_max_workers: int = 6
    package_refresh_days: int = 60         # refresh agent data packages monthly
    sec_min_interval_sec: float = 0.12     # rate-limit SEC requests to stay polite
    sec_timeout_sec: int = 30
    sec_num_8k: int = 10                   # number of recent 8-K filings to pull

#folder paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
SCREENING_OUTPUT_DIR = BASE_DIR / "screening_output"
AGENTS_DATA_PACKAGE_DIR = BASE_DIR / "agents_data_package"
CHART_IMAGES_DIR = SCREENING_OUTPUT_DIR / "chart_images"
PRICE_FEATHER = DATA_DIR / "small_midcap_prices_3y.feather"
META_FEATHER = DATA_DIR / "small_midcap_meta.feather"
INSIDER_FEATHER = DATA_DIR / "insider_latest.feather"
INSIDER_SUMMARY_FEATHER = DATA_DIR / "insider_summary_latest.feather"

#splits a big list into chunks 
def chunk_list(items: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]

#scrapes the nasdaq website to the all the tickers on nasdaq and other exchanges
def download_nasdaq_symbol_dirs() -> Tuple[pd.DataFrame, pd.DataFrame]:
    nasdaq_url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
    other_url = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
    nasdaq_txt = requests.get(nasdaq_url, timeout=30).text
    other_txt = requests.get(other_url, timeout=30).text
    # both files are pipe-delimited; parse them into dataframes and return as a pair
    return pd.read_csv(io.StringIO(nasdaq_txt), sep="|"), pd.read_csv(io.StringIO(other_txt), sep="|")
    lookback_months: int = 8


#remove 1135
def _sec_headers() -> dict:
    # SEC blocks requests without a real email in User-Agent.
    user_agent = os.getenv("SEC_USER_AGENT", "StocksPipeline research your_email@example.com")
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}


# politely wait between requests so we don't get rate-limited or banned
def _throttled_get(url: str, timeout: int, limiter: dict, headers: Optional[dict] = None) -> requests.Response:
    headers = headers or {}
    with limiter["lock"]:
        now = time.time()
        wait = limiter["next_ts"] - now
        if wait > 0:
            time.sleep(wait)
        limiter["next_ts"] = time.time() + limiter["interval"]  # update inside lock to prevent races
    resp = requests.get(url, timeout=timeout, headers=headers)
    resp.raise_for_status()
    return resp


# trims the raw SEC filings list down to just the handful we actually care about
def _select_recent_filings(df_recent: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    if df_recent.empty:
        return df_recent
    df = df_recent.copy()
    df["form_upper"] = df["form"].astype(str).str.upper()
    df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
    # 1 annual, 2 quarterly, N event filings — most recent of each.
    k = df[df["form_upper"] == "10-K"].sort_values("filingDate", ascending=False).head(1)
    q = df[df["form_upper"] == "10-Q"].sort_values("filingDate", ascending=False).head(2)
    e = df[df["form_upper"] == "8-K"].sort_values("filingDate", ascending=False).head(cfg.sec_num_8k)
    out = pd.concat([k, q, e], ignore_index=True)
    return out.drop_duplicates(subset=["accessionNumber"])


def _build_sec_doc_url(cik_10: str, accession_number: str, primary_document: str) -> str:
    # SEC URLs need no dashes in the accession number and no leading zeros in the CIK.
    accession_nodashes = accession_number.replace("-", "")
    cik_no_leading_zeros = str(int(cik_10))
    return f"https://www.sec.gov/Archives/edgar/data/{cik_no_leading_zeros}/{accession_nodashes}/{primary_document}"


def build_agents_data_packages(
    final_df: pd.DataFrame, price_wide: pd.DataFrame, universe_meta: pd.DataFrame, cfg: PipelineConfig
) -> pd.DataFrame:
    AGENTS_DATA_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    ticker_map_url = "https://www.sec.gov/files/company_tickers.json"
    sec_headers = _sec_headers()
    limiter = {"lock": threading.Lock(), "next_ts": 0.0, "interval": cfg.sec_min_interval_sec}

    try:
        ticker_map_resp = _throttled_get(ticker_map_url, cfg.sec_timeout_sec, limiter, headers=sec_headers).json()
        sec_ticker_to_cik = {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10) for v in ticker_map_resp.values()}
    except Exception:
        sec_ticker_to_cik = {}  # SEC unreachable; filings will be skipped

    # Remove stale ticker dirs no longer in the current universe.
    expected_tickers = {str(t).upper() for t in final_df["Ticker"].dropna().astype(str)}
    for child in AGENTS_DATA_PACKAGE_DIR.iterdir():
        if child.is_dir() and child.name.upper() not in expected_tickers:
            shutil.rmtree(child, ignore_errors=True)

    meta_map = (  # keyed by ticker for O(1) lookup below
        universe_meta[["Ticker", "Company", "sector", "industry", "market_cap_num"]]
        .drop_duplicates(subset=["Ticker"])
        .set_index("Ticker")
        .to_dict(orient="index")
    )

    wanted_fields = [
        "shortName",
        "longName",
        "sector",
        "industry",
        "marketCap",
        "enterpriseValue",
        "sharesOutstanding",
        "floatShares",
        "currentPrice",
        "previousClose",
        "fiftyTwoWeekHigh",
        "fiftyTwoWeekLow",
        "averageVolume",
        "averageVolume10days",
        "beta",
        "trailingPE",
        "priceToBook",
        "totalCash",
        "totalDebt",
        "revenueGrowth",
        "grossMargins",
        "operatingMargins",
        "ebitdaMargins",
    ]

    def _save_df(df_obj: pd.DataFrame, csv_path: Path) -> None:
        # skip silently if there's nothing to write
        if df_obj is None or df_obj.empty:
            return
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df_obj.to_csv(csv_path, index=True)

    # normalize anything date-like into a midnight Timestamp, or None if unparseable
    def _to_ts(val) -> Optional[pd.Timestamp]:
        if val is None:
            return None
        ts = pd.to_datetime(val, errors="coerce")
        if pd.isna(ts):
            return None
        return pd.Timestamp(ts).normalize()

    today = pd.Timestamp.now().normalize()

    # builds the full data folder for a single ticker — Yahoo + SEC filings
    def _build_one(row: pd.Series) -> dict:
        ticker = str(row["Ticker"]).upper()
        pkg_dir = AGENTS_DATA_PACKAGE_DIR / _safe_filename(ticker)
        yahoo_dir = pkg_dir / "yahoo"
        sec_dir = pkg_dir / "sec"
        filings_dir = sec_dir / "filings_html"
        package_meta_path = pkg_dir / "package_meta.json"
        for d in [pkg_dir, yahoo_dir, sec_dir, filings_dir]:
            d.mkdir(parents=True, exist_ok=True)

        out = {"Ticker": ticker, "package_dir": str(pkg_dir), "package_status": "ok", "package_error": "", "cache_hit": False}
        try:
            existing_meta = {}
            if package_meta_path.exists():
                try:
                    existing_meta = json.loads(package_meta_path.read_text(encoding="utf-8"))
                except Exception:
                    existing_meta = {}

            package_asof = _to_ts(existing_meta.get("package_asof_date"))
            package_age_days = (today - package_asof).days if package_asof is not None else 99999
            is_package_fresh = package_age_days <= cfg.package_refresh_days  # treat missing as ancient

            cik_10 = sec_ticker_to_cik.get(ticker)
            out["cik_10"] = cik_10

            sec_has_new = True
            latest_selected_df = pd.DataFrame()
            latest_sec_filing_date = None
            if cik_10:
                # Cheap freshness check first: if SEC has not posted anything newer than what
                # we already packaged, we can skip rebuilding the whole folder.
                try:
                    submissions_url = f"https://data.sec.gov/submissions/CIK{cik_10}.json"
                    submissions = _throttled_get(submissions_url, cfg.sec_timeout_sec, limiter, headers=sec_headers).json()
                    recent = submissions.get("filings", {}).get("recent", {})
                    df_recent = pd.DataFrame(recent) if isinstance(recent, dict) else pd.DataFrame()
                    latest_selected_df = _select_recent_filings(df_recent, cfg) if not df_recent.empty else pd.DataFrame()
                    if not latest_selected_df.empty and "filingDate" in latest_selected_df.columns:
                        latest_sec_filing_date = pd.to_datetime(latest_selected_df["filingDate"], errors="coerce").max()
                        latest_sec_filing_date = None if pd.isna(latest_sec_filing_date) else pd.Timestamp(latest_sec_filing_date).normalize()
                    prev_last = _to_ts(existing_meta.get("last_sec_filing_date"))
                    sec_has_new = True if prev_last is None or latest_sec_filing_date is None else (latest_sec_filing_date > prev_last)
                except Exception:
                    sec_has_new = False if is_package_fresh else True

            if is_package_fresh and (not sec_has_new):
                out["package_status"] = "cached"
                out["cache_hit"] = True
                return out

            summary = {k: _json_safe(v) for k, v in row.to_dict().items()}
            summary.update(meta_map.get(ticker, {}))
            with open(pkg_dir / "screening_snapshot.json", "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, default=str)

            if ticker in price_wide.columns:
                s = price_wide[ticker].dropna().to_frame("close").reset_index()
                s.columns = ["date", "close"]
                s.to_feather(pkg_dir / "price_history.feather")
                s.to_csv(pkg_dir / "price_history.csv", index=False)

            tk = yf.Ticker(ticker)
            fast_info = {}
            try:
                fi = getattr(tk, "fast_info", {})
                fast_info = dict(fi) if fi is not None else {}
            except Exception:
                fast_info = {}
            with open(yahoo_dir / "fast_info.json", "w", encoding="utf-8") as f:
                json.dump({k: _json_safe(v) for k, v in fast_info.items()}, f, indent=2, default=str)

            info = {}
            try:
                info = tk.info or {}
            except Exception:
                info = {}
            info_subset = {k: _json_safe(info.get(k, None)) for k in wanted_fields}
            with open(yahoo_dir / "info_selected.json", "w", encoding="utf-8") as f:
                json.dump(info_subset, f, indent=2, default=str)

            _save_df(getattr(tk, "financials", pd.DataFrame()), yahoo_dir / "financials.csv")
            _save_df(getattr(tk, "balance_sheet", pd.DataFrame()), yahoo_dir / "balance_sheet.csv")
            _save_df(getattr(tk, "cashflow", pd.DataFrame()), yahoo_dir / "cashflow.csv")
            _save_df(getattr(tk, "quarterly_financials", pd.DataFrame()), yahoo_dir / "quarterly_financials.csv")
            _save_df(getattr(tk, "quarterly_balance_sheet", pd.DataFrame()), yahoo_dir / "quarterly_balance_sheet.csv")
            _save_df(getattr(tk, "quarterly_cashflow", pd.DataFrame()), yahoo_dir / "quarterly_cashflow.csv")

            if cik_10:
                if latest_selected_df.empty:
                    try:
                        submissions_url = f"https://data.sec.gov/submissions/CIK{cik_10}.json"
                        submissions = _throttled_get(submissions_url, cfg.sec_timeout_sec, limiter, headers=sec_headers).json()
                        recent = submissions.get("filings", {}).get("recent", {})
                        df_recent = pd.DataFrame(recent) if isinstance(recent, dict) else pd.DataFrame()
                        latest_selected_df = _select_recent_filings(df_recent, cfg) if not df_recent.empty else pd.DataFrame()
                    except Exception:
                        latest_selected_df = pd.DataFrame()
                if not latest_selected_df.empty:
                    latest_selected_df.to_csv(sec_dir / "selected_filings.csv", index=False)
                    if filings_dir.exists():
                        shutil.rmtree(filings_dir, ignore_errors=True)
                    filings_dir.mkdir(parents=True, exist_ok=True)
                    for _, frow in latest_selected_df.iterrows():
                        acc = str(frow.get("accessionNumber", "")).strip()
                        doc = str(frow.get("primaryDocument", "")).strip()
                        if not acc or not doc:
                            continue
                        doc_url = _build_sec_doc_url(cik_10, acc, doc)
                        try:
                            content = _throttled_get(doc_url, 60, limiter, headers=sec_headers).content
                            save_name = _safe_filename(f"{acc}_{doc}")
                            with open(filings_dir / save_name, "wb") as fw:
                                fw.write(content)
                        except Exception:
                            continue  # one bad filing shouldn't blow up the rest

            latest_10k = None
            latest_10q = None
            latest_8k = None
            if not latest_selected_df.empty and "form" in latest_selected_df.columns and "filingDate" in latest_selected_df.columns:
                tmp = latest_selected_df.copy()
                tmp["form"] = tmp["form"].astype(str).str.upper()
                tmp["filingDate"] = pd.to_datetime(tmp["filingDate"], errors="coerce")
                if not tmp[tmp["form"] == "10-K"].empty:
                    latest_10k = str(tmp[tmp["form"] == "10-K"]["filingDate"].max().date())
                if not tmp[tmp["form"] == "10-Q"].empty:
                    latest_10q = str(tmp[tmp["form"] == "10-Q"]["filingDate"].max().date())
                if not tmp[tmp["form"] == "8-K"].empty:
                    latest_8k = str(tmp[tmp["form"] == "8-K"]["filingDate"].max().date())

            package_meta = {
                "ticker": ticker,
                "package_asof_date": str(today.date()),
                "package_age_days": 0,
                "cik_10": cik_10,
                "last_sec_filing_date": str(latest_sec_filing_date.date()) if latest_sec_filing_date is not None else existing_meta.get("last_sec_filing_date"),
                "last_10k_date": latest_10k,
                "last_10q_date": latest_10q,
                "last_8k_date": latest_8k,
                "refreshed_due_to_new_sec": bool(sec_has_new),
            }
            package_meta_path.write_text(json.dumps(package_meta, indent=2), encoding="utf-8")
            return out
        except Exception as exc:
            out["package_status"] = "error"
            out["package_error"] = str(exc)
            return out

    results = []
    # cap workers so we don't hammer the SEC or Yahoo with too many parallel connections
    worker_count = min(max(1, cfg.package_max_workers), max(1, len(final_df)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_build_one, row) for _, row in final_df.iterrows()]
        with tqdm(total=len(futures), desc="Building agent data packages", unit="ticker") as pbar:
            for future in as_completed(futures):
                results.append(future.result())
                pbar.update(1)
    return pd.DataFrame(results).sort_values("Ticker").reset_index(drop=True)

# make sure all output folders exist before anything tries to write to them
def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCREENING_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    AGENTS_DATA_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    CHART_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# all the knobs you can tweak from the command line without touching the code
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stock screening and data package pipeline")
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Force full metadata refresh from Yahoo (ignore metadata cache age).",
    )
    parser.add_argument(
        "--metadata-refresh-days",
        type=int,
        default=None,
        help="Override metadata cache TTL in days (default: 7).",
    )
    parser.add_argument(
        "--refresh-insider",
        action="store_true",
        help="Force insider cache refresh (ignore insider cache freshness).",
    )
    parser.add_argument(
        "--chart-start-rank",
        type=int,
        default=1,
        help="Start rank for the screening chart PDF bundle.",
    )
    parser.add_argument(
        "--chart-end-rank",
        type=int,
        default=50,
        help="End rank for the screening chart PDF bundle.",
    )
    parser.add_argument(
        "--package-start-rank",
        type=int,
        default=1,
        help="Start rank for building per-ticker agent data packages.",
    )
    parser.add_argument(
        "--package-end-rank",
        type=int,
        default=None,
        help="End rank for building per-ticker agent data packages. Defaults to all screened names.",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    cfg = PipelineConfig()
    if args.metadata_refresh_days is not None and args.metadata_refresh_days >= 0:
        cfg.metadata_refresh_days = int(args.metadata_refresh_days)
    ensure_dirs()

    print("1) Building universe and metadata...")
    raw_universe = build_us_common_stock_universe()
    meta = update_metadata_cache(raw_universe, cfg, force_refresh=bool(args.refresh_metadata))
    universe_meta = raw_universe.merge(meta, on="Ticker", how="left")
    universe_meta = universe_meta[universe_meta["quoteType"] == "EQUITY"].copy()
    universe_meta = universe_meta[
        (universe_meta["market_cap_num"] >= cfg.universe_min_market_cap)
        & (universe_meta["market_cap_num"] <= cfg.universe_max_market_cap)
    ].copy()
    universe_meta = universe_meta.reset_index(drop=True)
    print(f"Universe size (100M-50B): {len(universe_meta)}")

    print("2) Refreshing cached price data...")
    price_long = update_price_cache(universe_meta, cfg)
    print(f"Price rows: {len(price_long)}")
    price_wide = price_long.pivot(index="date", columns="Ticker", values="close").sort_index()

    print("3) Running insider pipeline first (all candidate tickers)...")
    # Insider is run on the broad candidate set before the technical filter so the final
    # union can still include names that are interesting only because of insider activity.
    candidate_tickers = sorted(set(price_wide.columns).intersection(set(universe_meta["Ticker"])))
    market_cap_map = universe_meta.set_index("Ticker")["market_cap_num"].to_dict()
    insider_ranked_df, insider_raw = update_insider_cache(
        candidate_tickers,
        cfg,
        market_cap_map=market_cap_map,
        force_refresh=bool(args.refresh_insider),
    )
    print(f"Insider summary rows: {len(insider_ranked_df)}")

    print("4) Running technical screen second...")
    technical_df, _ = build_screen(universe_meta, price_long, cfg)
    print(f"Technical pass rows: {len(technical_df)}")

    print("5) Building combined ranking (technical + insider)...")
    combined_df = merge_insider_data(technical_df, insider_ranked_df)
    # if insider coverage is sparse the combined score is basically meaningless, so fail loud
    validate_insider_coverage(combined_df, cfg.min_insider_coverage_ratio)
    combined_df = add_normalized_scores(combined_df)
    combined_df = combined_df.sort_values(
        by=["combined_score", "technical_score", "recent_r2", "recent_log_slope"],
        ascending=False,
    ).reset_index(drop=True)

    print("6) Building final deduped screening union...")
    final_df = build_screening_union_df(
        technical_df=combined_df,
        insider_ranked_df=insider_ranked_df,
        universe_meta=universe_meta,
        insider_threshold=cfg.insider_score_threshold,
    )
    final_df = rank_screening_df(final_df)
    chart_start_rank, chart_end_rank = resolve_rank_bounds(
        len(final_df),
        args.chart_start_rank,
        args.chart_end_rank,
        label="Chart range",
    )
    package_start_rank, package_end_rank = resolve_rank_bounds(
        len(final_df),
        args.package_start_rank,
        args.package_end_rank,
        label="Package range",
    )
    package_df = select_rank_range(final_df, start_rank=package_start_rank, end_rank=package_end_rank)

    insider_ranked_path = SCREENING_OUTPUT_DIR / "insider_ranked.csv"
    combined_ranked_path = SCREENING_OUTPUT_DIR / "combined_ranked.csv"
    feather_path = SCREENING_OUTPUT_DIR / "final_screening_union.feather"
    csv_path = SCREENING_OUTPUT_DIR / "final_screening_union.csv"
    pdf_path = SCREENING_OUTPUT_DIR / "final_screening_charts.pdf"
    chart_manifest_path = SCREENING_OUTPUT_DIR / "chart_manifest.csv"

    insider_ranked_df.to_csv(insider_ranked_path, index=False)
    combined_df.to_csv(combined_ranked_path, index=False)
    save_feather(final_df, feather_path)
    final_df.to_csv(csv_path, index=False)

    print("7) Generating chart artifacts for screening names...")
    chart_manifest_df = build_chart_images_for_screening(final_df, price_wide, cfg, CHART_IMAGES_DIR)
    chart_manifest_df.to_csv(chart_manifest_path, index=False)
    selected_chart_rows = build_chart_pdf_for_screening(
        final_df,
        price_wide,
        cfg,
        pdf_path,
        start_rank=chart_start_rank,
        end_rank=chart_end_rank,
    )

    print("8) Building per-ticker agent data packages (Yahoo + SEC)...")
    package_manifest_df = build_agents_data_packages(package_df, price_wide, universe_meta, cfg)
    package_manifest_path = SCREENING_OUTPUT_DIR / "agents_data_package_manifest.csv"
    package_manifest_df.to_csv(package_manifest_path, index=False)

    mongo = get_mongo_store()
    screening_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")  # used as a unique key for this run
    if mongo is not None:
        mongo.upsert_global_cache(
            "latest_screening_snapshot",
            {
                "screening_run_id": screening_run_id,
                "universe_size": int(len(universe_meta)),
                "technical_rows": int(len(technical_df)),
                "final_rows": int(len(final_df)),
                "latest_market_day": str(get_latest_market_trading_day().date()),
                "final_ranked_stocks": final_df.to_dict(orient="records"),
                "chart_manifest": chart_manifest_df.to_dict(orient="records"),
                "artifact_paths": {
                    "final_feather": str(feather_path),
                    "final_csv": str(csv_path),
                    "chart_manifest_csv": str(chart_manifest_path),
                    "screening_pdf": str(pdf_path),
                    "package_manifest_csv": str(package_manifest_path),
                },
                "selected_package_tickers": package_df[["Ticker", "screen_rank"]].to_dict(orient="records"),
            },
        )
        mongo.upsert_screening_run(
            screening_run_id,
            {
                "created_at": datetime.utcnow().isoformat(),
                "config": vars(cfg),
                "chart_range": {
                    "start_rank": int(chart_start_rank),
                    "end_rank": int(chart_end_rank),
                },
                "package_range": {
                    "start_rank": int(package_start_rank),
                    "end_rank": int(package_end_rank),
                },
                "technical_rows": int(len(technical_df)),
                "final_rows": int(len(final_df)),
                "selected_chart_tickers": selected_chart_rows.to_dict(orient="records"),
                "selected_package_tickers": package_df[["Ticker", "screen_rank"]].to_dict(orient="records"),
                "final_ranked_stocks": final_df.to_dict(orient="records"),
                "artifact_paths": {
                    "final_feather": str(feather_path),
                    "final_csv": str(csv_path),
                    "screening_pdf": str(pdf_path),
                    "chart_manifest_csv": str(chart_manifest_path),
                    "package_manifest_csv": str(package_manifest_path),
                },
            },
        )

    print("Done.")
    print(f"Technical rows: {len(technical_df)}")
    print(f"Insider rows with score > {cfg.insider_score_threshold}: {(insider_ranked_df['insider_score_60d'] > cfg.insider_score_threshold).sum()}")
    print(f"Saved insider ranking: {insider_ranked_path}")
    print(f"Saved combined ranking: {combined_ranked_path}")
    print(f"Final deduped rows: {len(final_df)}")
    print(f"Saved final feather: {feather_path}")
    print(f"Saved final csv: {csv_path}")
    print(f"Saved chart manifest: {chart_manifest_path}")
    print(f"Saved charts pdf: {pdf_path}")
    print(f"Saved data package manifest: {package_manifest_path}")
    print(f"Saved data packages root: {AGENTS_DATA_PACKAGE_DIR}")


if __name__ == "__main__":
    main()
