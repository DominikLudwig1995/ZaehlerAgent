from fastapi.testclient import TestClient

from app.config import load_meters
from app.main import app, healthz


def test_healthz():
    assert healthz() == {"status": "ok"}


def test_meters_file_is_valid():
    meters = {m.name: m for m in load_meters("config/meters.yml")}
    assert meters["gas"].digits == 7 and meters["wasser"].digits == 8
    assert meters["gas"].device_class == "gas" and meters["wasser"].device_class == "water"
    assert all(m.max_rate_per_hour > 0 and len(m.crop) == 4 for m in meters.values())


def test_status_and_poll_endpoints(monkeypatch):
    monkeypatch.setenv("METERS_FILE", "config/meters.yml")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    with TestClient(app) as client:
        assert set(client.get("/status").json()) == {"gas", "wasser"}
        assert client.post("/poll/unbekannt").status_code == 404
