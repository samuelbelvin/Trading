# Trading Dashboard - Balanced Upgrade

This version upgrades the deployment-safe starter into a balanced live scanner.

## What it does
- Polls Binance public market data for crypto
- Polls Polygon snapshots for stocks and forex
- Scores opportunities across crypto, stocks, and forex
- Sends SMS alerts through Twilio on stronger setups
- Exposes a Streamlit dashboard suitable for Render + iPad viewing

## Required environment variables
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM
- TWILIO_TO
- POLYGON_API_KEY

## Optional environment variables
- BINANCE_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT
- POLYGON_STOCKS=AAPL,NVDA,TSLA,AMD,META,MSFT
- POLYGON_FOREX=C:EURUSD,C:GBPUSD,C:USDJPY
- POLL_SECONDS=15
- ALERT_THRESHOLD=70
- ALERT_COOLDOWN_MINUTES=20

## Render start command
Defined in render.yaml:
streamlit run app.py --server.address 0.0.0.0 --server.port $PORT

## Important
This is a ranked-opportunity scanner, not an execution engine.
It is designed to surface candidates with stronger conditions, not guarantee profitability.
