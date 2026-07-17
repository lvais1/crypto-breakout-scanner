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


def is_status_command(text: object) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower() == "/status"


def is_near_command(text: object) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    return text.strip().split(maxsplit=1)[0].split("@", 1)[0].lower() == "/near"


def format_near_signals(candidates: list[dict[str, object]]) -> str:
    if not candidates:
        return "🔭 כרגע אין צמדים שעברו את שלב הפריצה ומתקרבים לתנאי ההתראה.\n\nהנתון יתעדכן בסגירת הנר הבא."
    lines = ["🔭 צמדים הקרובים להתראה", ""]
    stage_names = {"RETEST": "ממתין לאישור Retest", "CONFIDENCE": "Setup מלא, ציון נמוך מהסף", "RISK_REWARD": "Setup קיים, יחס סיכון/סיכוי לא מספיק", "RISK_PLAN": "Setup קיים, תכנית הסיכון נפסלה"}
    for item in candidates:
        missing = []
        if item.get("stage") == "RETEST":
            if not item.get("touched"): missing.append("נגיעה ברמה")
            if not item.get("held"): missing.append("החזקה מעבר לרמה")
            if not item.get("rejected"): missing.append("נר דחייה")
        detail = f"\n   חסר: {', '.join(missing)}" if missing else ""
        confidence = f"\n   ציון: {item.get('confidence_score')}/{item.get('required_confidence')}" if item.get("stage") == "CONFIDENCE" else ""
        lines.append(
            f"• {item['symbol']} | {item.get('direction', '?')} | קרבה טכנית {item['proximity']}%\n"
            f"   {stage_names.get(str(item.get('stage')), str(item.get('stage')))}{detail}{confidence}\n"
            f"   עודכן: {item['created_at']} UTC"
        )
    lines.append("\n⚠️ אחוז הקרבה הוא מדד שלבי פנימי, לא הסתברות להצלחת עסקה.")
    return "\n".join(lines)


def format_active_trades(trades: list[dict[str, object]]) -> str:
    if not trades:
        return "⚪ אין עסקאות Paper פעילות כרגע.\n\nהסורק ממשיך לעבוד. כשייווצר אות חדש הוא יופיע כאן ויהיה ניתן לעקוב אחריו עם /status."
    sections = [f"📡 עסקאות Paper פעילות: {len(trades)}"]
    for trade in trades:
        hits = [f"TP{i}" for i in (1, 2, 3) if trade.get(f"tp{i}_hit_at")]
        next_target = next((f"TP{i}: {float(trade[f'tp{i}']):.8g}" for i in (1, 2, 3) if not trade.get(f"tp{i}_hit_at")), "אין")
        last_time = str(trade.get("last_price_time") or "טרם התקבל")
        entry = trade.get("actual_entry_price") or trade["planned_entry_price"]
        sections.append(
            "\n".join([
                f"\n🟢 {trade['symbol']} — {trade['status']}",
                f"📈/📉 כיוון: {trade['direction']}",
                f"💵 כניסה: {float(entry):.8g}",
                f"📍 מחיר Mark אחרון: {float(trade['last_market_price']):.8g}" if trade.get("last_market_price") is not None else "📍 מחיר Mark אחרון: אין",
                f"🛡️ סטופ נוכחי: {float(trade['current_stop_price']):.8g}",
                f"🎯 היעד הבא: {next_target}",
                f"✅ יעדים שהושגו: {', '.join(hits) or 'אין'}",
                f"📦 כמות שנותרה: {float(trade['remaining_quantity']):.8g} / {float(trade['initial_quantity']):.8g}",
                f"💰 PnL ממומש נטו: {float(trade['realized_net_pnl']):.3f} USDT",
                f"〽️ PnL פתוח: {float(trade['unrealized_pnl']):.3f} USDT",
                f"📏 תוצאה ממומשת: {float(trade['realized_r']):.2f}R",
                f"🕒 עדכון מחיר אחרון: {last_time}",
            ])
        )
    sections.append("\n⚠️ Paper Trading בלבד.")
    return "\n".join(sections)


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
                        elif is_status_command(text):
                            status = format_active_trades(storage.active_paper_trades())
                        elif is_near_command(text):
                            status = format_near_signals(storage.near_signal_pairs())
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
