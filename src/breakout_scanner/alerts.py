from __future__ import annotations

import aiohttp

from .config import Settings
from .models import Direction, Signal


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


async def send_telegram(signal: Signal, cfg: Settings) -> bool:
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return False
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    timeout = aiohttp.ClientTimeout(total=cfg.request_timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, data={"chat_id": cfg.telegram_chat_id, "text": format_telegram(signal)}) as response:
            response.raise_for_status()
    return True

