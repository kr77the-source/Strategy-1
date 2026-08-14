from datetime import datetime, time
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
from zoneinfo import ZoneInfo

# -----------------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="20 EMA + VWAP Auto Square-Off Dashboard", layout="wide"
)

# -----------------------------------------------------------------------------
# CUSTOM CSS
# -----------------------------------------------------------------------------
st.markdown("""
    <style>
    .block-container {
        padding-top: 3.5rem !important;
        padding-bottom: 0rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }
    h3 {
        font-size: 1.1rem !important;
        margin-top: 0rem !important;
        margin-bottom: 0.5rem !important;
        padding: 0px !important;
    }
    .status-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 6px 10px;
        color: #ffffff;
        font-size: 12px;
        margin-bottom: 5px;
    }
    .pnl-card {
        background-color: #1e2530;
        border: 1px solid #2e3846;
        border-radius: 6px;
        padding: 6px 10px;
        color: #ffffff;
        font-size: 12px;
        margin-bottom: 8px;
    }
    hr {
        margin-top: 0.3rem !important;
        margin-bottom: 0.3rem !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("### 🎯 20 EMA + VWAP Dashboard (3:20 PM Auto Square-Off)")

# -----------------------------------------------------------------------------
# WATCHLIST & CONFIG
# -----------------------------------------------------------------------------
NIFTY_50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "LTIM.NS",
    "KOTAKBANK.NS", "LT.NS", "AXISBANK.NS", "HCLTECH.NS", "ASIANPAINT.NS",
    "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "BAJFINANCE.NS", "TATAMOTORS.NS",
    "ULTRACEMCO.NS", "NTPC.NS", "ONGC.NS", "POWERGRID.NS", "TATASTEEL.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS", "BAJAJFINSV.NS", "M&M.NS",
    "GRASIM.NS", "HEROMOTOCO.NS", "EICHERMOT.NS", "BPCL.NS", "DIVISLAB.NS",
    "CIPLA.NS", "DRREDDY.NS", "APOLLOHOSP.NS", "TATACONSUM.NS", "BRITANNIA.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "INDUSINDBK.NS", "TECHM.NS",
    "HINDALCO.NS", "JSWSTEEL.NS", "BEL.NS", "TRENT.NS", "SHRIRAMFIN.NS"
]

TOTAL_CAPITAL = 50000.0
MAX_ACTIVE_TRADES = 4
CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES

def is_market_open(now_time):
    start_time = time(9, 15)
    end_time = time(15, 30)
    return start_time <= now_time.time() <= end_time

def calculate_vwap(df):
    v = df['Volume'].values
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * v).cumsum() / v.cumsum()

# -----------------------------------------------------------------------------
# FULL DAY SCANNER WITH AUTO SQUARE-OFF AT 3:20 PM
# -----------------------------------------------------------------------------
def scan_full_day_market():
    all_signals = []

    for symbol in NIFTY_50:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 20:
                continue

            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)

            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            ema20 = df["EMA20"].values
            vwap = df["VWAP"].values
            timestamps = df.index
            cmp_price = round(float(closes[-1]), 2)

            # Subah 09:15 ki candles ke baad scanning start
            for i in range(20, len(df)):
                candle_time_str = timestamps[i].strftime("%H:%M")
                
                # 3:20 PM ke baad koi NAYI trade trigger nahi hogi
                if candle_time_str >= "15:20":
                    break

                curr_close = closes[i]
                curr_high = highs[i]
                curr_low = lows[i]
                curr_ema = ema20[i]
                curr_vwap = vwap[i]

                bullish_trend = curr_ema > curr_vwap
                long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                bearish_trend = curr_ema < curr_vwap
                short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if long_pullback or short_pullback:
                    trade_type = "BUY 🟢" if long_pullback else "SELL 🔴"
                    entry = round(float(curr_close), 2)
                    qty = max(1, int(CAPITAL_PER_STOCK / entry))

                    # Target (+42 pts), SL (-14 pts)
                    if long_pullback:
                        sl = round(entry - 14.0, 2)
                        target = round(entry + 42.0, 2)
                    else:
                        sl = round(entry + 14.0, 2)
                        target = round(entry - 42.0, 2)

                    status = "LIVE 🟡"
                    pnl = round((cmp_price - entry) * qty, 2) if long_pullback else round((entry - cmp_price) * qty, 2)

                    # Signal ke baad wali candles par checking (Exit Logic)
                    for j in range(i + 1, len(df)):
                        check_time_str = timestamps[j].strftime("%H:%M")

                        # 1. Target Hit Check
                        if long_pullback and highs[j] >= target:
                            status = "TARGET 🟢"
                            pnl = round(42.0 * qty, 2)
                            break
                        elif not long_pullback and lows[j] <= target:
                            status = "TARGET 🟢"
                            pnl = round(42.0 * qty, 2)
                            break

                        # 2. SL Hit Check
                        if long_pullback and lows[j] <= sl:
                            status = "SL HIT 🔴"
                            pnl = round(-14.0 * qty, 2)
                            break
                        elif not long_pullback and highs[j] >= sl:
                            status = "SL HIT 🔴"
                            pnl = round(-14.0 * qty, 2)
                            break

                        # 3. 3:20 PM Auto Square-Off Check
                        if check_time_str >= "15:20":
                            status = "AUTO SQ OFF ⚪"
                            exit_p = round(float(closes[j]), 2)
                            pnl = round((exit_p - entry) * qty, 2) if long_pullback else round((entry - exit_p) * qty, 2)
                            break

                    all_signals.append({
                        "Time": candle_time_str,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": trade_type,
                        "Qty": qty,
                        "Entry Price": entry,
                        "Stop Loss (SL)": sl,
                        "Target": target,
                        "CMP": cmp_price,
                        "Status": status,
                        "P&L (₹)": pnl
                    })

                    # Unique signal per stock
                    break

        except Exception:
            continue

    return pd.DataFrame(all_signals)

# -----------------------------------------------------------------------------
# DISPLAY DASHBOARD
# -----------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_date = now_ist.strftime("%Y-%m-%d")
    current_time = now_ist.strftime("%H:%M:%S")

    market_active = is_market_open(now_ist)
    status_text = "🟢 SCANNING LIVE MARKET" if market_active else "🔴 MARKET CLOSED (AUTO SQ OFF DONE)"

    df_signals = scan_full_day_market()

    if not df_signals.empty:
        total_trades = len(df_signals)
        live_trades = len(df_signals[df_signals["Status"] == "LIVE 🟡"])
        targets_hit = len(df_signals[df_signals["Status"] == "TARGET 🟢"])
        sl_hit = len(df_signals[df_signals["Status"] == "SL HIT 🔴"])
        auto_sq_off = len(df_signals[df_signals["Status"] == "AUTO SQ OFF ⚪"])
        overall_pnl = round(df_signals["P&L (₹)"].sum(), 2)
    else:
        total_trades = 0
        live_trades = 0
        targets_hit = 0
        sl_hit = 0
        auto_sq_off = 0
        overall_pnl = 0.0

    pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {current_date} | <b>Time:</b> {current_time}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            📊 <b>Cap:</b> ₹50k | <b>Active LIVE:</b> {live_trades} | <b>Total Trades Today:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>SQ-OFF (3:20):</b> {auto_sq_off} | <b>P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">₹{overall_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Today's Trades Log (09:15 AM - 03:20 PM)")

    if not df_signals.empty:
        st.dataframe(
            df_signals[
                [
                    "Time",
                    "Symbol",
                    "Type",
                    "Qty",
                    "Entry Price",
                    "Stop Loss (SL)",
                    "Target",
                    "CMP",
                    "Status",
                    "P&L (₹)"
                ]
            ],
            use_container_width=True,
        )
    else:
        st.info("Aaj koi valid setup nahi bana hai.")

render_dashboard()
