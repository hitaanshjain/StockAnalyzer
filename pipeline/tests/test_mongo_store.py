import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from mongo_store import MongoStore, _clean_doc, get_mongo_store


# --- _clean_doc: make sure all the weird types get converted correctly ---

def test_clean_doc_dict():
    assert _clean_doc({"a": 1}) == {"a": 1}

def test_clean_doc_list():
    assert _clean_doc([1, 2, 3]) == [1, 2, 3]

def test_clean_doc_tuple():
    assert _clean_doc((1, 2)) == [1, 2]

def test_clean_doc_set():
    assert _clean_doc({42}) == [42]

def test_clean_doc_path():
    assert _clean_doc(Path("/tmp/foo")) == "/tmp/foo"

def test_clean_doc_datetime():
    result = _clean_doc(datetime(2024, 1, 1, 12, 0, 0))
    assert result == "2024-01-01T12:00:00"

def test_clean_doc_date():
    result = _clean_doc(date(2024, 6, 15))
    assert result == "2024-06-15"

def test_clean_doc_pandas_timestamp():
    result = _clean_doc(pd.Timestamp("2024-03-01"))
    assert "2024-03-01" in result

def test_clean_doc_numpy_integer():
    result = _clean_doc(np.int64(99))
    assert result == 99
    assert isinstance(result, int)

def test_clean_doc_numpy_float_normal():
    result = _clean_doc(np.float64(2.71))
    assert abs(result - 2.71) < 1e-6

# NaN values should come back as None so MongoDB doesn't choke
def test_clean_doc_numpy_float_nan():
    assert _clean_doc(np.float64(np.nan)) is None

def test_clean_doc_float_nan():
    assert _clean_doc(float("nan")) is None

def test_clean_doc_pd_na():
    assert _clean_doc(pd.NA) is None

def test_clean_doc_string_passthrough():
    assert _clean_doc("hello") == "hello"

def test_clean_doc_int_passthrough():
    assert _clean_doc(7) == 7

# nested structures should be cleaned recursively
def test_clean_doc_nested():
    result = _clean_doc({"vals": [np.int64(1), np.float64(2.0)]})
    assert result == {"vals": [1, 2.0]}


# --- MongoStore with no URI: should fail gracefully, not crash ---

def test_mongo_store_no_uri_db_is_none(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    store = MongoStore(uri="")
    assert store.db is None
    assert store.enabled is False

def test_mongo_store_col_raises_when_no_db():
    store = MongoStore(uri="")
    with pytest.raises(RuntimeError, match="not configured"):
        store._col("users")


# --- MongoStore with a mocked client: test the real logic ---

def test_mongo_store_connects_successfully():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        assert store.enabled is True

# connection errors should be swallowed, not bubble up
def test_mongo_store_connect_handles_exception():
    with patch("mongo_store.MongoClient", side_effect=Exception("conn error")):
        store = MongoStore(uri="mongodb://fake:27017")
        assert store.enabled is False

def test_mongo_store_upsert_user():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.upsert_user("uid-1", email="a@b.com", password_hash="hashed")
        store.db["users"].update_one.assert_called()

# calling without email/hash should still work
def test_mongo_store_upsert_user_no_email_or_hash():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.upsert_user("uid-2")
        store.db["users"].update_one.assert_called()

def test_mongo_store_upsert_global_cache():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.upsert_global_cache("cache-key", {"x": 1})
        store.db["global_cache"].update_one.assert_called()

def test_mongo_store_upsert_screening_run():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.upsert_screening_run("run-1", {"status": "done"})
        store.db["screening_runs"].update_one.assert_called()

def test_mongo_store_create_analysis_session():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client["test_db"]["analysis_sessions"].insert_one.return_value = MagicMock(inserted_id="sess-abc")
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        result = store.create_analysis_session({"user_id": "u1"})
        assert isinstance(result, str)

# valid ObjectId string — should use _id selector
def test_mongo_store_update_analysis_session_valid_id():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.update_analysis_session("507f1f77bcf86cd799439011", {"status": "done"})
        store.db["analysis_sessions"].update_one.assert_called()

# invalid id string — should fall back to session_key selector
def test_mongo_store_update_analysis_session_invalid_id():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.update_analysis_session("not-an-object-id", {"status": "done"})
        store.db["analysis_sessions"].update_one.assert_called()

def test_mongo_store_upsert_stock_report():
    with patch("mongo_store.MongoClient") as mock_cls:
        mock_cls.return_value = MagicMock()
        store = MongoStore(uri="mongodb://fake:27017", db_name="test_db")
        store.upsert_stock_report("sess-1", "AAPL", {"score": 9.5})
        store.db["stock_reports"].update_one.assert_called()


# --- get_mongo_store ---

def test_get_mongo_store_returns_none_without_uri(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    result = get_mongo_store()
    assert result is None

def test_get_mongo_store_returns_none_on_exception(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017")
    with patch("mongo_store.MongoClient", side_effect=Exception("fail")):
        result = get_mongo_store()
        assert result is None
