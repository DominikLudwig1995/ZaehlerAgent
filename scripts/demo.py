"""Try the agent without a camera or an API key: a fake camera, a fake vision API and seeded history.

    uv run python scripts/demo.py            # then open http://127.0.0.1:8000

Two meters (water, gas) are served as generated pictures of digit wheels. The "models" read the generated value
(one of them slips on a wheel now and then, so you can see the voting). Nothing leaves your machine.
"""

from __future__ import annotations

import io
import json
import math
import os
import random
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CAM_PORT, LLM_PORT, APP_PORT = 9101, 9102, int(os.environ.get("PORT", "8000"))
# name -> (title, kind, integer wheels, decimals, start value, rise per hour)
METERS = {
    "water": ("Water meter", "water", 5, 3, 150.211, 0.12),
    "gas": ("Gas meter", "gas", 4, 3, 3598.661, 0.45),
}
state = {"value": {k: v[4] for k, v in METERS.items()}, "last": "water", "tick": 0}


def render(name: str, value: float) -> bytes:
    """A picture of the digit wheels, roughly what an ESP32 camera sees."""
    _, _, integer, decimals, _, _ = METERS[name]
    text = f"{value:0{integer + decimals + 1}.{decimals}f}".replace(".", "")
    w, h = 640, 200
    img = Image.new("RGB", (w, h), (52, 56, 60))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (20, 40, w - 20, h - 40), 10, fill=(14, 14, 16), outline=(120, 124, 130), width=4
    )
    font = ImageFont.load_default(size=74)
    n = len(text)
    cell = (w - 80) / n
    for i, ch in enumerate(text):
        red = i >= integer
        x0 = 40 + i * cell
        d.rectangle(
            (x0 + 3, 54, x0 + cell - 3, h - 54), fill=(228, 74, 66) if red else (236, 236, 232)
        )
        d.text(
            (x0 + cell / 2, h / 2),
            ch,
            font=font,
            fill=(240, 240, 240) if red else (18, 18, 18),
            anchor="mm",
        )
    img = img.rotate(random.uniform(-0.8, 0.8), resample=Image.BICUBIC, fillcolor=(52, 56, 60))
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return out.getvalue()


class Camera(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = self.path.strip("/").split("/")[0].split(".")[0]
        if name not in METERS:
            self.send_error(404)
            return
        state["last"] = name
        state["value"][name] += (
            METERS[name][5] / 60 * random.uniform(0.5, 1.5)
        )  # a few minutes of use
        body = render(name, state["value"][name])
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class FakeVision(BaseHTTPRequestHandler):
    """An OpenAI-compatible /chat/completions that answers with the digits of the last picture."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        name = state["last"]
        _, _, integer, decimals, _, _ = METERS[name]
        digits = f"{state['value'][name]:0{integer + decimals + 1}.{decimals}f}".replace(".", "")
        if (
            "b" in req.get("model", "") and random.random() < 0.3
        ):  # the second model sometimes slips on a wheel
            i = len(digits) - 1
            digits = digits[:i] + str((int(digits[i]) + random.choice([1, 9])) % 10)
        body = json.dumps(
            {
                "choices": [
                    {"message": {"content": json.dumps({"digits": digits, "confidence": 0.93})}}
                ],
                "usage": {"cost": 0.0004},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def serve(handler, port: int) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def seed(data_dir: str) -> None:
    """Three days of readings, so the curve and the table have something to show."""
    from app.storage import History

    history = History(data_dir)
    now = time.time()
    for name, (_, _, integer, decimals, start, rate) in METERS.items():
        value = start
        for i in range(3 * 24 * 2, 0, -1):
            ts = now - i * 1800
            hour = (ts // 3600) % 24
            use = rate / 2 * (1.6 if 6 <= hour <= 9 or 18 <= hour <= 21 else 0.25)
            value += use * (0.7 + 0.6 * abs(math.sin(i)))
            digits = f"{value:0{integer + decimals + 1}.{decimals}f}".replace(".", "")
            history.add(
                name,
                {
                    "status": "accepted",
                    "digits": digits,
                    "samples": [digits, digits],
                    "models": ["model-a", "model-b"],
                },
                round(value, decimals),
                0.0008,
                ts=ts,
            )
        state["value"][name] = value


def main() -> None:
    data_dir = tempfile.mkdtemp(prefix="zaehler-demo-")
    seed(data_dir)
    serve(Camera, CAM_PORT)
    serve(FakeVision, LLM_PORT)
    cfg = Path(data_dir) / "config.yml"
    meters = []
    for name, (title, kind, integer, decimals, _, rate) in METERS.items():
        meters.append(
            f"""  - name: {name}
    title: {title}
    kind: {kind}
    image_url: http://127.0.0.1:{CAM_PORT}/{name}.jpg
    integer_digits: {integer}
    decimals: {decimals}
    max_rate_per_hour: {max(2.0, rate * 6)}
    initial_value: {state["value"][name]:.3f}
    crop: [40, 54, 600, 146]
"""
        )
    cfg.write_text(
        f"""interval_seconds: 3600
vision:
  base_url: http://127.0.0.1:{LLM_PORT}
  models: [model-a, model-b]
meters:
{"".join(meters)}""",
        encoding="utf-8",
    )
    os.environ.update({"CONFIG_FILE": str(cfg), "DATA_DIR": data_dir, "LLM_API_KEY": "demo"})
    import uvicorn

    print(
        f"\nDemo: http://127.0.0.1:{APP_PORT}  (fake camera and fake models, data in {data_dir})\n"
    )
    uvicorn.run("app.main:app", host="127.0.0.1", port=APP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
