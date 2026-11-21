"""Liest Gas- und Wasserzaehler per Vision-Modell (OpenRouter) von den AI-on-the-edge-Kameras und meldet die Werte per MQTT an Home Assistant"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.config import Settings
from app.mqtt_ha import MqttPublisher
from app.service import MeterService
from app.vision import VisionClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_service(settings: Settings) -> MeterService:
    publisher = None
    if settings.mqtt_host:
        publisher = MqttPublisher(settings)
        publisher.connect()
    service = MeterService(
        settings, VisionClient(settings.openrouter_api_key, settings.models[0]), publisher
    )
    service.restore()
    return service


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.service = build_service(settings)
    task = asyncio.create_task(app.state.service.run_forever())
    try:
        yield
    finally:
        task.cancel()
        if app.state.service.publisher is not None:
            app.state.service.publisher.close()


app = FastAPI(title="zaehler-agent", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe used by Consul and the container health check."""
    return {"status": "ok"}


@app.get("/status")
def status() -> dict:
    """The last accepted value of every meter, with the last decision and the model's digits."""
    return app.state.service.snapshot()


@app.post("/poll/{name}")
async def poll_now(name: str) -> dict:
    """Read one meter right now (also when the picture did not change)."""
    service: MeterService = app.state.service
    meter = next((m for m in service.settings.meters if m.name == name), None)
    if meter is None:
        raise HTTPException(404, f"unknown meter {name!r}")
    await service.poll(meter, force=True)
    return service.snapshot()[name]
