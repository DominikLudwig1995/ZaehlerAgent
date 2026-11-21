"""zaehler-agent: reads mechanical meters with vision models and reports to MQTT / Home Assistant."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.config import Settings, export_yaml, public, reset_runtime, save_runtime, with_overrides
from app.mqtt_ha import MqttPublisher
from app.service import MeterService
from app.vision import VisionClient, oriented_jpeg, prepare_image

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC = Path(__file__).parent / "static"


def make_publisher(settings: Settings) -> MqttPublisher | None:
    if not settings.mqtt_host:
        return None
    publisher = MqttPublisher(settings)
    publisher.connect()
    return publisher


def build_service(settings: Settings) -> MeterService:
    service = MeterService(
        settings,
        VisionClient(settings.llm_api_key, settings.models[0], base_url=settings.llm_base_url),
        make_publisher(settings),
        publisher_factory=make_publisher,
    )
    service.restore()
    return service


def read_only() -> bool:
    """READ_ONLY=true: the UI shows everything but changes nothing (for a shared dashboard)."""
    return os.environ.get("READ_ONLY", "").lower() in ("1", "true", "yes")


def writable() -> None:
    if read_only():
        raise HTTPException(403, "this instance is read-only (READ_ONLY=true)")


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
        "read_only": read_only(),
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


@app.get("/api/live/{name}")
async def live(name: str, light: bool = False) -> Response:
    """A fresh picture from the camera right now; light=true switches its light on for the shot."""
    if light:
        writable()  # it switches something on
    service, meter = _meter(name)
    try:
        data = await service.live(meter, light=light)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"camera: {str(exc)[:120]}") from exc
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/poll/{name}")
async def poll_now(name: str) -> dict:
    """Read one meter right now (also when the picture did not change)."""
    writable()
    service, meter = _meter(name)
    await service.poll(meter, force=True)
    return service.snapshot()[name]


@app.post("/api/meters/{name}/value")
def set_value(name: str, body: dict) -> dict:
    """Set the counter by hand: {"value": 3600.34}. For the start value, or after the counter was replaced."""
    writable()
    service, meter = _meter(name)
    try:
        value = float(body["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, 'body must be {"value": <number>}') from exc
    if value < 0:
        raise HTTPException(422, "value must not be negative")
    return service.set_value(meter, value)


# -- configuration from the UI ------------------------------------------------------------------
def _apply(new: Settings) -> dict:
    service: MeterService = app.state.service
    persistent = save_runtime(new)
    service.reconfigure(new)
    return {**public(new), "persistent": persistent}


def _patched(patch: dict) -> Settings:
    service: MeterService = app.state.service
    try:
        return with_overrides(service.settings, patch)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/settings")
def get_settings() -> dict:
    return {**public(app.state.service.settings), "read_only": read_only()}


@app.put("/api/settings")
def put_settings(patch: dict) -> dict:
    """Change the general settings (models, key, interval, budget, MQTT). Only the keys you send change."""
    writable()
    patch = {k: v for k, v in patch.items() if k != "meters"}
    return _apply(_patched(patch))


@app.delete("/api/settings")
def reset_settings() -> dict:
    """Forget everything edited in the UI: back to the config file and the environment."""
    writable()
    service: MeterService = app.state.service
    reset_runtime(service.settings)
    fresh = Settings.load()
    service.reconfigure(fresh)
    return public(fresh)


@app.get("/api/settings/export", response_class=PlainTextResponse)
def export_settings() -> str:
    return export_yaml(app.state.service.settings)


def _meter_from(body: dict) -> dict:
    return {
        k: v
        for k, v in body.items()
        if v is not None or k in ("crop", "initial_value", "device_class")
    }


@app.post("/api/meters")
def add_meter(body: dict) -> dict:
    """Add a meter (camera + counter). The next round reads it, Home Assistant gets the sensor."""
    writable()
    service: MeterService = app.state.service
    if any(m.name == body.get("name") for m in service.settings.meters):
        raise HTTPException(409, f"meter {body.get('name')!r} exists")
    current = public(service.settings)["meters"]
    return _apply(_patched({"meters": [*current, _meter_from(body)]}))


@app.put("/api/meters/{name}")
def update_meter(name: str, body: dict) -> dict:
    writable()
    service, _ = _meter(name)
    current = public(service.settings)["meters"]
    merged = [{**m, **_meter_from(body), "name": name} if m["name"] == name else m for m in current]
    return _apply(_patched({"meters": merged}))


@app.delete("/api/meters/{name}")
def delete_meter(name: str) -> dict:
    writable()
    service, _ = _meter(name)
    current = public(service.settings)["meters"]
    return _apply(_patched({"meters": [m for m in current if m["name"] != name]}))


@app.post("/api/meters/test")
async def test_meter(body: dict) -> dict:
    """Try a meter definition (not saved): download the picture, read it with every model, show the vote."""
    writable()
    service: MeterService = app.state.service
    meter = _patched(
        {"meters": [{**_meter_from(body), "name": body.get("name") or "test"}]}
    ).meters[0]
    return await service.test_read(meter)


@app.get("/api/probe")
async def probe(
    url: str,
    rotate: float = 0.0,
    mirror: bool = False,
    crop: str = "",
    headers: str = "",
) -> Response:
    """The picture of a camera as the agent would see it: oriented (for drawing the crop) or, with crop, as the
    models get it. Used by the setup form of a meter."""
    if not url.startswith(("http://", "https://")):
        raise HTTPException(422, "url must be http(s)")
    hdrs = dict(h.split(":", 1) for h in headers.split("\n") if ":" in h) if headers else {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers={k.strip(): v.strip() for k, v in hdrs.items()})
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"camera: {str(exc)[:120]}") from exc
    if len(r.content) > 8_000_000:
        raise HTTPException(502, "picture too large")
    try:
        if crop:
            box = tuple(int(float(x)) for x in crop.split(","))
            if len(box) != 4:
                raise ValueError("crop")
            data = prepare_image(r.content, box, rotate, mirror)
        else:
            data = oriented_jpeg(r.content, rotate, mirror)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, "not a picture, or a bad crop") from exc
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/")
@app.get("/settings")
@app.get("/meters")
@app.get("/meters/{name}")
def ui(name: str = "") -> FileResponse:
    """The UI is one page that shows the view of the address; every view has its own URL."""
    return FileResponse(STATIC / "index.html")
