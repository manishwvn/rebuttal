"""The built dashboard is served from the API's own origin without shadowing any API route."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rebuttal.app import frontend_dir, mount_frontend


@pytest.fixture
def client(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>INDEX</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/webhooks/paypal")
    def hook():
        return {"hook": True}

    mount_frontend(app, tmp_path)  # after the API routes, as in rebuttal.app
    return TestClient(app)


def test_index_served_at_root_and_deep_paths_fall_back(client):
    assert "INDEX" in client.get("/").text
    assert "INDEX" in client.get("/some/deep/path").text
    assert client.head("/").status_code == 200
    assert client.get("/%00").status_code == 200


def test_never_serves_files_outside_the_directory(tmp_path):
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("INDEX")
    (tmp_path / "secret.txt").write_text("SECRET")
    (site / "link.txt").symlink_to(tmp_path / "secret.txt")
    app = FastAPI()
    mount_frontend(app, site)
    c = TestClient(app)
    for path in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/link.txt"):
        assert "SECRET" not in c.get(path).text


def test_static_files_are_served(client):
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"


def test_api_routes_are_not_shadowed(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.post("/api/webhooks/paypal").json() == {"hook": True}


def test_unknown_api_path_is_json_404(client):
    for path in ("/api/x", "/api", "/api/x/y"):
        response = client.get(path)
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}


def test_absent_directory_means_no_mount(tmp_path, monkeypatch):
    monkeypatch.setenv("REBUTTAL_FRONTEND_DIR", str(tmp_path / "missing"))
    assert frontend_dir() is None
    app = FastAPI()
    mount_frontend(app, None)
    assert TestClient(app).get("/").status_code == 404
    (tmp_path / "index.html").write_text("x")
    monkeypatch.setenv("REBUTTAL_FRONTEND_DIR", str(tmp_path))
    assert frontend_dir() == tmp_path
