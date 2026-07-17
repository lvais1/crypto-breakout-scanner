from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Decision, SignalStatus


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
            existing = {row[1] for row in connection.execute("PRAGMA table_info(paper_trades)")}
            if existing and "symbol" not in existing:
                connection.execute("ALTER TABLE paper_trades RENAME TO paper_trades_legacy")
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY, signal_id TEXT, symbol TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL,
                    direction TEXT, level_key TEXT, payload_json TEXT NOT NULL,
                    reasons_json TEXT NOT NULL, UNIQUE(signal_id)
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_symbol_time ON decisions(symbol, created_at);
                CREATE TABLE IF NOT EXISTS paper_trades (
                    signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                    status TEXT NOT NULL, planned_entry_price REAL NOT NULL, actual_entry_price REAL,
                    initial_stop_price REAL NOT NULL, current_stop_price REAL NOT NULL,
                    tp1 REAL NOT NULL, tp2 REAL NOT NULL, tp3 REAL NOT NULL,
                    initial_quantity REAL NOT NULL, remaining_quantity REAL NOT NULL,
                    step_size REAL NOT NULL, margin_usdt REAL NOT NULL, leverage INTEGER NOT NULL,
                    signal_created_at TEXT NOT NULL, expiry_time TEXT NOT NULL,
                    opened_at TEXT, closed_at TEXT, last_market_price REAL, last_price_time TEXT,
                    tp1_hit_at TEXT, tp2_hit_at TEXT, tp3_hit_at TEXT, stop_hit_at TEXT,
                    realized_gross_pnl REAL NOT NULL DEFAULT 0, realized_net_pnl REAL NOT NULL DEFAULT 0,
                    unrealized_pnl REAL NOT NULL DEFAULT 0, cumulative_fees REAL NOT NULL DEFAULT 0,
                    realized_r REAL NOT NULL DEFAULT 0, margin_return_percent REAL NOT NULL DEFAULT 0,
                    close_reason TEXT, entry_fee_paid REAL NOT NULL DEFAULT 0,
                    FOREIGN KEY(signal_id) REFERENCES decisions(signal_id)
                );
                CREATE TABLE IF NOT EXISTS paper_trade_events (
                    event_id INTEGER PRIMARY KEY, signal_id TEXT NOT NULL, event_type TEXT NOT NULL,
                    target_number INTEGER NOT NULL DEFAULT 0, event_time TEXT NOT NULL,
                    market_price REAL NOT NULL, execution_price REAL NOT NULL,
                    closed_quantity REAL NOT NULL, remaining_quantity REAL NOT NULL,
                    event_gross_pnl REAL NOT NULL, event_net_pnl REAL NOT NULL,
                    cumulative_net_pnl REAL NOT NULL, cumulative_r REAL NOT NULL,
                    payload_json TEXT NOT NULL, telegram_sent_at TEXT,
                    UNIQUE(signal_id,event_type,target_number),
                    FOREIGN KEY(signal_id) REFERENCES paper_trades(signal_id)
                );
                CREATE TABLE IF NOT EXISTS telegram_subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    subscribed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def save(self, symbol: str, decision: Decision) -> bool:
        signal = decision.signal
        payload = signal.as_dict() if signal else {"diagnostics": decision.diagnostics}
        values = (
            signal.signal_id if signal else None, symbol, str(decision.status),
            str(signal.direction) if signal else None,
            f"{signal.breakout_zone.center:.8f}" if signal else None,
            json.dumps(payload, ensure_ascii=False), json.dumps(decision.reasons, ensure_ascii=False),
        )
        try:
            with sqlite3.connect(self.path) as connection:
                connection.execute("INSERT INTO decisions(signal_id,symbol,status,direction,level_key,payload_json,reasons_json) VALUES(?,?,?,?,?,?,?)", values)
            return True
        except sqlite3.IntegrityError:
            return False

    def has_recent_level(self, symbol: str, direction: str, level_key: str, hours: int = 24 * 30) -> bool:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT 1 FROM decisions WHERE symbol=? AND direction=? AND level_key=? AND status=? AND created_at >= datetime('now', ?) LIMIT 1",
                (symbol, direction, level_key, str(SignalStatus.PAPER_SIGNAL), f"-{int(hours)} hours"),
            ).fetchone()
        return row is not None

    def add_telegram_subscriber(self, chat_id: int) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR IGNORE INTO telegram_subscribers(chat_id) VALUES(?)",
                (chat_id,),
            )

    def remove_telegram_subscriber(self, chat_id: int) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("DELETE FROM telegram_subscribers WHERE chat_id=?", (chat_id,))

    def telegram_subscribers(self) -> list[int]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT chat_id FROM telegram_subscribers ORDER BY subscribed_at").fetchall()
        return [int(row[0]) for row in rows]

    def active_paper_trades(self) -> list[dict[str, object]]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("""
                SELECT symbol,direction,status,planned_entry_price,actual_entry_price,
                       current_stop_price,tp1,tp2,tp3,initial_quantity,remaining_quantity,
                       opened_at,last_market_price,last_price_time,tp1_hit_at,tp2_hit_at,
                       tp3_hit_at,realized_net_pnl,unrealized_pnl,realized_r
                FROM paper_trades
                WHERE status IN ('WAITING_ENTRY','OPEN','PARTIALLY_CLOSED')
                ORDER BY signal_created_at
            """).fetchall()
        return [dict(row) for row in rows]
