import json
from dataclasses import replace

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import (
    export_yaml,
    public,
    save_runtime,
    with_overrides,
    with_runtime_overrides,
)
from app.main import app
from app.service import MeterService
from app.vision import CHAT_URL, VisionClient
from tests.test_service import FakePublisher, answer

METER = {
    "name": "water",
    "title": "Water",
    "kind": "water",
    "image_url": "http://cam/raw.jpg",
    "integer_digits": 5,
    "decimals": 3,
    "max_rate_per_hour": 2,
    "crop": [0, 0, 100, 40],
}


def test_overrides_are_validated(settings):
    assert with_overrides(settings, {"models": "a/b, c/d", "interval_seconds": "120"}).models == (
        "a/b",
        "c/d",
    )
    for bad in ({"interval_seconds": 5}, {"models": []}, {"nope": 1}, {"max_daily_cost_usd": -1}):
        with pytest.raises(ValueError):
            with_overrides(settings, bad)
    for bad in (
        {**METER, "name": "Bad Name"},
        {**METER, "image_url": "ftp://x"},
        {**METER, "crop": [10, 10, 5, 5]},
        {**METER, "max_rate_per_hour": 0},
        {**METER, "integer_digits": 0},
        {"name": "x"},
    ):
        with pytest.raises(ValueError):
            with_overrides(settings, {"meters": [bad]})
    with pytest.raises(ValueError):
        with_overrides(settings, {"meters": [METER, METER]})


def test_empty_secret_keeps_the_old_one(settings):
    s = replace(settings, llm_api_key="secret")
    assert with_overrides(s, {"llm_api_key": ""}).llm_api_key == "secret"
    assert with_overrides(s, {"llm_api_key": "new"}).llm_api_key == "new"
    pub = public(s)
    assert "llm_api_key" not in pub and pub["llm_api_key_set"] is True


def test_runtime_file_wins_and_is_private(settings, tmp_path):
    s = replace(settings, data_dir=str(tmp_path), llm_api_key="k")
    changed = with_overrides(s, {"models": ["x/y"], "meters": [METER]})
    assert save_runtime(changed) is True
    assert oct((tmp_path / "settings.json").stat().st_mode & 0o777) == "0o600"
    again = with_runtime_overrides(s)
    assert again.models == ("x/y",) and [m.name for m in again.meters] == ["water"]
    assert save_runtime(replace(settings, data_dir="")) is False
    assert "water" in export_yaml(again) and "llm_api_key:" not in export_yaml(again)


def test_settings_and_meter_endpoints(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yml"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("INTERVAL_SECONDS", "3600")
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["meters"] == []
        assert c.post("/api/meters", json=METER).status_code == 200
        assert c.post("/api/meters", json=METER).status_code == 409
        assert c.post("/api/meters", json={**METER, "name": "Bad"}).status_code == 422
        assert (
            c.put("/api/meters/water", json={"title": "Wasser"}).json()["meters"][0]["title"]
            == "Wasser"
        )
        assert c.put("/api/meters/none", json={}).status_code == 404
        out = c.put("/api/settings", json={"models": "a/b", "interval_seconds": 600, "meters": []})
        assert (
            out.json()["models"] == ["a/b"] and len(out.json()["meters"]) == 1
        )  # meters are ignored here
        assert c.put("/api/settings", json={"interval_seconds": 1}).status_code == 422
        assert "water" in c.get("/api/settings/export").text
        assert "water" in json.loads((tmp_path / "settings.json").read_text())["meters"][0]["name"]
        assert c.delete("/api/meters/water").json()["meters"] == []
        assert c.delete("/api/settings").json()["models"][0] == "openai/gpt-4o-mini"
        assert not (tmp_path / "settings.json").exists()


def test_read_only_blocks_every_change(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yml"))
    monkeypatch.setenv("READ_ONLY", "true")
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("INTERVAL_SECONDS", "3600")
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["read_only"] is True
        for method, url, body in [
            ("post", "/api/meters", METER),
            ("put", "/api/meters/x", {}),
            ("delete", "/api/meters/x", None),
            ("put", "/api/settings", {}),
            ("delete", "/api/settings", None),
            ("post", "/api/meters/test", METER),
            ("post", "/poll/x", None),
            ("post", "/api/meters/x/value", {"value": 1}),
        ]:
            r = getattr(c, method)(url, **({"json": body} if body is not None else {}))
            assert r.status_code == 403, url


@respx.mock
def test_probe_returns_oriented_and_cropped_pictures(monkeypatch, tmp_path, jpeg):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yml"))
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("INTERVAL_SECONDS", "3600")
    respx.get("http://cam/raw.jpg").mock(return_value=httpx.Response(200, content=jpeg))
    with TestClient(app) as c:
        r = c.get(
            "/api/probe", params={"url": "http://cam/raw.jpg", "rotate": 90, "mirror": "true"}
        )
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert (
            c.get(
                "/api/probe", params={"url": "http://cam/raw.jpg", "crop": "0,0,50,20"}
            ).status_code
            == 200
        )
        assert (
            c.get("/api/probe", params={"url": "http://cam/raw.jpg", "crop": "1,2"}).status_code
            == 422
        )
        assert c.get("/api/probe", params={"url": "file:///etc/passwd"}).status_code == 422
        respx.get("http://cam/bad.jpg").mock(
            return_value=httpx.Response(200, content=b"not a picture")
        )
        assert c.get("/api/probe", params={"url": "http://cam/bad.jpg"}).status_code == 422
        respx.get("http://cam/down.jpg").mock(return_value=httpx.Response(500))
        assert c.get("/api/probe", params={"url": "http://cam/down.jpg"}).status_code == 502


@respx.mock
async def test_test_read_votes_without_publishing(settings, gas, jpeg):
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    respx.post(CHAT_URL).mock(return_value=answer("3592360"))
    pub = FakePublisher()
    svc = MeterService(settings, VisionClient("k", "m/x"), pub)
    out = await svc.test_read(gas)
    assert out["ok"] and out["digits"] == "3592360" and pub.sent == {}
    respx.get(gas.image_url).mock(return_value=httpx.Response(500))
    assert (await svc.test_read(gas))["ok"] is False
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    respx.post(CHAT_URL).mock(return_value=httpx.Response(500))
    assert (await svc.test_read(gas))["ok"] is False


def test_reconfigure_adds_removes_and_moves_mqtt(settings, gas):
    made = []

    def factory(s):
        made.append(FakePublisher())
        return made[-1]

    pub = FakePublisher({"zaehler-agent/water/state": "10.500"})
    svc = MeterService(settings, VisionClient("k", "m/x"), pub, publisher_factory=factory)
    svc.restore()
    water = with_overrides(settings, {"meters": [METER]}).meters[0]

    # a new meter appears, the old one goes: its discovery is cleared (retained empty payload)
    svc.reconfigure(replace(settings, meters=(water,), models=("n/m",), llm_api_key="k2"))
    assert set(svc.state) == {"water"} and svc.state["water"].last.value == 10.5
    assert pub.sent["homeassistant/sensor/zaehler_agent_gas/config"] == ""
    assert "homeassistant/sensor/zaehler_agent_water/config" in pub.sent
    assert svc.vision.api_key == "k2" and svc.vision.model == "n/m"

    # MQTT settings changed: a new publisher gets all discoveries, the old one is cleared
    svc.reconfigure(replace(svc.settings, mqtt_host="broker2"))
    assert len(made) == 1 and svc.publisher is made[0]
    assert "homeassistant/sensor/zaehler_agent_water/config" in made[0].sent
    assert pub.sent["homeassistant/sensor/zaehler_agent_water/config"] == ""

    # an edited meter is read again at the next round
    svc.state["water"].image_hash = "abc"
    svc.reconfigure(replace(svc.settings, meters=(replace(water, title="Wasser"),)))
    assert svc.state["water"].image_hash == ""
    assert svc._wake.is_set()


@respx.mock
async def test_live_picture_switches_the_light_on_and_off(settings, gas, jpeg):
    cam = replace(
        gas,
        live_url="http://cam/capture",
        light_on_url="http://cam/lighton",
        light_off_url="http://cam/lightoff",
        light_settle_seconds=0,
    )
    on = respx.get("http://cam/lighton").mock(return_value=httpx.Response(200))
    shot = respx.get("http://cam/capture").mock(return_value=httpx.Response(200, content=jpeg))
    off = respx.get("http://cam/lightoff").mock(return_value=httpx.Response(200))
    svc = MeterService(settings, VisionClient("k", "m/x"), None)
    assert await svc.live(cam, light=True) == jpeg
    assert on.called and shot.called and off.called
    on.reset(), off.reset()
    assert (
        await svc.live(cam) == jpeg and not on.called and not off.called
    )  # no light asked: untouched
    # the light goes off even when the picture fails
    shot.mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await svc.live(cam, light=True)
    assert off.called
    # no live_url: the normal picture URL is used
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    assert await svc.live(gas) == jpeg


def test_light_settings_are_validated(settings):
    with pytest.raises(ValueError):
        with_overrides(settings, {"meters": [{**METER, "light_on_url": "ftp://x"}]})
    with pytest.raises(ValueError):
        with_overrides(settings, {"meters": [{**METER, "light_settle_seconds": 99}]})
    ok = with_overrides(
        settings,
        {"meters": [{**METER, "live_url": "http://c/capture", "light_on_url": "http://c/on"}]},
    )
    assert ok.meters[0].live_url == "http://c/capture"


@respx.mock
def test_live_endpoint_and_page_routes(monkeypatch, tmp_path, jpeg):
    monkeypatch.setenv("CONFIG_FILE", str(tmp_path / "none.yml"))
    monkeypatch.delenv("MQTT_HOST", raising=False)
    monkeypatch.setenv("INTERVAL_SECONDS", "3600")
    respx.get("http://cam/raw.jpg").mock(return_value=httpx.Response(200, content=jpeg))
    with TestClient(app) as c:
        c.post(
            "/api/meters",
            json={**METER, "light_on_url": "http://cam/on", "light_settle_seconds": 0},
        )
        assert c.get("/api/live/water").content == jpeg
        assert c.get("/api/live/none").status_code == 404
        respx.get("http://cam/on").mock(return_value=httpx.Response(200))
        assert c.get("/api/live/water", params={"light": "true"}).status_code == 200
        respx.get("http://cam/raw.jpg").mock(return_value=httpx.Response(500))
        assert c.get("/api/live/water").status_code == 502
        for path in ("/", "/settings", "/meters", "/meters/new", "/meters/water"):
            assert "zaehler-agent" in c.get(path).text
    monkeypatch.setenv("READ_ONLY", "true")
    with TestClient(app) as c:
        assert c.get("/api/live/water", params={"light": "true"}).status_code == 403
