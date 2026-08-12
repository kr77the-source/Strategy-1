from datetime import datetime
import os
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

# Page Config
st.set_page_config(
    page_title="Live 3-Candle Pullback + P&L Tracker", layout="wide"
)

# Custom CSS
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1rem !important; }
    h1 { font-size: 20px !important; margin-bottom: 5px !important; }
    p, div, span, label { font-size: 13px !important; }
    .status-card { background-color: #1e293b; padding: 12px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155; }
    .metric-box { background-color: #0f172a; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid #1e293b; }
    </style>
""",
    unsafe_allow_html=True,
)

# File path for permanent logging across refreshes
LOG_FILE = "trades_log.csv"


def init_log_file():
    """Ensures CSV file exists for permanent storage."""
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
    """Loads saved trades from CSV."""
    init_log_file()
    try:
        return pd.read_csv(LOG_FILE)
    except Exception:
        return pd.DataFrame()


def save_trade_logs(df):
    """Saves updated trades back to CSV."""
    df.to_csv(LOG_FILE, index=False)


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
    """Fetches real live 5-minute interval data."""
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
    """3-Candle Opening Range Pullback + Low Volume Strategy."""
    if df is None or len(df) < 4:
        return None

    opens = df["Open"].values
    closes = df["Close"].values
    highs = df["High"].values
    lows = df["Low"].values
    volumes = df["Volume"].values

    c1_green = closes[0] > opens[0]
    c2_green = closes[1] > opens[1]
    c3_green = closes[2] > opens[2]

    c1_red = closes[0] < opens[0]
    c2_red = closes[1] < opens[1]
    c3_red = closes[2] < opens[2]

    initial_3_avg_vol = np.mean(volumes[:3])

    for i in range(3, len(df)):
        curr_open, curr_close = opens[i], closes[i]
        curr_high, curr_low, curr_vol = highs[i], lows[i], volumes[i]

        # BUY SETUP
        if c1_green and c2_green and c3_green:
            if curr_close < curr_open and curr_vol < initial_3_avg_vol:
                entry = curr_high
                sl = curr_low
                target = entry + ((entry - sl) * 2)  # 1:2 Risk-Reward
                return {
                    "signal": "BUY",
                    "entry": round(entry, 2),
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

        # SELL SETUP
        if c1_red and c2_red and c3_red:
            if curr_close > curr_open and curr_vol < initial_3_avg_vol:
                entry = curr_low
                sl = curr_high
                target = entry - ((sl - entry) * 2)  # 1:2 Risk-Reward
                return {
                    "signal": "SELL",
                    "entry": round(entry, 2),
                    "sl": round(sl, 2),
                    "target": round(target, 2),
                }

    return None


# --- UI DASHBOARD ---
st.title("📊 Real-Time Strategy Scanner & Live P&L Tracker")
ist = ZoneInfo("Asia/Kolkata")
today_str = datetime.now(ist).strftime("%Y-%m-%d")

# Header Status
st.markdown(
    f"""
    <div class="status-card">
        <b>Live Engine Status:</b> Active | <b>Date:</b> {today_str} | <b>Time (IST):</b> {datetime.now(ist).strftime('%H:%M:%S')}
    </div>
""",
    unsafe_allow_html=True,
)

# Load existing saved trades
trade_logs = load_trade_logs()

# Filter logs for today
if not trade_logs.empty and "Date" in trade_logs.columns:
    today_logs = trade_logs[trade_logs["Date"] == today_str].copy()
else:
    today_logs = pd.DataFrame()

# Real-Time Scan Button
if st.button("🔄 Scan Market & Update Live P&L", type="primary"):
    with st.spinner("Scanning real-time candles & checking active trades..."):
        for name, symbol in STOCKS_DICT.items():
            df = fetch_live_5min_data(symbol)
            if df is None or df.empty:
                continue

            latest_price = df["Close"].iloc[-1]
            day_high = df["High"].max()
            day_low = df["Low"].min()

            # Check if stock is already logged today
            already_logged = False
            if not today_logs.empty:
                already_logged = name in today_logs["Stock"].values

            # 1. LOG NEW TRADES
            if not already_logged:
                signal_data = analyze_pullback_strategy(df)
                if signal_data:
                    # Check if entry trigger was hit
                    triggered = False
                    if (
                        signal_data["signal"] == "BUY"
                        and latest_price >= signal_data["entry"]
                    ):
                        triggered = True
                    elif (
                        signal_data["signal"] == "SELL"
                        and latest_price <= signal_data["entry"]
                    ):
                        triggered = True

                    if triggered:
                        new_row = pd.DataFrame([{
                            "Date": today_str,
                            "Stock": name,
                            "Symbol": symbol,
                            "Signal": signal_data["signal"],
                            "Entry_Price": signal_data["entry"],
                            "SL": signal_data["sl"],
                            "Target": signal_data["target"],
                            "Status": "OPEN",
                            "Exit_Price": 0.0,
                            "Points_PL": 0.0,
                        }])
                        trade_logs = pd.concat(
                            [trade_logs, new_row], ignore_index=True
                        )
                        save_trade_logs(trade_logs)

            # 2. UPDATE P&L FOR EXISTING OPEN TRADES
            if not trade_logs.empty:
                for idx, row in trade_logs.iterrows():
                    if row["Date"] == today_str and row["Status"] == "OPEN":
                        if row["Stock"] == name:
                            entry, sl, target, sig = (
                                row["Entry_Price"],
                                row["SL"],
                                row["Target"],
                                row["Signal"],
                            )

                            if sig == "BUY":
                                if day_high >= target:
                                    trade_logs.at[idx, "Status"] = "TARGET HIT"
                                    trade_logs.at[idx, "Exit_Price"] = target
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        target - entry, 2
                                    )
                                elif day_low <= sl:
                                    trade_logs.at[idx, "Status"] = "SL HIT"
                                    trade_logs.at[idx, "Exit_Price"] = sl
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        sl - entry, 2
                                    )
                                else:
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        latest_price - entry, 2
                                    )

                            elif sig == "SELL":
                                if day_low <= target:
                                    trade_logs.at[idx, "Status"] = "TARGET HIT"
                                    trade_logs.at[idx, "Exit_Price"] = target
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        entry - target, 2
                                    )
                                elif day_high >= sl:
                                    trade_logs.at[idx, "Status"] = "SL HIT"
                                    trade_logs.at[idx, "Exit_Price"] = sl
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        entry - sl, 2
                                    )
                                else:
                                    trade_logs.at[idx, "Points_PL"] = round(
                                        entry - latest_price, 2
                                    )

                save_trade_logs(trade_logs)

    # Reload fresh data
    trade_logs = load_trade_logs()
    if not trade_logs.empty and "Date" in trade_logs.columns:
        today_logs = trade_logs[trade_logs["Date"] == today_str].copy()

# --- TOP SUMMARY METRICS ---
st.subheader("📈 Today's Real-Time Performance Summary")
col1, col2, col3, col4 = st.columns(4)

total_trades = len(today_logs)
wins = (
    len(today_logs[today_logs["Status"] == "TARGET HIT"])
    if not today_logs.empty
    else 0
)
losses = (
    len(today_logs[today_logs["Status"] == "SL HIT"])
    if not today_logs.empty
    else 0
)
total_pl = today_logs["Points_PL"].sum() if not today_logs.empty else 0.0

col1.metric("Total Trades Today", total_trades)
col2.metric("Target Hit (Wins) 🎯", wins)
col3.metric("SL Hit (Losses) 🛑", losses)
col4.metric("Total Net P&L (Points)", f"{total_pl:+.2f}")

st.divider()

# --- DAILY TRADES LOG TABLE ---
st.subheader("📋 Today's Signal Log & Live P&L")
if not today_logs.empty:
    st.dataframe(
        today_logs[[
            "Stock",
            "Signal",
            "Entry_Price",
            "SL",
            "Target",
            "Status",
            "Exit_Price",
            "Points_PL",
        ]],
        use_container_width=True,
    )
else:
    st.info(
        "Aaj abhi tak kisi stock ne Entry trigger nahi kiya hai. 'Scan Market' button dabayein."
    )
