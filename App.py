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

# Auto-refresh every 10 seconds
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


def scan_full_day_signals():
    all_signals = []

    for symbol in WATCHLIST:
        try:
            ticker = yf.Ticker(symbol)
            # Fetch today's 5m data
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 4:
                continue

            opens = df["Open"].values
            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            volumes = df["Volume"].values
            timestamps = df.index

            # Subah 9:15 se lekar abhi tak ki har candle check karo
            for i in range(3, len(df)):
                # 3-Candle Check
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

                # Time string for display
                signal_time = timestamps[i].strftime("%H:%M")

                # BUY Strategy
                if (
                    c1_green
                    and c2_green
                    and c3_green
                    and curr_close < curr_open
                    and curr_vol < avg_vol_3
                ):
                    entry = round(curr_high, 2)
                    sl = round(curr_low * 0.997, 2)
                    risk = entry - sl
                    target = round(entry + (risk * 2), 2)

                    all_signals.append(
                        {
                            "Time": signal_time,
                            "Symbol": symbol.replace(".NS", ""),
                            "Type": "BUY",
                            "Entry Trigger": entry,
                            "Stop Loss (SL)": sl,
                            "Target (Exit)": target,
                        }
                    )

                # SELL Strategy
                elif (
                    c1_red
                    and c2_red
                    and c3_red
                    and curr_close > curr_open
                    and curr_vol < avg_vol_3
                ):
                    entry = round(curr_low, 2)
                    sl = round(curr_high * 1.003, 2)
                    risk = sl - entry
                    target = round(entry - (risk * 2), 2)

                    all_signals.append(
                        {
                            "Time": signal_time,
                            "Symbol": symbol.replace(".NS", ""),
                            "Type": "SELL",
                            "Entry Trigger": entry,
                            "Stop Loss (SL)": sl,
                            "Target (Exit)": target,
                        }
                    )

        except Exception:
            continue

    return pd.DataFrame(all_signals)


df_signals = scan_full_day_signals()

# Banner Section
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
            [
                "Time",
                "Symbol",
                "Type",
                "Entry Trigger",
                "Stop Loss (SL)",
                "Target (Exit)",
            ]
        ],
        width="stretch",
    )
else:
    st.info(
        "Subah 9:15 se lekar abhi tak koi pullback setup complete nahi hua hai."
    )
