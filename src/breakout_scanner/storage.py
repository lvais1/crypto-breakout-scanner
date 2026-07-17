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
                    signal_id TEXT PRIMARY KEY, opened_at TEXT NOT NULL, closed_at TEXT,
                    status TEXT NOT NULL, exit_price REAL, pnl_usdt REAL, outcome_r REAL,
                    FOREIGN KEY(signal_id) REFERENCES decisions(signal_id)
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
