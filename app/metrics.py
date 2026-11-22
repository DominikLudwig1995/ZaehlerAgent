"""Prometheus text format, hand written (no extra dependency)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict


def _labels(**kv: str) -> str:
    if not kv:
        return ""
    inner = ",".join(
        f'{k}="{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for k, v in kv.items()
    )
    return "{" + inner + "}"


def _num(v: float) -> str:
    """Full precision: a Unix timestamp or a counter reading must not be rounded to 6 digits."""
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started = time.time()
        self.counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self.gauges: dict[tuple[str, tuple], float] = {}

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self.counters[(name, tuple(sorted(labels.items())))] += value

    def set(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self.gauges[(name, tuple(sorted(labels.items())))] = value

    def render(self) -> str:
        helps = {
            "zaehler_up": "1 while the agent runs",
            "zaehler_uptime_seconds": "Seconds since the agent started",
            "zaehler_value": "Last accepted counter value",
            "zaehler_last_poll_timestamp_seconds": "Unix time of the last reading attempt that reached a decision",
            "zaehler_last_accepted_timestamp_seconds": "Unix time of the last accepted (changed) value",
            "zaehler_readings_total": "Readings by decision: accepted, unchanged, rejected, error",
            "zaehler_model_errors_total": "Failed model calls by model",
            "zaehler_camera_errors_total": "Failed picture downloads by meter",
            "zaehler_cost_usd_today": "Model cost of the current UTC day",
            "zaehler_budget_exhausted": "1 when the daily budget is used up and no model calls are made",
            "zaehler_mqtt_connected": "1 when MQTT is configured and connected",
            "zaehler_agreement": "Share of wheels the models agreed on in the last reading",
        }
        out = [
            "# TYPE zaehler_up gauge",
            "zaehler_up 1",
            "# TYPE zaehler_uptime_seconds gauge",
            f"zaehler_uptime_seconds {time.time() - self.started:.0f}",
        ]
        with self._lock:
            families: dict[str, list[str]] = defaultdict(list)
            kinds: dict[str, str] = {}
            for (name, lab), v in sorted(self.counters.items()):
                families[name].append(f"{name}{_labels(**dict(lab))} {_num(v)}")
                kinds[name] = "counter"
            for (name, lab), v in sorted(self.gauges.items()):
                families[name].append(f"{name}{_labels(**dict(lab))} {_num(v)}")
                kinds[name] = "gauge"
        for name, lines in families.items():
            out.append(f"# HELP {name} {helps.get(name, name)}")
            out.append(f"# TYPE {name} {kinds[name]}")
            out.extend(lines)
        return "\n".join(out) + "\n"
