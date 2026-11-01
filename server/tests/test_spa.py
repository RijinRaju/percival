from dataclasses import replace

from fastapi.testclient import TestClient

from percival_server.main import create_app


def test_ui_is_served_with_fallback_and_headers(config, redis_server, tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>percival</html>")
    (static / "assets" / "app-abc123.js").write_text("console.log(1)")

    client = TestClient(create_app(replace(config, static_dir=static)))

    for path in ("/", "/schedules/digest", "/runs?status=failure"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert "percival" in resp.text
        assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]

    assert client.get("/assets/app-abc123.js").text == "console.log(1)"
    # api paths never fall through to the ui
    assert client.get("/api/v1/nope").status_code == 404
    assert client.get("/api/v1/nope").headers["content-type"].startswith("application/json")
    assert client.get("/health").json()["status"] == "ok"


def test_no_static_dir_means_no_ui(client):
    assert client.get("/").status_code == 404
