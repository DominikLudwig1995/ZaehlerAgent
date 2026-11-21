import json

import httpx
import respx

from app.mqtt_ha import attributes_topic, discovery_messages, state_topic
from app.service import MeterService
from app.vision import OPENROUTER_URL, VisionClient


class FakePublisher:
    def __init__(self, stored=None):
        self.sent, self.stored = {}, stored or {}

    def publish(self, topic, payload, retain=True):
        self.sent[topic] = payload

    def retained(self, topic, timeout=3.0):
        return self.stored.get(topic)


def answer(digits):
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": json.dumps({"digits": digits, "confidence": 0.9})}}
            ],
            "usage": {"cost": 0.0003},
        },
    )


def make(settings, pub):
    return MeterService(settings, VisionClient("k", "m/x"), pub)


@respx.mock
async def test_poll_publishes_an_accepted_value(settings, gas, jpeg):
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    respx.get(gas.device_json_url).mock(
        return_value=httpx.Response(200, json={"main": {"raw": "1508.633"}})
    )
    respx.post(OPENROUTER_URL).mock(return_value=answer("3592360"))
    pub = FakePublisher()
    svc = make(settings, pub)
    svc.restore()
    decision = await svc.poll(gas)
    assert decision.status == "accepted"  # initial value 3592.35 not set here: first reading
    assert pub.sent[state_topic(settings, gas)] == "3592.360"
    attrs = json.loads(pub.sent[attributes_topic(settings, gas)])
    assert attrs["device_reading"] == "1508.633" and attrs["samples"] == ["3592360", "3592360"]
    assert svc.snapshot()["gas"]["value"] == 3592.36
    # the same picture again is skipped, a forced poll reads it anyway
    assert await svc.poll(gas) is None
    assert (await svc.poll(gas, force=True)).status == "unchanged"


@respx.mock
async def test_implausible_reading_keeps_the_stored_value(settings, gas, jpeg):
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    respx.get(gas.device_json_url).mock(return_value=httpx.Response(404))
    respx.post(OPENROUTER_URL).mock(return_value=answer("1508633"))
    pub = FakePublisher(stored={state_topic(settings, gas): "3592.352"})
    svc = make(settings, pub)
    svc.restore()
    decision = await svc.poll(gas)
    assert decision.status == "rejected"
    assert pub.sent[state_topic(settings, gas)] == "3592.352"  # the good value stays


@respx.mock
async def test_camera_and_model_failures_are_reported_not_raised(settings, gas, jpeg):
    respx.get(gas.image_url).mock(return_value=httpx.Response(503))
    svc = make(settings, FakePublisher())
    assert await svc.poll(gas) is None
    assert svc.snapshot()["gas"]["status"] == "error"
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    respx.post(OPENROUTER_URL).mock(return_value=httpx.Response(500))
    assert await svc.poll(gas) is None
    assert "model failed" in svc.snapshot()["gas"]["reason"]


@respx.mock
async def test_daily_budget_stops_the_model_calls(settings, gas, jpeg):
    respx.get(gas.image_url).mock(return_value=httpx.Response(200, content=jpeg))
    route = respx.post(OPENROUTER_URL).mock(return_value=answer("3592360"))
    from dataclasses import replace

    svc = make(replace(settings, max_daily_cost_usd=0.0), FakePublisher())
    assert await svc.poll(gas) is None
    assert route.call_count == 0 and svc.snapshot()["gas"]["reason"] == "daily budget used up"


def test_discovery_is_a_total_increasing_sensor(settings):
    ((topic, payload),) = discovery_messages(settings)
    cfg = json.loads(payload)
    assert topic == "homeassistant/sensor/zaehler_agent_gas/config"
    assert cfg["device_class"] == "gas" and cfg["state_class"] == "total_increasing"
    assert cfg["unit_of_measurement"] == "m³" and cfg["json_attributes_topic"].endswith(
        "/gas/attributes"
    )


def test_restore_uses_initial_value_when_nothing_is_stored(settings, gas):
    from dataclasses import replace

    s = replace(settings, meters=(replace(gas, initial_value=3592.35),))
    svc = make(s, FakePublisher())
    svc.restore()
    assert svc.state["gas"].last.value == 3592.35
