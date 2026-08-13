from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="Live Auto-Scanning Engine & Performance Tracker", layout="wide"
)

st_autorefresh(interval=10000, key="datarefresh")

st.markdown("### 🎯 Live Auto-Scanning Engine & Performance Tracker")

now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
current_date = now_ist.strftime("%Y-%m-%d")
current_time = now_ist.strftime("%H:%M:%S")

WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "TATAMOTORS.NS",
]


def analyze_code2_pullback(df):
    if df is None or len(df) < 4:
        return None

    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

    # Code 2 Logic: Check 3 candles direction
    c1_green, c2_green, c3_green = (
        closes[-4] > opens[-4],
        closes[-3] > opens[-3],
        closes[-2] > opens[-2],
    )
    c1_red, c2_red, c3_red = (
        closes[-4] < opens[-4],
        closes[-3] < opens[-3],
        closes[-2] < opens[-2],
    )

    initial_3_avg_vol = np.mean(volumes[-4:-1])
    curr_open, curr_close, curr_high, curr_low, curr_vol = (
        opens[-1],
        closes[-1],
        highs[-1],
        lows[-1],
        volumes[-1],
    )

    # BUY SET-UP (3 Green + 1 Red Pullback with Low Volume)
    if (
        c1_green
        and c2_green
        and c3_green
        and curr_close < curr_open
        and curr_vol < initial_3_avg_vol
    ):
        entry = curr_high
        sl = curr_low * 0.997  # 0.3% Buffer below Low
        risk = entry - sl
        target = entry + (risk * 2)  # 1:2 Target
        return {
            "Type": "BUY",
            "Entry": round(entry, 2),
            "SL": round(sl, 2),
            "Target": round(target, 2),
        }

    # SELL SET-UP (3 Red + 1 Green Pullback with Low Volume)
    if (
        c1_red
        and c2_red
        and c3_red
        and curr_close > curr_open
        and curr_vol < initial_3_avg_vol
    ):
        entry = curr_low
        sl = curr_high * 1.003  # 0.3% Buffer above High
        risk = sl - entry
        target = entry - (risk * 2)  # 1:2 Target
        return {
            "Type": "SELL",
            "Entry": round(entry, 2),
            "SL": round(sl, 2),
            "Target": round(target, 2),
        }

    return None


signals = []
for symbol in WATCHLIST:
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="5d", interval="5m")
        if not df.empty:
            res = analyze_code2_pullback(df)
            if res:
                signals.append(
                    {
                        "Symbol": symbol.replace(".NS", ""),
                        "Entry Trigger": res["Entry"],
                        "Stop Loss (SL)": res["SL"],
                        "Target (Exit)": res["Target"],
                    }
                )
    except Exception:
        continue

df_signals = pd.DataFrame(signals)

st.write(
    f"**Live Engine Status:** 🟢 AUTO SCANNING LIVE | **Date:** {current_date} | **Last Updated (IST):** {current_time}"
)
st.write(
    f"📊 **Trades:** {len(df_signals)} | **Targets:** 0 | **SL:** 0 | **Overall P&L:** 0.0 Pts"
)

st.markdown("---")
st.markdown("### 📋 Subah Se Mile Saare Signals & Live Status")

if not df_signals.empty:
    st.dataframe(
        df_signals[
            ["Symbol", "Entry Trigger", "Stop Loss (SL)", "Target (Exit)"]
        ],
        width="stretch",
    )
else:
    st.info("Scanning Market... Currently no active 3-candle pullback setups.")
