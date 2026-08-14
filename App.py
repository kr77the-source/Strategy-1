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
    page_title="20 EMA + VWAP Pullback Live Dashboard", layout="wide"
)

# -----------------------------------------------------------------------------
# CUSTOM CSS: CLEAN TOP PADDING & REMOVE OVERLAP
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

st.markdown("### 🎯 20 EMA + VWAP Pullback Dashboard")

# -----------------------------------------------------------------------------
# NIFTY 50 FULL WATCHLIST (50 STOCKS)
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
CAPITAL_PER_STOCK = TOTAL_CAPITAL / MAX_ACTIVE_TRADES  # ₹12,500 per trade

# -----------------------------------------------------------------------------
# MARKET HOURS CHECKER (09:15 AM to 03:30 PM IST)
# -----------------------------------------------------------------------------
def is_market_open(now_time):
    start_time = time(9, 15)
    end_time = time(15, 30)
    return start_time <= now_time.time() <= end_time

# -----------------------------------------------------------------------------
# TECHNICAL INDICATORS
# -----------------------------------------------------------------------------
def calculate_vwap(df):
    v = df['Volume'].values
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    return (tp * v).cumsum() / v.cumsum()

def calculate_atr(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

# -----------------------------------------------------------------------------
# SCANNING ENGINE WITH SLOTS CONTROL
# -----------------------------------------------------------------------------
def scan_nifty50_with_slots():
    all_signals = []
    active_trades_count = 0  # Dynamic tracker for active LIVE trades

    for symbol in NIFTY_50:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1d", interval="5m")

            if df.empty or len(df) < 25:
                continue

            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['VWAP'] = calculate_vwap(df)
            df['ATR14'] = calculate_atr(df, 14)

            opens = df["Open"].values
            closes = df["Close"].values
            highs = df["High"].values
            lows = df["Low"].values
            ema20 = df["EMA20"].values
            vwap = df["VWAP"].values
            atr14 = df["ATR14"].values
            timestamps = df.index

            for i in range(20, len(df)):
                curr_close = closes[i]
                curr_high = highs[i]
                curr_low = lows[i]
                curr_ema = ema20[i]
                curr_vwap = vwap[i]
                curr_atr = atr14[i]

                if np.isnan(curr_atr) or curr_atr == 0:
                    continue

                signal_time = timestamps[i].strftime("%H:%M")

                bullish_trend = curr_ema > curr_vwap
                long_pullback = bullish_trend and (curr_low <= curr_ema) and (curr_close > curr_ema) and (curr_close > curr_vwap)

                bearish_trend = curr_ema < curr_vwap
                short_pullback = bearish_trend and (curr_high >= curr_ema) and (curr_close < curr_ema) and (curr_close < curr_vwap)

                if long_pullback or short_pullback:
                    # Slot Control Check: Agar active trades pehle se 4 hain, to new trade hold hoga
                    if active_trades_count >= MAX_ACTIVE_TRADES:
                        break

                    trade_type = "BUY 🟢" if long_pullback else "SELL 🔴"
                    entry = round(float(curr_close), 2)

                    if long_pullback:
                        sl = round(float(entry - (1.5 * curr_atr)), 2)
                        risk = entry - sl
                        target = round(float(entry + (2.0 * risk)), 2)
                    else:
                        sl = round(float(entry + (1.5 * curr_atr)), 2)
                        risk = sl - entry
                        target = round(float(entry - (2.0 * risk)), 2)

                    qty = max(1, int(CAPITAL_PER_STOCK / entry))
                    cmp_price = round(float(closes[-1]), 2)
                    
                    final_status = "LIVE 🟡"
                    final_pnl = round((cmp_price - entry) * qty, 2) if long_pullback else round((entry - cmp_price) * qty, 2)

                    # Future Candle Checking for Exit
                    for j in range(i + 1, len(df)):
                        if long_pullback:
                            if lows[j] <= sl:
                                final_status = "SL HIT 🔴"
                                final_pnl = round((sl - entry) * qty, 2)
                                break
                            elif highs[j] >= target:
                                final_status = "TARGET 🟢"
                                final_pnl = round((target - entry) * qty, 2)
                                break
                        else:
                            if highs[j] >= sl:
                                final_status = "SL HIT 🔴"
                                final_pnl = round((entry - sl) * qty, 2)
                                break
                            elif lows[j] <= target:
                                final_status = "TARGET 🟢"
                                final_pnl = round((entry - target) * qty, 2)
                                break

                    # Agar trade LIVE hai, to counter badhega
                    if final_status == "LIVE 🟡":
                        active_trades_count += 1

                    all_signals.append({
                        "Time": signal_time,
                        "Symbol": symbol.replace(".NS", ""),
                        "Type": trade_type,
                        "Qty": qty,
                        "Entry Price": entry,
                        "Stop Loss (SL)": sl,
                        "Target": target,
                        "CMP": cmp_price,
                        "Status": final_status,
                        "P&L (₹)": final_pnl
                    })

                    # Single trade lock per stock
                    break

        except Exception:
            continue

    return pd.DataFrame(all_signals)

# -----------------------------------------------------------------------------
# DASHBOARD DISPLAY (AUTO REFRESH)
# -----------------------------------------------------------------------------
@st.fragment(run_every=10)
def render_dashboard():
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    current_date = now_ist.strftime("%Y-%m-%d")
    current_time = now_ist.strftime("%H:%M:%S")

    market_active = is_market_open(now_ist)
    status_text = "🟢 SCANNING (NIFTY 50)" if market_active else "🔴 MARKET CLOSED (09:15-15:30 IST)"

    df_signals = scan_nifty50_with_slots()

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
            📊 <b>Cap:</b> ₹50k | <b>Active:</b> {live_trades}/4 | <b>Total Trades:</b> {total_trades} | <b>Targets:</b> {targets_hit} | <b>SL:</b> {sl_hit} | <b>P&L:</b> <span style="color:{pnl_color}; font-weight:bold;">₹{overall_pnl}</span>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📋 Trades Log")

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
        st.info("Abhi tak koi valid trade setup nahi mila hai.")

render_dashboard()
