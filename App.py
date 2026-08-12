from datetime import datetime
import os
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# Page Setup
st.set_page_config(
    page_title="Live 3-Candle Pullback & P&L Engine", layout="wide"
)

# Custom Styling
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    h1 { font-size: 20px !important; margin-bottom: 5px !important; }
    p, div, span, label { font-size: 13px !important; }
    .status-card { background-color: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155; }
    </style>
""",
    unsafe_allow_html=True,
)

LOG_FILE = "trades_log.csv"


# Ensure CSV Persistence across refreshes
def init_log_file():
    if not os.path.exists(LOG_FILE):
        df = pd.DataFrame(columns=[
            "Date",
            "Stock",
            "Symbol",
            "Signal",
            "Entry_Price",
            "SL",
            "Target",
            "Status",
            "Exit_Price",
            "Points_PL",
        ])
        df.to_csv(LOG_FILE, index=False)


def load_trade_logs():
    init_log_file()
    try:
        return pd.read_csv(LOG_FILE)
    except Exception:
        return pd.DataFrame()


def save_trade_logs(df):
    df.to_csv(LOG_FILE, index=False)


# F&O Universe
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
    """Fetches real live 5-minute candles."""
    try:
        stock = yf.Ticker(ticker_symbol)
        df = stock.history(period="5d", interval="5m")
        if df.empty:
            return None

        ist = ZoneInfo("Asia/Kolkata")
        df.index = df.index.tz_convert(ist)

        today_date = datetime.now(ist).date()
        df_today = df[df.index.date == today_date].copy()

        if len(df_today) < 4:
            last_available_date = df.index.date[-1]
            df_today = df[df.index.date == last_available_date].copy()

        return df_today
    except Exception:
        return None


def analyze_pullback_strategy(df):
    """Opening Range 3-Candle Pullback & Low Volume Strategy Engine."""
    if df is None or len(df) < 4:
        return None

    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

    # Opening 3 candles colors
    c1_green = closes[0] > opens[0]
    c2_green = closes[1] > opens[1]
    c3_green = closes[2] > opens[2]

    c1_red = closes[0] < opens[0]
    c2_red = closes[1] < opens[1]
    c3_red = closes[2] < opens[2]

    initial_3_avg_vol = np.mean(volumes[:3])

    # Check for pullback in subsequent candles
    for i in range(3, len(df)):
        curr_open, curr_close = opens[i], closes[i]
        curr_high, curr_low, curr_vol = highs[i], lows[i], volumes[i]

        # BUY SETUP LOGIC
        if c1_green and c2_green and c3_green:
            if curr_close < curr_open and curr_vol < initial_3_avg_vol:
                entry = curr_high
                sl = curr_low
                risk = entry - sl
                target = entry + (risk * 2)  # 1:2 R:R
                return {
                    "signal": "BUY",
                    "entry": round(entry, 2),
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

        # SELL SETUP LOGIC
        if c1_red and c2_red and c3_red:
            if curr_close > curr_open and curr_vol < initial_3_avg_vol:
                entry = curr_low
                sl = curr_high
                risk = sl - entry
                target = entry - (risk * 2)  # 1:2 R:R
                return {
                    "signal": "SELL",
                    "entry": round(entry, 2),
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

    return None


# --- APP INTERFACE ---
st.title("🎯 Real-Time 3-Candle Pullback Engine & Daily P&L Log")
ist = ZoneInfo("Asia/Kolkata")
today_str = datetime.now(ist).strftime("%Y-%m-%d")

st.markdown(
    f"""
    <div class="status-card">
        <b>Live Engine Status:</b> Running | <b>Date:</b> {today_str} | <b>Time (IST):</b> {datetime.now(ist).strftime('%H:%M:%S')}
    </div>
""",
    unsafe_allow_html=True,
)

# Persistent Session State
if "live_signals" not in st.session_state:
    st.session_state["live_signals"] = []

# Scan Button Execution
if st.button("🔄 Scan Market & Update Live Signals", type="primary"):
    with st.spinner("Scanning 5-min live candles & tracking P&L..."):
        trade_logs = load_trade_logs()
        current_signals = []

        for name, symbol in STOCKS_DICT.items():
            df = fetch_live_5min_data(symbol)
            if df is None or df.empty:
                continue

            latest_price = round(df["Close"].iloc[-1], 2)
            day_high = round(df["High"].max(), 2)
            day_low = round(df["Low"].min(), 2)

            signal_data = analyze_pullback_strategy(df)

            if signal_data:
                sig_type = signal_data["signal"]
                entry = signal_data["entry"]
                sl = signal_data["sl"]
                target = signal_data["target"]

                # Determine Signal Status
                status = "SETUP FORMED"
                points_pl = 0.0

                if sig_type == "BUY":
                    if day_high >= target:
                        status = "TARGET HIT 🎯"
                        points_pl = round(target - entry, 2)
                    elif day_low <= sl:
                        status = "SL HIT 🛑"
                        points_pl = round(sl - entry, 2)
                    elif latest_price >= entry:
                        status = "ACTIVE BUY 🟢"
                        points_pl = round(latest_price - entry, 2)

                elif sig_type == "SELL":
                    if day_low <= target:
                        status = "TARGET HIT 🎯"
                        points_pl = round(entry - target, 2)
                    elif day_high >= sl:
                        status = "SL HIT 🛑"
                        points_pl = round(entry - sl, 2)
                    elif latest_price <= entry:
                        status = "ACTIVE SELL 🔴"
                        points_pl = round(entry - latest_price, 2)

                signal_record = {
                    "Date": today_str,
                    "Stock": name,
                    "Signal": sig_type,
                    "LTP": latest_price,
                    "Entry Trigger": entry,
                    "Stop Loss (SL)": sl,
                    "Target (Exit)": target,
                    "Status": status,
                    "Live P&L (Pts)": points_pl,
                }
                current_signals.append(signal_record)

                # Save to CSV log if not present
                existing_logged = False
                if not trade_logs.empty and "Stock" in trade_logs.columns:
                    existing_logged = name in trade_logs["Stock"].values

                if not existing_logged:
                    new_row = pd.DataFrame([{
                        "Date": today_str,
                        "Stock": name,
                        "Symbol": symbol,
                        "Signal": sig_type,
                        "Entry_Price": entry,
                        "SL": sl,
                        "Target": target,
                        "Status": status,
                        "Exit_Price": latest_price,
                        "Points_PL": points_pl,
                    }])
                    trade_logs = pd.concat(
                        [trade_logs, new_row], ignore_index=True
                    )
                    save_trade_logs(trade_logs)

        st.session_state["live_signals"] = current_signals

# --- DISPLAY DASHBOARD ---
signals_to_display = st.session_state["live_signals"]

# Top Metrics Summary
st.subheader("📊 Today's Real-Time Performance Summary")
col1, col2, col3, col4 = st.columns(4)

total_count = len(signals_to_display)
wins = sum(
    1 for item in signals_to_display if "TARGET HIT" in item["Status"]
)
losses = sum(1 for item in signals_to_display if "SL HIT" in item["Status"])
net_pl = sum(item["Live P&L (Pts)"] for item in signals_to_display)

col1.metric("Total Signals Generated", total_count)
col2.metric("Targets Hit (Wins)", wins)
col3.metric("SL Hit (Losses)", losses)
col4.metric("Total Net P&L (Points)", f"{net_pl:+.2f}")

st.divider()

# Live Signals Log Table
st.subheader("📋 Subah Se Mile Saare Signals & Live Status")
if signals_to_display:
    df_display = pd.DataFrame(signals_to_display)
    st.dataframe(df_display, use_container_width=True)
else:
    st.info(
        "Filhal koi signal screen par nahi hai. 'Scan Market' button par click karke refresh karein."
    )
