import json

import mongomock
import pytest

from mongo_service import client as mclient


def test_resolve_mongo_uri_prefers_argument():
    assert mclient._resolve_mongo_uri("mongodb://manual:27017") == "mongodb://manual:27017"


def test_resolve_mongo_uri_uses_env(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example:27017")
    monkeypatch.delenv("MONGO_URI", raising=False)

    assert mclient._resolve_mongo_uri() == "mongodb://example:27017"


def test_resolve_mongo_uri_falls_back_to_mongo_uri(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_URI", "mongodb://backup:27017")

    assert mclient._resolve_mongo_uri() == "mongodb://backup:27017"


def test_resolve_mongo_uri_default(monkeypatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)

    assert mclient._resolve_mongo_uri() == "mongodb://mongo:27017"


def test_get_client_uses_env(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example:27017")

    c = mclient.get_client()

    assert c is not None


def test_load_json_records_from_list(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps([{"Ticker": "AAPL"}]), encoding="utf-8")

    records = mclient._load_json_records(path)

    assert records == [{"Ticker": "AAPL"}]


def test_load_json_records_from_wrapped_data_key(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"data": [{"Ticker": "MSFT"}]}), encoding="utf-8")

    records = mclient._load_json_records(path)

    assert records == [{"Ticker": "MSFT"}]


def test_load_json_records_from_single_dict(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"Ticker": "TSLA"}), encoding="utf-8")

    records = mclient._load_json_records(path)

    assert records == [{"Ticker": "TSLA"}]


def test_load_json_records_rejects_invalid_structure(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps("not valid"), encoding="utf-8")

    with pytest.raises(ValueError):
        mclient._load_json_records(path)


def test_load_csv_records(tmp_path):
    path = tmp_path / "records.csv"
    path.write_text("Ticker,Company\nAAPL,Apple Inc.\n", encoding="utf-8")

    records = mclient._load_csv_records(path)

    assert records == [{"Ticker": "AAPL", "Company": "Apple Inc."}]


def test_load_records_rejects_unsupported_file_type(tmp_path):
    path = tmp_path / "records.txt"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError):
        mclient._load_records(path)


def test_import_snapshot_dir_missing_directory_raises(tmp_path):
    mc = mongomock.MongoClient()
    missing = tmp_path / "missing"

    with pytest.raises(FileNotFoundError):
        mclient.import_snapshot_dir(mc, "test_db", missing)


def test_import_snapshot_dir_with_no_json_or_csv_raises(tmp_path):
    mc = mongomock.MongoClient()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "ignore.txt").write_text("ignore me", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        mclient.import_snapshot_dir(mc, "test_db", snapshot_dir)


def test_seed_snapshot_dir_idempotent(tmp_path):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    payload = [{"Ticker": "AAPL", "Company": "Apple Inc.", "sector": "Technology"}]
    (snapshot_dir / "tickers.json").write_text(json.dumps(payload), encoding="utf-8")

    mc = mongomock.MongoClient()
    dbname = "seed_test_db"

    mclient.clear_db(mc, db_name=dbname)
    mclient.seed_sample_data(mc, db_name=dbname, snapshot_dir=snapshot_dir)
    first = list(mc[dbname].tickers.find({}, {"_id": 0}))

    assert any(d.get("Ticker") == "AAPL" for d in first)

    mclient.seed_sample_data(mc, db_name=dbname, snapshot_dir=snapshot_dir)
    second = list(mc[dbname].tickers.find({}, {"_id": 0}))

    assert len(second) == len({d["Ticker"] for d in second})


def test_seed_sample_data_uses_env_directory(tmp_path, monkeypatch):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        json.dumps([{"Ticker": "NVDA", "Company": "Nvidia"}]),
        encoding="utf-8",
    )

    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", str(snapshot_dir))

    mc = mongomock.MongoClient()
    imported = mclient.seed_sample_data(mc, db_name="env_db")

    assert imported == ["tickers"]
    assert mc["env_db"].tickers.find_one({"Ticker": "NVDA"}) is not None


def test_get_tickers_returns_list():
    mc = mongomock.MongoClient()
    mc["mydb"].tickers.insert_one({"Ticker": "FOO", "Company": "Foo Inc."})

    out = mclient.get_tickers(mc, db_name="mydb")

    assert isinstance(out, list)
    assert out[0]["Ticker"] == "FOO"

def test_seed_db_main_success(tmp_path, monkeypatch, capsys):
    from mongo_service import seed_db

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        '[{"Ticker": "AAPL", "Company": "Apple Inc."}]',
        encoding="utf-8",
    )

    import mongomock

    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017")
    monkeypatch.setenv("MONGODB_DB_NAME", "stocks_app")
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", str(snapshot_dir))

    monkeypatch.setattr(seed_db, "get_client", lambda uri=None: mongomock.MongoClient())

    seed_db.main()

    output = capsys.readouterr().out
    assert "Imported" in output
    assert "tickers" in output

def test_seed_db_main_failure_exits(monkeypatch, capsys):
    from mongo_service import seed_db

    def fake_get_client(uri=None):
        raise RuntimeError("fake connection failure")

    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017")
    monkeypatch.setenv("MONGODB_DB_NAME", "stocks_app")
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", "fake/path")

    monkeypatch.setattr(seed_db, "get_client", fake_get_client)

    with pytest.raises(SystemExit) as exc_info:
        seed_db.main()

    assert exc_info.value.code == 2

    output = capsys.readouterr().out
    assert "Failed to import snapshot data" in output
    assert "fake connection failure" in output