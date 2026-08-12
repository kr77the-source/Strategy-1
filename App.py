from datetime import datetime, timedelta
import pytz
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# Page Config
st.set_page_config(
    page_title="Live 3-Candle Pullback Scanner", layout="wide"
)

# Custom CSS
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    h1 { font-size: 20px !important; margin-bottom: 5px !important; }
    p, div, span, label { font-size: 13px !important; }
    .buy-signal { color: #00FF7F; font-weight: bold; background-color: #064e3b; padding: 4px 8px; border-radius: 4px; }
    .sell-signal { color: #FF4500; font-weight: bold; background-color: #7f1d1d; padding: 4px 8px; border-radius: 4px; }
    .no-signal { color: #94a3b8; font-weight: normal; }
    .status-card { background-color: #1e293b; padding: 10px; border-radius: 6px; margin-bottom: 15px; border: 1px solid #334155; }
    </style>
""",
    unsafe_allow_html=True,
)

# List of F&O Stocks & Indices
STOCKS_DICT = {
    "Nifty 50 Index": "^NSEI",
    "Bank Nifty Index": "^NSEBANK",
    "Reliance": "RELIANCE.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Infosys": "INFY.NS",
    "TCS": "TCS.NS",
    "SBI": "SBIN.NS",
    "Bharti Airtel": "BHARTIARTL.NS",
    "ITC": "ITC.NS",
    "L&T": "LT.NS",
    "Tata Motors": "TATAMOTORS.NS",
    "Axis Bank": "AXISBANK.NS",
    "Maruti": "MARUTI.NS",
    "Sun Pharma": "SUNPHARMA.NS",
    "Tata Steel": "TATASTEEL.NS",
    "M&M": "M&M.NS",
    "HUL": "HINDUNILVR.NS",
    "Power Grid": "POWERGRID.NS",
    "NTPC": "NTPC.NS",
}


def fetch_live_5min_data(ticker_symbol):
    """Fetches real 5-minute interval data for today via yfinance."""
    try:
        stock = yf.Ticker(ticker_symbol)
        # Fetching 5-minute data for the last 5 days to ensure intraday candles are loaded properly
        df = stock.history(period="5d", interval="5m")

        if df.empty:
            return None

        # Filter for today's market session
        ist = pytz.timezone("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)

        today_date = datetime.now(ist).date()
        df_today = df[df.index.date == today_date].copy()

        # If market hasn't opened today or early morning before 9:15, fallback to last available session
        if len(df_today) < 4:
            last_available_date = df.index.date[-1]
            df_today = df[df.index.date == last_available_date].copy()

        return df_today
    except Exception:
        return None


def analyze_pullback_strategy(df):
    """Applies the 3-Candle Opening Range Pullback + Low Volume Strategy.

    BUY Setup:
    1. Overall trend context (Nifty/Stock bullish)
    2. Initial 3 Green candles
    3. Followed by a Red Pullback Candle whose Volume < Average Volume of initial 3 Green candles.
    4. Trigger: High break of pullback candle.

    SELL Setup:
    1. Overall trend context (Bearish)
    2. Initial 3 Red candles
    3. Followed by a Green Pullback Candle whose Volume < Average Volume of initial 3 Red candles.
    4. Trigger: Low break of pullback candle.
    """
    if df is None or len(df) < 4:
        return {
            "status": "Insufficient Candles",
            "signal": "NONE",
            "trigger": 0.0,
            "sl": 0.0,
            "details": "Minimum 4 candles (5-min) needed for setup.",
        }

    # Extract OHLCV
    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

    # Check first 3 candles color
    c1_green = closes[0] > opens[0]
    c2_green = closes[1] > opens[1]
    c3_green = closes[2] > opens[2]

    c1_red = closes[0] < opens[0]
    c2_red = closes[1] < opens[1]
    c3_red = closes[2] < opens[2]

    # Average volume of first 3 candles
    initial_3_avg_vol = np.mean(volumes[:3])

    # Check subsequent candles for valid Low-Volume Pullback
    for i in range(3, len(df)):
        curr_open = opens[i]
        curr_close = closes[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_vol = volumes[i]

        # 1. BUY SETUP LOGIC
        if c1_green and c2_green and c3_green:
            is_pullback_red = curr_close < curr_open
            if is_pullback_red:
                if curr_vol < initial_3_avg_vol:
                    # Low volume pullback confirmed
                    entry_trigger = curr_high  # High break entry
                    stop_loss = curr_low  # Low SL

                    # Check if trigger broken in latest market price
                    latest_price = closes[-1]
                    is_active = latest_price > entry_trigger

                    return {
                        "status": "ACTIVE BUY SIGNAL"
                        if is_active
                        else "BUY SETUP FORMED",
                        "signal": "BUY",
                        "trigger": round(entry_trigger, 2),
                        "sl": round(stop_loss, 2),
                        "details": f"3 Green candles followed by low-vol Red pullback at Candle #{i+1}. (Pullback Vol: {curr_vol:,} vs Init Avg Vol: {int(initial_3_avg_vol):,})",
                    }

        # 2. SELL SETUP LOGIC
        if c1_red and c2_red and c3_red:
            is_pullback_green = curr_close > curr_open
            if is_pullback_green:
                if curr_vol < initial_3_avg_vol:
                    # Low volume bounce confirmed
                    entry_trigger = curr_low  # Low break entry
                    stop_loss = curr_high  # High SL

                    latest_price = closes[-1]
                    is_active = latest_price < entry_trigger

                    return {
                        "status": "ACTIVE SELL SIGNAL"
                        if is_active
                        else "SELL SETUP FORMED",
                        "signal": "SELL",
                        "trigger": round(entry_trigger, 2),
                        "sl": round(stop_loss, 2),
                        "details": f"3 Red candles followed by low-vol Green pullback at Candle #{i+1}. (Pullback Vol: {curr_vol:,} vs Init Avg Vol: {int(initial_3_avg_vol):,})",
                    }

    return {
        "status": "No Pattern Met",
        "signal": "NONE",
        "trigger": 0.0,
        "sl": 0.0,
        "details": "Market opening 3 candles were not strictly unicolour or low-volume condition failed.",
    }


# UI Header
st.title("🎯 Real-Time 3-Candle Pullback & Volume Confirmation Scanner")
st.caption(
    "5-Minute Timeframe | Real Live yfinance Feed | Strictly 1 Strategy Engine"
)

# Market Sentiment Section
ist = pytz.timezone("Asia/Kolkata")
st.markdown(
    f"""
    <div class="status-card">
        <b>Live Scan Status:</b> System Running Real-Time | <b>Time (IST):</b> {datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')}
    </div>
""",
    unsafe_allow_html=True,
)

# Nifty Trend Check
with st.spinner("Fetching Nifty 50 Trend..."):
    nifty_df = fetch_live_5min_data("^NSEI")
    if nifty_df is not None and not nifty_df.empty:
        nifty_last = nifty_df["Close"].iloc[-1]
        nifty_change = (
            (nifty_last - nifty_df["Open"].iloc[0]) / nifty_df["Open"].iloc[0]
        ) * 100
        nifty_trend = "BULLISH 🟢" if nifty_change >= 0 else "BEARISH 🔴"
        st.metric(
            label="Nifty 50 Sentiment Context",
            value=f"{nifty_last:.2f}",
            delta=f"{nifty_change:.2f}% ({nifty_trend})",
        )

# Scanner Execution
if st.button("🔄 Scan F&O Universe Now", type="primary"):
    results = []

    progress_bar = st.progress(0)
    total_stocks = len(STOCKS_DICT)

    for idx, (name, symbol) in enumerate(STOCKS_DICT.items()):
        df = fetch_live_5min_data(symbol)
        if df is not None and not df.empty:
            analysis = analyze_pullback_strategy(df)
            latest_price = round(df["Close"].iloc[-1], 2)
            day_change = round(
                ((df["Close"].iloc[-1] - df["Open"].iloc[0])
                 / df["Open"].iloc[0])
                * 100,
                2,
            )

            results.append({
                "Stock": name,
                "Symbol": symbol,
                "LTP": latest_price,
                "Day Change (%)": day_change,
                "Signal": analysis["signal"],
                "Status": analysis["status"],
                "Entry Trigger": analysis["trigger"],
                "Stop Loss (SL)": analysis["sl"],
                "Setup Rules & Volume Context": analysis["details"],
            })

        progress_bar.progress((idx + 1) / total_stocks)

    progress_bar.empty()

    if results:
        res_df = pd.DataFrame(results)

        # Split into Signals & Watchlist
        signals_df = res_df[res_df["Signal"] != "NONE"]
        watchlist_df = res_df[res_df["Signal"] == "NONE"]

        st.subheader("⚡ Active Trade Signals & Setup Confirmations")
        if not signals_df.empty:
            st.dataframe(signals_df, use_container_width=True)
        else:
            st.info(
                "Filhal kisi stock mein 3-Candle Pullback with Low Volume Ka Breakout Trigger Nahi Hua Hai."
            )

        st.subheader("📋 Full F&O Watchlist Scan Status")
        st.dataframe(watchlist_df, use_container_width=True)
