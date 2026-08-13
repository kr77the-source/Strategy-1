from datetime import datetime
import os
from zoneinfo import ZoneInfo
from growwapi import GrowwAPI
import numpy as np
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Streamlit Page Setup
st.set_page_config(
    page_title="Groww Live 3-Candle Pullback Engine", layout="wide"
)

# API Setup
API_KEY = "YOUR_API_KEY"
SECRET = "YOUR_SECRET"

CAPITAL_PER_TRADE = 50000.0  # ₹50,000 Fixed Capital Budget
TIMEFRAME = 5  # 5 Minute Candles

STOCKS_DICT = {
    "Reliance": "RELIANCE",
    "HDFC Bank": "HDFCBANK",
    "ICICI Bank": "ICICIBANK",
    "Infosys": "INFY",
    "TCS": "TCS",
    "SBI": "SBIN",
    "Bharti Airtel": "BHARTIARTL",
    "Tata Motors": "TATAMOTORS",
}


@st.cache_resource
def get_groww_client():
    try:
        token = GrowwAPI.get_access_token(api_key=API_KEY, secret=SECRET)
        return GrowwAPI(token)
    except Exception as e:
        st.error(f"Groww Connection Error: {e}")
        return None


groww = get_groww_client()


def fetch_groww_data(symbol):
    if not groww:
        return None
    try:
        end_time = datetime.now()
        start_time = end_time - pd.Timedelta(days=2)
        raw_data = groww.get_historical_candle_data(
            trading_symbol=symbol,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_CASH,
            start_time=start_time.strftime("%Y-%m-%d %H:%M:%S"),
            end_time=end_time.strftime("%Y-%m-%d %H:%M:%S"),
            interval_in_minutes=TIMEFRAME,
        )
        candles = (
            raw_data.get("candles", [])
            if isinstance(raw_data, dict)
            else raw_data
        )

        df_data = []
        for c in candles:
            if isinstance(c, list) and len(c) >= 6:
                df_data.append(
                    {
                        "Open": float(c[1]),
                        "High": float(c[2]),
                        "Low": float(c[3]),
                        "Close": float(c[4]),
                        "Volume": float(c[5]),
                    }
                )
        return pd.DataFrame(df_data) if df_data else None
    except Exception:
        return None


def analyze_pullback_strategy(df):
    if df is None or len(df) < 4:
        return None

    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

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

    if (
        c1_green
        and c2_green
        and c3_green
        and curr_close < curr_open
        and curr_vol < initial_3_avg_vol
    ):
        entry = curr_high
        sl = curr_low * 0.997
        risk = entry - sl
        target = entry + (risk * 2)
        qty = max(1, int(CAPITAL_PER_TRADE // entry))
        return {
            "signal": "BUY",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),
            "qty": qty,
        }

    if (
        c1_red
        and c2_red
        and c3_red
        and curr_close > curr_open
        and curr_vol < initial_3_avg_vol
    ):
        entry = curr_low
        sl = curr_high * 1.003
        risk = sl - entry
        target = entry - (risk * 2)
        qty = max(1, int(CAPITAL_PER_TRADE // entry))
        return {
            "signal": "SELL",
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "target": round(target, 2),
            "qty": qty,
        }

    return None


# Streamlit App UI
st.title("🎯 Groww Live Auto-Scanner Engine")
auto_scan = st.sidebar.checkbox("Enable Live Scan", value=True)
if auto_scan:
    st_autorefresh(interval=10000, key="groww_scanner_refresh")

ist = ZoneInfo("Asia/Kolkata")
st.write(
    f"**Live Engine Status:** 🟢 ACTIVE | **Time:** {datetime.now(ist).strftime('%H:%M:%S')}"
)

results = []
for name, symbol in STOCKS_DICT.items():
    df = fetch_groww_data(symbol)
    if df is not None:
        signal = analyze_pullback_strategy(df)
        if signal:
            results.append(
                {
                    "Stock": name,
                    "Signal": signal["signal"],
                    "Entry": signal["entry"],
                    "SL": signal["sl"],
                    "Target": signal["target"],
                    "Qty": signal["qty"],
                }
            )

if results:
    st.dataframe(pd.DataFrame(results), use_container_width=True)
else:
    st.info("Scanning Market... Currently no active 3-candle pullback setups.")
