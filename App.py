from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG & CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Live Auto-Scanning Engine & Performance Tracker", layout="wide"
)

# Auto refresh every 10 seconds
st_autorefresh(interval=10000, key="datarefresh")

st.markdown("""
    <style>
    .status-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 8px;
        padding: 12px 16px;
        color: #ffffff;
        font-size: 15px;
        margin-bottom: 10px;
    }
    .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 8px;
        padding: 12px 16px;
        color: #ffffff;
        font-size: 15px;
        margin-bottom: 20px;
    }
    </style>
""", unsafe_allow_html=True)

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

# -----------------------------------------------------------------------------
# CORE SCANNING AND LIVE P&L LOGIC
# -----------------------------------------------------------------------------
def scan_and_track_pnl():
    all_signals = []

    for symbol in WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 4:
                continue

            opens = df["Open"].values
            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            volumes = df["Volume"].values
            timestamps = df.index

            # Live price for P&L tracking
            cmp = round(float(closes[-1]), 2)

            for i in range(3, len(df)):
                c1_green, c2_green, c3_green = (
                    closes[i - 3] > opens[i - 3],
                    closes[i - 2] > opens[i - 2],
                    closes[i - 1] > opens[i - 1],
                )
                c1_red, c2_red, c3_red = (
                    closes[i - 3] < opens[i - 3],
                    closes[i - 2] < opens[i - 2],
                    closes[i - 1] < opens[i - 1],
                )

                avg_vol_3 = np.mean(volumes[i - 3 : i])
                curr_open, curr_close, curr_high, curr_low, curr_vol = (
                    opens[i],
                    closes[i],
                    highs[i],
                    lows[i],
                    volumes[i],
                )
                signal_time = timestamps[i].strftime("%H:%M")

                # BUY Trade Setup
                if (
                    c1_green
                    and c2_green
                    and c3_green
                    and curr_close < curr_open
                    and curr_vol < avg_vol_3
                ):
                    entry = round(float(curr_high), 2)
                    sl = round(float(curr_low * 0.997), 2)
                    risk = entry - sl
                    target = round(entry + (risk * 2), 2)

                    # Track Live Status & P&L
                    if cmp >= target:
                        status = "TARGET 🟢"
                        pnl = round(target - entry, 2)
                    elif cmp <= sl:
                        status = "SL HIT 🔴"
                        pnl = round(sl - entry, 2)
                    else:
                        status = "LIVE 🟡"
                        pnl = round(cmp - entry, 2)

                    all_signals.append({
                        "Time": signal_time,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": "BUY",
                        "Entry Trigger": entry,
                        "Stop Loss (SL)": sl,
                        "Target (Exit)": target,
                        "CMP": cmp,
                        "Status": status,
                        "P&L Pts": pnl
                    })

                # SELL Trade Setup
                elif (
                    c1_red
                    and c2_red
                    and c3_red
                    and curr_close > curr_open
                    and curr_vol < avg_vol_3
                ):
                    entry = round(float(curr_low), 2)
                    sl = round(float(curr_high * 1.003), 2)
                    risk = sl - entry
                    target = round(entry - (risk * 2), 2)

                    # Track Live Status & P&L
                    if cmp <= target:
                        status = "TARGET 🟢"
                        pnl = round(entry - target, 2)
                    elif cmp >= sl:
                        status = "SL HIT 🔴"
                        pnl = round(entry - sl, 2)
                    else:
                        status = "LIVE 🟡"
                        pnl = round(entry - cmp, 2)

                    all_signals.append({
                        "Time": signal_time,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": "SELL",
                        "Entry Trigger": entry,
                        "Stop Loss (SL)": sl,
                        "Target (Exit)": target,
                        "CMP": cmp,
                        "Status": status,
                        "P&L Pts": pnl
                    })

        except Exception:
            continue

    return pd.DataFrame(all_signals)

# -----------------------------------------------------------------------------
# DISPLAY METRICS & TABLE
# -----------------------------------------------------------------------------
df_signals = scan_and_track_pnl()

if not df_signals.empty:
    total_trades = len(df_signals)
    targets_hit = len(df_signals[df_signals["Status"].str.contains("TARGET")])
    sl_hit = len(df_signals[df_signals["Status"].str.contains("SL HIT")])
    overall_pnl = round(df_signals["P&L Pts"].sum(), 2)
else:
    total_trades = 0
    targets_hit = 0
    sl_hit = 0
    overall_pnl = 0.0

pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"

# Top Cards
st.markdown(f"""
    <div class="status-card">
        <b>Live Engine Status:</b> 🟢 AUTO SCANNING LIVE | <b>Date:</b> {current_date} | <b>Last Updated (IST):</b> {current_time}
    </div>
""", unsafe_allow_html=True)

st.markdown(f"""
    <div class="pnl-card">
        📊 <b>Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>Overall P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">{overall_pnl} Pts</span>
    </div>
""", unsafe_allow_html=True)

st.markdown("---")
st.markdown("### 📋 Subah Se Mile Saare Signals & Live Status")

if not df_signals.empty:
    st.dataframe(
        df_signals[
            [
                "Time",
                "Symbol",
                "Type",
                "Entry Trigger",
                "Stop Loss (SL)",
                "Target (Exit)",
                "CMP",
                "Status",
                "P&L Pts"
            ]
        ],
        width="stretch",
    )
else:
    st.info("Subah 9:15 se abhi tak koi trade setup scan nahi hua hai.")
