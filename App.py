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
    page_title="Real-Time 20 EMA + VWAP Live Dashboard", layout="wide"
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

st.markdown("### 🎯 20 EMA + VWAP Pullback Real Live Dashboard")

# -----------------------------------------------------------------------------
# SESSION STATE (TRADES PERMANENT SAVE RAKHNE KE LIYE)
# -----------------------------------------------------------------------------
if "real_live_trades" not in st.session_state:
    st.session_state.real_live_trades = {}

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
# REAL-TIME LIVE SCANNER & TRACKER
# -----------------------------------------------------------------------------
def run_live_scanner():
    for symbol in NIFTY_50:
        try:
            clean_symbol = symbol.replace(".NS", "")
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 20:
                continue

            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)

            cmp_price = round(float(df["Close"].iloc[-1]), 2)

            # A. PEHLE SE SAVED LIVE TRADES KO UPDATE KARO (SL/TARGET CHECK)
            if clean_symbol in st.session_state.real_live_trades:
                trade = st.session_state.real_live_trades[clean_symbol]
                
                if trade["Status"] == "LIVE 🟡":
                    trade["CMP"] = cmp_price
                    if trade["Type"] == "BUY 🟢":
                        if cmp_price >= trade["Target"]:
                            trade["Status"] = "TARGET 🟢"
                            trade["P&L (₹)"] = round(42.0 * trade["Qty"], 2)
                        elif cmp_price <= trade["Stop Loss (SL)"]:
                            trade["Status"] = "SL HIT 🔴"
                            trade["P&L (₹)"] = round(-14.0 * trade["Qty"], 2)
                        else:
                            trade["P&L (₹)"] = round((cmp_price - trade["Entry Price"]) * trade["Qty"], 2)
                    else: # SELL Trade
                        if cmp_price <= trade["Target"]:
                            trade["Status"] = "TARGET 🟢"
                            trade["P&L (₹)"] = round(42.0 * trade["Qty"], 2)
                        elif cmp_price >= trade["Stop Loss (SL)"]:
                            trade["Status"] = "SL HIT 🔴"
                            trade["P&L (₹)"] = round(-14.0 * trade["Qty"], 2)
                        else:
                            trade["P&L (₹)"] = round((trade["Entry Price"] - cmp_price) * trade["Qty"], 2)
                continue

            # B. PURE LIVE SIGNAL DETECTION (Only check latest completed 5-min candle)
            idx = -2 if len(df) > 1 else -1
            curr_close = df["Close"].iloc[idx]
            curr_high = df["High"].iloc[idx]
            curr_low = df["Low"].iloc[idx]
            curr_ema = df["EMA20"].iloc[idx]
            curr_vwap = df["VWAP"].iloc[idx]
            signal_time = df.index[idx].strftime("%H:%M")

            bullish_trend = curr_ema > curr_vwap
            long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

            bearish_trend = curr_ema < curr_vwap
            short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

            if long_pullback or short_pullback:
                trade_type = "BUY 🟢" if long_pullback else "SELL 🔴"
                entry = round(float(curr_close), 2)
                qty = max(1, int(CAPITAL_PER_STOCK / entry))

                # Hardcoded Fixed Points: SL 14, Target 42
                if long_pullback:
                    sl = round(entry - 14.0, 2)
                    target = round(entry + 42.0, 2)
                    pnl = round((cmp_price - entry) * qty, 2)
                else:
                    sl = round(entry + 14.0, 2)
                    target = round(entry - 42.0, 2)
                    pnl = round((entry - cmp_price) * qty, 2)

                # LOCK REAL TRADE IN MEMORY
                st.session_state.real_live_trades[clean_symbol] = {
                    "Time": signal_time,
                    "Symbol": clean_symbol,
                    "Type": trade_type,
                    "Qty": qty,
                    "Entry Price": entry,
                    "Stop Loss (SL)": sl,
                    "Target": target,
                    "CMP": cmp_price,
                    "Status": "LIVE 🟡",
                    "P&L (₹)": pnl
                }

        except Exception:
            continue

    if st.session_state.real_live_trades:
        return pd.DataFrame(list(st.session_state.real_live_trades.values()))
    return pd.DataFrame()

# -----------------------------------------------------------------------------
# DISPLAY DASHBOARD (EVERY 10 SECONDS REFRESH)
# -----------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_date = now_ist.strftime("%Y-%m-%d")
    current_time = now_ist.strftime("%H:%M:%S")

    market_active = is_market_open(now_ist)
    status_text = "🟢 SCANNING REAL LIVE MARKET" if market_active else "🔴 MARKET CLOSED (09:15-15:30 IST)"

    df_signals = run_live_scanner()

    if not df_signals.empty:
        total_trades = len(df_signals)
        live_trades = len(df_signals[df_signals["Status"].str.contains("LIVE")])
        targets_hit = len(df_signals[df_signals["Status"].str.contains("TARGET")])
        sl_hit = len(df_signals[df_signals["Status"].str.contains("SL HIT")])
        overall_pnl = round(df_signals["P&L (₹)"].sum(), 2)
    else:
        total_trades = 0
        live_trades = 0
        targets_hit = 0
        sl_hit = 0
        overall_pnl = 0.0

    pnl_color = "#4CAF50" if overall_pnl >= 0 else "#FF5252"

    st.markdown(f"""
        <div class="status-card">
            <b>Status:</b> {status_text} | <b>Date:</b> {current_date} | <b>Time:</b> {current_time}
        </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <div class="pnl-card">
            📊 <b>Cap:</b> ₹50k | <b>Active Signals:</b> {live_trades} | <b>Total Signals:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">₹{overall_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Pure Live Trade Signals")

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
        st.info("Abhi current LIVE market candle par koi Naya pullback signal nahi bana hai. Jaise hi signal banega yahan instantly lock ho jayega.")

render_dashboard()
