"""The polling loop: fetch the picture, let the model read it, vote, check, publish."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from app.config import Meter, Settings
from app.mqtt_ha import (
    Publisher,
    attributes_topic,
    publish_discovery,
    publish_reading,
    state_topic,
)
from app.plausibility import Decision, Reading, decide, vote
from app.vision import VisionClient, VisionError

log = logging.getLogger("zaehler")


@dataclass
class MeterState:
    last: Reading | None = None
    image_hash: str = ""
    status: str = "starting"
    detail: dict = field(default_factory=dict)


class MeterService:
    def __init__(
        self,
        settings: Settings,
        vision: VisionClient,
        publisher: Publisher | None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.vision = vision
        self.publisher = publisher
        self.http = http or httpx.AsyncClient(timeout=20)
        self.state = {m.name: MeterState() for m in settings.meters}
        self._spent = 0.0
        self._spent_day = datetime.now(UTC).date()

    # -- start ----------------------------------------------------------------------------------
    def restore(self) -> None:
        """Discovery to Home Assistant, then the last stored value of every meter (so a restart loses nothing)."""
        if self.publisher is None:
            return
        publish_discovery(self.publisher, self.settings)
        for m in self.settings.meters:
            stored = self.publisher.retained(state_topic(self.settings, m))
            attrs = self.publisher.retained(attributes_topic(self.settings, m))
            at = datetime.now(UTC)
            with contextlib.suppress(KeyError, ValueError, TypeError):
                at = datetime.fromisoformat(json.loads(attrs or "{}")["updated"])
            if stored:
                self.state[m.name].last = Reading(float(stored), at)
            elif m.initial_value is not None:
                # Old on purpose: the value may be days old, so the rate window must be wide at first.
                self.state[m.name].last = Reading(
                    m.initial_value, datetime.now(UTC) - timedelta(days=3)
                )
            log.info("%s starts at %s", m.name, self.state[m.name].last)

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
            r = await self.http.get(meter.image_url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return self._fail(meter, "camera unreachable", str(exc)[:120])
        digest = hashlib.sha256(r.content).hexdigest()[:16]
        if digest == st.image_hash and not force:
            return None  # the camera has not taken a new picture since the last poll
        if not self._budget_left():
            return self._fail(meter, "daily budget used up", "")

        results = await asyncio.gather(
            *(self.vision.read(r.content, meter, model=m) for m in self.settings.models),
            return_exceptions=True,
        )
        good = [x for x in results if not isinstance(x, BaseException)]
        self._spent += sum(x.cost_usd for x in good)
        if not good:
            return self._fail(meter, "model failed", "; ".join(str(x)[:80] for x in results))
        st.image_hash = digest
        digits, agreement = vote([x.digits for x in good])
        decision = decide(meter, digits, st.last, now)
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
        if self.publisher is not None:
            publish_reading(
                self.publisher, self.settings, meter, st.last.value if st.last else None, st.detail
            )
        log.info("%s: %s %s (%s)", meter.name, decision.status, digits, decision.reason)
        return decision

    def _fail(self, meter: Meter, reason: str, detail: str) -> None:
        st = self.state[meter.name]
        st.status = "error"
        st.detail = {"status": "error", "reason": reason, "detail": detail}
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
            await asyncio.sleep(self.settings.interval_seconds)

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


__all__ = ["MeterService", "VisionError"]
