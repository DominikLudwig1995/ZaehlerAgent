from fastapi.testclient import TestClient

from app.config import load_meters
from app.main import app, healthz


def test_healthz():
    assert healthz() == {"status": "ok"}


def test_meters_file_is_valid():
    meters = {m.name: m for m in load_meters("tests/meters.yml")}
    assert meters["gas"].digits == 7 and meters["wasser"].digits == 8
    assert meters["gas"].device_class == "gas" and meters["wasser"].device_class == "water"
    assert all(m.max_rate_per_hour > 0 and len(m.crop) == 4 for m in meters.values())


def test_status_and_poll_endpoints(monkeypatch):
    monkeypatch.setenv("METERS_FILE", "tests/meters.yml")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    with TestClient(app) as client:
        assert set(client.get("/status").json()) == {"gas", "wasser"}
        assert client.post("/poll/unbekannt").status_code == 404


def test_ui_metrics_and_history_endpoints(monkeypatch):
    monkeypatch.setenv("CONFIG_FILE", "tests/meters.yml")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("INTERVAL_SECONDS", "3600")
    with TestClient(app) as client:
        assert "zaehler-agent" in client.get("/").text
        cfg = client.get("/api/config").json()
        assert {m["name"] for m in cfg["meters"]} == {"gas", "wasser"}
        assert "zaehler_up 1" in client.get("/metrics").text
        h = client.get("/api/history/gas").json()
        assert h["series"] == [] or isinstance(h["series"], list)
        assert client.get("/api/history/x").status_code == 404
        assert client.get("/api/image/gas").status_code in (404, 200)
        assert client.get("/api/image/x").status_code == 404


def test_example_config_is_valid():
    from app.config import Settings

    s = Settings.load({"CONFIG_FILE": "config/config.example.yml"})
    assert s.meters and s.models and s.llm_base_url.startswith("https://")


def test_build_service_passes_base_url_as_keyword():
    from app.config import Settings
    from app.main import build_service

    svc = build_service(Settings(llm_base_url="http://ollama:11434/v1", models=("m",)))
    assert svc.vision.base_url == "http://ollama:11434/v1"
