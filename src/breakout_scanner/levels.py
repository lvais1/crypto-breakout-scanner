from __future__ import annotations

import pandas as pd

from .config import Settings
from .indicators import swing_points
from .models import Zone


def detect_zones(frame: pd.DataFrame, cfg: Settings) -> list[Zone]:
    high_swings, low_swings = swing_points(frame, cfg.swing_width)
    start = max(0, len(frame) - cfg.level_lookback_max)
    end = len(frame) - cfg.swing_width
    candidates: list[tuple[float, int, str]] = []
    for pos in range(start, end):
        if high_swings.iloc[pos]:
            candidates.append((float(frame["high"].iloc[pos]), pos, "resistance"))
        if low_swings.iloc[pos]:
            candidates.append((float(frame["low"].iloc[pos]), pos, "support"))
    zones: list[Zone] = []
    for kind in ("resistance", "support"):
        points = sorted((p for p in candidates if p[2] == kind), key=lambda item: item[0])
        groups: list[list[tuple[float, int, str]]] = []
        for point in points:
            atr = float(frame["atr14"].iloc[point[1]])
            tolerance = max(point[0] * cfg.zone_price_fraction, atr * cfg.zone_atr_multiple)
            if groups and abs(point[0] - sum(x[0] for x in groups[-1]) / len(groups[-1])) <= tolerance:
                groups[-1].append(point)
            else:
                groups.append([point])
        for group in groups:
            indices = sorted(x[1] for x in group)
            separated = [indices[0]] if indices else []
            for idx in indices[1:]:
                if idx - separated[-1] >= cfg.min_touch_separation:
                    separated.append(idx)
            age = len(frame) - 1 - max(separated, default=len(frame))
            if len(separated) < cfg.min_touches or age < 0:
                continue
            prices = [x[0] for x in group if x[1] in separated]
            center = sum(prices) / len(prices)
            atr = float(frame["atr14"].iloc[separated[-1]])
            half_width = max(center * cfg.zone_price_fraction, atr * cfg.zone_atr_multiple)
            reactions = []
            for idx in separated:
                future = frame.iloc[idx + 1 : min(idx + 4, len(frame))]
                if not future.empty:
                    move = (center - future["low"].min()) if kind == "resistance" else (future["high"].max() - center)
                    reactions.append(max(0.0, float(move / max(atr, 1e-12))))
            zones.append(Zone(
                low=center - half_width, high=center + half_width, center=center,
                touches=len(separated), indices=separated, age=age,
                reaction_strength=sum(reactions) / max(1, len(reactions)),
                touch_volume=float(frame["volume"].iloc[separated].mean()), kind=kind,
            ))
    return zones

