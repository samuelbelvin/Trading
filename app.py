import os
import time
import random
from datetime import datetime
import streamlit as st

st.set_page_config(page_title="Trading Dashboard", layout="wide")

st.title("Trading Dashboard")
st.caption("Starter deployment package for Render + iPad access")

twilio_configured = all(
    os.getenv(k) for k in [
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM",
        "TWILIO_TO",
    ]
)
polygon_configured = bool(os.getenv("POLYGON_API_KEY"))

col1, col2 = st.columns(2)
with col1:
    st.subheader("Service status")
    st.write(f"Twilio configured: {'Yes' if twilio_configured else 'No'}")
    st.write(f"Polygon configured: {'Yes' if polygon_configured else 'No'}")
    st.write("Server time:", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))

with col2:
    st.subheader("Notes")
    st.write("This is a deployment-safe starter app.")
    st.write("Once deployed successfully, the scanner and live feeds can be layered in.")
    st.write("This version is designed to confirm Render, Streamlit, and environment settings are correct.")

st.subheader("Sample ranked opportunities")
symbols = ["BTCUSDT", "ETHUSDT", "AAPL", "NVDA", "EURUSD", "TSLA"]
rows = []
for s in symbols:
    rows.append({
        "symbol": s,
        "score": round(random.uniform(55, 88), 2),
        "signal": random.choice(["Watch", "Momentum", "Breakout", "A+"]),
        "updated": datetime.now().strftime("%H:%M:%S"),
    })

st.dataframe(rows, use_container_width=True)

st.info("If you can see this page on Render, your Blueprint, port binding, and Python runtime are working.")
