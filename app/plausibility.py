"""Decides whether a reading may be believed.

A counter only ever goes up, and only as fast as the pipe allows. That is the whole trick that turns a
mediocre read-out (blurry wheels, "?" here and there) into a reliable number: a reading that jumps back,
leaps ahead or does not fit the last value is thrown away instead of published.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from app.config import Meter

# Wheels can be caught half-way: a small step back is a misread of the fastest wheel, not a real rollback.
ROLLBACK_TOLERANCE = 0.02
MAX_UNKNOWN_WHEELS = 4


@dataclass(frozen=True)
class Reading:
    value: float
    at: datetime


@dataclass(frozen=True)
class Decision:
    status: str  # "accepted" | "unchanged" | "rejected"
    value: float | None  # the value to publish (the last good one when unchanged or rejected)
    reason: str = ""


def vote(samples: list[str]) -> tuple[str, float]:
    """Majority per wheel over several reads. "?" does not vote. Returns (digits, agreement 0..1)."""
    if not samples:
        raise ValueError("no samples")
    out, agreed = [], 0
    for position in zip(*samples, strict=True):
        counts = Counter(c for c in position if c != "?")
        if not counts:
            out.append("?")
            continue
        (digit, n), *rest = counts.most_common()
        if rest and rest[0][1] == n:  # tie: do not guess
            out.append("?")
            continue
        out.append(digit)
        if n * 2 > len(position):
            agreed += 1
    return "".join(out), agreed / len(out)


def _to_value(digits: str, decimals: int) -> float:
    return int(digits) / 10**decimals


def _complete(digits: str, meter: Meter, low: float, high: float) -> float | None:
    """Fill the "?" wheels so that the value lies in [low, high]; the smallest such value, or None."""
    unknown = [i for i, c in enumerate(digits) if c == "?"]
    if len(unknown) > MAX_UNKNOWN_WHEELS:
        return None
    best = None
    for combo in itertools.product("0123456789", repeat=len(unknown)):
        chars = list(digits)
        for i, c in zip(unknown, combo, strict=True):
            chars[i] = c
        value = _to_value("".join(chars), meter.decimals)
        if low <= value <= high and (best is None or value < best):
            best = value
    return best


def decide(meter: Meter, digits: str, last: Reading | None, now: datetime) -> Decision:
    """Judge one (voted) digit string against the last accepted reading."""
    if len(digits) != meter.digits:
        return Decision(
            "rejected",
            last.value if last else None,
            f"{len(digits)} wheels, expected {meter.digits}",
        )
    resolution = 10**-meter.decimals

    if last is None:
        if "?" in digits:
            return Decision("rejected", None, "first reading has unreadable wheels")
        return Decision("accepted", _to_value(digits, meter.decimals), "first reading")

    hours = max((now - last.at).total_seconds() / 3600, 0.25)
    low = last.value - ROLLBACK_TOLERANCE
    high = last.value + meter.max_rate_per_hour * hours + 5 * resolution

    if "?" in digits:
        value = _complete(digits, meter, max(low, last.value), high)
        if value is None:
            return Decision("rejected", last.value, "unreadable wheels do not fit the last value")
    else:
        value = _to_value(digits, meter.decimals)
        if value > high:
            return Decision("rejected", last.value, f"{value:.3f} is more than {high:.3f} (rate)")
        if value < low:
            return Decision(
                "rejected", last.value, f"{value:.3f} is below the last value {last.value:.3f}"
            )
    if value <= last.value:
        return Decision("unchanged", last.value, "no change")
    return Decision("accepted", round(value, meter.decimals), "")
