"""Reads the digits of a counter from a camera picture with a vision model (any OpenAI-compatible chat API)."""

from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass

import httpx
from PIL import Image, ImageOps

from app.config import DEFAULT_LLM_BASE_URL, Meter

CHAT_URL = DEFAULT_LLM_BASE_URL + "/chat/completions"

PROMPT = """You read a mechanical {kind} meter{unit_part}. The picture shows its row of digit wheels, {digits} wheels in all: \
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


def _oriented(data: bytes, rotate: float, mirror: bool) -> Image.Image:
    img = Image.open(io.BytesIO(data)).convert("L")
    if mirror:
        img = ImageOps.mirror(img)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor=0)
    return img


def _jpeg(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=92)
    return out.getvalue()


def oriented_jpeg(data: bytes, rotate: float = 0.0, mirror: bool = False) -> bytes:
    """The picture after rotate/mirror, before the crop: the frame the crop rectangle is drawn in."""
    return _jpeg(_oriented(data, rotate, mirror))


def prepare_image(
    data: bytes,
    crop: tuple[int, int, int, int] | None = None,
    rotate: float = 0.0,
    mirror: bool = False,
) -> bytes:
    """Mirror/rotate, crop the digit row, stretch the contrast and enlarge it: the models read much better."""
    img = _oriented(data, rotate, mirror)
    if crop:
        w, h = img.size
        x0, y0, x1, y1 = crop
        img = img.crop((max(0, x0), max(0, y0), min(w, x1), min(h, y1)))
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    return _jpeg(img)


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
    """Talks to {base_url}/chat/completions. The key is optional (a local Ollama needs none)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_LLM_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=120)

    async def read(self, image: bytes, meter: Meter, *, model: str | None = None) -> VisionResult:
        prompt = PROMPT.format(
            kind=meter.kind if meter.kind != "generic" else "",
            unit_part=f" ({meter.unit})" if meter.unit else "",
            digits=meter.digits,
            integer=meter.integer_digits,
            decimals=meter.decimals,
        ).replace("a mechanical  meter", "a mechanical meter")
        b64 = base64.b64encode(
            prepare_image(image, meter.crop, meter.rotate, meter.mirror)
        ).decode()
        body = {
            "model": model or self.model,
            "temperature": 0,
            "max_tokens": 1200,
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
        if "openrouter" in self.base_url:
            body["usage"] = {
                "include": True
            }  # OpenRouter reports the cost; other servers would reject the field
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = await self._client.post(
                f"{self.base_url}/chat/completions", json=body, headers=headers
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VisionError(f"model request failed: {type(exc).__name__}: {exc}") from exc
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VisionError(f"unexpected answer: {str(data)[:160]}") from exc
        digits, conf = parse_answer(text or "", meter.digits)
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        return VisionResult(digits=digits, confidence=conf, cost_usd=cost, raw=text.strip()[:200])
