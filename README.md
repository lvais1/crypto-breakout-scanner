# Crypto Breakout/Retest Scanner

מערכת Python 3.12 לסריקת חוזים לינאריים מסוג Bybit USDT על בסיס נרות סגורים בלבד. היא מזהה אזורי swing מרובי נגיעות, פריצה עם גוף ונפח, וריטסט עם נר דחייה; מחשבת ציון דטרמיניסטי, גודל פוזיציה, סטופ מבני ויעדי רווח; שומרת כל החלטה ב-SQLite ושולחת רק אותות Paper Trading ל-Telegram.

> אין בפרויקט קוד לשליחת פקודות מסחר אמיתיות. הוא מיועד לסריקה, Backtesting ו-Paper Trading בלבד.

## התקנה

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

מלאו ב-`.env` את `TELEGRAM_BOT_TOKEN` ו-`TELEGRAM_CHAT_ID` רק אם נדרשות התראות. אין צורך במפתחות Bybit: המערכת קוראת נתוני שוק ציבוריים בלבד.

## שימוש

```powershell
# סריקה חד-פעמית
breakout-scanner once

# האזנה לנרות סגורים ב-WebSocket, עם השלמת היסטוריה ב-REST
breakout-scanner run

# Backtest על CSV בעל open_time,close_time,open,high,low,close,volume
breakout-scanner backtest candles.csv --symbol BTCUSDT --tick-size 0.1 --step-size 0.001

# בדיקות
pytest
```

ה-Backtester כותב `backtest_trades.csv` ומדפיס מספר עסקאות, Win rate, Profit factor, Expectancy, Maximum drawdown, Average R ותוצאות לפני/אחרי עלויות. כל נקודת החלטה מקבלת רק slice היסטורי עד אותו נר; שלוש הנרות שאחרי swing נחוצים לאישורו ולכן swing נהיה זמין רק בדיעבד, בלי Look-ahead.

## מבנה

- `market.py` — Bybit V5 REST/WebSocket עם TLS, timeout, reconnect ו-host allowlist.
- `indicators.py`, `levels.py` — ATR/EMA/נפח, swings ואזורי תמיכה/התנגדות.
- `detector.py` — Breakout→Retest, פסילות וציון מוסבר 0–100.
- `risk.py` — סטופ מבני, sizing דינמי, Tick/Step/Notional, עמלות והחלקה.
- `storage.py` — SQLite בשאילתות פרמטריות, מניעת כפילויות ושמירת NO_SIGNAL.
- `alerts.py` — הודעת Telegram בעברית ו-JSON מלא.
- `backtest.py` — סימולציה שמרנית ללא Look-ahead.

## הנחות ושיקולי בטיחות

- נרות Bybit שטרם נסגרו מסוננים לפי זמן הסגירה לפני הניתוח.
- אם TP וסטופ נוגעים באותו נר ב-Backtest, הסטופ נחשב ראשון (הנחה שמרנית).
- TP3 הוא המבנה הנגדי הקרוב; כשאין מבנה כזה הוא מוגדר ל-3R, אך האות עדיין חייב לעבור 1.5R.
- Telegram token נטען רק מהסביבה ואינו נרשם ללוג. כל כתובות ה-API מקובעות ל-Bybit/Telegram, אימות TLS נשאר פעיל, ושאילתות SQLite פרמטריות.
- יש להריץ Backtest על מאות עסקאות ולבצע חלוקת training/validation/out-of-sample לפני הסקת מסקנות. אין לראות בציון הביטחון הסתברות הצלחה.
