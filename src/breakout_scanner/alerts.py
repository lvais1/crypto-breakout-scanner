from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

import aiohttp

from .config import Settings
from .models import Direction, Signal
from .paper import PaperEvent
from .storage import Storage

LOG = logging.getLogger(__name__)


def format_telegram(signal: Signal) -> str:
    s, z, b = signal, signal.breakout_zone, signal.score_breakdown
    emoji = "📈" if s.direction == Direction.LONG else "📉"
    return f"""📊 זוג: {s.symbol}
💵 כניסה: {s.entry_price:.8g} USDT
{emoji} כיוון: {s.direction}
⚡ מינוף: {s.leverage}X

🚫 סטופ לוס: {s.stop_price:.8g} USDT
📏 מרחק סטופ במחיר: {s.price_risk_percent:.3f}%
💥 סיכון מה-Margin: {s.margin_risk_percent:.3f}%
💵 הפסד משוער כולל עלויות: {s.estimated_loss_usdt:.3f} USDT

💰 Margin שהוקצה: {s.margin_usdt:.3f} USDT
📦 שווי פוזיציה: {s.notional_usdt:.3f} USDT
🪙 כמות: {s.quantity:.8g}

🎯 TP1: {s.take_profit_1:.8g} | 1R
🎯 TP2: {s.take_profit_2:.8g} | 2R
🎯 TP3: {s.take_profit_3:.8g} | {s.risk_reward_ratio:.2f}R

🔍 אות: פריצה וריטסט, ביטחון {s.confidence_score}/100, טווח {s.timeframe}.
📋 פירוט: רמה {b.level_quality}/20 | פריצה {b.breakout_quality}/20 | נפח {b.volume_confirmation}/15 | ריטסט {b.retest_quality}/20 | דחייה {b.rejection_candle}/10 | מגמה {b.trend_alignment}/10 | שוק {b.market_quality}/5
🧱 אזור שנפרץ: {z.low:.8g}–{z.high:.8g}
🕒 זמן זיהוי: {s.signal_created_at.isoformat()}
⌛ בתוקף עד: {s.expires_at.isoformat()}

⚠️ אות ל-Paper Trading בלבד. הציון אינו הבטחה להצלחה."""


async def send_telegram(signal: Signal, cfg: Settings, chat_ids: list[int] | None = None) -> bool:
    if not cfg.telegram_bot_token:
        return False
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    timeout = aiohttp.ClientTimeout(total=cfg.request_timeout_seconds)
    recipients = set(chat_ids or [])
    if cfg.telegram_chat_id:
        try:
            recipients.add(int(cfg.telegram_chat_id))
        except ValueError:
            LOG.warning("Configured Telegram chat ID is invalid")
    if not recipients:
        return False
    delivered = False
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for chat_id in recipients:
            try:
                async with session.post(url, data={"chat_id": str(chat_id), "text": format_telegram(signal)}) as response:
                    response.raise_for_status()
                delivered = True
            except aiohttp.ClientError as exc:
                LOG.warning("Telegram alert delivery failed: %s", type(exc).__name__)
    return delivered


def format_paper_event(event: PaperEvent) -> str:
    arrow = "📈" if event.direction == "LONG" else "📉"
    if event.event_type == "EXPIRED":
        return f"⌛ Signal expired without entry\n\n📊 Pair: {event.symbol}\n{arrow} Direction: {event.direction}\n💵 Planned entry: {event.execution_price:.8g}\n\nNo paper trade was opened."
    if event.event_type == "TP":
        message = (
            f"✅ TP{event.target_number} reached\n\n📊 Pair: {event.symbol}\n{arrow} Direction: {event.direction}\n"
            f"💵 Target: {event.execution_price:.8g}\n💵 Observed: {event.market_price:.8g}\n"
            f"📦 Closed: {event.closed_quantity:.8g}\n📦 Remaining: {event.remaining_quantity:.8g}\n"
            f"💰 Cumulative net PnL: {event.cumulative_net_pnl:.3f} USDT\n📏 Result: {event.cumulative_r:.2f}R\n"
            f"🛡️ New stop: {event.current_stop:.8g}\n\n⚠️ Paper Trading only."
        )
        if event.close_reason:
            message += (
                f"\n\n🏁 Paper trade closed\n📋 Reason: {event.close_reason}\n"
                f"🎯 Targets: {', '.join(event.targets_hit)}\n💵 Net PnL: {event.cumulative_net_pnl:.3f} USDT\n"
                f"📏 Result: {event.cumulative_r:.2f}R"
            )
        return message
    message = (
        f"❌ Stop Loss hit\n\n📊 Pair: {event.symbol}\n{arrow} Direction: {event.direction}\n"
        f"🚫 Stop: {event.execution_price:.8g}\n📦 Closed: {event.closed_quantity:.8g}\n"
        f"💥 Event net PnL: {event.event_net_pnl:.3f} USDT\n💰 Total net PnL: {event.cumulative_net_pnl:.3f} USDT\n"
        f"📏 Total: {event.cumulative_r:.2f}R\n📋 Targets hit: {', '.join(event.targets_hit) or 'None'}\n\n⚠️ Paper Trading only."
    )
    if event.close_reason:
        message += f"\n\n🏁 Paper trade closed\n📋 Reason: {event.close_reason}\n💵 Net PnL: {event.cumulative_net_pnl:.3f} USDT"
    return message


async def send_paper_event(event: PaperEvent, cfg: Settings, chat_ids: list[int]) -> bool:
    if not cfg.telegram_bot_token or not chat_ids:
        return False
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    delivered = False
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=cfg.request_timeout_seconds)) as session:
        for chat_id in set(chat_ids):
            try:
                async with session.post(url, data={"chat_id": str(chat_id), "text": format_paper_event(event)}) as response:
                    response.raise_for_status()
                delivered = True
            except aiohttp.ClientError as exc:
                LOG.warning("Telegram paper event delivery failed: %s", type(exc).__name__)
    return delivered


def is_start_command(text: object) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower() == "/start"


def is_stop_command(text: object) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower() == "/stop"


async def listen_for_telegram_commands(cfg: Settings, storage: Storage) -> None:
    if not cfg.telegram_bot_token:
        LOG.warning("Telegram status listener disabled — bot token is missing")
        return

    base_url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}"
    timeout = aiohttp.ClientTimeout(total=40)
    offset: int | None = None
    LOG.info("Telegram /start status listener active")

    while True:
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while True:
                    params: dict[str, object] = {
                        "timeout": 25,
                        "allowed_updates": json.dumps(["message"]),
                    }
                    if offset is not None:
                        params["offset"] = offset
                    async with session.get(f"{base_url}/getUpdates", params=params) as response:
                        response.raise_for_status()
                        payload = await response.json()
                    if payload.get("ok") is not True:
                        raise RuntimeError("Telegram getUpdates returned an error")

                    for update in payload.get("result", []):
                        update_id = update.get("update_id")
                        if isinstance(update_id, int):
                            offset = update_id + 1
                        message = update.get("message", {})
                        chat = message.get("chat", {})
                        if chat.get("type") != "private":
                            continue
                        chat_id = chat.get("id")
                        if not isinstance(chat_id, int):
                            continue
                        text = message.get("text")
                        if is_start_command(text):
                            storage.add_telegram_subscriber(chat_id)
                            status = (
                                "🟢 Active — alerts subscribed\n"
                                "The Bybit breakout scanner is online and monitoring "
                                f"{len(cfg.symbols)} symbols on {cfg.timeframe} candles.\n"
                                f"Checked at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}."
                            )
                        elif is_stop_command(text):
                            storage.remove_telegram_subscriber(chat_id)
                            status = "🔕 Alerts stopped. Send /start to subscribe again."
                        else:
                            continue
                        async with session.post(
                            f"{base_url}/sendMessage",
                            data={"chat_id": str(chat_id), "text": status},
                        ) as response:
                            response.raise_for_status()
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
            LOG.warning("Telegram status listener reconnecting: %s", exc)
            await asyncio.sleep(5)
