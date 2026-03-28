# Final Multi-Asset Trading Platform

This is the split-broker version:
- Forex execution: OANDA
- Stock execution: Alpaca
- Crypto execution: Alpaca

## What is wired
- Unified Streamlit dashboard
- Broker routing by asset class
- OANDA account, pricing, positions, forex order submit
- Alpaca account, positions, stock/crypto order submit
- Risk checks before order placement
- Paper mode fallback
- Polygon stock scanner support

## What you should do first
1. Copy `.env.example` to `.env`
2. Set `TRADING_MODE=paper`
3. Add Alpaca and OANDA paper/practice credentials
4. Verify account reads and market rows
5. Submit tiny paper/practice orders
6. Only then consider live mode

## Suggested environment
- OANDA practice account for forex
- Alpaca paper account for stock/crypto
- Polygon only if you want stock scanner rows beyond broker account/execution connectivity

## Run
```bash
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```
