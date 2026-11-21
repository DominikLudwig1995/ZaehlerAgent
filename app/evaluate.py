"""Compare vision models (and the camera's own reading) on saved pictures.

    uv run python -m app.evaluate --dir eval/ --truth gas=3592,wasser=00149 --models a/b,c/d

The directory holds the pictures as <meter>-<time>.jpg, optionally with <meter>-<time>.json (the camera's own
answer from /json). --truth gives the leading wheels that are known to be right for the whole session (the
whole-number wheels do not move within minutes); the fraction wheels are checked for plausibility only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from app.config import DEFAULT_LLM_BASE_URL, Meter, load_meters
from app.vision import VisionClient, VisionError


def device_digits(path: Path, meter: Meter) -> str:
    """The camera's own reading as a digit string ("?" for N), or "" when there is none."""
    f = path.with_suffix(".json")
    if not f.is_file():
        return ""
    try:
        raw = str(json.loads(f.read_text())["main"]["raw"])
    except (KeyError, ValueError):
        return ""
    digits = re.sub(r"[^0-9N]", "", raw).replace("N", "?")
    return digits.rjust(meter.digits, "0")[-meter.digits :] if digits else ""


def score(digits: str, truth: str) -> tuple[int, int]:
    """(right, total) over the leading wheels that are known."""
    right = sum(1 for a, b in zip(digits, truth, strict=False) if a == b)
    return right, len(truth)


async def run(args: argparse.Namespace) -> int:
    meters = {m.name: m for m in load_meters(args.meters)}
    truth = dict(item.split("=") for item in args.truth.split(","))
    client = VisionClient(
        os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY", ""),
        args.models.split(",")[0],
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
    )
    files = sorted(Path(args.dir).glob("*.jpg"))
    summary: dict[tuple[str, str], list[int]] = {}
    cost = 0.0
    for f in files:
        name = f.stem.split("-")[0]
        meter = meters.get(name)
        if meter is None or name not in truth:
            continue
        data = f.read_bytes()
        dev = device_digits(f, meter)
        if dev:
            r, t = score(dev, truth[name])
            summary.setdefault((name, "kamera-eigen"), [0, 0, 0, 0])
            s = summary[(name, "kamera-eigen")]
            s[0] += r
            s[1] += t
            s[2] += 1
            s[3] += int(r == t)
        line = f"{f.stem:16} kamera={dev or '-':10}"
        for model in args.models.split(","):
            try:
                res = await client.read(data, meter, model=model)
            except VisionError as exc:
                line += f" | {model.split('/')[-1][:18]}=FEHLER {str(exc)[:40]}"
                continue
            cost += res.cost_usd
            r, t = score(res.digits, truth[name])
            s = summary.setdefault((name, model), [0, 0, 0, 0])
            s[0] += r
            s[1] += t
            s[2] += 1
            s[3] += int(r == t)
            line += f" | {model.split('/')[-1][:18]}={res.digits} ({r}/{t})"
        print(line)
    print("\nErgebnis (richtige fuehrende Ziffern; Bilder mit allen bekannten Ziffern richtig):")
    for (name, model), (right, total, n, full) in sorted(summary.items()):
        print(
            f"  {name:7} {model:42} Ziffern {right}/{total} = {100 * right / max(total, 1):5.1f} %   "
            f"Bilder voll richtig {full}/{n}"
        )
    print(f"Kosten: {cost:.4f} USD")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True)
    ap.add_argument("--truth", required=True, help="meter=leading digits, comma separated")
    ap.add_argument("--models", required=True, help="comma separated OpenRouter model ids")
    ap.add_argument("--meters", default="config/config.yml")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
