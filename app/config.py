"""Configuration: the meters (config/meters.yml) and the settings from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Meter:
    """One mechanical counter that an AI-on-the-edge camera looks at."""

    name: str  # short id, used in topics: "gas", "wasser"
    title: str  # shown in Home Assistant
    kind: str  # "gas" or "water": the prompt and the Home Assistant device class
    image_url: str  # aligned image of the camera (img_tmp/alg.jpg)
    integer_digits: int  # black wheels (whole m3)
    decimals: int  # red wheels (fractions of a m3)
    crop: tuple[int, int, int, int]  # x0, y0, x1, y1 of the digit row in the image
    max_rate_per_hour: float  # plausibility: the most the counter can advance in an hour (m3)
    device_json_url: str = ""  # the camera's own reading, only reported next to ours
    initial_value: float | None = (
        None  # known counter value to start from when nothing is stored yet
    )
    unit: str = "m³"

    @property
    def digits(self) -> int:
        return self.integer_digits + self.decimals

    @property
    def device_class(self) -> str:
        return "gas" if self.kind == "gas" else "water"


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = ""
    # One call per model per reading; the digits are voted wheel by wheel. Two different models make
    # different mistakes, which is what the vote needs. Measured on the real pictures: see README.
    models: tuple[str, ...] = ("openai/gpt-4o-mini", "qwen/qwen3-vl-30b-a3b-instruct")
    interval_seconds: int = 1800
    max_daily_cost_usd: float = 0.30
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    topic_prefix: str = "zaehler-agent"
    discovery_prefix: str = "homeassistant"
    meters_file: str = "config/meters.yml"
    meters: tuple[Meter, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        meters_file = e.get("METERS_FILE", "config/meters.yml")
        return cls(
            openrouter_api_key=e.get("OPENROUTER_API_KEY", ""),
            models=tuple(
                x.strip() for x in e.get("MODELS", ",".join(cls.models)).split(",") if x.strip()
            ),
            interval_seconds=int(e.get("INTERVAL_SECONDS", cls.interval_seconds)),
            max_daily_cost_usd=float(e.get("MAX_DAILY_COST_USD", cls.max_daily_cost_usd)),
            mqtt_host=e.get("MQTT_HOST", ""),
            mqtt_port=int(e.get("MQTT_PORT", cls.mqtt_port)),
            mqtt_user=e.get("MQTT_USER", ""),
            mqtt_password=e.get("MQTT_PASSWORD", ""),
            topic_prefix=e.get("TOPIC_PREFIX", cls.topic_prefix),
            discovery_prefix=e.get("DISCOVERY_PREFIX", cls.discovery_prefix),
            meters_file=meters_file,
            meters=load_meters(meters_file),
        )


def load_meters(path: str) -> tuple[Meter, ...]:
    p = Path(path)
    if not p.is_file():
        return ()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    meters = []
    for item in data.get("meters", []):
        item = dict(item)
        item["crop"] = tuple(item["crop"])
        meters.append(Meter(**item))
    return tuple(meters)
