from __future__ import annotations

import asyncio
import json
import logging

from .alerts import listen_for_telegram_commands, send_telegram
from .config import Settings
from .detector import evaluate
from .indicators import enrich
from .market import BybitMarketData
from .models import Decision, SignalStatus
from .storage import Storage

LOG = logging.getLogger(__name__)


class Scanner:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.market = BybitMarketData(cfg)
        self.storage = Storage(cfg.database_path)
        self.storage.initialize()

    async def scan_symbol(self, symbol: str) -> bool:
        try:
            frame = enrich(await self.market.klines(symbol, self.cfg.timeframe, self.cfg.history_limit))
            rules = await self.market.symbol_rules(symbol)
            decision = evaluate(frame, symbol, rules, self.cfg)
            if decision.signal:
                signal = decision.signal
                mark_price = await self.market.mark_price(symbol)
                risk = abs(signal.entry_price - signal.stop_price)
                decision.diagnostics.update({"mark_price": mark_price, "contract_price": float(frame.iloc[-1].close)})
                if abs(mark_price - signal.entry_price) > self.cfg.max_entry_drift_r * risk:
                    rejected = Decision(
                        SignalStatus.NO_SIGNAL,
                        reasons=["mark_price_outside_0.25R_entry_range"],
                        diagnostics=decision.diagnostics,
                    )
                    self.storage.save(symbol, rejected)
                    LOG.info("%-14s NO_SIGNAL — stale entry", symbol)
                    return True
                level_key = f"{signal.breakout_zone.center:.8f}"
                if self.storage.has_recent_level(symbol, str(signal.direction), level_key):
                    LOG.info("%-14s NO_SIGNAL — duplicate level", symbol)
                    return True
                if self.storage.save(symbol, decision):
                    await send_telegram(signal, self.cfg)
                    LOG.info("%-14s PAPER_SIGNAL — %s score=%s", symbol, signal.direction, signal.confidence_score)
                    print(json.dumps(signal.as_dict(), ensure_ascii=False, indent=2))
            else:
                self.storage.save(symbol, decision)
                if self.cfg.debug_decisions:
                    LOG.info("%-14s NO_SIGNAL — %s", symbol, ", ".join(decision.reasons))
            return True
        except Exception:
            LOG.exception("%-14s ERROR — symbol scan failed", symbol)
            return False

    async def once(self) -> None:
        LOG.info("SCAN START — %d Bybit symbols", len(self.cfg.symbols))
        results = [await self.scan_symbol(symbol) for symbol in self.cfg.symbols]
        succeeded = sum(results)
        LOG.info("SCAN COMPLETE — %d/%d succeeded", succeeded, len(self.cfg.symbols))
        if succeeded != len(self.cfg.symbols):
            raise RuntimeError(f"scan failed for {len(self.cfg.symbols) - succeeded} symbol(s)")

    async def run(self) -> None:
        await self.once()
        await asyncio.gather(self._run_market_stream(), listen_for_telegram_commands(self.cfg))

    async def _run_market_stream(self) -> None:
        cycle_end: object | None = None
        checked: set[str] = set()
        async for symbol, candle in self.market.closed_klines():
            candle_end = candle.get("end")
            if candle_end != cycle_end:
                cycle_end = candle_end
                checked = set()
                LOG.info("CANDLE CYCLE START — waiting for %d symbols", len(self.cfg.symbols))
            await self.scan_symbol(symbol)
            checked.add(symbol)
            LOG.info("CYCLE PROGRESS — %d/%d checked", len(checked), len(self.cfg.symbols))
            if len(checked) == len(self.cfg.symbols):
                LOG.info("CANDLE CYCLE COMPLETE — %d/%d checked", len(checked), len(self.cfg.symbols))
