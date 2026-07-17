from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import Settings
from .indicators import finite_row
from .levels import detect_zones
from .models import Decision, Direction, ScoreBreakdown, Signal, SignalStatus, SymbolRules, Zone
from .risk import create_risk_plan, take_profits


def _rejection(row: pd.Series, previous: pd.Series, direction: Direction) -> tuple[bool, int]:
    body = abs(float(row.close - row.open))
    full = max(float(row.high - row.low), 1e-12)
    upper = float(row.high - max(row.open, row.close))
    lower = float(min(row.open, row.close) - row.low)
    if direction == Direction.LONG:
        engulf = row.close > row.open and previous.close < previous.open and row.close >= previous.open and row.open <= previous.close
        wick = lower >= max(body * 1.5, full * 0.35)
        directional = row.close > row.open
    else:
        engulf = row.close < row.open and previous.close > previous.open and row.open >= previous.close and row.close <= previous.open
        wick = upper >= max(body * 1.5, full * 0.35)
        directional = row.close < row.open
    return bool(directional and (engulf or wick)), min(10, (5 if directional else 0) + (3 if wick else 0) + (2 if engulf else 0))


def _breakout(row: pd.Series, zone: Zone, direction: Direction, cfg: Settings) -> tuple[bool, dict[str, float]]:
    atr, close, open_ = float(row.atr14), float(row.close), float(row.open)
    full = max(float(row.high - row.low), 1e-12)
    body = abs(close - open_)
    boundary = zone.high if direction == Direction.LONG else zone.low
    distance = (close - boundary) if direction == Direction.LONG else (boundary - close)
    buffer = max(close * cfg.breakout_price_fraction, atr * cfg.breakout_atr_multiple)
    volume_ratio = float(row.volume / row.volume_ma20) if row.volume_ma20 > 0 else 0.0
    close_location = (close - row.low) / full
    location_ok = close_location >= 2 / 3 if direction == Direction.LONG else close_location <= 1 / 3
    valid = distance >= buffer and body >= cfg.breakout_body_atr * atr and body / full >= cfg.breakout_body_range_fraction and volume_ratio >= cfg.breakout_volume_multiple and location_ok
    return bool(valid), {"distance": distance, "buffer": buffer, "body_atr": body / atr, "body_fraction": body / full, "volume_ratio": volume_ratio, "close_location": close_location}


def _score(frame: pd.DataFrame, zone: Zone, bidx: int, ridx: int, direction: Direction, cfg: Settings) -> ScoreBreakdown:
    breakout, retest = frame.iloc[bidx], frame.iloc[ridx]
    _, rejection_score = _rejection(retest, frame.iloc[ridx - 1], direction)
    distance = abs(float(breakout.close) - (zone.high if direction == Direction.LONG else zone.low))
    buffer = max(float(breakout.close) * cfg.breakout_price_fraction, float(breakout.atr14) * cfg.breakout_atr_multiple)
    volume_ratio = float(breakout.volume / breakout.volume_ma20)
    elapsed = ridx - bidx
    level = min(20, 6 + min(zone.touches, 4) * 2 + min(4, round(zone.reaction_strength * 2)) + (2 if zone.age >= cfg.level_lookback_min else 0))
    breakout_score = min(20, 6 + min(5, round(distance / buffer * 2)) + min(5, round(abs(breakout.close - breakout.open) / breakout.atr14 * 4)) + 4)
    volume = min(15, round(min(volume_ratio / cfg.breakout_volume_multiple, 1.5) * 7) + (4 if retest.volume < breakout.volume else 1))
    tolerance = max(float(retest.close) * cfg.retest_price_fraction, float(retest.atr14) * cfg.retest_atr_multiple)
    boundary = zone.high if direction == Direction.LONG else zone.low
    touch_distance = abs((float(retest.low) if direction == Direction.LONG else float(retest.high)) - boundary)
    retest_score = min(20, 8 + (5 if touch_distance <= tolerance else 0) + (4 if 2 <= elapsed <= 5 else 2) + (3 if retest.volume < breakout.volume else 0))
    close = float(retest.close)
    trend = (close > retest.ema50 and retest.ema50 > retest.ema200) if direction == Direction.LONG else (close < retest.ema50 and retest.ema50 < retest.ema200)
    trend_score = 10 if trend else (5 if (close > retest.ema50) == (direction == Direction.LONG) else 0)
    atr_ratio = float(retest.atr14 / retest.atr_ma50) if retest.atr_ma50 > 0 else 1.0
    market = 5 if atr_ratio <= 1.5 else (2 if atr_ratio <= cfg.max_atr_ratio else 0)
    return ScoreBreakdown(level, breakout_score, volume, retest_score, rejection_score, trend_score, market)


def evaluate(frame: pd.DataFrame, symbol: str, rules: SymbolRules, cfg: Settings) -> Decision:
    reasons: list[str] = []
    needed = ["atr14", "ema50", "ema200", "volume_ma20", "atr_ma50"]
    if len(frame) < 210 or not finite_row(frame.iloc[-1], needed):
        return Decision(SignalStatus.NO_SIGNAL, reasons=["insufficient_or_invalid_indicator_history"])
    zones = detect_zones(frame, cfg)
    if not zones:
        return Decision(SignalStatus.NO_SIGNAL, reasons=["no_valid_multi_touch_zone"])
    last = len(frame) - 1
    for zone in sorted(zones, key=lambda z: (z.touches, z.reaction_strength), reverse=True):
        direction = Direction.LONG if zone.kind == "resistance" else Direction.SHORT
        for bidx in range(max(1, last - cfg.retest_max_candles), last):
            elapsed = last - bidx
            if not cfg.retest_min_candles <= elapsed <= cfg.retest_max_candles:
                continue
            breakout_ok, metrics = _breakout(frame.iloc[bidx], zone, direction, cfg)
            if not breakout_ok:
                continue
            retest = frame.iloc[last]
            tolerance = max(float(retest.close) * cfg.retest_price_fraction, float(retest.atr14) * cfg.retest_atr_multiple)
            touched = float(retest.low) <= zone.high + tolerance if direction == Direction.LONG else float(retest.high) >= zone.low - tolerance
            held = float(retest.close) > zone.high if direction == Direction.LONG else float(retest.close) < zone.low
            rejected, _ = _rejection(retest, frame.iloc[last - 1], direction)
            if not (touched and held and rejected):
                reasons.append("retest_did_not_touch_hold_and_reject")
                continue
            entry = float(retest.close)
            stop = float(retest.low - retest.atr14 * cfg.stop_atr_buffer) if direction == Direction.LONG else float(retest.high + retest.atr14 * cfg.stop_atr_buffer)
            if (direction == Direction.LONG and stop >= entry) or (direction == Direction.SHORT and stop <= entry):
                reasons.append("structural_stop_wrong_side")
                continue
            targets = [z.center for z in zones if (z.center > entry if direction == Direction.LONG else z.center < entry)]
            structural_target = (min(targets) if direction == Direction.LONG else max(targets)) if targets else entry + (3 if direction == Direction.LONG else -3) * abs(entry - stop)
            tp1, tp2, tp3, rr3 = take_profits(direction, entry, stop, structural_target)
            if rr3 < cfg.min_rr:
                reasons.append("next_structure_below_minimum_rr")
                continue
            try:
                plan = create_risk_plan(entry, stop, rules, cfg)
            except ValueError as exc:
                reasons.append(f"risk_plan_rejected:{exc}")
                continue
            score = _score(frame, zone, bidx, last, direction, cfg)
            if score.total < cfg.min_confidence:
                reasons.append(f"confidence_below_threshold:{score.total}")
                continue
            created = pd.Timestamp(retest.close_time).to_pydatetime()
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            candle_delta = pd.Timestamp(frame.iloc[-1].close_time) - pd.Timestamp(frame.iloc[-2].close_time)
            identity = f"{symbol}|{cfg.timeframe}|{direction}|{zone.center:.8f}|{pd.Timestamp(frame.iloc[bidx].close_time).isoformat()}"
            signal_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
            signal = Signal(
                signal_id, symbol, cfg.timeframe, direction, plan.entry, plan.stop, tp1, tp2, tp3,
                cfg.leverage, plan.margin, plan.notional, plan.quantity, plan.price_risk_percent,
                plan.margin_risk_percent, plan.estimated_loss, rr3, score.total, score, zone,
                pd.Timestamp(frame.iloc[bidx].close_time).to_pydatetime(), created, created,
                created + timedelta(seconds=candle_delta.total_seconds() * cfg.signal_expiry_candles),
            )
            return Decision(SignalStatus.PAPER_SIGNAL, signal=signal, diagnostics=metrics)
    return Decision(SignalStatus.NO_SIGNAL, reasons=reasons or ["no_breakout_retest_setup"])

