"""Configuration: one YAML file (config/config.yml) for the meters and the settings, environment on top.

Secrets never belong in the file: the file names the environment variable that holds them
(`vision.api_key_env`, `mqtt.password_env`), or you set LLM_API_KEY / MQTT_PASSWORD directly.
Every setting can be overridden by an environment variable (see README), which is what docker-compose
and Nomad do.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

# Defaults per kind of meter: (Home Assistant device class, unit). "generic" has neither.
KINDS: dict[str, tuple[str | None, str]] = {
    "gas": ("gas", "m³"),
    "water": ("water", "m³"),
    "electricity": ("energy", "kWh"),
    "heat": ("energy", "kWh"),
    "generic": (None, ""),
}
DEFAULT_LLM_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODELS = ("openai/gpt-4o-mini", "qwen/qwen3-vl-30b-a3b-instruct")


@dataclass(frozen=True)
class Meter:
    """One mechanical counter (digit wheels) that a camera looks at."""

    name: str  # short id used in topics, URLs and metrics: "gas", "water"
    title: str  # shown in the UI and in Home Assistant
    image_url: str  # a picture of the counter (HTTP GET); any camera or snapshot URL
    integer_digits: int  # wheels left of the decimal point
    decimals: int  # wheels right of it (usually the red ones)
    kind: str = "generic"  # gas | water | electricity | heat | generic
    crop: tuple[int, int, int, int] | None = (
        None  # x0, y0, x1, y1 of the digit row; None = whole image
    )
    max_rate_per_hour: float = 10.0  # the most the counter can plausibly advance in an hour
    rotate: float = 0.0  # degrees counter-clockwise, applied before the crop
    mirror: bool = False  # mirror horizontally, applied before the crop
    image_headers: dict[str, str] = field(
        default_factory=dict
    )  # e.g. {"Authorization": "Bearer ${CAM_TOKEN}"}
    device_json_url: str = (
        ""  # optional: the camera's own reading (AI-on-the-edge /json), shown for comparison
    )
    initial_value: float | None = None  # known value to start from while nothing is stored yet
    unit: str = ""  # default by kind
    device_class: str | None = None  # default by kind

    def __post_init__(self) -> None:
        dc, unit = KINDS.get(self.kind, KINDS["generic"])
        if not self.unit:
            object.__setattr__(self, "unit", unit)
        if self.device_class is None:
            object.__setattr__(self, "device_class", dc)

    @property
    def digits(self) -> int:
        return self.integer_digits + self.decimals


@dataclass(frozen=True)
class Settings:
    llm_base_url: str = (
        DEFAULT_LLM_BASE_URL  # any OpenAI-compatible chat API: OpenRouter, OpenAI, Ollama, vLLM
    )
    llm_api_key: str = ""  # empty is fine for a local model
    # One call per model and reading; the digits are voted wheel by wheel. Different models make different
    # mistakes, which is what the vote needs. Measured on real pictures: see README.
    models: tuple[str, ...] = DEFAULT_MODELS
    interval_seconds: int = 1800
    max_daily_cost_usd: float = 0.30
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_password: str = ""
    topic_prefix: str = "zaehler-agent"
    discovery_prefix: str = "homeassistant"
    data_dir: str = ""  # where the history database lives; empty = memory only
    history_days: int = 30
    config_file: str = "config/config.yml"
    meters: tuple[Meter, ...] = field(default_factory=tuple)

    @property
    def openrouter_api_key(self) -> str:  # the name used before the agent became generic
        return self.llm_api_key

    @classmethod
    def load(cls, env: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ if env is None else env)
        path = e.get("CONFIG_FILE") or e.get("METERS_FILE") or "config/config.yml"
        data = _read_yaml(path)
        vision, mqtt = data.get("vision") or {}, data.get("mqtt") or {}

        def pick(env_name: str, file_value, default):
            if e.get(env_name) not in (None, ""):
                return e[env_name]
            return file_value if file_value not in (None, "") else default

        key_env = vision.get("api_key_env") or ""
        models = pick("MODELS", vision.get("models"), list(DEFAULT_MODELS))
        if isinstance(models, str):
            models = [m.strip() for m in models.split(",") if m.strip()]
        d = cls()
        return cls(
            llm_base_url=str(pick("LLM_BASE_URL", vision.get("base_url"), d.llm_base_url)),
            llm_api_key=e.get("LLM_API_KEY")
            or e.get(key_env, "")
            or e.get("OPENROUTER_API_KEY", ""),
            models=tuple(models),
            interval_seconds=int(
                pick("INTERVAL_SECONDS", data.get("interval_seconds"), d.interval_seconds)
            ),
            max_daily_cost_usd=float(
                pick("MAX_DAILY_COST_USD", data.get("max_daily_cost_usd"), d.max_daily_cost_usd)
            ),
            mqtt_host=str(pick("MQTT_HOST", mqtt.get("host"), "")),
            mqtt_port=int(pick("MQTT_PORT", mqtt.get("port"), d.mqtt_port)),
            mqtt_user=str(pick("MQTT_USER", mqtt.get("user"), "")),
            mqtt_password=e.get("MQTT_PASSWORD") or e.get(mqtt.get("password_env") or "", ""),
            topic_prefix=str(pick("TOPIC_PREFIX", mqtt.get("topic_prefix"), d.topic_prefix)),
            discovery_prefix=str(
                pick("DISCOVERY_PREFIX", mqtt.get("discovery_prefix"), d.discovery_prefix)
            ),
            data_dir=str(pick("DATA_DIR", data.get("data_dir"), "")),
            history_days=int(pick("HISTORY_DAYS", data.get("history_days"), d.history_days)),
            config_file=path,
            meters=tuple(_meter(m, e) for m in data.get("meters") or []),
        )

    from_env = load  # the name of the first version


def _read_yaml(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _expand(value: str, env: dict[str, str]) -> str:
    return re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), ""), value)


def _meter(item: dict, env: dict[str, str]) -> Meter:
    known = {f.name for f in fields(Meter)}
    unknown = set(item) - known
    if unknown:
        raise ValueError(f"meter {item.get('name')!r}: unknown settings {sorted(unknown)}")
    item = dict(item)
    if item.get("crop") is not None:
        item["crop"] = tuple(item["crop"])
    item["image_headers"] = {
        k: _expand(str(v), env) for k, v in (item.get("image_headers") or {}).items()
    }
    return Meter(**item)


def load_meters(path: str) -> tuple[Meter, ...]:
    """The meters of a config file (the first version had a meters-only file)."""
    return tuple(_meter(m, dict(os.environ)) for m in _read_yaml(path).get("meters") or [])
