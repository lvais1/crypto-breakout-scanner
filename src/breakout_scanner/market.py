from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import aiohttp
import pandas as pd

from .config import Settings
from .models import SymbolRules

LOG = logging.getLogger(__name__)

INTERVALS = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "12h": "720",
    "1d": "D", "1w": "W", "1M": "M",
}


class BybitMarketData:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.timeout = aiohttp.ClientTimeout(total=cfg.request_timeout_seconds)

    async def klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        url = f"{self.cfg.rest_base_url}/v5/market/kline"
        params = {
            "category": "linear", "symbol": symbol,
            "interval": self._interval(interval), "limit": min(limit + 1, 1000),
        }
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
        self._check_response(data)
        rows = list(reversed(data["result"]["list"]))
        frame = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume", "turnover"])
        frame["open_time"] = pd.to_datetime(frame["open_time"].astype("int64"), unit="ms", utc=True)
        frame["close_time"] = frame["open_time"] + self._interval_duration(interval)
        frame = frame[frame["close_time"] <= pd.Timestamp.now(tz="UTC")]
        return frame.tail(limit).reset_index(drop=True)

    async def mark_price(self, symbol: str) -> float:
        url = f"{self.cfg.rest_base_url}/v5/market/tickers"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, params={"category": "linear", "symbol": symbol}) as response:
                response.raise_for_status()
                data = await response.json()
        self._check_response(data)
        return float(data["result"]["list"][0]["markPrice"])

    async def mark_price_klines(self, symbol: str, start_ms: int) -> list[dict[str, object]]:
        url = f"{self.cfg.rest_base_url}/v5/market/mark-price-kline"
        params = {"category": "linear", "symbol": symbol, "interval": "1", "start": start_ms, "limit": 1000}
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
        self._check_response(data)
        return [
            {"start": int(row[0]), "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])}
            for row in reversed(data["result"]["list"])
        ]

    async def symbol_rules(self, symbol: str) -> SymbolRules:
        url = f"{self.cfg.rest_base_url}/v5/market/instruments-info"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url, params={"category": "linear", "symbol": symbol}) as response:
                response.raise_for_status()
                data = await response.json()
        self._check_response(data)
        item = next((s for s in data["result"]["list"] if s["symbol"] == symbol and s["status"] == "Trading"), None)
        if item is None:
            raise ValueError(f"unknown Bybit linear symbol: {symbol}")
        return SymbolRules(
            float(item["priceFilter"]["tickSize"]),
            float(item["lotSizeFilter"]["qtyStep"]),
            float(item["lotSizeFilter"]["minNotionalValue"]),
        )

    async def closed_klines(self) -> AsyncIterator[tuple[str, dict[str, object]]]:
        interval = self._interval(self.cfg.timeframe)
        topics = [f"kline.{interval}.{symbol}" for symbol in self.cfg.symbols]
        delay = 1.0
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(self.cfg.ws_base_url, heartbeat=20) as ws:
                        await ws.send_json({"op": "subscribe", "args": topics})
                        delay = 1.0
                        while True:
                            try:
                                message = await ws.receive(timeout=20)
                            except asyncio.TimeoutError:
                                await ws.send_json({"op": "ping"})
                                continue
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                candles = payload.get("data", [])
                                if candles and candles[0].get("confirm") is True:
                                    symbol = str(payload["topic"]).rsplit(".", 1)[-1]
                                    yield symbol, candles[0]
                            elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                raise aiohttp.ClientConnectionError("Bybit websocket closed")
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
                LOG.warning("Bybit websocket reconnect: %s (retry in %.0fs)", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.cfg.reconnect_max_seconds)

    async def mark_prices(self, symbols: list[str]) -> AsyncIterator[tuple[str, float, datetime]]:
        topics = [f"tickers.{symbol}" for symbol in symbols]
        delay = 1.0
        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_read=None)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(self.cfg.ws_base_url, heartbeat=20) as ws:
                        await ws.send_json({"op": "subscribe", "args": topics})
                        delay = 1.0
                        while True:
                            try:
                                message = await ws.receive(timeout=20)
                            except asyncio.TimeoutError:
                                await ws.send_json({"op": "ping"})
                                continue
                            if message.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(message.data)
                                data = payload.get("data", {})
                                mark = data.get("markPrice") if isinstance(data, dict) else None
                                topic = str(payload.get("topic", ""))
                                if topic.startswith("tickers.") and mark not in (None, ""):
                                    yield topic.split(".", 1)[1], float(mark), datetime.fromtimestamp(int(payload["ts"]) / 1000, UTC)
                            elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                                raise aiohttp.ClientConnectionError("Bybit mark-price websocket closed")
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError, KeyError) as exc:
                LOG.warning("Bybit mark-price reconnect: %s (retry in %.0fs)", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.cfg.reconnect_max_seconds)

    @staticmethod
    def _interval(interval: str) -> str:
        try:
            return INTERVALS[interval]
        except KeyError as exc:
            raise ValueError(f"unsupported Bybit timeframe: {interval}") from exc

    @staticmethod
    def _interval_duration(interval: str) -> pd.Timedelta:
        if interval.endswith("m"):
            return pd.Timedelta(minutes=int(interval[:-1]))
        if interval.endswith("h"):
            return pd.Timedelta(hours=int(interval[:-1]))
        if interval == "1d":
            return pd.Timedelta(days=1)
        if interval == "1w":
            return pd.Timedelta(weeks=1)
        return pd.Timedelta(days=31)

    @staticmethod
    def _check_response(data: dict[str, object]) -> None:
        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit API error {data.get('retCode')}: {data.get('retMsg')}")
