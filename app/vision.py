"""Reads the digits of a counter from a camera image with a vision model through OpenRouter."""

from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass

import httpx
from PIL import Image, ImageOps

from app.config import Meter

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT = """You read a mechanical {kind} meter ({unit}). The picture shows its row of digit wheels, {digits} wheels in all: \
{integer} whole-number wheels (black digits) followed by {decimals} fraction wheels (usually red, they turn fast). \
Some wheels are half-way between two digits: then give the digit that is mostly visible.
The picture is low quality (grey, blurry, with glare). Read every wheel from left to right. \
Write "?" for a wheel you cannot read. Do not guess digits that are not visible. \
Leading zeros count: always return exactly {digits} characters.
Answer with one line of JSON only: {{"digits": "<{digits} characters, 0-9 or ?>", "confidence": <0.0-1.0>}}"""


@dataclass(frozen=True)
class VisionResult:
    digits: str  # exactly meter.digits characters, "?" for unreadable wheels
    confidence: float
    cost_usd: float
    raw: str


class VisionError(RuntimeError):
    pass


def prepare_image(data: bytes, crop: tuple[int, int, int, int]) -> bytes:
    """Crop the digit row, stretch the contrast and enlarge it: the models read the wheels much better."""
    img = Image.open(io.BytesIO(data)).convert("L")
    w, h = img.size
    x0, y0, x1, y1 = crop
    img = img.crop((max(0, x0), max(0, y0), min(w, x1), min(h, y1)))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def parse_answer(text: str, expected: int) -> tuple[str, float]:
    """Pull {"digits": "...", "confidence": x} out of a model answer; tolerant about extra words and fences."""
    m = re.search(r"\{.*?\}", text, re.S)
    if not m:
        raise VisionError(f"no JSON in answer: {text[:120]!r}")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise VisionError(f"invalid JSON: {m.group(0)[:120]!r}") from exc
    digits = re.sub(r"[^0-9?]", "", str(obj.get("digits", "")).replace("X", "?").replace("x", "?"))
    if len(digits) != expected:
        raise VisionError(f"expected {expected} characters, got {len(digits)}: {digits!r}")
    try:
        conf = max(0.0, min(1.0, float(obj.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return digits, conf


class VisionClient:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.AsyncClient(timeout=60)

    async def read(self, image: bytes, meter: Meter, *, model: str | None = None) -> VisionResult:
        if not self.api_key:
            raise VisionError("OPENROUTER_API_KEY is not set")
        prompt = PROMPT.format(
            kind=meter.kind,
            unit=meter.unit,
            digits=meter.digits,
            integer=meter.integer_digits,
            decimals=meter.decimals,
        )
        b64 = base64.b64encode(prepare_image(image, meter.crop)).decode()
        body = {
            "model": model or self.model,
            "temperature": 0,
            "max_tokens": 1200,
            "usage": {"include": True},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
        }
        try:
            resp = await self._client.post(
                OPENROUTER_URL, json=body, headers={"Authorization": f"Bearer {self.api_key}"}
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VisionError(f"OpenRouter request failed: {type(exc).__name__}: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionError(f"unexpected OpenRouter answer: {str(data)[:160]}") from exc
        digits, conf = parse_answer(text or "", meter.digits)
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return VisionResult(digits=digits, confidence=conf, cost_usd=cost, raw=text.strip()[:200])
