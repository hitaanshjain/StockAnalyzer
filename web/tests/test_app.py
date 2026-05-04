import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import app as web_app


class FakeMongoStore:
    def __init__(self):
        self.db = None


def test_create_app_exists(monkeypatch):
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    app = web_app.create_app()

    assert app is not None
    assert app.name == "app"
    assert app.config["MONGO_STORE"] is not None


def test_app_has_index_route(monkeypatch):
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    app = web_app.create_app()

    routes = [str(rule) for rule in app.url_map.iter_rules()]

    assert "/" in routes