import json

import mongomock
import pytest

from mongo_service import client as mclient


# shared fixture — gives us a clean in-memory mongo client for each test
@pytest.fixture
def mock_client(monkeypatch):
    mc = mongomock.MongoClient()
    monkeypatch.setattr(mclient, "get_client", lambda uri=None: mc)
    return mc


# --- seeding and retrieving tickers ---

def test_seed_and_get_tickers(mock_client, tmp_path):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        json.dumps(
            [
                {"Ticker": "AAPL", "Company": "Apple Inc.", "sector": "Technology"},
                {"Ticker": "MSFT", "Company": "Microsoft Corp.", "sector": "Technology"},
            ]
        ),
        encoding="utf-8",
    )
    # also seed a csv to make sure mixed file types work
    (snapshot_dir / "sessions.csv").write_text(
        "run,status\nseed,ok\n", encoding="utf-8"
    )

    client = mclient.get_client()
    assert client.list_database_names() == []
    mclient.seed_sample_data(client, db_name="test_db", snapshot_dir=snapshot_dir)
    assert "test_db" in client.list_database_names()
    tickers = mclient.get_tickers(client, db_name="test_db")
    assert isinstance(tickers, list)
    assert any(d.get("Ticker") == "AAPL" for d in tickers)


def test_clear_db(mock_client, tmp_path):
    # Seed then wipe — the db should be completely gone afterwards.
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        json.dumps([{"Ticker": "TSLA", "Company": "Tesla, Inc.", "sector": "Automotive"}]),
        encoding="utf-8",
    )

    client = mclient.get_client()
    mclient.seed_sample_data(client, db_name="to_clear", snapshot_dir=snapshot_dir)
    assert "to_clear" in client.list_database_names()
    mclient.clear_db(client, db_name="to_clear")
    assert "to_clear" not in client.list_database_names()


def test_get_tickers_returns_list():
    # Direct insert bypasses seeding; just checks that get_tickers wraps results in a list.
    mc = mongomock.MongoClient()
    mc["mydb"].tickers.insert_one({"Ticker": "FOO", "Company": "Foo Inc."})
    out = mclient.get_tickers(mc, db_name="mydb")
    assert isinstance(out, list)
    assert out[0]["Ticker"] == "FOO"


# --- URI resolution ---
# Priority order: explicit arg > MONGODB_URI > MONGO_URI > hardcoded default

def test_resolve_mongo_uri_prefers_argument():
    assert mclient._resolve_mongo_uri("mongodb://manual:27017") == "mongodb://manual:27017"

def test_resolve_mongo_uri_uses_env(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example:27017")
    monkeypatch.delenv("MONGO_URI", raising=False)
    assert mclient._resolve_mongo_uri() == "mongodb://example:27017"

def test_resolve_mongo_uri_falls_back_to_mongo_uri(monkeypatch):
    # MONGO_URI is the secondary env var when MONGODB_URI isn't set.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setenv("MONGO_URI", "mongodb://backup:27017")
    assert mclient._resolve_mongo_uri() == "mongodb://backup:27017"

def test_resolve_mongo_uri_default(monkeypatch):
    # No env vars at all — should land on the hardcoded docker-compose default.
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    assert mclient._resolve_mongo_uri() == "mongodb://mongo:27017"

def test_get_client_uses_env(monkeypatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example:27017")
    assert mclient.get_client() is not None


# --- loading records from files ---
# The loader handles three JSON shapes: bare list, {"data": [...]}, and a single dict.

def test_load_json_records_from_list(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps([{"Ticker": "AAPL"}]), encoding="utf-8")
    assert mclient._load_json_records(path) == [{"Ticker": "AAPL"}]

def test_load_json_records_from_wrapped_data_key(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"data": [{"Ticker": "MSFT"}]}), encoding="utf-8")
    assert mclient._load_json_records(path) == [{"Ticker": "MSFT"}]

def test_load_json_records_from_single_dict(tmp_path):
    # A single object should be wrapped in a list so callers always get a list back.
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"Ticker": "TSLA"}), encoding="utf-8")
    assert mclient._load_json_records(path) == [{"Ticker": "TSLA"}]

def test_load_json_records_rejects_invalid_structure(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(json.dumps("not valid"), encoding="utf-8")
    with pytest.raises(ValueError):
        mclient._load_json_records(path)

def test_load_csv_records(tmp_path):
    path = tmp_path / "records.csv"
    path.write_text("Ticker,Company\nAAPL,Apple Inc.\n", encoding="utf-8")
    assert mclient._load_csv_records(path) == [{"Ticker": "AAPL", "Company": "Apple Inc."}]

def test_load_records_rejects_unsupported_file_type(tmp_path):
    # Anything that isn't .json or .csv should raise, not silently return nothing.
    path = tmp_path / "records.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        mclient._load_records(path)


# --- error cases for import ---

def test_import_snapshot_dir_missing_directory_raises(tmp_path):
    # Passing a nonexistent path should fail loudly instead of silently importing nothing.
    mc = mongomock.MongoClient()
    with pytest.raises(FileNotFoundError):
        mclient.import_snapshot_dir(mc, "test_db", tmp_path / "missing")

def test_import_snapshot_dir_with_no_json_or_csv_raises(tmp_path):
    # A directory full of unrecognized files is treated as an error, not an empty import.
    mc = mongomock.MongoClient()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "ignore.txt").write_text("ignore me", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        mclient.import_snapshot_dir(mc, "test_db", snapshot_dir)


# --- seeding behavior ---

# seeding twice shouldn't create duplicate records
def test_seed_snapshot_dir_idempotent(tmp_path):
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    payload = [{"Ticker": "AAPL", "Company": "Apple Inc.", "sector": "Technology"}]
    (snapshot_dir / "tickers.json").write_text(json.dumps(payload), encoding="utf-8")

    mc = mongomock.MongoClient()
    mclient.clear_db(mc, db_name="seed_test_db")
    mclient.seed_sample_data(mc, db_name="seed_test_db", snapshot_dir=snapshot_dir)
    first = list(mc["seed_test_db"].tickers.find({}, {"_id": 0}))
    assert any(d.get("Ticker") == "AAPL" for d in first)

    mclient.seed_sample_data(mc, db_name="seed_test_db", snapshot_dir=snapshot_dir)
    second = list(mc["seed_test_db"].tickers.find({}, {"_id": 0}))
    assert len(second) == len({d["Ticker"] for d in second})

def test_seed_sample_data_uses_env_directory(tmp_path, monkeypatch):
    # When no snapshot_dir arg is given, the function should fall back to PIPELINE_OUTPUT_DIR.
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        json.dumps([{"Ticker": "NVDA", "Company": "Nvidia"}]), encoding="utf-8"
    )
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", str(snapshot_dir))

    mc = mongomock.MongoClient()
    imported = mclient.seed_sample_data(mc, db_name="env_db")
    assert imported == ["tickers"]
    assert mc["env_db"].tickers.find_one({"Ticker": "NVDA"}) is not None


# --- seed_db.main ---

def test_seed_db_main_success(tmp_path, monkeypatch, capsys):
    # Full happy-path run: env vars wired, snapshot present, output should mention the collection.
    from mongo_service import seed_db

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "tickers.json").write_text(
        '[{"Ticker": "AAPL", "Company": "Apple Inc."}]', encoding="utf-8"
    )

    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017")
    monkeypatch.setenv("MONGODB_DB_NAME", "stocks_app")
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", str(snapshot_dir))
    monkeypatch.setattr(seed_db, "get_client", lambda uri=None: mongomock.MongoClient())

    seed_db.main()
    output = capsys.readouterr().out
    assert "Imported" in output
    assert "tickers" in output

# connection failures should print an error and exit with code 2
def test_seed_db_main_failure_exits(monkeypatch, capsys):
    from mongo_service import seed_db

    monkeypatch.setenv("MONGODB_URI", "mongodb://fake:27017")
    monkeypatch.setenv("MONGODB_DB_NAME", "stocks_app")
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", "fake/path")
    monkeypatch.setattr(seed_db, "get_client", lambda uri=None: (_ for _ in ()).throw(RuntimeError("fake connection failure")))

    with pytest.raises(SystemExit) as exc_info:
        seed_db.main()
    assert exc_info.value.code == 2
    output = capsys.readouterr().out
    assert "Failed to import snapshot data" in output
