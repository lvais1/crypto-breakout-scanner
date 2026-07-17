from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Settings
from .detector import evaluate
from .indicators import enrich
from .models import Direction, Signal, SignalStatus, SymbolRules


@dataclass
class TradeResult:
    signal: Signal
    exit_price: float
    outcome_r: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str


def _simulate(signal: Signal, future: pd.DataFrame, cfg: Settings) -> TradeResult:
    sign = 1 if signal.direction == Direction.LONG else -1
    risk = abs(signal.entry_price - signal.stop_price)
    exit_price, reason = float(future.iloc[-1].close), "end_of_data"
    for row in future.itertuples():
        stop_hit = row.low <= signal.stop_price if sign == 1 else row.high >= signal.stop_price
        tp_hit = row.high >= signal.take_profit_2 if sign == 1 else row.low <= signal.take_profit_2
        if stop_hit:  # Conservative same-candle ordering.
            exit_price, reason = signal.stop_price, "stop"
            break
        if tp_hit:
            exit_price, reason = signal.take_profit_2, "tp2"
            break
    gross = sign * (exit_price - signal.entry_price) * signal.quantity
    costs = (signal.entry_price + exit_price) * signal.quantity * (cfg.fee_rate + cfg.slippage_rate)
    return TradeResult(signal, exit_price, sign * (exit_price - signal.entry_price) / risk, gross, gross - costs, reason)


def run_backtest(raw: pd.DataFrame, symbol: str, rules: SymbolRules, cfg: Settings, warmup: int = 210, horizon: int = 24) -> tuple[pd.DataFrame, dict[str, float]]:
    frame = enrich(raw)
    trades: list[TradeResult] = []
    seen: set[str] = set()
    for end in range(warmup, len(frame) - horizon):
        historical = frame.iloc[: end + 1].copy()  # Point-in-time slice prevents look-ahead.
        decision = evaluate(historical, symbol, rules, cfg)
        if decision.status != SignalStatus.PAPER_SIGNAL or decision.signal is None or decision.signal.signal_id in seen:
            continue
        seen.add(decision.signal.signal_id)
        trades.append(_simulate(decision.signal, frame.iloc[end + 1 : end + 1 + horizon], cfg))
    rows = [{"signal_id": t.signal.signal_id, "direction": str(t.signal.direction), "confidence": t.signal.confidence_score, "outcome_r": t.outcome_r, "gross_pnl": t.gross_pnl, "net_pnl": t.net_pnl, "exit_reason": t.exit_reason} for t in trades]
    report = pd.DataFrame(rows)
    if report.empty:
        return report, {"trades": 0.0, "win_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0, "max_drawdown": 0.0, "average_r": 0.0}
    equity = report.net_pnl.cumsum()
    drawdown = equity - equity.cummax()
    wins, losses = report.loc[report.net_pnl > 0, "net_pnl"].sum(), -report.loc[report.net_pnl < 0, "net_pnl"].sum()
    metrics = {"trades": float(len(report)), "win_rate": float((report.net_pnl > 0).mean()), "profit_factor": float(wins / losses) if losses else float("inf"), "expectancy": float(report.net_pnl.mean()), "max_drawdown": float(-drawdown.min()), "average_r": float(report.outcome_r.mean()), "gross_pnl": float(report.gross_pnl.sum()), "net_pnl": float(report.net_pnl.sum()), "false_breakouts": float((report.exit_reason == "stop").sum())}
    return report, metrics

