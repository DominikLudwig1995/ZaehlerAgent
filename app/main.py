"""zaehler-agent: reads mechanical meters with vision models and reports to MQTT / Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import Settings
from app.mqtt_ha import MqttPublisher
from app.service import MeterService
from app.vision import VisionClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


def build_service(settings: Settings) -> MeterService:
    publisher = None
    if settings.mqtt_host:
        publisher = MqttPublisher(settings)
        publisher.connect()
    service = MeterService(
        settings,
        VisionClient(settings.llm_api_key, settings.models[0], settings.llm_base_url),
        publisher,
    )
    service.restore()
    return service


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.load()
    app.state.service = build_service(settings)
    task = asyncio.create_task(app.state.service.run_forever())
    try:
        yield
    finally:
        task.cancel()
        if app.state.service.publisher is not None:
            app.state.service.publisher.close()


app = FastAPI(title="zaehler-agent", lifespan=lifespan)


def _meter(name: str):
    service: MeterService = app.state.service
    meter = next((m for m in service.settings.meters if m.name == name), None)
    if meter is None:
        raise HTTPException(404, f"unknown meter {name!r}")
    return service, meter


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe used by Consul, docker-compose and the container health check."""
    return {"status": "ok"}


@app.get("/status")
def status() -> dict:
    """The last accepted value of every meter, with the last decision and the digits each model read."""
    return app.state.service.snapshot()


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return app.state.service.metrics.render()


@app.get("/api/config")
def api_config() -> dict:
    s: MeterService = app.state.service
    st = s.settings
    return {
        "models": list(st.models),
        "interval_seconds": st.interval_seconds,
        "max_daily_cost_usd": st.max_daily_cost_usd,
        "cost_today_usd": round(s._spent, 4),
        "mqtt": bool(st.mqtt_host),
        "meters": [
            {
                "name": m.name,
                "title": m.title,
                "kind": m.kind,
                "unit": m.unit,
                "decimals": m.decimals,
            }
            for m in st.meters
        ],
    }


@app.get("/api/history/{name}")
def history(name: str, hours: int = 72, limit: int = 50) -> dict:
    service, _ = _meter(name)
    return {
        "series": service.history.series(name, hours),
        "readings": service.history.recent(name, min(limit, 500)),
    }


@app.get("/api/image/{name}")
def image(name: str, crop: bool = False) -> Response:
    """The last picture of the camera (crop=true: what the models saw)."""
    service, _ = _meter(name)
    st = service.state[name]
    data = st.crop_image if crop else st.image
    if not data:
        raise HTTPException(404, "no picture yet")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/poll/{name}")
async def poll_now(name: str) -> dict:
    """Read one meter right now (also when the picture did not change)."""
    service, meter = _meter(name)
    await service.poll(meter, force=True)
    return service.snapshot()[name]


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(STATIC / "index.html")
