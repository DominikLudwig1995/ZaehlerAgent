import json

import httpx
import pytest
import respx
from PIL import Image

from app.vision import CHAT_URL, VisionClient, VisionError, parse_answer, prepare_image


def test_parse_answer_is_tolerant():
    assert parse_answer('```json\n{"digits": "3592352", "confidence": 0.8}\n```', 7) == (
        "3592352",
        0.8,
    )
    assert parse_answer('{"digits": "35X2352"}', 7)[0] == "35?2352"
    assert parse_answer('{"digits": "3592352", "confidence": "abc"}', 7)[1] == 0.5
    with pytest.raises(VisionError):
        parse_answer("I cannot read this", 7)
    with pytest.raises(VisionError):
        parse_answer('{"digits": "359"}', 7)
    with pytest.raises(VisionError):
        parse_answer("{not json}", 7)


def test_prepare_image_crops_and_enlarges(jpeg):
    out = prepare_image(jpeg, (10, 10, 110, 50))
    img = Image.open(__import__("io").BytesIO(out))
    assert img.size == (200, 80)  # 100 x 40, doubled


@respx.mock
async def test_read_sends_the_image_and_returns_digits_and_cost(gas, jpeg):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"digits": "3592352", "confidence": 0.9}'}}],
                "usage": {"cost": 0.0004},
            },
        )
    )
    res = await VisionClient("key", "m/x").read(jpeg, gas)
    assert (res.digits, res.confidence, res.cost_usd) == ("3592352", 0.9, 0.0004)
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "m/x" and body["messages"][0]["content"][1]["type"] == "image_url"
    assert route.calls[0].request.headers["authorization"] == "Bearer key"


@respx.mock
async def test_read_reports_failures(gas, jpeg):
    respx.post(CHAT_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(VisionError):
        await VisionClient("key", "m/x").read(jpeg, gas)
    with pytest.raises(VisionError):
        await VisionClient("", "m/x").read(jpeg, gas)
