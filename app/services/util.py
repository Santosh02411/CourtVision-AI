from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Iterable


def num(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def rnd(v: Any, nd: int = 1) -> float | None:
    f = num(v)
    return None if f is None else round(f, nd)


def parse_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    s = str(v or "")[:10]
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s if fmt == "%Y-%m-%d" else str(v), fmt).date()
        except ValueError:
            continue
    return None


def zscores(values: list[float | None]) -> list[float]:
    xs = [v for v in values if v is not None]
    if len(xs) < 2:
        return [0.0] * len(values)
    mean = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs)) or 1.0
    return [0.0 if v is None else (v - mean) / sd for v in values]


def percentile_rank(value: float, population: Iterable[float]) -> float:
    pop = sorted(population)
    if not pop:
        return 50.0
    below = sum(1 for x in pop if x < value)
    equal = sum(1 for x in pop if x == value)
    return round(100.0 * (below + 0.5 * equal) / len(pop), 1)


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def clock_seconds(clock: str | None) -> float:
    """ISO8601 'PT05M32.00S' (NBA CDN) or 'M:SS' -> seconds."""
    if not clock:
        return 0.0
    c = str(clock)
    try:
        if c.startswith("PT"):
            m, _, rest = c[2:].partition("M")
            return int(m) * 60 + float(rest.rstrip("S") or 0)
        m, _, s = c.partition(":")
        return int(m) * 60 + float(s or 0)
    except ValueError:
        return 0.0


def time_remaining(period: int, clock: str | None) -> int:
    """Seconds left in regulation (or the current OT period)."""
    left = clock_seconds(clock)
    if period <= 4:
        return int(max(0, (4 - period) * 720 + left))
    return int(max(0, left))


def elapsed_seconds(period: int, clock: str | None) -> float:
    left = clock_seconds(clock)
    if period <= 4:
        return (period - 1) * 720 + (720 - left)
    return 2880 + (period - 5) * 300 + (300 - left)


def fmt_clock(clock: str | None) -> str:
    s = clock_seconds(clock)
    return f"{int(s // 60)}:{int(s % 60):02d}"


def today_et() -> date:
    """NBA schedules are published in US Eastern time."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:  # tzdata missing (e.g. Windows without the tzdata package)
        from datetime import timedelta, timezone
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()
