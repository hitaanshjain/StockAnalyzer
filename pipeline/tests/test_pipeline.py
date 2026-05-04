import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import stocks


def test_chunk_list_splits_list_correctly():
    result = list(stocks.chunk_list([1, 2, 3, 4, 5], 2))
    assert result == [[1, 2], [3, 4], [5]]


def test_pipeline_config_defaults():
    cfg = stocks.PipelineConfig()
    assert cfg.universe_history_years == 3
    assert cfg.min_return_pct == 30.0
    assert cfg.min_last_price == 1.0


def test_sec_headers_uses_env(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "TestAgent test@example.com")
    headers = stocks._sec_headers()
    assert headers["User-Agent"] == "TestAgent test@example.com"
    assert headers["Accept-Encoding"] == "gzip, deflate"