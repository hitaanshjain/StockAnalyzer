import importlib
import sys
import types
from pathlib import Path

import pytest

PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

def load_agent_workflow(monkeypatch):
    fake_mongo_store = types.ModuleType("mongo_store")
    fake_mongo_store.get_mongo_store = lambda: None
    monkeypatch.setitem(sys.modules, "mongo_store", fake_mongo_store)
    sys.modules.pop("agent_workflow", None)
    return importlib.import_module("agent_workflow")


def test_get_api_key_reads_openai_api_key(monkeypatch):
    agent_workflow = load_agent_workflow(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("OPENAI_KEY", raising=False)

    assert agent_workflow.get_api_key() == "fake-key"


def test_get_api_key_reads_backup_key(monkeypatch):
    agent_workflow = load_agent_workflow(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_KEY", "backup-key")

    assert agent_workflow.get_api_key() == "backup-key"


def test_get_api_key_raises_if_missing(monkeypatch):
    agent_workflow = load_agent_workflow(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_KEY", raising=False)

    with pytest.raises(RuntimeError):
        agent_workflow.get_api_key()


def test_build_run_dirs_creates_folders(tmp_path, monkeypatch):
    agent_workflow = load_agent_workflow(monkeypatch)
    monkeypatch.setattr(agent_workflow, "OUTPUT_ROOT", tmp_path)

    dirs = agent_workflow.build_run_dirs("test-run")

    assert dirs["root"].exists()
    assert dirs["per_stock"].exists()
    assert dirs["charts"].exists()
    assert dirs["uploaded"].exists()
    assert dirs["root"].name == "test-run"


def test_agent_parse_args_defaults(monkeypatch):
    agent_workflow = load_agent_workflow(monkeypatch)
    monkeypatch.setattr("sys.argv", ["agent_workflow.py"])

    args = agent_workflow.parse_args()

    assert args.start_rank == 1
    assert args.end_rank == 5
    assert args.max_workers == 2
    assert args.reasoning_effort == "low"
    assert args.user_id == "local-user"
