import os
import time
import threading
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Trading Dashboard", layout="wide")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_STOCKS = ["AAPL","NVDA","TSLA"]

state = {"rows": [], "status": "starting", "last_update": None, "errors": []}
lock = threading.Lock()

def log(msg):
    with lock:
        state["errors"].append(msg)

def scan():
    rows = []
    for s in POLYGON_STOCKS:
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{s}/prev?apiKey={POLYGON_API_KEY}"
            r = requests.get(url).json()
            if "results" in r:
                price = r["results"][0]["c"]
                rows.append({"symbol": s, "price": price})
        except Exception as e:
            log(str(e))
    return rows

def loop():
    while True:
        rows = scan()
        with lock:
            state["rows"] = rows
            state["status"] = "running"
            state["last_update"] = datetime.now().strftime("%H:%M:%S")
        time.sleep(15)

if "started" not in st.session_state:
    st.session_state.started = True
    state["rows"] = scan()
    threading.Thread(target=loop, daemon=True).start()

st.title("Trading Dashboard")

st.write("Status:", state["status"])
st.write("Last Update:", state["last_update"])

st.dataframe(pd.DataFrame(state["rows"]))

if state["errors"]:
    st.write("Errors:", state["errors"])
