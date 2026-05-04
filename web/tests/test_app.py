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


def test_output_root_created(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, "OUTPUT_ROOT", tmp_path / "web_jobs")
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    web_app.create_app()

    assert web_app.OUTPUT_ROOT.exists()


def test_app_stores_mongo_store_in_config(monkeypatch):
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    app = web_app.create_app()

    assert "MONGO_STORE" in app.config
    assert app.config["MONGO_STORE"].db is None


def test_index_redirects_to_login_when_logged_out(monkeypatch):
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    app = web_app.create_app()
    app.config["TESTING"] = True

    @app.route("/login")
    def login():
        return "login page"

    client = app.test_client()
    response = client.get("/")

    assert response.status_code in [302, 303]
    assert "/login" in response.location


def test_index_redirects_to_dashboard_when_logged_in(monkeypatch):
    monkeypatch.setattr(web_app, "MongoStore", FakeMongoStore, raising=False)

    app = web_app.create_app()
    app.config["TESTING"] = True

    @app.route("/dashboard")
    def dashboard():
        return "dashboard page"

    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = "test-user"

    response = client.get("/")

    assert response.status_code in [302, 303]
    assert "/dashboard" in response.location