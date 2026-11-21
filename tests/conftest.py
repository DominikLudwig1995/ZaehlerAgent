import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from app.config import Meter, Settings


@pytest.fixture
def gas() -> Meter:
    return Meter(
        name="gas",
        title="Gaszaehler",
        kind="gas",
        image_url="http://cam/alg.jpg",
        integer_digits=4,
        decimals=3,
        crop=(0, 0, 100, 40),
        max_rate_per_hour=4.0,
        device_json_url="http://cam/json",
    )


@pytest.fixture
def settings(gas) -> Settings:
    return Settings(llm_api_key="k", models=("m/x", "m/y"), meters=(gas,), mqtt_host="")


@pytest.fixture
def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (200, 80), 128).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
