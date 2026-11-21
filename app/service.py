"""The polling loop: fetch the picture, let the model read it, vote, check, publish."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Meter, Settings
from app.metrics import Metrics
from app.mqtt_ha import (
    Publisher,
    attributes_topic,
    publish_discovery,
    publish_reading,
    state_topic,
)
from app.plausibility import Decision, Reading, decide, vote
from app.storage import History
from app.vision import VisionClient, prepare_image

log = logging.getLogger("zaehler")


@dataclass
class MeterState:
    last: Reading | None = None
    image_hash: str = ""
    status: str = "starting"
    detail: dict = field(default_factory=dict)
    image: bytes = b""  # last raw picture from the camera
    crop_image: bytes = b""  # what the models saw


class MeterService:
    def __init__(
        self,
        settings: Settings,
        vision: VisionClient,
        publisher: Publisher | None,
        http: httpx.AsyncClient | None = None,
        history: History | None = None,
        metrics: Metrics | None = None,
        publisher_factory: Callable[[Settings], Publisher | None] | None = None,
    ) -> None:
        self.publisher_factory = publisher_factory
        self._wake = asyncio.Event()
        self.history = history or History(settings.data_dir, settings.history_days)
        self.metrics = metrics or Metrics()
        self.settings = settings
        self.vision = vision
        self.publisher = publisher
        self.http = http or httpx.AsyncClient(timeout=20)
        self.state = {m.name: MeterState() for m in settings.meters}
        self._spent = 0.0
        self._spent_day = datetime.now(UTC).date()
        midnight = datetime.combine(self._spent_day, datetime.min.time(), UTC).timestamp()
        self._spent = self.history.cost_since(midnight)  # a restart must not reset the daily budget

    # -- start ----------------------------------------------------------------------------------
    def restore(self) -> None:
        """Discovery to Home Assistant, then the last stored value of every meter (so a restart loses nothing)."""
        if self.publisher is None:
            return
        publish_discovery(self.publisher, self.settings)
        for m in self.settings.meters:
            self._init_meter(m)

    def _init_meter(self, m: Meter) -> None:
        st = self.state.setdefault(m.name, MeterState())
        stored = self.publisher.retained(state_topic(self.settings, m)) if self.publisher else None
        attrs = (
            self.publisher.retained(attributes_topic(self.settings, m)) if self.publisher else None
        )
        at = datetime.now(UTC)
        with contextlib.suppress(KeyError, ValueError, TypeError):
            at = datetime.fromisoformat(json.loads(attrs or "{}")["updated"])
        if stored:
            st.last = Reading(float(stored), at)
        elif m.initial_value is not None:
            # Old on purpose: the value may be days old, so the rate window must be wide at first.
            st.last = Reading(m.initial_value, datetime.now(UTC) - timedelta(days=3))
        log.info("%s starts at %s", m.name, st.last)

    # -- changes from the UI -----------------------------------------------------------------------
    def reconfigure(self, new: Settings) -> None:
        """Apply new settings without a restart: meters, models, key, MQTT."""
        old = self.settings
        self.settings = new
        old_by, new_by = {m.name: m for m in old.meters}, {m.name: m for m in new.meters}
        mqtt_changed = (
            old.mqtt_host,
            old.mqtt_port,
            old.mqtt_user,
            old.mqtt_password,
            old.topic_prefix,
        ) != (
            new.mqtt_host,
            new.mqtt_port,
            new.mqtt_user,
            new.mqtt_password,
            new.topic_prefix,
        )
        if mqtt_changed and self.publisher_factory is not None:
            self._clear_discovery(old, [m.name for m in old.meters])
            if self.publisher is not None:
                self.publisher.close()
            self.publisher = self.publisher_factory(new)
            added = list(new_by)
        else:
            self._clear_discovery(old, [n for n in old_by if n not in new_by])
            added = [n for n in new_by if n not in old_by]
        for name in [n for n in self.state if n not in new_by]:
            del self.state[name]
        for name, m in new_by.items():
            self.state.setdefault(name, MeterState())
            if old_by.get(name) != m:
                self.state[name].image_hash = ""  # a changed meter is read again at the next round
        self.vision.api_key, self.vision.base_url = new.llm_api_key, new.llm_base_url.rstrip("/")
        self.vision.model = new.models[0]
        if self.publisher is not None:
            publish_discovery(self.publisher, new)
            for name in added:
                self._init_meter(new_by[name])
        self._wake.set()

    def _clear_discovery(self, settings: Settings, names: list[str]) -> None:
        if self.publisher is None:
            return
        for name in names:
            self.publisher.publish(
                f"{settings.discovery_prefix}/sensor/zaehler_agent_{name}/config", ""
            )

    async def test_read(self, meter: Meter) -> dict:
        """One reading for the setup form: fetch, read with every model, vote. Nothing is stored or published."""
        try:
            r = await self.http.get(meter.image_url, headers=meter.image_headers)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"camera: {str(exc)[:120]}"}
        results = await asyncio.gather(
            *(self.vision.read(r.content, meter, model=m) for m in self.settings.models),
            return_exceptions=True,
        )
        good = [x for x in results if not isinstance(x, BaseException)]
        self._spent += sum(x.cost_usd for x in good)
        if not good:
            return {"ok": False, "error": "; ".join(str(x)[:80] for x in results)}
        digits, agreement, _ = vote([x.digits for x in good])
        return {
            "ok": True,
            "digits": digits,
            "agreement": round(agreement, 2),
            "samples": [x.digits for x in good],
            "models": list(self.settings.models),
            "cost_usd": round(sum(x.cost_usd for x in good), 5),
        }

    # -- one reading ----------------------------------------------------------------------------
    def _budget_left(self) -> bool:
        today = datetime.now(UTC).date()
        if today != self._spent_day:
            self._spent, self._spent_day = 0.0, today
        return self._spent < self.settings.max_daily_cost_usd

    async def _device_reading(self, meter: Meter) -> str:
        if not meter.device_json_url:
            return ""
        try:
            r = await self.http.get(meter.device_json_url)
            return str(r.json()["main"]["raw"])
        except (httpx.HTTPError, KeyError, ValueError):
            return ""

    async def poll(self, meter: Meter, *, force: bool = False) -> Decision | None:
        st = self.state[meter.name]
        now = datetime.now(UTC)
        try:
            r = await self.http.get(meter.image_url, headers=meter.image_headers)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return self._fail(meter, "camera unreachable", str(exc)[:120])
        digest = hashlib.sha256(r.content).hexdigest()[:16]
        if digest == st.image_hash and not force:
            return None  # the camera has not taken a new picture since the last poll
        if not self._budget_left():
            self.metrics.set("zaehler_budget_exhausted", 1)
            return self._fail(meter, "daily budget used up", "")
        self.metrics.set("zaehler_budget_exhausted", 0)
        st.image = r.content
        try:
            st.crop_image = prepare_image(r.content, meter.crop, meter.rotate, meter.mirror)
        except Exception:  # noqa: BLE001 -- a broken picture is reported by the model call
            st.crop_image = b""

        results = await asyncio.gather(
            *(self.vision.read(r.content, meter, model=m) for m in self.settings.models),
            return_exceptions=True,
        )
        good = [x for x in results if not isinstance(x, BaseException)]
        cost = sum(x.cost_usd for x in good)
        self._spent += cost
        for m, x in zip(self.settings.models, results, strict=False):
            if isinstance(x, BaseException):
                self.metrics.inc("zaehler_model_errors_total", model=m)
        if not good:
            return self._fail(meter, "model failed", "; ".join(str(x)[:80] for x in results), cost)
        st.image_hash = digest
        digits, agreement, alternatives = vote([x.digits for x in good])
        decision = decide(meter, digits, st.last, now, alternatives)
        if decision.status == "accepted" and decision.value is not None:
            st.last = Reading(decision.value, now)
        st.status = decision.status
        st.detail = {
            "status": decision.status,
            "reason": decision.reason,
            "digits": digits,
            "agreement": round(agreement, 2),
            "confidence": round(sum(x.confidence for x in good) / len(good), 2),
            "samples": [x.digits for x in good],
            "models": list(self.settings.models),
            "device_reading": await self._device_reading(meter),
            "cost_today_usd": round(self._spent, 4),
        }
        self._record(meter, st, cost)
        if self.publisher is not None:
            publish_reading(
                self.publisher, self.settings, meter, st.last.value if st.last else None, st.detail
            )
        log.info("%s: %s %s (%s)", meter.name, decision.status, digits, decision.reason)
        return decision

    def set_value(self, meter: Meter, value: float) -> dict:
        """Calibration: set the counter to a value you read yourself (start value, or after a counter jump)."""
        st = self.state[meter.name]
        st.last = Reading(value, datetime.now(UTC))
        st.status = "accepted"
        st.detail = {"status": "accepted", "reason": "set by hand", "digits": ""}
        self._record(meter, st, 0.0)
        if self.publisher is not None:
            publish_reading(self.publisher, self.settings, meter, value, st.detail)
        return self.snapshot()[meter.name]

    def _record(self, meter: Meter, st: MeterState, cost: float) -> None:
        d, name = st.detail, meter.name
        self.history.add(name, d, st.last.value if st.last else None, cost)
        self.metrics.inc("zaehler_readings_total", meter=name, status=st.status)
        self.metrics.set(
            "zaehler_last_poll_timestamp_seconds", datetime.now(UTC).timestamp(), meter=name
        )
        if st.last:
            self.metrics.set("zaehler_value", st.last.value, meter=name)
        if st.status == "accepted":
            self.metrics.set(
                "zaehler_last_accepted_timestamp_seconds", datetime.now(UTC).timestamp(), meter=name
            )
        if "agreement" in d:
            self.metrics.set("zaehler_agreement", d["agreement"], meter=name)
        self.metrics.set("zaehler_cost_usd_today", self._spent)
        self.metrics.set("zaehler_mqtt_connected", 1 if self.publisher is not None else 0)

    def _fail(self, meter: Meter, reason: str, detail: str, cost: float = 0.0) -> None:
        st = self.state[meter.name]
        st.status = "error"
        st.detail = {"status": "error", "reason": reason, "detail": detail}
        if reason == "camera unreachable":
            self.metrics.inc("zaehler_camera_errors_total", meter=meter.name)
        self._record(meter, st, cost)
        log.warning("%s: %s %s", meter.name, reason, detail)
        if self.publisher is not None:
            publish_reading(
                self.publisher, self.settings, meter, st.last.value if st.last else None, st.detail
            )
        return None

    async def run_forever(self) -> None:
        while True:
            for meter in self.settings.meters:
                try:
                    await self.poll(meter)
                except Exception:  # noqa: BLE001 -- the loop must survive anything
                    log.exception("poll of %s crashed", meter.name)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.settings.interval_seconds)
            self._wake.clear()

    def snapshot(self) -> dict:
        return {
            name: {
                "value": st.last.value if st.last else None,
                "at": st.last.at.isoformat() if st.last else None,
                "status": st.status,
                **st.detail,
            }
            for name, st in self.state.items()
        }
