@echo off
title Crypto Breakout Scanner - LIVE
cd /d "%~dp0"
echo Crypto Breakout Scanner is running.
echo Watching 10 Bybit linear USDT symbols on closed 5-minute candles.
echo Keep this window open. Press Ctrl+C to stop.
echo.
".venv\Scripts\breakout-scanner.exe" run
echo.
echo Scanner stopped. Press any key to close this window.
pause >nul
