from __future__ import annotations

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume", "open_time", "close_time"}


def enrich(frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"missing market columns: {sorted(missing)}")
    out = frame.copy()
    numeric = ["open", "high", "low", "close", "volume"]
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="coerce")
    if out[numeric].isna().any().any():
        raise ValueError("market data contains NaN/non-numeric values")
    previous_close = out["close"].shift(1)
    tr = pd.concat(
        [(out["high"] - out["low"]), (out["high"] - previous_close).abs(), (out["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    for period in (20, 50, 200):
        out[f"ema{period}"] = out["close"].ewm(span=period, adjust=False, min_periods=period).mean()
    out["volume_ma20"] = out["volume"].rolling(20).mean().shift(1)
    out["atr_ma50"] = out["atr14"].rolling(50).mean().shift(1)
    return out


def swing_points(frame: pd.DataFrame, width: int = 3) -> tuple[pd.Series, pd.Series]:
    highs = frame["high"]
    lows = frame["low"]
    swing_high = pd.Series(False, index=frame.index)
    swing_low = pd.Series(False, index=frame.index)
    for pos in range(width, len(frame) - width):
        high_window = highs.iloc[pos - width : pos + width + 1]
        low_window = lows.iloc[pos - width : pos + width + 1]
        swing_high.iloc[pos] = highs.iloc[pos] == high_window.max() and int((high_window == highs.iloc[pos]).sum()) == 1
        swing_low.iloc[pos] = lows.iloc[pos] == low_window.min() and int((low_window == lows.iloc[pos]).sum()) == 1
    return swing_high, swing_low


def finite_row(row: pd.Series, fields: list[str]) -> bool:
    return all(pd.notna(row.get(name)) and np.isfinite(float(row[name])) for name in fields)

