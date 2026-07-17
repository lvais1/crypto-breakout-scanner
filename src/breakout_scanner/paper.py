from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .models import Direction, Signal
from .risk import round_to_step

ACTIVE_STATUSES = ("WAITING_ENTRY", "OPEN", "PARTIALLY_CLOSED")


@dataclass(frozen=True)
class PaperEvent:
    signal_id: str
    symbol: str
    direction: str
    event_type: str
    target_number: int
    event_time: str
    market_price: float
    execution_price: float
    closed_quantity: float
    remaining_quantity: float
    event_gross_pnl: float
    event_net_pnl: float
    cumulative_net_pnl: float
    cumulative_r: float
    current_stop: float
    targets_hit: list[str]
    close_reason: str | None = None


class PaperTradeEngine:
    def __init__(self, database_path: Path, cfg: Settings) -> None:
        self.path = database_path
        self.cfg = cfg

    def create_trade(self, signal: Signal, step_size: float, mark_price: float, immediate: bool = True) -> bool:
        status = "OPEN" if immediate else "WAITING_ENTRY"
        now = datetime.now(UTC).isoformat()
        actual = signal.entry_price if immediate else None
        entry_fee = signal.entry_price * signal.quantity * self.cfg.fee_rate if immediate else 0.0
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("""
                INSERT OR IGNORE INTO paper_trades(
                    signal_id,symbol,direction,status,planned_entry_price,actual_entry_price,
                    initial_stop_price,current_stop_price,tp1,tp2,tp3,initial_quantity,
                    remaining_quantity,step_size,margin_usdt,leverage,signal_created_at,
                    expiry_time,opened_at,last_market_price,last_price_time,entry_fee_paid,cumulative_fees
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                signal.signal_id, signal.symbol, str(signal.direction), status, signal.entry_price, actual,
                signal.stop_price, signal.stop_price, signal.take_profit_1, signal.take_profit_2,
                signal.take_profit_3, signal.quantity, signal.quantity, step_size, signal.margin_usdt,
                signal.leverage, signal.signal_created_at.isoformat(), signal.expires_at.isoformat(),
                now if immediate else None, mark_price, now, entry_fee, entry_fee,
            ))
            if cursor.rowcount == 1 and immediate:
                db.execute("""INSERT INTO paper_trade_events(signal_id,event_type,target_number,event_time,market_price,execution_price,closed_quantity,remaining_quantity,event_gross_pnl,event_net_pnl,cumulative_net_pnl,cumulative_r,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (signal.signal_id, "ENTRY", 0, now, mark_price, signal.entry_price, 0, signal.quantity, 0, -entry_fee, -entry_fee, 0, json.dumps({"status": "OPEN"})))
            return cursor.rowcount == 1

    def active_symbols(self) -> list[str]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(f"SELECT DISTINCT symbol FROM paper_trades WHERE status IN ({placeholders})", ACTIVE_STATUSES).fetchall()
        return [str(row[0]) for row in rows]

    def recovery_points(self) -> list[tuple[str, datetime]]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                f"SELECT symbol,MIN(last_price_time) FROM paper_trades WHERE status IN ({placeholders}) AND last_price_time IS NOT NULL GROUP BY symbol",
                ACTIVE_STATUSES,
            ).fetchall()
        return [(str(symbol), datetime.fromisoformat(str(last_time))) for symbol, last_time in rows]

    def process_price(self, symbol: str, market_price: float, event_time: datetime) -> list[PaperEvent]:
        if market_price <= 0 or event_time.tzinfo is None:
            return []
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            trades = db.execute(
                "SELECT * FROM paper_trades WHERE symbol=? AND status IN (?,?,?)",
                (symbol, *ACTIVE_STATUSES),
            ).fetchall()
        events: list[PaperEvent] = []
        for trade in trades:
            last_time = trade["last_price_time"]
            if last_time and event_time <= datetime.fromisoformat(last_time):
                continue
            if trade["status"] == "WAITING_ENTRY":
                if event_time >= datetime.fromisoformat(trade["expiry_time"]):
                    event = self._expire(trade, market_price, event_time)
                    if event:
                        events.append(event)
                    continue
                if self._entry_touched(trade, market_price):
                    self._open(trade, market_price, event_time)
                else:
                    self._update_mark(trade["signal_id"], market_price, event_time)
                continue
            events.extend(self._process_open(trade, market_price, event_time))
        return events

    def process_candle(self, symbol: str, high: float, low: float, event_time: datetime) -> list[PaperEvent]:
        """Conservative gap recovery: if stop and target coexist, process stop first."""
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            trades = db.execute("SELECT * FROM paper_trades WHERE symbol=? AND status IN (?,?)", (symbol, "OPEN", "PARTIALLY_CLOSED")).fetchall()
        events: list[PaperEvent] = []
        for trade in trades:
            stop_hit = low <= trade["current_stop_price"] if trade["direction"] == "LONG" else high >= trade["current_stop_price"]
            if stop_hit:
                stop_price = float(trade["current_stop_price"])
                events.extend(self.process_price(symbol, stop_price, event_time))
            else:
                favorable = high if trade["direction"] == "LONG" else low
                events.extend(self.process_price(symbol, favorable, event_time))
        return events

    @staticmethod
    def _entry_touched(t: sqlite3.Row, price: float) -> bool:
        return price <= t["planned_entry_price"] if t["direction"] == "LONG" else price >= t["planned_entry_price"]

    def _open(self, t: sqlite3.Row, price: float, at: datetime) -> None:
        fee = price * t["initial_quantity"] * self.cfg.fee_rate
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_trades SET status='OPEN',actual_entry_price=?,opened_at=?,last_market_price=?,last_price_time=?,entry_fee_paid=?,cumulative_fees=? WHERE signal_id=?",
                       (price, at.isoformat(), price, at.isoformat(), fee, fee, t["signal_id"]))
            db.execute("""INSERT OR IGNORE INTO paper_trade_events(signal_id,event_type,target_number,event_time,market_price,execution_price,closed_quantity,remaining_quantity,event_gross_pnl,event_net_pnl,cumulative_net_pnl,cumulative_r,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (t["signal_id"], "ENTRY", 0, at.isoformat(), price, price, 0, t["initial_quantity"], 0, -fee, -fee, 0, json.dumps({"status": "OPEN"})))

    def _update_mark(self, signal_id: str, price: float, at: datetime) -> None:
        trade = self._load(signal_id)
        entry = float(trade["actual_entry_price"] or trade["planned_entry_price"])
        unrealized = ((price - entry) if trade["direction"] == "LONG" else (entry - price)) * float(trade["remaining_quantity"])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_trades SET last_market_price=?,last_price_time=?,unrealized_pnl=? WHERE signal_id=?", (price, at.isoformat(), unrealized, signal_id))

    def _expire(self, t: sqlite3.Row, price: float, at: datetime) -> PaperEvent | None:
        return self._record(t, "EXPIRED", 0, at, price, float(t["planned_entry_price"]), 0.0, "EXPIRY")

    def _process_open(self, t: sqlite3.Row, price: float, at: datetime) -> list[PaperEvent]:
        direction = t["direction"]
        if (direction == "LONG" and price <= t["current_stop_price"]) or (direction == "SHORT" and price >= t["current_stop_price"]):
            event = self._record(t, "STOP", 0, at, price, float(t["current_stop_price"]), float(t["remaining_quantity"]), "STOP")
            return [event] if event else []
        events: list[PaperEvent] = []
        current = t
        for number in (1, 2, 3):
            if current[f"tp{number}_hit_at"]:
                continue
            target = float(current[f"tp{number}"])
            hit = price >= target if direction == "LONG" else price <= target
            if not hit:
                continue
            fraction = (self.cfg.tp1_close_fraction, self.cfg.tp2_close_fraction, self.cfg.tp3_close_fraction)[number - 1]
            qty = float(current["remaining_quantity"]) if number == 3 else round_to_step(float(current["initial_quantity"]) * fraction, float(current["step_size"]))
            qty = min(qty, float(current["remaining_quantity"]))
            event = self._record(current, "TP", number, at, price, target, qty, "TP3" if number == 3 else None)
            if event:
                events.append(event)
                current = self._load(current["signal_id"])
        if not events:
            self._update_mark(t["signal_id"], price, at)
        return events

    def _load(self, signal_id: str) -> sqlite3.Row:
        db = sqlite3.connect(self.path); db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM paper_trades WHERE signal_id=?", (signal_id,)).fetchone(); db.close()
        if row is None: raise KeyError(signal_id)
        return row

    def _record(self, t: sqlite3.Row, kind: str, target: int, at: datetime, market: float, execution: float, qty: float, close_reason: str | None) -> PaperEvent | None:
        entry = float(t["actual_entry_price"] or t["planned_entry_price"])
        gross = ((execution - entry) if t["direction"] == "LONG" else (entry - execution)) * qty
        exit_fee = execution * qty * self.cfg.fee_rate
        allocated_entry_fee = entry * qty * self.cfg.fee_rate
        slippage = execution * qty * self.cfg.slippage_rate
        net = gross - allocated_entry_fee - exit_fee - slippage
        remaining = max(0.0, float(t["remaining_quantity"]) - qty)
        cumulative_gross = float(t["realized_gross_pnl"]) + gross
        cumulative_net = float(t["realized_net_pnl"]) + net
        fees = float(t["cumulative_fees"]) + exit_fee + slippage
        initial_risk = abs(entry - float(t["initial_stop_price"])) * float(t["initial_quantity"])
        realized_r = cumulative_net / initial_risk if initial_risk else 0.0
        margin_return = cumulative_net / float(t["margin_usdt"]) * 100 if t["margin_usdt"] else 0.0
        new_stop = float(t["current_stop_price"])
        if kind == "TP" and target == 1 and self.cfg.move_stop_to_break_even_after_tp1:
            cost_fraction = 2 * self.cfg.fee_rate + self.cfg.slippage_rate
            new_stop = entry * (1 + cost_fraction if t["direction"] == "LONG" else 1 - cost_fraction)
        if kind == "TP" and target == 2 and self.cfg.stop_after_tp2 == "TP1":
            new_stop = float(t["tp1"])
        final = kind in {"STOP", "EXPIRED"} or remaining <= 1e-12
        status = "EXPIRED" if kind == "EXPIRED" else ("CLOSED" if final else "PARTIALLY_CLOSED")
        payload = {"kind": kind, "target": target, "new_stop": new_stop}
        with sqlite3.connect(self.path) as db:
            try:
                db.execute("""INSERT INTO paper_trade_events(signal_id,event_type,target_number,event_time,market_price,execution_price,closed_quantity,remaining_quantity,event_gross_pnl,event_net_pnl,cumulative_net_pnl,cumulative_r,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (t["signal_id"], kind, target, at.isoformat(), market, execution, qty, remaining, gross, net, cumulative_net, realized_r, json.dumps(payload)))
            except sqlite3.IntegrityError:
                duplicate = db.execute(
                    "SELECT 1 FROM paper_trade_events WHERE signal_id=? AND event_type=? AND target_number=?",
                    (t["signal_id"], kind, target),
                ).fetchone()
                if duplicate:
                    return None
                raise
            hit_column = f"tp{target}_hit_at" if kind == "TP" else ("stop_hit_at" if kind == "STOP" else None)
            hit_sql = f",{hit_column}=?" if hit_column else ""
            params = [status, remaining, new_stop, market, at.isoformat(), cumulative_gross, cumulative_net, fees, realized_r, margin_return, close_reason if final else None, at.isoformat() if final else None]
            if hit_column: params.append(at.isoformat())
            params.append(t["signal_id"])
            db.execute(f"""UPDATE paper_trades SET status=?,remaining_quantity=?,current_stop_price=?,last_market_price=?,last_price_time=?,realized_gross_pnl=?,realized_net_pnl=?,unrealized_pnl=0,cumulative_fees=?,realized_r=?,margin_return_percent=?,close_reason=?,closed_at=?{hit_sql} WHERE signal_id=?""", params)
        refreshed = self._load(t["signal_id"])
        hits = [f"TP{i}" for i in (1,2,3) if refreshed[f"tp{i}_hit_at"]]
        return PaperEvent(t["signal_id"], t["symbol"], t["direction"], kind, target, at.isoformat(), market, execution, qty, remaining, gross, net, cumulative_net, realized_r, new_stop, hits, close_reason if final else None)

    def mark_event_sent(self, event: PaperEvent) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_trade_events SET telegram_sent_at=? WHERE signal_id=? AND event_type=? AND target_number=?",
                       (datetime.now(UTC).isoformat(), event.signal_id, event.event_type, event.target_number))
