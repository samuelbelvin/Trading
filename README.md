
# Real Data Forex + Crypto Pairs Dashboard

Data sources:
- Forex: OANDA instrument candles
- Crypto: Binance public market-data klines

Required env vars:
- OANDA_API_KEY
- OANDA_ACCOUNT_ID

Defaults:
- FOREX_SYMBOLS=EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD
- CRYPTO_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT
- FOREX_GRANULARITY=M15
- CRYPTO_INTERVAL=15m
- CANDLE_COUNT=120
- AUTO_REFRESH_SECONDS=60
