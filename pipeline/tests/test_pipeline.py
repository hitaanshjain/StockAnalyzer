import sys
from pathlib import Path

import pandas as pd

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import stocks


def test_chunk_list_splits_items_into_chunks():
    result = list(stocks.chunk_list([1, 2, 3, 4, 5], 2))
    assert result == [[1, 2], [3, 4], [5]]


def test_pipeline_config_default_values():
    cfg = stocks.PipelineConfig()

    assert cfg.universe_history_years == 3
    assert cfg.min_return_pct == 30.0
    assert cfg.min_last_price == 1.0
    assert cfg.lookback_months == 8


def test_sec_headers_uses_env_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "TestAgent test@example.com")

    headers = stocks._sec_headers()

    assert headers["User-Agent"] == "TestAgent test@example.com"
    assert headers["Accept-Encoding"] == "gzip, deflate"


def test_ensure_dirs_creates_expected_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(stocks, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(stocks, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(stocks, "SCREENING_OUTPUT_DIR", tmp_path / "screening_output")
    monkeypatch.setattr(stocks, "AGENTS_DATA_PACKAGE_DIR", tmp_path / "agents_data_package")
    monkeypatch.setattr(
        stocks,
        "CHART_IMAGES_DIR",
        tmp_path / "screening_output" / "chart_images",
    )

    stocks.ensure_dirs()

    assert stocks.DATA_DIR.exists()
    assert stocks.OUTPUT_DIR.exists()
    assert stocks.SCREENING_OUTPUT_DIR.exists()
    assert stocks.AGENTS_DATA_PACKAGE_DIR.exists()
    assert stocks.CHART_IMAGES_DIR.exists()


def test_build_sec_doc_url_formats_url_correctly():
    url = stocks._build_sec_doc_url(
        "0000320193",
        "0000320193-24-000123",
        "aapl-20240928.htm",
    )

    assert url == (
        "https://www.sec.gov/Archives/edgar/data/"
        "320193/000032019324000123/aapl-20240928.htm"
    )


def test_select_recent_filings_handles_empty_dataframe():
    cfg = stocks.PipelineConfig()

    result = stocks._select_recent_filings(pd.DataFrame(), cfg)

    assert result.empty


def test_select_recent_filings_keeps_latest_forms():
    cfg = stocks.PipelineConfig()
    cfg.sec_num_8k = 2

    df = pd.DataFrame(
        [
            {"form": "10-K", "filingDate": "2023-01-01", "accessionNumber": "old-k"},
            {"form": "10-K", "filingDate": "2025-01-01", "accessionNumber": "new-k"},
            {"form": "10-Q", "filingDate": "2025-02-01", "accessionNumber": "q1"},
            {"form": "10-Q", "filingDate": "2025-03-01", "accessionNumber": "q2"},
            {"form": "10-Q", "filingDate": "2025-04-01", "accessionNumber": "q3"},
            {"form": "8-K", "filingDate": "2025-05-01", "accessionNumber": "eight1"},
            {"form": "8-K", "filingDate": "2025-06-01", "accessionNumber": "eight2"},
            {"form": "8-K", "filingDate": "2025-07-01", "accessionNumber": "eight3"},
        ]
    )

    result = stocks._select_recent_filings(df, cfg)
    accessions = set(result["accessionNumber"])

    assert "new-k" in accessions
    assert "old-k" not in accessions

    assert "q3" in accessions
    assert "q2" in accessions
    assert "q1" not in accessions

    assert "eight3" in accessions
    assert "eight2" in accessions
    assert "eight1" not in accessions


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr("sys.argv", ["stocks.py"])

    args = stocks.parse_args()

    assert args.refresh_metadata is False
    assert args.refresh_insider is False
    assert args.chart_start_rank == 1
    assert args.chart_end_rank == 50
    assert args.package_start_rank == 1
    assert args.package_end_rank is None